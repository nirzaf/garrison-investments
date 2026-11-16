"""Reconcile externally executed payments against the exact registered payroll export."""

import csv
import hashlib
import hmac
from collections import defaultdict
from decimal import Decimal
from io import StringIO
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import (
    HrPayrollClosure,
    HrPayrollExport,
    HrPayrollRun,
    HrPayrollSettlementEvent,
    HrPayslipPublication,
)
from app.models.user import User
from app.schemas.hr import (
    PayrollClosureRequest,
    PayrollClosureResponse,
    PayrollSettlementEventResponse,
    PayrollSettlementEventsResponse,
    PayrollSettlementLine,
    PayrollSettlementRequest,
    PayrollSettlementSummary,
)
from app.services.audit_service import AuditService
from app.services.hr_crypto import _derive_fernet_key, decrypt_hr_value, encrypt_hr_value
from app.services.hr_payroll_export import _ensure_export_access, _export_material, _verify_receipt
from app.services.hr_payroll_snapshot import _decimal, _locked_run, get_payroll_run
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.security import utc_now
from app.utils.time import business_today

ZERO = Decimal("0.00")
AMOUNT_LIMIT = Decimal("9999999999999999.99")


async def _payment_material(
    session: AsyncSession, run: HrPayrollRun, *, allow_zero: bool = False
) -> tuple[str, str, dict[UUID, Decimal]]:
    receipt = await session.get(HrPayrollExport, run.id)
    if receipt is None and not allow_zero:
        raise NotFoundException("Registered payroll export")
    preview, content = await _export_material(session, run)
    if receipt is None:
        if preview.payment_count != 0:
            raise NotFoundException("Registered payroll export")
        return preview.csv_sha256, preview.currency, {}
    _verify_receipt(receipt, preview)
    rows = csv.DictReader(StringIO(content.decode()))
    expected = {UUID(row["payment_reference"]): Decimal(row["net_amount"]) for row in rows}
    return receipt.csv_sha256, preview.currency, expected


def _amount(event: HrPayrollSettlementEvent) -> Decimal:
    return _decimal(decrypt_hr_value(event.amount_encrypted), places=2, maximum=AMOUNT_LIMIT)


def _event_response(event: HrPayrollSettlementEvent) -> PayrollSettlementEventResponse:
    evidence = decrypt_hr_value(event.evidence_encrypted)
    if not evidence or event.kind not in {"paid", "failed", "reversed"}:
        raise AppException("A stored settlement event is invalid.", status_code=409)
    return PayrollSettlementEventResponse(
        id=event.id,
        run_id=event.run_id,
        payment_reference=event.payment_reference,
        kind=cast(Literal["paid", "failed", "reversed"], event.kind),
        amount=_amount(event),
        occurred_on=event.occurred_on,
        evidence_reference=evidence,
        reverses_event_id=event.reverses_event_id,
        recorded_at=event.recorded_at,
    )


def _settled_amount(events: list[HrPayrollSettlementEvent]) -> Decimal:
    return sum((_amount(event) for event in events if event.kind == "paid"), ZERO) - sum(
        (_amount(event) for event in events if event.kind == "reversed"), ZERO
    )


async def summarize_payroll_settlements(
    session: AsyncSession, run_id: UUID, actor: User
) -> PayrollSettlementSummary:
    _ensure_export_access(actor)
    run = await get_payroll_run(session, run_id)
    result = await _settlement_state(session, run)
    await _settlement_read_audit(session, run_id, actor)
    return result


