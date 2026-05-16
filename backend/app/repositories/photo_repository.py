from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
