from app.tasks.backup import backup_command
from app.tasks.celery_app import celery_app
from scripts.backup import database_targets


def test_backup_command_uses_current_python_and_monthly_flag() -> None:
    daily_command = backup_command()
    monthly_command = backup_command(monthly=True)

    assert daily_command[-2:] == ["--target", "all"]
    assert "--monthly" not in daily_command
    assert monthly_command[-3:] == ["--target", "all", "--monthly"]


def test_backup_targets_include_grafana_with_url_encoded_password(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:password@postgres/application")
    monkeypatch.setenv("GRAFANA_DB_PASSWORD", "grafana@password")

    targets = dict(database_targets("all"))

    assert targets["application"].endswith("/application")
    assert targets["grafana"] == "postgresql://grafana:grafana%40password@postgres:5432/grafana"


def test_celery_beat_schedules_operational_maintenance_tasks() -> None:
    schedule = celery_app.conf.beat_schedule

    assert schedule["run-database-backup-daily"]["task"] == "run_database_backup"
    assert schedule["run-database-backup-monthly"]["task"] == "run_database_backup"
    assert schedule["run-database-backup-monthly"]["args"] == (True,)
    assert schedule["cleanup-old-notifications-daily"]["task"] == "cleanup_old_notifications"
    assert schedule["check-supplier-tds-expiry-daily"]["task"] == "check_supplier_tds_expiry"
