from datetime import UTC, datetime
from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import BearerToken, DbSession, require_permission
from app.api.streaming import ManagedEventStream
from app.database import AsyncSessionLocal
from app.models.user import User
from app.schemas.audit import AuditLogListResponse, AuditLogResponse
from app.services.audit_service import AuditService
from app.services.business_log_stream import (
    admit_business_log_stream,
    business_log_events,
    release_business_log_stream,
)
from app.utils.permissions import PERMISSION_AUDIT_VIEW

router = APIRouter(prefix="/log-events", tags=["Log Events"])

CanViewLogs = Annotated[User, Depends(require_permission(PERMISSION_AUDIT_VIEW))]


@router.get("", response_model=AuditLogListResponse)
async def list_log_events(
    current_user: CanViewLogs,
    session: DbSession,
    request: Request,
    event_type: Annotated[str | None, Query(max_length=32)] = None,
    severity: Annotated[str | None, Query(max_length=16)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    user_id: Annotated[UUID | None, Query()] = None,
    session_id: Annotated[str | None, Query(max_length=128)] = None,
    request_id: Annotated[str | None, Query(max_length=64)] = None,
    ip_address: Annotated[str | None, Query(max_length=64)] = None,
    endpoint: Annotated[str | None, Query(max_length=255)] = None,
    source_service: Annotated[str | None, Query(max_length=64)] = None,
    storage_tier: Annotated[str | None, Query(max_length=16)] = None,
    status_code: Annotated[int | None, Query(ge=100, le=599)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditLogListResponse:
    audit = AuditService(session)
    logs, total = await audit.list_logs(
        event_type=event_type,
        severity=severity,
        action=action,
        entity_type=entity_type,
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
        ip_address=ip_address,
        endpoint=endpoint,
        source_service=source_service,
        storage_tier=storage_tier,
        status_code=status_code,
        search=search,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    await _record_log_access(
        session=session,
        current_user=current_user,
        request=request,
        action="logs.cli.query" if _cli_session_id(request) else "logs.query",
        context_payload={
            "filters": {
                "event_type": event_type,
                "severity": severity,
                "action": action,
                "entity_type": entity_type,
                "user_id": str(user_id) if user_id else None,
                "session_id": session_id,
                "request_id": request_id,
                "ip_address": ip_address,
                "endpoint": endpoint,
                "source_service": source_service,
                "storage_tier": storage_tier,
                "status_code": status_code,
                "search": search,
                "created_from": created_from.isoformat() if created_from else None,
                "created_to": created_to.isoformat() if created_to else None,
                "limit": limit,
                "offset": offset,
            }
        },
    )
    await session.commit()
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
    )


@router.get(
    "/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def stream_log_events(
    token: BearerToken,
    request: Request,
    event_type: Annotated[str | None, Query(max_length=32)] = None,
    severity: Annotated[str | None, Query(max_length=16)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    user_id: Annotated[UUID | None, Query()] = None,
    session_id: Annotated[str | None, Query(max_length=128)] = None,
    endpoint: Annotated[str | None, Query(max_length=255)] = None,
    source_service: Annotated[str | None, Query(max_length=64)] = None,
    storage_tier: Annotated[str | None, Query(max_length=16)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    last_event_id: Annotated[UUID | None, Header()] = None,
) -> StreamingResponse:
    if created_from is not None and created_from.tzinfo is None:
        created_from = created_from.replace(tzinfo=UTC)
    filters = {
        "event_type": event_type,
        "severity": severity,
        "action": action,
        "entity_type": entity_type,
        "user_id": user_id,
        "session_id": session_id,
        "endpoint": endpoint,
        "source_service": source_service,
        "storage_tier": storage_tier,
        "search": search,
        "created_from": created_from,
    }
    async with AsyncSessionLocal() as session:
        user, stream = await admit_business_log_stream(
            session, token, request.state.request_id, last_event_id, created_from
        )
        await _record_log_access(
            session=session,
            current_user=user,
            request=request,
            action="logs.cli.stream" if _cli_session_id(request) else "logs.stream",
            context_payload={
                "filters": {
                    **filters,
                    "user_id": str(user_id) if user_id else None,
                    "created_from": created_from.isoformat() if created_from else None,
                },
                "stream_id": str(stream.id),
                "last_event_id": str(last_event_id) if last_event_id else None,
            },
        )
        await session.commit()

    return ManagedEventStream(
        business_log_events(stream, token, filters),
        partial(release_business_log_stream, stream.id),
    )


async def _record_log_access(
    *,
    session,
    current_user: User,
    request: Request,
    action: str,
    context_payload: dict,
) -> None:
    await AuditService(session).record(
        action=action,
        event_type="log_access",
        severity="INFO",
        user_id=current_user.id,
        entity_type="log_events",
        comments=f"{request.method} {request.url.path}",
        context_payload={
            **context_payload,
            "cli_session_id": _cli_session_id(request),
        },
    )


def _cli_session_id(request: Request) -> str | None:
    return request.headers.get("X-Log-CLI-Session")
