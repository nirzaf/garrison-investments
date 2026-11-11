from functools import lru_cache

from minio import Minio

from app.config import Settings


def minio_client(settings: Settings) -> Minio:
    return _client(
        settings.minio_endpoint,
        settings.minio_root_user,
        settings.minio_root_password,
        settings.minio_secure,
    )


def minio_signed_url_client(settings: Settings) -> Minio:
    return _client(
        settings.minio_signed_url_endpoint,
        settings.minio_root_user,
        settings.minio_root_password,
        settings.minio_signed_url_secure,
    )


@lru_cache(maxsize=8)
def _client(endpoint: str, access_key: str, secret_key: str, secure: bool) -> Minio:
    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
        region="us-east-1",
    )
