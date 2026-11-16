"""Freeze the supported payroll calculation and approve the exact reviewed snapshot."""

import hashlib
import json
from calendar import monthrange
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import (
    HrCompensationTerm,
    HrEmployee,
    HrEmploymentPeriod,
    HrPayrollAdjustment,
    HrPayrollClosure,
    HrPayrollLine,
    HrPayrollPeriod,
    HrPayrollPolicy,
    HrPayrollRun,
    HrPayslipPublication,
)
from app.models.user import User
from app.schemas.hr import (
    PayrollAdjustmentCreate,
    PayrollAdjustmentDetail,
    PayrollAdjustmentList,
    PayrollAdjustmentResponse,
    PayrollAdjustmentReview,
    PayrollControlledPolicyRecord,
    PayrollFrozenSources,
    PayrollRunSnapshotResponse,
    PayrollSnapshotLine,
    PayrollSourceEvidenceRequest,
    PayslipDetail,
    PayslipListResponse,
    PayslipSummary,
)
from app.services.audit_service import AuditService
from app.services.hr_crypto import decrypt_hr_value, encrypt_hr_value
from app.services.hr_leave_accrual import _eligible_category
from app.services.hr_payroll_time import (
    reconcile_payroll_leave_inputs,
    reconcile_payroll_time_inputs,
)
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_PAYROLL_APPROVE,
    PERMISSION_HR_PAYROLL_PREPARE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    ensure_permission,
    has_permission,
)
from app.utils.security import utc_now
from app.utils.time import business_today

CENTS = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999999999.99")
ADJUSTED_BASIS = "base_salary_with_reviewed_adjustments"
ROUNDING = {"half_even": ROUND_HALF_EVEN, "half_up": ROUND_HALF_UP}
RULES = {"calculation_basis", "currency", "rounding", "pay_frequency", "employee_deduction_rate"}


async def lock_payroll_periods(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('garrison.hr_payroll_periods'))")
    )


def _decimal(raw: Any, *, places: int, maximum: Decimal) -> Decimal:
    try:
        if not isinstance(raw, str) or len(raw) > 40:
            raise ValueError
        number = Decimal(raw)
        if not number.is_finite() or number < 0 or number > maximum:
            raise ValueError
        normalized = number.quantize(Decimal(1).scaleb(-places))
        if number != normalized:
            raise ValueError
        return normalized
    except (ValueError, InvalidOperation) as exc:
        raise AppException("The payroll amount or rate is invalid.", status_code=422) from exc


def _policy_rules(policy: HrPayrollPolicy) -> tuple[str, str, Decimal]:
    if (
        not policy.is_approved
        or policy.approved_by_id is None
        or policy.second_approved_by_id is None
        or policy.approved_by_id == policy.second_approved_by_id
        or policy.approved_at is None
    ):
        raise AppException(
            "Payroll requires a policy with two distinct approving actors.",
            status_code=409,
            error_code="POLICY_NOT_APPROVED",
        )
    return validate_payroll_policy(policy)


def validate_payroll_rules(rules: dict[str, Any]) -> tuple[str, str, Decimal]:
    currency, rounding = rules.get("currency"), rules.get("rounding")
    if (
        set(rules) != RULES
        or rules.get("pay_frequency") != "monthly"
        or rules.get("calculation_basis") not in ("base_salary_only", ADJUSTED_BASIS)
        or not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or not currency.isupper()
        or not isinstance(rounding, str)
        or rounding not in ROUNDING
    ):
        raise AppException(
            "The approved policy is outside the supported monthly calculation.",
            status_code=422,
        )
    limit = Decimal("1")
    rate = _decimal(rules["employee_deduction_rate"], places=8, maximum=limit)
    return currency, rounding, rate


