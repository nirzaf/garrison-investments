from minio import Minio

from app.config import Settings


def minio_client(settings: Settings) -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
        region="us-east-1",
    )


def minio_signed_url_client(settings: Settings) -> Minio:
    return Minio(
        settings.minio_signed_url_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_signed_url_secure,
        region="us-east-1",
    )
