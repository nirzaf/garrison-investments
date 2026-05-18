from urllib.parse import urlparse

from app.config import Settings
from app.services.storage_service import minio_client, minio_signed_url_client


def test_presigned_url_uses_public_minio_endpoint() -> None:
    settings = Settings(
        minio_endpoint="minio:9000",
        minio_public_endpoint="localhost:9000",
        minio_root_user="garrison_minio",
        minio_root_password="garrison_minio_password",
        minio_secure=False,
        minio_public_secure=False,
    )

    upload_client = minio_client(settings)
    signed_url_client = minio_signed_url_client(settings)

    assert upload_client._base_url.host == "minio:9000"
    assert signed_url_client._base_url.host == "localhost:9000"

    url = signed_url_client.presigned_get_object(
        settings.minio_bucket,
        "seed-photos/blockwork_day5_thumb.jpg",
    )

    parsed = urlparse(url)
    assert parsed.netloc == "localhost:9000"
    assert parsed.path == "/portal-files/seed-photos/blockwork_day5_thumb.jpg"
