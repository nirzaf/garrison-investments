from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.boq_item import BoqItem
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_milestone import ProjectMilestone


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_project_sequence(self) -> int:
        total = await self.session.scalar(select(func.count()).select_from(Project))
        return int(total or 0) + 1

    async def get_by_id(self, project_id: UUID) -> Project | None:
        result = await self.session.execute(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_projects(
        self,
        *,
        current_user_id: UUID,
        unrestricted: bool,
        status: str | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Project], int]:
        query: Select = select(Project).where(Project.deleted_at.is_(None))
        if not unrestricted:
            query = query.join(ProjectMember, ProjectMember.project_id == Project.id).where(
                ProjectMember.user_id == current_user_id,
                ProjectMember.deleted_at.is_(None),
            )
        query = self._apply_filters(query, status=status, search=search)
        count_query = select(func.count()).select_from(
            query.with_only_columns(Project.id).subquery()
        )
        total = await self.session.scalar(count_query)
        result = await self.session.execute(
            query.order_by(Project.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def add_project(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.flush()
        return project

    async def add_member(self, member: ProjectMember) -> ProjectMember:
        self.session.add(member)
        await self.session.flush()
        return member

    async def list_members(self, project_id: UUID) -> list[ProjectMember]:
        result = await self.session.execute(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.deleted_at.is_(None))
            .order_by(ProjectMember.assigned_at.asc())
        )
        return list(result.scalars().all())

    async def list_project_ids_for_user(self, user_id: UUID) -> list[UUID]:
        result = await self.session.execute(
            select(ProjectMember.project_id)
            .where(ProjectMember.user_id == user_id, ProjectMember.deleted_at.is_(None))
            .order_by(ProjectMember.assigned_at.asc())
        )
        return list(result.scalars().all())

    async def add_milestone(self, milestone: ProjectMilestone) -> ProjectMilestone:
        self.session.add(milestone)
        await self.session.flush()
        return milestone

    async def list_milestones(self, project_id: UUID) -> list[ProjectMilestone]:
        result = await self.session.execute(
            select(ProjectMilestone)
            .where(ProjectMilestone.project_id == project_id, ProjectMilestone.deleted_at.is_(None))
            .order_by(ProjectMilestone.sort_order.asc(), ProjectMilestone.created_at.asc())
        )
        return list(result.scalars().all())

    async def add_boq_item(self, item: BoqItem) -> BoqItem:
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_boq_items(self, project_id: UUID) -> list[BoqItem]:
        result = await self.session.execute(
            select(BoqItem)
            .where(BoqItem.project_id == project_id, BoqItem.deleted_at.is_(None))
            .order_by(BoqItem.item_code.asc())
        )
        return list(result.scalars().all())

    def _apply_filters(self, query: Select, *, status: str | None, search: str | None) -> Select:
        if status:
            query = query.where(Project.status == status)
        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(Project.name).like(pattern),
                    func.lower(Project.code).like(pattern),
                    func.lower(Project.client_name).like(pattern),
                    func.lower(Project.contract_number).like(pattern),
                )
            )
        return query
