import asyncio

from app.database import AsyncSessionLocal
from app.services.approval_service import ApprovalService
from app.services.inventory_service import InventoryService
from app.tasks.celery_app import celery_app


@celery_app.task(name="process_approval_reminders", queue="maintenance")
def process_approval_reminders() -> dict[str, int]:
    async def run() -> dict[str, int]:
        async with AsyncSessionLocal() as session:
            reminded, escalated = await ApprovalService(session).send_reminders_and_escalations()
            return {"reminded": reminded, "escalated": escalated}

    return asyncio.run(run())


@celery_app.task(name="check_low_stock", queue="maintenance")
def check_low_stock() -> dict[str, int]:
    async def run() -> dict[str, int]:
        async with AsyncSessionLocal() as session:
            rows = await InventoryService(session).low_stock()
            return {"low_stock_items": len(rows)}

    return asyncio.run(run())
