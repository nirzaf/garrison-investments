from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.hr import HrEmployee, HrProjectAssignmentRequest
from app.models.project import Project
from app.models.user import User
from app.schemas.hr import (
    HrProjectAssignmentCreateRequest,
    HrProjectAssignmentDecision,
    HrProjectAssignmentListResponse,
    HrProjectAssignmentResponse,
)
from app.schemas.projects import (
    ProjectMemberCreateRequest,
    ProjectOption,
    ProjectOptionListResponse,
)
from app.services.project_service import READ_ONLY_STATUSES, ProjectService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_EMPLOYEES_MANAGE,
    PERMISSION_PROJECTS_MANAGE,
    ensure_permission,
)
from app.utils.security import utc_now

ACTIVE_ASSIGNMENT_EMPLOYMENT = frozenset({"active", "on_probation", "on_leave", "notice_period"})


class HrProjectAssignmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectService(session)

    async def project_options(
        self, actor: User, *, search: str | None, limit: int, offset: int
    ) -> ProjectOptionListResponse:
        ensure_permission(actor, PERMISSION_HR_EMPLOYEES_MANAGE)
        filters: list[ColumnElement[bool]] = [
            Project.deleted_at.is_(None),
            Project.status.not_in(READ_ONLY_STATUSES),
        ]
        if search:
            term = f"%{search.strip()}%"
            filters.append(or_(Project.name.ilike(term), Project.code.ilike(term)))
        rows = await self.session.scalars(
            select(Project)
            .where(*filters)
            .order_by(Project.code, Project.id)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(select(func.count(Project.id)).where(*filters))
        return ProjectOptionListResponse(
            items=[ProjectOption.model_validate(row) for row in rows], total=int(total or 0)
        )

    async def list_requests(
        self, actor: User, *, limit: int, offset: int, project_id: UUID | None = None
    ) -> HrProjectAssignmentListResponse:
        if project_id is None:
            ensure_permission(actor, PERMISSION_HR_EMPLOYEES_MANAGE)
            filters = [HrProjectAssignmentRequest.requested_by_id == actor.id]
        else:
            ensure_permission(actor, PERMISSION_PROJECTS_MANAGE)
            await self.projects.get_project(project_id, actor)
            filters = [HrProjectAssignmentRequest.project_id == project_id]
        rows = await self.session.execute(
            select(HrProjectAssignmentRequest, HrEmployee, Project)
            .join(HrEmployee, HrEmployee.id == HrProjectAssignmentRequest.employee_id)
            .join(Project, Project.id == HrProjectAssignmentRequest.project_id)
            .where(*filters)
            .order_by(
                HrProjectAssignmentRequest.status != "pending",
                HrProjectAssignmentRequest.created_at.desc(),
                HrProjectAssignmentRequest.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count(HrProjectAssignmentRequest.id)).where(*filters)
        )
        return HrProjectAssignmentListResponse(
            items=[
                self._response(request, employee, project) for request, employee, project in rows
            ],
            total=int(total or 0),
        )

    async def create(
        self, employee_id: UUID, payload: HrProjectAssignmentCreateRequest, actor: User
    ) -> HrProjectAssignmentResponse:
        ensure_permission(actor, PERMISSION_HR_EMPLOYEES_MANAGE)
        if payload.action == "revoke" and payload.role_in_project:
            raise AppException(
                "A removal request does not need a project role label.", status_code=422
            )
        employee = await self._employee(employee_id)
        project = await self.projects.projects.get_by_id(payload.project_id)
        if project is None:
            raise NotFoundException("Project")
        if project.status in READ_ONLY_STATUSES:
            raise AppException("This project is read-only.", status_code=409)
        linked_user = await self._validate_employee(employee, payload.action)
        current_member = await self.projects.projects.get_member(project.id, linked_user.id)
        if bool(current_member) == (payload.action == "assign"):
            raise AppException(
                "The project membership already matches this request.", status_code=409
            )
        request = HrProjectAssignmentRequest(
            employee_id=employee.id,
            project_id=project.id,
            linked_user_id=linked_user.id,
            requested_by_id=actor.id,
            action=payload.action,
            role_in_project=payload.role_in_project or None,
            reason=payload.reason,
        )
        self.session.add(request)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "A request for this employee and project is already pending.", status_code=409
            ) from exc
        await self.projects.audit.record(
            action="hr.project_assignment.requested",
            user_id=actor.id,
            entity_type="hr_project_assignment_requests",
            entity_id=request.id,
            new_values={"action": request.action, "project_id": str(project.id)},
        )
        await self.session.commit()
        await self.session.refresh(request)
        return self._response(request, employee, project)

    async def decide(
        self, project_id: UUID, request_id: UUID, payload: HrProjectAssignmentDecision, actor: User
    ) -> HrProjectAssignmentResponse:
        ensure_permission(actor, PERMISSION_PROJECTS_MANAGE)
        project = await self.projects.get_project(project_id, actor)
        request = await self.session.scalar(
            select(HrProjectAssignmentRequest)
            .where(
                HrProjectAssignmentRequest.id == request_id,
                HrProjectAssignmentRequest.project_id == project.id,
            )
            .with_for_update()
        )
        if request is None:
            raise NotFoundException("Project assignment request")
        if actor.id in {request.requested_by_id, request.linked_user_id}:
            raise PermissionDeniedException(PERMISSION_PROJECTS_MANAGE)
        if request.status != "pending":
            raise AppException(
                "The project assignment request is already decided.", status_code=409
            )
        employee = await self._employee(request.employee_id, include_deleted=True)
        if payload.decision == "reject" and not payload.note:
            raise AppException("Provide a reason for rejecting the request.", status_code=422)

        request.status = "approved" if payload.decision == "approve" else "rejected"
        request.decision_note = payload.note or None
        request.decided_by_id = actor.id
        request.decided_at = utc_now()
        await self.projects.audit.record(
            action="hr.project_assignment.decided",
            user_id=actor.id,
            entity_type="hr_project_assignment_requests",
            entity_id=request.id,
            new_values={"status": request.status, "project_id": str(project.id)},
        )
        if payload.decision == "reject":
            await self.projects._lock_membership_users(actor)
            await self.session.commit()
        else:
            linked_user = await self._validate_employee(employee, request.action)
            if request.linked_user_id != linked_user.id:
                raise AppException(
                    "The linked account changed. Request the assignment again.", status_code=409
                )
            # ProjectService commits the decision, both audit events and the membership together.
            if request.action == "assign":
                await self.projects.assign_member(
                    project.id,
                    ProjectMemberCreateRequest(
                        user_id=linked_user.id,
                        role_in_project=request.role_in_project,
                        expected_revision=payload.expected_project_revision,
                    ),
                    actor,
                )
            else:
                await self.projects.revoke_member(
                    project.id, linked_user.id, payload.expected_project_revision, actor
                )
        return self._response(request, employee, project)

    async def _employee(self, employee_id: UUID, *, include_deleted: bool = False) -> HrEmployee:
        query = select(HrEmployee).where(HrEmployee.id == employee_id)
        if not include_deleted:
            query = query.where(HrEmployee.deleted_at.is_(None))
        employee = await self.session.scalar(query.with_for_update())
        if employee is None:
            raise NotFoundException("Employee")
        return employee

    async def _validate_employee(self, employee: HrEmployee, action: str) -> User:
        user = await self.session.get(User, employee.user_id) if employee.user_id else None
        if (
            user is None
            or user.deleted_at is not None
            or (
                action == "assign"
                and (
                    not user.is_active
                    or employee.deleted_at is not None
                    or employee.employment_status not in ACTIVE_ASSIGNMENT_EMPLOYMENT
                )
            )
        ):
            raise AppException(
                "An eligible employee with a linked account is required.", status_code=409
            )
        return user

    @staticmethod
    def _response(
        request: HrProjectAssignmentRequest, employee: HrEmployee, project: Project
    ) -> HrProjectAssignmentResponse:
        return HrProjectAssignmentResponse(
            id=request.id,
            employee_id=employee.id,
            employee_name=employee.full_name,
            project_id=project.id,
            project_code=project.code,
            project_name=project.name,
            action=request.action,
            status=request.status,
            role_in_project=request.role_in_project,
            reason=request.reason,
            decision_note=request.decision_note,
            decided_at=request.decided_at,
            created_at=request.created_at,
        )
