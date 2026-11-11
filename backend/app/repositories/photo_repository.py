from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_report import DailyReport
from app.models.photo import Photo


class PhotoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, photo: Photo) -> Photo:
        self.session.add(photo)
        await self.session.flush()
        return photo

    async def get_by_id(self, photo_id: UUID) -> Photo | None:
        result = await self.session.execute(
            select(Photo).where(Photo.id == photo_id, Photo.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_deleted_by_id(self, photo_id: UUID) -> Photo | None:
        result = await self.session.execute(
            select(Photo).where(Photo.id == photo_id, Photo.deleted_at.is_not(None))
        )
        return result.scalar_one_or_none()

    async def list_for_entity(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Photo], int]:
        query: Select = select(Photo).where(
            Photo.entity_type == entity_type,
            Photo.entity_id == entity_id,
            Photo.deleted_at.is_(None),
        )
        if kind:
            query = query.where(Photo.kind == kind)
        total = await self.session.scalar(
            select(func.count()).select_from(query.with_only_columns(Photo.id).subquery())
        )
        result = await self.session.execute(
            query.order_by(Photo.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def list_recent(
        self,
        *,
        entity_type: str | None = None,
        kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
        project_ids: list[UUID] | None = None,
    ) -> tuple[list[Photo], int]:
        query: Select = select(Photo).where(Photo.deleted_at.is_(None))
        if entity_type:
            query = query.where(Photo.entity_type == entity_type)
        if kind:
            query = query.where(Photo.kind == kind)
        if project_ids is not None:
            # None means company-wide. Otherwise the feed is limited to daily reports in
            # the actor's projects; an empty list deliberately matches nothing.
            query = query.join(DailyReport, DailyReport.id == Photo.entity_id).where(
                Photo.entity_type == "daily_report",
                DailyReport.deleted_at.is_(None),
                DailyReport.project_id.in_(project_ids),
            )
        total = await self.session.scalar(
            select(func.count()).select_from(query.with_only_columns(Photo.id).subquery())
        )
        result = await self.session.execute(
            query.order_by(Photo.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)
