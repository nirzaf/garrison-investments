from __future__ import annotations

import logging
import socket
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.typing import Processor

from app.config import Settings
from app.observability.context import log_context_dict
from app.utils.redaction import redact_payload

_configured = False
_standard_context: dict[str, str] = {}


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


def _redact_sensitive_fields(
    _: Any,
    __: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    try:
        return redact_payload(event_dict)
    except RecursionError:
        # The offending payload is exactly what defeated redaction, so it must not be emitted.
        return {
            "message": "log_redaction_failed",
            "severity": "ERROR",
            "event_type": "system_event",
            "logger": event_dict.get("logger"),
        }


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
    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "celery",
        "celery.task",
        "celery.redirected",
    ):
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
