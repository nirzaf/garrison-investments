from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.user import User
from app.utils.permissions import ROLE_ADMIN
from app.utils.security import utc_now


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

    async def lock_access_management(self) -> None:
        # Two administrators can act on different rows, so a target row lock alone
        # cannot protect the last administrator across transactions.
        await self.session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext("garrison.user_access_management")))
        )

    async def lock_users(
        self, *user_ids: UUID, include_active_admins: bool = False
    ) -> dict[UUID, User]:
        selected: ColumnElement[bool] = User.id.in_(user_ids)
        if include_active_admins:
            # Lock candidate admins in the same order as the actor and target. Their
            # credential and lockout state also determines whether they can sign in.
            selected = or_(selected, and_(User.role == ROLE_ADMIN, User.is_active.is_(True)))
        result = await self.session.scalars(
            select(User)
            .where(selected, User.deleted_at.is_(None))
            .order_by(User.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        return {user.id: user for user in result}

    async def has_other_usable_admin(self, excluded_user_id: UUID) -> bool:
        other_id = await self.session.scalar(
            select(User.id)
            .where(
                User.id != excluded_user_id,
                User.role == ROLE_ADMIN,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                User.password_hash.is_not(None),
                User.password_hash != "",
                or_(User.locked_until.is_(None), User.locked_until <= utc_now()),
            )
            .limit(1)
        )
        return other_id is not None

    async def list_users(
        self,
        *,
        active: bool | None = None,
        role: str | None = None,
        search: str | None = None,
        email: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        query = select(User).where(User.deleted_at.is_(None))
        query = self._apply_filters(query, active=active, role=role, search=search, email=email)
        count_query = select(func.count()).select_from(query.with_only_columns(User.id).subquery())
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
        email: str | None,
    ) -> Select:
        if active is not None:
            query = query.where(User.is_active.is_(active))
        if role:
            query = query.where(User.role == role)
        if email:
            query = query.where(User.email == email.lower())
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
