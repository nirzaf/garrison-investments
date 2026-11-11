import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import DbSession, require_permission
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.user import User
from app.schemas.audit import AuditLogListResponse, AuditLogResponse
from app.services.audit_service import AuditService
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
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
    )


@router.get("/stream")
async def stream_log_events(
    current_user: CanViewLogs,
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
) -> StreamingResponse:
    async with AsyncSessionLocal() as session:
        await _record_log_access(
            session=session,
            current_user=current_user,
            request=request,
            action="logs.cli.stream" if _cli_session_id(request) else "logs.stream",
            context_payload={
                "filters": {
                    "event_type": event_type,
                    "severity": severity,
                    "action": action,
                    "entity_type": entity_type,
                    "user_id": str(user_id) if user_id else None,
                    "session_id": session_id,
                    "endpoint": endpoint,
                    "source_service": source_service,
                    "storage_tier": storage_tier,
                    "search": search,
                    "created_from": created_from.isoformat() if created_from else None,
                }
            },
        )

    async def event_stream() -> AsyncIterator[str]:
        poll_seconds = get_settings().log_stream_poll_seconds
        page_size = 100
        after: tuple[datetime, UUID] | None = None
        while True:
            if await request.is_disconnected():
                break
            async with AsyncSessionLocal() as session:
                logs, _ = await AuditService(session).list_logs(
                    event_type=event_type,
                    severity=severity,
                    action=action,
                    entity_type=entity_type,
                    user_id=user_id,
                    session_id=session_id,
                    endpoint=endpoint,
                    source_service=source_service,
                    storage_tier=storage_tier,
                    search=search,
                    created_from=created_from,
                    limit=page_size,
                    ascending=True,
                    after=after,
                    include_total=False,
                )
            for log in logs:
                after = (log.created_at, log.id)
                payload = AuditLogResponse.model_validate(log).model_dump(mode="json")
                yield f"data: {json.dumps(payload)}\n\n"
            if len(logs) == page_size:
                continue
            yield ": keep-alive\n\n"
            await asyncio.sleep(poll_seconds)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    await session.commit()


def _cli_session_id(request: Request) -> str | None:
    return request.headers.get("X-Log-CLI-Session")
