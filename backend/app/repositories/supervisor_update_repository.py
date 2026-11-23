from uuid import UUID

from sqlalchemy import Select, func, or_, select
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

    async def lock_linked(self, update_ids: list[UUID]) -> list[SupervisorUpdate]:
        if not update_ids:
            return []
        return list(
            await self.session.scalars(
                select(SupervisorUpdate)
                .where(SupervisorUpdate.id.in_(update_ids), SupervisorUpdate.deleted_at.is_(None))
                .order_by(SupervisorUpdate.id)
                .with_for_update()
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
