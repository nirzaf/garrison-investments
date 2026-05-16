import subprocess

from app.tasks.celery_app import celery_app


@celery_app.task(name="run_database_backup", queue="backup")
def run_database_backup() -> str:
    result = subprocess.run(
        ["python", "scripts/backup.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
