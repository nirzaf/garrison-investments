from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.users import AdminPasswordResetRequest, UserCreateRequest, UserUpdateRequest
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import validate_role
from app.utils.security import hash_password, validate_password_policy


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    async def list_users(
        self,
        *,
        active: bool | None,
        role: str | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        normalized_role = validate_role(role) if role else None
        return await self.users.list_users(
            active=active,
            role=normalized_role,
            search=search,
            limit=min(limit, 200),
            offset=max(offset, 0),
        )

    async def create_user(self, payload: UserCreateRequest, actor: User) -> User:
        validate_password_policy(payload.temporary_password)
        user = User(
            email=payload.email.lower(),
            full_name=payload.full_name.strip(),
            role=validate_role(payload.role),
            employee_code=payload.employee_code.strip(),
            phone=payload.phone.strip(),
            designation=payload.designation.strip() if payload.designation else None,
            password_hash=hash_password(payload.temporary_password),
            must_change_password=True,
        )
        try:
            await self.users.add(user)
            await self.audit.record(
                action="users.created",
                user_id=actor.id,
                entity_type="users",
                entity_id=user.id,
                new_values={"email": user.email, "role": user.role},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "A user with this email or employee code already exists.",
                status_code=409,
                error_code="USER_ALREADY_EXISTS",
            ) from exc
        return user

    async def update_user(self, user_id: UUID, payload: UserUpdateRequest, actor: User) -> User:
        user = await self.users.get_by_id(user_id)
        if not user:
            raise NotFoundException("User")
        old_values = {
            "full_name": user.full_name,
            "role": user.role,
            "employee_code": user.employee_code,
            "phone": user.phone,
            "designation": user.designation,
            "is_active": user.is_active,
        }
        if payload.full_name is not None:
            user.full_name = payload.full_name.strip()
        if payload.role is not None:
            user.role = validate_role(payload.role)
        if payload.employee_code is not None:
            user.employee_code = payload.employee_code.strip()
        if payload.phone is not None:
            user.phone = payload.phone.strip()
        if payload.designation is not None:
            user.designation = payload.designation.strip() or None
        if payload.is_active is not None:
            if user.id == actor.id and not payload.is_active:
                raise AppException(
                    "Admins cannot deactivate their own account.",
                    status_code=409,
                    error_code="SELF_DEACTIVATION_BLOCKED",
                )
            user.is_active = payload.is_active
        try:
            await self.audit.record(
                action="users.updated",
                user_id=actor.id,
                entity_type="users",
                entity_id=user.id,
                old_values=old_values,
                new_values={
                    "full_name": user.full_name,
                    "role": user.role,
                    "employee_code": user.employee_code,
                    "phone": user.phone,
                    "designation": user.designation,
                    "is_active": user.is_active,
                },
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "A user with this email or employee code already exists.",
                status_code=409,
                error_code="USER_ALREADY_EXISTS",
            ) from exc
        return user

    async def deactivate_user(self, user_id: UUID, actor: User) -> User:
        return await self.update_user(user_id, UserUpdateRequest(is_active=False), actor)

    async def admin_reset_password(
        self,
        user_id: UUID,
        payload: AdminPasswordResetRequest,
        actor: User,
    ) -> User:
        if user_id == actor.id:
            raise AppException(
                "Use the change-password endpoint to update your own password.",
                status_code=409,
                error_code="SELF_PASSWORD_RESET_BLOCKED",
            )
        user = await self.users.get_by_id(user_id)
        if not user:
            raise NotFoundException("User")
        validate_password_policy(payload.new_password)
        user.password_hash = hash_password(payload.new_password)
        user.must_change_password = True
        await self.audit.record(
            action="users.password_reset_by_admin",
            user_id=actor.id,
            entity_type="users",
            entity_id=user.id,
            new_values={"reset_by": str(actor.id)},
        )
        await self.session.commit()
        return user
