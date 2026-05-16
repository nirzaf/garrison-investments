from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.boq_item import BoqItem
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_milestone import ProjectMilestone
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.projects import (
    BoqItemCreateRequest,
    ProjectCreateRequest,
    ProjectMemberCreateRequest,
    ProjectUpdateRequest,
)
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
)

PROJECT_STATUSES = {"planning", "active", "on_hold", "completed", "cancelled"}
READ_ONLY_STATUSES = {"completed", "cancelled"}
UNRESTRICTED_PROJECT_ROLES = {
    ROLE_ADMIN,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
    ROLE_ACCOUNTS,
}


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    async def list_projects(
        self,
        *,
        current_user: User,
        status: str | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Project], int]:
        self._validate_status(status)
        return await self.projects.list_projects(
            current_user_id=current_user.id,
            unrestricted=current_user.role in UNRESTRICTED_PROJECT_ROLES,
            status=status,
            search=search,
            limit=min(limit, 200),
            offset=max(offset, 0),
        )

    async def get_project_detail(self, project_id: UUID, current_user: User):
        project = await self._get_authorized_project(project_id, current_user)
        members = await self.projects.list_members(project.id)
        milestones = await self.projects.list_milestones(project.id)
        boq_items = await self.projects.list_boq_items(project.id)
        return project, members, milestones, boq_items

    async def create_project(self, payload: ProjectCreateRequest, actor: User) -> Project:
        self._validate_status(payload.status)
        if not payload.boq_items:
            raise AppException(
                "Project creation requires at least one BOQ item.",
                status_code=422,
                error_code="PROJECT_BOQ_REQUIRED",
            )
        project = Project(
            name=payload.name.strip(),
            code=await self._generate_project_code(payload.name),
            location=payload.location,
            description=payload.description,
            scope_of_work=payload.scope_of_work,
            status=payload.status,
            budget_amount=payload.budget_amount,
            start_date=payload.start_date,
            target_end_date=payload.target_end_date,
            client_name=payload.client_name,
            contract_number=payload.contract_number,
            created_by=actor.id,
        )
        try:
            await self.projects.add_project(project)
            milestones = await self._create_milestones(project.id, payload)
            await self._create_boq_items(project.id, payload.boq_items, milestones)
            await self.audit.record(
                action="projects.created",
                user_id=actor.id,
                entity_type="projects",
                entity_id=project.id,
                new_values={"code": project.code, "status": project.status},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Project code or BOQ item code already exists.",
                status_code=409,
                error_code="PROJECT_CONFLICT",
            ) from exc
        return project

    async def update_project(
        self,
        project_id: UUID,
        payload: ProjectUpdateRequest,
        actor: User,
    ) -> Project:
        project = await self._get_authorized_project(project_id, actor)
        if project.status in READ_ONLY_STATUSES:
            raise AppException(
                "Completed or cancelled projects are read-only.",
                status_code=409,
                error_code="PROJECT_READ_ONLY",
            )
        old_values = {"status": project.status, "name": project.name}
        if payload.status is not None:
            self._validate_status(payload.status)
            project.status = payload.status
        for field in (
            "name",
            "scope_of_work",
            "target_end_date",
            "location",
            "description",
            "budget_amount",
            "start_date",
            "actual_end_date",
            "client_name",
            "contract_number",
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(project, field, value.strip() if isinstance(value, str) else value)
        await self.audit.record(
            action="projects.updated",
            user_id=actor.id,
            entity_type="projects",
            entity_id=project.id,
            old_values=old_values,
            new_values={"status": project.status, "name": project.name},
        )
        await self.session.commit()
        return project

    async def assign_member(
        self,
        project_id: UUID,
        payload: ProjectMemberCreateRequest,
        actor: User,
    ) -> ProjectMember:
        project = await self._get_authorized_project(project_id, actor)
        if project.status in READ_ONLY_STATUSES:
            raise AppException(
                "Completed or cancelled projects are read-only.",
                status_code=409,
                error_code="PROJECT_READ_ONLY",
            )
        user = await self.users.get_by_id(payload.user_id)
        if not user or not user.is_active:
            raise NotFoundException("User")
        member = ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role_in_project=payload.role_in_project,
        )
        try:
            await self.projects.add_member(member)
            await self.audit.record(
                action="projects.member_assigned",
                user_id=actor.id,
                entity_type="projects",
                entity_id=project.id,
                new_values={"member_user_id": str(user.id)},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "User is already assigned to this project.",
                status_code=409,
                error_code="PROJECT_MEMBER_EXISTS",
            ) from exc
        return member

    async def list_members(self, project_id: UUID, current_user: User) -> list[ProjectMember]:
        project = await self._get_authorized_project(project_id, current_user)
        return await self.projects.list_members(project.id)

    async def list_timeline(self, project_id: UUID, current_user: User):
        project = await self._get_authorized_project(project_id, current_user)
        milestones = await self.projects.list_milestones(project.id)
        return project, milestones

    async def _create_milestones(
        self,
        project_id: UUID,
        payload: ProjectCreateRequest,
    ) -> dict[str, UUID]:
        milestone_map: dict[str, UUID] = {}
        for index, milestone_payload in enumerate(payload.milestones):
            milestone = await self.projects.add_milestone(
                ProjectMilestone(
                    project_id=project_id,
                    name=milestone_payload.name.strip(),
                    discipline=milestone_payload.discipline,
                    planned_start_date=milestone_payload.planned_start_date,
                    planned_end_date=milestone_payload.planned_end_date,
                    sort_order=milestone_payload.sort_order or index,
                )
            )
            milestone_map[milestone.name.lower()] = milestone.id
        return milestone_map

    async def _create_boq_items(
        self,
        project_id: UUID,
        boq_items: list[BoqItemCreateRequest],
        milestone_map: dict[str, UUID],
    ) -> None:
        seen_codes: set[str] = set()
        for item in boq_items:
            code = item.item_code.strip()
            if code.lower() in seen_codes:
                raise AppException(
                    "BOQ item codes must be unique within a project.",
                    status_code=422,
                    error_code="BOQ_DUPLICATE_ITEM_CODE",
                )
            seen_codes.add(code.lower())
            milestone_id = None
            if item.milestone_name:
                milestone_id = milestone_map.get(item.milestone_name.strip().lower())
            await self.projects.add_boq_item(
                BoqItem(
                    project_id=project_id,
                    milestone_id=milestone_id,
                    item_code=code,
                    description=item.description,
                    discipline=item.discipline,
                    phase=item.phase,
                    unit=item.unit,
                    planned_quantity=item.planned_quantity,
                    unit_rate=item.unit_rate,
                    planned_amount=Decimal(item.planned_quantity * item.unit_rate),
                )
            )

    async def _get_authorized_project(self, project_id: UUID, current_user: User) -> Project:
        project = await self.projects.get_by_id(project_id)
        if not project:
            raise NotFoundException("Project")
        if current_user.role in UNRESTRICTED_PROJECT_ROLES:
            return project
        members = await self.projects.list_members(project_id)
        if any(member.user_id == current_user.id for member in members):
            return project
        raise NotFoundException("Project")

    async def _generate_project_code(self, name: str) -> str:
        sequence = await self.projects.next_project_sequence()
        prefix = "".join(char for char in name.upper() if char.isalnum())[:3] or "PRJ"
        return f"{prefix}-{sequence:04d}"

    def _validate_status(self, status: str | None) -> None:
        if status and status not in PROJECT_STATUSES:
            raise AppException(
                "Invalid project status.",
                status_code=422,
                error_code="INVALID_PROJECT_STATUS",
            )
