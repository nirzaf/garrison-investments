from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, exists, false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.hr import HrEmployee, HrLeaveRequest
from app.models.notification import Notification
from app.models.user import User
from app.services.hr_manager_review import REVIEW_EMPLOYMENT_STATES
from app.utils.permissions import (
    BUSINESS_ROLES,
    PERMISSION_HR_LEAVE_APPROVE,
    roles_with_permission,
)
from app.utils.time import business_today

PENDING_LEAVE_EVENTS = ("submitted", "resubmitted", "rerouted")


def _manager_exists(
    request: type[HrLeaveRequest],
    employee: type[HrEmployee],
    *,
    assigned_to_requester: bool = False,
) -> ColumnElement[bool]:
    manager = aliased(HrEmployee)
    manager_user = aliased(User)
    filters = [
        manager.id == employee.manager_employee_id,
        manager.id != employee.id,
        manager.deleted_at.is_(None),
        manager.employment_status.in_(REVIEW_EMPLOYMENT_STATES),
        manager_user.is_active.is_(True),
        manager_user.deleted_at.is_(None),
        manager_user.role.in_(BUSINESS_ROLES),
        or_(employee.user_id.is_(None), manager_user.id != employee.user_id),
        or_(request.requested_by_id.is_(None), manager_user.id != request.requested_by_id),
    ]
    if assigned_to_requester:
        filters.append(manager_user.id == request.assigned_supervisor_user_id)
    return exists(
        select(1)
        .select_from(manager)
        .join(manager_user, manager_user.id == manager.user_id)
        .where(*filters)
    )


def _current_leave_route_for_recipient(user: User) -> ColumnElement[bool]:
    """Match live leave routing without loading request reasons or attachments."""
    if not user.is_active or user.deleted_at is not None or user.role not in BUSINESS_ROLES:
        return false()

    request = aliased(HrLeaveRequest)
    employee = aliased(HrEmployee)
    today = business_today()
    manager_is_eligible = _manager_exists(request, employee)
    assigned_manager_is_eligible = _manager_exists(request, employee, assigned_to_requester=True)
    absence = aliased(HrLeaveRequest)
    manager_is_absent = exists(
        select(1)
        .select_from(absence)
        .where(
            absence.employee_id == employee.manager_employee_id,
            absence.status == "approved",
            absence.start_date <= today,
            absence.end_date >= today,
        )
    )

    manager_missing = and_(
        request.fallback_reason_code == "manager_missing",
        request.fallback_reason == "No valid direct supervisor is assigned.",
        request.assigned_supervisor_user_id.is_(None),
        request.fallback_until.is_(None),
        or_(employee.manager_employee_id.is_(None), employee.manager_employee_id == employee.id),
    )
    manager_ineligible = and_(
        request.fallback_reason_code == "manager_ineligible",
        request.fallback_reason == "The assigned direct supervisor is unavailable.",
        request.assigned_supervisor_user_id.is_(None),
        request.fallback_until.is_(None),
        employee.manager_employee_id.is_not(None),
        employee.manager_employee_id != employee.id,
        ~manager_is_eligible,
    )
    manager_absent = and_(
        request.fallback_reason_code == "manager_absent",
        request.fallback_reason == "The assigned direct supervisor is on approved leave.",
        request.assigned_supervisor_user_id.is_(None),
        request.fallback_until.is_(None),
        manager_is_eligible,
        manager_is_absent,
    )
    temporary_fallback_current = and_(
        request.fallback_reason_code == "manager_temporarily_unavailable",
        request.assigned_supervisor_user_id.is_not(None),
        request.fallback_until.is_not(None),
        request.fallback_until >= today,
        assigned_manager_is_eligible,
        ~manager_is_absent,
    )

    supervisor_route_current = and_(
        request.approval_route == "supervisor",
        request.assigned_supervisor_user_id == user.id,
        request.fallback_until.is_(None),
        assigned_manager_is_eligible,
        ~manager_is_absent,
    )
    hr_route_current = (
        and_(
            request.approval_route == "hr_fallback",
            or_(manager_missing, manager_ineligible, manager_absent, temporary_fallback_current),
        )
        if user.role in roles_with_permission(PERMISSION_HR_LEAVE_APPROVE)
        else false()
    )

    return exists(
        select(1)
        .select_from(request)
        .join(employee, employee.id == request.employee_id)
        .where(
            request.id == Notification.reference_id,
            request.status == "submitted",
            request.record_revision == Notification.event_revision,
            employee.deleted_at.is_(None),
            employee.employment_status.in_(REVIEW_EMPLOYMENT_STATES),
            or_(employee.user_id.is_(None), Notification.user_id != employee.user_id),
            or_(request.requested_by_id.is_(None), Notification.user_id != request.requested_by_id),
            Notification.user_id == user.id,
            or_(supervisor_route_current, hr_route_current),
        )
    )


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, notification_id: UUID) -> Notification | None:
        result = await self.session.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def add(self, notification: Notification) -> Notification:
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def get_for_user(self, notification_id: UUID, user_id: UUID) -> Notification | None:
        result = await self.session.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
                Notification.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> tuple[list[Notification], int]:
        query = select(Notification).where(
            Notification.user_id == user_id,
            Notification.deleted_at.is_(None),
        )
        total = await self.session.scalar(
            select(func.count()).select_from(query.with_only_columns(Notification.id).subquery())
        )
        result = await self.session.execute(
            query.order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def actionable_leave_notification_ids(
        self, notification_ids: set[UUID], user: User
    ) -> set[UUID]:
        if not notification_ids:
            return set()
        result = await self.session.scalars(
            select(Notification.id).where(
                Notification.id.in_(notification_ids),
                Notification.user_id == user.id,
                Notification.deleted_at.is_(None),
                Notification.superseded_at.is_(None),
                Notification.reference_type == "hr_leave_request",
                Notification.event_code.in_(PENDING_LEAVE_EVENTS),
                _current_leave_route_for_recipient(user),
            )
        )
        return set(result)

    async def unread_count(self, user: User) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user.id,
                Notification.is_read.is_(False),
                Notification.muted.is_(False),
                Notification.deleted_at.is_(None),
                or_(
                    Notification.reference_type.is_(None),
                    Notification.reference_type != "hr_leave_request",
                    Notification.event_code.is_(None),
                    Notification.event_code.not_in(PENDING_LEAVE_EVENTS),
                    and_(
                        Notification.superseded_at.is_(None),
                        _current_leave_route_for_recipient(user),
                    ),
                ),
            )
        )
        return int(total or 0)

    async def mark_all_read(self, user_id: UUID, read_at: datetime) -> int:
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.deleted_at.is_(None),
            )
            .values(
                is_read=True,
                read_at=func.coalesce(Notification.read_at, read_at),
            )
            .returning(Notification.id)
            .execution_options(synchronize_session=False)
        )
        return len(result.scalars().all())
