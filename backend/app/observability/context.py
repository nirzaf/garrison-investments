from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LogContext:
    request_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    ip_address: str | None = None
    endpoint: str | None = None
    method: str | None = None
    source_service: str | None = None
    instance_id: str | None = None
    cli_session_id: str | None = None


_log_context: ContextVar[LogContext] = ContextVar("log_context", default=LogContext())


def get_log_context() -> LogContext:
    return _log_context.get()


def bind_log_context(**values: str | None) -> None:
    current = asdict(get_log_context())
    current.update(values)
    _log_context.set(LogContext(**current))


def clear_log_context() -> None:
    _log_context.set(LogContext())


def log_context_dict() -> dict[str, Any]:
    return {key: value for key, value in asdict(get_log_context()).items() if value is not None}
