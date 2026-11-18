from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.hr import (
    HrAttendanceEntry,
    HrEmployee,
    HrLeaveRequest,
    HrOvertimeRequest,
    HrTimesheet,
)
from app.models.user import User
from app.schemas.hr import (
    ManagerReviewDecisionRequest,
    ManagerReviewItemResponse,
    ManagerReviewKind,
    ManagerReviewListResponse,
)
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.security import utc_now

REVIEW_EMPLOYMENT_STATES = ("active", "on_probation", "on_leave", "notice_period")
ReviewRequest = HrAttendanceEntry | HrLeaveRequest | HrOvertimeRequest | HrTimesheet
REVIEW_MODELS: dict[ManagerReviewKind, type[ReviewRequest]] = {
    "attendance": HrAttendanceEntry,
    "leave": HrLeaveRequest,
    "overtime": HrOvertimeRequest,
    "timesheet": HrTimesheet,
}


def _submitter(record: ReviewRequest) -> UUID | None:
    if isinstance(record, HrAttendanceEntry):
        return record.recorded_by_id
    return record.submitted_by_id if isinstance(record, HrTimesheet) else record.requested_by_id


async def eligible_reviewer(
    session: AsyncSession, employee: HrEmployee, submitter_id: UUID | None = None
) -> UUID | None:
    if (
        employee.line_manager_reviewer_id is None
        or employee.line_manager_reviewer_id != employee.manager_employee_id
        or employee.line_manager_reviewer_id == employee.id
        or employee.employment_status not in REVIEW_EMPLOYMENT_STATES
    ):
        return None
    reviewer_user_id = await session.scalar(
        select(User.id)
        .join(HrEmployee, HrEmployee.user_id == User.id)
        .where(
            HrEmployee.id == employee.line_manager_reviewer_id,
            HrEmployee.deleted_at.is_(None),
            HrEmployee.employment_status.in_(REVIEW_EMPLOYMENT_STATES),
            User.deleted_at.is_(None),
            User.is_active.is_(True),
        )
    )
    return reviewer_user_id if reviewer_user_id not in {employee.user_id, submitter_id} else None


async def start_manager_review(
    session: AsyncSession, record: ReviewRequest, employee: HrEmployee
) -> None:
    record.requires_manager_recommendation = (
        get_settings().hr_line_manager_review_enabled
        and await eligible_reviewer(session, employee, _submitter(record)) is not None
    )
    record.manager_recommendation = None
    record.manager_recommended_by_id = None
    record.manager_recommended_at = None


def verify_request_revision(record: ReviewRequest, expected: int | None) -> None:
    if expected is not None and expected != record.record_revision:
        raise AppException(
            "The request changed. Reload it before deciding.",
            status_code=409,
            error_code="REVISION_CONFLICT",
        )


async def require_manager_recommendation(
    session: AsyncSession,
    record: ReviewRequest,
    employee: HrEmployee,
    actor: User,
    expected_revision: int | None,
) -> None:
    if record.manager_recommendation is not None:
        if record.manager_recommended_by_id == actor.id:
            raise PermissionDeniedException(
                "make the final HR decision after your own recommendation"
            )
        if expected_revision is None:
            raise AppException(
                "Reload the recommended request before making a final decision.",
                status_code=409,
                error_code="REVISION_REQUIRED",
            )
    if (
        not record.requires_manager_recommendation
        or not get_settings().hr_line_manager_review_enabled
    ):
        return
    reviewer_id = await eligible_reviewer(session, employee, _submitter(record))
    if reviewer_id is None:
        return
    if record.manager_recommended_by_id != reviewer_id or record.manager_recommendation is None:
        raise AppException(
            "This request is awaiting its line-manager recommendation.",
            status_code=409,
            error_code="MANAGER_RECOMMENDATION_REQUIRED",
        )
    if expected_revision is None:
        raise AppException(
            "Reload the recommended request before making a final decision.",
            status_code=409,
            error_code="REVISION_REQUIRED",
        )


async def can_review_direct_reports(session: AsyncSession, manager: HrEmployee) -> bool:
    if not get_settings().hr_line_manager_review_enabled:
        return False
    return (
        await session.scalar(
            select(HrEmployee.id)
            .where(
                HrEmployee.id != manager.id,
                HrEmployee.manager_employee_id == manager.id,
                HrEmployee.line_manager_reviewer_id == manager.id,
                HrEmployee.deleted_at.is_(None),
                HrEmployee.employment_status.in_(REVIEW_EMPLOYMENT_STATES),
            )
            .limit(1)
        )
        is not None
    )


