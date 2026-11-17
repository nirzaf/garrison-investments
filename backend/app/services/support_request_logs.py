"""Bounded evidence projection for the future case-authorized support portal."""

import re
from asyncio import timeout
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.utils.exceptions import AppException

REQUEST_ID_PATTERN = r"^(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$"
SUPPORT_REQUEST_ID = re.compile(REQUEST_ID_PATTERN)

RequestEvent = Literal["request", "handled_error", "unhandled_error"]
RequestMethod = Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_EVENTS: dict[str, RequestEvent] = {
    "http.request": "request",
    "http.app_exception": "handled_error",
    "http.unhandled_exception": "unhandled_error",
}
_METHODS: dict[str, RequestMethod] = {
    "GET": "GET",
    "HEAD": "HEAD",
    "POST": "POST",
    "PUT": "PUT",
    "PATCH": "PATCH",
    "DELETE": "DELETE",
    "OPTIONS": "OPTIONS",
}


class SupportRequestLogQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_window: ClassVar[timedelta] = timedelta(hours=24)

    request_id: str = Field(
        pattern=REQUEST_ID_PATTERN,
        max_length=36,
    )
    started_at: AwareDatetime
    ended_at: AwareDatetime
    limit: int = Field(default=25, ge=1, le=100)
    status_code: int | None = Field(default=None, ge=100, le=599)

    @model_validator(mode="after")
    def validate_window(self) -> "SupportRequestLogQuery":
        duration = self.ended_at - self.started_at
        if not timedelta(0) < duration <= self.max_window:
            hours = int(self.max_window.total_seconds() / 3600)
            raise ValueError(f"Select a positive window of at most {hours} hours.")
        return self


class SupportRequestEvent(BaseModel):
    id: UUID
    occurred_at: AwareDatetime
    kind: RequestEvent
    method: RequestMethod | None
    status_code: int | None = Field(ge=100, le=599)


class SupportRequestLogPage(BaseModel):
    request_id: str
    events: list[SupportRequestEvent]
    truncated: bool


class SupportRequestLogStreamQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=REQUEST_ID_PATTERN, max_length=36)
    hours: int = Field(default=1, ge=1, le=24)


async def resolve_request_log_cursor(
    session: AsyncSession, request_id: str, event_id: UUID
) -> tuple[datetime, UUID] | None:
    log = ActivityLog
    created_at = await session.scalar(
        select(log.created_at).where(
            log.id == event_id,
            log.request_id == request_id,
            log.action.in_(_EVENTS),
            log.entity_type == "request",
            log.deleted_at.is_(None),
        )
    )
    return (created_at, event_id) if created_at is not None else None


async def project_request_logs(
    session: AsyncSession,
    query: SupportRequestLogQuery,
    *,
    ascending: bool = False,
    after: tuple[datetime, UUID] | None = None,
) -> SupportRequestLogPage:
    """Project an exact request ID after the caller authorizes it for the case."""
    log = ActivityLog
    statement = select(log.id, log.created_at, log.action, log.http_method, log.status_code).where(
        log.request_id == query.request_id,
        log.created_at >= query.started_at,
        log.created_at < query.ended_at,
        log.action.in_(_EVENTS),
        log.entity_type == "request",
        log.deleted_at.is_(None),
    )
    if query.status_code is not None:
        statement = statement.where(log.status_code == query.status_code)
    if after is not None:
        statement = statement.where(tuple_(log.created_at, log.id) > tuple_(*after))
    order = (log.created_at, log.id) if ascending else (log.created_at.desc(), log.id.desc())
    statement = statement.order_by(*order).limit(query.limit + 1)
    try:
        async with timeout(5):
            rows = (await session.execute(statement)).all()
    except TimeoutError as exc:
        raise AppException(
            "Operational evidence is temporarily unavailable.",
            status_code=503,
            error_code="SUPPORT_LOG_TIMEOUT",
        ) from exc
    return SupportRequestLogPage(
        request_id=query.request_id,
        events=[
            SupportRequestEvent(
                id=event_id,
                occurred_at=created_at.astimezone(UTC),
                kind=_EVENTS[action],
                method=_METHODS.get(method or ""),
                status_code=status if status is not None and 100 <= status <= 599 else None,
            )
            for event_id, created_at, action, method, status in rows[: query.limit]
        ],
        truncated=len(rows) > query.limit,
    )