def _payroll_amounts(
    base: Decimal, rate: Decimal, rounding: str, earnings: Decimal, extra_deductions: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    gross = base + earnings
    deductions = (base * rate).quantize(CENTS, rounding=ROUNDING[rounding]) + extra_deductions
    if gross > MAX_AMOUNT or deductions > gross:
        raise AppException("Adjustments put gross or net outside payroll limits.", status_code=422)
    return gross, deductions, gross - deductions


def validate_payroll_policy(policy: HrPayrollPolicy) -> tuple[str, str, Decimal]:
    currency, rounding, rate = validate_payroll_rules(policy.rules_json)
    if policy.controlled_record is not None:
        record = PayrollControlledPolicyRecord.model_validate(policy.controlled_record)
        for position, example in enumerate(record.worked_examples, start=1):
            if policy.rules_json["calculation_basis"] != ADJUSTED_BASIS and (
                example.earnings or example.extra_deductions
            ):
                raise AppException(
                    f"Worked example {position} includes adjustments outside this policy.",
                    status_code=422,
                    error_code="PAYROLL_EXAMPLE_MISMATCH",
                )
            amounts = _payroll_amounts(
                example.base_salary, rate, rounding, example.earnings, example.extra_deductions
            )
            expected = (example.expected_gross, example.expected_deductions, example.expected_net)
            if amounts != expected:
                raise AppException(
                    f"Worked example {position} differs from the payroll calculation.",
                    status_code=422,
                    error_code="PAYROLL_EXAMPLE_MISMATCH",
                )
    return currency, rounding, rate


async def get_payroll_run(session: AsyncSession, run_id: UUID) -> HrPayrollRun:
    run = await session.get(HrPayrollRun, run_id)
    if run is None:
        raise NotFoundException("Payroll run")
    return run


async def _locked_run(session: AsyncSession, run_id: UUID) -> tuple[HrPayrollRun, HrPayrollPeriod]:
    period = await session.scalar(
        select(HrPayrollPeriod)
        .join(HrPayrollRun, HrPayrollRun.payroll_period_id == HrPayrollPeriod.id)
        .where(HrPayrollRun.id == run_id)
        .with_for_update(of=HrPayrollPeriod)
    )
    if period is None:
        raise NotFoundException("Payroll run")
    run = await session.scalar(
        select(HrPayrollRun).where(HrPayrollRun.id == run_id).with_for_update()
    )
    if run is None:
        raise NotFoundException("Payroll run")
    return run, period


def _adjustment_response(row: HrPayrollAdjustment) -> PayrollAdjustmentResponse:
    detail = PayrollAdjustmentDetail.model_validate_json(
        decrypt_hr_value(row.detail_encrypted) or ""
    )
    return PayrollAdjustmentResponse(
        **detail.model_dump(),
        id=row.id,
        employee_id=row.employee_id,
        status=row.status,
        submitted_by_id=row.submitted_by_id,
        decided_by_id=row.decided_by_id,
        decided_at=row.decided_at,
        digest=hashlib.sha256(row.detail_encrypted.encode()).hexdigest(),
    )


async def _adjustments(session: AsyncSession, run_id: UUID) -> list[HrPayrollAdjustment]:
    return list(
        await session.scalars(
            select(HrPayrollAdjustment)
            .where(HrPayrollAdjustment.run_id == run_id)
            .order_by(HrPayrollAdjustment.id)
        )
    )


async def _audit_adjustment(
    session: AsyncSession, action: str, run_id: UUID, actor: User, adjustment_id: UUID | None = None
) -> None:
    await AuditService(session).record(
        action=f"hr.payroll_adjustment.{action}",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run_id,
        new_values={"adjustment_id": str(adjustment_id)} if adjustment_id else None,
    )
    await session.commit()


async def read_payroll_adjustments(
    session: AsyncSession, run_id: UUID, actor: User
) -> PayrollAdjustmentList:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    run = await get_payroll_run(session, run_id)
    period = await session.get(HrPayrollPeriod, run.payroll_period_id)
    policy = await session.get(HrPayrollPolicy, run.policy_id) if run.policy_id else None
    editable = bool(
        run.status == "draft"
        and run.snapshot_encrypted is None
        and period is not None and period.status == "open"
        and policy is not None and policy.is_approved
        and policy.rules_json.get("calculation_basis") == ADJUSTED_BASIS
    )
    result = PayrollAdjustmentList(
        run_id=run_id,
        can_submit=editable and actor.id == run.prepared_by_id
        and has_permission(actor, PERMISSION_HR_PAYROLL_PREPARE),
        can_review=editable and actor.id != run.prepared_by_id
        and has_permission(actor, PERMISSION_HR_PAYROLL_APPROVE),
        items=[_adjustment_response(row) for row in await _adjustments(session, run_id)],
    )
    await _audit_adjustment(session, "viewed", run_id, actor)
    return result


def _ensure_adjustable(run: HrPayrollRun, period: HrPayrollPeriod) -> None:
    if run.status != "draft" or run.snapshot_encrypted is not None or period.status != "open":
        raise AppException("Adjust only a draft run in an open payroll period.", status_code=409)


async def submit_payroll_adjustment(
    session: AsyncSession, run_id: UUID, payload: PayrollAdjustmentCreate, actor: User
) -> PayrollAdjustmentResponse:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_PREPARE)
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    run, period = await _locked_run(session, run_id)
    if actor.id != run.prepared_by_id:
        raise PermissionDeniedException("submit an adjustment for this payroll run")
    amount = _decimal(payload.amount, places=2, maximum=MAX_AMOUNT)
    if amount <= 0:
        raise AppException("Enter a positive adjustment amount.", status_code=422)
    detail = PayrollAdjustmentDetail(
        kind=payload.kind, amount=str(amount), evidence_reference=payload.evidence_reference
    )
    existing = await session.get(HrPayrollAdjustment, payload.adjustment_id)
    if existing is not None:
        if existing.run_id == run_id and existing.employee_id == payload.employee_id:
            prior = _adjustment_response(existing)
            if (prior.kind, prior.amount, prior.evidence_reference) == (
                detail.kind, detail.amount, detail.evidence_reference,
            ):
                return prior
        raise AppException("The adjustment ID already refers to another record.", status_code=409)
    _ensure_adjustable(run, period)
    policy = await session.get(HrPayrollPolicy, run.policy_id) if run.policy_id else None
    if policy is None or policy.rules_json.get("calculation_basis") != ADJUSTED_BASIS:
        raise AppException("Select an approved policy that permits adjustments.", status_code=409)
    _policy_rules(policy)
    employee = await session.get(HrEmployee, payload.employee_id)
    if employee is None or employee.deleted_at is not None:
        raise NotFoundException("Payroll roster employee")
    await _eligible_category(session, employee, period.period_start, period.period_end)
    adjustments = await _adjustments(session, run_id)
    if len(adjustments) >= 5000:
        raise AppException("This run has reached the adjustment limit.", status_code=409)
    for row in adjustments:
        if row.employee_id == employee.id and row.status != "rejected":
            previous = _adjustment_response(row)
            if (previous.kind, previous.evidence_reference) == (
                detail.kind, detail.evidence_reference
            ):
                raise AppException("This evidence already supports an adjustment.", status_code=409)
    encrypted = encrypt_hr_value(detail.model_dump_json())
    assert encrypted is not None
    result = await session.scalar(
        insert(HrPayrollAdjustment)
        .values(
            id=payload.adjustment_id,
            run_id=run_id,
            employee_id=employee.id,
            submitted_by_id=actor.id,
            detail_encrypted=encrypted,
        )
        .on_conflict_do_nothing(index_elements=[HrPayrollAdjustment.id])
        .returning(HrPayrollAdjustment)
    )
    if result is None:
        raise AppException("The adjustment ID already refers to another record.", status_code=409)
    response = _adjustment_response(result)
    await _audit_adjustment(session, "submitted", run_id, actor, result.id)
    return response


