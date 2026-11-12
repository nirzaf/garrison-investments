import json
import logging
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock

import pytest
import structlog
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.observability.context import bind_log_context, clear_log_context, log_context_dict
from app.observability.logging import configure_logging
from app.tasks.base import LoggedTask


def _configure(
    *,
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
) -> None:
    settings = Settings.model_validate(
        {
            "app_env": "production",
            "log_level": level,
            "log_source_service": "backend-api",
            "log_instance_id": "test-instance",
        }
    )
    configure_logging(settings, force=True)


def _last_record(stderr: str) -> dict:
    lines = [line for line in stderr.splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_structured_logging_emits_standard_fields_and_context(capfd) -> None:
    _configure()
    capfd.readouterr()
    bind_log_context(request_id="req-123", user_id="user-456")

    structlog.get_logger("app.test").info("request_finished", status_code=200)

    record = _last_record(capfd.readouterr().err)
    assert record["message"] == "request_finished"
    assert record["severity"] == "INFO"
    assert record["logger"] == "app.test"
    assert record["environment"] == "production"
    assert record["source_service"] == "backend-api"
    assert "service" not in record
    assert record["instance_id"] == "test-instance"
    assert record["timestamp"].endswith("Z")
    assert record["request_id"] == "req-123"
    assert record["user_id"] == "user-456"
    clear_log_context()


def test_structured_logging_redacts_nested_secrets_and_credentials(capfd) -> None:
    _configure()
    capfd.readouterr()

    structlog.get_logger("app.test").warning(
        "redaction_check",
        password="plain-secret",
        payload={"api_token": "nested-secret", "safe": "visible"},
        endpoint="postgresql://user:password@postgres/garrison",
        authorization_text="Bearer abc.def.ghi",
        file_url=(
            "https://store.example.invalid/portal-files/item?"
            "X-Amz-Credential=fixture-credential&X-Amz-Signature=fixture-signature"
        ),
    )

    output = capfd.readouterr().err
    record = _last_record(output)
    assert record["password"] == "[redacted]"
    assert record["payload"]["api_token"] == "[redacted]"
    assert record["payload"]["safe"] == "visible"
    assert record["endpoint"] == "postgresql://[redacted]@postgres/garrison"
    assert record["authorization_text"] == "[redacted]"
    assert "plain-secret" not in output
    assert "nested-secret" not in output
    assert "fixture-credential" not in output
    assert "fixture-signature" not in output


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authorization", "Basic dXNlcjpwYXNz"),
        ("cookie", "sessionid=leaked-cookie-value"),
        ("set_cookie", "refresh=leaked-refresh-value"),
        ("credential", "leaked-credential-value"),
        ("jwt", "leaked-jwt-value"),
        ("otp_code", "123456"),
        ("passphrase", "leaked-passphrase-value"),
        ("private_key_pem", "-----BEGIN PRIVATE KEY-----leaked"),
        ("client_secret", "leaked-secret-value"),
        ("refresh_token", "leaked-token-value"),
        ("x_api_key", "leaked-api-key-value"),
        ("X-API-Key", "leaked-header-key-value"),
    ],
)
def test_every_sensitive_key_class_is_redacted(capfd, field: str, value: str) -> None:
    _configure()
    capfd.readouterr()

    structlog.get_logger("app.test").warning("redaction_check", **{field: value})

    output = capfd.readouterr().err
    assert _last_record(output)[field] == "[redacted]"
    assert value not in output


@pytest.mark.parametrize(
    "value",
    [
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.leaked-signature-value",
        "callback?token=leaked-signature-value&page=2",
        "upstream said: Bearer leaked-signature-value",
        "postgresql://user:leaked-signature-value@postgres/garrison",
    ],
)
def test_credential_patterns_are_redacted_in_free_text(capfd, value: str) -> None:
    _configure()
    capfd.readouterr()

    structlog.get_logger("app.test").warning(
        "redaction_check",
        note=value,
        nested={"list": [value]},
    )

    output = capfd.readouterr().err
    assert "leaked-signature-value" not in output


def test_deeply_nested_payloads_are_truncated_instead_of_raising(capfd) -> None:
    _configure()
    capfd.readouterr()

    payload: dict = {"password": "leaked-deep-secret"}
    for _ in range(60):
        payload = {"level": payload}

    structlog.get_logger("app.test").warning("redaction_check", payload=payload)

    output = capfd.readouterr().err
    assert _last_record(output)["message"] == "redaction_check"
    assert "[redacted-depth-limit]" in output
    assert "leaked-deep-secret" not in output


