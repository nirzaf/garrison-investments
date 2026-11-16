"""Freeze the supported payroll calculation and approve the exact reviewed snapshot."""

import hashlib
import json
from calendar import monthrange
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import (
    HrCompensationTerm,
    HrEmployee,
    HrEmploymentPeriod,
    HrPayrollLine,
    HrPayrollPeriod,
    HrPayrollPolicy,
    HrPayrollRun,
    HrPayslipPublication,
)
from app.models.user import User
from app.schemas.hr import (
    PayrollRunSnapshotResponse,
    PayrollSnapshotLine,
    PayslipDetail,
    PayslipListResponse,
    PayslipSummary,
)
from app.services.audit_service import AuditService
from app.services.hr_crypto import decrypt_hr_value, encrypt_hr_value
from app.services.hr_leave_accrual import _eligible_category
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_PAYROLL_APPROVE,
    PERMISSION_HR_PAYROLL_PREPARE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    ensure_permission,
)
from app.utils.security import utc_now
from app.utils.time import business_today

CENTS = Decimal("0.01")
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
    return validate_payroll_rules(policy.rules_json)


def validate_payroll_rules(rules: dict[str, Any]) -> tuple[str, str, Decimal]:
    currency, rounding = rules.get("currency"), rules.get("rounding")
    if (
        set(rules) != RULES
        or rules.get("pay_frequency") != "monthly"
        or rules.get("calculation_basis") != "base_salary_only"
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
    session: AsyncSession, run_id: UUID, employee_ids: list[UUID], actor: User
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
    terms = await _source_terms(session, roster, period, currency)
    lines = []
    for term in terms:
        gross = _decimal(
            decrypt_hr_value(term.base_salary_encrypted),
            places=2,
            maximum=Decimal("9999999999999999.99"),
        )
        deduction = (gross * rate).quantize(CENTS, rounding=ROUNDING[rounding])
        lines.append(
            HrPayrollLine(
                payroll_run_id=run.id,
                employee_id=term.employee_id,
                gross_encrypted=encrypt_hr_value(str(gross)),
                deductions_encrypted=encrypt_hr_value(str(deduction)),
                net_encrypted=encrypt_hr_value(str(gross - deduction)),
                breakdown_json={},
            )
        )
    snapshot = {
        "run_id": str(run.id),
        "period_id": str(period.id),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "pay_date": period.pay_date.isoformat(),
        "policy_id": str(policy.id),
        "policy_code": policy.code,
        "policy_approvers": [str(policy.approved_by_id), str(policy.second_approved_by_id)],
        "calculation_basis": "base_salary_only",
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
    details = [
        PayrollSnapshotLine(
            employee_id=line.employee_id,
            payment_reference=line.id,
            term_id=UUID(data["terms"][str(line.employee_id)]),
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
        payslips_published_at=publication.published_at if publication else None,
        digest=run.snapshot_digest,
        policy_id=data["policy_id"],
        period_start=data["period_start"],
        period_end=data["period_end"],
        pay_date=data["pay_date"],
        calculation_basis=data["calculation_basis"],
        currency=data["currency"],
        rounding=data["rounding"],
        employee_deduction_rate=Decimal(data["rate"]),
        lines=details,
        gross=sum((line.gross for line in details), Decimal(0)),
        deductions=sum((line.deductions for line in details), Decimal(0)),
        net=sum((line.net for line in details), Decimal(0)),
    )


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
    data, _ = await _stored_snapshot(session, run)
    if (data["period_start"], data["period_end"], data["pay_date"]) != (
        period.period_start.isoformat(),
        period.period_end.isoformat(),
        period.pay_date.isoformat(),
    ):
        raise AppException("The payroll period changed after calculation.", status_code=409)
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
