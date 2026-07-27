import json
import logging

import structlog
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.observability.context import bind_log_context, clear_log_context
from app.observability.logging import configure_logging


def _configure(*, level: str = "INFO") -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        log_level=level,
        log_source_service="backend-api",
        log_instance_id="test-instance",
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
    assert record["service"] == "backend-api"
    assert record["instance_id"] == "test-instance"
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
        json.loads(line)
        for line in capfd.readouterr().err.splitlines()
        if line.startswith("{")
    ]
    completion = next(record for record in records if record.get("message") == "http_request_completed")
    assert completion["route"] == "/api/v1/"
    assert completion["status_code"] == 200
    assert completion["duration_ms"] >= 0
