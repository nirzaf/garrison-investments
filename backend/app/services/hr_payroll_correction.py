"""Preserve independent corrections to closed payroll without changing posted history."""

import hashlib
import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.hr import HrPayrollClosure, HrPayrollCorrection, HrPayrollLine, HrPayrollRun
from app.models.user import User
from app.schemas.hr import (
    PayrollCorrectionAmounts,
    PayrollCorrectionCreate,
    PayrollCorrectionDecision,
    PayrollCorrectionPage,
    PayrollCorrectionResponse,
)
from app.services.audit_service import AuditService
from app.services.hr_crypto import decrypt_hr_value, encrypt_hr_value
from app.services.hr_payroll_snapshot import (
    MAX_AMOUNT,
    _decimal,
    _line_amounts,
    _locked_run,
    _stored_snapshot,
    get_payroll_run,
)
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_PAYROLL_APPROVE,
    PERMISSION_HR_PAYROLL_PREPARE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    ensure_permission,
)
from app.utils.security import utc_now


async def _closed_line(
    session: AsyncSession, run: HrPayrollRun, line_id: UUID
) -> tuple[HrPayrollLine, str]:
    closure = await session.get(HrPayrollClosure, run.id)
    if closure is None or closure.snapshot_digest != run.snapshot_digest:
        raise AppException("Corrections require a confirmed closed payroll run.", status_code=409)
    snapshot, lines = await _stored_snapshot(session, run)
    line = next((entry for entry in lines if entry.id == line_id), None)
    if line is None:
        raise NotFoundException("Closed payroll line")
    return line, str(snapshot["currency"])


