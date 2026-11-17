from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.support_case_actions import SupportCaseProject
from app.models.support_cases import SupportCase, SupportCaseMember, SupportOperatorGrant
from app.models.support_directory import SupportCaseSubject, SupportDirectoryRead
from app.models.user import User
from app.services.support_identity import SupportIdentity, support_session_deadline
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import BUSINESS_ROLES, permissions_for_role
from app.utils.recovery_destination import verified_recovery_destination
from app.utils.security import utc_now

_AuthEvent = Literal[
    "login_succeeded",
    "login_failed",
    "session_replay_revoked",
    "password_changed",
    "password_recovered",
]
_EVENTS: dict[str, _AuthEvent] = {
    "auth.login_success": "login_succeeded",
    "auth.login_failed": "login_failed",
    "auth.refresh_replay_revoked_session": "session_replay_revoked",
    "auth.password_changed": "password_changed",
    "auth.password_reset_completed": "password_recovered",
}


class SupportAccountEvent(BaseModel):
    id: UUID
    occurred_at: datetime
    category: _AuthEvent


class SupportAccountSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    field: Literal["email", "employee_code", "name", "role"]
    value: str = Field(min_length=1, max_length=254, repr=False)

    @model_validator(mode="after")
    def check_selector(self) -> "SupportAccountSelector":
        if self.field == "name" and len(self.value) < 3:
            raise ValueError("Enter at least three characters for a name search.")
        if self.field == "role" and self.value.casefold() not in BUSINESS_ROLES:
            raise ValueError("Choose a supported business role.")
        return self


class SupportAccountRead(BaseModel):
    case_id: UUID
    case_revision: int
    user_id: UUID
    display_name: str
    email_masked: str
    employee_code: str | None
    role: str
    permissions: list[str]
    access_revision: int
    active: bool
    deleted: bool
    locked: bool
    recovery_destination_verified: bool | None
    membership_ids: list[UUID]
    recent_auth_events: list[SupportAccountEvent]


def _masked_email(email: str) -> str:
    account, sep, domain = email.rpartition("@")
    return f"{account[:1]}***@{domain}" if sep and account and domain else "***"


async def read_support_account(
    session: AsyncSession,
    token: str | None,
    case_id: UUID,
    request_id: str,
    *,
    user_id: UUID | None = None,
    selector: SupportAccountSelector | None = None,
) -> SupportAccountRead:
    operator, active = await SupportIdentity(session).current(token)
    grant = await session.get(
        SupportOperatorGrant, (operator.id, "directory.read"), with_for_update=True
    )
    if grant is None:
        raise PermissionDeniedException("directory.read")
    case = await session.get(SupportCase, case_id, with_for_update=True)
    if case is None or case.status not in {"open", "investigating"}:
        raise NotFoundException("Support account")
    member = await session.get(SupportCaseMember, (case.id, operator.id), with_for_update=True)
    subject = await session.get(SupportCaseSubject, case.id, with_for_update=True)
    if member is None or subject is None or (user_id is not None and subject.user_id != user_id):
        raise NotFoundException("Support account")
    now = utc_now()
    count = await session.scalar(
        select(func.count())
        .select_from(SupportDirectoryRead)
        .where(
            SupportDirectoryRead.operator_id == operator.id,
            SupportDirectoryRead.occurred_at > now - timedelta(minutes=1),
        )
    )
    if count is not None and count >= 20:
        raise AppException(
            "Wait before checking more support accounts.",
            status_code=429,
            error_code="SUPPORT_DIRECTORY_RATE_LIMIT",
        )
    row = (
        await session.execute(
            select(
                User.id,
                User.full_name,
                User.email,
                User.employee_code,
                User.role,
                User.access_revision,
                User.is_active,
                User.deleted_at,
                User.locked_until,
                User.recovery_email_digest,
                User.recovery_email_verified_at,
            ).where(User.id == subject.user_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundException("Support account")
    show_recovery_status = (
        await session.get(SupportOperatorGrant, (operator.id, "account.request")) is not None
    )
    recovery_verified = None
    if show_recovery_status or (selector is not None and selector.field == "email"):
        recovery_verified = (
            row.role in BUSINESS_ROLES
            and row.is_active
            and row.deleted_at is None
            and verified_recovery_destination(
                get_settings(), row.id, row.email,
                row.recovery_email_digest, row.recovery_email_verified_at,
            ) is not None
        )
    if selector is not None:
        if selector.field == "email":
            match = recovery_verified is True and row.email.casefold() == selector.value.casefold()
        elif selector.field == "employee_code":
            match = (row.employee_code or "").casefold() == selector.value.casefold()
        elif selector.field == "name":
            match = selector.value.casefold() in row.full_name.casefold()
        else:
            match = row.role == selector.value.casefold()
        if not match:
            raise NotFoundException("Support account")
    events = (
        await session.execute(
            select(ActivityLog.id, ActivityLog.created_at, ActivityLog.action)
            .where(
                ActivityLog.user_id == row.id,
                ActivityLog.action.in_(_EVENTS),
                ActivityLog.deleted_at.is_(None),
                ActivityLog.created_at > now - timedelta(hours=24),
            )
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(25)
        )
    ).all()
    memberships = await session.scalars(
        select(ProjectMember.id)
        .join(SupportCaseProject, SupportCaseProject.project_id == ProjectMember.project_id)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(
            SupportCaseProject.case_id == case.id,
            ProjectMember.user_id == row.id,
            ProjectMember.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
        .order_by(ProjectMember.id)
    )
    now = utc_now()
    if support_session_deadline(active) <= now:
        raise AppException(
            "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
        )
    result = SupportAccountRead(
        case_id=case.id,
        case_revision=case.revision,
        user_id=row.id,
        display_name=row.full_name,
        email_masked=_masked_email(row.email),
        employee_code=row.employee_code,
        role=row.role,
        permissions=permissions_for_role(row.role),
        access_revision=row.access_revision,
        active=row.is_active and row.deleted_at is None,
        deleted=row.deleted_at is not None,
        locked=row.locked_until is not None and row.locked_until > now,
        recovery_destination_verified=recovery_verified if show_recovery_status else None,
        membership_ids=list(memberships),
        recent_auth_events=[
            SupportAccountEvent(id=event_id, occurred_at=when, category=_EVENTS[action])
            for event_id, when, action in events
        ],
    )
    session.add(
        SupportDirectoryRead(
            id=uuid4(),
            case_id=case.id,
            operator_id=operator.id,
            subject_user_id=row.id,
            request_id=request_id,
            occurred_at=now,
        )
    )
    active.last_seen_at = now
    await session.commit()
    return result
