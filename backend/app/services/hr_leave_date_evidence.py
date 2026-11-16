"""Reconcile missing historical work dates while retaining approved leave and its debit."""

import hashlib
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import (
    HrEmployee,
    HrLeaveDateEvidence,
    HrLeaveLedger,
    HrLeaveRequest,
    HrPayrollLine,
    HrPayrollPeriod,
    HrPayrollRun,
)
from app.models.user import User
from app.schemas.hr import (
    LeaveDateEvidenceCandidate,
    LeaveDateEvidenceCandidates,
    LeaveDateEvidenceCreate,
    LeaveDateEvidenceDecision,
    LeaveDateEvidenceDetail,
    LeaveDateEvidencePage,
    LeaveDateEvidenceResponse,
)
from app.services.audit_service import AuditService
from app.services.hr_crypto import decrypt_hr_value, encrypt_hr_value
from app.services.hr_manager_review import verify_request_revision
from app.services.hr_payroll_snapshot import lock_payroll_periods
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_LEAVE_APPROVE,
    PERMISSION_HR_LEAVE_MANAGE,
    ensure_permission,
    has_permission,
)
from app.utils.security import utc_now


async def _require_request(
    session: AsyncSession, request_id: UUID, *, locked: bool = False
) -> HrLeaveRequest:
    row = await session.get(HrLeaveRequest, request_id, with_for_update=locked)
    if row is None:
        raise NotFoundException("Leave request")
    return row


def _is_missing_legacy_dates(row: HrLeaveRequest) -> bool:
    return (
        row.status == "approved"
        and row.decided_at is not None
        and row.scheduled_work_dates is None
        and not row.is_half_day
        and (row.start_date.year, row.start_date.month) < (row.end_date.year, row.end_date.month)
    )


def _require_legacy_dates(row: HrLeaveRequest, work_dates: list[date]) -> None:
    if not _is_missing_legacy_dates(row):
        raise AppException(
            "Only approved cross-month leave missing historical dates is eligible.",
            status_code=409,
        )
    if any(not row.start_date <= day <= row.end_date for day in work_dates) or (
        Decimal(len(work_dates)) != row.days_requested
    ):
        raise AppException(
            "The historical dates must be within the approved range and match its units.",
            status_code=422,
        )


async def require_approved_leave_debit(session: AsyncSession, request: HrLeaveRequest) -> UUID:
    rows = list(await session.scalars(
        select(HrLeaveLedger)
        .where(HrLeaveLedger.reference_request_id == request.id)
        .with_for_update()
        .limit(2)
    ))
    if (
        request.days_requested <= 0
        or request.decided_at is None
        or len(rows) != 1
        or rows[0].entry_type != "taken"
        or rows[0].employee_id != request.employee_id
        or rows[0].leave_type_id != request.leave_type_id
        or rows[0].leave_year != request.start_date.year
        or rows[0].days_delta != -request.days_requested
    ):
        raise AppException("The approved leave does not match its ledger debit.", status_code=409)
    return rows[0].id


async def _employee(session: AsyncSession, request: HrLeaveRequest) -> HrEmployee:
    # Existing leave decisions lock the request before the employee. Payroll
    # source readers take the employee lock before reading leave and ledger rows.
    employee = await session.get(HrEmployee, request.employee_id, with_for_update=True)
    if employee is None or employee.deleted_at is not None:
        raise NotFoundException("Leave employee")
    return employee


def _payroll_already_approved() -> ColumnElement[bool]:
    return (
        select(HrPayrollLine.id)
        .join(HrPayrollRun, HrPayrollLine.payroll_run_id == HrPayrollRun.id)
        .join(HrPayrollPeriod, HrPayrollRun.payroll_period_id == HrPayrollPeriod.id)
        .where(
            HrPayrollLine.employee_id == HrLeaveRequest.employee_id,
            HrPayrollRun.status == "approved",
            HrPayrollPeriod.period_start <= HrLeaveRequest.end_date,
            HrPayrollPeriod.period_end >= HrLeaveRequest.start_date,
        )
        .correlate(HrLeaveRequest)
        .exists()
    )


async def _has_approved_payroll(session: AsyncSession, request_id: UUID) -> bool:
    return bool(await session.scalar(
        select(_payroll_already_approved()).select_from(HrLeaveRequest)
        .where(HrLeaveRequest.id == request_id)
    ))


