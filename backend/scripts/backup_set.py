"""Capture and verify a database and its referenced objects as one encrypted backup set.

Run as `python -m scripts.backup_set` from the backend environment.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.config import get_settings
from app.models.document import DocumentVersion
from app.models.finance import Invoice
from app.models.photo import Photo
from app.models.report_export import ReportExport
from app.models.supplier import Supplier
from app.services.photo_service import PHOTO_RECOVERY_DAYS
from app.services.storage_service import minio_client
from scripts.backup import create_dump, encrypt_file
from scripts.restore_dry_run import inspect_backup, restore_backup, sha256_file

MANIFEST = "manifest.json"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
HEX_SHA256 = r"^[a-f0-9]{64}$"


class BackupSetError(Exception):
    pass


class Artifact(BaseModel):
    file: str
    sha256: str = Field(pattern=HEX_SHA256)
    size_bytes: int = Field(ge=1)


class StoredObject(BaseModel):
    key: str = Field(min_length=1)
    version_id: str | None = None
    content_type: str
    sha256: str = Field(pattern=HEX_SHA256)
    size_bytes: int = Field(ge=0)
    encrypted: Artifact


class Manifest(BaseModel):
    format_version: Literal[1] = 1
    source_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    alembic_heads: list[str] = Field(min_length=1)
    captured_from: datetime
    captured_to: datetime
    consistency_note: str = Field(min_length=1)
    source_database: str
    source_grafana_database: str | None = None
    source_bucket: str
    application_dump: Artifact
    grafana_dump: Artifact | None = None
    objects: list[StoredObject]


def database_identity(url: str) -> str:
    parsed = make_url(url)
    host = "127.0.0.1" if parsed.host in LOOPBACK else parsed.host
    return f"{host}:{parsed.port or 5432}/{parsed.database}"


def require_disposable_database(url: str, source: str | None) -> None:
    parsed = make_url(url)
    if parsed.drivername not in {"postgresql", "postgresql+asyncpg"} or (
        parsed.host not in LOOPBACK
        or not (parsed.database or "").startswith("garrison_restore_test_")
        or parsed.query
        or database_identity(url) == source
    ):
        raise BackupSetError(
            "Restore requires a separate, explicitly named loopback test database."
        )


def require_disposable_bucket(endpoint: str, bucket: str, source_bucket: str) -> None:
    parsed = urlsplit(f"//{endpoint}")
    if (
        parsed.hostname not in LOOPBACK
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not bucket.startswith("garrison-restore-test-")
        or bucket == source_bucket
    ):
        raise BackupSetError("Restore requires a separate, explicitly named loopback test bucket.")


def async_database_url(url: str):
    return make_url(url).set(drivername="postgresql+asyncpg")


async def references(connection: AsyncConnection, as_of: datetime) -> set[str]:
    photo_cutoff = as_of - timedelta(days=PHOTO_RECOVERY_DAYS)
    photos = await connection.execute(
        select(Photo.storage_path, Photo.compressed_path, Photo.thumbnail_path).where(
            or_(Photo.deleted_at.is_(None), Photo.deleted_at >= photo_cutoff)
        )
    )
    keys = {key for row in photos for key in row if key}
    for query in (
        select(DocumentVersion.storage_path).where(DocumentVersion.deleted_at.is_(None)),
        select(Invoice.attachment_key).where(Invoice.deleted_at.is_(None)),
        select(Supplier.tds_document_key).where(Supplier.deleted_at.is_(None)),
        select(ReportExport.object_key).where(
            ReportExport.deleted_at.is_(None), ReportExport.status == "ready"
        ),
    ):
        keys.update(key for key in await connection.scalars(query) if key)
    return keys


async def schema_heads(connection: AsyncConnection) -> list[str]:
    return sorted(await connection.scalars(text("SELECT version_num FROM alembic_version")))


async def dump_application(
    database_url: str, dump: Path, as_of: datetime
) -> tuple[list[str], set[str]]:
    engine = create_async_engine(async_database_url(database_url))
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            snapshot = await connection.scalar(text("SELECT pg_export_snapshot()"))
            heads = await schema_heads(connection)
            keys = await references(connection, as_of)
            await asyncio.to_thread(create_dump, database_url, dump, snapshot=str(snapshot))
            return heads, keys
    finally:
        await engine.dispose()


def checksum(path: Path) -> Artifact:
    return Artifact(file=path.name, sha256=sha256_file(path), size_bytes=path.stat().st_size)


def write_encrypted(path: Path, destination: Path, password: str) -> Artifact:
    encrypted = encrypt_file(path, password)
    target = destination / encrypted.name
    shutil.move(encrypted, target)
    return checksum(target)


def download_object(
    client: Minio, bucket: str, key: str, target: Path, version_id: str | None
) -> None:
    response = client.get_object(bucket, key, version_id=version_id)
    try:
        with target.open("wb") as output:
            shutil.copyfileobj(response, output)
    finally:
        response.close()
        response.release_conn()


def capture_object(
    client: Minio, bucket: str, key: str, temporary: Path, destination: Path, password: str
) -> StoredObject:
    try:
        info = client.stat_object(bucket, key)
        version_id = info.version_id if info.version_id not in {"", "null"} else None
        path = temporary / f"object-{hashlib.sha256(key.encode()).hexdigest()}"
        download_object(client, bucket, key, path, version_id)
    except S3Error as error:
        if error.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket", "NoSuchVersion"}:
            raise BackupSetError(
                "A referenced object is missing from the source capture."
            ) from None
        raise
    if path.stat().st_size != info.size:
        raise BackupSetError("A source object changed during capture. Check write quiescence.")
    if version_id is None and client.stat_object(bucket, key).etag != info.etag:
        raise BackupSetError("A source object changed during capture. Check write quiescence.")
    size = path.stat().st_size
    digest = sha256_file(path)
    return StoredObject(
        key=key,
        version_id=version_id,
        content_type=info.content_type or "application/octet-stream",
        sha256=digest,
        size_bytes=size,
        encrypted=write_encrypted(path, destination, password),
    )


async def capture(args: argparse.Namespace, password: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{40}", args.source_sha) or not args.consistency_note.strip():
        raise BackupSetError(
            "Provide the full release SHA and the recorded write-quiescence window."
        )
    settings = get_settings()
    source = minio_client(settings)
    destination = args.destination.expanduser().resolve()
    destination.mkdir(mode=0o700)
    start = datetime.now(UTC)
    grafana_url = os.getenv("BACKUP_GRAFANA_DATABASE_URL")
    with TemporaryDirectory(prefix="garrison-backup-") as temp:
        temporary = Path(temp)
        app_dump = temporary / "application.sql.gz"
        heads, keys = await dump_application(settings.database_url, app_dump, start)
        encrypted_app = write_encrypted(app_dump, destination, password)
        encrypted_grafana = None
        if grafana_url:
            grafana_dump = temporary / "grafana.sql.gz"
            create_dump(grafana_url, grafana_dump)
            encrypted_grafana = write_encrypted(grafana_dump, destination, password)
        if args.extra_objects:
            keys.update(
                key for key in args.extra_objects.read_text(encoding="utf-8").splitlines() if key
            )
        objects = [
            capture_object(source, settings.minio_bucket, key, temporary, destination, password)
            for key in sorted(keys)
        ]
    manifest = Manifest(
        source_sha=args.source_sha,
        alembic_heads=heads,
        captured_from=start,
        captured_to=datetime.now(UTC),
        consistency_note=args.consistency_note.strip(),
        source_database=database_identity(settings.database_url),
        source_grafana_database=database_identity(grafana_url) if grafana_url else None,
        source_bucket=settings.minio_bucket,
        application_dump=encrypted_app,
        grafana_dump=encrypted_grafana,
        objects=objects,
    )
    pending = destination / "manifest.pending"
    pending.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    pending.rename(destination / MANIFEST)
    print(f"Captured {len(objects)} referenced objects with the database backup set.")


def load_verified_manifest(source: Path) -> Manifest:
    source = source.resolve()
    manifest_path = source / MANIFEST
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise BackupSetError("No complete backup-set manifest was found.")
    manifest = Manifest.model_validate_json(manifest_path.read_bytes())
    artifacts = [manifest.application_dump, *(item.encrypted for item in manifest.objects)]
    if manifest.grafana_dump:
        artifacts.append(manifest.grafana_dump)
    if len({item.key for item in manifest.objects}) != len(manifest.objects) or (
        len({item.file for item in artifacts}) != len(artifacts)
    ):
        raise BackupSetError("Backup manifest contains duplicate objects or artifacts.")
    for artifact in artifacts:
        if not re.fullmatch(
            r"(application\.sql\.gz|grafana\.sql\.gz|object-[a-f0-9]{64})\.enc", artifact.file
        ):
            raise BackupSetError("Backup manifest contains an invalid artifact path.")
        path = source / artifact.file
        if path.is_symlink() or not path.is_file():
            raise BackupSetError("A backup artifact is missing or is a symbolic link.")
        if path.stat().st_size != artifact.size_bytes or sha256_file(path) != artifact.sha256:
            raise BackupSetError("A backup artifact failed the size or SHA-256 check.")
    if manifest.application_dump.file != "application.sql.gz.enc" or (
        manifest.grafana_dump and manifest.grafana_dump.file != "grafana.sql.gz.enc"
    ):
        raise BackupSetError("The manifest's database artifact types do not match.")
    return manifest


def decrypt(source: Path, artifact: Artifact, destination: Path, password: str) -> Path:
    path = destination / artifact.file.removesuffix(".enc")
    try:
        subprocess.run(
            [
                "openssl",
                "enc",
                "-d",
                "-aes-256-cbc",
                "-pbkdf2",
                "-in",
                str(source / artifact.file),
                "-out",
                str(path),
                "-pass",
                "env:BACKUP_ENCRYPTION_PASSWORD",
            ],
            check=True,
            env={**os.environ, "BACKUP_ENCRYPTION_PASSWORD": password},
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        raise BackupSetError(
            "An artifact could not be decrypted with the supplied backup key."
        ) from None
    return path


async def check_empty_database(url: str) -> None:
    engine = create_async_engine(async_database_url(url))
    try:
        async with engine.connect() as connection:
            existing = await connection.scalar(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            )
            if existing:
                raise BackupSetError("The restore database already contains tables.")
    finally:
        await engine.dispose()


async def verify_database(url: str, manifest: Manifest) -> None:
    engine = create_async_engine(async_database_url(url))
    try:
        async with engine.connect() as connection:
            if await schema_heads(connection) != sorted(manifest.alembic_heads):
                raise BackupSetError("The restored database schema differs from the manifest.")
            if not (await references(connection, manifest.captured_from)) <= {
                item.key for item in manifest.objects
            }:
                raise BackupSetError(
                    "The restored database references objects outside the backup set."
                )
    finally:
        await engine.dispose()


async def restore(source: Path, manifest: Manifest, password: str) -> None:
    database_url = os.environ["RESTORE_DATABASE_URL"]
    grafana_url = os.getenv("RESTORE_GRAFANA_DATABASE_URL")
    endpoint = os.environ["RESTORE_OBJECT_ENDPOINT"]
    bucket = os.environ["RESTORE_OBJECT_BUCKET"]
    require_disposable_database(database_url, manifest.source_database)
    require_disposable_bucket(endpoint, bucket, manifest.source_bucket)
    if bool(grafana_url) != bool(manifest.grafana_dump):
        raise BackupSetError(
            "The Grafana backup and its separate restore database must be provided together."
        )
    if grafana_url:
        require_disposable_database(grafana_url, manifest.source_grafana_database)
        if database_identity(grafana_url) in {
            database_identity(database_url),
            manifest.source_database,
        }:
            raise BackupSetError(
                "The Grafana restore database must be distinct from the application databases."
            )
        await check_empty_database(grafana_url)
    if manifest.source_grafana_database == database_identity(database_url):
        raise BackupSetError("The application restore database matches the Grafana source.")
    await check_empty_database(database_url)
    target = Minio(
        endpoint,
        access_key=os.environ["RESTORE_OBJECT_ACCESS_KEY"],
        secret_key=os.environ["RESTORE_OBJECT_SECRET_KEY"],
        secure=False,
        region="us-east-1",
    )
    if target.bucket_exists(bucket):
        raise BackupSetError("The restore bucket must be new.")
    with TemporaryDirectory(prefix="garrison-restore-") as temp:
        temporary = Path(temp)
        app_dump = decrypt(source, manifest.application_dump, temporary, password)
        inspect_backup(app_dump)
        grafana_dump = None
        if manifest.grafana_dump:
            grafana_dump = decrypt(source, manifest.grafana_dump, temporary, password)
            inspect_backup(grafana_dump)
        files = []
        for item in manifest.objects:
            path = decrypt(source, item.encrypted, temporary, password)
            if path.stat().st_size != item.size_bytes or sha256_file(path) != item.sha256:
                raise BackupSetError("Decrypted bytes differ from the object manifest.")
            files.append((item, path))

        restore_backup(app_dump, database_url, quiet=True)
        if grafana_url and grafana_dump:
            restore_backup(grafana_dump, grafana_url, quiet=True)
        await verify_database(database_url, manifest)
        target.make_bucket(bucket)
        verification_file = temporary / "verify-object"
        for item, path in files:
            target.fput_object(bucket, item.key, str(path), content_type=item.content_type)
            download_object(target, bucket, item.key, verification_file, None)
            if (
                verification_file.stat().st_size != item.size_bytes
                or sha256_file(verification_file) != item.sha256
            ):
                raise BackupSetError("The restored object failed the size or SHA-256 check.")
    print(f"Restored the backup set and verified {len(manifest.objects)} object checksums.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    capture_args = subcommands.add_parser("capture")
    capture_args.add_argument("--destination", type=Path, required=True)
    capture_args.add_argument("--source-sha", required=True)
    capture_args.add_argument("--consistency-note", required=True)
    capture_args.add_argument("--extra-objects", type=Path)
    for command in ("verify", "restore"):
        subcommands.add_parser(command).add_argument("source", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "verify":
            manifest = load_verified_manifest(args.source)
            print(f"Verified encrypted artifacts for {len(manifest.objects)} objects.")
            return
        password = os.getenv("BACKUP_ENCRYPTION_PASSWORD")
        if not password:
            raise BackupSetError("BACKUP_ENCRYPTION_PASSWORD is required.")
        if args.command == "capture":
            asyncio.run(capture(args, password))
        else:
            source = args.source.resolve()
            asyncio.run(restore(source, load_verified_manifest(source), password))
    except BackupSetError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit(f"Backup-set operation failed ({type(error).__name__}).") from None


if __name__ == "__main__":
    main()