async def review_payroll_adjustment(
    session: AsyncSession, run_id: UUID, adjustment_id: UUID,
    payload: PayrollAdjustmentReview, actor: User,
) -> PayrollAdjustmentResponse:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    run, period = await _locked_run(session, run_id)
    row = await session.get(HrPayrollAdjustment, adjustment_id)
    if row is None or row.run_id != run_id:
        raise NotFoundException("Payroll adjustment")
    if actor.id in (row.submitted_by_id, run.prepared_by_id):
        raise PermissionDeniedException("independent payroll adjustment review")
    previous = _adjustment_response(row)
    if previous.digest != payload.expected_digest:
        raise AppException("Confirm the reviewed adjustment digest.", status_code=409)
    if row.status == payload.decision and row.decided_by_id == actor.id:
        return previous
    _ensure_adjustable(run, period)
    if row.status != "submitted":
        raise AppException("This adjustment already has a final decision.", status_code=409)
    row.status = payload.decision
    row.decided_by_id = actor.id
    row.decided_at = utc_now()
    result = _adjustment_response(row)
    await _audit_adjustment(session, payload.decision, run_id, actor, row.id)
    return result


async def _source_terms(
    session: AsyncSession, roster: list[UUID], period: HrPayrollPeriod, currency: str
) -> list[HrCompensationTerm]:
    employees = list(
        await session.scalars(
            select(HrEmployee)
            .where(HrEmployee.id.in_(roster), HrEmployee.deleted_at.is_(None))
            .order_by(HrEmployee.id)
            .with_for_update()
        )
    )
    if len(employees) != len(roster):
        raise NotFoundException("Payroll roster employee")
    for employee in employees:
        try:
            await _eligible_category(session, employee, period.period_start, period.period_end)
        except AppException as exc:
            raise AppException(
                "A roster employee lacks complete eligible employment history.", status_code=409
            ) from exc
    candidates = list(
        await session.scalars(
            select(HrCompensationTerm)
            .where(
                HrCompensationTerm.employee_id.in_(roster),
                HrCompensationTerm.approval_status == "approved",
                HrCompensationTerm.effective_from <= period.period_end,
                ~select(HrEmploymentPeriod.id)
                .where(
                    HrEmploymentPeriod.employee_id == HrCompensationTerm.employee_id,
                    HrEmploymentPeriod.ended_on.is_(None),
                    HrEmploymentPeriod.rehire_change_id.is_not(None),
                    HrCompensationTerm.effective_from < HrEmploymentPeriod.started_on,
                )
                .exists(),
            )
            .order_by(HrCompensationTerm.effective_from.desc(), HrCompensationTerm.id)
        )
    )
    latest: dict[UUID, HrCompensationTerm] = {}
    for term in candidates:
        previous = latest.setdefault(term.employee_id, term)
        if previous.id != term.id and previous.effective_from == term.effective_from:
            raise AppException("Payroll has ambiguous compensation terms.", status_code=409)
    if len(latest) != len(roster) or any(
        row.effective_from > period.period_start
        or row.approved_by_id is None
        or row.approved_at is None
        or row.currency != currency
        or row.pay_frequency != "monthly"
        or row.allowances_encrypted is not None
        for row in latest.values()
    ):
        raise AppException(
            "Each employee needs one approved whole-period monthly term in the policy currency "
            "without unhandled allowances.",
            status_code=409,
        )
    return [latest[employee_id] for employee_id in roster]


