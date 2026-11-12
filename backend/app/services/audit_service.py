from datetime import datetime, timedelta
from typing import Any
from typing import cast as type_cast
from uuid import UUID

from sqlalchemy import CursorResult, Select, Text, cast, delete, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.models.activity_log import ActivityLog
from app.observability.context import get_log_context
from app.utils.redaction import redact_payload, redact_text
from app.utils.security import utc_now


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    async def record(
        self,
        *,
        action: str,
        event_type: str | None = None,
        severity: str | None = None,
        user_id: UUID | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        request_id: str | None = None,
        session_id: str | None = None,
        ip_address: str | None = None,
        endpoint: str | None = None,
        http_method: str | None = None,
        status_code: int | None = None,
        source_service: str | None = None,
        instance_id: str | None = None,
        user_agent: str | None = None,
        comments: str | None = None,
        context_payload: dict | None = None,
        old_values: dict | None = None,
        new_values: dict | None = None,
        retention_until: datetime | None = None,
        storage_tier: str = "hot",
        archived_at: datetime | None = None,
    ) -> None:
        context = get_log_context()
        resolved_user_id = user_id or self._context_user_id(context.user_id)
        resolved_retention = retention_until or (
            utc_now() + self._retention_delta(self.settings.log_archive_retention_days)
        )
        payload = dict(context_payload or {})
        payload.setdefault("request_id", request_id or context.request_id)
        payload.setdefault("session_id", session_id or context.session_id)
        payload.setdefault("endpoint", endpoint or context.endpoint)
        payload.setdefault("method", http_method or context.method)
        payload.setdefault("source_service", source_service or context.source_service)
        payload.setdefault("instance_id", instance_id or context.instance_id)
        payload.setdefault("cli_session_id", context.cli_session_id)
        payload = {key: value for key, value in payload.items() if value is not None}

        self.session.add(
            ActivityLog(
                user_id=resolved_user_id,
                event_type=event_type or self._infer_event_type(action, old_values, new_values),
                severity=(severity or self._infer_severity(action, status_code)).upper(),
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                request_id=request_id or context.request_id,
                session_id=session_id or context.session_id,
                ip_address=ip_address or context.ip_address,
                endpoint=endpoint or context.endpoint,
                http_method=http_method or context.method,
                status_code=status_code,
                source_service=(
                    source_service or context.source_service or self.settings.log_source_service
                ),
                instance_id=instance_id or context.instance_id or self.settings.log_instance_id,
                storage_tier=storage_tier,
                archived_at=archived_at,
                retention_until=resolved_retention,
                user_agent=user_agent,
                comments=redact_text(comments) if comments else comments,
                context_payload=redact_payload(payload) or None,
                old_values=redact_payload(old_values),
                new_values=redact_payload(new_values),
            )
        )

    async def list_logs(
        self,
        *,
        event_type: str | None = None,
        severity: str | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        user_id: UUID | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        endpoint: str | None = None,
        source_service: str | None = None,
        storage_tier: str | None = None,
        status_code: int | None = None,
        search: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
        ascending: bool = False,
        after: tuple[datetime, UUID] | None = None,
        include_total: bool = True,
    ) -> tuple[list[ActivityLog], int]:
        filters: list[ColumnElement[bool]] = [ActivityLog.deleted_at.is_(None)]
        if event_type:
            filters.append(ActivityLog.event_type == event_type)
        if severity:
            filters.append(ActivityLog.severity == severity.upper())
        if action:
            filters.append(ActivityLog.action == action)
        if entity_type:
            filters.append(ActivityLog.entity_type == entity_type)
        if user_id:
            filters.append(ActivityLog.user_id == user_id)
        if session_id:
            filters.append(ActivityLog.session_id == session_id)
        if request_id:
            filters.append(ActivityLog.request_id == request_id)
        if ip_address:
            filters.append(ActivityLog.ip_address == ip_address)
        if endpoint:
            filters.append(ActivityLog.endpoint.ilike(f"%{endpoint.strip()}%"))
        if source_service:
            filters.append(ActivityLog.source_service == source_service)
        if storage_tier and storage_tier != "all":
            filters.append(ActivityLog.storage_tier == storage_tier)
        if status_code is not None:
            filters.append(ActivityLog.status_code == status_code)
        if created_from:
            filters.append(ActivityLog.created_at >= created_from)
        if created_to:
            filters.append(ActivityLog.created_at <= created_to)
        if after is not None:
            cursor = tuple_(ActivityLog.created_at, ActivityLog.id)
            filters.append(cursor > tuple_(*after) if ascending else cursor < tuple_(*after))
        if search:
            normalized_search = search.strip()
            pattern = f"%{normalized_search}%"
            search_document = func.concat_ws(
                " ",
                ActivityLog.event_type,
                ActivityLog.severity,
                ActivityLog.action,
                ActivityLog.entity_type,
                ActivityLog.endpoint,
                ActivityLog.comments,
                cast(ActivityLog.context_payload, Text),
                cast(ActivityLog.old_values, Text),
                cast(ActivityLog.new_values, Text),
            )
            filters.append(
                or_(
                    func.to_tsvector("simple", search_document).op("@@")(
                        func.plainto_tsquery("simple", normalized_search)
                    ),
                    search_document.ilike(pattern),
                )
            )

        query: Select[ActivityLog] = (
            select(ActivityLog)
            .where(*filters)
            .order_by(
                ActivityLog.created_at.asc() if ascending else ActivityLog.created_at.desc(),
                ActivityLog.id.asc() if ascending else ActivityLog.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        logs = list((await self.session.scalars(query)).all())
        if not include_total:
            return logs, 0
        total_query = select(func.count()).select_from(ActivityLog).where(*filters)
        total = int(await self.session.scalar(total_query) or 0)
        return logs, total

    async def archive_logs(self, *, hot_retention_days: int | None = None) -> int:
        cutoff_at = utc_now()
        hot_cutoff = cutoff_at - self._retention_delta(
            hot_retention_days or self.settings.log_hot_retention_days
        )
        result = await self.session.execute(
            update(ActivityLog)
            .where(
                ActivityLog.deleted_at.is_(None),
                ActivityLog.storage_tier == "hot",
                ActivityLog.created_at < hot_cutoff,
            )
            .values(storage_tier="archive", archived_at=cutoff_at)
            .execution_options(synchronize_session=False)
        )
        return int(type_cast(CursorResult[Any], result).rowcount or 0)

    def _purge_candidates(self, archive_retention_days: int | None) -> Select:
        now = utc_now()
        purge_cutoff = now - self._retention_delta(
            archive_retention_days or self.settings.log_archive_retention_days
        )
        return (
            select(ActivityLog.id, ActivityLog.retention_until)
            .where(
                ActivityLog.storage_tier == "archive",
                ActivityLog.deleted_at.is_(None),
                ActivityLog.retention_until <= now,
                func.coalesce(ActivityLog.archived_at, ActivityLog.created_at) < purge_cutoff,
            )
            .order_by(ActivityLog.retention_until, ActivityLog.id)
            .limit(1000)
        )

    async def preview_purge(
        self, *, archive_retention_days: int | None = None
    ) -> list[tuple[UUID, datetime]]:
        rows = await self.session.execute(self._purge_candidates(archive_retention_days))
        return [(row.id, row.retention_until) for row in rows]

    async def purge_logs(self, *, archive_retention_days: int | None = None) -> int:
        if not self.settings.log_purge_enabled:
            return 0
        candidates = (
            self._purge_candidates(archive_retention_days)
            .with_only_columns(ActivityLog.id)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(
            delete(ActivityLog).where(ActivityLog.id.in_(candidates))
        )
        return int(type_cast(CursorResult[Any], result).rowcount or 0)

    def _infer_event_type(
        self,
        action: str,
        old_values: dict | None,
        new_values: dict | None,
    ) -> str:
        if action.startswith("http."):
            return "api_request"
        if action.startswith("auth."):
            return "security_event"
        if action.startswith("logs."):
            return "log_access"
        if (
            action.startswith("system.")
            or action.startswith("celery.")
            or action.startswith("maintenance.")
        ):
            return "system_event"
        if old_values is not None or new_values is not None:
            return "state_change"
        return "user_action"

    def _infer_severity(self, action: str, status_code: int | None) -> str:
        lowered = action.lower()
        if status_code is not None:
            if status_code >= 500:
                return "ERROR"
            if status_code >= 400:
                return "WARNING"
        if any(token in lowered for token in {"error", "failed", "exception"}):
            return "ERROR"
        if any(token in lowered for token in {"rejected", "denied", "locked", "late"}):
            return "WARNING"
        return "INFO"

    @staticmethod
    def _retention_delta(days: int) -> timedelta:
        return timedelta(days=days)

    @staticmethod
    def _context_user_id(user_id: str | None) -> UUID | None:
        if not user_id:
            return None
        try:
            return UUID(user_id)
        except ValueError:
            return None
