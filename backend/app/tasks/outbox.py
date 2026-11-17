import asyncio
from datetime import timedelta
from uuid import UUID

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.task_outbox import TaskOutbox
from app.repositories.report_export_repository import ReportExportRepository
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.utils.security import utc_now

logger = structlog.get_logger("celery.task")

MAX_OUTBOX_ATTEMPTS = 5
STALE_DISPATCH_TIMEOUT = timedelta(minutes=5)


@celery_app.task(name="dispatch_task_outbox", queue="maintenance")
def dispatch_task_outbox() -> int:
    return run_async_task(_dispatch_task_outbox())


def _parse_report_pdf_payload(entry: TaskOutbox) -> tuple[UUID, bool] | None:
    if entry.task_name != "generate_report_pdf" or not entry.args_json:
        return None
    try:
        report_id = UUID(str(entry.args_json[0]))
    except (ValueError, TypeError):
        return None
    email_after = bool((entry.kwargs_json or {}).get("email_after", False))
    return report_id, email_after


async def _dispatch_entry(entry: TaskOutbox, *, task_id: str) -> bool:
    try:
        await asyncio.to_thread(
            celery_app.send_task,
            entry.task_name,
            args=entry.args_json,
            kwargs=entry.kwargs_json,
            task_id=task_id,
            queue="report",
            retry=False,
        )
    except Exception as exc:
        logger.warning(
            "outbox_dispatch_failed",
            outbox_id=str(entry.id),
            attempts=entry.attempts,
            error_type=type(exc).__name__,
        )
        return False
    return True


async def _dispatch_task_outbox() -> int:
    dispatched = 0
    now = utc_now()
    stale_cutoff = now - STALE_DISPATCH_TIMEOUT
    async with AsyncSessionLocal() as session:
        exports = ReportExportRepository(session)
        pending_entries = list(
            await session.scalars(
                select(TaskOutbox)
                .where(TaskOutbox.status == "pending")
                .order_by(TaskOutbox.created_at, TaskOutbox.id)
                .limit(25)
                .with_for_update(skip_locked=True)
            )
        )
        for entry in pending_entries:
            parsed = _parse_report_pdf_payload(entry)
            if parsed is None:
                entry.attempts += 1
                entry.status = "failed"
                logger.error("outbox_unknown_task", outbox_id=str(entry.id))
                continue
            if entry.attempts >= MAX_OUTBOX_ATTEMPTS:
                entry.status = "failed"
                logger.error(
                    "outbox_dispatch_exhausted",
                    outbox_id=str(entry.id),
                    attempts=entry.attempts,
                )
                continue
            entry.attempts += 1
            if not await _dispatch_entry(entry, task_id=str(entry.id)):
                if entry.attempts >= MAX_OUTBOX_ATTEMPTS:
                    entry.status = "failed"
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
                    TaskOutbox.dispatched_at.is_not(None),
                    TaskOutbox.dispatched_at < stale_cutoff,
                )
                .order_by(TaskOutbox.dispatched_at, TaskOutbox.id)
                .limit(25)
                .with_for_update(skip_locked=True)
            )
        )
        for entry in stale_entries:
            parsed = _parse_report_pdf_payload(entry)
            if parsed is None:
                entry.status = "failed"
                logger.error("outbox_unknown_task", outbox_id=str(entry.id))
                continue
            report_id, email_after = parsed
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
                logger.error(
                    "outbox_dispatch_exhausted",
                    outbox_id=str(entry.id),
                    attempts=entry.attempts,
                )
                continue
            next_attempt = entry.attempts + 1
            entry.attempts = next_attempt
            retry_task_id = f"{entry.id}:retry:{next_attempt}"
            if not await _dispatch_entry(entry, task_id=retry_task_id):
                if entry.attempts >= MAX_OUTBOX_ATTEMPTS:
                    entry.status = "failed"
                break
            entry.dispatched_at = now
            dispatched += 1
        await session.commit()
    return dispatched
