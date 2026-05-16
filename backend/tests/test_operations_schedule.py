from app.tasks.backup import backup_command
from app.tasks.celery_app import celery_app


def test_backup_command_uses_current_python_and_monthly_flag() -> None:
    daily_command = backup_command()
    monthly_command = backup_command(monthly=True)

    assert daily_command[-1] == "scripts/backup.py"
    assert "--monthly" not in daily_command
    assert monthly_command[-2:] == ["scripts/backup.py", "--monthly"]


def test_celery_beat_schedules_operational_maintenance_tasks() -> None:
    schedule = celery_app.conf.beat_schedule

    assert schedule["run-database-backup-daily"]["task"] == "run_database_backup"
    assert schedule["run-database-backup-monthly"]["task"] == "run_database_backup"
    assert schedule["run-database-backup-monthly"]["args"] == (True,)
    assert schedule["cleanup-old-notifications-daily"]["task"] == "cleanup_old_notifications"
