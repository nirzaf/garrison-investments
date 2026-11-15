"""Shared project/entity authorization helpers.

Only the two director roles have company-wide resource scope. Dashboard grants do
not grant broad resource access; other roles require active project membership.

Denial conventions (ground rule 6):
* entity-level denials raise 404 so an out-of-scope id is indistinguishable from a
  missing one;
* project-level scope denials raise 403 ``PROJECT_FORBIDDEN``, mirroring
  ``finance_service._ensure_project_scope``.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.document import Document
from app.models.supervisor_update import SupervisorUpdate
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_REPORTS_SUBMIT,
    PERMISSION_REPORTS_VIEW,
    SUPERVISOR_ROLES,
    VALID_ROLES,
    has_permission,
)

COMPANY_WIDE_ROLES = COMPANY_RESOURCE_ROLES


async def accessible_project_ids(session: AsyncSession, actor: User) -> list[UUID] | None:
    """``None`` means unrestricted (company-wide); a list means membership-scoped.

    An empty list is meaningful: the actor belongs to no project and must see nothing.
    """
    _ensure_supported_role(actor)
    if actor.role in COMPANY_WIDE_ROLES:
        return None
    return await ProjectRepository(session).list_project_ids_for_user(actor.id)


async def ensure_project_access(session: AsyncSession, project_id: UUID, actor: User) -> None:
    _ensure_supported_role(actor)
    if actor.role in COMPANY_WIDE_ROLES:
        return
    project_ids = await accessible_project_ids(session, actor) or []
    if project_id not in project_ids:
        raise AppException(
            "This project is outside your assigned scope.",
            status_code=403,
            error_code="PROJECT_FORBIDDEN",
        )


async def document_scope_filter(session: AsyncSession, actor: User) -> ColumnElement[bool] | None:
    """Predicate for ``Document`` queries, or ``None`` when unrestricted.

    ``project_id IS NULL`` documents are company-wide: SQL ``IN`` never matches NULL, so
    they are excluded for every scoped role without a special case.
    """
    _ensure_supported_role(actor)
    if actor.role in COMPANY_WIDE_ROLES:
        return None
    project_ids = await accessible_project_ids(session, actor) or []
    return Document.project_id.in_(project_ids)


async def ensure_document_access(session: AsyncSession, document: Document, actor: User) -> None:
    _ensure_supported_role(actor)
    if actor.role in COMPANY_WIDE_ROLES:
        return
    if document.project_id is None:
        raise NotFoundException("Document")
    project_ids = await accessible_project_ids(session, actor) or []
    if document.project_id not in project_ids:
        raise NotFoundException("Document")


async def ensure_entity_access(
    session: AsyncSession,
    entity_type: str,
    entity_id: UUID,
    actor: User,
) -> None:
    """Verify the actor may reach the owner of a photo/attachment before any I/O."""
    _ensure_supported_role(actor)
    if entity_type == "daily_report":
        # Imported lazily: report_service imports this module, so a top-level import
        # would be circular. get_report already enforces engineer/PM/company-wide rules.
        from app.services.report_service import ReportService

        await ReportService(session).get_report(entity_id, actor)
        return
    if entity_type == "project":
        await ensure_project_access(session, entity_id, actor)
        return
    if entity_type == "supervisor_update":
        update = await session.scalar(
            select(SupervisorUpdate).where(
                SupervisorUpdate.id == entity_id,
                SupervisorUpdate.deleted_at.is_(None),
            )
        )
        if update is None:
            raise NotFoundException("Supervisor update")
        if update.supervisor_id == actor.id and has_permission(actor, PERMISSION_REPORTS_SUBMIT):
            return
        if not has_permission(actor, PERMISSION_REPORTS_VIEW):
            raise NotFoundException("Supervisor update")
        if update.status == "draft" or actor.role in SUPERVISOR_ROLES:
            raise NotFoundException("Supervisor update")
        if actor.role in COMPANY_WIDE_ROLES:
            return
        project_ids = await accessible_project_ids(session, actor) or []
        if update.project_id not in project_ids:
            raise NotFoundException("Supervisor update")
        return
    if entity_type == "document":
        document = await session.scalar(
            select(Document).where(Document.id == entity_id, Document.deleted_at.is_(None))
        )
        if document is None:
            raise NotFoundException("Document")
        await ensure_document_access(session, document, actor)
        return
    raise AppException(
        "Invalid file owner.",
        status_code=422,
        error_code="INVALID_ENTITY_TYPE",
    )


def _ensure_supported_role(actor: User) -> None:
    if actor.role not in VALID_ROLES:
        raise AppException(
            "Account has an unsupported role.",
            status_code=403,
            error_code="INVALID_ROLE",
        )
