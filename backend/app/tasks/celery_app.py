from __future__ import annotations

import logging
import socket

import structlog
from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure, worker_ready

from app.config import get_settings
from app.services.exception_reporter import report_celery_task_failure

settings = get_settings()


def _configure_celery_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.processors.CallsiteParameterAdder(
                [structlog.processors.CallsiteParameter.FILENAME,
                 structlog.processors.CallsiteParameter.FUNC_NAME,
                 structlog.processors.CallsiteParameter.LINENO]
            ),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=False),
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in ("celery", "celery.app", "celery.worker", "celery.task"):
        logging.getLogger(name).setLevel(logging.INFO)


_configure_celery_logging()

_logger = structlog.get_logger("celery.app")

celery_app = Celery(
    "construction_portal",
    broker=settings.redis_url,
    backend=settings.redis_url,
    task_cls="app.tasks.base.LoggedTask",
    include=[
        "app.tasks.approval",
        "app.tasks.email",
        "app.tasks.image",
        "app.tasks.report",
        "app.tasks.backup",
        "app.tasks.maintenance",
        "app.tasks.imports",
    ],
)

celery_app.conf.task_default_queue = "maintenance"
celery_app.conf.timezone = "UTC"
celery_app.conf.task_track_started = True
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.beat_schedule = {
    "run-database-backup-daily": {
        "task": "run_database_backup",
        "schedule": crontab(hour=1, minute=0),
        "args": (False,),
    },
    "run-database-backup-monthly": {
        "task": "run_database_backup",
        "schedule": crontab(day_of_month=1, hour=2, minute=0),
        "args": (True,),
    },
    "check-late-reports-hourly": {
        "task": "check_late_reports",
        "schedule": 3600,
    },
    "process-approval-reminders-hourly": {
        "task": "process_approval_reminders",
        "schedule": 3600,
    },
    "check-low-stock-hourly": {
        "task": "check_low_stock",
        "schedule": 3600,
    },
    "cleanup-old-notifications-daily": {
        "task": "cleanup_old_notifications",
        "schedule": crontab(hour=3, minute=0),
    },
    "archive-and-purge-logs-daily": {
        "task": "archive_and_purge_logs",
        "schedule": crontab(hour=3, minute=30),
    },
    "check-supplier-tds-expiry-daily": {
        "task": "check_supplier_tds_expiry",
        "schedule": crontab(hour=4, minute=0),
    },
}


@worker_ready.connect
def _on_worker_ready(sender, **_):
    _logger.info(
        "worker_ready",
        worker_hostname=getattr(sender, "hostname", "unknown"),
    )


@task_failure.connect
def report_failed_task(
    sender=None,
    task_id=None,
    exception=None,
    args=None,
    kwargs=None,
    einfo=None,
    **_,
) -> None:
    if exception is None:
        return
    report_celery_task_failure(
        task_name=getattr(sender, "name", None),
        task_id=task_id,
        exc=exception,
        args=args,
        kwargs=kwargs,
        traceback_text=str(einfo) if einfo else None,
    )
