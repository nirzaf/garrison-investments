from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str, *, for_update: bool = False) -> User | None:
        query = select(User).where(User.email == email.lower(), User.deleted_at.is_(None))
        return await self._get(query, for_update)

    async def get_by_id(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        query = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        return await self._get(query, for_update)

    async def _get(self, query: Select[User], for_update: bool) -> User | None:
        if for_update:
            query = query.with_for_update(key_share=True).execution_options(populate_existing=True)
        return await self.session.scalar(query)

    async def list_users(
        self,
        *,
        active: bool | None = None,
        role: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        query = select(User).where(User.deleted_at.is_(None))
        query = self._apply_filters(query, active=active, role=role, search=search)
        count_query = select(func.count()).select_from(
            self._apply_filters(
                select(User.id).where(User.deleted_at.is_(None)),
                active=active,
                role=role,
                search=search,
            ).subquery()
        )
        total = await self.session.scalar(count_query)
        result = await self.session.execute(
            query.order_by(User.full_name.asc(), User.id.asc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user

    async def display_names(self, user_ids: set[UUID]) -> dict[UUID, str]:
        if not user_ids:
            return {}
        result = await self.session.execute(
            select(User.id, User.full_name).where(User.id.in_(user_ids), User.deleted_at.is_(None))
        )
        return {user_id: name for user_id, name in result}

    def _apply_filters(
        self,
        query: Select,
        *,
        active: bool | None,
        role: str | None,
        search: str | None,
    ) -> Select:
        if active is not None:
            query = query.where(User.is_active.is_(active))
        if role:
            query = query.where(User.role == role)
        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(User.full_name).like(pattern),
                    func.lower(User.email).like(pattern),
                    func.lower(User.employee_code).like(pattern),
                )
            )
        return query
