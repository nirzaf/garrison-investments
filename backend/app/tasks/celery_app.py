from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "construction_portal",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.approval",
        "app.tasks.email",
        "app.tasks.image",
        "app.tasks.report",
        "app.tasks.backup",
        "app.tasks.maintenance",
    ],
)

celery_app.conf.task_default_queue = "maintenance"
celery_app.conf.timezone = "UTC"
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
}
