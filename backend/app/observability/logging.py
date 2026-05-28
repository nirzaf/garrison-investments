from __future__ import annotations

import logging
import socket
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.config import Settings
from app.observability.context import log_context_dict

_configured = False


def _inject_standard_fields(
    _: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    event_dict.setdefault("severity", event_dict.get("level", method_name).upper())
    event_dict.setdefault("event_type", event_dict.get("event_type", "system_event"))
    for key, value in log_context_dict().items():
        event_dict.setdefault(key, value)
    return event_dict


def configure_logging(settings: Settings) -> None:
    global _configured
    if _configured:
        return

    instance_id = settings.log_instance_id or socket.gethostname()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            _inject_standard_fields,
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    structlog.get_logger("app.observability").info(
        "logging_configured",
        event_type="system_event",
        source_service=settings.log_source_service,
        instance_id=instance_id,
    )
    _configured = True
