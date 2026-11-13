import gzip

import pytest

from app.tasks.backup import backup_command
from app.tasks.celery_app import celery_app
from scripts.backup import create_dump, database_targets


@pytest.mark.parametrize("portable", [False, True], ids=["ordinary", "portable"])
def test_backup_dump_is_valid_gzip(tmp_path, monkeypatch, portable: bool) -> None:
    pg_dump = tmp_path / "pg_dump"
    pg_dump.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$DUMP_ARGUMENTS\"\nprintf 'SELECT 1;\\n'\n"
    )
    pg_dump.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=":")
    arguments = tmp_path / "arguments"
    monkeypatch.setenv("DUMP_ARGUMENTS", str(arguments))

    output = tmp_path / "backup.sql.gz"
    if portable:
        create_dump("postgresql://localhost/test", output, include_acl=False)
    else:
        create_dump("postgresql://localhost/test", output)

    assert gzip.decompress(output.read_bytes()) == b"SELECT 1;\n"
    assert ("--no-acl" in arguments.read_text().splitlines()) == portable


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
