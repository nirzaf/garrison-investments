from uuid import UUID

from app.database import AsyncSessionLocal
from app.models.import_batch import ImportBatch
from app.models.user import User
from app.services.import_service import ImportService
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app


@celery_app.task(
    name="run_import_async",
    queue="maintenance",
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
        if not actor:
            await _mark_batch_failed(session, batch_uuid, f"user {actor_id} not found")
            return f"import failed: user {actor_id} not found"
        if batch_uuid:
            batch = await session.get(ImportBatch, batch_uuid)
            if batch:
                batch.status = "processing"
                await session.commit()
        try:
            result = await ImportService(session).run_import(
                template_type=template_type,
                file_name=file_name,
                content=content,
                actor=actor,
                batch_id=batch_uuid,
            )
        except Exception as exc:
            await session.rollback()
            await _mark_batch_failed(session, batch_uuid, str(exc))
            raise
        return f"import {result.batch_id} completed: {result.status}"


async def _mark_batch_failed(session, batch_id: UUID | None, error: str) -> None:
    if not batch_id:
        return
    batch = await session.get(ImportBatch, batch_id)
    if not batch:
        return
    batch.status = "failed"
    batch.summary = {"error": error}
    await session.commit()