async def list_manager_reviews(
    session: AsyncSession,
    manager: HrEmployee,
    actor: User,
    *,
    offset: int,
    limit: int,
) -> ManagerReviewListResponse:
    if not get_settings().hr_line_manager_review_enabled:
        raise NotFoundException("Line manager reviews")
    selections = []
    # Only availability data is projected. Leave types, notes, documents, rate and salary
    # data are visible to their owning workflows and never enter the manager queue.
    for kind, (model, start, end, amount, submitter) in (
        (
            "attendance",
            (
                HrAttendanceEntry,
                HrAttendanceEntry.work_date,
                HrAttendanceEntry.work_date,
                HrAttendanceEntry.worked_hours,
                HrAttendanceEntry.recorded_by_id,
            ),
        ),
        (
            "leave",
            (
                HrLeaveRequest,
                HrLeaveRequest.start_date,
                HrLeaveRequest.end_date,
                HrLeaveRequest.days_requested,
                HrLeaveRequest.requested_by_id,
            ),
        ),
        (
            "timesheet",
            (
                HrTimesheet,
                HrTimesheet.period_start,
                HrTimesheet.period_end,
                HrTimesheet.regular_hours + HrTimesheet.overtime_hours,
                HrTimesheet.submitted_by_id,
            ),
        ),
        (
            "overtime",
            (
                HrOvertimeRequest,
                HrOvertimeRequest.work_date,
                HrOvertimeRequest.work_date,
                HrOvertimeRequest.requested_hours,
                HrOvertimeRequest.requested_by_id,
            ),
        ),
    ):
        selections.append(
            select(
                literal(kind).label("kind"),
                model.id,
                HrEmployee.full_name.label("employee_name"),
                start.label("start_date"),
                end.label("end_date"),
                amount.label("requested_amount"),
                model.record_revision,
            )
            .join(HrEmployee, HrEmployee.id == model.employee_id)
            .where(
                HrEmployee.id != manager.id,
                HrEmployee.user_id.is_distinct_from(actor.id),
                HrEmployee.manager_employee_id == manager.id,
                HrEmployee.line_manager_reviewer_id == manager.id,
                HrEmployee.deleted_at.is_(None),
                HrEmployee.employment_status.in_(REVIEW_EMPLOYMENT_STATES),
                model.status == "submitted",
                model.requires_manager_recommendation.is_(True),
                model.manager_recommended_by_id.is_distinct_from(actor.id),
                submitter.is_distinct_from(actor.id),
            )
        )
    queue = union_all(*selections).subquery()
    rows = (
        (
            await session.execute(
                select(queue)
                .order_by(queue.c.start_date, queue.c.kind, queue.c.id)
                .offset(offset)
                .limit(limit + 1)
            )
        )
        .mappings()
        .all()
    )
    return ManagerReviewListResponse(
        items=[ManagerReviewItemResponse.model_validate(row) for row in rows[:limit]],
        has_more=len(rows) > limit,
    )


async def recommend_request(
    session: AsyncSession,
    *,
    kind: ManagerReviewKind,
    request_id: UUID,
    payload: ManagerReviewDecisionRequest,
    actor: User,
) -> ManagerReviewItemResponse:
    if not get_settings().hr_line_manager_review_enabled:
        raise NotFoundException("Line manager review")
    model = REVIEW_MODELS[kind]
    employee = None
    if kind == "attendance":
        employee_id = await session.scalar(
            select(HrAttendanceEntry.employee_id).where(HrAttendanceEntry.id == request_id)
        )
        if employee_id is None:
            raise NotFoundException("Line manager review")
        employee = await session.scalar(
            select(HrEmployee)
            .where(HrEmployee.id == employee_id, HrEmployee.deleted_at.is_(None))
            .with_for_update()
        )
    record = cast(
        ReviewRequest | None,
        await session.scalar(select(model).where(model.id == request_id).with_for_update()),
    )
    if record is None or not record.requires_manager_recommendation:
        raise NotFoundException("Line manager review")
    if employee is None and kind != "attendance":
        employee = await session.scalar(
            select(HrEmployee)
            .where(HrEmployee.id == record.employee_id, HrEmployee.deleted_at.is_(None))
            .with_for_update()
        )
    if (
        employee is None
        or await eligible_reviewer(session, employee, _submitter(record)) != actor.id
    ):
        raise NotFoundException("Line manager review")
    verify_request_revision(record, payload.expected_revision)
    if record.status != "submitted" or record.manager_recommended_by_id == actor.id:
        raise AppException("This review is already decided.", status_code=409)

    record.manager_recommendation = payload.recommendation
    record.manager_recommended_by_id = actor.id
    record.manager_recommended_at = utc_now()
    record.record_revision += 1
    start: date
    end: date
    amount: Decimal
    if isinstance(record, HrLeaveRequest):
        start, end, amount = record.start_date, record.end_date, record.days_requested
    elif isinstance(record, HrTimesheet):
        start, end = record.period_start, record.period_end
        amount = record.regular_hours + record.overtime_hours
    elif isinstance(record, HrAttendanceEntry):
        start = end = record.work_date
        amount = record.worked_hours
    else:
        start = end = record.work_date
        amount = record.requested_hours
    projected = ManagerReviewItemResponse(
        kind=kind,
        id=record.id,
        employee_name=employee.full_name,
        start_date=start,
        end_date=end,
        requested_amount=amount,
        record_revision=record.record_revision,
    )
    await AuditService(session).record(
        action=f"hr.{kind}.manager_recommended",
        user_id=actor.id,
        entity_type=model.__tablename__,
        entity_id=record.id,
        new_values={"recommendation": payload.recommendation},
    )
    await session.commit()
    return projected