def _response(row: HrPayrollCorrection) -> PayrollCorrectionResponse:
    details = json.loads(decrypt_hr_value(row.detail_encrypted) or "")
    baseline = PayrollCorrectionAmounts.model_validate(details["baseline"])
    proposed = PayrollCorrectionAmounts.model_validate(details["proposed"])
    return PayrollCorrectionResponse(
        id=row.id,
        line_id=row.line_id,
        previous_id=row.previous_id,
        snapshot_digest=row.snapshot_digest,
        digest=hashlib.sha256(row.detail_encrypted.encode()).hexdigest(),
        status=row.status,
        currency=details["currency"],
        baseline=baseline,
        proposed=proposed,
        net_delta=proposed.net - baseline.net,
        evidence_reference=details["evidence_reference"],
        submitted_by_id=row.submitted_by_id,
        decided_by_id=row.decided_by_id,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


def _history(line_id: UUID) -> Select[HrPayrollCorrection]:
    return (
        select(HrPayrollCorrection)
        .where(HrPayrollCorrection.line_id == line_id)
        .order_by(HrPayrollCorrection.created_at.desc(), HrPayrollCorrection.id.desc())
    )


async def _latest_approved(session: AsyncSession, line_id: UUID) -> HrPayrollCorrection | None:
    successor = aliased(HrPayrollCorrection)
    current = list(await session.scalars(
        _history(line_id).where(
            HrPayrollCorrection.status == "approved",
            ~select(successor.id).where(
                successor.line_id == line_id,
                successor.previous_id == HrPayrollCorrection.id,
                successor.status == "approved",
            ).exists(),
        ).limit(2)
    ))
    if len(current) > 1:
        raise AppException("Payroll correction history requires reconciliation.", status_code=409)
    return current[0] if current else None


async def _audit(
    session: AsyncSession, run_id: UUID, actor: User, action: str, row_id: UUID | None = None
) -> None:
    await AuditService(session).record(
        action=f"hr.payroll_correction.{action}",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run_id,
        new_values={"correction_id": str(row_id)} if row_id else None,
    )
    await session.commit()


async def list_payroll_corrections(
    session: AsyncSession,
    run_id: UUID,
    line_id: UUID,
    actor: User,
    *,
    limit: int,
    offset: int,
) -> PayrollCorrectionPage:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    run = await get_payroll_run(session, run_id)
    line, currency = await _closed_line(session, run, line_id)
    latest = await _latest_approved(session, line_id)
    total = await session.scalar(
        select(func.count()).select_from(HrPayrollCorrection)
        .where(HrPayrollCorrection.line_id == line_id)
    )
    rows = await session.scalars(_history(line_id).offset(offset).limit(limit))
    result = PayrollCorrectionPage(
        line_id=line_id,
        currency=currency,
        current_correction_id=latest.id if latest else None,
        baseline=(
            _response(latest).proposed if latest
            else PayrollCorrectionAmounts(**_line_amounts(line))
        ),
        total=total or 0,
        items=[_response(row) for row in rows],
    )
    await _audit(session, run_id, actor, "viewed")
    return result


async def read_payroll_correction(
    session: AsyncSession, run_id: UUID, line_id: UUID, correction_id: UUID, actor: User
) -> PayrollCorrectionResponse:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    run = await get_payroll_run(session, run_id)
    await _closed_line(session, run, line_id)
    row = await session.get(HrPayrollCorrection, correction_id)
    if row is None or row.line_id != line_id or row.snapshot_digest != run.snapshot_digest:
        raise NotFoundException("Payroll correction")
    result = _response(row)
    await _audit(session, run_id, actor, "viewed", correction_id)
    return result


def _proposed_amounts(gross: Decimal, deductions: Decimal) -> PayrollCorrectionAmounts:
    if deductions > gross:
        raise AppException("Corrected deductions cannot exceed gross.", status_code=422)
    return PayrollCorrectionAmounts(gross=gross, deductions=deductions, net=gross - deductions)


async def propose_payroll_correction(
    session: AsyncSession,
    run_id: UUID,
    line_id: UUID,
    payload: PayrollCorrectionCreate,
    actor: User,
) -> PayrollCorrectionResponse:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_PREPARE)
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    run, _ = await _locked_run(session, run_id)
    line, currency = await _closed_line(session, run, line_id)
    if run.snapshot_digest != payload.expected_snapshot_digest:
        raise AppException("Confirm the original closed payroll snapshot.", status_code=409)
    proposed = _proposed_amounts(
        _decimal(payload.gross, places=2, maximum=MAX_AMOUNT),
        _decimal(payload.deductions, places=2, maximum=MAX_AMOUNT),
    )
    existing = await session.get(HrPayrollCorrection, payload.correction_id)
    if existing is not None:
        if existing.line_id == line_id and existing.submitted_by_id == actor.id:
            previous = _response(existing)
            if (
                previous.snapshot_digest == payload.expected_snapshot_digest
                and previous.previous_id == payload.expected_previous_id
                and previous.proposed == proposed
                and previous.evidence_reference == payload.evidence_reference
            ):
                return previous
        raise AppException("The correction ID already refers to another proposal.", status_code=409)
    latest = await _latest_approved(session, line_id)
    previous_id = latest.id if latest else None
    if previous_id != payload.expected_previous_id:
        raise AppException("Review the current payroll correction baseline.", status_code=409)
    if await session.scalar(
        select(HrPayrollCorrection.id)
        .where(HrPayrollCorrection.line_id == line_id, HrPayrollCorrection.status == "submitted")
        .limit(1)
    ):
        raise AppException("Resolve the existing correction proposal first.", status_code=409)
    baseline = (
        _response(latest).proposed if latest
        else PayrollCorrectionAmounts(**_line_amounts(line))
    )
    if proposed == baseline:
        raise AppException("Enter changed amounts for the correction.", status_code=422)
    detail = encrypt_hr_value(json.dumps({
        "currency": currency,
        "baseline": baseline.model_dump(mode="json"),
        "proposed": proposed.model_dump(mode="json"),
        "evidence_reference": payload.evidence_reference,
    }))
    assert detail is not None
    row = await session.scalar(
        insert(HrPayrollCorrection)
        .values(
            id=payload.correction_id,
            line_id=line_id,
            previous_id=previous_id,
            snapshot_digest=payload.expected_snapshot_digest,
            detail_encrypted=detail,
            submitted_by_id=actor.id,
        )
        .on_conflict_do_nothing(index_elements=[HrPayrollCorrection.id])
        .returning(HrPayrollCorrection)
    )
    if row is None:
        raise AppException("The correction ID already refers to another proposal.", status_code=409)
    result = _response(row)
    await _audit(session, run_id, actor, "submitted", row.id)
    return result


async def decide_payroll_correction(
    session: AsyncSession,
    run_id: UUID,
    line_id: UUID,
    correction_id: UUID,
    payload: PayrollCorrectionDecision,
    actor: User,
) -> PayrollCorrectionResponse:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    run, _ = await _locked_run(session, run_id)
    await _closed_line(session, run, line_id)
    row = await session.get(HrPayrollCorrection, correction_id)
    if row is None or row.line_id != line_id:
        raise NotFoundException("Payroll correction")
    if actor.id == row.submitted_by_id:
        raise PermissionDeniedException("independent payroll correction review")
    reviewed = _response(row)
    if reviewed.digest != payload.expected_digest or row.snapshot_digest != run.snapshot_digest:
        raise AppException("Confirm the exact correction proposal.", status_code=409)
    if row.status == payload.decision and row.decided_by_id == actor.id:
        return reviewed
    if row.status != "submitted":
        raise AppException("The correction already has a final decision.", status_code=409)
    latest = await _latest_approved(session, line_id)
    if (latest.id if latest else None) != row.previous_id:
        raise AppException("The correction baseline has changed.", status_code=409)
    row.status = payload.decision
    row.decided_by_id = actor.id
    row.decided_at = utc_now()
    result = _response(row)
    await _audit(session, run_id, actor, payload.decision, row.id)
    return result
