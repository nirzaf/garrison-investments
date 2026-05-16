from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "construction_portal",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.email",
        "app.tasks.image",
        "app.tasks.report",
        "app.tasks.backup",
        "app.tasks.maintenance",
    ],
)

celery_app.conf.task_default_queue = "maintenance"
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {}