async def require_unlocked_leave_payroll(session: AsyncSession, request: HrLeaveRequest) -> None:
    if await _has_approved_payroll(session, request.id):
        raise AppException(
            "Use the payroll correction procedure for a locked payroll period.",
            status_code=409,
            error_code="LEAVE_PAYROLL_LOCKED",
        )


async def list_missing_leave_dates(
    session: AsyncSession, actor: User, *, employee_id: UUID | None, limit: int, offset: int
) -> LeaveDateEvidenceCandidates:
    ensure_permission(actor, PERMISSION_HR_LEAVE_MANAGE)
    criteria = [
        HrLeaveRequest.status == "approved",
        HrLeaveRequest.decided_at.is_not(None),
        HrLeaveRequest.scheduled_work_dates.is_(None),
        HrLeaveRequest.is_half_day.is_(False),
        func.date_trunc("month", HrLeaveRequest.start_date)
        < func.date_trunc("month", HrLeaveRequest.end_date),
        HrEmployee.deleted_at.is_(None),
    ]
    if employee_id is not None:
        criteria.append(HrLeaveRequest.employee_id == employee_id)
    total = await session.scalar(
        select(func.count()).select_from(HrLeaveRequest)
        .join(HrEmployee, HrLeaveRequest.employee_id == HrEmployee.id).where(*criteria)
    )
    result = await session.execute(
        select(
            HrLeaveRequest.id, HrLeaveRequest.employee_id, HrLeaveRequest.start_date,
            HrLeaveRequest.end_date, HrLeaveRequest.days_requested, _payroll_already_approved(),
        )
        .join(HrEmployee, HrLeaveRequest.employee_id == HrEmployee.id).where(*criteria)
        .order_by(HrLeaveRequest.start_date, HrLeaveRequest.id)
        .limit(limit).offset(offset)
    )
    return LeaveDateEvidenceCandidates(
        items=[
            LeaveDateEvidenceCandidate(
                request_id=request_id,
                employee_id=owner_id,
                start_date=start,
                end_date=end,
                approved_units=units,
                requires_payroll_correction=locked,
            )
            for request_id, owner_id, start, end, units, locked in result
        ],
        total=total or 0,
    )