def _line_hash(lines: list[HrPayrollLine]) -> str:
    values = sorted(
        (str(line.employee_id), line.gross_encrypted, line.deductions_encrypted, line.net_encrypted)
        for line in lines
    )
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


async def _stored_snapshot(
    session: AsyncSession, run: HrPayrollRun
) -> tuple[dict[str, Any], list[HrPayrollLine]]:
    raw = decrypt_hr_value(run.snapshot_encrypted)
    if raw is None:
        raise AppException("This run has no reviewable payroll snapshot.", status_code=409)
    snapshot = json.loads(raw)
    lines = list(
        await session.scalars(
            select(HrPayrollLine)
            .where(HrPayrollLine.payroll_run_id == run.id)
            .order_by(HrPayrollLine.employee_id, HrPayrollLine.id)
        )
    )
    if (
        snapshot.get("run_id") != str(run.id)
        or snapshot.get("period_id") != str(run.payroll_period_id)
        or snapshot.get("policy_id") != str(run.policy_id)
        or snapshot.get("line_hash") != _line_hash(lines)
        or [str(line.employee_id) for line in lines] != sorted(snapshot["terms"])
    ):
        raise AppException(
            "The stored payroll lines differ from the frozen snapshot.", status_code=409
        )
    return snapshot, lines


