"""Read-only operational monitoring projections for the dedicated support portal."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import redis.asyncio as redis
from cryptography import x509
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.activity_log import ActivityLog
from app.models.support_business_actions import SupportBusinessAction, SupportRecoveryDelivery
from app.models.support_cases import SupportCaseRequest
from app.models.support_custody import SupportCustodyAction
from app.models.support_identity import SupportAuthEvent, SupportSession
from app.models.support_oversight import SupportBackupReceipt
from app.models.task_outbox import TaskOutbox
from app.schemas.support_oversight import (
    FreshnessState,
    OversightMetric,
    OversightScope,
    SourceStatus,
    SupportBackupReceiptSummary,
    SupportBackupsMonitorRead,
    SupportConfigStatusRead,
    SupportIncidentsQuery,
    SupportIncidentsSummaryRead,
    SupportJobEventSummary,
    SupportJobScheduleItem,
    SupportJobsMonitorRead,
    SupportJobsQuery,
)
from app.services.support_overview import execute_oversight_read
from app.tasks.celery_app import celery_app
from app.tasks.outbox import STALE_DISPATCH_TIMEOUT
from app.tasks.worker_heartbeat import read_worker_heartbeats

_BEAT_TASK_ALLOWLIST: dict[str, str] = {
    "dispatch_task_outbox": "maintenance",
    "run_database_backup": "backup",
    "check_late_reports": "maintenance",
    "process_approval_reminders": "maintenance",
    "check_low_stock": "maintenance",
    "cleanup_old_notifications": "maintenance",
    "archive_and_purge_logs": "maintenance",
    "check_supplier_tds_expiry": "maintenance",
    "check_hr_credential_expiry": "maintenance",
    "check_hr_service_request_sla": "maintenance",
    "check_hr_probation_reviews": "maintenance",
    "post_hr_leave_accruals": "maintenance",
    "dispatch_support_recovery_deliveries": "email",
}

_TASK_QUEUE_ALLOWLIST: dict[str, str] = {
    **_BEAT_TASK_ALLOWLIST,
    "run_import_async": "maintenance",
    "generate_report_pdf": "report",
    "generate_excel_export": "report",
    "generate_management_export": "report",
    "send_email_notification": "email",
    "send_report_email": "email",
    "generate_thumbnail": "image",
    "compress_photo": "image",
}

_HISTORY_COVERAGE_NOTE = (
    "Recent lifecycle events reflect persisted task failures and recorded activity_log "
    "entries only; absence of events does not prove complete broker execution history."
)

_JOB_ACTION_MAP: dict[str, str] = {
    "celery.task_started": "started",
    "celery.task_succeeded": "succeeded",
    "celery.task_failed": "failed",
    "celery.task_retried": "retried",
    "task_started": "started",
    "task_succeeded": "succeeded",
    "task_failed": "failed",
    "task_retried": "retried",
}

_BACKUP_SET_MAX_AGE = timedelta(hours=48)
_RESTORE_DRILL_MAX_AGE = timedelta(days=30)
_GIT_SHA_RE = re.compile(r"^[a-f0-9]{40}$")
_TLS_CERT_CANDIDATE = Path("/etc/nginx/ssl/support-fullchain.pem")


async def _ping_broker(settings: Settings) -> str:
    try:
        async with asyncio.timeout(1.5):
            async with redis.from_url(
                settings.redis_url, socket_connect_timeout=1, socket_timeout=1
            ) as conn:
                return "operational" if await conn.ping() else "unavailable"
    except TimeoutError:
        return "unknown"
    except Exception:
        return "unavailable"


def _format_schedule(schedule: object) -> str:
    if isinstance(schedule, (int, float)):
        return f"every {int(schedule)}s"
    return str(schedule)


def _normalize_queue(queue_filter: str | None) -> str | None:
    if queue_filter == "reports":
        return "report"
    if queue_filter == "images":
        return "image"
    return queue_filter


def _schedule_items(queue_filter: str | None) -> list[SupportJobScheduleItem]:
    normalized = _normalize_queue(queue_filter)
    beat = celery_app.conf.beat_schedule or {}
    items: list[SupportJobScheduleItem] = []
    active_by_task = {entry.get("task"): (name, entry) for name, entry in beat.items()}
    for task_name, queue in sorted(_BEAT_TASK_ALLOWLIST.items()):
        if normalized is not None and queue != normalized:
            continue
        if task_name in active_by_task:
            job_name, entry = active_by_task[task_name]
            items.append(
                SupportJobScheduleItem(
                    job_name=str(job_name),
                    task_name=task_name,
                    queue=queue,
                    state="scheduled",
                    schedule_summary=_format_schedule(entry.get("schedule", "configured")),
                )
            )
        else:
            items.append(
                SupportJobScheduleItem(
                    job_name=task_name,
                    task_name=task_name,
                    queue=queue,
                    state="disabled_by_policy",
                    schedule_summary="policy-gated (inactive)",
                )
            )
    return items


async def read_jobs_monitor(
    session: AsyncSession, token: str | None, query: SupportJobsQuery, request_id: str
) -> SupportJobsMonitorRead:
    settings = get_settings()
    normalized_queue = _normalize_queue(query.queue)

    async def run(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportJobsMonitorRead:
        broker = await _ping_broker(settings)
        worker_status, worker_age, _ = await read_worker_heartbeats(settings, now)
        cutoff = now - timedelta(hours=query.hours)
        stale_dispatch_cutoff = now - STALE_DISPATCH_TIMEOUT
        allowed_tasks = [
            task
            for task, q in _TASK_QUEUE_ALLOWLIST.items()
            if normalized_queue is None or q == normalized_queue
        ]

        outbox_pending = int(
            await db.scalar(
                select(func.count()).select_from(TaskOutbox).where(TaskOutbox.status == "pending")
            )
            or 0
        )
        outbox_dispatched = int(
            await db.scalar(
                select(func.count())
                .select_from(TaskOutbox)
                .where(TaskOutbox.status == "dispatched")
            )
            or 0
        )
        outbox_stale_dispatched = int(
            await db.scalar(
                select(func.count())
                .select_from(TaskOutbox)
                .where(
                    TaskOutbox.status == "dispatched",
                    TaskOutbox.dispatched_at.is_not(None),
                    TaskOutbox.dispatched_at < stale_dispatch_cutoff,
                )
            )
            or 0
        )
        outbox_failed = int(
            await db.scalar(
                select(func.count()).select_from(TaskOutbox).where(TaskOutbox.status == "failed")
            )
            or 0
        )
        oldest_pending = await db.scalar(
            select(func.min(TaskOutbox.created_at)).where(TaskOutbox.status == "pending")
        )
        oldest_age = (
            max(0, int((now - oldest_pending).total_seconds()))
            if oldest_pending is not None
            else None
        )
        rec_pending = int(
            await db.scalar(
                select(func.count())
                .select_from(SupportRecoveryDelivery)
                .where(SupportRecoveryDelivery.status == "pending")
            )
            or 0
        )
        rec_dispatching = int(
            await db.scalar(
                select(func.count())
                .select_from(SupportRecoveryDelivery)
                .where(SupportRecoveryDelivery.status == "dispatching")
            )
            or 0
        )
        rec_unknown = int(
            await db.scalar(
                select(func.count())
                .select_from(SupportRecoveryDelivery)
                .where(SupportRecoveryDelivery.status == "unknown")
            )
            or 0
        )

        recent_events: list[SupportJobEventSummary] = []
        truncated = False
        if allowed_tasks:
            task_expr = ActivityLog.context_payload["task_name"].astext
            rows = (
                await db.execute(
                    select(
                        ActivityLog.id,
                        ActivityLog.action,
                        ActivityLog.created_at,
                        task_expr.label("task_name"),
                    )
                    .where(
                        ActivityLog.deleted_at.is_(None),
                        ActivityLog.created_at >= cutoff,
                        ActivityLog.action.in_(tuple(_JOB_ACTION_MAP)),
                        task_expr.in_(allowed_tasks),
                    )
                    .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
                    .limit(query.limit + 1)
                )
            ).all()
            truncated = len(rows) > query.limit
            for row in rows[: query.limit]:
                mapped_state = _JOB_ACTION_MAP.get(row.action)
                if mapped_state is None or row.task_name not in _TASK_QUEUE_ALLOWLIST:
                    continue
                recent_events.append(
                    SupportJobEventSummary(
                        event_id=row.id,
                        task_name=row.task_name,
                        event=mapped_state,  # type: ignore[arg-type]
                        occurred_at=row.created_at,
                    )
                )
        if broker != "operational":
            source_status: SourceStatus = "degraded"
            freshness: FreshnessState = "unknown"
        elif (
            worker_status == "unavailable"
            or outbox_failed > 0
            or outbox_stale_dispatched > 0
            or rec_unknown > 0
        ):
            source_status = "degraded"
            freshness = (
                "stale"
                if (outbox_stale_dispatched > 0 or worker_status == "unavailable")
                else "current"
            )
        elif worker_status == "unknown":
            source_status = "partial"
            freshness = "unknown"
        else:
            source_status = "operational"
            freshness = "current"
        return SupportJobsMonitorRead(
            observed_at=now,
            window_hours=query.hours,
            broker_status=broker,  # type: ignore[arg-type]
            worker_status=worker_status,  # type: ignore[arg-type]
            worker_heartbeat_age_seconds=worker_age,
            source_status=source_status,
            freshness=freshness,
            history_coverage=_HISTORY_COVERAGE_NOTE,
            outbox_pending=outbox_pending,
            outbox_dispatched=outbox_dispatched,
            outbox_stale_dispatched=outbox_stale_dispatched,
            outbox_failed=outbox_failed,
            outbox_oldest_age_seconds=oldest_age,
            recovery_pending=rec_pending,
            recovery_dispatching=rec_dispatching,
            recovery_unknown=rec_unknown,
            schedules=_schedule_items(normalized_queue),
            recent_events=recent_events,
            truncated=truncated,
        )

    def degraded(now: datetime) -> SupportJobsMonitorRead:
        return SupportJobsMonitorRead(
            observed_at=now,
            window_hours=query.hours,
            broker_status="unknown",
            worker_status="unknown",
            worker_heartbeat_age_seconds=None,
            source_status="unavailable",
            freshness="unknown",
            history_coverage=_HISTORY_COVERAGE_NOTE,
            outbox_pending=None,
            outbox_dispatched=None,
            outbox_stale_dispatched=None,
            outbox_failed=None,
            outbox_oldest_age_seconds=None,
            recovery_pending=None,
            recovery_dispatching=None,
            recovery_unknown=None,
            schedules=_schedule_items(normalized_queue),
            recent_events=[],
            truncated=False,
        )

    return await execute_oversight_read(
        session,
        token,
        capability="jobs.read",
        surface="jobs",
        request_id=request_id,
        query_fn=run,
        degraded_fn=degraded,
    )


async def read_backups_monitor(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportBackupsMonitorRead:
    escalation_ref = "docs/OPERATIONS_AND_DEPLOYMENT.md#3-operations-backup--restore"

    async def run(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportBackupsMonitorRead:
        rows = list(
            await db.scalars(
                select(SupportBackupReceipt)
                .order_by(SupportBackupReceipt.captured_at.desc(), SupportBackupReceipt.id.desc())
                .limit(20)
            )
        )
        # Note any scheduled DB backup task failure separately from verified receipts.
        latest_db_receipt = next(
            (r for r in rows if r.receipt_kind == "scheduled_db_attempt"), None
        )
        latest_set_receipt = next(
            (r for r in rows if r.receipt_kind == "authenticated_backup_set"), None
        )
        latest_restore = next((r for r in rows if r.receipt_kind == "restore_drill"), None)

        db_status = "unverified"
        if latest_db_receipt is not None:
            if latest_db_receipt.outcome == "fail":
                db_status = "failed"
            elif latest_db_receipt.outcome == "pass" and latest_db_receipt.covers_database:
                age = now - latest_db_receipt.captured_at
                db_status = "current" if age <= _BACKUP_SET_MAX_AGE else "stale"

        set_status = "unverified"
        if latest_set_receipt is not None:
            if latest_set_receipt.outcome == "fail":
                set_status = "failed"
            elif (
                latest_set_receipt.outcome == "pass"
                and latest_set_receipt.target_domain == "independent_offhost"
                and latest_set_receipt.covers_database
                and latest_set_receipt.covers_objects
                and bool(latest_set_receipt.manifest_sha256)
            ):
                set_status = (
                    "verified"
                    if now - latest_set_receipt.captured_at <= _BACKUP_SET_MAX_AGE
                    else "stale"
                )

        restore_status = "unverified"
        if latest_restore is not None:
            drill_time = latest_restore.verified_at or latest_restore.captured_at
            if latest_restore.outcome == "fail":
                restore_status = "failed"
            elif (
                latest_restore.outcome == "pass"
                and latest_restore.target_domain == "isolated_restore"
                and latest_restore.verified_at is not None
            ):
                restore_status = (
                    "verified" if now - drill_time <= _RESTORE_DRILL_MAX_AGE else "stale"
                )

        if set_status == "verified" and restore_status == "verified":
            overall = "complete_verified"
            source_status: SourceStatus = "operational"
        elif "stale" in {db_status, set_status, restore_status} and "failed" not in {
            db_status,
            set_status,
            restore_status,
        }:
            overall = "stale"
            source_status = "degraded"
        elif db_status == "current":
            overall = "partial_db_only"
            source_status = "partial"
        else:
            overall = "unverified"
            source_status = "unverified"

        receipts = [
            SupportBackupReceiptSummary(
                receipt_id=r.id,
                receipt_kind=r.receipt_kind,  # type: ignore[arg-type]
                target_domain=r.target_domain,  # type: ignore[arg-type]
                backup_set_id=r.backup_set_id,
                manifest_digest_prefix=r.manifest_sha256[:12] if r.manifest_sha256 else None,
                covers_database=r.covers_database,
                covers_objects=r.covers_objects,
                outcome=r.outcome,  # type: ignore[arg-type]
                rpo_minutes=r.rpo_minutes,
                rto_minutes=r.rto_minutes,
                captured_at=r.captured_at,
                verified_at=r.verified_at,
                signer_key_id=r.signer_key_id,
            )
            for r in rows
        ]
        return SupportBackupsMonitorRead(
            observed_at=now,
            source_status=source_status,
            overall_recovery_posture=overall,  # type: ignore[arg-type]
            database_backup_status=db_status,  # type: ignore[arg-type]
            authenticated_backup_set_status=set_status,  # type: ignore[arg-type]
            isolated_restore_status=restore_status,  # type: ignore[arg-type]
            escalation_reference=escalation_ref,
            latest_scheduled_db_task_at=latest_db_receipt.captured_at
            if latest_db_receipt is not None
            else None,
            receipts=receipts,
        )

    def degraded(now: datetime) -> SupportBackupsMonitorRead:
        return SupportBackupsMonitorRead(
            observed_at=now,
            source_status="unavailable",
            overall_recovery_posture="unverified",
            database_backup_status="unverified",
            authenticated_backup_set_status="unverified",
            isolated_restore_status="unverified",
            escalation_reference=escalation_ref,
            latest_scheduled_db_task_at=None,
            receipts=[],
        )

    return await execute_oversight_read(
        session,
        token,
        capability="backups.read",
        surface="backups",
        request_id=request_id,
        query_fn=run,
        degraded_fn=degraded,
    )


def _read_public_tls_status(now: datetime) -> tuple[str, datetime | None]:
    """Read only public leaf certificate dates if mounted; never inspect private keys."""
    cert_path_raw = os.environ.get("SUPPORT_TLS_CERT_PATH", "").strip()
    path = Path(cert_path_raw) if cert_path_raw else _TLS_CERT_CANDIDATE
    try:
        if not path.is_file() or path.is_symlink():
            return "unknown", None
        cert = x509.load_pem_x509_certificate(path.read_bytes())
        not_after = cert.not_valid_after_utc
        not_before = cert.not_valid_before_utc
        if now < not_before or now >= not_after:
            return "expired", not_after
        if not_after - now <= timedelta(days=30):
            return "expiring_soon", not_after
        return "valid", not_after
    except Exception:
        return "unknown", None


async def read_config_status(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportConfigStatusRead:
    settings = get_settings()

    async def run(
        _db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportConfigStatusRead:
        raw_sha = os.environ.get("APP_COMMIT_SHA", "").strip().lower()
        source_sha = raw_sha if _GIT_SHA_RE.fullmatch(raw_sha) else "unknown"
        otp_key = (
            settings.support_email_otp_key.get_secret_value().strip()
            if settings.support_email_otp_key is not None
            else ""
        )
        otp_configured = (
            len(otp_key.encode("utf-8")) >= 32 and len(settings.support_email_otp_recipients) >= 2
        )
        mail_configured = bool(
            settings.smtp_host.strip()
            or (settings.usesend_api_url is not None and settings.usesend_api_key is not None)
            or (
                settings.cloudflare_email_account_id
                and settings.cloudflare_email_api_token is not None
            )
        )
        hr_key_ok = (
            settings.hr_encryption_key is not None
            and len(settings.hr_encryption_key.get_secret_value().strip()) >= 32
        )
        backup_key_ok = bool((settings.backup_encryption_password or "").strip())
        tls_status, tls_not_after = _read_public_tls_status(now)
        return SupportConfigStatusRead(
            observed_at=now,
            source_status="operational",
            app_env=settings.app_env.strip().lower() or "unknown",
            source_sha=source_sha,
            business_currency=settings.business_currency,
            business_timezone=settings.business_timezone,
            audit_purge_disabled=not settings.log_purge_enabled,
            mail_configured=mail_configured,
            support_portal_enabled=settings.support_portal_enabled,
            support_recovery_delivery_enabled=settings.support_recovery_delivery_enabled,
            support_email_otp_configured=otp_configured,
            support_otp_recipient_count=len(settings.support_email_otp_recipients),
            hr_encryption_configured=hr_key_ok,
            backup_encryption_configured=backup_key_ok,
            scheduler_jobs_configured=len(celery_app.conf.beat_schedule or {}),
            tls_status=tls_status,  # type: ignore[arg-type]
            tls_not_after=tls_not_after,
            change_control_reference="docs/OPERATIONS_AND_DEPLOYMENT.md#production-maintenance",
        )

    def degraded(now: datetime) -> SupportConfigStatusRead:
        return SupportConfigStatusRead(
            observed_at=now,
            source_status="unavailable",
            app_env="unknown",
            source_sha="unknown",
            business_currency="unknown",
            business_timezone="unknown",
            audit_purge_disabled=True,
            mail_configured=False,
            support_portal_enabled=False,
            support_recovery_delivery_enabled=False,
            support_email_otp_configured=False,
            support_otp_recipient_count=0,
            hr_encryption_configured=False,
            backup_encryption_configured=False,
            scheduler_jobs_configured=0,
            tls_status="unknown",
            tls_not_after=None,
            change_control_reference="docs/OPERATIONS_AND_DEPLOYMENT.md#production-maintenance",
        )

    return await execute_oversight_read(
        session,
        token,
        capability="config.read",
        surface="config",
        request_id=request_id,
        query_fn=run,
        degraded_fn=degraded,
    )


async def read_incidents_summary(
    session: AsyncSession, token: str | None, query: SupportIncidentsQuery, request_id: str
) -> SupportIncidentsSummaryRead:
    scope = (
        OversightScope(kind="case_scope", case_id=query.case_id)
        if query.case_id is not None
        else OversightScope(kind="approved_company_aggregate")
    )

    async def run(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportIncidentsSummaryRead:
        cutoff = now - timedelta(hours=query.hours)
        support_auth_failed = int(
            await db.scalar(
                select(func.count())
                .select_from(SupportAuthEvent)
                .where(
                    SupportAuthEvent.occurred_at >= cutoff,
                    SupportAuthEvent.action == "login_denied",
                )
            )
            or 0
        )
        sessions_revoked = int(
            await db.scalar(
                select(func.count())
                .select_from(SupportSession)
                .where(SupportSession.revoked_at.is_not(None), SupportSession.revoked_at >= cutoff)
            )
            or 0
        )
        pending_custody = int(
            await db.scalar(
                select(func.count())
                .select_from(SupportCustodyAction)
                .where(
                    SupportCustodyAction.executed_at.is_(None),
                    SupportCustodyAction.expires_at > now,
                )
            )
            or 0
        )
        action_filters = [
            SupportBusinessAction.applied_at.is_(None),
            SupportBusinessAction.expires_at > now,
        ]
        if query.case_id is not None:
            action_filters.append(SupportBusinessAction.case_id == query.case_id)
        pending_business_actions = int(
            await db.scalar(
                select(func.count()).select_from(SupportBusinessAction).where(*action_filters)
            )
            or 0
        )
        business_auth_failures = int(
            await db.scalar(
                select(func.count())
                .select_from(ActivityLog)
                .where(
                    ActivityLog.deleted_at.is_(None),
                    ActivityLog.created_at >= cutoff,
                    ActivityLog.action == "auth.login_failed",
                )
            )
            or 0
        )
        http_5xx = int(
            await db.scalar(
                select(func.count())
                .select_from(ActivityLog)
                .where(
                    ActivityLog.deleted_at.is_(None),
                    ActivityLog.created_at >= cutoff,
                    ActivityLog.status_code >= 500,
                )
            )
            or 0
        )
        metrics = [
            OversightMetric(
                key="support_auth_failures",
                label="Support authentication failures",
                value=support_auth_failed,
                state="observed",
                source="support_auth_events",
            ),
            OversightMetric(
                key="support_sessions_revoked",
                label="Revoked technical sessions",
                value=sessions_revoked,
                state="observed",
                source="support_sessions",
            ),
            OversightMetric(
                key="pending_custody_decisions",
                label="Pending custody actions",
                value=pending_custody,
                state="observed",
                source="support_custody_actions",
            ),
            OversightMetric(
                key="pending_account_interventions",
                label="Pending reviewed account actions",
                value=pending_business_actions,
                state="observed",
                source="support_business_actions",
            ),
            OversightMetric(
                key="business_login_failures",
                label="Business portal sign-in failures",
                value=business_auth_failures,
                state="observed",
                source="activity_log",
            ),
            OversightMetric(
                key="http_5xx_events",
                label="HTTP 5xx error events",
                value=http_5xx,
                state="observed",
                source="activity_log",
            ),
        ]
        if query.case_id is not None:
            case_errors = int(
                await db.scalar(
                    select(func.count())
                    .select_from(ActivityLog)
                    .join(
                        SupportCaseRequest,
                        SupportCaseRequest.request_id == ActivityLog.request_id,
                    )
                    .where(
                        SupportCaseRequest.case_id == query.case_id,
                        ActivityLog.deleted_at.is_(None),
                        ActivityLog.created_at >= cutoff,
                        ActivityLog.action.in_(("http.app_exception", "http.unhandled_exception")),
                    )
                )
                or 0
            )
            metrics.append(
                OversightMetric(
                    key="case_linked_error_events",
                    label="Case-linked request error events",
                    value=case_errors,
                    state="observed",
                    source="support_case_requests",
                )
            )
        return SupportIncidentsSummaryRead(
            observed_at=now,
            window_hours=query.hours,
            scope=scope,
            source_status="operational",
            freshness="current",
            metrics=metrics,
        )

    def degraded(now: datetime) -> SupportIncidentsSummaryRead:
        return SupportIncidentsSummaryRead(
            observed_at=now,
            window_hours=query.hours,
            scope=scope,
            source_status="unavailable",
            freshness="unknown",
            metrics=[
                OversightMetric(
                    key="incidents_summary",
                    label="Security incidents summary",
                    value=None,
                    state="unavailable",
                    source="activity_log",
                )
            ],
        )

    return await execute_oversight_read(
        session,
        token,
        capability="incidents.read",
        surface="incidents",
        request_id=request_id,
        query_fn=run,
        degraded_fn=degraded,
        case_id=query.case_id,
    )
