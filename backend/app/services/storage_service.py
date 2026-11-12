import asyncio
from functools import lru_cache

import structlog
from minio import Minio

from app.config import Settings

logger = structlog.get_logger(__name__)


async def discard_new_uploads(client: Minio, bucket: str, object_keys: list[str]) -> None:
    for object_key in object_keys:
        try:
            await asyncio.to_thread(client.remove_object, bucket, object_key)
        except Exception as error:
            logger.warning("upload_cleanup_failed", error_type=type(error).__name__)


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
