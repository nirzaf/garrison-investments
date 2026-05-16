from app.tasks.celery_app import celery_app


@celery_app.task(name="generate_thumbnail", queue="image")
def generate_thumbnail(photo_id: str) -> str:
    return f"thumbnail ready for {photo_id}"


@celery_app.task(name="compress_photo", queue="image")
def compress_photo(photo_id: str) -> str:
    return f"compressed photo ready for {photo_id}"
