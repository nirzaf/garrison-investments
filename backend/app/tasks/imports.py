from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.import_batch import ImportBatch
from app.models.user import User
from app.services.import_service import ImportService
from app.tasks.async_utils import run_async_task
from app.tasks.base import LoggedTask
from app.tasks.celery_app import celery_app
from app.utils.exceptions import AppException

logger = structlog.get_logger("celery.task")


class ImportTask(LoggedTask):
    """Mark a batch failed only after Celery exhausts its retry policy."""

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        batch_id = kwargs.get("batch_id")
        if batch_id:
            try:
                run_async_task(_mark_import_batch_failed(batch_id))
            except Exception as cleanup_error:
                logger.error(
                    "import_batch_failure_state_update_failed",
                    batch_id=batch_id,
                    exception_type=type(cleanup_error).__name__,
                )
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(
    name="run_import_async",
    queue="maintenance",
    base=ImportTask,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def run_import_async(
    *,
    template_type: str,
    file_name: str,
    content: bytes,
    actor_id: str,
    batch_id: str | None = None,
) -> str:
    logger.info(
        "import_started",
        template_type=template_type,
        file_name=file_name,
        actor_id=actor_id,
        batch_id=batch_id,
        content_size=len(content),
    )
    return run_async_task(
        _run_import_async(
            template_type=template_type,
            file_name=file_name,
            content=content,
            actor_id=actor_id,
            batch_id=batch_id,
        )
    )


async def _run_import_async(
    *,
    template_type: str,
    file_name: str,
    content: bytes,
    actor_id: str,
    batch_id: str | None = None,
) -> str:
    batch_uuid = UUID(batch_id) if batch_id else None
    async with AsyncSessionLocal() as session:
        actor = await session.get(User, UUID(actor_id))
        if not actor or not actor.is_active or actor.deleted_at is not None:
            await _mark_batch_failed(session, batch_uuid, "IMPORT_ACTOR_UNAVAILABLE")
            logger.warning("import_actor_unavailable", actor_id=actor_id)
            return f"import failed: user {actor_id} not found"
        try:
            ImportService.ensure_template_access(actor, template_type)
            if batch_uuid:
                batch = await session.get(ImportBatch, batch_uuid, with_for_update=True)
                if (
                    batch is None
                    or batch.created_by != actor.id
                    or batch.template_type != template_type
                    or batch.status not in {"queued", "processing", "completed"}
                ):
                    raise AppException(
                        "Queued import is no longer eligible for processing.",
                        status_code=409,
                        error_code="IMPORT_BATCH_NOT_ELIGIBLE",
                    )
                if batch.status == "queued":
                    await session.execute(
                        update(ImportBatch)
                        .where(
                            ImportBatch.id == batch_uuid,
                            ImportBatch.created_by == actor.id,
                            ImportBatch.template_type == template_type,
                            ImportBatch.status == "queued",
                        )
                        .values(status="processing")
                    )
                # End the batch-only transaction before the service takes the
                # actor lock. A concurrent delivery may already hold that lock.
                await session.commit()
            result = await ImportService(session).run_import(
                template_type=template_type,
                file_name=file_name,
                content=content,
                actor=actor,
                batch_id=batch_uuid,
            )
        except AppException as exc:
            await session.rollback()
            if exc.status_code < 500:
                await _mark_batch_failed(session, batch_uuid, exc.error_code)
                logger.warning(
                    "import_authorization_or_validation_stopped",
                    batch_id=batch_id,
                    error_code=exc.error_code,
                )
                return f"import stopped: {exc.error_code}"
            logger.error(
                "import_execution_failed",
                batch_id=batch_id,
                error_code=exc.error_code,
            )
            raise
        except Exception as exc:
            await session.rollback()
            logger.error(
                "import_execution_failed",
                batch_id=batch_id,
                error_type=type(exc).__name__,
            )
            raise
        logger.info("import_completed", batch_id=str(result.batch_id), status=result.status)
        return f"import {result.batch_id} completed: {result.status}"


async def _mark_batch_failed(session: AsyncSession, batch_id: UUID | None, error_code: str) -> None:
    if not batch_id:
        return
    batch = await session.get(ImportBatch, batch_id, with_for_update=True)
    if not batch or batch.status == "completed":
        return
    batch.status = "failed"
    batch.summary = {"error_code": error_code}
    await session.commit()


async def _mark_import_batch_failed(batch_id: str) -> None:
    try:
        parsed_batch_id = UUID(batch_id)
    except (ValueError, TypeError):
        logger.warning("import_failure_batch_id_invalid")
        return
    async with AsyncSessionLocal() as session:
        await _mark_batch_failed(session, parsed_batch_id, "IMPORT_EXECUTION_FAILED")