async def calculate_payroll_snapshot(
    session: AsyncSession,
    run_id: UUID,
    employee_ids: list[UUID],
    actor: User,
    *,
    source_evidence: PayrollSourceEvidenceRequest | None = None,
) -> HrPayrollRun:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_PREPARE)
    run, period = await _locked_run(session, run_id)
    if run.prepared_by_id != actor.id:
        raise PermissionDeniedException("prepare this payroll run")
    roster = sorted(employee_ids)
    if len(roster) != len(set(roster)) or not roster:
        raise AppException("Enter a nonempty payroll roster without duplicates.", status_code=422)
    if run.snapshot_encrypted is not None:
        snapshot, _ = await _stored_snapshot(session, run)
        if sorted(snapshot["terms"]) != [str(user_id) for user_id in roster]:
            raise AppException("This payroll run already has a frozen roster.", status_code=409)
        frozen = snapshot.get("source_evidence")
        frozen_checksums = (frozen["time_sha256"], frozen["leave_sha256"]) if frozen else None
        submitted_checksums = (
            (source_evidence.time_sha256, source_evidence.leave_sha256)
            if source_evidence else None
        )
        if frozen_checksums != submitted_checksums:
            raise AppException("This run already has a fixed source review.", status_code=409)
        return run
    if (
        run.status != "draft"
        or period.status != "open"
        or await session.scalar(
            select(HrPayrollLine.id).where(HrPayrollLine.payroll_run_id == run.id).limit(1)
        )
    ):
        raise AppException(
            "Calculate only an empty draft in an open payroll period.", status_code=409
        )
    start, end = period.period_start, period.period_end
    if (
        start.day != 1
        or (start.year, start.month) != (end.year, end.month)
        or end.day != monthrange(end.year, end.month)[1]
        or end >= business_today()
        or period.pay_date < end
    ):
        raise AppException(
            "The supported payroll period is a closed calendar month.", status_code=422
        )
    policy = await session.get(HrPayrollPolicy, run.policy_id) if run.policy_id else None
    if policy is None:
        raise AppException("Select an approved payroll policy.", status_code=409)
    currency, rounding, rate = _policy_rules(policy)
    if policy.controlled_record is not None:
        record = PayrollControlledPolicyRecord.model_validate(policy.controlled_record)
        if record.effective_from > start:
            raise AppException(
                "The controlled payroll policy must be effective from the start of the period.",
                status_code=409,
                error_code="PAYROLL_POLICY_NOT_EFFECTIVE",
            )
    basis = policy.rules_json["calculation_basis"]
    terms = await _source_terms(session, roster, period, currency)
    adjustment_map: dict[str, list[PayrollAdjustmentResponse]] = {}
    if basis == ADJUSTED_BASIS:
        for row in await _adjustments(session, run_id):
            if row.status == "rejected":
                continue
            if (
                row.status != "approved"
                or row.decided_at is None
                or row.decided_by_id in (None, row.submitted_by_id, run.prepared_by_id)
            ):
                raise AppException(
                    "Review all payroll adjustments before calculation.", status_code=409
                )
            if row.employee_id not in roster:
                raise AppException(
                    "Include each employee with an approved adjustment.", status_code=409
                )
            adjustment_map.setdefault(str(row.employee_id), []).append(_adjustment_response(row))
    lines = []
    for term in terms:
        base = _decimal(
            decrypt_hr_value(term.base_salary_encrypted),
            places=2,
            maximum=MAX_AMOUNT,
        )
        earnings = Decimal("0.00")
        extra_deductions = Decimal("0.00")
        for adjustment in adjustment_map.get(str(term.employee_id), []):
            if adjustment.kind == "earning":
                earnings += Decimal(adjustment.amount)
            else:
                extra_deductions += Decimal(adjustment.amount)
        gross, deduction, net = _payroll_amounts(base, rate, rounding, earnings, extra_deductions)
        lines.append(
            HrPayrollLine(
                payroll_run_id=run.id,
                employee_id=term.employee_id,
                gross_encrypted=encrypt_hr_value(str(gross)),
                deductions_encrypted=encrypt_hr_value(str(deduction)),
                net_encrypted=encrypt_hr_value(str(net)),
                breakdown_json={},
            )
        )
    frozen_sources = None
    frozen_csvs = None
    if source_evidence is not None:
        source_roster = set(roster)  # _source_terms holds the employee locks through commit.
        time_preview, time_csv = await reconcile_payroll_time_inputs(session, period, source_roster)
        leave_preview, leave_csv = await reconcile_payroll_leave_inputs(
            session, period, source_roster
        )
        if (
            time_csv is None
            or leave_csv is None
            or time_preview.csv_sha256 != source_evidence.time_sha256
            or leave_preview.csv_sha256 != source_evidence.leave_sha256
            or time_preview.regular_hours is None
            or time_preview.overtime_hours is None
            or leave_preview.paid_days is None
            or leave_preview.unpaid_days is None
        ):
            raise AppException(
                "Refresh time and leave reconciliation before calculation.", status_code=409
            )
        frozen_sources = PayrollFrozenSources(
            time_sha256=source_evidence.time_sha256,
            leave_sha256=source_evidence.leave_sha256,
            regular_hours=time_preview.regular_hours,
            overtime_hours=time_preview.overtime_hours,
            paid_days=leave_preview.paid_days,
            unpaid_days=leave_preview.unpaid_days,
        ).model_dump(mode="json")
        frozen_csvs = {"time": time_csv.decode(), "leave": leave_csv.decode()}
    snapshot = {
        "source_evidence": frozen_sources,
        "source_csvs": frozen_csvs,
        "run_id": str(run.id),
        "period_id": str(period.id),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "pay_date": period.pay_date.isoformat(),
        "policy_id": str(policy.id),
        "controlled_policy_record": policy.controlled_record,
        "policy_code": policy.code,
        "policy_approvers": [str(policy.approved_by_id), str(policy.second_approved_by_id)],
        "calculation_basis": basis,
        "adjustments": {
            employee_id: [item.model_dump(mode="json") for item in adjustments]
            for employee_id, adjustments in adjustment_map.items()
        },
        "currency": currency,
        "rounding": rounding,
        "rate": str(rate),
        "terms": {str(term.employee_id): str(term.id) for term in terms},
        "line_hash": _line_hash(lines),
    }
    session.add_all(lines)
    run.snapshot_encrypted = encrypt_hr_value(json.dumps(snapshot, sort_keys=True))
    run.status = "calculated"
    await AuditService(session).record(
        action="hr.payroll_run.calculated",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run.id,
        new_values={"line_count": len(lines)},
    )
    await session.commit()
    return run


