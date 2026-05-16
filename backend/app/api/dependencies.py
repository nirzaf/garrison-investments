from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.services.auth_service import AuthService, RequestMeta
from app.utils.permissions import ensure_permission

DbSession = Annotated[AsyncSession, Depends(get_db)]
bearer_scheme = HTTPBearer(auto_error=False)


def get_request_meta(request: Request) -> RequestMeta:
    forwarded_for = request.headers.get("X-Forwarded-For")
    ip_address = forwarded_for.split(",")[0].strip() if forwarded_for else None
    if not ip_address and request.client:
        ip_address = request.client.host
    return RequestMeta(
        ip_address=ip_address,
        user_agent=request.headers.get("User-Agent"),
    )


RequestMetadata = Annotated[RequestMeta, Depends(get_request_meta)]


async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    from app.utils.exceptions import AppException

    if not credentials or credentials.scheme.lower() != "bearer":
        raise AppException("Authentication required.", status_code=401, error_code="AUTH_REQUIRED")
    return await AuthService(session).get_user_from_access_token(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: str) -> Callable[[User], User]:
    def permission_dependency(current_user: CurrentUser) -> User:
        ensure_permission(current_user, permission)
        return current_user

    return permission_dependency
