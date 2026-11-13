import argparse
import gzip
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.launch_evidence import collect_evidence, render_markdown
from scripts.restore_dry_run import inspect_backup, restore_backup
from scripts.validate_import_sources import default_template_sources, validate_source


def test_launch_evidence_records_attached_files(tmp_path: Path) -> None:
    signoff = tmp_path / "uat.md"
    signoff.write_text("signed by operation manager", encoding="utf-8")
    args = argparse.Namespace(
        target="production",
        output=tmp_path / "evidence.md",
        json_output=None,
        health_url=None,
        readiness_url=None,
        timeout=1,
        approver="Operation Manager",
        run_url="https://github.example/run/1",
        commit="abc123",
        backup_object="backups/daily/garrison.sql.gz",
        restore_log=None,
        uat_signoff=str(signoff),
        template_signoff=None,
        migration_source=[],
    )

    evidence = collect_evidence(args, {})
    markdown = render_markdown(evidence)

    assert evidence["target"] == "production"
    assert evidence["approver"] == "Operation Manager"
    assert evidence["files"][0]["label"] == "uat_signoff"
    assert "backups/daily/garrison.sql.gz" in markdown


def test_production_launch_evidence_requires_operator(tmp_path: Path) -> None:
    args = argparse.Namespace(
        target="production",
        output=tmp_path / "evidence.md",
        json_output=None,
        health_url=None,
        readiness_url=None,
        timeout=1,
        approver=None,
        run_url=None,
        commit=None,
        backup_object=None,
        restore_log=None,
        uat_signoff=None,
        template_signoff=None,
        migration_source=[],
    )

    with pytest.raises(ValueError):
        collect_evidence(args, {})


def test_restore_dry_run_inspects_gzipped_plain_sql_dump(tmp_path: Path) -> None:
    backup = tmp_path / "backup.sql.gz"
    with gzip.open(backup, "wt", encoding="utf-8") as file:
        file.write("SET statement_timeout = 0;\nCREATE TABLE users (id uuid);\n")

    result = inspect_backup(backup)

    assert result["size_bytes"] > 0
    assert "CREATE TABLE" in result["markers"]


@pytest.mark.parametrize("suffix", [".sql", ".sql.gz"])
def test_restore_uses_noninteractive_psql_without_startup_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    backup = tmp_path / f"fixture{suffix}"
    opener = gzip.open if suffix.endswith(".gz") else open
    with opener(backup, "wt", encoding="utf-8") as dump:
        dump.write("CREATE TABLE sample (id int);\n")
    run = Mock()
    monkeypatch.setattr("scripts.restore_dry_run.subprocess.run", run)

    restore_backup(backup, "postgresql://fixture:fixture_only@127.0.0.1/garrison_restore_test_sample")

    run.assert_called_once()
    command = run.call_args.args[0]
    assert command[:6] == [
        "psql", "--no-psqlrc", "--no-password", "--set", "ON_ERROR_STOP=on", "--single-transaction"
    ]
    assert command[6:9] == [
        "--dbname", "postgresql://fixture@127.0.0.1/garrison_restore_test_sample", "--file"
    ]
    assert run.call_args.kwargs["env"]["PGPASSWORD"] == "fixture_only"
    assert run.call_args.kwargs["check"] is True


def test_validate_default_import_templates_are_usable() -> None:
    results = [
        validate_source(template_type, path)
        for template_type, path in default_template_sources()
    ]

    assert results
    assert all(result.valid for result in results)