def test_standard_library_logs_are_json_and_level_is_respected(capfd) -> None:
    _configure(level="INFO")
    capfd.readouterr()

    logging.getLogger("uvicorn.error").debug("hidden debug message")
    logging.getLogger("uvicorn.error").error("visible error")

    output = capfd.readouterr().err
    assert "hidden debug message" not in output
    record = _last_record(output)
    assert record["message"] == "visible error"
    assert record["severity"] == "ERROR"
    assert record["logger"] == "uvicorn.error"


def test_exception_traceback_is_structured_and_redacted(capfd) -> None:
    _configure()
    capfd.readouterr()

    try:
        raise RuntimeError("Bearer secret-access-token")
    except RuntimeError:
        structlog.get_logger("app.test").exception("operation_failed")

    output = capfd.readouterr().err
    record = _last_record(output)
    assert record["message"] == "operation_failed"
    assert record["severity"] == "ERROR"
    assert "RuntimeError" in record["exception"]
    assert "secret-access-token" not in output


def test_http_request_completion_contains_route_status_and_duration(capfd) -> None:
    _configure()
    capfd.readouterr()

    response = TestClient(create_app()).get("/api/v1/")

    assert response.status_code == 200
    records = [
        json.loads(line) for line in capfd.readouterr().err.splitlines() if line.startswith("{")
    ]
    completion = next(
        record for record in records if record.get("message") == "http_request_completed"
    )
    assert completion["route"] == "/api/v1/"
    assert completion["status_code"] == 200
    assert completion["duration_ms"] >= 0


def test_http_request_context_is_cleared_and_query_string_is_not_logged(capfd) -> None:
    _configure()
    capfd.readouterr()

    response = TestClient(create_app(), client=("127.0.0.1", 50000)).get(
        "/api/v1/?token=must-not-leak",
        headers={"X-Request-ID": "req-cleanup", "X-Session-ID": "session-cleanup"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-cleanup"
    output = capfd.readouterr().err
    completion = next(
        json.loads(line)
        for line in output.splitlines()
        if line.startswith("{") and '"message": "http_request_completed"' in line
    )
    assert completion["request_id"] == "req-cleanup"
    assert completion["session_id"] == "session-cleanup"
    assert completion["endpoint"] == "/api/v1/"
    assert "must-not-leak" not in output
    assert log_context_dict() == {}


def test_http_request_replaces_untrusted_or_malformed_correlation_ids() -> None:
    headers = {"X-Request-ID": "caller-supplied", "X-Session-ID": "caller-session"}
    untrusted = TestClient(create_app(), client=("198.51.100.10", 50000)).get(
        "/api/v1/", headers=headers
    )
    assert untrusted.headers["X-Request-ID"] != headers["X-Request-ID"]
    assert untrusted.headers["X-Session-ID"] == untrusted.headers["X-Request-ID"]

    trusted = TestClient(create_app(), client=("127.0.0.1", 50000)).get(
        "/api/v1/", headers={"X-Request-ID": "x" * 65, "X-Session-ID": "bad session"}
    )
    assert len(trusted.headers["X-Request-ID"]) == 36
    assert trusted.headers["X-Session-ID"] == trusted.headers["X-Request-ID"]


def test_healthcheck_completion_is_suppressed_by_default(capfd) -> None:
    _configure()
    capfd.readouterr()

    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    records = [
        json.loads(line) for line in capfd.readouterr().err.splitlines() if line.startswith("{")
    ]
    assert not any(record.get("message") == "http_request_completed" for record in records)
    assert log_context_dict() == {}


class _TestLoggedTask(LoggedTask):
    name = "tests.safe_task"

    @property
    def request(self):
        return SimpleNamespace(delivery_info={"routing_key": "maintenance"}, retries=2)


def test_celery_lifecycle_logs_context_without_args_or_results(monkeypatch) -> None:
    task = _TestLoggedTask()
    task_args = ("raw-password",)
    task_kwargs = {"authorization": "Bearer secret"}
    task_logger = Mock()
    monkeypatch.setattr("app.tasks.base.logger", task_logger)

    task.before_start("task-123", task_args, task_kwargs)
    task.on_success({"access_token": "secret"}, "task-123", task_args, task_kwargs)

    started = task_logger.info.call_args_list[0]
    succeeded = task_logger.info.call_args_list[1]
    assert started.args == ("task_started",)
    assert started.kwargs == {
        "task_name": "tests.safe_task",
        "task_id": "task-123",
        "queue": "maintenance",
        "retry_count": 2,
    }
    assert succeeded.args == ("task_succeeded",)
    assert succeeded.kwargs["task_name"] == "tests.safe_task"
    assert succeeded.kwargs["task_id"] == "task-123"
    assert "retval" not in succeeded.kwargs
    assert "args" not in started.kwargs
    assert "kwargs" not in started.kwargs
    assert log_context_dict() == {}
