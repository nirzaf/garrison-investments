from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
from release_config_contract import validate_pinned_service_environment  # noqa: E402


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
