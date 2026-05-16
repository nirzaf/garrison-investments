import asyncio
from uuid import UUID

from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.import_service import ImportService
from app.tasks.celery_app import celery_app


@celery_app.task(name="run_import_async", queue="maintenance")
def run_import_async(*, template_type: str, file_name: str, content: bytes, actor_id: str) -> str:
    async def run() -> str:
        async with AsyncSessionLocal() as session:
            actor = await session.get(User, UUID(actor_id))
            if not actor:
                return f"import failed: user {actor_id} not found"
            result = await ImportService(session).run_import(
                template_type=template_type,
                file_name=file_name,
                content=content,
                actor=actor,
            )
            return f"import {result.batch_id} completed: {result.status}"

    return asyncio.run(run())