def _line_amounts(line: HrPayrollLine) -> dict[str, Decimal]:
    maximum = Decimal("9999999999999999.99")
    return {
        "gross": _decimal(decrypt_hr_value(line.gross_encrypted), places=2, maximum=maximum),
        "deductions": _decimal(
            decrypt_hr_value(line.deductions_encrypted), places=2, maximum=maximum
        ),
        "net": _decimal(decrypt_hr_value(line.net_encrypted), places=2, maximum=maximum),
    }


async def read_payroll_snapshot(
    session: AsyncSession, run_id: UUID, actor: User
) -> PayrollRunSnapshotResponse:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    run = await get_payroll_run(session, run_id)
    data, lines = await _stored_snapshot(session, run)
    assert run.snapshot_digest is not None
    publication = await session.get(HrPayslipPublication, run.id)
    closure = await session.get(HrPayrollClosure, run.id)
    details = [
        PayrollSnapshotLine(
            employee_id=line.employee_id,
            payment_reference=line.id,
            term_id=UUID(data["terms"][str(line.employee_id)]),
            adjustments=data.get("adjustments", {}).get(str(line.employee_id), []),
            **_line_amounts(line),
        )
        for line in lines
    ]
    await AuditService(session).record(
        action="hr.payroll_run.snapshot_viewed",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run.id,
    )
    await session.commit()
    return PayrollRunSnapshotResponse(
        run_id=run.id,
        status=run.status,
        prepared_by_id=run.prepared_by_id,
        approved_by_id=run.approved_by_id,
        payslips_published_at=publication.published_at if publication else None,
        closed_at=closure.closed_at if closure else None,
        digest=run.snapshot_digest,
        policy_id=data["policy_id"],
        controlled_policy_record=data.get("controlled_policy_record"),
        period_start=data["period_start"],
        period_end=data["period_end"],
        pay_date=data["pay_date"],
        calculation_basis=data["calculation_basis"],
        currency=data["currency"],
        rounding=data["rounding"],
        employee_deduction_rate=Decimal(data["rate"]),
        source_evidence=data.get("source_evidence"),
        lines=details,
        gross=sum((line.gross for line in details), Decimal(0)),
        deductions=sum((line.deductions for line in details), Decimal(0)),
        net=sum((line.net for line in details), Decimal(0)),
    )


