import argparse
import gzip
from pathlib import Path

import pytest

from scripts.launch_evidence import collect_evidence, render_markdown
from scripts.restore_dry_run import inspect_backup
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


def test_validate_default_import_templates_are_usable() -> None:
    results = [
        validate_source(template_type, path)
        for template_type, path in default_template_sources()
    ]

    assert results
    assert all(result.valid for result in results)
