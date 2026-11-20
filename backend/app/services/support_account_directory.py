"""Company account directory, User 360 profile, session inventory, and data inspector."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.activity_log import ActivityLog
from app.models.auth import AuthRefreshToken, AuthSession
from app.models.hr import HrEmployee
from app.models.inventory import InventoryItem, StorageLocation
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.supplier import Supplier
from app.models.support_admin_commands import SupportAdminCommand
from app.models.support_business_actions import SupportBusinessAction
from app.models.support_case_actions import SupportCaseProject
from app.models.support_cases import SupportCase, SupportCaseEvent, SupportCaseMember
from app.models.support_directory import SupportCaseSubject
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.support_company_admin import (
    SupportAccessExplanationItem,
    SupportCompanyUserAccessRead,
    SupportCompanyUserPage,
    SupportCompanyUserProfileRead,
    SupportCompanyUserSummary,
    SupportDataInspectorCatalogRead,
    SupportDataInspectorEntityMeta,
    SupportDataInspectorPage,
    SupportDiagnoseCaseRead,
    SupportDiagnoseCaseRequest,
    SupportLinkedCaseSummary,
    SupportNavigationRouteItem,
    SupportProjectOptionRead,
    SupportRoleOption,
    SupportUserActionAvailability,
    SupportUserActivityItem,
    SupportUserActivityPage,
    SupportUserProjectMembershipRead,
    SupportUserSessionInventoryRead,
    SupportUserSessionItem,
)
from app.services.project_service import PROJECT_STATUSES, READ_ONLY_STATUSES
from app.services.support_admin_policy import (
    TECHNICAL_COMMAND_POLICY,
    resolve_support_actor_context,
)
from app.services.support_directory import _EVENTS, _masked_email
from app.services.support_identity import support_session_deadline
from app.services.support_overview import execute_oversight_read
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    BUSINESS_ROLE_LABELS,
    BUSINESS_ROLES,
    COMPANY_RESOURCE_ROLES,
    PERMISSION_PROJECTS_READ,
    PERMISSION_REPORTS_APPROVE,
    PROTECTED_USER_ROLES,
    REPORT_APPROVER_ROLES,
    ROLE_MEP_PROJECT_MANAGER,
    permissions_for_role,
)
from app.utils.portal_navigation import navigation_visibility
from app.utils.recovery_destination import (
    is_recovery_issuance_enabled,
    verified_recovery_destination,
)
from app.utils.redaction import redact_text
from app.utils.security import utc_now


def _masked_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    cleaned = phone.strip()
    if len(cleaned) <= 4:
        return "***"
    return f"***-{cleaned[-4:]}"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _encode_user_cursor(full_name: str, user_id: UUID) -> str:
    raw = f"{full_name.casefold()}\n{user_id}".encode()
    return urlsafe_b64encode(raw).decode("ascii")


def _decode_user_cursor(cursor: str) -> tuple[str, UUID]:
    try:
        decoded = urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        name_part, id_part = decoded.split("\n", 1)
        return name_part, UUID(id_part)
    except (ValueError, Error, UnicodeDecodeError) as exc:
        raise AppException(
            "The directory pagination cursor is invalid.",
            status_code=422,
            error_code="SUPPORT_DIRECTORY_CURSOR_INVALID",
        ) from exc


def _user_state(
    is_active: bool, locked_until: datetime | None, now: datetime
) -> tuple[Literal["active", "inactive", "locked"], bool]:
    is_locked = bool(locked_until is not None and locked_until > now)
    if not is_active:
        return "inactive", is_locked
    if is_locked:
        return "locked", True
    return "active", False


def _is_recovery_verified(user: User) -> bool:
    return bool(
        user.role in BUSINESS_ROLES
        and user.is_active
        and user.deleted_at is None
        and verified_recovery_destination(
            get_settings(),
            user.id,
            user.email,
            user.recovery_email_digest,
            user.recovery_email_verified_at,
        )
        is not None
    )


async def _load_business_user(session: AsyncSession, user_id: UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None or user.role not in BUSINESS_ROLES:
        raise NotFoundException("Business account")
    return user


async def list_company_users(
    session: AsyncSession,
    token: str | None,
    request_id: str,
    *,
    search: str | None = None,
    role: str | None = None,
    state: Literal["active", "inactive", "locked"] | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> SupportCompanyUserPage:
    normalized_role: str | None = None
    if role is not None and role.strip():
        candidate = role.strip().casefold()
        if candidate not in BUSINESS_ROLES:
            raise AppException(
                "Choose a supported business role filter.",
                status_code=422,
                error_code="INVALID_ROLE",
            )
        normalized_role = candidate
    cleaned_search = search.strip() if search else None
    if cleaned_search and len(cleaned_search) > 120:
        raise AppException(
            "Directory search text must be 120 characters or fewer.",
            status_code=422,
            error_code="SUPPORT_DIRECTORY_QUERY_INVALID",
        )
    cursor_pair = _decode_user_cursor(cursor) if cursor else None
    bounded_limit = min(max(limit, 1), 100)

    async def query(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportCompanyUserPage:
        filters: list[ColumnElement[bool]] = [
            User.deleted_at.is_(None),
            User.role.in_(tuple(BUSINESS_ROLES)),
        ]
        if normalized_role is not None:
            filters.append(User.role == normalized_role)
        if state == "inactive":
            filters.append(User.is_active.is_(False))
        elif state == "locked":
            filters.append(User.is_active.is_(True))
            filters.append(User.locked_until.is_not(None))
            filters.append(User.locked_until > now)
        elif state == "active":
            filters.append(User.is_active.is_(True))
            filters.append(or_(User.locked_until.is_(None), User.locked_until <= now))
        if cleaned_search:
            pattern = f"%{_escape_like(cleaned_search.casefold())}%"
            filters.append(
                or_(
                    func.lower(User.full_name).like(pattern, escape="\\"),
                    func.lower(User.email).like(pattern, escape="\\"),
                    func.lower(func.coalesce(User.employee_code, "")).like(pattern, escape="\\"),
                )
            )
        total = int(
            await db.scalar(select(func.count(User.id)).where(*filters)) or 0
        )
        page_filters = list(filters)
        if cursor_pair is not None:
            cursor_name, cursor_id = cursor_pair
            page_filters.append(
                tuple_(func.lower(User.full_name), User.id) > (cursor_name, cursor_id)
            )
        users = list(
            await db.scalars(
                select(User)
                .where(*page_filters)
                .order_by(func.lower(User.full_name).asc(), User.id.asc())
                .limit(bounded_limit + 1)
            )
        )
        has_more = len(users) > bounded_limit
        visible = users[:bounded_limit]
        user_ids = [u.id for u in visible]
        project_counts: dict[UUID, int] = {}
        employee_linked: set[UUID] = set()
        if user_ids:
            proj_rows = (
                await db.execute(
                    select(ProjectMember.user_id, func.count(ProjectMember.id))
                    .join(Project, Project.id == ProjectMember.project_id)
                    .where(
                        ProjectMember.user_id.in_(user_ids),
                        ProjectMember.deleted_at.is_(None),
                        Project.deleted_at.is_(None),
                    )
                    .group_by(ProjectMember.user_id)
                )
            ).all()
            project_counts = {uid: int(cnt) for uid, cnt in proj_rows}
            emp_rows = await db.scalars(
                select(HrEmployee.user_id).where(
                    HrEmployee.user_id.in_(user_ids),
                    HrEmployee.deleted_at.is_(None),
                )
            )
            employee_linked = {uid for uid in emp_rows if uid is not None}

        items: list[SupportCompanyUserSummary] = []
        for u in visible:
            state_label, is_locked = _user_state(u.is_active, u.locked_until, now)
            items.append(
                SupportCompanyUserSummary(
                    user_id=u.id,
                    full_name=u.full_name,
                    email_masked=_masked_email(u.email),
                    employee_code=u.employee_code,
                    designation=u.designation,
                    role=u.role,
                    role_label=BUSINESS_ROLE_LABELS.get(u.role, u.role),
                    state=state_label,
                    is_active=u.is_active,
                    is_locked=is_locked,
                    access_revision=u.access_revision,
                    assigned_project_count=project_counts.get(u.id, 0),
                    has_linked_employee=u.id in employee_linked,
                    recovery_destination_verified=_is_recovery_verified(u),
                    last_login_at=u.last_login_at,
                )
            )
        next_cursor = (
            _encode_user_cursor(visible[-1].full_name, visible[-1].id)
            if has_more and visible
            else None
        )
        return SupportCompanyUserPage(items=items, total=total, next_cursor=next_cursor)

    def degraded(_now: datetime) -> SupportCompanyUserPage:
        raise AppException(
            "The company account directory is temporarily unavailable.",
            status_code=503,
            error_code="SUPPORT_DIRECTORY_UNAVAILABLE",
        )

    return await execute_oversight_read(
        session,
        token,
        capability="company.directory.read",
        surface="company_directory",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def read_company_user_profile(
    session: AsyncSession, token: str | None, user_id: UUID, request_id: str
) -> SupportCompanyUserProfileRead:
    ctx, _, _ = await resolve_support_actor_context(
        session,
        token,
        request_id=request_id,
        required_capability="company.directory.read",
    )

    async def query(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportCompanyUserProfileRead:
        user = await _load_business_user(db, user_id)
        state_label, is_locked = _user_state(user.is_active, user.locked_until, now)
        recovery_verified = _is_recovery_verified(user)
        proj_count = int(
            await db.scalar(
                select(func.count(ProjectMember.id))
                .join(Project, Project.id == ProjectMember.project_id)
                .where(
                    ProjectMember.user_id == user.id,
                    ProjectMember.deleted_at.is_(None),
                    Project.deleted_at.is_(None),
                )
            )
            or 0
        )
        active_sessions = int(
            await db.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.user_id == user.id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > now,
                )
            )
            or 0
        )
        emp_status = await db.scalar(
            select(HrEmployee.employment_status).where(
                HrEmployee.user_id == user.id,
                HrEmployee.deleted_at.is_(None),
            )
        )
        has_other_director = True
        if user.is_active and user.role in COMPANY_RESOURCE_ROLES:
            has_other_director = await UserRepository(db).has_other_usable_director(user.id)

        caps = ctx.capabilities
        can_manage_accounts = "company.accounts.manage" in caps
        can_assign_access = "company.access.assign" in caps
        can_revoke_sessions = "company.sessions.revoke" in caps
        is_protected = user.role in PROTECTED_USER_ROLES

        # Build explicit action availability with structured policy reasons.
        if not can_manage_accounts:
            state_allowed, state_reason = (
                False,
                "Missing operator capability 'company.accounts.manage'.",
            )
        elif user.is_active and user.role in COMPANY_RESOURCE_ROLES and not has_other_director:
            state_allowed, state_reason = (
                False,
                "Cannot disable the last active, unlocked director account (anti-lockout policy).",
            )
        else:
            state_allowed = True
            state_reason = (
                "Account can be disabled with fresh passkey proof."
                if user.is_active
                else "Account can be reactivated with fresh passkey proof."
            )

        if not can_manage_accounts:
            unlock_allowed, unlock_reason = (
                False,
                "Missing operator capability 'company.accounts.manage'.",
            )
        elif not is_locked and user.failed_login_attempts == 0:
            unlock_allowed, unlock_reason = False, "Account does not have an active sign-in lock."
        else:
            unlock_allowed, unlock_reason = (
                True,
                "Sign-in lock can be cleared with fresh passkey proof.",
            )

        if not can_assign_access:
            role_allowed, role_reason = (
                False,
                "Missing operator capability 'company.access.assign'.",
            )
        elif user.is_active and user.role in COMPANY_RESOURCE_ROLES and not has_other_director:
            role_allowed, role_reason = (
                False,
                "Cannot demote the last active, unlocked director account (anti-lockout policy).",
            )
        else:
            role_allowed, role_reason = (
                True,
                "Role can be changed within the fixed 10-role business ceiling.",
            )

        if not can_assign_access:
            member_allowed, member_reason = (
                False,
                "Missing operator capability 'company.access.assign'.",
            )
        elif not user.is_active:
            member_allowed, member_reason = (
                False,
                "Account is inactive; reactivate before assigning projects.",
            )
        else:
            member_allowed, member_reason = True, "Project memberships can be assigned or revoked."

        if not can_manage_accounts:
            rec_allowed, rec_reason = (
                False,
                "Missing operator capability 'company.accounts.manage'.",
            )
        elif not user.is_active:
            rec_allowed, rec_reason = (
                False,
                "Account is inactive; reactivate before issuing recovery.",
            )
        elif is_protected and ctx.authorization_mode == "single_owner":
            rec_allowed = False
            rec_reason = TECHNICAL_COMMAND_POLICY["request_account_recovery"].protected_target_note
        elif not recovery_verified:
            rec_allowed = False
            rec_reason = (
                "The account's recovery email destination has not been verified "
                "by a prior OTP sign-in."
            )
        elif not is_recovery_issuance_enabled(
            get_settings(), support_host="superadmin.garrisons.lk"
        ):
            rec_allowed = False
            rec_reason = "Runtime recovery issuance key is not configured."
        else:
            rec_allowed = True
            rec_reason = (
                "One-time recovery instructions will be delivered directly to "
                "the verified recipient."
            )

        if not can_revoke_sessions:
            sess_allowed, sess_reason = (
                False,
                "Missing operator capability 'company.sessions.revoke'.",
            )
        else:
            sess_allowed, sess_reason = (
                True,
                "Selected session or all active business sessions can be revoked.",
            )

        available_actions = [
            SupportUserActionAvailability(
                action_kind="set_account_state",
                label="Disable account" if user.is_active else "Reactivate account",
                allowed=state_allowed,
                required_capability="company.accounts.manage",
                reason=state_reason,
            ),
            SupportUserActionAvailability(
                action_kind="unlock_account",
                label="Clear sign-in lock",
                allowed=unlock_allowed,
                required_capability="company.accounts.manage",
                reason=unlock_reason,
            ),
            SupportUserActionAvailability(
                action_kind="change_business_role",
                label="Change business role",
                allowed=role_allowed,
                required_capability="company.access.assign",
                reason=role_reason,
            ),
            SupportUserActionAvailability(
                action_kind="change_project_membership",
                label="Manage project memberships",
                allowed=member_allowed,
                required_capability="company.access.assign",
                reason=member_reason,
            ),
            SupportUserActionAvailability(
                action_kind="request_account_recovery",
                label="Send recovery instructions",
                allowed=rec_allowed,
                required_capability="company.accounts.manage",
                reason=rec_reason,
            ),
            SupportUserActionAvailability(
                action_kind="revoke_business_session",
                label="Revoke business sessions",
                allowed=sess_allowed,
                required_capability="company.sessions.revoke",
                reason=sess_reason,
            ),
        ]

        linked_cases: list[SupportLinkedCaseSummary] = []
        if "cases.manage" in caps:
            case_rows = list(
                await db.scalars(
                    select(SupportCase)
                    .join(SupportCaseMember, SupportCaseMember.case_id == SupportCase.id)
                    .join(SupportCaseSubject, SupportCaseSubject.case_id == SupportCase.id)
                    .where(
                        SupportCaseMember.operator_id == ctx.operator_id,
                        SupportCaseSubject.user_id == user.id,
                    )
                    .order_by(SupportCase.created_at.desc())
                    .limit(10)
                )
            )
            linked_cases = [
                SupportLinkedCaseSummary(
                    case_id=c.id,
                    external_ref=c.external_ref,
                    status=c.status,
                    severity=c.severity,
                    reason_code=c.reason_code,
                    revision=c.revision,
                )
                for c in case_rows
            ]

        return SupportCompanyUserProfileRead(
            user_id=user.id,
            full_name=user.full_name,
            email_masked=_masked_email(user.email),
            employee_code=user.employee_code,
            phone_masked=_masked_phone(user.phone),
            designation=user.designation,
            role=user.role,
            role_label=BUSINESS_ROLE_LABELS.get(user.role, user.role),
            state=state_label,
            is_active=user.is_active,
            is_locked=is_locked,
            must_change_password=user.must_change_password,
            access_revision=user.access_revision,
            recovery_destination_verified=recovery_verified,
            has_linked_employee=emp_status is not None,
            employee_status=emp_status,
            assigned_project_count=proj_count,
            active_session_count=active_sessions,
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login_at=user.last_login_at,
            available_actions=available_actions,
            linked_cases=linked_cases,
        )

    def degraded(_now: datetime) -> SupportCompanyUserProfileRead:
        raise AppException(
            "User profile could not be loaded.",
            status_code=503,
            error_code="SUPPORT_PROFILE_UNAVAILABLE",
        )

    return await execute_oversight_read(
        session,
        token,
        capability="company.directory.read",
        surface="company_user_profile",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def read_company_user_access(
    session: AsyncSession,
    token: str | None,
    user_id: UUID,
    request_id: str,
    *,
    project_id: UUID | None = None,
) -> SupportCompanyUserAccessRead:
    async def query(
        db: AsyncSession, _now: datetime, _scoped: list[UUID] | None
    ) -> SupportCompanyUserAccessRead:
        user = await _load_business_user(db, user_id)
        role_perms = permissions_for_role(user.role)
        effective_perms = role_perms if user.is_active else []
        company_scope = user.role in COMPANY_RESOURCE_ROLES
        role_label = BUSINESS_ROLE_LABELS.get(user.role, user.role)

        membership_rows = (
            await db.execute(
                select(ProjectMember, Project)
                .join(Project, Project.id == ProjectMember.project_id)
                .where(
                    ProjectMember.user_id == user.id,
                    ProjectMember.deleted_at.is_(None),
                    Project.deleted_at.is_(None),
                )
                .order_by(Project.code.asc(), Project.id.asc())
            )
        ).all()
        member_project_ids = {proj.id for _, proj in membership_rows}
        memberships = [
            SupportUserProjectMembershipRead(
                membership_id=member.id,
                project_id=proj.id,
                project_code=proj.code,
                project_name=proj.name,
                project_status=proj.status,
                project_revision=proj.revision,
                role_in_project=member.role_in_project,
            )
            for member, proj in membership_rows
        ]

        all_projects = list(
            await db.scalars(
                select(Project)
                .where(Project.deleted_at.is_(None))
                .order_by(Project.code.asc(), Project.id.asc())
                .limit(100)
            )
        )
        eligible_projects = [
            SupportProjectOptionRead(
                project_id=p.id,
                project_code=p.code,
                project_name=p.name,
                project_status=p.status,
                project_revision=p.revision,
                is_member=p.id in member_project_ids,
                is_read_only=p.status in READ_ONLY_STATUSES,
            )
            for p in all_projects
        ]

        assignable_roles = [
            SupportRoleOption(
                role=r_key,
                label=r_label,
                permissions=permissions_for_role(r_key),
                company_scope=r_key in COMPANY_RESOURCE_ROLES,
                protected_target=r_key in PROTECTED_USER_ROLES,
            )
            for r_key, r_label in BUSINESS_ROLE_LABELS.items()
        ]

        explanations: list[SupportAccessExplanationItem] = []
        if not user.is_active:
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key="account_status",
                    label="Account sign-in and workflow access",
                    allowed=False,
                    category="account_inactive",
                    explanation=(
                        "Account is inactive. All permissions and project memberships "
                        "are suspended until reactivated."
                    ),
                )
            )
        else:
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key="account_status",
                    label="Account sign-in and workflow access",
                    allowed=True,
                    category="allowed",
                    explanation=f"Account is active with role {role_label}.",
                )
            )

        # Project visibility explanation
        if not user.is_active:
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key="project_visibility",
                    label="Project visibility scope",
                    allowed=False,
                    category="account_inactive",
                    explanation="Account inactive — cannot read projects.",
                )
            )
        elif PERMISSION_PROJECTS_READ not in role_perms:
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key="project_visibility",
                    label="Project visibility scope",
                    allowed=False,
                    category="no_permission",
                    explanation=(
                        f"No permission: role {role_label} does not include 'projects:read'."
                    ),
                )
            )
        elif company_scope:
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key="project_visibility",
                    label="Project visibility scope",
                    allowed=True,
                    category="allowed",
                    explanation=f"{role_label} has company-wide project read scope.",
                )
            )
        elif not memberships:
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key="project_visibility",
                    label="Project visibility scope",
                    allowed=False,
                    category="no_project_membership",
                    explanation=(
                        "No project membership: role has 'projects:read' but 0 active "
                        "project assignments."
                    ),
                )
            )
        else:
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key="project_visibility",
                    label="Project visibility scope",
                    allowed=True,
                    category="allowed",
                    explanation=f"Scoped to {len(memberships)} assigned project(s).",
                )
            )

        # MEP planning setup exception explanation
        if user.role == ROLE_MEP_PROJECT_MANAGER:
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key="mep_planning_setup",
                    label="MEP priced planning project creation",
                    allowed=user.is_active,
                    category="allowed" if user.is_active else "account_inactive",
                    explanation=(
                        "MEP Project Manager may create priced projects in 'planning' "
                        "status, but creation does not automatically grant ongoing "
                        "project membership or financial read authority."
                    ),
                )
            )

        # Approval eligibility and self-approval rules
        if user.role in REPORT_APPROVER_ROLES and PERMISSION_REPORTS_APPROVE in role_perms:
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key="report_approvals",
                    label="Daily report approval authority",
                    allowed=user.is_active,
                    category="allowed" if user.is_active else "account_inactive",
                    explanation=(
                        "Eligible to approve daily reports in scoped projects, "
                        "excluding self-submitted reports."
                    ),
                )
            )
        else:
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key="report_approvals",
                    label="Daily report approval authority",
                    allowed=False,
                    category="not_eligible_approver",
                    explanation=(
                        f"Not an eligible approver: role {role_label} cannot approve "
                        "daily reports."
                    ),
                )
            )

        explanations.append(
            SupportAccessExplanationItem(
                subject_key="self_approval_guard",
                label="Own submission and subject decision guard",
                allowed=False,
                category="self_approval_prohibited",
                explanation=(
                    "Self-approval prohibited: no user may approve their own report, "
                    "document version, HR change, or leave request."
                ),
            )
        )

        # Policy-disabled modules
        for key, label, detail in (
            (
                "finance_writes",
                "Invoice creation, approval, and payment recording",
                (
                    "Feature disabled by policy: invoice mutations and payment writes "
                    "are disabled for all roles."
                ),
            ),
            (
                "payroll_execution",
                "Payroll run preparation, approval, and settlement",
                (
                    "Feature disabled by policy: payroll execution grants are not "
                    "active in the current business role catalogue."
                ),
            ),
            (
                "deleted_media_recovery",
                "Deleted media recovery through portal",
                (
                    "Feature disabled by policy: deleted evidence recovery is denied "
                    "at the service boundary."
                ),
            ),
        ):
            explanations.append(
                SupportAccessExplanationItem(
                    subject_key=key,
                    label=label,
                    allowed=False,
                    category="feature_disabled_by_policy",
                    explanation=detail,
                )
            )

        focused_explanation: SupportAccessExplanationItem | None = None
        if project_id is not None:
            project = await db.get(Project, project_id)
            if project is None or project.deleted_at is not None:
                raise NotFoundException("Project")
            is_member = project.id in member_project_ids
            if not user.is_active:
                focused_explanation = SupportAccessExplanationItem(
                    subject_key=f"project:{project.id}",
                    label=f"Project {project.code} ({project.name})",
                    allowed=False,
                    category="account_inactive",
                    explanation=(
                        f"Account inactive: {user.full_name} cannot access "
                        f"{project.code} while disabled."
                    ),
                )
            elif PERMISSION_PROJECTS_READ not in role_perms:
                focused_explanation = SupportAccessExplanationItem(
                    subject_key=f"project:{project.id}",
                    label=f"Project {project.code} ({project.name})",
                    allowed=False,
                    category="no_permission",
                    explanation=(
                        f"No permission: {role_label} does not grant 'projects:read', "
                        f"even if assigned to {project.code}."
                    ),
                )
            elif not company_scope and not is_member:
                creator_note = (
                    f" Note: {user.full_name} created this project during setup, "
                    "but project creation does not automatically grant project membership."
                    if project.created_by == user.id
                    else ""
                )
                focused_explanation = SupportAccessExplanationItem(
                    subject_key=f"project:{project.id}",
                    label=f"Project {project.code} ({project.name})",
                    allowed=False,
                    category="no_project_membership",
                    explanation=(
                        f"No project membership: {user.full_name} ({role_label}) "
                        f"is not assigned to {project.code}.{creator_note}"
                    ),
                )
            else:
                scope_reason = (
                    "company-wide director scope"
                    if company_scope
                    else "active project membership"
                )
                focused_explanation = SupportAccessExplanationItem(
                    subject_key=f"project:{project.id}",
                    label=f"Project {project.code} ({project.name})",
                    allowed=True,
                    category="allowed",
                    explanation=(
                        f"Allowed: {user.full_name} can access {project.code} "
                        f"via {scope_reason}."
                    ),
                )

        nav_routes = [
            SupportNavigationRouteItem(route_id=route_id, visible=visible and user.is_active)
            for route_id, visible in navigation_visibility(user.role).items()
        ]

        return SupportCompanyUserAccessRead(
            user_id=user.id,
            role=user.role,
            role_label=role_label,
            access_revision=user.access_revision,
            is_active=user.is_active,
            company_scope=company_scope,
            effective_permissions=effective_perms,
            assignable_roles=assignable_roles,
            project_memberships=memberships,
            eligible_projects=eligible_projects,
            navigation_routes=nav_routes,
            explanations=explanations,
            focused_project_explanation=focused_explanation,
        )

    def degraded(_now: datetime) -> SupportCompanyUserAccessRead:
        raise AppException(
            "User access explanation is temporarily unavailable.",
            status_code=503,
            error_code="SUPPORT_ACCESS_EXPLAIN_UNAVAILABLE",
        )

    return await execute_oversight_read(
        session,
        token,
        capability="company.directory.read",
        surface="company_user_access",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def read_company_user_sessions(
    session: AsyncSession, token: str | None, user_id: UUID, request_id: str
) -> SupportUserSessionInventoryRead:
    async def query(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportUserSessionInventoryRead:
        user = await _load_business_user(db, user_id)
        sessions = list(
            await db.scalars(
                select(AuthSession)
                .where(AuthSession.user_id == user.id)
                .order_by(AuthSession.created_at.desc(), AuthSession.id.desc())
                .limit(50)
            )
        )
        session_ids = [s.id for s in sessions]
        refresh_stats: dict[UUID, tuple[int, datetime | None]] = {}
        if session_ids:
            rows = (
                await db.execute(
                    select(
                        AuthRefreshToken.session_id,
                        func.count(AuthRefreshToken.id).filter(
                            AuthRefreshToken.revoked_at.is_(None),
                            AuthRefreshToken.deleted_at.is_(None),
                            AuthRefreshToken.expires_at > now,
                        ),
                        func.max(AuthRefreshToken.created_at),
                    )
                    .where(
                        AuthRefreshToken.user_id == user.id,
                        AuthRefreshToken.session_id.in_(session_ids),
                    )
                    .group_by(AuthRefreshToken.session_id)
                )
            ).all()
            refresh_stats = {
                sid: (int(active_cnt or 0), latest_created)
                for sid, active_cnt, latest_created in rows
                if sid is not None
            }
        legacy_unindexed = int(
            await db.scalar(
                select(func.count(AuthRefreshToken.id)).where(
                    AuthRefreshToken.user_id == user.id,
                    AuthRefreshToken.session_id.is_(None),
                    AuthRefreshToken.revoked_at.is_(None),
                    AuthRefreshToken.deleted_at.is_(None),
                    AuthRefreshToken.expires_at > now,
                )
            )
            or 0
        )

        items: list[SupportUserSessionItem] = []
        active_count = 0
        for s in sessions:
            active_tokens, latest_token_at = refresh_stats.get(s.id, (0, None))
            if s.revoked_at is not None:
                state: Literal["active", "revoked", "expired"] = "revoked"
            elif s.expires_at <= now:
                state = "expired"
            else:
                state = "active"
                active_count += 1
            last_active = max(
                filter(None, [s.created_at, s.updated_at, latest_token_at]),
                default=s.created_at,
            )
            items.append(
                SupportUserSessionItem(
                    session_id=s.id,
                    created_at=s.created_at,
                    last_active_at=last_active,
                    expires_at=s.expires_at,
                    revoked_at=s.revoked_at,
                    state=state,
                    active_refresh_tokens=active_tokens,
                )
            )
        return SupportUserSessionInventoryRead(
            user_id=user.id,
            access_revision=user.access_revision,
            has_unindexed_legacy_tokens=legacy_unindexed > 0,
            active_session_count=active_count,
            sessions=items,
        )

    def degraded(_now: datetime) -> SupportUserSessionInventoryRead:
        raise AppException(
            "User session inventory is temporarily unavailable.",
            status_code=503,
            error_code="SUPPORT_SESSIONS_UNAVAILABLE",
        )

    return await execute_oversight_read(
        session,
        token,
        capability="company.sessions.read",
        surface="company_user_sessions",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def read_company_user_activity(
    session: AsyncSession, token: str | None, user_id: UUID, request_id: str
) -> SupportUserActivityPage:
    async def query(
        db: AsyncSession, _now: datetime, _scoped: list[UUID] | None
    ) -> SupportUserActivityPage:
        user = await _load_business_user(db, user_id)
        auth_rows = (
            await db.execute(
                select(ActivityLog.id, ActivityLog.created_at, ActivityLog.action)
                .where(
                    ActivityLog.user_id == user.id,
                    ActivityLog.action.in_(_EVENTS),
                    ActivityLog.deleted_at.is_(None),
                )
                .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
                .limit(15)
            )
        ).all()

        cmd_rows = list(
            await db.scalars(
                select(SupportAdminCommand)
                .where(SupportAdminCommand.target_user_id == user.id)
                .order_by(
                    SupportAdminCommand.created_at.desc(), SupportAdminCommand.id.desc()
                )
                .limit(15)
            )
        )

        case_action_rows = list(
            await db.scalars(
                select(SupportBusinessAction)
                .where(SupportBusinessAction.user_id == user.id)
                .order_by(
                    SupportBusinessAction.expires_at.desc(), SupportBusinessAction.id.desc()
                )
                .limit(10)
            )
        )

        items: list[SupportUserActivityItem] = []
        for event_id, occurred_at, action in auth_rows:
            mapped = _EVENTS[action]
            items.append(
                SupportUserActivityItem(
                    event_id=event_id,
                    source="business_auth",
                    category=mapped,
                    summary=f"Business authentication event: {mapped.replace('_', ' ')}",
                    actor_reference=str(user.id),
                    authorization_mode=None,
                    occurred_at=occurred_at,
                )
            )
        for cmd in cmd_rows:
            when = cmd.completed_at or cmd.created_at
            items.append(
                SupportUserActivityItem(
                    event_id=cmd.id,
                    source="technical_command",
                    category=f"{cmd.command_kind}:{cmd.status}",
                    summary=(
                        f"Technical command '{cmd.command_kind.replace('_', ' ')}' "
                        f"({cmd.status})"
                    ),
                    actor_reference=str(cmd.operator_id),
                    authorization_mode=cmd.authorization_mode,
                    occurred_at=when,
                )
            )
        for act in case_action_rows:
            when = act.applied_at or (act.expires_at - timedelta(minutes=15))
            state_str = "applied" if act.applied_at is not None else "proposed"
            items.append(
                SupportUserActivityItem(
                    event_id=act.id,
                    source="case_account_action",
                    category=f"{act.kind}:{state_str}",
                    summary=(
                        f"Case account intervention '{act.kind.replace('_', ' ')}' "
                        f"({state_str})"
                    ),
                    actor_reference=str(act.requester_id),
                    authorization_mode=act.authorization_mode,
                    occurred_at=when,
                )
            )
        items.sort(key=lambda item: item.occurred_at, reverse=True)
        return SupportUserActivityPage(user_id=user.id, items=items[:25])

    def degraded(_now: datetime) -> SupportUserActivityPage:
        raise AppException(
            "User activity history is temporarily unavailable.",
            status_code=503,
            error_code="SUPPORT_ACTIVITY_UNAVAILABLE",
        )

    return await execute_oversight_read(
        session,
        token,
        capability="company.directory.read",
        surface="company_user_activity",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def diagnose_or_link_user_case(
    session: AsyncSession,
    token: str | None,
    csrf: str | None,
    user_id: UUID,
    payload: SupportDiagnoseCaseRequest,
    request_id: str,
) -> SupportDiagnoseCaseRead:
    ctx, operator, active = await resolve_support_actor_context(
        session,
        token,
        csrf,
        request_id=request_id,
        required_capability="cases.manage",
        require_csrf=True,
        require_passkey_assurance=True,
    )
    user = await _load_business_user(session, user_id)
    if payload.project_id is not None:
        project = await session.get(Project, payload.project_id)
        if project is None or project.deleted_at is not None:
            raise NotFoundException("Project")

    existing_case = await session.scalar(
        select(SupportCase)
        .join(SupportCaseMember, SupportCaseMember.case_id == SupportCase.id)
        .join(SupportCaseSubject, SupportCaseSubject.case_id == SupportCase.id)
        .where(
            SupportCaseMember.operator_id == operator.id,
            SupportCaseSubject.user_id == user.id,
            SupportCase.status.in_(("open", "investigating")),
        )
        .order_by(SupportCase.created_at.desc())
        .limit(1)
        .with_for_update(of=SupportCase)
    )
    now = utc_now()
    created_new = False
    if existing_case is None:
        if ctx.authorization_mode != "single_owner":
            raise AppException(
                (
                    "Paired custody requires an independently reviewed subject_set "
                    "case action before linking an account."
                ),
                status_code=403,
                error_code="SUPPORT_CASE_PAIRED_REVIEW_REQUIRED",
            )
        created_new = True
        safe_reason = redact_text(payload.reason)[:60]
        ext_ref = f"acct-{user.id.hex[:8]}-{uuid4().hex[:8]}"
        existing_case = SupportCase(
            id=uuid4(),
            owner_id=operator.id,
            external_ref=ext_ref,
            severity="medium",
            reason_code="access",
            status="open",
            revision=1,
        )
        session.add(existing_case)
        await session.flush()
        session.add(SupportCaseMember(case_id=existing_case.id, operator_id=operator.id))
        session.add(SupportCaseSubject(case_id=existing_case.id, user_id=user.id))
        session.add(
            SupportCaseEvent(
                id=uuid4(),
                case_id=existing_case.id,
                operator_id=operator.id,
                action="created",
                revision=existing_case.revision,
                status=existing_case.status,
                reason_code="access",
                request_id=request_id,
                occurred_at=now,
            )
        )
        del safe_reason

    if payload.project_id is not None and ctx.authorization_mode == "single_owner":
        existing_proj = await session.get(
            SupportCaseProject, (existing_case.id, payload.project_id)
        )
        if existing_proj is None:
            session.add(
                SupportCaseProject(case_id=existing_case.id, project_id=payload.project_id)
            )
            await session.flush()

    linked_projects = list(
        await session.scalars(
            select(SupportCaseProject.project_id)
            .where(SupportCaseProject.case_id == existing_case.id)
            .order_by(SupportCaseProject.project_id)
        )
    )
    if support_session_deadline(active) <= utc_now():
        raise AppException(
            "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
        )
    active.last_seen_at = utc_now()
    await session.commit()
    return SupportDiagnoseCaseRead(
        case_id=existing_case.id,
        external_ref=existing_case.external_ref,
        status=existing_case.status,
        revision=existing_case.revision,
        subject_user_id=user.id,
        linked_project_ids=linked_projects,
        created_new=created_new,
    )


_INSPECTOR_CATALOG: dict[str, SupportDataInspectorEntityMeta] = {
    "projects": SupportDataInspectorEntityMeta(
        entity_key="projects",
        label="Projects (non-financial metadata)",
        description="Project codes, names, statuses, locations, schedule dates, and revisions.",
        columns=[
            "id",
            "code",
            "name",
            "status",
            "location",
            "start_date",
            "target_end_date",
            "revision",
        ],
        filterable_statuses=sorted(PROJECT_STATUSES),
    ),
    "suppliers": SupportDataInspectorEntityMeta(
        entity_key="suppliers",
        label="Suppliers register",
        description="Registered suppliers, active status, TDS compliance expiry, and revisions.",
        columns=["id", "name", "contact_person", "is_active", "tds_expiry_date", "revision"],
        filterable_statuses=["active", "inactive"],
    ),
    "inventory_items": SupportDataInspectorEntityMeta(
        entity_key="inventory_items",
        label="Inventory catalogue items",
        description="Item codes, names, categories, units, active status, and reorder thresholds.",
        columns=["id", "item_code", "name", "category", "item_type", "unit", "is_active"],
        filterable_statuses=["active", "inactive"],
    ),
    "storage_locations": SupportDataInspectorEntityMeta(
        entity_key="storage_locations",
        label="Storage locations",
        description="Warehouse and project site storage locations and active state.",
        columns=["id", "code", "name", "location_type", "is_active", "project_id"],
        filterable_statuses=["active", "inactive"],
    ),
}


async def read_data_inspector_catalog(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportDataInspectorCatalogRead:
    async def query(
        _db: AsyncSession, _now: datetime, _scoped: list[UUID] | None
    ) -> SupportDataInspectorCatalogRead:
        return SupportDataInspectorCatalogRead(
            entities=list(_INSPECTOR_CATALOG.values()),
            excluded_domains_notice=(
                "Confidential HR records, payroll snapshots, credentials, session tokens, "
                "and raw SQL queries are permanently excluded from the technical data inspector."
            ),
        )

    def degraded(_now: datetime) -> SupportDataInspectorCatalogRead:
        raise AppException(
            "Data inspector catalog is temporarily unavailable.",
            status_code=503,
            error_code="SUPPORT_INSPECTOR_UNAVAILABLE",
        )

    return await execute_oversight_read(
        session,
        token,
        capability="company.data.inspect",
        surface="company_data_inspector",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def query_data_inspector_entity(
    session: AsyncSession,
    token: str | None,
    entity_key: str,
    request_id: str,
    *,
    search: str | None = None,
    status: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> SupportDataInspectorPage:
    meta = _INSPECTOR_CATALOG.get(entity_key)
    if meta is None:
        raise AppException(
            "This entity is not registered in the non-sensitive data inspector allowlist.",
            status_code=404,
            error_code="SUPPORT_INSPECTOR_ENTITY_DENIED",
        )
    cleaned_search = search.strip() if search else None
    if cleaned_search and len(cleaned_search) > 120:
        raise AppException(
            "Inspector search filter must be 120 characters or fewer.",
            status_code=422,
            error_code="SUPPORT_INSPECTOR_FILTER_INVALID",
        )
    if status and status not in meta.filterable_statuses:
        raise AppException(
            f"Unsupported status filter '{status}' for {entity_key}.",
            status_code=422,
            error_code="SUPPORT_INSPECTOR_FILTER_INVALID",
        )
    bounded_limit = min(max(limit, 1), 50)
    bounded_offset = max(offset, 0)

    async def query(
        db: AsyncSession, _now: datetime, _scoped: list[UUID] | None
    ) -> SupportDataInspectorPage:
        rows: list[dict[str, Any]] = []
        total = 0
        pattern = f"%{_escape_like(cleaned_search.casefold())}%" if cleaned_search else None

        if entity_key == "projects":
            proj_filters: list[ColumnElement[bool]] = [Project.deleted_at.is_(None)]
            if status:
                proj_filters.append(Project.status == status)
            if pattern:
                proj_filters.append(
                    or_(
                        func.lower(Project.code).like(pattern, escape="\\"),
                        func.lower(Project.name).like(pattern, escape="\\"),
                    )
                )
            total = int(
                await db.scalar(select(func.count(Project.id)).where(*proj_filters)) or 0
            )
            project_records = await db.scalars(
                select(Project)
                .where(*proj_filters)
                .order_by(Project.code.asc(), Project.id.asc())
                .limit(bounded_limit)
                .offset(bounded_offset)
            )
            rows = [
                {
                    "id": str(r.id),
                    "code": r.code,
                    "name": r.name,
                    "status": r.status,
                    "location": r.location,
                    "start_date": r.start_date.isoformat() if r.start_date else None,
                    "target_end_date": (
                        r.target_end_date.isoformat() if r.target_end_date else None
                    ),
                    "revision": r.revision,
                }
                for r in project_records
            ]
        elif entity_key == "suppliers":
            sup_filters: list[ColumnElement[bool]] = [Supplier.deleted_at.is_(None)]
            if status:
                sup_filters.append(Supplier.is_active.is_(status == "active"))
            if pattern:
                sup_filters.append(
                    or_(
                        func.lower(Supplier.name).like(pattern, escape="\\"),
                        func.lower(func.coalesce(Supplier.contact_person, "")).like(
                            pattern, escape="\\"
                        ),
                    )
                )
            total = int(
                await db.scalar(select(func.count(Supplier.id)).where(*sup_filters)) or 0
            )
            supplier_records = await db.scalars(
                select(Supplier)
                .where(*sup_filters)
                .order_by(Supplier.name.asc(), Supplier.id.asc())
                .limit(bounded_limit)
                .offset(bounded_offset)
            )
            rows = [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "contact_person": r.contact_person,
                    "is_active": r.is_active,
                    "tds_expiry_date": (
                        r.tds_expiry_date.isoformat() if r.tds_expiry_date else None
                    ),
                    "revision": r.revision,
                }
                for r in supplier_records
            ]
        elif entity_key == "inventory_items":
            inv_filters: list[ColumnElement[bool]] = [InventoryItem.deleted_at.is_(None)]
            if status:
                inv_filters.append(InventoryItem.is_active.is_(status == "active"))
            if pattern:
                inv_filters.append(
                    or_(
                        func.lower(InventoryItem.item_code).like(pattern, escape="\\"),
                        func.lower(InventoryItem.name).like(pattern, escape="\\"),
                        func.lower(func.coalesce(InventoryItem.category, "")).like(
                            pattern, escape="\\"
                        ),
                    )
                )
            total = int(
                await db.scalar(select(func.count(InventoryItem.id)).where(*inv_filters)) or 0
            )
            inv_records = await db.scalars(
                select(InventoryItem)
                .where(*inv_filters)
                .order_by(InventoryItem.item_code.asc(), InventoryItem.id.asc())
                .limit(bounded_limit)
                .offset(bounded_offset)
            )
            rows = [
                {
                    "id": str(r.id),
                    "item_code": r.item_code,
                    "name": r.name,
                    "category": r.category,
                    "item_type": r.item_type,
                    "unit": r.unit,
                    "is_active": r.is_active,
                }
                for r in inv_records
            ]
        elif entity_key == "storage_locations":
            loc_filters: list[ColumnElement[bool]] = [StorageLocation.deleted_at.is_(None)]
            if status:
                loc_filters.append(StorageLocation.is_active.is_(status == "active"))
            if pattern:
                loc_filters.append(
                    or_(
                        func.lower(StorageLocation.code).like(pattern, escape="\\"),
                        func.lower(StorageLocation.name).like(pattern, escape="\\"),
                    )
                )
            total = int(
                await db.scalar(select(func.count(StorageLocation.id)).where(*loc_filters)) or 0
            )
            loc_records = await db.scalars(
                select(StorageLocation)
                .where(*loc_filters)
                .order_by(StorageLocation.code.asc(), StorageLocation.id.asc())
                .limit(bounded_limit)
                .offset(bounded_offset)
            )
            rows = [
                {
                    "id": str(r.id),
                    "code": r.code,
                    "name": r.name,
                    "location_type": r.location_type,
                    "is_active": r.is_active,
                    "project_id": str(r.project_id) if r.project_id else None,
                }
                for r in loc_records
            ]

        return SupportDataInspectorPage(
            entity_key=entity_key,
            columns=meta.columns,
            rows=rows,
            total=total,
            limit=bounded_limit,
            offset=bounded_offset,
        )

    def degraded(_now: datetime) -> SupportDataInspectorPage:
        raise AppException(
            "Data inspector query is temporarily unavailable.",
            status_code=503,
            error_code="SUPPORT_INSPECTOR_UNAVAILABLE",
        )

    return await execute_oversight_read(
        session,
        token,
        capability="company.data.inspect",
        surface="company_data_inspector",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )
