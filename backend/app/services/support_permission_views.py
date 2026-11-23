from datetime import datetime, timedelta
from hmac import compare_digest
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_business_actions import SupportBusinessAction, SupportBusinessApproval
from app.models.support_cases import SupportCase, SupportCaseMember, SupportOperatorGrant
from app.models.support_directory import SupportCaseSubject
from app.models.support_identity import SupportOperator, SupportSession
from app.models.support_permission_view import SupportPermissionView, SupportPermissionViewEvent
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.support_custody import _CUSTODY_LOCK
from app.services.support_identity import SupportIdentity, _digest, support_session_deadline
from app.services.support_project_projection import (
    MaskedProject,
    MaskedProjectDetail,
    MaskedProjects,
    masked_projects,
    portal_preview_projects,
)
from app.services.support_request_projection import RequestSummary, read_linked_request_summary
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    ALL_PERMISSIONS,
    BUSINESS_ROLE_LABELS,
    BUSINESS_ROLES,
    HR_PERMISSIONS,
    permissions_for_role,
)
from app.utils.portal_navigation import navigation_visibility
from app.utils.security import utc_now

_CAPABILITY = "simulation.start"
_IDLE = timedelta(minutes=10)


class SupportPermissionExplanation(BaseModel):
    view_id: UUID
    case_id: UUID
    operator_id: UUID
    subject_id: UUID
    expires_at: datetime
    adapter: Literal["permission-explanation"] = "permission-explanation"
    scope: Literal["role"] = "role"
    permission_key: str
    allowed: bool


class SupportRequestSummary(RequestSummary):
    view_id: UUID
    case_id: UUID
    operator_id: UUID
    subject_id: UUID
    expires_at: datetime
    adapter: Literal["request-summary"] = "request-summary"


class SupportNavigationRoute(BaseModel):
    route_id: str
    visible: bool


class SupportNavigationProjection(BaseModel):
    view_id: UUID
    case_id: UUID
    operator_id: UUID
    subject_id: UUID
    expires_at: datetime
    adapter: Literal["navigation"] = "navigation"
    routes: list[SupportNavigationRoute]


class SupportProjectView(BaseModel):
    view_id: UUID
    case_id: UUID
    operator_id: UUID
    subject_id: UUID
    expires_at: datetime


class SupportProjectList(SupportProjectView):
    adapter: Literal["project-list"] = "project-list"
    projects: list[MaskedProject]


class SupportProjectDetail(SupportProjectView):
    adapter: Literal["project-detail-summary"] = "project-detail-summary"
    project: MaskedProjectDetail


PortalPreviewPage = Literal["home", "projects", "project"]


class SupportPortalPreview(BaseModel):
    view_id: UUID
    subject_name: str
    role_label: str
    case_reference: str
    expires_at: datetime
    routes: list[str]
    projects: list[MaskedProject]
    project: MaskedProjectDetail | None = None


class SupportPermissionViews:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _load(
        self, token: str | None, view_id: UUID
    ) -> tuple[SupportOperator, SupportSession, SupportBusinessAction, SupportPermissionView]:
        await UserRepository(self.session).lock_access_management()
        await self.session.execute(select(func.pg_advisory_xact_lock(_CUSTODY_LOCK)))
        operator, active = await SupportIdentity(self.session).current(token)
        view = await self.session.get(SupportPermissionView, view_id, with_for_update=True)
        if view is None or view.session_id != active.id:
            raise NotFoundException("Support view")
        action = await self.session.get(SupportBusinessAction, view_id)
        if action is None or action.requester_id != operator.id:
            raise NotFoundException("Support view")
        return operator, active, action, view

    def _audit(
        self, operator: SupportOperator, view: SupportPermissionView, event: str, request_id: str
    ) -> None:
        self.session.add(
            SupportPermissionViewEvent(
                id=uuid4(),
                view_id=view.id,
                actor_id=operator.id,
                event=event,
                occurred_at=utc_now(),
                request_id=request_id,
            )
        )

    async def _authorize_read(
        self, token: str | None, view_id: UUID, kind: str
    ) -> tuple[SupportOperator, SupportSession, SupportBusinessAction, SupportPermissionView, str]:
        operator, active, action, view = await self._load(token, view_id)
        if kind == "portal_preview" and active.auth_method != "passkey":
            raise AppException(
                "A passkey-authenticated technical session is required.", status_code=403
            )
        case = await self.session.get(SupportCase, action.case_id, with_for_update=True)
        subject = await self.session.get(SupportCaseSubject, action.case_id)
        if (
            action.kind != kind
            or (
                kind == "portal_preview"
                and (action.permission_session_id != active.id or action.applied_at is None)
            )
            or operator.grant_epoch != action.requester_epoch
            or await self.session.get(SupportOperatorGrant, (operator.id, _CAPABILITY)) is None
            or case is None
            or case.revision != action.case_revision
            or case.status not in {"open", "investigating"}
            or await self.session.get(SupportCaseMember, (action.case_id, operator.id)) is None
            or subject is None
            or subject.user_id != action.user_id
        ):
            raise NotFoundException("Support view")
        owner_authorized = False
        if action.owner_session_id is not None:
            owner_authorized = (
                action.owner_session_id == active.id
                and action.permission_session_id == active.id
                and active.operator_id == action.requester_id
                and active.grant_epoch == action.requester_epoch
                and active.revoked_at is None
                and support_session_deadline(active) > utc_now()
                and await SupportIdentity(self.session).is_single_owner(operator.id)
            )
        reviewer = None
        if not owner_authorized and action.owner_session_id is None:
            reviewer = await self.session.scalar(
                select(SupportBusinessApproval.reviewer_id)
                .join(SupportOperator, SupportOperator.id == SupportBusinessApproval.reviewer_id)
                .join(
                    SupportCaseMember,
                    and_(
                        SupportCaseMember.case_id == action.case_id,
                        SupportCaseMember.operator_id == SupportOperator.id,
                    ),
                )
                .join(
                    SupportOperatorGrant,
                    and_(
                        SupportOperatorGrant.operator_id == SupportOperator.id,
                        SupportOperatorGrant.capability == _CAPABILITY,
                    ),
                )
                .where(
                    SupportBusinessApproval.action_id == action.id,
                    SupportBusinessApproval.reviewer_id != operator.id,
                    SupportBusinessApproval.reviewer_epoch == SupportOperator.grant_epoch,
                    SupportOperator.status == "active",
                )
                .limit(1)
            )
        user = (
            await self.session.execute(
                select(User.role, User.access_revision)
                .where(
                    User.id == action.user_id, User.is_active.is_(True), User.deleted_at.is_(None)
                )
                .with_for_update(key_share=True)
            )
        ).one_or_none()
        if (
            (not owner_authorized and reviewer is None)
            or user is None
            or user.access_revision != action.user_revision
            or user.role not in BUSINESS_ROLES
        ):
            raise NotFoundException("Support view")
        now = utc_now()
        if (
            view.ended_at
            or min(view.expires_at, view.last_seen_at + _IDLE, support_session_deadline(active))
            <= now
        ):
            raise AppException(
                "The support view expired or ended.",
                status_code=409,
                error_code="SUPPORT_VIEW_EXPIRED",
            )
        return operator, active, action, view, user.role

    async def _record_read(
        self, operator: SupportOperator, active: SupportSession, view: SupportPermissionView,
        request_id: str,
    ) -> None:
        now = utc_now()
        if min(view.expires_at, view.last_seen_at + _IDLE, support_session_deadline(active)) <= now:
            raise AppException(
                "The support view expired or ended.",
                status_code=409,
                error_code="SUPPORT_VIEW_EXPIRED",
            )
        view.last_seen_at = now
        active.last_seen_at = now
        self._audit(operator, view, "read", request_id)
        await self.session.commit()

    async def read(
        self, token: str | None, view_id: UUID, request_id: str
    ) -> SupportPermissionExplanation:
        operator, active, action, view, role = await self._authorize_read(
            token, view_id, "permission_view"
        )
        permission = action.permission_key
        if permission is None or permission not in (ALL_PERMISSIONS | HR_PERMISSIONS):
            raise NotFoundException("Support view")
        result = SupportPermissionExplanation(
            view_id=view.id,
            case_id=action.case_id,
            operator_id=operator.id,
            subject_id=action.user_id,
            expires_at=view.expires_at,
            permission_key=permission,
            allowed=permission in permissions_for_role(role),
        )
        await self._record_read(operator, active, view, request_id)
        return result

    async def read_request_summary(
        self, token: str | None, view_id: UUID, request_id: str
    ) -> SupportRequestSummary:
        operator, active, action, view, _ = await self._authorize_read(
            token, view_id, "request_summary"
        )
        summary = await read_linked_request_summary(
            self.session, action.case_id, action.user_id, action.source_event_id
        )
        result = SupportRequestSummary(
            **summary.model_dump(),
            view_id=view.id,
            case_id=action.case_id,
            operator_id=operator.id,
            subject_id=action.user_id,
            expires_at=view.expires_at,
        )
        await self._record_read(operator, active, view, request_id)
        return result

    async def read_navigation(
        self, token: str | None, view_id: UUID, request_id: str
    ) -> SupportNavigationProjection:
        operator, active, action, view, role = await self._authorize_read(
            token, view_id, "navigation_view"
        )
        result = SupportNavigationProjection(
            view_id=view.id,
            case_id=action.case_id,
            operator_id=operator.id,
            subject_id=action.user_id,
            expires_at=view.expires_at,
            routes=[
                SupportNavigationRoute(route_id=route_id, visible=visible)
                for route_id, visible in navigation_visibility(role).items()
            ],
        )
        await self._record_read(operator, active, view, request_id)
        return result

    async def read_projects(
        self, token: str | None, view_id: UUID, request_id: str
    ) -> SupportProjectList:
        operator, active, action, view, role = await self._authorize_read(
            token, view_id, "project_list"
        )
        try:
            projects = await masked_projects(self.session, action.case_id, action.user_id, role)
            if not isinstance(projects, MaskedProjects) or (
                projects.scope_digest != action.project_scope_digest
            ):
                raise NotFoundException("Support project")
        except NotFoundException:
            await self._end_view(operator, view, request_id)
            raise
        result = SupportProjectList(
            view_id=view.id,
            case_id=action.case_id,
            operator_id=operator.id,
            subject_id=action.user_id,
            expires_at=view.expires_at,
            projects=projects.projects,
        )
        await self._record_read(operator, active, view, request_id)
        return result

    async def read_project_detail(
        self, token: str | None, view_id: UUID, request_id: str
    ) -> SupportProjectDetail:
        operator, active, action, view, role = await self._authorize_read(
            token, view_id, "project_detail"
        )
        if action.project_id is None:
            raise NotFoundException("Support project")
        try:
            project = await masked_projects(
                self.session, action.case_id, action.user_id, role, project_id=action.project_id
            )
        except NotFoundException:
            await self._end_view(operator, view, request_id)
            raise
        assert isinstance(project, MaskedProjectDetail)
        result = SupportProjectDetail(
            view_id=view.id,
            case_id=action.case_id,
            operator_id=operator.id,
            subject_id=action.user_id,
            expires_at=view.expires_at,
            project=project,
        )
        await self._record_read(operator, active, view, request_id)
        return result

    async def read_portal_preview(
        self, token: str | None, view_id: UUID, request_id: str, page: PortalPreviewPage,
        project_label: str | None = None,
    ) -> SupportPortalPreview:
        try:
            operator, active, action, view, role = await self._authorize_read(
                token, view_id, "portal_preview"
            )
        except AppException as exc:
            await self.record_portal_preview_denial(token, view_id, request_id, page, exc)
            raise
        projects = await portal_preview_projects(
            self.session, action.case_id, action.user_id, role
        )
        if projects.scope_digest != action.project_scope_digest:
            await self._preview_audit(operator, action, page, "scope_changed", request_id)
            await self._end_view(operator, view, request_id)
            raise NotFoundException("Support preview")

        navigation = navigation_visibility(role)
        detail: MaskedProjectDetail | None = None
        try:
            if page in {"projects", "project"} and not navigation.get("projects"):
                raise NotFoundException("Support project")
            if page == "project":
                if project_label is None:
                    raise NotFoundException("Support project")
                projected = await masked_projects(
                    self.session, action.case_id, action.user_id, role, project_label=project_label
                )
                assert isinstance(projected, MaskedProjectDetail)
                detail = projected
        except NotFoundException:
            await self._preview_audit(operator, action, page, "denied", request_id)
            await self.session.commit()
            raise

        subject = await self.session.get(User, action.user_id)
        case = await self.session.get(SupportCase, action.case_id)
        assert subject is not None and case is not None
        result = SupportPortalPreview(
            view_id=view.id,
            subject_name=subject.full_name,
            role_label=BUSINESS_ROLE_LABELS[role],
            case_reference=case.external_ref or str(case.id),
            expires_at=min(view.expires_at, active.expires_at, utc_now() + _IDLE),
            routes=[route for route, visible in navigation.items() if visible],
            projects=projects.projects if page == "projects" else [],
            project=detail,
        )
        await self._preview_audit(operator, action, page, "returned", request_id)
        await self._record_read(operator, active, view, request_id)
        return result

    async def record_portal_preview_denial(
        self, token: str | None, view_id: UUID, request_id: str, page: str, error: AppException,
    ) -> None:
        # Only attribute a denial to an authenticated operator's own reviewed preview.
        try:
            operator, _, action, view = await self._load(token, view_id)
        except AppException:
            return
        if action.kind != "portal_preview":
            return
        outcome = (
            "expired" if error.error_code == "SUPPORT_VIEW_EXPIRED" else
            "invalidated" if error.status_code == 404 else
            "denied"
        )
        await self._preview_audit(operator, action, page, outcome, request_id)
        if outcome in {"expired", "invalidated"}:
            await self._end_view(operator, view, request_id)
        else:
            await self.session.commit()

    async def _preview_audit(
        self, operator: SupportOperator, action: SupportBusinessAction, page: str, outcome: str,
        request_id: str,
    ) -> None:
        await AuditService(self.session).record(
            action="support.portal_preview",
            entity_type="support_business_action",
            entity_id=action.id,
            request_id=request_id,
            context_payload={
                "operator_id": str(operator.id), "case_id": str(action.case_id),
                "subject_id": str(action.user_id), "page": page, "outcome": outcome,
            },
        )

    async def end(
        self, token: str | None, csrf: str | None, view_id: UUID, request_id: str,
        *, expected_kind: str | None = None,
    ) -> None:
        operator, active, action, view = await self._load(token, view_id)
        if expected_kind is not None and action.kind != expected_kind:
            raise NotFoundException("Support view")
        if not csrf or len(csrf) != 43 or not compare_digest(active.csrf_hash, _digest(csrf)):
            raise AppException("The support request could not be verified.", status_code=403)
        await self._end_view(operator, view, request_id)

    async def _end_view(
        self, operator: SupportOperator, view: SupportPermissionView, request_id: str
    ) -> None:
        if view.ended_at is None:
            view.ended_at = utc_now()
            self._audit(operator, view, "ended", request_id)
        await self.session.commit()
