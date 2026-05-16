from app.tasks.celery_app import celery_app


@celery_app.task(name="send_email_notification", queue="email")
def send_email_notification() -> str:
    return "email notification placeholder"
