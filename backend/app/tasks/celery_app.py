from __future__ import annotations

import structlog
from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging, task_failure, worker_ready

from app.config import get_settings
from app.observability import configure_logging
from app.services.exception_reporter import report_celery_task_failure
from app.utils.recovery_destination import is_recovery_issuance_enabled

settings = get_settings()


configure_logging(settings, source_service="celery")

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
        "app.tasks.outbox",
        "app.tasks.support_recovery",
    ],
)

celery_app.conf.task_default_queue = "maintenance"
celery_app.conf.timezone = "UTC"
celery_app.conf.task_track_started = True
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.worker_hijack_root_logger = False
celery_app.conf.beat_schedule = {
    "dispatch-task-outbox-every-minute": {
        "task": "dispatch_task_outbox",
        "schedule": 60,
    },
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
if is_recovery_issuance_enabled(settings):
    celery_app.conf.beat_schedule["dispatch-support-recovery-deliveries"] = {
        "task": "dispatch_support_recovery_deliveries",
        "schedule": 30,
    }
if settings.hr_reminder_window_days is not None:
    celery_app.conf.beat_schedule["check-hr-credential-expiry-daily"] = {
        "task": "check_hr_credential_expiry",
        "schedule": crontab(hour=4, minute=15),
    }
if settings.hr_service_request_sla_days is not None:
    celery_app.conf.beat_schedule["check-hr-service-request-sla-daily"] = {
        "task": "check_hr_service_request_sla",
        "schedule": crontab(hour=4, minute=30),
    }
if settings.hr_probation_review_reminder_days is not None:
    celery_app.conf.beat_schedule["check-hr-probation-review-daily"] = {
        "task": "check_hr_probation_reviews",
        "schedule": crontab(hour=4, minute=45),
    }
if settings.hr_scheduled_leave_policy_ids:
    celery_app.conf.beat_schedule["post-hr-leave-accruals-daily"] = {
        "task": "post_hr_leave_accruals",
        "schedule": crontab(hour=5, minute=15),
    }


@setup_logging.connect
def _configure_worker_logging(**_) -> None:
    # Celery's task formatter otherwise bypasses the JSON handler used by Loki queries.
    configure_logging(settings, source_service="celery", force=True)


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
