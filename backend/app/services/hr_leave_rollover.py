"""Review and post one employee's year-end leave ledger closure."""

import hashlib
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import HrEmployee, HrLeaveLedger, HrLeaveRequest, HrLeaveRollover, HrLeaveType
from app.models.user import User
from app.schemas.hr import LeaveRolloverRequest, LeaveRolloverResponse
from app.services.audit_service import AuditService
from app.services.hr_leave_accrual import (
    _eligible_category,
    _policy_for_period,
    ensure_leave_year_open,
)
from app.utils.exceptions import AppException, NotFoundException
from app.utils.time import business_today


async def process_leave_rollover(
    session: AsyncSession,
    payload: LeaveRolloverRequest,
    actor: User,
    *,
    expected_digest: str | None = None,
) -> LeaveRolloverResponse:
    year = payload.source_year
    target = year + 1
    start, end = date(year, 1, 1), date(year, 12, 31)
    query = select(HrEmployee).where(
        HrEmployee.id == payload.employee_id, HrEmployee.deleted_at.is_(None)
    )
    if expected_digest is not None:
        # All source and target ledger writes for this employee share this lock.
        query = query.with_for_update()
    employee = await session.scalar(query)
    if employee is None:
        raise NotFoundException("Employee")
    saved = await session.scalar(
        select(HrLeaveRollover).where(
            HrLeaveRollover.employee_id == employee.id,
            HrLeaveRollover.leave_type_id == payload.leave_type_id,
            HrLeaveRollover.source_year == year,
        )
    )
    if saved is not None:
        if expected_digest is not None and (
            saved.plan_digest != expected_digest or saved.actor_user_id != actor.id
        ):
            raise AppException("This leave year already has a posted rollover.", status_code=409)
        return LeaveRolloverResponse(
            employee_id=employee.id,
            leave_type_id=saved.leave_type_id,
            policy_id=saved.policy_id,
            source_year=year,
            target_year=target,
            source_balance=saved.carried_days + saved.expired_days,
            carried_days=saved.carried_days,
            expired_days=saved.expired_days,
            receipt_id=saved.id,
        )
    if end >= business_today():
        raise AppException("Only a calendar year that has ended can roll over.", status_code=422)
    await ensure_leave_year_open(session, employee.id, payload.leave_type_id, target)
    type_query = select(HrLeaveType.id).where(
        HrLeaveType.id == payload.leave_type_id,
        HrLeaveType.is_active.is_(True),
        HrLeaveType.is_paid.is_(True),
    )
    if expected_digest is not None:
        type_query = type_query.with_for_update()
    if await session.scalar(type_query) is None:
        raise NotFoundException("Active paid leave type")
    category = await _eligible_category(session, employee, end, date(target, 1, 1))
    policy = await _policy_for_period(session, payload.leave_type_id, category, end, end)
    if await session.scalar(
        select(HrLeaveRequest.id)
        .where(
            HrLeaveRequest.employee_id == employee.id,
            HrLeaveRequest.leave_type_id == payload.leave_type_id,
            HrLeaveRequest.start_date.between(start, end),
            HrLeaveRequest.status.in_(["draft", "submitted"]),
        )
        .limit(1)
    ):
        raise AppException(
            "Resolve draft and submitted leave for the source year before rollover.",
            status_code=409,
            error_code="LEAVE_ROLLOVER_PENDING_REQUESTS",
        )
    ledger_scope = (
        HrLeaveLedger.employee_id == employee.id,
        HrLeaveLedger.leave_type_id == payload.leave_type_id,
    )
    if await session.scalar(
        select(HrLeaveLedger.id)
        .where(
            *ledger_scope,
            HrLeaveLedger.leave_year == target,
            HrLeaveLedger.entry_type.in_(["opening_balance", "carry_forward"]),
        )
        .limit(1)
    ):
        raise AppException(
            "Reconcile the destination opening balance or carry-forward first.",
            status_code=409,
            error_code="LEAVE_ROLLOVER_TARGET_BALANCE",
        )
    balance = Decimal(
        await session.scalar(
            select(func.coalesce(func.sum(HrLeaveLedger.days_delta), 0)).where(
                *ledger_scope, HrLeaveLedger.leave_year == year
            )
        )
        or 0
    ).quantize(Decimal("0.01"))
    if not Decimal(0) <= balance <= Decimal("9999.99"):
        raise AppException("Reconcile the source balance before rolling over.", status_code=409)
    carry = min(balance, policy.max_carry_forward_days)
    expiry = balance - carry
    if expiry > 0 and not policy.expire_excess_on_rollover:
        raise AppException(
            "The approved closing policy does not authorize expiry of excess days.",
            status_code=409,
            error_code="LEAVE_ROLLOVER_EXPIRY_NOT_APPROVED",
        )
    quote = LeaveRolloverResponse(
        employee_id=employee.id,
        leave_type_id=payload.leave_type_id,
        policy_id=policy.id,
        source_year=year,
        target_year=target,
        source_balance=balance,
        carried_days=carry,
        expired_days=expiry,
    )
    digest = hashlib.sha256(
        json.dumps(
            {
                **quote.model_dump(mode="json", exclude_none=True),
                "actor": str(actor.id),
                "employee_revision": employee.record_revision,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    if expected_digest is None:
        return quote.model_copy(update={"digest": digest})
    if digest != expected_digest:
        raise AppException("The rollover preview changed. Review it again.", status_code=409)

    def add_entry(entry_type: str, amount: Decimal, entry_year: int) -> HrLeaveLedger:
        row = HrLeaveLedger(
            employee_id=employee.id,
            leave_type_id=payload.leave_type_id,
            entry_type=entry_type,
            days_delta=amount,
            leave_year=entry_year,
            reason=f"Reviewed year-end leave rollover {year} to {target}",
            actor_user_id=actor.id,
        )
        session.add(row)
        return row

    debit = add_entry("carry_forward_out", -carry, year) if carry else None
    credit = add_entry("carry_forward_in", carry, target) if carry else None
    expired = add_entry("expiry", -expiry, year) if expiry else None
    await session.flush()
    receipt = HrLeaveRollover(
        employee_id=employee.id,
        leave_type_id=payload.leave_type_id,
        policy_id=policy.id,
        source_year=year,
        carried_days=carry,
        expired_days=expiry,
        transferred_out_id=debit.id if debit else None,
        transferred_in_id=credit.id if credit else None,
        expiry_entry_id=expired.id if expired else None,
        actor_user_id=actor.id,
        plan_digest=digest,
    )
    session.add(receipt)
    await session.flush()
    await AuditService(session).record(
        action="hr.leave_rollover.posted",
        user_id=actor.id,
        entity_type="hr_leave_rollovers",
        entity_id=receipt.id,
        new_values={
            "source_year": year,
            "carried_days": str(carry),
            "expired_days": str(expiry),
        },
    )
    await session.commit()
    return quote.model_copy(update={"receipt_id": receipt.id})
