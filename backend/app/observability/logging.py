from __future__ import annotations

import logging
import re
import socket
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.typing import Processor

from app.config import Settings
from app.observability.context import log_context_dict

_configured = False
_standard_context: dict[str, str] = {}

_SENSITIVE_KEY_PARTS = {
    "authorization",
    "cookie",
    "credential",
    "jwt",
    "otp",
    "passphrase",
    "password",
    "private_key",
    "secret",
    "set_cookie",
    "token",
    "x_api_key",
}
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_URL_CREDENTIAL_PATTERN = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s:]+:[^@\s]+@")
_KEY_VALUE_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?P<prefix>(?:access[_-]?token|api[_-]?key|auth(?:orization)?|cookie|jwt|otp|"
    r"pass(?:word)?|secret|session|token)=)[^&\s\"']+"
)


def _inject_standard_fields(
    _: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    event_dict.setdefault("severity", event_dict.get("level", method_name).upper())
    event_dict.setdefault("event_type", event_dict.get("event_type", "system_event"))
    for key, value in _standard_context.items():
        event_dict.setdefault(key, value)
    for key, value in log_context_dict().items():
        event_dict.setdefault(key, value)
    return event_dict


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact_string(value: str) -> str:
    value = _BEARER_PATTERN.sub("Bearer [redacted]", value)
    value = _JWT_PATTERN.sub("[redacted-jwt]", value)
    value = _URL_CREDENTIAL_PATTERN.sub(r"\g<scheme>[redacted]@", value)
    return _KEY_VALUE_CREDENTIAL_PATTERN.sub(r"\g<prefix>[redacted]", value)


def _redact_value(value: Any, *, key: object | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return "[redacted]"
    if isinstance(value, MutableMapping):
        return {item_key: _redact_value(item, key=item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _redact_sensitive_fields(
    _: Any,
    __: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    return _redact_value(event_dict)


def configure_logging(
    settings: Settings,
    *,
    source_service: str | None = None,
    force: bool = False,
) -> None:
    global _configured
    if _configured and not force:
        return

    instance_id = settings.log_instance_id or socket.gethostname()
    service = source_service or settings.log_source_service
    _standard_context.clear()
    _standard_context.update(
        {
            "environment": settings.app_env,
            "service": service,
            "source_service": service,
            "instance_id": instance_id,
        }
    )

    shared_processors: list[Processor] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _inject_standard_fields,
        _redact_sensitive_fields,
        structlog.processors.EventRenamer("message"),
    ]
    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery"):
        named_logger = logging.getLogger(logger_name)
        named_logger.handlers.clear()
        named_logger.propagate = True
        named_logger.setLevel(settings.log_level)

    structlog.get_logger("app.observability").info(
        "logging_configured",
        event_type="system_event",
        source_service=service,
        instance_id=instance_id,
        configured_level=settings.log_level,
    )
    _configured = True
