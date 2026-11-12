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

    async def get_by_id(self, photo_id: UUID, *, for_update: bool = False) -> Photo | None:
        query = select(Photo).where(Photo.id == photo_id, Photo.deleted_at.is_(None))
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(query)

    async def get_deleted_by_id(self, photo_id: UUID, *, for_update: bool = False) -> Photo | None:
        query = select(Photo).where(Photo.id == photo_id, Photo.deleted_at.is_not(None))
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(query)

    async def count_photos(self, entity_type: str, entity_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count(Photo.id)).where(
                Photo.entity_type == entity_type,
                Photo.entity_id == entity_id,
                Photo.kind == "photo",
                Photo.deleted_at.is_(None),
            )
        )
        return int(count or 0)

    async def list_deleted(
        self,
        *,
        entity_type: str | None,
        entity_id: UUID | None,
        kind: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Photo], int]:
        query = select(Photo).where(Photo.deleted_at.is_not(None))
        if entity_type:
            query = query.where(Photo.entity_type == entity_type)
        if entity_id:
            query = query.where(Photo.entity_id == entity_id)
        if kind:
            query = query.where(Photo.kind == kind)
        total = await self.session.scalar(
            select(func.count()).select_from(query.with_only_columns(Photo.id).subquery())
        )
        rows = await self.session.scalars(
            query.order_by(Photo.deleted_at.desc(), Photo.id).limit(limit).offset(offset)
        )
        return list(rows), int(total or 0)

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
        engineer_id: UUID | None = None,
    ) -> tuple[list[Photo], int]:
        query: Select = select(Photo).where(Photo.deleted_at.is_(None))
        if entity_type:
            query = query.where(Photo.entity_type == entity_type)
        if kind:
            query = query.where(Photo.kind == kind)
        if project_ids is not None or engineer_id is not None:
            query = query.join(DailyReport, DailyReport.id == Photo.entity_id).where(
                Photo.entity_type == "daily_report",
                DailyReport.deleted_at.is_(None),
            )
        if project_ids is not None:
            query = query.where(DailyReport.project_id.in_(project_ids))
        if engineer_id is not None:
            query = query.where(DailyReport.engineer_id == engineer_id)
        total = await self.session.scalar(
            select(func.count()).select_from(query.with_only_columns(Photo.id).subquery())
        )
        result = await self.session.execute(
            query.order_by(Photo.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)
