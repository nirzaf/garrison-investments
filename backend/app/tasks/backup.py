import structlog
import subprocess
import sys

from app.tasks.celery_app import celery_app

logger = structlog.get_logger("celery.task")


def backup_command(monthly: bool = False) -> list[str]:
    command = [sys.executable, "scripts/backup.py"]
    if monthly:
        command.append("--monthly")
    return command


@celery_app.task(
    name="run_database_backup",
    queue="backup",
    autoretry_for=(subprocess.CalledProcessError, subprocess.TimeoutExpired),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def run_database_backup(monthly: bool = False) -> str:
    cmd = backup_command(monthly)
    logger.info("backup_executing", command=" ".join(cmd), monthly=monthly)
    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        timeout=900,
    )
    output = result.stdout.strip()
    logger.info("backup_completed", output=output[:500])
    return output
