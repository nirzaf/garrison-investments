import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import structlog
from anyio import move_on_after
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.business_log_stream import BusinessLogStream
from app.models.user import User
from app.schemas.audit import AuditLogResponse
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.utils.exceptions import AppException
from app.utils.permissions import PERMISSION_AUDIT_VIEW, ensure_permission
from app.utils.security import utc_now

logger = structlog.get_logger(__name__)
_MAX_DURATION = timedelta(minutes=15)
_MAX_STREAMS = 2
_PAGE_SIZE = 100
_BATCH_TIMEOUT = 2


@dataclass(frozen=True)
class BusinessStream:
    id: UUID
    actor_id: UUID
    role: str
    expires_at: datetime
    cursor: tuple[datetime, UUID] | None


async def _viewer(session: AsyncSession, token: str, *, lock: bool = False) -> User:
    user = await AuthService(session).get_user_from_access_token(
        token, require_session=True, for_update=lock
    )
    ensure_permission(user, PERMISSION_AUDIT_VIEW)
    return user


async def admit_business_log_stream(
    session: AsyncSession, token: str, request_id: str,
    last_event_id: UUID | None, created_from: datetime | None,
) -> tuple[User, BusinessStream]:
    # The user lock serializes admission across workers and access changes.
    user = await _viewer(session, token, lock=True)
    now = utc_now()
    cursor = None
    if last_event_id is not None:
        occurred_at = await session.scalar(
            select(ActivityLog.created_at).where(
                ActivityLog.id == last_event_id, ActivityLog.deleted_at.is_(None)
            )
        )
        if occurred_at is None or (created_from is not None and occurred_at < created_from):
            raise AppException(
                "The audit cursor is no longer available.",
                status_code=409, error_code="LOG_STREAM_CURSOR_UNAVAILABLE",
            )
        cursor = (occurred_at, last_event_id)
    count = await session.scalar(
        select(func.count()).select_from(BusinessLogStream).where(
            BusinessLogStream.user_id == user.id,
            BusinessLogStream.closed_at.is_(None),
            BusinessLogStream.expires_at > now,
        )
    )
    if count is not None and count >= _MAX_STREAMS:
        raise AppException(
            "Close an open audit stream before opening another.",
            status_code=429, error_code="LOG_STREAM_LIMIT",
        )
    stream = BusinessStream(uuid4(), user.id, user.role, now + _MAX_DURATION, cursor)
    session.add(BusinessLogStream(
        id=stream.id, user_id=user.id, request_id=request_id,
        opened_at=now, expires_at=stream.expires_at,
    ))
    return user, stream


async def release_business_log_stream(stream_id: UUID) -> None:
    with move_on_after(3, shield=True):
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(BusinessLogStream)
                    .where(BusinessLogStream.id == stream_id, BusinessLogStream.closed_at.is_(None))
                    .values(closed_at=utc_now())
                )
                await db.commit()
        except SQLAlchemyError:
            logger.warning("business_log_stream_close_unavailable")


async def _authorize(db: AsyncSession, token: str, stream: BusinessStream) -> None:
    viewer = await _viewer(db, token)
    if viewer.id != stream.actor_id or viewer.role != stream.role:
        raise AppException("The audit stream authorization changed.", status_code=403)


async def business_log_events(
    stream: BusinessStream, token: str, filters: dict[str, Any]
) -> AsyncIterator[str]:
    cursor = stream.cursor
    # Keep the full idle cycle under five seconds, including the auth and query timeout.
    poll_seconds = min(2.5, max(0.05, get_settings().log_stream_poll_seconds))
    while utc_now() < stream.expires_at:
        frames: list[str] = []
        try:
            async with asyncio.timeout(_BATCH_TIMEOUT):
                async with AsyncSessionLocal() as db:
                    await _authorize(db, token, stream)
                    logs, _ = await AuditService(db).list_logs(
                        **filters, limit=_PAGE_SIZE, ascending=True, after=cursor,
                        include_total=False,
                    )
                if logs:
                    for log in logs:
                        payload = AuditLogResponse.model_validate(log).model_dump(mode="json")
                        frames.append(f"id: {log.id}\ndata: {json.dumps(payload)}\n\n")
                    # A fresh session avoids an identity-map hit after the projection.
                    async with AsyncSessionLocal() as db:
                        await _authorize(db, token, stream)
        except AppException as error:
            reason = "authorization_ended" if error.status_code in (401, 403) else "unavailable"
            yield f": closed {reason}\n\n"
            return
        except (SQLAlchemyError, TimeoutError):
            yield ": closed unavailable\n\n"
            return
        if utc_now() >= stream.expires_at:
            break
        if logs:
            last = logs[-1]
            cursor = (last.created_at, last.id)
            yield "".join(frames)
        if len(logs) < _PAGE_SIZE:
            yield ": keep-alive\n\n"
            remaining = (stream.expires_at - utc_now()).total_seconds()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_seconds, remaining))
    yield ": closed time_limit\n\n"
