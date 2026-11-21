from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import Literal

import structlog

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.backup_receipt_ingestion import record_local_scheduled_db_attempt
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.utils.security import utc_now

logger = structlog.get_logger("celery.task")


def backup_command(monthly: bool = False, target: str = "all") -> list[str]:
    command = [sys.executable, "-m", "scripts.backup", "--target", target]
    if monthly:
        command.append("--monthly")
    return command


async def _persist_local_backup_attempt(outcome: Literal["pass", "fail"]) -> None:
    async with AsyncSessionLocal() as session:
        await record_local_scheduled_db_attempt(
            session,
            outcome=outcome,
            captured_at=utc_now(),
            recorded_by="celery:run_database_backup",
        )
        await session.commit()


def _record_local_attempt_best_effort(outcome: Literal["pass", "fail"]) -> None:
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            run_async_task(_persist_local_backup_attempt(outcome))
        else:
            raise RuntimeError("Cannot record backup receipt inside an active event loop.")
    except Exception as exc:
        logger.warning(
            "backup_receipt_record_failed",
            outcome=outcome,
            error_type=type(exc).__name__,
        )


@celery_app.task(
    name="run_database_backup",
    queue="backup",
    autoretry_for=(subprocess.CalledProcessError, subprocess.TimeoutExpired),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def run_database_backup(monthly: bool = False) -> str:
    if not get_settings().backup_encryption_password:
        logger.error("backup_encryption_password_missing")
        _record_local_attempt_best_effort("fail")
        raise RuntimeError("A backup-encryption secret is required for scheduled backups.")
    cmd = backup_command(monthly)
    logger.info("backup_executing", command=" ".join(cmd), monthly=monthly)
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except Exception:
        _record_local_attempt_best_effort("fail")
        raise
    output = result.stdout.strip()
    _record_local_attempt_best_effort("pass")
    logger.info("backup_completed", output=output[:500])
    return output
