from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime, EmailStr

from app.api.dependencies import DbSession, require_permission
from app.models.user import User
from app.schemas.users import (
    AdminPasswordResetRequest,
    UserCreateRequest,
    UserDetailResponse,
    UserListResponse,
    UserResponse,
    UserRoleListResponse,
    UserRoleResponse,
    UserUpdateRequest,
)
from app.services.user_service import UserService
from app.utils.permissions import (
    PERMISSION_USERS_MANAGE,
    PERMISSION_USERS_READ,
    ROLE_LABELS,
    VALID_ROLES,
    can_assign_user_role,
    permissions_for_role,
)

router = APIRouter(prefix="/users", tags=["Users"])

CanReadUsers = Annotated[User, Depends(require_permission(PERMISSION_USERS_READ))]
CanManageUsers = Annotated[User, Depends(require_permission(PERMISSION_USERS_MANAGE))]


@router.get("", response_model=UserListResponse)
async def list_users(
    _: CanReadUsers,
    session: DbSession,
    active: Annotated[bool | None, Query()] = None,
    role: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    email: Annotated[EmailStr | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserListResponse:
    users, total = await UserService(session).list_users(
        active=active,
        role=role,
        search=search,
        email=email,
        limit=limit,
        offset=offset,
    )
    return UserListResponse(
        items=[UserResponse.model_validate(user) for user in users],
        total=total,
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateRequest,
    current_user: CanManageUsers,
    session: DbSession,
) -> UserResponse:
    user = await UserService(session).create_user(payload, current_user)
    return UserResponse.model_validate(user)


@router.get("/roles", response_model=UserRoleListResponse)
async def list_user_roles(current_user: CanReadUsers) -> UserRoleListResponse:
    return UserRoleListResponse(
        items=[
            UserRoleResponse(
                role=role,
                label=ROLE_LABELS[role],
                permissions=permissions_for_role(role),
                assignable=can_assign_user_role(current_user.role, role),
            )
            for role in sorted(VALID_ROLES)
        ]
    )


@router.get("/{user_id}", response_model=UserDetailResponse)
async def get_user(user_id: UUID, _: CanReadUsers, session: DbSession) -> UserDetailResponse:
    user = await UserService(session).get_user(user_id)
    return UserDetailResponse(
        **UserResponse.model_validate(user).model_dump(),
        permissions=permissions_for_role(user.role),
    )


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdateRequest,
    current_user: CanManageUsers,
    session: DbSession,
) -> UserResponse:
    user = await UserService(session).update_user(user_id, payload, current_user)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", response_model=UserResponse)
async def deactivate_user(
    user_id: UUID,
    current_user: CanManageUsers,
    session: DbSession,
    expected_updated_at: Annotated[AwareDatetime | None, Query()] = None,
) -> UserResponse:
    user = await UserService(session).deactivate_user(
        user_id, current_user, expected_updated_at=expected_updated_at
    )
    return UserResponse.model_validate(user)


@router.post("/{user_id}/reset-password", response_model=UserResponse)
async def admin_reset_password(
    user_id: UUID,
    payload: AdminPasswordResetRequest,
    current_user: CanManageUsers,
    session: DbSession,
) -> UserResponse:
    user = await UserService(session).admin_reset_password(user_id, payload, current_user)
    return UserResponse.model_validate(user)
