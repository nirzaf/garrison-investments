from __future__ import annotations

import logging
import time
from typing import Any

import structlog
from celery import Task

logger = structlog.get_logger("celery.task")


class LoggedTask(Task):
    """Base Task that logs lifecycle events with timing for CLI inspection."""

    abstract = True
    _start_time: float | None = None

    def before_start(self, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self._start_time = time.monotonic()
        logger.info(
            "task_started",
            task_name=self.name,
            task_id=task_id,
            args=_safe_repr(args),
            kwargs=_safe_repr(kwargs),
        )

    def on_success(self, retval: Any, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        duration = _elapsed(self._start_time)
        logger.info(
            "task_succeeded",
            task_name=self.name,
            task_id=task_id,
            result=_safe_repr(retval),
            duration_ms=duration,
        )

    def on_failure(self, exc: BaseException, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any], einfo: Any) -> None:
        duration = _elapsed(self._start_time)
        logger.error(
            "task_failed",
            task_name=self.name,
            task_id=task_id,
            exception=type(exc).__name__,
            error=str(exc),
            duration_ms=duration,
        )

    def on_retry(self, exc: BaseException, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any], einfo: Any) -> None:
        duration = _elapsed(self._start_time)
        logger.warning(
            "task_retried",
            task_name=self.name,
            task_id=task_id,
            exception=type(exc).__name__,
            error=str(exc),
            retry_request=self.request.retries,
            max_retries=self.max_retries,
            duration_ms=duration,
        )


def _safe_repr(obj: Any, max_len: int = 200) -> str:
    try:
        r = repr(obj)
    except Exception:
        r = "<unrepresentable>"
    return r[:max_len] + "..." if len(r) > max_len else r


def _elapsed(start: float | None) -> float | None:
    if start is None:
        return None
    return round((time.monotonic() - start) * 1000, 1)
