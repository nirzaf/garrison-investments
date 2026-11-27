"""Preview and post approved leave credits for closed periods."""

import hashlib
import json
from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.hr import (
    HrEmployee,
    HrEmploymentHistory,
    HrEmploymentPeriod,
    HrLeaveAccrual,
    HrLeaveEntitlementBaseline,
    HrLeaveLedger,
    HrLeavePolicy,
    HrLeaveRollover,
    HrLeaveType,
)
from app.models.user import User
from app.schemas.hr import (
    GarrisonsAnnualLeaveRules,
    GarrisonsCasualLeaveRules,
    LeaveAccrualCatchUpRequest,
    LeaveAccrualCatchUpResponse,
    LeaveAccrualRequest,
    LeaveAccrualResponse,
)
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.time import business_today

ELIGIBLE_STATUSES = {"active", "on_probation", "on_leave"}


async def ensure_leave_year_open(
    session: AsyncSession, employee_id: UUID, leave_type_id: UUID, year: int
) -> None:
    if await session.scalar(
        select(HrLeaveRollover.id).where(
            HrLeaveRollover.employee_id == employee_id,
            HrLeaveRollover.leave_type_id == leave_type_id,
            HrLeaveRollover.source_year == year,
        )
    ):
        raise AppException(
            "Year-end rollover has closed this leave year.",
            status_code=409,
            error_code="LEAVE_YEAR_CLOSED",
        )


def _period(payload: LeaveAccrualRequest) -> tuple[date, date]:
    if payload.month is None:
        return date(payload.year, 1, 1), date(payload.year, 12, 31)
    last_day = monthrange(payload.year, payload.month)[1]
    return date(payload.year, payload.month, 1), date(payload.year, payload.month, last_day)


async def _lock_leave_payroll_periods(session: AsyncSession) -> None:
    # Deferred to avoid the payroll snapshot module's shared eligibility import.
    from app.services.hr_payroll_snapshot import lock_payroll_periods

    await lock_payroll_periods(session)


def _credit(annual_days: Decimal, month: int | None) -> Decimal:
    if month is None:
        return annual_days
    # Difference of rounded totals avoids losing or gaining a cent over 12 months.
    cent = Decimal("0.01")
    return (annual_days * month / 12).quantize(cent, rounding=ROUND_HALF_UP) - (
        annual_days * (month - 1) / 12
    ).quantize(cent, rounding=ROUND_HALF_UP)


