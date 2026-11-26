import asyncio
from datetime import timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.import_batch import ImportBatch
from app.models.notification import Notification
from app.models.task_outbox import TaskOutbox, notification_email_outbox_dedupe_key
from app.repositories.report_export_repository import ReportExportRepository
from app.services.import_service import (
    InvalidToken,
    decrypt_import_payload,
    import_outbox_dedupe_key,
)
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.utils.security import utc_now

logger = structlog.get_logger("celery.task")

MAX_OUTBOX_ATTEMPTS = 5
STALE_DISPATCH_TIMEOUT = timedelta(minutes=5)
MAX_NOTIFICATION_EMAIL_ATTEMPTS = 8
NOTIFICATION_EMAIL_TASK = "send_email_notification"
NOTIFICATION_EMAIL_LEASE = timedelta(minutes=5)


@celery_app.task(name="dispatch_task_outbox", queue="maintenance")
def dispatch_task_outbox() -> int:
    return run_async_task(_dispatch_task_outbox())


@celery_app.task(name="dispatch_notification_email_outbox", queue="maintenance")
def dispatch_notification_email_outbox() -> int:
    return run_async_task(_dispatch_notification_email_outbox())


def _parse_report_pdf_payload(entry: TaskOutbox) -> tuple[UUID, bool] | None:
    if entry.task_name != "generate_report_pdf" or not entry.args_json:
        return None
    try:
        report_id = UUID(str(entry.args_json[0]))
    except (ValueError, TypeError):
        return None
    email_after = bool((entry.kwargs_json or {}).get("email_after", False))
    return report_id, email_after


def _parse_import_async_payload(entry: TaskOutbox) -> dict[str, Any] | None:
    if entry.task_name != "run_import_async" or len(entry.args_json or []) != 2:
        return None
    try:
        batch_id = UUID(str(entry.args_json[0]))
        actor_id = UUID(str(entry.args_json[1]))
    except (ValueError, TypeError):
        return None
    kwargs = entry.kwargs_json or {}
    if not isinstance(kwargs, dict):
        return None
    template_type = kwargs.get("template_type")
    file_name = kwargs.get("file_name")
    content_sha256 = kwargs.get("content_sha256")
    content_ciphertext = kwargs.get("content_ciphertext")
    content_key_id = kwargs.get("content_key_id")
    if not all(
        isinstance(item, str) and bool(item)
        for item in (template_type, file_name, content_sha256, content_ciphertext)
    ):
        return None
    if content_key_id is not None and (not isinstance(content_key_id, str) or not content_key_id):
        return None
    try:
        content = decrypt_import_payload(
            str(content_ciphertext),
            expected_key_id=content_key_id,
        )
    except (InvalidToken, ValueError, OSError):
        return None
    if sha256(content).hexdigest() != content_sha256:
        return None
    return {
        "template_type": template_type,
        "file_name": file_name,
        "actor_id": str(actor_id),
        "batch_id": str(batch_id),
    }


def _parse_notification_email_payload(entry: TaskOutbox) -> UUID | None:
    if entry.task_name != NOTIFICATION_EMAIL_TASK or len(entry.args_json or []) != 1:
        return None
    try:
        notification_id = UUID(str(entry.args_json[0]))
    except (ValueError, TypeError):
        return None
    if entry.dedupe_key != notification_email_outbox_dedupe_key(notification_id):
        return None
    if entry.kwargs_json:
        return None
    return notification_id


def _scrub_outbox_ciphertext(entry: TaskOutbox) -> None:
    if isinstance(entry.kwargs_json, dict) and "content_ciphertext" in entry.kwargs_json:
        entry.kwargs_json = {
            key: value for key, value in entry.kwargs_json.items() if key != "content_ciphertext"
        }


async def _reconcile_import_outbox_before_dispatch(
    session: AsyncSession, entry: TaskOutbox
) -> bool:
    if entry.task_name != "run_import_async" or not entry.args_json:
        return False
    try:
        batch_id = UUID(str(entry.args_json[0]))
    except (ValueError, TypeError):
        return False
    # Lock order: TaskOutbox (already locked by dispatcher) -> ImportBatch.
    batch = await session.get(ImportBatch, batch_id, with_for_update=True, populate_existing=True)
    if batch is not None and batch.status in {"completed", "failed"}:
        entry.status = "completed" if batch.status == "completed" else "failed"
        _scrub_outbox_ciphertext(entry)
        return True
    return False