def _response(row: HrLeaveDateEvidence) -> LeaveDateEvidenceResponse:
    detail = LeaveDateEvidenceDetail.model_validate_json(
        decrypt_hr_value(row.detail_encrypted) or ""
    )
    return LeaveDateEvidenceResponse(
        **detail.model_dump(),
        id=row.id,
        request_revision=row.request_revision,
        status=row.status,
        digest=hashlib.sha256(row.detail_encrypted.encode()).hexdigest(),
        submitted_by_id=row.submitted_by_id,
        decided_by_id=row.decided_by_id,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


async def list_leave_date_evidence(
    session: AsyncSession, request_id: UUID, actor: User, *, limit: int, offset: int
) -> LeaveDateEvidencePage:
    ensure_permission(actor, PERMISSION_HR_LEAVE_MANAGE)
    request = await _require_request(session, request_id)
    employee = await session.get(HrEmployee, request.employee_id)
    independent = (
        employee is not None
        and employee.deleted_at is None
        and actor.id not in {employee.user_id, request.requested_by_id}
    )
    total = await session.scalar(
        select(func.count()).select_from(HrLeaveDateEvidence)
        .where(HrLeaveDateEvidence.request_id == request.id)
    )
    rows = await session.scalars(
        select(HrLeaveDateEvidence)
        .where(HrLeaveDateEvidence.request_id == request.id)
        .order_by(HrLeaveDateEvidence.created_at.desc(), HrLeaveDateEvidence.id.desc())
        .limit(limit).offset(offset)
    )
    locked = await _has_approved_payroll(session, request.id)
    return LeaveDateEvidencePage(
        request_id=request.id,
        request_revision=request.record_revision,
        start_date=request.start_date,
        end_date=request.end_date,
        approved_units=request.days_requested,
        scheduled_work_dates=request.scheduled_work_dates,
        requires_payroll_correction=locked,
        can_propose=independent and not locked and _is_missing_legacy_dates(request),
        can_review=independent and has_permission(actor, PERMISSION_HR_LEAVE_APPROVE),
        items=[_response(row) for row in rows],
        total=total or 0,
    )


async def read_leave_date_evidence(
    session: AsyncSession, request_id: UUID, proposal_id: UUID, actor: User
) -> LeaveDateEvidenceResponse:
    ensure_permission(actor, PERMISSION_HR_LEAVE_MANAGE)
    row = await session.get(HrLeaveDateEvidence, proposal_id)
    if row is None or row.request_id != request_id:
        raise NotFoundException("Leave date evidence")
    return _response(row)


async def _audit(
    session: AsyncSession, actor: User, row: HrLeaveDateEvidence, action: str
) -> None:
    await AuditService(session).record(
        action=f"hr.leave_date_evidence.{action}",
        user_id=actor.id,
        entity_type="hr_leave_requests",
        entity_id=row.request_id,
        new_values={"evidence_id": str(row.id)},
    )
    await session.commit()


async def propose_leave_date_evidence(
    session: AsyncSession, request_id: UUID, payload: LeaveDateEvidenceCreate, actor: User
) -> LeaveDateEvidenceResponse:
    ensure_permission(actor, PERMISSION_HR_LEAVE_MANAGE)
    await lock_payroll_periods(session)
    request = await _require_request(session, request_id, locked=True)
    employee = await _employee(session, request)
    if employee.user_id == actor.id or request.requested_by_id == actor.id:
        raise PermissionDeniedException("propose evidence for your own leave")
    prior = await session.get(HrLeaveDateEvidence, payload.proposal_id)
    if prior is not None:
        if prior.request_id == request.id and prior.submitted_by_id == actor.id:
            previous = _response(prior)
            if (
                previous.request_revision == payload.expected_revision
                and previous.work_dates == payload.work_dates
                and previous.evidence_reference == payload.evidence_reference
            ):
                return previous
        raise AppException("The evidence ID already refers to another proposal.", status_code=409)
    verify_request_revision(request, payload.expected_revision)
    _require_legacy_dates(request, payload.work_dates)
    await require_unlocked_leave_payroll(session, request)
    debit_id = await require_approved_leave_debit(session, request)
    if await session.scalar(
        select(HrLeaveDateEvidence.id)
        .where(
            HrLeaveDateEvidence.request_id == request.id,
            HrLeaveDateEvidence.status == "submitted",
        )
        .limit(1)
    ):
        raise AppException("Resolve the pending work-date evidence first.", status_code=409)
    detail = LeaveDateEvidenceDetail(
        work_dates=payload.work_dates, evidence_reference=payload.evidence_reference
    )
    encrypted = encrypt_hr_value(detail.model_dump_json())
    assert encrypted is not None
    row = await session.scalar(
        insert(HrLeaveDateEvidence)
        .values(
            id=payload.proposal_id,
            request_id=request.id,
            ledger_id=debit_id,
            request_revision=request.record_revision,
            submitted_by_id=actor.id,
            detail_encrypted=encrypted,
        )
        .on_conflict_do_nothing(index_elements=[HrLeaveDateEvidence.id])
        .returning(HrLeaveDateEvidence)
    )
    if row is None:
        raise AppException("The evidence ID already refers to another proposal.", status_code=409)
    result = _response(row)
    await _audit(session, actor, row, "submitted")
    return result


async def decide_leave_date_evidence(
    session: AsyncSession, request_id: UUID, proposal_id: UUID, payload: LeaveDateEvidenceDecision,
    actor: User,
) -> LeaveDateEvidenceResponse:
    ensure_permission(actor, PERMISSION_HR_LEAVE_APPROVE)
    await lock_payroll_periods(session)
    request = await _require_request(session, request_id, locked=True)
    employee = await _employee(session, request)
    row = await session.get(HrLeaveDateEvidence, proposal_id)
    if row is None or row.request_id != request.id:
        raise NotFoundException("Leave date evidence")
    if actor.id in {row.submitted_by_id, employee.user_id, request.requested_by_id}:
        raise PermissionDeniedException("independently review the leave date evidence")
    reviewed = _response(row)
    if reviewed.digest != payload.expected_digest:
        raise AppException("Confirm the exact historical work-date evidence.", status_code=409)
    if row.status == payload.decision and row.decided_by_id == actor.id:
        return reviewed
    if row.status != "submitted":
        raise AppException("This evidence already has a final decision.", status_code=409)
    if payload.decision == "approved":
        verify_request_revision(request, row.request_revision)
        _require_legacy_dates(request, reviewed.work_dates)
        await require_unlocked_leave_payroll(session, request)
        if await require_approved_leave_debit(session, request) != row.ledger_id:
            raise AppException("The leave debit changed after submission.", status_code=409)
        request.scheduled_work_dates = reviewed.work_dates
        request.record_revision += 1
    row.status = payload.decision
    row.decided_by_id = actor.id
    row.decided_at = utc_now()
    result = _response(row)
    await _audit(session, actor, row, payload.decision)
    return result
