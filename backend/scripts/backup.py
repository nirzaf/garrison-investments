from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from minio import Minio


def normalize_pg_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return database_url


def create_dump(database_url: str, output_path: Path) -> None:
    with output_path.open("wb") as raw_file:
        with gzip.GzipFile(fileobj=raw_file, mode="wb") as gzip_file:
            subprocess.run(
                ["pg_dump", "--format=plain", "--no-owner", normalize_pg_url(database_url)],
                check=True,
                stdout=gzip_file,
            )


def encrypt_file(input_path: Path, password: str) -> Path:
    encrypted_path = input_path.with_suffix(input_path.suffix + ".enc")
    subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-salt",
            "-pbkdf2",
            "-in",
            str(input_path),
            "-out",
            str(encrypted_path),
            "-pass",
            f"pass:{password}",
        ],
        check=True,
    )
    input_path.unlink()
    return encrypted_path


def get_minio_client() -> Minio:
    endpoint = os.environ["MINIO_ENDPOINT"]
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
    return Minio(
        endpoint,
        access_key=os.environ["MINIO_ROOT_USER"],
        secret_key=os.environ["MINIO_ROOT_PASSWORD"],
        secure=secure,
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_backup(client: Minio, bucket: str, object_name: str, path: Path) -> None:
    client.fput_object(bucket, object_name, str(path))


def cleanup_retention(client: Minio, bucket: str, prefix: str, retention_days: int) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    for item in client.list_objects(bucket, prefix=prefix, recursive=True):
        if item.last_modified and item.last_modified < cutoff:
            client.remove_object(bucket, item.object_name)


def monthly_retention_days(months: int) -> int:
    return months * 31


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    host_part = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit(
        (parts.scheme, f"***:***@{host_part}", parts.path, parts.query, parts.fragment)
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create encrypted PostgreSQL backups in MinIO.")
    parser.add_argument("--monthly", action="store_true", help="Store backup under monthly prefix.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = os.environ["DATABASE_URL"]
    bucket = os.getenv("MINIO_BUCKET", "portal-files")
    local_dir = Path(os.getenv("BACKUP_LOCAL_DIR", "/tmp/garrison-backups"))
    local_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = local_dir / f"garrison-{timestamp}.sql.gz"
    create_dump(database_url, backup_path)

    encryption_password = os.getenv("BACKUP_ENCRYPTION_PASSWORD")
    if encryption_password:
        backup_path = encrypt_file(backup_path, encryption_password)

    prefix = "backups/monthly" if args.monthly else "backups/daily"
    object_name = f"{prefix}/{backup_path.name}"
    client = get_minio_client()
    ensure_bucket(client, bucket)
    upload_backup(client, bucket, object_name, backup_path)

    retention_days = (
        monthly_retention_days(int(os.getenv("MONTHLY_BACKUP_RETENTION_MONTHS", "12")))
        if args.monthly
        else int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
    )
    cleanup_retention(client, bucket, prefix, retention_days)
    shutil.rmtree(local_dir, ignore_errors=True)
    print(f"Uploaded backup {object_name} from {redact_url(database_url)}")


if __name__ == "__main__":
    main()