def _prorated_credit(period_credit: Decimal, eligible_days: int, period_days: int) -> Decimal:
    return (period_credit * Decimal(eligible_days) / Decimal(period_days)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _incomplete_employment_period() -> AppException:
    return AppException(
        "Accrual requires a complete eligible employment period in the employee history.",
        status_code=409,
        error_code="LEAVE_ACCRUAL_EMPLOYMENT_PERIOD",
    )


async def _eligible_category(
    session: AsyncSession, employee: HrEmployee, start: date, end: date
) -> str:
    if (
        employee.join_date is None
        or employee.join_date > start
        or (employee.termination_date is not None and employee.termination_date <= end)
    ):
        raise _incomplete_employment_period()
    history = await session.execute(
        select(
            HrEmploymentHistory.effective_date,
            HrEmploymentHistory.new_snapshot["employment_status"].as_string(),
            HrEmploymentHistory.new_snapshot["employment_category"].as_string(),
        )
        .where(
            HrEmploymentHistory.employee_id == employee.id,
            HrEmploymentHistory.effective_date <= end,
        )
        .order_by(
            HrEmploymentHistory.effective_date,
            HrEmploymentHistory.created_at,
            HrEmploymentHistory.id,
        )
    )
    status = category = None
    for day, next_status, next_category in history:
        if day > start:
            if status not in ELIGIBLE_STATUSES or category is None:
                raise _incomplete_employment_period()
            if next_status is not None and next_status not in ELIGIBLE_STATUSES:
                raise _incomplete_employment_period()
            if next_category is not None and next_category != category:
                raise _incomplete_employment_period()
        status = next_status or status
        category = next_category or category
    if status not in ELIGIBLE_STATUSES or category is None:
        raise _incomplete_employment_period()
    return category


async def _policy_for_period(
    session: AsyncSession, leave_type_id: UUID, category: str, start: date, end: date
) -> HrLeavePolicy:
    policies = list(
        await session.scalars(
            select(HrLeavePolicy)
            .where(
                HrLeavePolicy.leave_type_id == leave_type_id,
                HrLeavePolicy.status == "approved",
                HrLeavePolicy.is_active.is_(True),
                HrLeavePolicy.approved_at.is_not(None),
                HrLeavePolicy.effective_from <= end,
                HrLeavePolicy.effective_to >= start,
                or_(
                    HrLeavePolicy.employment_category == category,
                    HrLeavePolicy.employment_category.is_(None),
                ),
            )
            .order_by(HrLeavePolicy.employment_category.is_(None), HrLeavePolicy.id)
        )
    )
    chosen = None
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        policy = next(
            (
                row
                for row in policies
                if row.effective_from is not None
                and row.effective_to is not None
                and row.effective_from <= day <= row.effective_to
            ),
            None,
        )
        if policy is None or (chosen is not None and chosen.id != policy.id):
            raise AppException(
                "One dated, approved policy must cover the entire accrual period.",
                status_code=409,
                error_code="LEAVE_ACCRUAL_POLICY_PERIOD",
            )
        chosen = policy
    assert chosen is not None
    return chosen


async def require_managed_leave_credit_reconciliation(
    session: AsyncSession,
    *,
    employee_id: UUID,
    leave_type_id: UUID,
    leave_year: int,
    policy_id: UUID,
    employee: HrEmployee,
    policy: HrLeavePolicy,
) -> HrLeaveEntitlementBaseline | None:
    """Reject unreviewed positive credits before a managed entitlement is used.

    Accrual posting and leave approval both hold the payroll advisory lock before
    calling this predicate, so a baseline cannot race a managed credit or debit.
    """
    baseline = await session.scalar(
        select(HrLeaveEntitlementBaseline).where(
            HrLeaveEntitlementBaseline.employee_id == employee_id,
            HrLeaveEntitlementBaseline.leave_type_id == leave_type_id,
            HrLeaveEntitlementBaseline.leave_year == leave_year,
        )
    )
    if policy.id != policy_id:
        raise _baseline_required()
    _validate_managed_policy(policy)
    if baseline is not None:
        await _validate_managed_baseline_receipt(
            session, baseline, employee=employee, policy=policy
        )

    service_start = await _managed_service_start(session, employee)
    positive_rows = list(
        await session.execute(
            select(HrLeaveLedger, HrLeaveAccrual)
            .outerjoin(HrLeaveAccrual, HrLeaveAccrual.ledger_id == HrLeaveLedger.id)
            .where(
                HrLeaveLedger.employee_id == employee_id,
                HrLeaveLedger.leave_type_id == leave_type_id,
                HrLeaveLedger.leave_year == leave_year,
                HrLeaveLedger.days_delta > 0,
            )
            .order_by(HrLeaveLedger.created_at, HrLeaveLedger.id)
        )
    )
    for ledger, accrual in positive_rows:
        if baseline is not None and (
            ledger.id == baseline.adjustment_ledger_id
            or ledger.created_at <= baseline.created_at
        ):
            continue
        if ledger.entry_type == "reversal" and ledger.reference_request_id is not None:
            matching_debit = await session.scalar(
                select(HrLeaveLedger.id).where(
                    HrLeaveLedger.employee_id == employee_id,
                    HrLeaveLedger.leave_type_id == leave_type_id,
                    HrLeaveLedger.leave_year == leave_year,
                    HrLeaveLedger.reference_request_id == ledger.reference_request_id,
                    HrLeaveLedger.entry_type == "taken",
                    HrLeaveLedger.days_delta == -ledger.days_delta,
                )
            )
            if matching_debit is not None:
                continue
        if not _is_approved_managed_accrual(
            ledger, accrual, policy=policy, service_start=service_start, year=leave_year
        ):
            raise _baseline_required()
    return baseline


def _baseline_required() -> AppException:
    return AppException(
        "Reconcile the existing managed leave balance before using this entitlement.",
        status_code=409,
        error_code="LEAVE_ENTITLEMENT_BASELINE_REQUIRED",
    )


def _validate_managed_policy(policy: HrLeavePolicy) -> None:
    rules = policy.entitlement_rules
    if not isinstance(rules, dict):
        raise AppException(
            "The approved managed leave profile is incomplete.",
            status_code=409,
            error_code="LEAVE_POLICY_CONFIGURATION_INCOMPLETE",
        )
    profile = rules.get("profile")
    try:
        if profile == "garrisons_annual_v1":
            GarrisonsAnnualLeaveRules.model_validate(rules)
            expected = (Decimal("14.00"), "annual")
        elif profile == "garrisons_casual_v1":
            GarrisonsCasualLeaveRules.model_validate(rules)
            expected = (Decimal("7.00"), "monthly")
        else:
            raise ValueError("Unsupported managed leave profile")
    except ValueError as exc:
        raise AppException(
            "The approved managed leave profile is incomplete.",
            status_code=409,
            error_code="LEAVE_POLICY_CONFIGURATION_INCOMPLETE",
        ) from exc
    if (
        policy.annual_entitlement_days != expected[0]
        or policy.accrual_frequency != expected[1]
        or policy.prorate_by_calendar_day
        or policy.max_carry_forward_days != 0
        or not policy.expire_excess_on_rollover
        or policy.allow_negative_balance
    ):
        raise AppException(
            "The approved managed leave policy configuration is incomplete.",
            status_code=409,
            error_code="LEAVE_POLICY_CONFIGURATION_INCOMPLETE",
        )


def _ledger_digest(rows: list[HrLeaveLedger]) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                {
                    "id": str(row.id),
                    "entry_type": row.entry_type,
                    "days_delta": str(row.days_delta),
                    "year": row.leave_year,
                    "reference_request_id": (
                        str(row.reference_request_id) if row.reference_request_id else None
                    ),
                    "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _possible_managed_due_dates(policy: HrLeavePolicy, service_start: date, year: int) -> set[date]:
    profile = policy.entitlement_rules.get("profile") if policy.entitlement_rules else None
    service_year = year - service_start.year + 1
    if profile == "garrisons_annual_v1":
        return {date(year, 1, 1)} if service_year >= 2 else set()
    if profile == "garrisons_casual_v1":
        if service_year >= 2:
            return {date(year, 1, 1)}
        return {
            due
            for offset in range(1, 12)
            if (due := _add_service_month(service_start, offset)).year == year
        }
    raise _baseline_required()


async def _validate_managed_baseline_receipt(
    session: AsyncSession,
    baseline: HrLeaveEntitlementBaseline,
    *,
    employee: HrEmployee,
    policy: HrLeavePolicy,
) -> None:
    if (
        baseline.employee_id != employee.id
        or baseline.policy_id != policy.id
        or baseline.leave_year != baseline.as_of_date.year
        or baseline.as_of_date > business_today()
        or baseline.verified_balance < 0
        or not baseline.supporting_reference.strip()
        or baseline.reviewed_by_id is None
        or baseline.reviewed_at is None
    ):
        raise _baseline_required()

    service_start = await _managed_service_start(session, employee)
    possible_due_dates = _possible_managed_due_dates(
        policy, service_start, baseline.leave_year
    )
    recognized = baseline.recognized_due_dates
    if not isinstance(recognized, list):
        raise _baseline_required()
    try:
        recognized_dates = [date.fromisoformat(item) for item in recognized]
    except (TypeError, ValueError):
        raise _baseline_required() from None
    if len(recognized_dates) != len(set(recognized_dates)) or any(
        day not in possible_due_dates or day > baseline.as_of_date for day in recognized_dates
    ):
        raise _baseline_required()

    ambiguous_snapshot_query = select(HrLeaveLedger.id).where(
        HrLeaveLedger.employee_id == employee.id,
        HrLeaveLedger.leave_type_id == baseline.leave_type_id,
        HrLeaveLedger.leave_year == baseline.leave_year,
        HrLeaveLedger.created_at == baseline.created_at,
    )
    if baseline.adjustment_ledger_id is not None:
        ambiguous_snapshot_query = ambiguous_snapshot_query.where(
            HrLeaveLedger.id != baseline.adjustment_ledger_id
        )
    ambiguous_snapshot_row = await session.scalar(ambiguous_snapshot_query.limit(1))
    if ambiguous_snapshot_row is not None:
        raise _baseline_required()
    snapshot_rows = list(
        await session.scalars(
            select(HrLeaveLedger)
            .where(
                HrLeaveLedger.employee_id == employee.id,
                HrLeaveLedger.leave_type_id == baseline.leave_type_id,
                HrLeaveLedger.leave_year == baseline.leave_year,
                HrLeaveLedger.created_at < baseline.created_at,
            )
            .order_by(HrLeaveLedger.created_at, HrLeaveLedger.id)
        )
    )
    future_credit = await session.scalar(
        select(HrLeaveLedger.id)
        .join(HrLeaveAccrual, HrLeaveAccrual.ledger_id == HrLeaveLedger.id)
        .where(
            HrLeaveLedger.employee_id == employee.id,
            HrLeaveLedger.leave_type_id == baseline.leave_type_id,
            HrLeaveLedger.leave_year == baseline.leave_year,
            HrLeaveLedger.created_at < baseline.created_at,
            HrLeaveLedger.days_delta > 0,
            or_(
                HrLeaveAccrual.due_date.is_(None),
                HrLeaveAccrual.due_date > baseline.as_of_date,
            ),
        )
        .limit(1)
    )
    if future_credit is not None:
        raise _baseline_required()
    as_of_cutoff = datetime.combine(
        baseline.as_of_date,
        time.max,
        tzinfo=ZoneInfo(get_settings().business_timezone),
    ).astimezone(UTC)
    if any(row.created_at.astimezone(UTC) > as_of_cutoff for row in snapshot_rows):
        raise _baseline_required()
    raw_ledger_digest = _ledger_digest(snapshot_rows)
    snapshot_balance = sum((row.days_delta for row in snapshot_rows), Decimal("0.00"))
    adjustment_days = (baseline.verified_balance - snapshot_balance).quantize(Decimal("0.01"))
    adjustment = (
        await session.get(HrLeaveLedger, baseline.adjustment_ledger_id)
        if baseline.adjustment_ledger_id
        else None
    )
    if adjustment_days == 0:
        if adjustment is not None:
            raise _baseline_required()
    elif (
        adjustment is None
        or adjustment.employee_id != employee.id
        or adjustment.leave_type_id != baseline.leave_type_id
        or adjustment.leave_year != baseline.leave_year
        or adjustment.entry_type != "adjustment"
        or adjustment.days_delta != adjustment_days
        or adjustment.actor_user_id != baseline.reviewed_by_id
    ):
        raise _baseline_required()

    plan = {
        "employee_id": str(employee.id),
        "leave_type_id": str(baseline.leave_type_id),
        "year": baseline.leave_year,
        "policy_id": str(baseline.policy_id),
        "as_of_date": baseline.as_of_date.isoformat(),
        "current_balance": str(snapshot_balance),
        "verified_balance": str(baseline.verified_balance),
        "adjustment_days": str(adjustment_days),
        "recognized_due_dates": recognized,
        "supporting_reference": baseline.supporting_reference,
    }
    expected_plan_digest = hashlib.sha256(
        json.dumps(
            {
                "plan": plan,
                "actor_id": str(baseline.reviewed_by_id),
                "employee_revision": employee.record_revision,
                "policy_id": str(policy.id),
                "policy_rules": policy.entitlement_rules,
                "policy_approved_at": policy.approved_at.isoformat()
                if policy.approved_at
                else None,
                "ledger_digest": raw_ledger_digest,
                "possible_due_dates": sorted(day.isoformat() for day in possible_due_dates),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    # Older approved receipts stored the plan digest in both columns. Their
    # underlying snapshot is still verifiable from the ledger rows before receipt creation.
    if baseline.ledger_digest not in {raw_ledger_digest, baseline.plan_digest}:
        raise _baseline_required()
    if expected_plan_digest != baseline.plan_digest:
        raise _baseline_required()


def _is_approved_managed_accrual(
    ledger: HrLeaveLedger,
    accrual: HrLeaveAccrual | None,
    *,
    policy: HrLeavePolicy,
    service_start: date,
    year: int,
) -> bool:
    if (
        ledger.entry_type != "accrual"
        or accrual is None
        or accrual.policy_id != policy.id
        or accrual.due_date is None
        or accrual.due_date > business_today()
        or accrual.due_date not in _possible_managed_due_dates(policy, service_start, year)
    ):
        return False
    service_year = year - service_start.year + 1
    rules = policy.entitlement_rules or {}
    if rules.get("profile") == "garrisons_annual_v1":
        expected = (
            _bracket_days(rules, service_start)
            if service_year == 2
            else Decimal("14.00")
            if service_year >= 3
            else Decimal("0.00")
        )
        return (
            accrual.period_start == date(year, 1, 1)
            and accrual.period_end == date(year, 12, 31)
            and accrual.due_date == date(year, 1, 1)
            and ledger.days_delta == expected
            and expected > 0
        )
    if rules.get("profile") == "garrisons_casual_v1":
        if service_year >= 2:
            return (
                accrual.period_start == date(year, 1, 1)
                and accrual.period_end == date(year, 12, 31)
                and accrual.due_date == date(year, 1, 1)
                and ledger.days_delta == Decimal("7.00")
            )
        month_start = accrual.period_start
        return (
            month_start.year == year
            and month_start.day == 1
            and accrual.period_end == date(
                month_start.year,
                month_start.month,
                monthrange(month_start.year, month_start.month)[1],
            )
            and accrual.due_date
            == _add_service_month(service_start, (month_start.year - service_start.year) * 12
                                  + month_start.month - service_start.month)
            and ledger.days_delta == Decimal("0.50")
        )
    return False


def _add_service_month(start: date, month_offset: int) -> date:
    month_index = start.year * 12 + start.month - 1 + month_offset
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


async def _managed_service_start(session: AsyncSession, employee: HrEmployee) -> date:
    periods = list(
        await session.scalars(
            select(HrEmploymentPeriod)
            .where(HrEmploymentPeriod.employee_id == employee.id)
            .order_by(HrEmploymentPeriod.started_on, HrEmploymentPeriod.id)
        )
    )
    if periods:
        active = [period for period in periods if period.ended_on is None]
        if len(active) != 1 or active[0].started_on is None:
            raise _incomplete_employment_period()
        start = active[0].started_on
    elif employee.join_date is not None:
        start = employee.join_date
    else:
        raise _incomplete_employment_period()
    today = business_today()
    if start > today or employee.employment_status not in ELIGIBLE_STATUSES:
        raise _incomplete_employment_period()
    if employee.termination_date is not None and employee.termination_date <= today:
        raise _incomplete_employment_period()
    return start


async def _managed_category_at(
    session: AsyncSession, employee: HrEmployee, effective_date: date
) -> str:
    rows = await session.execute(
        select(
            HrEmploymentHistory.new_snapshot["employment_status"].as_string(),
            HrEmploymentHistory.new_snapshot["employment_category"].as_string(),
        )
        .where(
            HrEmploymentHistory.employee_id == employee.id,
            HrEmploymentHistory.effective_date <= effective_date,
        )
        .order_by(
            HrEmploymentHistory.effective_date,
            HrEmploymentHistory.created_at,
            HrEmploymentHistory.id,
        )
    )
    status = category = None
    for next_status, next_category in rows:
        status = next_status or status
        category = next_category or category
    if status is not None and status not in ELIGIBLE_STATUSES:
        raise _incomplete_employment_period()
    if category is None:
        if employee.join_date is None:
            raise _incomplete_employment_period()
        category = employee.employment_category
    return category


def _bracket_days(rules: dict, service_start: date) -> Decimal:
    for bracket in rules.get("second_year_brackets", []):
        start = (bracket["from_month"], bracket["from_day"])
        end = (bracket["through_month"], bracket["through_day"])
        day = (service_start.month, service_start.day)
        if (start <= end and start <= day <= end) or (start > end and (day >= start or day <= end)):
            return Decimal(str(bracket["days"]))
    raise AppException(
        "The approved second-year entitlement profile has no matching bracket.",
        status_code=409,
        error_code="LEAVE_POLICY_CONFIGURATION_INCOMPLETE",
    )


async def _plan_managed_leave_accrual(
    session: AsyncSession,
    payload: LeaveAccrualRequest,
    employee: HrEmployee,
    policy: HrLeavePolicy,
    actor: User | None,
    start: date,
    end: date,
) -> tuple[LeaveAccrualResponse, str | None]:
    rules = policy.entitlement_rules
    if not isinstance(rules, dict):
        raise AppException(
            "The approved managed leave profile is incomplete.",
            status_code=409,
            error_code="LEAVE_POLICY_CONFIGURATION_INCOMPLETE",
        )
    profile = rules.get("profile")
    service_start = await _managed_service_start(session, employee)
    category = await _managed_category_at(session, employee, start)
    if category != employee.employment_category:
        policy = await _policy_for_period(
            session, payload.leave_type_id, category, start, end
        )
        rules = policy.entitlement_rules or {}
        if rules.get("profile") != profile:
            raise AppException(
                "An approved policy must cover the employee's category "
                "for the full credit period.",
                status_code=409,
                error_code="LEAVE_ACCRUAL_POLICY_PERIOD",
            )
    service_year = payload.year - service_start.year + 1
    due_date: date | None
    days = Decimal("0.00")
    if profile == "garrisons_annual_v1":
        if payload.month is not None:
            raise AppException(
                "Annual managed leave is credited at the beginning of the calendar year.",
                status_code=409,
                error_code="LEAVE_ACCRUAL_FREQUENCY",
            )
        due_date = date(payload.year, 1, 1)
        if service_year == 2:
            days = _bracket_days(rules, service_start)
        elif service_year >= 3:
            days = Decimal("14.00")
    elif profile == "garrisons_casual_v1":
        if payload.month is None:
            due_date = date(payload.year, 1, 1)
            if service_year >= 2:
                days = Decimal("7.00")
        else:
            due_date = None
            if service_year == 1:
                for month_offset in range(1, 12):
                    completed_on = _add_service_month(service_start, month_offset)
                    if completed_on.year == payload.year and completed_on.month == payload.month:
                        due_date = completed_on
                        days = Decimal("0.50")
                        break
    else:
        raise AppException(
            "The approved managed leave profile is unsupported.",
            status_code=409,
            error_code="LEAVE_POLICY_CONFIGURATION_INCOMPLETE",
        )
    outcome: Literal[
        "preview", "posted", "already_posted", "not_due", "reconciliation_required"
    ] = "preview"
    if due_date is None or due_date > business_today() or days == 0:
        outcome = "not_due"
        days = Decimal("0.00")
    if days > 0 and due_date is not None and due_date < service_start:
        raise _incomplete_employment_period()
    if due_date is not None:
        due_category = await _managed_category_at(session, employee, due_date)
        if due_category != category:
            policy = await _policy_for_period(
                session, payload.leave_type_id, due_category, start, end
            )
            rules = policy.entitlement_rules or {}
            if rules.get("profile") != profile:
                raise AppException(
                    "The approved policy must cover this category for the full credit period.",
                    status_code=409,
                    error_code="LEAVE_ACCRUAL_POLICY_PERIOD",
                )
    quote = LeaveAccrualResponse(
        employee_id=employee.id,
        leave_type_id=payload.leave_type_id,
        policy_id=policy.id,
        period_start=start,
        period_end=end,
        days=days,
        due_date=due_date,
        service_year_band=service_year if service_year >= 1 else None,
        outcome=outcome,
    )
    if outcome == "not_due":
        return quote, None
    digest = hashlib.sha256(
        json.dumps(
            {
                **quote.model_dump(mode="json", exclude_none=True),
                "actor": str(actor.id) if actor else "scheduler",
                "employee_revision": employee.record_revision,
                "policy_rules": rules,
                "service_start": service_start.isoformat(),
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    return quote.model_copy(update={"digest": digest}), digest


async def _plan_leave_accrual(
    session: AsyncSession,
    payload: LeaveAccrualRequest,
    actor: User | None,
    *,
    lock: bool,
) -> tuple[LeaveAccrualResponse, str, UUID | None]:
    if payload.year > business_today().year:
        raise AppException("Leave accrual cannot be planned for a future year.", status_code=422)
    start, end = _period(payload)
    employee_query = select(HrEmployee).where(
        HrEmployee.id == payload.employee_id, HrEmployee.deleted_at.is_(None)
    )
    if lock:
        # Shared with approval, balance adjustments and employee updates.
        employee_query = employee_query.with_for_update()
    employee = await session.scalar(employee_query)
    if employee is None:
        raise NotFoundException("Employee")
    posted = (
        await session.execute(
            select(HrLeaveAccrual, HrLeaveLedger.days_delta, HrLeaveLedger.actor_user_id)
            .join(HrLeaveLedger, HrLeaveLedger.id == HrLeaveAccrual.ledger_id)
            .where(
                HrLeaveAccrual.employee_id == employee.id,
                HrLeaveAccrual.leave_type_id == payload.leave_type_id,
                HrLeaveAccrual.period_start <= end,
                HrLeaveAccrual.period_end >= start,
            )
            .order_by(HrLeaveAccrual.period_start)
            .limit(1)
        )
    ).first()
    if posted is not None:
        receipt, days, posted_by = posted
        if (receipt.period_start, receipt.period_end) != (start, end):
            raise AppException("This period overlaps a posted accrual.", status_code=409)
        return (
            LeaveAccrualResponse(
                employee_id=employee.id,
                leave_type_id=receipt.leave_type_id,
                policy_id=receipt.policy_id,
                period_start=start,
                period_end=end,
                eligible_from=receipt.eligible_from,
                eligible_through=receipt.eligible_through,
                days=days,
                ledger_entry_id=receipt.ledger_id,
                due_date=receipt.due_date,
                outcome="already_posted",
            ),
            receipt.plan_digest,
            posted_by,
        )

    await ensure_leave_year_open(session, employee.id, payload.leave_type_id, start.year)
    type_query = select(HrLeaveType.id).where(
        HrLeaveType.id == payload.leave_type_id,
        HrLeaveType.is_active.is_(True),
        HrLeaveType.is_paid.is_(True),
    )
    if lock:
        # Policy review takes the same type lock before changing applicability.
        type_query = type_query.with_for_update()
    if await session.scalar(type_query) is None:
        raise NotFoundException("Active paid leave type")
    eligible_from = max(start, employee.join_date or start)
    eligible_through = end
    if employee.termination_date is not None and employee.termination_date <= end:
        if employee.termination_date <= eligible_from:
            raise _incomplete_employment_period()
        eligible_through = employee.termination_date - timedelta(days=1)
    if eligible_from > eligible_through:
        raise _incomplete_employment_period()
    if employee.join_date is None:
        category = employee.employment_category
    else:
        category = await _eligible_category(session, employee, eligible_from, eligible_through)
    policy = await _policy_for_period(session, payload.leave_type_id, category, start, end)
    if policy.entitlement_rules is not None:
        baseline = await require_managed_leave_credit_reconciliation(
            session,
            employee_id=employee.id,
            leave_type_id=payload.leave_type_id,
            leave_year=start.year,
            policy_id=policy.id,
            employee=employee,
            policy=policy,
        )
        quote, digest = await _plan_managed_leave_accrual(
            session, payload, employee, policy, actor, start, end
        )
        if baseline is not None and quote.due_date is not None and (
            quote.due_date.isoformat() in baseline.recognized_due_dates
        ):
            return (
                quote.model_copy(
                    update={
                        "days": Decimal("0.00"),
                        "outcome": "baseline_recognized",
                        "digest": None,
                    }
                ),
                "",
                None,
            )
        if baseline is not None and digest:
            digest = hashlib.sha256(
                f"{digest}:{baseline.plan_digest}".encode()
            ).hexdigest()
        return quote, digest or "", None
    if employee.join_date is None:
        raise _incomplete_employment_period()
    if end >= business_today():
        raise AppException("Accrual can only post for a closed period.", status_code=422)
    partial = (eligible_from, eligible_through) != (start, end)
    if partial and not policy.prorate_by_calendar_day:
        raise AppException(
            "This policy does not authorize accrual for a partial employment period.",
            status_code=409,
            error_code="LEAVE_ACCRUAL_EMPLOYMENT_PERIOD",
        )
    if policy.accrual_frequency != ("annual" if payload.month is None else "monthly"):
        raise AppException(
            "The requested period does not match the approved policy's accrual frequency.",
            status_code=409,
            error_code="LEAVE_ACCRUAL_FREQUENCY",
        )
    if await session.scalar(
        select(HrLeaveLedger.id)
        .outerjoin(HrLeaveAccrual, HrLeaveAccrual.ledger_id == HrLeaveLedger.id)
        .where(
            HrLeaveLedger.employee_id == employee.id,
            HrLeaveLedger.leave_type_id == payload.leave_type_id,
            HrLeaveLedger.leave_year == start.year,
            HrLeaveLedger.entry_type.in_(["opening_balance", "accrual"]),
            HrLeaveAccrual.id.is_(None),
        )
        .limit(1)
    ):
        raise AppException(
            "Reconcile the opening balance or manual accrual before crediting this year.",
            status_code=409,
            error_code="LEAVE_ACCRUAL_MANUAL_BALANCE",
        )
    days = _credit(policy.annual_entitlement_days, payload.month)
    if partial:
        days = _prorated_credit(
            days, (eligible_through - eligible_from).days + 1, (end - start).days + 1
        )
    if days <= 0:
        raise AppException(
            "The approved calculation yields no credit for this period.", status_code=422
        )
    quote = LeaveAccrualResponse(
        employee_id=employee.id,
        leave_type_id=payload.leave_type_id,
        policy_id=policy.id,
        period_start=start,
        period_end=end,
        eligible_from=eligible_from if partial else None,
        eligible_through=eligible_through if partial else None,
        days=days,
    )
    digest = hashlib.sha256(
        json.dumps(
            {
                **quote.model_dump(mode="json", exclude_none=True),
                "actor": str(actor.id) if actor else "scheduler",
                "employee_revision": employee.record_revision,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return quote, digest, None


async def _record_accrual(
    session: AsyncSession, quote: LeaveAccrualResponse, digest: str, actor: User | None
) -> LeaveAccrualResponse:
    start, end = quote.period_start, quote.period_end
    entry = HrLeaveLedger(
        employee_id=quote.employee_id,
        leave_type_id=quote.leave_type_id,
        entry_type="accrual",
        days_delta=quote.days,
        leave_year=start.year,
        reason=f"Approved policy accrual for {start.isoformat()} through {end.isoformat()}",
        actor_user_id=actor.id if actor else None,
    )
    session.add(entry)
    await session.flush()
    session.add(
        HrLeaveAccrual(
            employee_id=quote.employee_id,
            leave_type_id=quote.leave_type_id,
            policy_id=quote.policy_id,
            ledger_id=entry.id,
            period_start=start,
            period_end=end,
            due_date=quote.due_date,
            eligible_from=quote.eligible_from,
            eligible_through=quote.eligible_through,
            plan_digest=digest,
        )
    )
    await AuditService(session).record(
        action="hr.leave_accrual.posted",
        user_id=actor.id if actor else None,
        entity_type="hr_leave_ledger",
        entity_id=entry.id,
        new_values={
            "policy_id": str(quote.policy_id),
            "period_start": start.isoformat(),
            "days": str(quote.days),
            **(
                {
                    "eligible_from": quote.eligible_from.isoformat(),
                    "eligible_through": quote.eligible_through.isoformat(),
                }
                if quote.eligible_from and quote.eligible_through
                else {}
            ),
            **({"source": "scheduled"} if actor is None else {}),
        },
    )
    return quote.model_copy(update={"ledger_entry_id": entry.id, "outcome": "posted"})


async def process_leave_accrual(
    session: AsyncSession,
    payload: LeaveAccrualRequest,
    actor: User,
    *,
    expected_digest: str | None = None,
) -> LeaveAccrualResponse:
    if expected_digest is not None:
        await _lock_leave_payroll_periods(session)
    quote, digest, posted_by = await _plan_leave_accrual(
        session, payload, actor, lock=expected_digest is not None
    )
    if expected_digest is None:
        if quote.ledger_entry_id or quote.outcome in {"not_due", "baseline_recognized"}:
            return quote
        return quote.model_copy(update={"digest": digest})
    if quote.outcome in {"not_due", "baseline_recognized"}:
        raise AppException(
            "This managed entitlement does not need another credit.", status_code=409
        )
    if quote.ledger_entry_id:
        if digest != expected_digest or posted_by != actor.id:
            raise AppException("This period overlaps a posted accrual.", status_code=409)
        return quote
    if digest != expected_digest:
        raise AppException("The accrual preview changed. Review it again.", status_code=409)
    saved = await _record_accrual(session, quote, digest, actor)
    await session.commit()
    return saved


async def post_scheduled_leave_accrual(
    session: AsyncSession, payload: LeaveAccrualRequest, approved_policy_ids: set[UUID]
) -> Literal["posted", "already_posted", "outside_schedule", "not_due"]:
    await _lock_leave_payroll_periods(session)
    quote, digest, _ = await _plan_leave_accrual(session, payload, None, lock=True)
    if quote.ledger_entry_id:
        return "already_posted"
    if quote.outcome in {"not_due", "baseline_recognized"}:
        return "not_due"
    if quote.policy_id not in approved_policy_ids:
        return "outside_schedule"
    await _record_accrual(session, quote, digest, None)
    await session.commit()
    return "posted"


async def process_leave_accrual_catch_up(
    session: AsyncSession,
    payload: LeaveAccrualCatchUpRequest,
    actor: User,
    *,
    expected_digest: str | None = None,
) -> LeaveAccrualCatchUpResponse:
    if payload.start_month > payload.end_month:
        raise AppException("The first month must precede or equal the last month.", status_code=422)

    if expected_digest is not None:
        await _lock_leave_payroll_periods(session)

    plans = []
    for month in range(payload.start_month, payload.end_month + 1):
        selection = LeaveAccrualRequest(
            employee_id=payload.employee_id,
            leave_type_id=payload.leave_type_id,
            year=payload.year,
            month=month,
        )
        quote, period_digest, posted_by = await _plan_leave_accrual(
            session, selection, actor, lock=expected_digest is not None
        )
        plans.append((quote, period_digest, posted_by))

    # Individual receipt digests survive posting so an exact retry reconstructs
    # the same confirmation, including periods already posted before preview.
    digest = hashlib.sha256(
        json.dumps(
            {
                "actor": str(actor.id),
                "selection": payload.model_dump(mode="json", exclude={"expected_digest"}),
                "periods": [period_digest for _, period_digest, _ in plans],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    if expected_digest is not None and expected_digest != digest:
        raise AppException("The catch-up preview changed. Review it again.", status_code=409)

    periods = []
    pending_days = Decimal("0")
    for quote, period_digest, posted_by in plans:
        if quote.ledger_entry_id is None:
            if expected_digest is None:
                if quote.outcome not in {"not_due", "baseline_recognized"}:
                    pending_days += quote.days
            elif quote.outcome not in {"not_due", "baseline_recognized"}:
                quote = await _record_accrual(session, quote, period_digest, actor)
        elif (
            expected_digest is not None
            and quote.outcome == "already_posted"
            and posted_by == actor.id
        ):
            # Preserve the first committed catch-up response on an exact retry.
            # A credit posted by another command remains reported as already
            # posted; this only stabilizes the actor's own committed plan.
            quote = quote.model_copy(update={"outcome": "posted"})
        periods.append(quote)
    if expected_digest is not None:
        await session.commit()
    return LeaveAccrualCatchUpResponse(
        periods=periods,
        pending_days=pending_days,
        digest=digest if pending_days else None,
    )
