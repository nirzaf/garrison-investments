from app.tasks.celery_app import celery_app


@celery_app.task(name="cleanup_old_notifications", queue="maintenance")
def cleanup_old_notifications() -> str:
    return "notification cleanup placeholder"


@celery_app.task(name="check_late_reports", queue="maintenance")
def check_late_reports() -> str:
    return "late report check placeholder"


@celery_app.task(name="check_low_stock", queue="maintenance")
def check_low_stock() -> str:
    return "low stock check placeholder"
