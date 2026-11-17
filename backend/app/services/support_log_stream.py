import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import structlog
from anyio import move_on_after
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.database import AsyncSessionLocal
from app.models.support_cases import SupportLogStream
from app.services.support_case_logs import authorize_case_request_logs
from app.services.support_identity import support_session_deadline
from app.services.support_request_logs import (
    SupportRequestLogQuery,
    SupportRequestLogStreamQuery,
    project_request_logs,
    resolve_request_log_cursor,
)
from app.utils.exceptions import AppException
from app.utils.security import utc_now

logger = structlog.get_logger(__name__)
_MAX_DURATION = timedelta(minutes=15)
_MAX_WINDOW = timedelta(hours=24)
_POLL_SECONDS = 3
_BATCH_TIMEOUT_SECONDS = 2
_MAX_STREAMS = 2


@dataclass(frozen=True)
class CaseLogStream:
    id: UUID
    expires_at: datetime
    started_at: datetime
    cursor: tuple[datetime, UUID] | None


async def open_case_log_stream(
    token: str | None,
    case_id: UUID,
    query: SupportRequestLogStreamQuery,
    request_id: str,
    resume_after: UUID | None,
) -> CaseLogStream:
    async with AsyncSessionLocal() as db:
        active = await authorize_case_request_logs(
            db, token, case_id, query.request_id, require_stream=True
        )
        now = utc_now()
        started_at = now - timedelta(hours=query.hours)
        cursor = None
        if resume_after is not None:
            cursor = await resolve_request_log_cursor(db, query.request_id, resume_after)
            if cursor is None:
                raise AppException(
                    "The evidence cursor is unavailable. Start a new stream.",
                    status_code=409,
                    error_code="SUPPORT_STREAM_CURSOR_UNAVAILABLE",
                )
        # Authorization locks the operator before this count and insert.
        count = await db.scalar(
            select(func.count())
            .select_from(SupportLogStream)
            .where(
                SupportLogStream.operator_id == active.operator_id,
                SupportLogStream.closed_at.is_(None),
                SupportLogStream.expires_at > now,
            )
        )
        if count is not None and count >= _MAX_STREAMS:
            raise AppException(
                "Close an open support stream before opening another.",
                status_code=429,
                error_code="SUPPORT_STREAM_LIMIT",
            )
        if support_session_deadline(active) <= utc_now():
            raise AppException(
                "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
            )
        stream = CaseLogStream(
            id=uuid4(), expires_at=min(active.expires_at, now + _MAX_DURATION),
            started_at=started_at, cursor=cursor,
        )
        db.add(SupportLogStream(
            id=stream.id,
            operator_id=active.operator_id,
            session_id=active.id,
            case_id=case_id,
            request_id=request_id,
            source_request_id=query.request_id,
            started_at=started_at,
            opened_at=now,
            expires_at=stream.expires_at,
        ))
        # A stream never advances the interactive session's idle deadline.
        await db.commit()
        return stream


async def close_case_log_stream(stream_id: UUID) -> None:
    with move_on_after(3, shield=True):
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(SupportLogStream)
                    .where(SupportLogStream.id == stream_id, SupportLogStream.closed_at.is_(None))
                    .values(closed_at=utc_now())
                )
                await db.commit()
        except SQLAlchemyError:
            logger.warning("support_stream_close_unavailable")


def _closed(reason: str) -> str:
    return f"event: closed\ndata: {json.dumps({'reason': reason})}\n\n"


async def case_log_events(
    stream: CaseLogStream, token: str | None, case_id: UUID, source_request: str
) -> AsyncGenerator[str]:
    cursor = stream.cursor
    while utc_now() < stream.expires_at:
        try:
            async with asyncio.timeout(_BATCH_TIMEOUT_SECONDS), AsyncSessionLocal() as db:
                active = await authorize_case_request_logs(
                    db, token, case_id, source_request, require_stream=True
                )
                now = utc_now()
                query = SupportRequestLogQuery(
                    request_id=source_request,
                    started_at=max(stream.started_at, now - _MAX_WINDOW),
                    ended_at=now,
                )
                result = await project_request_logs(db, query, ascending=True, after=cursor)
                now = utc_now()
                if support_session_deadline(active) <= now:
                    yield_reason = "session_ended"
                elif stream.expires_at <= now:
                    yield_reason = "time_limit"
                else:
                    yield_reason = None
        except AppException as error:
            if error.status_code == 401:
                yield_reason = "session_ended"
            elif error.status_code in (403, 404):
                yield_reason = "access_ended"
            else:
                yield_reason = "unavailable"
        except (TimeoutError, SQLAlchemyError):
            yield_reason = "unavailable"
        else:
            if yield_reason is None:
                if result.events:
                    last = result.events[-1]
                    cursor = (last.occurred_at, last.id)
                    yield "".join(
                        f"id: {event.id}\ndata: {event.model_dump_json()}\n\n"
                        for event in result.events
                    )
                if result.truncated:
                    continue
                yield ": keep-alive\n\n"
                await asyncio.sleep(_POLL_SECONDS)
                continue
        yield _closed(yield_reason)
        return
    yield _closed("time_limit")
