from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.repositories.user_repository import UserRepository
from app.schemas.users import AdminPasswordResetRequest, UserCreateRequest, UserUpdateRequest
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_USERS_MANAGE,
    can_assign_user_role,
    ensure_permission,
    validate_role,
)
from app.utils.security import hash_password, utc_now, validate_password_policy


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.auth = AuthRepository(session)
        self.audit = AuditService(session)

    async def list_users(
        self,
        *,
        active: bool | None,
        role: str | None,
        search: str | None,
        email: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        normalized_role = validate_role(role) if role else None
        return await self.users.list_users(
            active=active,
            role=normalized_role,
            search=search,
            email=email,
            limit=min(limit, 200),
            offset=max(offset, 0),
        )

    async def create_user(
        self, payload: UserCreateRequest, actor: User, *, commit: bool = True
    ) -> User:
        validate_password_policy(payload.temporary_password)
        target_role = validate_role(payload.role)
        await self._lock_managed_users(actor)
        if not can_assign_user_role(actor.role, target_role):
            raise PermissionDeniedException(PERMISSION_USERS_MANAGE)
        user = User(
            email=payload.email.lower(),
            full_name=payload.full_name.strip(),
            role=target_role,
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
            if commit:
                await self.session.commit()
            else:
                await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "A user with this email or employee code already exists.",
                status_code=409,
                error_code="USER_ALREADY_EXISTS",
            ) from exc
        return user

    async def get_user(self, user_id: UUID) -> User:
        user = await self.users.get_by_id(user_id)
        if not user:
            raise NotFoundException("User")
        return user

    async def update_user(
        self, user_id: UUID, payload: UserUpdateRequest, actor: User, *, commit: bool = True
    ) -> User:
        if ("role" in payload.model_fields_set or "is_active" in payload.model_fields_set) and (
            payload.expected_updated_at is None
        ):
            raise AppException(
                "Reload the user and include expected_updated_at before changing access.",
                status_code=422,
                error_code="USER_PRECONDITION_REQUIRED",
            )
        user = await self._lock_target(
            actor,
            user_id,
            payload.expected_updated_at,
            include_active_directors=payload.role is not None or payload.is_active is not None,
        )
        role = validate_role(payload.role) if payload.role is not None else user.role
        active = user.is_active if payload.is_active is None else payload.is_active
        if not can_assign_user_role(actor.role, user.role) or not can_assign_user_role(
            actor.role, role
        ):
            raise PermissionDeniedException(PERMISSION_USERS_MANAGE)
        if user.id == actor.id and role != user.role:
            raise AppException(
                "You cannot change your own role.",
                status_code=409,
                error_code="SELF_ROLE_CHANGE_BLOCKED",
            )
        if user.id == actor.id and not active:
            raise AppException(
                "You cannot deactivate your own account.",
                status_code=409,
                error_code="SELF_DEACTIVATION_BLOCKED",
            )
        if (
            user.is_active
            and user.role in COMPANY_RESOURCE_ROLES
            and (not active or role not in COMPANY_RESOURCE_ROLES)
            and not await self.users.has_other_usable_director(user.id)
        ):
            raise AppException(
                "At least one other director account must be able to sign in.",
                status_code=409,
                error_code="LAST_ACCESS_MANAGER_REQUIRED",
            )
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
        if payload.employee_code is not None:
            user.employee_code = payload.employee_code.strip()
        if payload.phone is not None:
            user.phone = payload.phone.strip()
        if "designation" in payload.model_fields_set:
            user.designation = (payload.designation or "").strip() or None
        access_changed = user.role != role or user.is_active != active
        user.role = role
        user.is_active = active
        user.updated_at = utc_now()
        try:
            if access_changed:
                user.access_revision += 1
                await self.auth.revoke_user_authentication(user.id)
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
            if commit:
                await self.session.commit()
            else:
                await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "A user with this email or employee code already exists.",
                status_code=409,
                error_code="USER_ALREADY_EXISTS",
            ) from exc
        return user

    async def deactivate_user(
        self, user_id: UUID, actor: User, *, expected_updated_at: datetime | None = None
    ) -> User:
        return await self.update_user(
            user_id,
            UserUpdateRequest(is_active=False, expected_updated_at=expected_updated_at),
            actor,
        )

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
        if payload.expected_updated_at is None:
            raise AppException(
                "Reload the user and include expected_updated_at before resetting credentials.",
                status_code=422,
                error_code="USER_PRECONDITION_REQUIRED",
            )
        validate_password_policy(payload.new_password)
        user = await self._lock_target(actor, user_id, payload.expected_updated_at)
        if not can_assign_user_role(actor.role, user.role):
            raise PermissionDeniedException(PERMISSION_USERS_MANAGE)
        user.password_hash = hash_password(payload.new_password)
        user.must_change_password = True
        user.access_revision += 1
        user.updated_at = utc_now()
        await self.auth.revoke_user_authentication(user.id)
        await self.audit.record(
            action="users.password_reset_by_admin",
            user_id=actor.id,
            entity_type="users",
            entity_id=user.id,
            new_values={"reset_by": str(actor.id)},
        )
        await self.session.commit()
        return user

    async def _lock_managed_users(
        self, actor: User, *targets: UUID, include_active_directors: bool = False
    ) -> dict[UUID, User]:
        actor_access_revision = actor.access_revision
        await self.users.lock_access_management()
        users = await self.users.lock_users(
            actor.id, *targets, include_active_directors=include_active_directors
        )
        current_actor = users.get(actor.id)
        if (
            not current_actor
            or not current_actor.is_active
            or current_actor.access_revision != actor_access_revision
        ):
            raise PermissionDeniedException(PERMISSION_USERS_MANAGE)
        ensure_permission(current_actor, PERMISSION_USERS_MANAGE)
        return users

    async def _lock_target(
        self,
        actor: User,
        user_id: UUID,
        expected_updated_at: datetime | None,
        *,
        include_active_directors: bool = False,
    ) -> User:
        users = await self._lock_managed_users(
            actor, user_id, include_active_directors=include_active_directors
        )
        user = users.get(user_id)
        if not user:
            raise NotFoundException("User")
        if expected_updated_at is not None and user.updated_at != expected_updated_at:
            raise AppException(
                "This user changed. Review the current record before applying changes.",
                status_code=409,
                error_code="USER_STATE_CONFLICT",
            )
        return user
