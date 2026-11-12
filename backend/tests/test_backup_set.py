from datetime import UTC, datetime

import pytest

from scripts.backup_set import (
    MANIFEST,
    BackupSetError,
    Manifest,
    StoredObject,
    checksum,
    load_verified_manifest,
    require_disposable_bucket,
    require_disposable_database,
)


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
