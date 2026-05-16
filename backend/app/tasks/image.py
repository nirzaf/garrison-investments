from app.tasks.celery_app import celery_app


@celery_app.task(name="generate_thumbnail", queue="image")
def generate_thumbnail() -> str:
    return "thumbnail placeholder"


@celery_app.task(name="compress_photo", queue="image")
def compress_photo() -> str:
    return "photo compression placeholder"
