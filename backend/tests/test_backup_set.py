import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from scripts import backup
from scripts.backup_set import (
    MANIFEST,
    BackupSetError,
    Manifest,
    StoredObject,
    check_empty_database,
    checksum,
    load_verified_manifest,
    require_disposable_bucket,
    require_disposable_database,
)


@pytest.mark.parametrize(("flags", "cleanup_calls"), [([], 2), (["--skip-retention"], 0)])
def test_backup_retention_can_be_skipped_for_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flags: list[str], cleanup_calls: int
) -> None:
    monkeypatch.setattr(sys, "argv", ["backup.py", "--target", "all", *flags])
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic@127.0.0.1/disposable")
    monkeypatch.setenv("GRAFANA_DB_PASSWORD", "synthetic")
    monkeypatch.setenv("BACKUP_ENCRYPTION_PASSWORD", "synthetic")
    monkeypatch.setenv("BACKUP_LOCAL_DIR", str(tmp_path))
    monkeypatch.setenv("MINIO_BUCKET", "disposable-backups")
    client = Mock()
    cleanup = Mock()
    monkeypatch.setattr(backup, "get_minio_client", lambda: client)
    monkeypatch.setattr(backup, "create_dump", Mock())
    monkeypatch.setattr(backup, "encrypt_file", lambda path, password: path.with_suffix(".enc"))
    monkeypatch.setattr(backup, "cleanup_retention", cleanup)

    backup.main()

    assert client.fput_object.call_count == 2
    assert cleanup.call_count == cleanup_calls


@pytest.mark.parametrize(
    "destination",
    (
        "postgresql+asyncpg://db.example.invalid/garrison_restore_test_app",
        "postgresql+asyncpg://127.0.0.1/garrison_portal",
        "postgresql+asyncpg://127.0.0.1/garrison_restore_test_source",
        "postgresql+asyncpg://localhost/garrison_restore_test_source",
        "postgresql+asyncpg://127.0.0.1/garrison_restore_test_app?host=db.example.invalid",
    ),
)
def test_restore_database_guard_rejects_shared_or_external_targets(destination: str) -> None:
    with pytest.raises(BackupSetError, match="separate"):
        require_disposable_database(destination, "127.0.0.1:5432/garrison_restore_test_source")
    require_disposable_database(
        "postgresql+asyncpg://127.0.0.1/garrison_restore_test_app",
        "127.0.0.1:5432/garrison_restore_test_source",
    )


async def test_restore_preflight_rejects_objects_in_any_schema() -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        settings.app_env.lower() not in {"test", "development", "local"}
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.skip("restore preflight regression requires local test PostgreSQL")
    database = f"garrison_restore_test_{uuid4().hex}"
    target_url = url.set(database=database)
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    target = create_async_engine(target_url)
    try:
        try:
            async with admin.connect() as connection:
                can_create = await connection.scalar(
                    text(
                        "SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user"
                    )
                )
        except (OSError, OperationalError):
            pytest.skip("local PostgreSQL is unavailable")
        if not can_create:
            pytest.skip("restore preflight fixture requires a database-creation role")

        async with admin.connect() as connection:
            await connection.execute(text(f"CREATE DATABASE {database} TEMPLATE template0"))
        try:
            target_dsn = target_url.render_as_string(hide_password=False)
            await check_empty_database(target_dsn)
            async with target.begin() as connection:
                await connection.execute(text("CREATE SEQUENCE public.restore_probe"))
            with pytest.raises(BackupSetError, match="already contains"):
                await check_empty_database(target_dsn)

            async with target.begin() as connection:
                await connection.execute(text("DROP SEQUENCE public.restore_probe"))
                await connection.execute(text("CREATE SCHEMA preserved"))
                await connection.execute(text("CREATE TABLE preserved.evidence (value integer)"))
                await connection.execute(text("INSERT INTO preserved.evidence VALUES (42)"))
            with pytest.raises(BackupSetError, match="already contains"):
                await check_empty_database(target_dsn)
            async with target.connect() as connection:
                assert await connection.scalar(text("SELECT value FROM preserved.evidence")) == 42
        finally:
            await target.dispose()
            async with admin.connect() as connection:
                await connection.execute(text(f"DROP DATABASE {database}"))
    finally:
        await admin.dispose()


@pytest.mark.parametrize(
    ("endpoint", "bucket"),
    (
        ("store.example.invalid", "garrison-restore-test-local"),
        ("127.0.0.1:9000", "portal-files"),
        ("127.0.0.1:9000", "garrison-restore-test-source"),
        ("127.0.0.1:9000/path", "garrison-restore-test-local"),
    ),
)
def test_restore_bucket_guard_rejects_shared_or_external_targets(
    endpoint: str, bucket: str
) -> None:
    with pytest.raises(BackupSetError, match="separate"):
        require_disposable_bucket(endpoint, bucket, "garrison-restore-test-source")
    require_disposable_bucket("127.0.0.1:9000", "garrison-restore-test-local", "portal-files")


def test_missing_corrupt_and_unsafe_manifest_artifacts_fail(tmp_path) -> None:
    app = tmp_path / "application.sql.gz.enc"
    app.write_bytes(b"synthetic dump")
    payload = tmp_path / ("object-" + "a" * 64 + ".enc")
    payload.write_bytes(b"synthetic encrypted object")
    now = datetime.now(UTC)
    manifest = Manifest(
        source_sha="a" * 40,
        alembic_heads=["202605300003"],
        captured_from=now,
        captured_to=now,
        consistency_note="Synthetic writers stopped.",
        source_database="127.0.0.1:5432/source",
        source_bucket="portal-files",
        application_dump=checksum(app),
        objects=[
            StoredObject(
                key="document/file.pdf",
                content_type="application/pdf",
                sha256="b" * 64,
                size_bytes=10,
                encrypted=checksum(payload),
            )
        ],
    )
    manifest_file = tmp_path / MANIFEST
    manifest_file.write_text(manifest.model_dump_json())
    assert load_verified_manifest(tmp_path) == manifest

    payload.write_bytes(b"X" * payload.stat().st_size)
    with pytest.raises(BackupSetError, match="SHA-256"):
        load_verified_manifest(tmp_path)
    payload.unlink()
    with pytest.raises(BackupSetError, match="missing"):
        load_verified_manifest(tmp_path)

    manifest.objects[0].encrypted.file = "../object.enc"
    manifest_file.write_text(manifest.model_dump_json())
    with pytest.raises(BackupSetError, match="invalid artifact path"):
        load_verified_manifest(tmp_path)
