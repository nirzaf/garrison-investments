from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
from release_config_contract import (  # noqa: E402
    validate_backup_secret_configuration,
    validate_pinned_service_environment,
)


def test_pinned_values_must_be_present_in_effective_compose_environment() -> None:
    service = {"environment": {"DATABASE_URL": "postgres://db/app", "LOG_PURGE_ENABLED": "false"}}

    result = validate_pinned_service_environment(
        "backend",
        service,
        {"DATABASE_URL": "postgres://db/app", "LOG_PURGE_ENABLED": "false"},
    )

    assert result["LOG_PURGE_ENABLED"] == "false"


def test_list_environment_format_is_supported() -> None:
    result = validate_pinned_service_environment(
        "celery_worker",
        {"environment": ["DATABASE_URL=postgres://db/app", "LOG_PURGE_ENABLED=false"]},
        {"DATABASE_URL": "postgres://db/app", "LOG_PURGE_ENABLED": "false"},
    )

    assert result["DATABASE_URL"] == "postgres://db/app"


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"LOG_PURGE_ENABLED": "false"}, "missing keys: DATABASE_URL"),
        (
            {"DATABASE_URL": "postgres://other/app", "LOG_PURGE_ENABLED": "false"},
            "mismatched keys: DATABASE_URL",
        ),
    ],
)
def test_missing_or_overridden_pinned_value_fails(
    environment: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_pinned_service_environment(
            "backend",
            {"environment": environment},
            {"DATABASE_URL": "postgres://db/app", "LOG_PURGE_ENABLED": "false"},
        )


def test_error_does_not_reveal_environment_value() -> None:
    secret = "do-not-print-this-secret"

    with pytest.raises(ValueError) as error:
        validate_pinned_service_environment(
            "backend",
            {"environment": {"API_KEY": "different-secret"}},
            {"API_KEY": secret},
        )

    assert secret not in str(error.value)
    assert "API_KEY" in str(error.value)


def test_backup_secret_requires_private_read_only_file_mounts(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "backup-encryption-key"
    secret.write_text("synthetic-only")
    secret.chmod(0o600)
    target = "/run/secrets/backup_encryption_key"
    services = {
        name: {
            "environment": {"BACKUP_ENCRYPTION_KEY_FILE": target},
            "volumes": [
                {
                    "type": "bind",
                    "source": str(secret),
                    "target": target,
                    "read_only": True,
                }
            ],
        }
        for name in ("backend", "celery_worker", "celery_beat")
    }
    validate_backup_secret_configuration(
        {"BACKUP_ENCRYPTION_KEY_HOST_FILE": str(secret)}, services
    )


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("legacy-env", "Remove BACKUP_ENCRYPTION_PASSWORD"),
        ("read-write", "read-only file"),
        ("wide-mode", "root-owned, owner-only"),
        ("wrong-target", "mount the backup secret exactly once"),
    ],
)
def test_backup_secret_configuration_fails_closed(
    tmp_path: Path, fault: str, message: str
) -> None:
    secret = tmp_path / "backup-encryption-key"
    secret.write_text("synthetic-only")
    secret.chmod(0o644 if fault == "wide-mode" else 0o600)
    target = "/run/secrets/backup_encryption_key"
    mounted_target = "/run/secrets/wrong" if fault == "wrong-target" else target
    services = {
        name: {
            "environment": {"BACKUP_ENCRYPTION_KEY_FILE": target},
            "volumes": [
                {
                    "type": "bind",
                    "source": str(secret),
                    "target": mounted_target,
                    "read_only": fault != "read-write",
                }
            ],
        }
        for name in ("backend", "celery_worker", "celery_beat")
    }
    environment = {"BACKUP_ENCRYPTION_KEY_HOST_FILE": str(secret)}
    if fault == "legacy-env":
        environment["BACKUP_ENCRYPTION_PASSWORD"] = ""

    with pytest.raises(ValueError, match=message):
        validate_backup_secret_configuration(environment, services)