async def _mark_import_batch_dispatch_failed(session: AsyncSession, entry: TaskOutbox) -> None:
    if entry.task_name != "run_import_async":
        return
    _scrub_outbox_ciphertext(entry)
    if not entry.args_json:
        return
    try:
        batch_id = UUID(str(entry.args_json[0]))
    except (ValueError, TypeError):
        return
    # Lock order: TaskOutbox (already locked by dispatcher) -> ImportBatch.
    batch = await session.get(ImportBatch, batch_id, with_for_update=True, populate_existing=True)
    if batch is not None and batch.status == "completed":
        entry.status = "completed"
        return
    if batch is not None and batch.status == "queued":
        batch.status = "failed"
        batch.error_count = 1
        batch.summary = {"error_code": "IMPORT_DISPATCH_FAILED"}


def _build_dispatch_spec(entry: TaskOutbox) -> tuple[list[Any], dict[str, Any], str] | None:
    if _parse_notification_email_payload(entry) is not None:
        return list(entry.args_json), {}, "email"
    if entry.task_name == "generate_report_pdf":
        if _parse_report_pdf_payload(entry) is None:
            return None
        return list(entry.args_json), dict(entry.kwargs_json or {}), "report"
    if entry.task_name == "run_import_async":
        import_kwargs = _parse_import_async_payload(entry)
        if import_kwargs is None:
            return None
        return [], import_kwargs, "maintenance"
    return None


