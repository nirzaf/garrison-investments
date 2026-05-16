from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supervisor_update import SupervisorUpdate
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.supervisor_update_repository import SupervisorUpdateRepository
from app.schemas.supervisor_updates import SupervisorUpdateCreateRequest
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    ROLE_ADMIN,
    ROLE_CIVIL_ENGINEER,
    ROLE_CIVIL_SUPERVISOR,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
    ROLE_PROJECT_MANAGER,
)
from app.utils.security import utc_now

SUPERVISOR_UPDATE_STATUSES = {"draft", "submitted", "verified", "rejected"}


class ReportingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.updates = SupervisorUpdateRepository(session)
        self.audit = AuditService(session)

    async def create_supervisor_update(
        self,
        payload: SupervisorUpdateCreateRequest,
        actor: User,
    ) -> SupervisorUpdate:
        if actor.role != ROLE_CIVIL_SUPERVISOR:
            raise AppException(
                "Only Civil Supervisors can create supervisor updates.",
                status_code=403,
                error_code="SUPERVISOR_UPDATE_FORBIDDEN",
            )
        await self._ensure_project_member(payload.project_id, actor)
        self._validate_day_type(payload.day_type)
        self._validate_previous_date(payload, actor)
        update = SupervisorUpdate(
            project_id=payload.project_id,
            supervisor_id=actor.id,
            update_date=payload.update_date,
            day_type=payload.day_type,
            work_location=payload.work_location,
            attendance_count=payload.attendance_count,
            overtime_hours=payload.overtime_hours,
            progress_notes=payload.progress_notes,
            delay_notes=payload.delay_notes,
            required_notes=payload.required_notes,
            attachment_refs=[ref.model_dump() for ref in payload.attachment_refs],
            status="draft",
        )
        try:
            await self.updates.add(update)
            await self.audit.record(
                action="supervisor_updates.created",
                user_id=actor.id,
                entity_type="supervisor_updates",
                entity_id=update.id,
                new_values={"project_id": str(update.project_id), "date": str(update.update_date)},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "You already have a draft or submitted update for this project date.",
                status_code=409,
                error_code="SUPERVISOR_UPDATE_EXISTS",
            ) from exc
        return update

    async def update_supervisor_update(
        self,
        update_id: UUID,
        payload: SupervisorUpdateCreateRequest,
        actor: User,
    ) -> SupervisorUpdate:
        update = await self.updates.get_by_id(update_id)
        if not update:
            raise NotFoundException("Supervisor update")
        if update.supervisor_id != actor.id:
            raise NotFoundException("Supervisor update")
        if update.status != "draft":
            raise AppException(
                "Only draft updates can be autosaved.",
                status_code=409,
                error_code="SUPERVISOR_UPDATE_LOCKED",
            )
        await self._ensure_project_member(payload.project_id, actor)
        self._validate_day_type(payload.day_type)
        self._validate_previous_date(payload, actor)
        update.project_id = payload.project_id
        update.update_date = payload.update_date
        update.day_type = payload.day_type
        update.work_location = payload.work_location
        update.attendance_count = payload.attendance_count
        update.overtime_hours = payload.overtime_hours
        update.progress_notes = payload.progress_notes
        update.delay_notes = payload.delay_notes
        update.required_notes = payload.required_notes
        update.attachment_refs = [ref.model_dump() for ref in payload.attachment_refs]
        await self.audit.record(
            action="supervisor_updates.autosaved",
            user_id=actor.id,
            entity_type="supervisor_updates",
            entity_id=update.id,
            new_values={"project_id": str(update.project_id), "date": str(update.update_date)},
        )
        await self.session.commit()
        return update

    async def submit_supervisor_update(self, update_id: UUID, actor: User) -> SupervisorUpdate:
        update = await self.updates.get_by_id(update_id)
        if not update:
            raise NotFoundException("Supervisor update")
        if update.supervisor_id != actor.id:
            raise NotFoundException("Supervisor update")
        if update.status != "draft":
            raise AppException(
                "Only draft updates can be submitted.",
                status_code=409,
                error_code="SUPERVISOR_UPDATE_LOCKED",
            )
        update.status = "submitted"
        update.submitted_at = utc_now()
        await self.audit.record(
            action="supervisor_updates.submitted",
            user_id=actor.id,
            entity_type="supervisor_updates",
            entity_id=update.id,
        )
        await self.session.commit()
        return update

    async def list_supervisor_updates(
        self,
        *,
        current_user: User,
        project_id: UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[SupervisorUpdate], int]:
        self._validate_status(status)
        supervisor_id = current_user.id if current_user.role == ROLE_CIVIL_SUPERVISOR else None
        if current_user.role == ROLE_CIVIL_ENGINEER:
            if project_id is None:
                return [], 0
            await self._ensure_project_member(project_id, current_user)
        return await self.updates.list_updates(
            project_id=project_id,
            supervisor_id=supervisor_id,
            status=status,
            limit=min(limit, 200),
            offset=max(offset, 0),
        )

    async def _ensure_project_member(self, project_id: UUID, actor: User) -> None:
        project = await self.projects.get_by_id(project_id)
        if not project:
            raise NotFoundException("Project")
        members = await self.projects.list_members(project_id)
        if not any(member.user_id == actor.id for member in members):
            raise NotFoundException("Project")

    def _validate_previous_date(self, payload: SupervisorUpdateCreateRequest, actor: User) -> None:
        allowed_roles = {
            ROLE_ADMIN,
            ROLE_GENERAL_MANAGER,
            ROLE_OPERATION_MANAGER,
            ROLE_PROJECT_MANAGER,
            ROLE_CIVIL_ENGINEER,
        }
        is_previous_date = payload.update_date < (utc_now().date() - timedelta(days=1))
        if is_previous_date and actor.role not in allowed_roles:
            raise AppException(
                "Previous-date supervisor updates require admin approval.",
                status_code=409,
                error_code="PREVIOUS_DATE_UPDATE_BLOCKED",
            )

    def _validate_day_type(self, day_type: str) -> None:
        if day_type not in {"weekday", "friday", "public_holiday"}:
            raise AppException("Invalid day type.", status_code=422, error_code="INVALID_DAY_TYPE")

    def _validate_status(self, status: str | None) -> None:
        if status and status not in SUPERVISOR_UPDATE_STATUSES:
            raise AppException(
                "Invalid supervisor update status.",
                status_code=422,
                error_code="INVALID_SUPERVISOR_UPDATE_STATUS",
            )
