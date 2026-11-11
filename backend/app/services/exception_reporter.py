import asyncio
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import Request

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.audit_service import AuditService
from app.services.email_service import EmailService
from app.utils.redaction import redact_payload, redact_text
from app.utils.request import get_client_ip
from app.utils.security import decode_access_token

logger = structlog.get_logger("app.exception_reporter")


def _authenticated_subject(request: Request) -> str | None:
    authorization = request.headers.get("Authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        payload = decode_access_token(token)
    except Exception:
        return None
    subject = payload.get("sub")
    return str(subject) if subject else None


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


async def report_unhandled_exception(request: Request, exc: Exception) -> None:
    settings = get_settings()
    recipients = settings.exception_email_recipients_list
    if not settings.should_send_exception_emails or not recipients:
        return

    request_id = getattr(request.state, "request_id", None)
    exception_type = type(exc).__name__
    subject = (
        f"[{settings.app_env}] {settings.app_name} unhandled exception"
        f" {exception_type} {request.method} {request.url.path}"
    )
    body = "\n".join(
        [
            "Unhandled exception report",
            "",
            "Application",
            f"  Name: {settings.app_name}",
            f"  Environment: {settings.app_env}",
            f"  Timestamp UTC: {datetime.now(UTC).isoformat()}",
            "",
            "Request",
            f"  Request ID: {_format_value(request_id)}",
            f"  Method: {request.method}",
            f"  URL: {redact_text(str(request.url))}",
            f"  Path: {request.url.path}",
            f"  Query: {_format_value(redact_text(request.url.query) or None)}",
            f"  Client IP: {_format_value(get_client_ip(request))}",
            f"  User ID: {_format_value(_authenticated_subject(request))}",
            f"  User-Agent: {_format_value(request.headers.get('User-Agent'))}",
            "",
            "Headers",
            *[
                f"  {key}: {value}"
                for key, value in sorted(redact_payload(request.headers).items())
            ],
            "",
            "Exception",
            f"  Type: {exception_type}",
            f"  Message: {redact_text(str(exc))}",
            "",
            "Traceback",
            redact_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__))),
        ]
    )

    try:
        await asyncio.to_thread(
            EmailService().send,
            recipients=recipients,
            subject=subject,
            body=body,
        )
    except Exception:
        logger.exception(
            "exception_email_failed",
            request_id=request_id,
            path=request.url.path,
            exception_type=exception_type,
        )


def report_celery_task_failure(
    *,
    task_name: str | None,
    task_id: str | None,
    exc: BaseException,
    args: tuple[Any, ...] | None = None,
    kwargs: Mapping[str, Any] | None = None,
    traceback_text: str | None = None,
) -> None:
    asyncio.run(
        _store_celery_failure_event(
            task_name=task_name,
            task_id=task_id,
            exc=exc,
            args=args,
            kwargs=kwargs,
            traceback_text=traceback_text,
        )
    )

    settings = get_settings()
    recipients = settings.exception_email_recipients_list
    if not settings.should_send_exception_emails or not recipients:
        return

    exception_type = type(exc).__name__
    subject = (
        f"[{settings.app_env}] {settings.app_name} Celery task failed {task_name or 'unknown'}"
    )
    body = "\n".join(
        [
            "Celery task failure report",
            "",
            "Application",
            f"  Name: {settings.app_name}",
            f"  Environment: {settings.app_env}",
            f"  Timestamp UTC: {datetime.now(UTC).isoformat()}",
            "",
            "Task",
            f"  Name: {_format_value(task_name)}",
            f"  ID: {_format_value(task_id)}",
            f"  Args: {_format_value(redact_payload(args))}",
            f"  Kwargs: {_format_value(redact_payload(kwargs or {}))}",
            "",
            "Exception",
            f"  Type: {exception_type}",
            f"  Message: {redact_text(str(exc))}",
            "",
            "Traceback",
            redact_text(
                traceback_text
                or "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            ),
        ]
    )

    try:
        EmailService().send(recipients=recipients, subject=subject, body=body)
    except Exception:
        logger.exception(
            "celery_exception_email_failed",
            task_id=task_id,
            task_name=task_name,
            exception_type=exception_type,
        )


async def _store_celery_failure_event(
    *,
    task_name: str | None,
    task_id: str | None,
    exc: BaseException,
    args: tuple[Any, ...] | None,
    kwargs: Mapping[str, Any] | None,
    traceback_text: str | None,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            await AuditService(session).record(
                action="celery.task_failed",
                event_type="error",
                severity="ERROR",
                entity_type="task",
                comments=redact_text(str(exc)),
                context_payload={
                    "task_name": task_name,
                    "task_id": task_id,
                    "args": redact_payload(list(args or ())),
                    "kwargs": redact_payload(kwargs or {}),
                    "traceback": redact_text(traceback_text) if traceback_text else None,
                    "exception_type": type(exc).__name__,
                },
            )
            await session.commit()
    except Exception:
        logger.exception(
            "celery_failure_log_persist_failed",
            task_name=task_name,
            task_id=task_id,
            exception_type=type(exc).__name__,
        )
