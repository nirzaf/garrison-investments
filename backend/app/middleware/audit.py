from uuid import UUID

import structlog
from fastapi import Request, Response

from app.database import AsyncSessionLocal
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException
from app.utils.security import decode_access_token

logger = structlog.get_logger("app.middleware.audit")

_SKIPPED_PATHS = {"/health", "/health/readiness"}


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _authenticated_user_id(request: Request) -> UUID | None:
    authorization = request.headers.get("Authorization")
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None

    try:
        payload = decode_access_token(token)
    except AppException:
        return None

    subject = payload.get("sub")
    return UUID(subject) if subject else None


async def audit_authenticated_request(request: Request, response: Response) -> None:
    if request.url.path in _SKIPPED_PATHS or not request.url.path.startswith("/api/"):
        return

    user_id = _authenticated_user_id(request)
    if user_id is None:
        return

    try:
        async with AsyncSessionLocal() as session:
            await AuditService(session).record(
                action="http.request",
                user_id=user_id,
                entity_type="request",
                ip_address=_client_ip(request),
                user_agent=request.headers.get("User-Agent"),
                comments=f"{request.method} {request.url.path} -> {response.status_code}",
                new_values={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "request_id": getattr(request.state, "request_id", None),
                },
            )
            await session.commit()
    except Exception:
        logger.warning(
            "request_audit_failed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )