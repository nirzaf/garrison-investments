from __future__ import annotations

import time
from typing import Any

import structlog
from celery import Task

from app.observability import bind_log_context, clear_log_context

logger = structlog.get_logger("celery.task")


class LoggedTask(Task):
    """Base Task that logs lifecycle events with timing for CLI inspection."""

    abstract = True
    _start_time: float | None = None

    def before_start(self, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self._start_time = time.monotonic()
        bind_log_context(source_service="celery", instance_id=None)
        logger.info(
            "task_started",
            task_name=self.name,
            task_id=task_id,
            queue=(self.request.delivery_info or {}).get("routing_key"),
            retry_count=self.request.retries,
        )

    def on_success(
        self,
        retval: Any,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        duration = _elapsed(self._start_time)
        try:
            logger.info(
                "task_succeeded",
                task_name=self.name,
                task_id=task_id,
                duration_ms=duration,
            )
        finally:
            clear_log_context()

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        duration = _elapsed(self._start_time)
        try:
            logger.error(
                "task_failed",
                task_name=self.name,
                task_id=task_id,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
                duration_ms=duration,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        finally:
            clear_log_context()

    def on_retry(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        duration = _elapsed(self._start_time)
        try:
            logger.warning(
                "task_retried",
                task_name=self.name,
                task_id=task_id,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
                retry_count=self.request.retries,
                max_retries=self.max_retries,
                duration_ms=duration,
            )
        finally:
            clear_log_context()


def _elapsed(start: float | None) -> float | None:
    if start is None:
        return None
    return round((time.monotonic() - start) * 1000, 1)