async def read_frozen_payroll_source(
    session: AsyncSession, run_id: UUID, source: Literal["time", "leave"], actor: User
) -> tuple[bytes, str]:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    run = await get_payroll_run(session, run_id)
    snapshot, _ = await _stored_snapshot(session, run)
    metadata = snapshot.get("source_evidence")
    if metadata is None:
        raise NotFoundException("Frozen payroll source")
    stored = (snapshot.get("source_csvs") or {}).get(source)
    digest = metadata.get(f"{source}_sha256")
    if (
        not isinstance(stored, str)
        or not isinstance(digest, str)
        or hashlib.sha256(stored.encode()).hexdigest() != digest
    ):
        raise AppException("Stored payroll source checksum is invalid.", status_code=409)
    await AuditService(session).record(
        action="hr.payroll_run.frozen_source_downloaded",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run_id,
        new_values={"source": source, "sha256": digest},
    )
    await session.commit()
    return stored.encode(), digest


async def approve_payroll_snapshot(
    session: AsyncSession, run_id: UUID, expected_digest: str, actor: User
) -> HrPayrollRun:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    await lock_payroll_periods(session)
    run, period = await _locked_run(session, run_id)
    if run.prepared_by_id is None or run.prepared_by_id == actor.id:
        raise PermissionDeniedException("independent payroll approval")
    if run.snapshot_digest != expected_digest:
        raise AppException("Review and confirm the frozen payroll snapshot.", status_code=409)
    if run.status == "approved" and run.approved_by_id == actor.id:
        await _stored_snapshot(session, run)
        return run
    if run.status != "calculated" or period.status != "open":
        raise AppException(
            "Only a calculated run in an open period can be approved.", status_code=409
        )
    if await session.scalar(
        select(HrPayrollRun.id)
        .join(HrPayrollPeriod, HrPayrollPeriod.id == HrPayrollRun.payroll_period_id)
        .where(
            HrPayrollRun.id != run.id,
            HrPayrollRun.status == "approved",
            HrPayrollPeriod.period_start <= period.period_end,
            HrPayrollPeriod.period_end >= period.period_start,
        )
        .limit(1)
    ):
        raise AppException("An overlapping payroll run is already approved.", status_code=409)
    data, lines = await _stored_snapshot(session, run)
    if (data["period_start"], data["period_end"], data["pay_date"]) != (
        period.period_start.isoformat(),
        period.period_end.isoformat(),
        period.pay_date.isoformat(),
    ):
        raise AppException("The payroll period changed after calculation.", status_code=409)
    roster = [line.employee_id for line in lines]
    try:
        # The same roster locks also protect the attached source recheck.
        terms = await _source_terms(session, roster, period, data["currency"])
    except AppException as exc:
        raise AppException(
            "The roster no longer has eligible compensation for this period. "
            "Review the source records.",
            status_code=409,
            error_code="PAYROLL_COMPENSATION_CHANGED",
        ) from exc
    if {str(term.employee_id): str(term.id) for term in terms} != data["terms"]:
        raise AppException(
            "Approved compensation changed after calculation. Prepare a new payroll run.",
            status_code=409,
            error_code="PAYROLL_COMPENSATION_CHANGED",
        )
    if (sources := data.get("source_evidence")) is not None:
        source_roster = set(roster)
        time, _ = await reconcile_payroll_time_inputs(session, period, source_roster)
        leave, _ = await reconcile_payroll_leave_inputs(session, period, source_roster)
        if (
            time.csv_sha256 is None
            or time.csv_sha256 != sources.get("time_sha256")
            or leave.csv_sha256 is None
            or leave.csv_sha256 != sources.get("leave_sha256")
        ):
            raise AppException(
                "Time or leave changed after calculation. Resolve outstanding records and "
                "prepare a new run if the reviewed inputs changed.",
                status_code=409,
                error_code="PAYROLL_SOURCES_CHANGED",
            )
    run.status = "approved"
    run.approved_by_id = actor.id
    run.approved_at = utc_now()
    period.status = "locked"
    await AuditService(session).record(
        action="hr.payroll_run.approved",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run.id,
        new_values={"period_id": str(period.id), "snapshot_digest": expected_digest},
    )
    await session.commit()
    return run


