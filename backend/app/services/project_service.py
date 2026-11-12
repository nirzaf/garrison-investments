from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.boq_item import BoqItem
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_milestone import ProjectMilestone
from app.models.project_task import ProjectTask
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.projects import (
    BoqItemCreateRequest,
    ProjectCreateRequest,
    ProjectMemberCreateRequest,
    ProjectResponse,
    ProjectTaskCreateRequest,
    ProjectTaskResponse,
    ProjectTaskUpdateRequest,
    ProjectUpdateRequest,
)
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, ErrorDetail, NotFoundException
from app.utils.permissions import (
    PERMISSION_PROJECTS_MANAGE,
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
    ensure_permission,
)

PROJECT_STATUSES = {"planning", "active", "on_hold", "completed", "cancelled"}
PROJECT_TASK_STATUSES = {"not_started", "in_progress", "blocked", "completed", "cancelled"}
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
        ensure_permission(actor, PERMISSION_PROJECTS_MANAGE)
        self._validate_status(payload.status)
        self._validate_dates(payload.start_date, payload.target_end_date, "target_end_date")
        amounts = self._validate_setup(payload)
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
            await self._create_boq_items(project.id, payload.boq_items, amounts, milestones)
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
        project = await self._get_editable_project(project_id, actor)
        self._check_revision(
            project.revision, payload.expected_revision, "PROJECT_REVISION_CONFLICT"
        )
        proposed = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
        changes = {key: value for key, value in proposed.items() if getattr(project, key) != value}
        if not changes:
            return project
        self._validate_status(changes.get("status"))
        start = changes.get("start_date", project.start_date)
        if "start_date" in changes or "target_end_date" in changes:
            self._validate_dates(
                start, changes.get("target_end_date", project.target_end_date), "target_end_date"
            )
        if "start_date" in changes or "actual_end_date" in changes:
            self._validate_dates(
                start, changes.get("actual_end_date", project.actual_end_date), "actual_end_date"
            )
        fields = set(changes) | {"revision"}
        old_values = ProjectResponse.model_validate(project).model_dump(mode="json", include=fields)
        for field, value in changes.items():
            setattr(project, field, value)
        project.revision += 1
        await self.audit.record(
            action="projects.updated",
            user_id=actor.id,
            entity_type="projects",
            entity_id=project.id,
            old_values=old_values,
            new_values=ProjectResponse.model_validate(project).model_dump(
                mode="json", include=fields
            ),
        )
        await self.session.commit()
        return project

    async def assign_member(
        self,
        project_id: UUID,
        payload: ProjectMemberCreateRequest,
        actor: User,
    ) -> ProjectMember:
        project = await self._get_editable_project(project_id, actor)
        self._check_revision(
            project.revision, payload.expected_revision, "PROJECT_REVISION_CONFLICT"
        )
        user = await self.users.get_by_id(payload.user_id, for_update=True)
        if not user or not user.is_active:
            raise NotFoundException("User")
        member = ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role_in_project=payload.role_in_project or None,
        )
        try:
            await self.projects.add_member(member)
            project.revision += 1
            await self.audit.record(
                action="projects.member_assigned",
                user_id=actor.id,
                entity_type="projects",
                entity_id=project.id,
                new_values={
                    "member_user_id": str(user.id),
                    "role_in_project": member.role_in_project,
                    "revision": project.revision,
                },
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
        tasks = await self.projects.list_tasks(project.id)
        return project, milestones, tasks

    async def create_task(
        self,
        project_id: UUID,
        payload: ProjectTaskCreateRequest,
        actor: User,
    ) -> ProjectTask:
        project = await self._get_editable_project(project_id, actor)
        values = payload.model_dump()
        await self._validate_task_fields(project.id, values)
        task = ProjectTask(project_id=project.id, **values)
        await self.projects.add_task(task)
        await self.audit.record(
            action="projects.task_created",
            user_id=actor.id,
            entity_type="project_tasks",
            entity_id=task.id,
            new_values={
                "project_id": str(project.id),
                "owner_id": str(payload.owner_id) if payload.owner_id else None,
                "status": task.status,
            },
        )
        await self.session.commit()
        return task

    async def update_task(
        self,
        project_id: UUID,
        task_id: UUID,
        payload: ProjectTaskUpdateRequest,
        actor: User,
    ) -> ProjectTask:
        project = await self._get_editable_project(project_id, actor)
        task = await self.projects.get_task(project.id, task_id)
        if task is None:
            raise NotFoundException("Task")
        self._check_revision(
            task.revision, payload.expected_revision, "PROJECT_TASK_REVISION_CONFLICT"
        )
        proposed = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
        changes = {key: value for key, value in proposed.items() if getattr(task, key) != value}
        if not changes:
            return task
        await self._validate_task_fields(project.id, changes, task=task)
        fields = set(changes) | {"revision"}
        old_values = ProjectTaskResponse.model_validate(task).model_dump(
            mode="json", include=fields
        )
        for field, value in changes.items():
            setattr(task, field, value)
        task.revision += 1
        await self.audit.record(
            action="projects.task_updated",
            user_id=actor.id,
            entity_type="project_tasks",
            entity_id=task.id,
            old_values=old_values,
            new_values=ProjectTaskResponse.model_validate(task).model_dump(
                mode="json", include=fields
            ),
        )
        await self.session.commit()
        return task

    def _validate_setup(self, payload: ProjectCreateRequest) -> list[Decimal]:
        milestone_names: set[str] = set()
        for index, milestone in enumerate(payload.milestones):
            field = f"milestones.{index}"
            name = milestone.name.casefold()
            if name in milestone_names:
                raise self._invalid_field(
                    f"{field}.name",
                    "Milestone names must be unique.",
                    "PROJECT_MILESTONE_DUPLICATE",
                )
            milestone_names.add(name)
            self._validate_dates(
                milestone.planned_start_date,
                milestone.planned_end_date,
                f"{field}.planned_end_date",
            )
        seen_codes: set[str] = set()
        amounts: list[Decimal] = []
        for index, item in enumerate(payload.boq_items):
            field = f"boq_items.{index}"
            code = item.item_code.casefold()
            if code in seen_codes:
                raise self._invalid_field(
                    f"{field}.item_code",
                    "BOQ item codes must be unique.",
                    "BOQ_DUPLICATE_ITEM_CODE",
                )
            seen_codes.add(code)
            if item.milestone_name and item.milestone_name.casefold() not in milestone_names:
                raise self._invalid_field(
                    f"{field}.milestone_name",
                    "Select a milestone included in this project.",
                    "BOQ_UNKNOWN_MILESTONE",
                )
            amount = (item.planned_quantity * item.unit_rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if amount >= Decimal("10000000000000"):
                raise self._invalid_field(
                    f"{field}.unit_rate", "The planned amount is too large.", "BOQ_AMOUNT_TOO_LARGE"
                )
            amounts.append(amount)
        return amounts

    async def _validate_task_fields(
        self, project_id: UUID, fields: dict[str, Any], *, task: ProjectTask | None = None
    ) -> None:
        self._validate_task_status(fields.get("status"))
        for date_type in ("baseline", "planned", "actual"):
            start = f"{date_type}_start_date"
            end = f"{date_type}_end_date"
            if start in fields or end in fields:
                self._validate_dates(
                    fields.get(start, getattr(task, start, None)),
                    fields.get(end, getattr(task, end, None)),
                    end,
                )
        milestone_id = fields.get("milestone_id")
        if milestone_id and not await self.projects.get_milestone(project_id, milestone_id):
            raise self._invalid_field(
                "milestone_id",
                "Milestone does not belong to this project.",
                "PROJECT_TASK_INVALID_MILESTONE",
            )
        dependency_id = fields.get("dependency_task_id")
        if dependency_id:
            dependencies = {
                existing.id: existing.dependency_task_id
                for existing in await self.projects.list_tasks(project_id)
            }
            if dependency_id not in dependencies:
                raise self._invalid_field(
                    "dependency_task_id",
                    "Dependency task does not belong to this project.",
                    "PROJECT_TASK_INVALID_DEPENDENCY",
                )
            seen = {task.id} if task else set()
            while dependency_id is not None:
                if dependency_id in seen:
                    raise self._invalid_field(
                        "dependency_task_id",
                        "The dependency would create a cycle.",
                        "PROJECT_TASK_DEPENDENCY_CYCLE",
                    )
                seen.add(dependency_id)
                dependency_id = dependencies.get(dependency_id)
        owner_id = fields.get("owner_id")
        if owner_id:
            owner = await self.users.get_by_id(owner_id, for_update=True)
            if not owner or not owner.is_active:
                raise NotFoundException("User")

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
                    sort_order=(
                        milestone_payload.sort_order
                        if "sort_order" in milestone_payload.model_fields_set
                        else index
                    ),
                )
            )
            milestone_map[milestone.name.casefold()] = milestone.id
        return milestone_map

    async def _create_boq_items(
        self,
        project_id: UUID,
        boq_items: list[BoqItemCreateRequest],
        amounts: list[Decimal],
        milestone_map: dict[str, UUID],
    ) -> None:
        for item, amount in zip(boq_items, amounts, strict=True):
            await self.projects.add_boq_item(
                BoqItem(
                    project_id=project_id,
                    milestone_id=milestone_map[item.milestone_name.casefold()]
                    if item.milestone_name
                    else None,
                    item_code=item.item_code,
                    description=item.description,
                    discipline=item.discipline,
                    phase=item.phase,
                    unit=item.unit,
                    planned_quantity=item.planned_quantity,
                    unit_rate=item.unit_rate,
                    planned_amount=amount,
                )
            )

    async def _get_editable_project(self, project_id: UUID, actor: User) -> Project:
        ensure_permission(actor, PERMISSION_PROJECTS_MANAGE)
        project = await self._get_authorized_project(project_id, actor, for_update=True)
        if project.status in READ_ONLY_STATUSES:
            raise AppException(
                "Completed or cancelled projects are read-only.",
                status_code=409,
                error_code="PROJECT_READ_ONLY",
            )
        return project

    async def _get_authorized_project(
        self, project_id: UUID, current_user: User, *, for_update: bool = False
    ) -> Project:
        project = await self.projects.get_by_id(project_id, for_update=for_update)
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

    def _validate_task_status(self, status: str | None) -> None:
        if status and status not in PROJECT_TASK_STATUSES:
            raise AppException(
                "Invalid project task status.",
                status_code=422,
                error_code="INVALID_PROJECT_TASK_STATUS",
            )

    @staticmethod
    def _check_revision(revision: int, expected_revision: int | None, error_code: str) -> None:
        if expected_revision is not None and expected_revision != revision:
            raise AppException(
                "This record changed. Compare your edits with the latest version.",
                status_code=409,
                error_code=error_code,
            )

    def _validate_dates(self, start: date | None, end: date | None, end_field: str) -> None:
        if start is not None and end is not None and end < start:
            raise self._invalid_field(
                end_field, "End date must be on or after the start date.", "PROJECT_DATE_ORDER"
            )

    @staticmethod
    def _invalid_field(field: str, message: str, error_code: str) -> AppException:
        return AppException(
            message,
            status_code=422,
            error_code=error_code,
            errors=[ErrorDetail(field=field, message=message)],
        )
