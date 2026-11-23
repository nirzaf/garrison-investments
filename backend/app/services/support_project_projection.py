from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import ScalarSelect

from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_milestone import ProjectMilestone
from app.models.project_task import ProjectTask
from app.models.support_case_actions import SupportCaseProject
from app.schemas.support_case_actions import MAX_CASE_PROJECTS
from app.services.project_service import PROJECT_STATUSES, UNRESTRICTED_PROJECT_ROLES
from app.utils.exceptions import NotFoundException
from app.utils.permissions import PERMISSION_PROJECTS_READ, permissions_for_role

PROJECT_VIEW_KINDS = {"project_list", "project_detail"}
_COUNT_LIMIT = 100


class MaskedProject(BaseModel):
    label: str
    status: str


class MaskedProjectDetail(MaskedProject):
    milestones: int
    tasks: int
    counts_capped: bool


@dataclass(frozen=True)
class MaskedProjects:
    projects: list[MaskedProject]
    scope_digest: str


def _bounded_count(model: type[ProjectMilestone] | type[ProjectTask]) -> ScalarSelect[int]:
    rows = (
        select(model.id)
        .where(model.project_id == Project.id, model.deleted_at.is_(None))
        .correlate(Project)
        .limit(_COUNT_LIMIT + 1)
        .subquery()
    )
    return select(func.count()).select_from(rows).scalar_subquery()


async def masked_projects(
    session: AsyncSession,
    case_id: UUID,
    user_id: UUID,
    role: str,
    *,
    project_id: UUID | None = None,
    project_label: str | None = None,
) -> MaskedProjects | MaskedProjectDetail:
    if PERMISSION_PROJECTS_READ not in permissions_for_role(role):
        raise NotFoundException("Support project")
    approved = {
        scoped_id: f"Project {index:02d}"
        for index, scoped_id in enumerate(
            await session.scalars(
                select(SupportCaseProject.project_id)
                .where(SupportCaseProject.case_id == case_id)
                .order_by(SupportCaseProject.project_id)
                .limit(MAX_CASE_PROJECTS)
            ),
            start=1,
        )
    }
    if project_label is not None:
        project_id = next((key for key, label in approved.items() if label == project_label), None)
        if project_id is None:
            raise NotFoundException("Support project")
    if project_id is not None and project_id not in approved:
        raise NotFoundException("Support project")

    query = select(Project.id, Project.status).where(
        Project.id.in_(approved), Project.deleted_at.is_(None)
    )
    if role not in UNRESTRICTED_PROJECT_ROLES:
        query = query.join(ProjectMember, ProjectMember.project_id == Project.id).where(
            ProjectMember.user_id == user_id, ProjectMember.deleted_at.is_(None)
        ).with_for_update(read=True, of=ProjectMember)
    if project_id is None:
        project_rows = (await session.execute(query.order_by(Project.id))).all()
        return MaskedProjects(
            projects=[
                MaskedProject(label=approved[row.id], status=_safe_status(row.status))
                for row in project_rows
            ],
            scope_digest=sha256(b"".join(row.id.bytes for row in project_rows)).hexdigest(),
        )

    row = (
        await session.execute(
            query.where(Project.id == project_id).add_columns(
                _bounded_count(ProjectMilestone).label("milestones"),
                _bounded_count(ProjectTask).label("tasks"),
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundException("Support project")
    return MaskedProjectDetail(
        label=approved[row.id],
        status=_safe_status(row.status),
        milestones=min(row.milestones, _COUNT_LIMIT),
        tasks=min(row.tasks, _COUNT_LIMIT),
        counts_capped=max(row.milestones, row.tasks) > _COUNT_LIMIT,
    )


def _safe_status(status: str) -> str:
    return status if status in PROJECT_STATUSES else "unknown"


async def portal_preview_projects(
    session: AsyncSession, case_id: UUID, user_id: UUID, role: str
) -> MaskedProjects:
    if PERMISSION_PROJECTS_READ not in permissions_for_role(role):
        return MaskedProjects(projects=[], scope_digest=sha256(b"").hexdigest())
    result = await masked_projects(session, case_id, user_id, role)
    assert isinstance(result, MaskedProjects)
    return result