async def publish_payslips(
    session: AsyncSession, run_id: UUID, expected_digest: str, actor: User
) -> HrPayslipPublication:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
    run, period = await _locked_run(session, run_id)
    if run.status != "approved" or run.approved_at is None or period.status != "locked":
        raise AppException("Only an approved, locked run can publish payslips.", status_code=409)
    if run.approved_by_id != actor.id or run.prepared_by_id == actor.id:
        raise PermissionDeniedException("publish this payroll run's payslips")
    if run.snapshot_digest != expected_digest:
        raise AppException(
            "Confirm the exact approved snapshot before publishing.", status_code=409
        )
    await _stored_snapshot(session, run)
    receipt = await session.get(HrPayslipPublication, run.id)
    if receipt is not None:
        if receipt.snapshot_digest != expected_digest:
            raise AppException("The published payroll snapshot changed.", status_code=409)
        return receipt
    receipt = HrPayslipPublication(
        run_id=run.id,
        published_by_id=actor.id,
        snapshot_digest=expected_digest,
        published_at=utc_now(),
    )
    session.add(receipt)
    await AuditService(session).record(
        action="hr.payroll_run.payslips_published",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run.id,
        new_values={"snapshot_digest": expected_digest},
    )
    await session.commit()
    return receipt


async def list_employee_payslips(
    session: AsyncSession, employee_id: UUID, limit: int, offset: int
) -> PayslipListResponse:
    query = (
        select(
            HrPayrollRun.id,
            HrPayrollPeriod.period_start,
            HrPayrollPeriod.period_end,
            HrPayrollPeriod.pay_date,
            HrPayslipPublication.published_at,
        )
        .join(HrPayrollPeriod, HrPayrollPeriod.id == HrPayrollRun.payroll_period_id)
        .join(HrPayslipPublication, HrPayslipPublication.run_id == HrPayrollRun.id)
        .where(
            HrPayrollRun.status == "approved",
            HrPayrollPeriod.status == "locked",
            select(HrPayrollLine.id)
            .where(
                HrPayrollLine.employee_id == employee_id,
                HrPayrollLine.payroll_run_id == HrPayrollRun.id,
            )
            .exists(),
        )
    )
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(HrPayrollPeriod.period_start.desc(), HrPayrollRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return PayslipListResponse(
        items=[
            PayslipSummary(
                run_id=row.id,
                period_start=row.period_start,
                period_end=row.period_end,
                pay_date=row.pay_date,
                published_at=row.published_at,
            )
            for row in rows
        ],
        total=total or 0,
    )


async def read_employee_payslip(
    session: AsyncSession, run_id: UUID, employee_id: UUID, actor: User
) -> PayslipDetail:
    result = (
        await session.execute(
            select(HrPayrollRun, HrPayslipPublication)
            .join(HrPayrollPeriod, HrPayrollPeriod.id == HrPayrollRun.payroll_period_id)
            .join(HrPayslipPublication, HrPayslipPublication.run_id == HrPayrollRun.id)
            .where(
                HrPayrollRun.id == run_id,
                HrPayrollRun.status == "approved",
                HrPayrollPeriod.status == "locked",
                select(HrPayrollLine.id)
                .where(
                    HrPayrollLine.employee_id == employee_id,
                    HrPayrollLine.payroll_run_id == HrPayrollRun.id,
                )
                .exists(),
            )
        )
    ).one_or_none()
    if result is None:
        raise NotFoundException("Payslip")
    run, publication = result
    if publication.snapshot_digest != run.snapshot_digest:
        raise AppException("The published payroll snapshot changed.", status_code=409)
    data, lines = await _stored_snapshot(session, run)
    own = next(line for line in lines if line.employee_id == employee_id)
    detail = PayslipDetail(
        run_id=run.id,
        period_start=data["period_start"],
        period_end=data["period_end"],
        pay_date=data["pay_date"],
        published_at=publication.published_at,
        currency=data["currency"],
        **_line_amounts(own),
    )
    await AuditService(session).record(
        action="hr.payslip.viewed",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run.id,
    )
    await session.commit()
    return detail
