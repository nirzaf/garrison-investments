import subprocess
import sys

from app.tasks.celery_app import celery_app


def backup_command(monthly: bool = False) -> list[str]:
    command = [sys.executable, "scripts/backup.py"]
    if monthly:
        command.append("--monthly")
    return command


@celery_app.task(name="run_database_backup", queue="backup")
def run_database_backup(monthly: bool = False) -> str:
    result = subprocess.run(
        backup_command(monthly),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
