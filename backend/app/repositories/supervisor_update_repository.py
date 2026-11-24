from uuid import UUID

from sqlalchemy import CTE, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supervisor_update import SupervisorUpdate, SupervisorUpdateSubmission


class SupervisorUpdateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, update: SupervisorUpdate) -> SupervisorUpdate:
        self.session.add(update)
        await self.session.flush()
        return update

    async def get_by_id(
        self, update_id: UUID, *, for_update: bool = False
    ) -> SupervisorUpdate | None:
        query = select(SupervisorUpdate).where(
            SupervisorUpdate.id == update_id,
            SupervisorUpdate.deleted_at.is_(None),
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(query)

    @staticmethod
    def _correction_ancestors(update_ids: list[UUID]) -> CTE:
        update = SupervisorUpdate
        ancestors = (
            select(update.id.label("selected_id"), update.id, update.previous_id)
            .where(update.id.in_(update_ids))
            .cte(recursive=True)
        )
        return ancestors.union(
            select(ancestors.c.selected_id, update.id, update.previous_id).join(
                ancestors, update.id == ancestors.c.previous_id
            )
        )

    async def lock_correction_roots(self, update_ids: list[UUID]) -> None:
        if not update_ids:
            return
        ancestors = self._correction_ancestors(update_ids)
        await self.session.scalars(
            select(SupervisorUpdate.id)
            .where(
                SupervisorUpdate.id.in_(
                    select(ancestors.c.id).where(ancestors.c.previous_id.is_(None))
                )
            )
            .order_by(SupervisorUpdate.id)
            .with_for_update()
        )

    async def linkable_update_ids(self, update_ids: list[UUID]) -> set[UUID]:
        if not update_ids:
            return set()
        ancestors = self._correction_ancestors(update_ids)
        update = SupervisorUpdate
        roots = select(ancestors.c.selected_id, ancestors.c.id).where(
            ancestors.c.previous_id.is_(None)
        )
        chain = roots.cte(recursive=True)
        chain = chain.union(
            select(chain.c.selected_id, update.id).join(chain, update.previous_id == chain.c.id)
        )
        return set(
            await self.session.scalars(
                select(chain.c.selected_id)
                .join(update, update.id == chain.c.id)
                .group_by(chain.c.selected_id)
                .having(
                    func.count().filter(update.verified_report_id.is_not(None)) == 0,
                    func.count().filter(
                        update.previous_id == chain.c.selected_id,
                        update.status == "verified",
                        update.deleted_at.is_(None),
                    )
                    == 0,
                )
            )
        )

    async def lock_linked(self, update_ids: list[UUID]) -> list[SupervisorUpdate]:
        if not update_ids:
            return []
        await self.lock_correction_roots(update_ids)
        return list(
            await self.session.scalars(
                select(SupervisorUpdate)
                .where(SupervisorUpdate.id.in_(update_ids), SupervisorUpdate.deleted_at.is_(None))
                .order_by(SupervisorUpdate.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    async def bound_ids(self, report_id: UUID) -> set[UUID]:
        return set(
            await self.session.scalars(
                select(SupervisorUpdate.id).where(
                    SupervisorUpdate.verified_report_id == report_id,
                    SupervisorUpdate.deleted_at.is_(None),
                )
            )
        )

    async def list_report_evidence(
        self, report_id: UUID, project_id: UUID, update_ids: list[UUID]
    ) -> list[SupervisorUpdate]:
        linkable_ids = await self.linkable_update_ids(update_ids)
        return list(
            await self.session.scalars(
                select(SupervisorUpdate)
                .where(
                    SupervisorUpdate.id.in_(update_ids),
                    SupervisorUpdate.project_id == project_id,
                    SupervisorUpdate.deleted_at.is_(None),
                    or_(
                        SupervisorUpdate.verified_report_id == report_id,
                        (
                            (SupervisorUpdate.status == "verified")
                            & SupervisorUpdate.verified_report_id.is_(None)
                            & SupervisorUpdate.id.in_(linkable_ids)
                            & SupervisorUpdate.submission_revision.is_not(None)
                        ),
                    ),
                )
                .order_by(SupervisorUpdate.update_date.desc(), SupervisorUpdate.id)
            )
        )

    async def list_updates(
        self,
        *,
        project_id: UUID | None,
        supervisor_id: UUID | None,
        status: str | None,
        limit: int,
        offset: int,
        project_ids: list[UUID] | None = None,
        qs_reviewer_id: UUID | None = None,
        update_id: UUID | None = None,
    ) -> tuple[list[SupervisorUpdate], int]:
        query: Select = select(SupervisorUpdate).where(SupervisorUpdate.deleted_at.is_(None))
        if project_id:
            query = query.where(SupervisorUpdate.project_id == project_id)
        if update_id is not None:
            query = query.where(SupervisorUpdate.id == update_id)
        if qs_reviewer_id is not None:
            query = query.where(
                select(SupervisorUpdateSubmission.update_id)
                .where(
                    SupervisorUpdateSubmission.update_id == SupervisorUpdate.id,
                    SupervisorUpdateSubmission.submission_revision
                    == SupervisorUpdate.submission_revision,
                    SupervisorUpdateSubmission.qs_id == qs_reviewer_id,
                )
                .exists()
            )
        if project_ids is not None:
            query = query.where(SupervisorUpdate.project_id.in_(project_ids))
        if supervisor_id:
            query = query.where(SupervisorUpdate.supervisor_id == supervisor_id)
        else:
            query = query.where(SupervisorUpdate.status != "draft")
        if status:
            query = query.where(SupervisorUpdate.status == status)
        total = await self.session.scalar(
            select(func.count()).select_from(
                query.with_only_columns(SupervisorUpdate.id).subquery()
            )
        )
        result = await self.session.execute(
            query.order_by(SupervisorUpdate.update_date.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)