async def _lock_notification_for_outbox(
    session: AsyncSession, entry: TaskOutbox
) -> Notification | None:
    notification_id = _parse_notification_email_payload(entry)
    if notification_id is None:
        return None
    return await session.scalar(
        select(Notification)
        .where(Notification.id == notification_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _dispatch_notification_email_outbox() -> int:
    """Persist bounded notification dispatch claims before submitting to Celery."""
    now = utc_now()
    claimed: list[tuple[UUID, int]] = []
    async with AsyncSessionLocal() as session:
        candidates = list(
            await session.scalars(
                select(TaskOutbox)
                .where(
                    TaskOutbox.task_name == NOTIFICATION_EMAIL_TASK,
                    or_(
                        and_(
                            TaskOutbox.status == "pending",
                            or_(
                                TaskOutbox.next_attempt_at.is_(None),
                                TaskOutbox.next_attempt_at <= now,
                            ),
                        ),
                        and_(
                            TaskOutbox.status.in_(("dispatching", "dispatched", "processing")),
                            TaskOutbox.lease_until.is_not(None),
                            TaskOutbox.lease_until <= now,
                        ),
                    ),
                )
                .order_by(TaskOutbox.next_attempt_at, TaskOutbox.created_at, TaskOutbox.id)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )
        for entry in candidates:
            notification = await _lock_notification_for_outbox(session, entry)
            if _parse_notification_email_payload(entry) is None or notification is None:
                entry.status = "failed"
                entry.lease_until = None
                logger.error("notification_email_outbox_payload_invalid", outbox_id=str(entry.id))
                continue
            if notification.email_status in {"sent", "skipped"}:
                entry.status = "completed"
                entry.lease_until = None
                continue
            if entry.status != "pending":
                # A claim or worker lease expired after the broker/provider outcome may have
                # become ambiguous. Do not resend without an explicit audited reconciliation.
                entry.status = "manual_review"
                entry.lease_until = None
                notification.email_status = "unknown"
                logger.warning(
                    "notification_email_dispatch_outcome_unknown", outbox_id=str(entry.id)
                )
                continue
            if _build_dispatch_spec(entry) is None:
                entry.status = "failed"
                notification.email_status = "failed"
                continue
            if entry.attempts >= MAX_NOTIFICATION_EMAIL_ATTEMPTS:
                entry.status = "failed"
                notification.email_status = "failed"
                logger.error("notification_email_dispatch_exhausted", outbox_id=str(entry.id))
                continue
            entry.attempts += 1
            entry.status = "dispatching"
            entry.lease_until = now + NOTIFICATION_EMAIL_LEASE
            entry.next_attempt_at = None
            claimed.append((entry.id, entry.attempts))
        await session.commit()

    submitted = 0
    for outbox_id, attempt in claimed:
        async with AsyncSessionLocal() as session:
            dispatch_entry = await session.get(TaskOutbox, outbox_id)
        if dispatch_entry is None:
            continue
        dispatch_ok = await _dispatch_entry(
            dispatch_entry, task_id=f"notification-email-{outbox_id}-attempt-{attempt}"
        )
        if dispatch_ok:
            submitted += 1
        async with AsyncSessionLocal() as session:
            final_entry = await session.scalar(
                select(TaskOutbox)
                .where(TaskOutbox.id == outbox_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                final_entry is None
                or final_entry.status != "dispatching"
                or final_entry.attempts != attempt
            ):
                # The worker may already have claimed or completed this message.
                continue
            if dispatch_ok:
                final_entry.status = "dispatched"
                final_entry.dispatched_at = utc_now()
                final_entry.lease_until = utc_now() + NOTIFICATION_EMAIL_LEASE
            elif attempt >= MAX_NOTIFICATION_EMAIL_ATTEMPTS:
                final_entry.status = "failed"
                final_entry.lease_until = None
                notification = await _lock_notification_for_outbox(session, final_entry)
                if notification is not None and notification.email_status not in {
                    "sent",
                    "skipped",
                }:
                    notification.email_status = "failed"
            else:
                final_entry.status = "pending"
                final_entry.lease_until = None
                final_entry.next_attempt_at = utc_now() + timedelta(
                    seconds=min(30 * (2 ** (attempt - 1)), 3600)
                )
                logger.warning(
                    "notification_email_enqueue_deferred",
                    outbox_id=str(final_entry.id),
                    attempts=attempt,
                )
            await session.commit()
    return submitted


def _entry_task_id(entry: TaskOutbox, *, attempt: int | None = None) -> str:
    if entry.task_name == "run_import_async" and entry.args_json:
        base = f"import-batch-{entry.args_json[0]}"
        return base if attempt is None else f"{base}-retry-{attempt}"
    return str(entry.id) if attempt is None else f"{entry.id}:retry:{attempt}"


async def _dispatch_entry(entry: TaskOutbox, *, task_id: str) -> bool:
    spec = _build_dispatch_spec(entry)
    if spec is None:
        return False
    args, kwargs, queue = spec
    try:
        await asyncio.to_thread(
            celery_app.send_task,
            entry.task_name,
            args=args,
            kwargs=kwargs,
            task_id=task_id,
            queue=queue,
            retry=False,
        )
    except Exception as exc:
        logger.warning(
            "outbox_dispatch_failed",
            outbox_id=str(entry.id),
            task_name=entry.task_name,
            attempts=entry.attempts,
            error_type=type(exc).__name__,
        )
        return False
    return True


async def dispatch_import_outbox_for_batch(batch_id: UUID) -> bool:
    async with AsyncSessionLocal() as session:
        entry = await session.scalar(
            select(TaskOutbox)
            .where(
                TaskOutbox.dedupe_key == import_outbox_dedupe_key(batch_id),
                TaskOutbox.status == "pending",
            )
            .with_for_update(skip_locked=True)
        )
        if entry is None:
            return False
        if await _reconcile_import_outbox_before_dispatch(session, entry):
            await session.commit()
            return True
        if _build_dispatch_spec(entry) is None:
            entry.attempts += 1
            entry.status = "failed"
            await _mark_import_batch_dispatch_failed(session, entry)
            logger.error("outbox_invalid_import_payload", outbox_id=str(entry.id))
            await session.commit()
            return False
        entry.attempts += 1
        if await _dispatch_entry(entry, task_id=_entry_task_id(entry)):
            entry.status = "dispatched"
            entry.dispatched_at = utc_now()
            await session.commit()
            return True
        if entry.attempts >= MAX_OUTBOX_ATTEMPTS:
            entry.status = "failed"
            await _mark_import_batch_dispatch_failed(session, entry)
        else:
            logger.warning(
                "import_outbox_immediate_dispatch_deferred",
                outbox_id=str(entry.id),
                batch_id=str(batch_id),
                attempts=entry.attempts,
            )
        await session.commit()
        return False


async def _dispatch_task_outbox() -> int:
    dispatched = 0
    now = utc_now()
    stale_cutoff = now - STALE_DISPATCH_TIMEOUT
    async with AsyncSessionLocal() as session:
        exports = ReportExportRepository(session)
        pending_entries = list(
            await session.scalars(
                select(TaskOutbox)
                .where(
                    TaskOutbox.status == "pending",
                    TaskOutbox.task_name != NOTIFICATION_EMAIL_TASK,
                )
                .order_by(TaskOutbox.created_at, TaskOutbox.id)
                .limit(25)
                .with_for_update(skip_locked=True)
            )
        )
        for entry in pending_entries:
            if await _reconcile_import_outbox_before_dispatch(session, entry):
                continue
            if _build_dispatch_spec(entry) is None:
                entry.attempts += 1
                entry.status = "failed"
                await _mark_import_batch_dispatch_failed(session, entry)
                logger.error("outbox_unknown_task", outbox_id=str(entry.id))
                continue
            if entry.attempts >= MAX_OUTBOX_ATTEMPTS:
                entry.status = "failed"
                await _mark_import_batch_dispatch_failed(session, entry)
                logger.error(
                    "outbox_dispatch_exhausted",
                    outbox_id=str(entry.id),
                    attempts=entry.attempts,
                )
                continue
            entry.attempts += 1
            if not await _dispatch_entry(entry, task_id=_entry_task_id(entry)):
                if entry.attempts >= MAX_OUTBOX_ATTEMPTS:
                    entry.status = "failed"
                    await _mark_import_batch_dispatch_failed(session, entry)
                    logger.error(
                        "outbox_dispatch_exhausted",
                        outbox_id=str(entry.id),
                        attempts=entry.attempts,
                    )
                break
            entry.status = "dispatched"
            entry.dispatched_at = now
            dispatched += 1

        stale_entries = list(
            await session.scalars(
                select(TaskOutbox)
                .where(
                    TaskOutbox.status == "dispatched",
                    TaskOutbox.task_name != NOTIFICATION_EMAIL_TASK,
                    TaskOutbox.dispatched_at.is_not(None),
                    TaskOutbox.dispatched_at < stale_cutoff,
                )
                .order_by(TaskOutbox.dispatched_at, TaskOutbox.id)
                .limit(25)
                .with_for_update(skip_locked=True)
            )
        )
        for entry in stale_entries:
            if await _reconcile_import_outbox_before_dispatch(session, entry):
                logger.info(
                    "outbox_reconciled_completed",
                    outbox_id=str(entry.id),
                    task_name=entry.task_name,
                )
                continue
            if _build_dispatch_spec(entry) is None:
                entry.status = "failed"
                await _mark_import_batch_dispatch_failed(session, entry)
                logger.error("outbox_unknown_task", outbox_id=str(entry.id))
                continue
            report_parsed = _parse_report_pdf_payload(entry)
            if report_parsed is not None:
                report_id, email_after = report_parsed
                existing = await exports.latest_for_report(report_id)
                if existing is not None and (not email_after or existing.email_status == "sent"):
                    entry.status = "completed"
                    logger.info(
                        "outbox_reconciled_completed",
                        outbox_id=str(entry.id),
                        report_id=str(report_id),
                    )
                    continue
            if entry.attempts >= MAX_OUTBOX_ATTEMPTS:
                entry.status = "failed"
                await _mark_import_batch_dispatch_failed(session, entry)
                logger.error(
                    "outbox_dispatch_exhausted",
                    outbox_id=str(entry.id),
                    attempts=entry.attempts,
                )
                continue
            next_attempt = entry.attempts + 1
            entry.attempts = next_attempt
            retry_task_id = _entry_task_id(entry, attempt=next_attempt)
            if not await _dispatch_entry(entry, task_id=retry_task_id):
                if entry.attempts >= MAX_OUTBOX_ATTEMPTS:
                    entry.status = "failed"
                    await _mark_import_batch_dispatch_failed(session, entry)
                break
            entry.dispatched_at = now
            dispatched += 1
        await session.commit()
    return dispatched