async def _settlement_state(session: AsyncSession, run: HrPayrollRun) -> PayrollSettlementSummary:
    csv_sha256, currency, expected = await _payment_material(session, run, allow_zero=True)
    closure = await session.get(HrPayrollClosure, run.id)
    rows = list(await session.scalars(
        select(HrPayrollSettlementEvent)
        .where(HrPayrollSettlementEvent.run_id == run.id)
        .order_by(HrPayrollSettlementEvent.id)
    ))
    event_by_payment: dict[UUID, list[HrPayrollSettlementEvent]] = defaultdict(list)
    for event in rows:
        if event.payment_reference not in expected:
            raise AppException("Settlement references a missing exported payment.", status_code=409)
        event_by_payment[event.payment_reference].append(event)
    payments = []
    status: Literal["pending", "failed", "partial", "settled", "reversed"]
    for reference, owed in expected.items():
        events = event_by_payment[reference]
        paid = _settled_amount(events)
        if not ZERO <= paid <= owed:
            raise AppException(
                "Recorded settlements do not balance with the export.", status_code=409
            )
        if paid == owed:
            status = "settled"
        elif paid:
            status = "partial"
        elif any(event.kind == "reversed" for event in events):
            status = "reversed"
        elif events:
            status = "failed"
        else:
            status = "pending"
        payments.append(
            PayrollSettlementLine(
                payment_reference=reference,
                expected=owed,
                net_paid=paid,
                outstanding=owed - paid,
                status=status,
            )
        )
    owed_total = sum((payment.expected for payment in payments), ZERO)
    paid_total = sum((payment.net_paid for payment in payments), ZERO)
    digest = hashlib.sha256()
    digest.update(bytes.fromhex(csv_sha256))
    for row in rows:
        # Events are append-only. The ordered IDs bind a read to the reviewed event set.
        digest.update(row.id.bytes)
    return PayrollSettlementSummary(
        run_id=run.id,
        csv_sha256=csv_sha256,
        currency=currency,
        expected=owed_total,
        net_paid=paid_total,
        outstanding=owed_total - paid_total,
        fully_reconciled=owed_total == paid_total,
        settlement_digest=digest.hexdigest(),
        closure=PayrollClosureResponse.model_validate(closure) if closure is not None else None,
        payments=payments,
    )


async def close_payroll_period(
    session: AsyncSession, run_id: UUID, payload: PayrollClosureRequest, actor: User
) -> PayrollClosureResponse:
    _ensure_export_access(actor)
    run, _ = await _locked_run(session, run_id)
    if run.prepared_by_id is None or actor.id == run.prepared_by_id:
        raise PermissionDeniedException("independent payroll closure")
    if run.snapshot_digest != payload.expected_snapshot_digest:
        raise AppException("Confirm the approved payroll snapshot.", status_code=409)
    publication = await session.get(HrPayslipPublication, run_id)
    if publication is None or publication.snapshot_digest != payload.expected_snapshot_digest:
        raise AppException("Publish the approved payslips before closure.", status_code=409)
    try:
        current = await _settlement_state(session, run)
    except NotFoundException as exc:
        raise AppException("Register the payroll export before closure.", status_code=409) from exc
    if (
        current.csv_sha256 != payload.expected_csv_sha256
        or current.settlement_digest != payload.expected_settlement_digest
    ):
        raise AppException(
            "Review the current settlement evidence before closure.", status_code=409
        )
    if not current.fully_reconciled:
        raise AppException("Resolve outstanding payroll payments before closure.", status_code=409)
    if current.closure is not None:
        return current.closure
    closure = HrPayrollClosure(
        run_id=run_id,
        closed_by_id=actor.id,
        snapshot_digest=payload.expected_snapshot_digest,
        csv_sha256=current.csv_sha256,
        settlement_digest=current.settlement_digest,
        closed_at=utc_now(),
    )
    session.add(closure)
    await AuditService(session).record(
        action="hr.payroll_period.closed",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run_id,
        new_values={"settlement_digest": current.settlement_digest},
    )
    await session.commit()
    return PayrollClosureResponse.model_validate(closure)


async def _settlement_read_audit(session: AsyncSession, run_id: UUID, actor: User) -> None:
    await AuditService(session).record(
        action="hr.payroll_settlement.viewed",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run_id,
    )
    await session.commit()


async def list_payroll_settlement_events(
    session: AsyncSession,
    run_id: UUID,
    actor: User,
    *,
    limit: int,
    offset: int,
    payment_reference: UUID | None,
) -> PayrollSettlementEventsResponse:
    _ensure_export_access(actor)
    run = await get_payroll_run(session, run_id)
    _, _, expected = await _payment_material(session, run)
    query = select(HrPayrollSettlementEvent).where(HrPayrollSettlementEvent.run_id == run_id)
    if payment_reference is not None:
        if payment_reference not in expected:
            raise NotFoundException("Exported payroll payment")
        query = query.where(HrPayrollSettlementEvent.payment_reference == payment_reference)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(
            HrPayrollSettlementEvent.recorded_at.desc(), HrPayrollSettlementEvent.id.desc()
        )
        .limit(limit)
        .offset(offset)
    )
    result = PayrollSettlementEventsResponse(
        items=[_event_response(row) for row in rows], total=total or 0
    )
    await _settlement_read_audit(session, run_id, actor)
    return result


