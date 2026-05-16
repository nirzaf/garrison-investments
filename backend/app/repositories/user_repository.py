from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email.lower(), User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

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
            query.order_by(User.full_name.asc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user

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
