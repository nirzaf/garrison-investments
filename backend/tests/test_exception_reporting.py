from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.exception_reporter import report_celery_task_failure


class FakeExceptionSettings:
    app_name = "Construction Internal Portal"
    app_env = "staging"
    should_send_exception_emails = True
    exception_email_recipients_list = ["ops@example.test", "quadrate.lk@gmail.com"]


def test_unhandled_exception_sends_configured_email_with_debug_context(monkeypatch) -> None:
    sent: dict[str, object] = {}

    class FakeEmailService:
        def send(self, *, recipients: list[str], subject: str, body: str) -> int:
            sent["recipients"] = recipients
            sent["subject"] = subject
            sent["body"] = body
            return len(recipients)

    monkeypatch.setattr(
        "app.services.exception_reporter.get_settings",
        lambda: FakeExceptionSettings(),
    )
    monkeypatch.setattr("app.services.exception_reporter.EmailService", FakeEmailService)

    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database connection exploded")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/boom?project_id=123",
        headers={
            "Authorization": "Bearer secret-token",
            "User-Agent": "pytest-client",
            "X-Request-ID": "req-test-123",
        },
    )

    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_SERVER_ERROR"
    assert sent["recipients"] == ["ops@example.test", "quadrate.lk@gmail.com"]
    assert "[staging]" in str(sent["subject"])
    body = str(sent["body"])
    assert "RuntimeError" in body
    assert "database connection exploded" in body
    assert "GET" in body
    assert "/boom" in body
    assert "project_id=123" in body
    assert "req-test-123" in body
    assert "authorization: [redacted]" in body
    assert "secret-token" not in body


def test_unhandled_exception_email_respects_disabled_config(monkeypatch) -> None:
    class DisabledSettings(FakeExceptionSettings):
        should_send_exception_emails = False

    sent = False

    class FakeEmailService:
        def send(self, *, recipients: list[str], subject: str, body: str) -> int:
            nonlocal sent
            del recipients, subject, body
            sent = True
            return 1

    monkeypatch.setattr(
        "app.services.exception_reporter.get_settings",
        lambda: DisabledSettings(),
    )
    monkeypatch.setattr("app.services.exception_reporter.EmailService", FakeEmailService)

    app = FastAPI()

    @app.exception_handler(Exception)
    async def handler(request, exc):
        from app.services.exception_reporter import report_unhandled_exception

        await report_unhandled_exception(request, exc)
        raise exc

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("disabled")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 500
    assert sent is False


def test_celery_task_failure_sends_configured_email(monkeypatch) -> None:
    sent: dict[str, object] = {}

    class FakeEmailService:
        def send(self, *, recipients: list[str], subject: str, body: str) -> int:
            sent["recipients"] = recipients
            sent["subject"] = subject
            sent["body"] = body
            return len(recipients)

    monkeypatch.setattr(
        "app.services.exception_reporter.get_settings",
        lambda: FakeExceptionSettings(),
    )
    monkeypatch.setattr("app.services.exception_reporter.EmailService", FakeEmailService)

    report_celery_task_failure(
        task_name="run_import_async",
        task_id="task-123",
        exc=RuntimeError("worker exploded"),
        args=("materials",),
        kwargs={"token": "secret-token", "batch_id": "batch-1"},
        traceback_text="Traceback text",
    )

    assert sent["recipients"] == ["ops@example.test", "quadrate.lk@gmail.com"]
    assert "Celery task failed" in str(sent["subject"])
    body = str(sent["body"])
    assert "run_import_async" in body
    assert "task-123" in body
    assert "worker exploded" in body
    assert "Traceback text" in body
    assert "'token': '[redacted]'" in body
    assert "secret-token" not in body