async def read_payroll_settlement_event(
    session: AsyncSession, run_id: UUID, event_id: UUID, actor: User
) -> PayrollSettlementEventResponse:
    _ensure_export_access(actor)
    event = await session.get(HrPayrollSettlementEvent, event_id)
    if event is None or event.run_id != run_id:
        raise NotFoundException("Payroll settlement event")
    run = await get_payroll_run(session, run_id)
    await _payment_material(session, run)
    result = _event_response(event)
    await _settlement_read_audit(session, run_id, actor)
    return result


async def record_payroll_settlement(
    session: AsyncSession, run_id: UUID, payload: PayrollSettlementRequest, actor: User
) -> PayrollSettlementEventResponse:
    _ensure_export_access(actor)
    run, _ = await _locked_run(session, run_id)
    csv_sha256, _, expected = await _payment_material(session, run)
    if csv_sha256 != payload.expected_csv_sha256:
        raise AppException("Confirm the registered export digest.", status_code=409)
    owed = expected.get(payload.payment_reference)
    if owed is None:
        raise NotFoundException("Exported payroll payment")
    amount = Decimal(payload.amount).quantize(Decimal("0.01"))
    evidence_digest = hmac.digest(
        _derive_fernet_key(),
        b"hr.payroll.settlement:" + payload.evidence_reference.encode(),
        "sha256",
    ).hex()
    existing = await session.get(HrPayrollSettlementEvent, payload.event_id)
    if existing is not None:
        if (
            existing.run_id == run_id
            and existing.payment_reference == payload.payment_reference
            and existing.kind == payload.kind
            and _amount(existing) == amount
            and existing.reverses_event_id == payload.reverses_event_id
            and existing.evidence_digest == evidence_digest
            and existing.occurred_on == payload.occurred_on
        ):
            return _event_response(existing)
        raise AppException(
            "The settlement event ID already refers to another record.", status_code=409
        )
    if await session.get(HrPayrollClosure, run_id) is not None:
        raise AppException("The payroll period is closed.", status_code=409)
    if payload.occurred_on > business_today():
        raise AppException("Settlement cannot be recorded for a future date.", status_code=422)

    events = list(
        await session.scalars(
            select(HrPayrollSettlementEvent).where(
                HrPayrollSettlementEvent.run_id == run_id,
                HrPayrollSettlementEvent.payment_reference == payload.payment_reference,
            )
        )
    )
    paid = _settled_amount(events)
    if not ZERO <= paid <= owed:
        raise AppException("Recorded settlements do not balance with the export.", status_code=409)
    if payload.kind == "paid" and amount > owed - paid:
        raise AppException("The payment exceeds the outstanding amount.", status_code=409)
    if payload.kind == "reversed":
        original = next((event for event in events if event.id == payload.reverses_event_id), None)
        if original is None or original.kind != "paid":
            raise NotFoundException("Original payroll payment event")
        previously_reversed = sum(
            (_amount(event) for event in events if event.reverses_event_id == original.id), ZERO
        )
        if amount > min(paid, _amount(original) - previously_reversed):
            raise AppException("The reversal exceeds the unreversed payment.", status_code=409)
        if payload.occurred_on < original.occurred_on:
            raise AppException("A reversal cannot precede the payment.", status_code=422)

    row = HrPayrollSettlementEvent(
        id=payload.event_id,
        run_id=run_id,
        payment_reference=payload.payment_reference,
        kind=payload.kind,
        amount_encrypted=encrypt_hr_value(str(amount)),
        reverses_event_id=payload.reverses_event_id,
        occurred_on=payload.occurred_on,
        evidence_encrypted=encrypt_hr_value(payload.evidence_reference),
        evidence_digest=evidence_digest,
        recorded_by_id=actor.id,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppException(
            "This settlement event or evidence reference is already recorded.", status_code=409
        ) from exc
    await AuditService(session).record(
        action=f"hr.payroll_settlement.{row.kind}",
        user_id=actor.id,
        entity_type="hr_payroll_settlement_events",
        entity_id=row.id,
        new_values={"run_id": str(run_id), "payment_reference": str(row.payment_reference)},
    )
    await session.commit()
    return _event_response(row)
