import asyncio

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.task_outbox import TaskOutbox
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.utils.security import utc_now

logger = structlog.get_logger("celery.task")


@celery_app.task(name="dispatch_task_outbox", queue="maintenance")
def dispatch_task_outbox() -> int:
    return run_async_task(_dispatch_task_outbox())


async def _dispatch_task_outbox() -> int:
    dispatched = 0
    async with AsyncSessionLocal() as session:
        entries = await session.scalars(
            select(TaskOutbox)
            .where(TaskOutbox.status == "pending")
            .order_by(TaskOutbox.created_at, TaskOutbox.id)
            .limit(25)
            .with_for_update(skip_locked=True)
        )
        for entry in entries:
            entry.attempts += 1
            if entry.task_name != "generate_report_pdf":
                entry.status = "failed"
                logger.error("outbox_unknown_task", outbox_id=str(entry.id))
                continue
            try:
                await asyncio.to_thread(
                    celery_app.send_task,
                    entry.task_name,
                    args=entry.args_json,
                    kwargs=entry.kwargs_json,
                    task_id=str(entry.id),
                    queue="report",
                    retry=False,
                )
            except Exception as exc:
                logger.warning(
                    "outbox_dispatch_failed", outbox_id=str(entry.id), error_type=type(exc).__name__
                )
                break
            entry.status = "dispatched"
            entry.dispatched_at = utc_now()
            dispatched += 1
        await session.commit()
    return dispatched
