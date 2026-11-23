from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.services.auth_service import AuthService, RequestMeta
from app.utils.exceptions import AppException
from app.utils.permissions import ensure_permission
from app.utils.request import get_client_ip

DbSession = Annotated[AsyncSession, Depends(get_db)]
bearer_scheme = HTTPBearer(auto_error=False)


def get_request_meta(request: Request) -> RequestMeta:
    return RequestMeta(
        request_id=getattr(request.state, "request_id", None),
        session_id=getattr(request.state, "session_id", None),
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        endpoint=request.url.path,
        method=request.method,
    )


RequestMetadata = Annotated[RequestMeta, Depends(get_request_meta)]


async def get_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise AppException("Authentication required.", status_code=401, error_code="AUTH_REQUIRED")
    return credentials.credentials


BearerToken = Annotated[str, Depends(get_bearer_token)]


async def get_current_user(request: Request, session: DbSession, token: BearerToken) -> User:
    user = await AuthService(session).get_user_from_access_token(token)
    request.state.business_user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: str) -> Callable[[User], User]:
    def permission_dependency(current_user: CurrentUser) -> User:
        ensure_permission(current_user, permission)
        return current_user

    return permission_dependency
