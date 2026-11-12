"""Capture and verify a database and its referenced objects as one encrypted backup set.

Run as `python -m scripts.backup_set` from the backend environment.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory, mkstemp
from typing import Literal, Self
from urllib.parse import urlsplit
from uuid import uuid4

from alembic.script import ScriptDirectory
from minio import Minio
from minio.error import S3Error
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
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
from scripts.backup_set_contract import (
    AUTH_ALGORITHM,
    HEX_SHA256,
    LOOPBACK,
    SET_ID,
    AuthenticationRecord,
    BackupSetError,
    CaptureEvidence,
    CaptureInventoryIdentity,
    PublicationReceipt,
    RecoveryPolicy,
    RetentionAuthorization,
    RetentionCandidate,
    RetentionPlan,
    ScheduledAttempt,
    ScheduledAttemptReceipt,
    authentication_key,
    canonical_bytes,
    read_policy,
    require_relative_path,
    sign_publication_receipt,
    sign_scheduled_attempt,
)
from scripts.backup_set_storage import (
    CHUNK,
    COMPLETE,
    IDENTITY,
    MAX_MANIFEST_BYTES,
    MAX_SCHEDULED_ATTEMPT_BYTES,
    RecoveryStore,
    complete_receipt,
    retention_candidates,
)
from scripts.restore_dry_run import inspect_backup, restore_backup, sha256_file

MANIFEST = "manifest.json"
SIGNATURE = "manifest.signature.json"


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


class ManifestBody(BaseModel):
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


class Manifest(ManifestBody):
    format_version: Literal[1] = 1


class ConfigurationArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    plaintext: Artifact
    encrypted: Artifact


class AuthenticatedManifest(ManifestBody):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal[2] = 2
    backup_set_id: str = Field(pattern=SET_ID)
    policy_revision: str = Field(min_length=1)
    policy_sha256: str = Field(pattern=HEX_SHA256)
    snapshot_at_utc: AwareDatetime
    source_environment: str = Field(min_length=1)
    configuration_sha256: str = Field(pattern=HEX_SHA256)
    image_digests: dict[str, str] = Field(min_length=1)
    application_dump_plaintext: Artifact
    grafana_dump_plaintext: Artifact | None = None
    configuration_artifacts: list[ConfigurationArtifact] = Field(min_length=1)
    capture_receipt: ConfigurationArtifact

    @model_validator(mode="after")
    def validate_inventory(self) -> Self:
        if (
            self.captured_from.utcoffset() != timedelta(0)
            or self.captured_to.utcoffset() != timedelta(0)
            or self.snapshot_at_utc.utcoffset() != timedelta(0)
            or not self.captured_from <= self.snapshot_at_utc <= self.captured_to
            or bool(self.grafana_dump) != bool(self.grafana_dump_plaintext)
            or bool(self.grafana_dump) != bool(self.source_grafana_database)
        ):
            raise ValueError(
                "Authenticated recovery manifest has invalid time or database coverage."
            )
        paths = [item.path for item in self.configuration_artifacts]
        if len(set(paths)) != len(paths) or self.capture_receipt.path in paths:
            raise ValueError("Authenticated recovery manifest has duplicate configuration paths.")
        for item in [*self.configuration_artifacts, self.capture_receipt]:
            require_relative_path(item.path)
            if (
                item.plaintext.file != configuration_filename(item.path)
                or item.encrypted.file != f"{item.plaintext.file}.enc"
            ):
                raise ValueError(
                    "Recovery configuration artifact path does not match its identity."
                )
        for encrypted, plain in (
            (self.application_dump, self.application_dump_plaintext),
            (self.grafana_dump, self.grafana_dump_plaintext),
        ):
            if encrypted and plain and encrypted.file != f"{plain.file}.enc":
                raise ValueError("Recovery database artifact path does not match its plaintext.")
        return self


BackupManifest = Manifest | AuthenticatedManifest


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


async def dump_application(database_url: str, dump: Path) -> tuple[list[str], set[str], datetime]:
    engine = create_async_engine(async_database_url(database_url))
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            row = (
                await connection.execute(
                    text("SELECT pg_export_snapshot(), transaction_timestamp()")
                )
            ).one()
            snapshot = str(row[0])
            snapshot_at: datetime = row[1].astimezone(UTC)
            heads = await schema_heads(connection)
            keys = await references(connection, snapshot_at)
            await asyncio.to_thread(create_dump, database_url, dump, snapshot=snapshot)
            return heads, keys, snapshot_at
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


def configuration_filename(path: str) -> str:
    return f"configuration-{hashlib.sha256(path.encode()).hexdigest()}"


def capture_configuration(
    path: Path, logical_path: str, temporary: Path, destination: Path, password: str
) -> ConfigurationArtifact:
    if path.is_symlink() or not path.is_file():
        raise BackupSetError("Recovery configuration must be supplied in regular files.")
    staging_file = temporary / configuration_filename(logical_path)
    shutil.copyfile(path, staging_file)
    plain = checksum(staging_file)
    return ConfigurationArtifact(
        path=logical_path,
        plaintext=plain,
        encrypted=write_encrypted(staging_file, destination, password),
    )


def key_settings() -> tuple[Path, str]:
    try:
        return Path(os.environ["BACKUP_AUTH_KEY_FILE"]), os.environ["BACKUP_AUTH_KEY_ID"]
    except KeyError:
        raise BackupSetError(
            "Backup authentication key file and identifier are required."
        ) from None


def manifest_signature(raw: bytes, key: bytes, key_id: str) -> bytes:
    return canonical_bytes(
        AuthenticationRecord(
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
            key_id=key_id,
            algorithm=AUTH_ALGORITHM,
            signature=hmac.digest(key, raw, "sha256").hex(),
        )
    )


def write_authenticated_manifest(
    destination: Path, manifest: AuthenticatedManifest, key: bytes, key_id: str
) -> None:
    raw = canonical_bytes(manifest)
    (destination / SIGNATURE).write_bytes(manifest_signature(raw, key, key_id))
    pending = destination / "manifest.pending"
    pending.write_bytes(raw)
    pending.rename(destination / MANIFEST)


def read_capture_evidence(path: Path, source_sha: str, policy: RecoveryPolicy) -> CaptureEvidence:
    if path.is_symlink():
        raise BackupSetError("Recovery capture evidence requires a regular file.")
    try:
        evidence = CaptureEvidence.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        raise BackupSetError("Recovery capture evidence could not be validated.") from None
    if (
        evidence.source_sha != source_sha
        or evidence.source_environment != policy.source_environment
    ):
        raise BackupSetError("Capture evidence differs from the approved recovery environment.")
    if not policy.required_configuration_paths <= set(evidence.configuration_files):
        raise BackupSetError("Capture evidence omits approved configuration files.")
    return evidence


def ensure_spool(path: Path, minimum_free: int) -> None:
    if shutil.disk_usage(path).free < minimum_free:
        raise BackupSetError("Recovery spool capacity is below the approved minimum.")


async def capture(args: argparse.Namespace, password: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{40}", args.source_sha) or not args.consistency_note.strip():
        raise BackupSetError(
            "Provide the full release SHA and the recorded write-quiescence window."
        )
    settings = get_settings()
    destination: Path = args.destination.expanduser()
    policy_path: Path | None = args.policy
    receipt_path: Path | None = args.capture_receipt
    if bool(policy_path) != bool(receipt_path):
        raise BackupSetError("Provide both the approved recovery policy and capture evidence.")
    policy = None
    policy_sha256 = ""
    key = b""
    key_id = ""
    evidence = None
    start = datetime.now(UTC)
    grafana_url = os.getenv("BACKUP_GRAFANA_DATABASE_URL")
    if policy_path and receipt_path:
        policy, policy_sha256 = read_policy(policy_path)
        evidence = read_capture_evidence(receipt_path, args.source_sha, policy)
        key_file, key_id = key_settings()
        key = authentication_key(key_file, key_id)
        if hmac.compare_digest(key, password.encode()):
            raise BackupSetError("Backup authentication and encryption require distinct keys.")
        if "grafana_database" in policy.required_artifact_categories and not grafana_url:
            raise BackupSetError("The approved recovery policy requires the Grafana database.")
        if (
            policy.destination_identity.endpoint == settings.minio_endpoint
            or policy.destination_identity.bucket == settings.minio_bucket
        ):
            raise BackupSetError("The independent destination must differ from primary storage.")
        if (
            not 0
            <= (start - evidence.quiescence_started_at_utc).total_seconds()
            < policy.maximum_capture_pause_seconds
        ):
            raise BackupSetError("The approved capture pause is unavailable or exceeded.")
        ensure_spool(destination.parent, policy.minimum_spool_free_bytes)

    destination.mkdir(mode=0o700)
    try:
        with TemporaryDirectory(prefix="garrison-backup-") as temp:
            temporary = Path(temp)
            if policy:
                ensure_spool(temporary, policy.minimum_spool_free_bytes)
            app_dump = temporary / "application.sql.gz"
            heads, keys, snapshot_at = await dump_application(settings.database_url, app_dump)
            app_plain = checksum(app_dump)
            encrypted_app = write_encrypted(app_dump, destination, password)
            encrypted_grafana = None
            grafana_plain = None
            if grafana_url:
                grafana_dump = temporary / "grafana.sql.gz"
                create_dump(grafana_url, grafana_dump)
                grafana_plain = checksum(grafana_dump)
                encrypted_grafana = write_encrypted(grafana_dump, destination, password)
            if args.extra_objects:
                keys.update(
                    key
                    for key in args.extra_objects.read_text(encoding="utf-8").splitlines()
                    if key
                )
            source = minio_client(settings)
            objects = [
                capture_object(
                    source, settings.minio_bucket, object_key, temporary, destination, password
                )
                for object_key in sorted(keys)
            ]
            if policy and evidence and receipt_path:
                directory = (args.configuration_root or receipt_path.parent).resolve()
                configs = []
                for path in sorted(evidence.configuration_files):
                    config_path = directory / require_relative_path(path)
                    if config_path.resolve() != config_path:
                        raise BackupSetError(
                            "Recovery configuration paths may not traverse symlinks."
                        )
                    configs.append(
                        capture_configuration(config_path, path, temporary, destination, password)
                    )
                capture_receipt = capture_configuration(
                    receipt_path, "capture-receipt.json", temporary, destination, password
                )
            else:
                configs = []
                capture_receipt = None

        captured_to = datetime.now(UTC)
        base = ManifestBody(
            source_sha=args.source_sha,
            alembic_heads=heads,
            captured_from=start,
            captured_to=captured_to,
            consistency_note=args.consistency_note.strip(),
            source_database=database_identity(settings.database_url),
            source_grafana_database=database_identity(grafana_url) if grafana_url else None,
            source_bucket=settings.minio_bucket,
            application_dump=encrypted_app,
            grafana_dump=encrypted_grafana,
            objects=objects,
        )
        if policy and evidence and capture_receipt:
            if (
                captured_to - evidence.quiescence_started_at_utc
            ).total_seconds() > policy.maximum_capture_pause_seconds:
                raise BackupSetError("The approved capture pause was exceeded.")
            manifest = AuthenticatedManifest(
                **base.model_dump(),
                backup_set_id=uuid4().hex,
                policy_revision=policy.revision,
                policy_sha256=policy_sha256,
                snapshot_at_utc=snapshot_at,
                source_environment=policy.source_environment,
                configuration_sha256=evidence.configuration_sha256,
                image_digests=evidence.image_digests,
                application_dump_plaintext=app_plain,
                grafana_dump_plaintext=grafana_plain,
                configuration_artifacts=configs,
                capture_receipt=capture_receipt,
            )
            write_authenticated_manifest(destination, manifest, key, key_id)
            assurance = "authenticated format 2"
        else:
            legacy = Manifest(**base.model_dump())
            pending = destination / "manifest.pending"
            pending.write_text(legacy.model_dump_json(indent=2), encoding="utf-8")
            pending.rename(destination / MANIFEST)
            assurance = "legacy checksum-only format 1"
    except BaseException:
        shutil.rmtree(destination)
        raise
    print(f"Captured {len(objects)} referenced objects with the {assurance} backup set.")


def encrypted_artifacts(manifest: ManifestBody) -> list[Artifact]:
    artifacts = [manifest.application_dump, *(item.encrypted for item in manifest.objects)]
    if manifest.grafana_dump:
        artifacts.append(manifest.grafana_dump)
    if isinstance(manifest, AuthenticatedManifest):
        artifacts.extend(item.encrypted for item in manifest.configuration_artifacts)
        artifacts.append(manifest.capture_receipt.encrypted)
    return artifacts


def validate_inventory(manifest: ManifestBody) -> None:
    artifacts = encrypted_artifacts(manifest)
    if len({item.key for item in manifest.objects}) != len(manifest.objects) or (
        len({item.file for item in artifacts}) != len(artifacts)
    ):
        raise BackupSetError("Backup manifest contains duplicate objects or artifacts.")
    if manifest.application_dump.file != "application.sql.gz.enc" or (
        manifest.grafana_dump and manifest.grafana_dump.file != "grafana.sql.gz.enc"
    ):
        raise BackupSetError("The manifest's database artifact types do not match.")
    for item in manifest.objects:
        if not re.fullmatch(r"object-[a-f0-9]{64}\.enc", item.encrypted.file):
            raise BackupSetError("Backup manifest contains an invalid artifact path.")


def decode_manifest(
    raw: bytes,
    signature: bytes | None,
    *,
    policy: tuple[RecoveryPolicy, str] | None,
    require_authenticated: bool,
) -> BackupManifest:
    try:
        version = json.loads(raw).get("format_version", 1)
        if type(version) is not int or version not in {1, 2}:
            raise BackupSetError("Unsupported recovery manifest format.")
        if version == 1:
            if require_authenticated or signature is not None:
                raise BackupSetError("An authenticated format-2 backup manifest is required.")
            legacy = Manifest.model_validate_json(raw)
            validate_inventory(legacy)
            return legacy
        if not policy or signature is None:
            raise BackupSetError(
                "Format-2 verification requires the approved policy and signature."
            )
        record = AuthenticationRecord.model_validate_json(signature)
        key_file, key_id = key_settings()
        if record.key_id != key_id:
            raise BackupSetError("Unknown backup authentication key identifier.")
        key = authentication_key(key_file, key_id)
        if not hmac.compare_digest(signature, manifest_signature(raw, key, key_id)):
            raise BackupSetError("Backup manifest authentication failed.")
        manifest = AuthenticatedManifest.model_validate_json(raw)
        approved, policy_sha256 = policy
        if (
            canonical_bytes(manifest) != raw
            or manifest.policy_revision != approved.revision
            or manifest.policy_sha256 != policy_sha256
            or manifest.source_environment != approved.source_environment
            or (
                "grafana_database" in approved.required_artifact_categories
                and manifest.grafana_dump is None
            )
            or manifest.source_bucket == approved.destination_identity.bucket
            or not approved.required_configuration_paths
            <= {item.path for item in manifest.configuration_artifacts}
        ):
            raise BackupSetError("Authenticated backup manifest differs from its approved scope.")
        validate_inventory(manifest)
        return manifest
    except (ValueError, AttributeError):
        raise BackupSetError("Recovery manifest or signature format is invalid.") from None


def metadata_bytes(path: Path, size_limit: int) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise BackupSetError("A required backup metadata file is missing or is a symbolic link.")
    with path.open("rb") as file:
        raw = file.read(size_limit + 1)
    if len(raw) > size_limit:
        raise BackupSetError("Backup metadata exceeds its allowed size.")
    return raw


def load_verified_manifest(
    source: Path,
    *,
    policy: tuple[RecoveryPolicy, str] | None = None,
    require_authenticated: bool = False,
) -> BackupManifest:
    if source.is_symlink():
        raise BackupSetError("A recovery set path cannot be a symbolic link.")
    raw = metadata_bytes(source / MANIFEST, MAX_MANIFEST_BYTES)
    signature_path = source / SIGNATURE
    signature = (
        metadata_bytes(signature_path, CHUNK)
        if signature_path.exists() or signature_path.is_symlink()
        else None
    )
    manifest = decode_manifest(
        raw, signature, policy=policy, require_authenticated=require_authenticated
    )
    artifacts = encrypted_artifacts(manifest)
    for artifact in artifacts:
        path = source / artifact.file
        if path.is_symlink() or not path.is_file():
            raise BackupSetError("A backup artifact is missing or is a symbolic link.")
        if path.stat().st_size != artifact.size_bytes or sha256_file(path) != artifact.sha256:
            raise BackupSetError("A backup artifact failed the size or SHA-256 check.")
    return manifest


def assert_complete_matches(
    receipt: PublicationReceipt, manifest: AuthenticatedManifest, digest: str
) -> None:
    if (
        receipt.backup_set_id != manifest.backup_set_id
        or receipt.manifest_sha256 != digest
        or receipt.snapshot_at_utc != manifest.snapshot_at_utc
        or receipt.source_sha != manifest.source_sha
        or receipt.configuration_sha256 != manifest.configuration_sha256
        or receipt.object_count != len(manifest.objects)
    ):
        raise BackupSetError("An independent backup set already exists with a different identity.")


def write_receipt(path: Path, raw: bytes) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise BackupSetError("Receipt output requires a regular operator-controlled path.")
    descriptor, temporary_name = mkstemp(prefix=".receipt-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(raw)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def publish(source: Path, policy_data: tuple[RecoveryPolicy, str], receipt_path: Path) -> None:
    policy, policy_sha256 = policy_data
    manifest = load_verified_manifest(source, policy=policy_data, require_authenticated=True)
    assert isinstance(manifest, AuthenticatedManifest)
    store = RecoveryStore(policy.destination_identity)
    key_file, key_id = key_settings()
    secret = authentication_key(key_file, key_id)
    raw_manifest = canonical_bytes(manifest)
    metadata = [
        Artifact(file=name, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
        for name, data in (
            (MANIFEST, raw_manifest),
            (SIGNATURE, manifest_signature(raw_manifest, secret, key_id)),
        )
    ]
    digest = metadata[0].sha256
    set_id = manifest.backup_set_id
    marker = store.key(set_id, COMPLETE)
    identity_key = store.key(set_id, IDENTITY)
    expected_identity = digest.encode("ascii")

    if store.read(marker, CHUNK) is not None:
        existing = complete_receipt(
            store, marker, policy, policy_sha256, key_file=key_file, key_id=key_id
        )
        assert_complete_matches(existing, manifest, digest)
        if store.read(identity_key, CHUNK) != expected_identity:
            raise BackupSetError("Completed backup identity is missing or differs.")
        for artifact in [*encrypted_artifacts(manifest), *metadata]:
            if not store.verify(
                store.key(set_id, artifact.file), artifact.sha256, artifact.size_bytes
            ):
                raise BackupSetError("Completed backup artifact is missing.")
    else:
        identity = store.read(identity_key, CHUNK)
        if identity is None:
            store.put_once(identity_key, expected_identity, len(expected_identity))
            identity = store.read(identity_key, CHUNK)
        if identity != expected_identity:
            raise BackupSetError("A backup set ID is reserved for a different manifest.")
        for artifact in [*encrypted_artifacts(manifest), *metadata]:
            store.put_verified_file(
                store.key(set_id, artifact.file),
                source / artifact.file,
                artifact.sha256,
                artifact.size_bytes,
            )
        verified_at = datetime.now(UTC)
        if (
            not timedelta(0)
            <= verified_at - manifest.snapshot_at_utc
            <= timedelta(minutes=policy.maximum_publication_delay_minutes)
        ):
            raise BackupSetError("Independent backup exceeded its approved publication delay.")
        receipt = PublicationReceipt(
            backup_set_id=set_id,
            manifest_sha256=digest,
            snapshot_at_utc=manifest.snapshot_at_utc,
            remote_verified_at_utc=verified_at,
            source_sha=manifest.source_sha,
            source_environment=manifest.source_environment,
            policy_revision=manifest.policy_revision,
            policy_sha256=policy_sha256,
            configuration_sha256=manifest.configuration_sha256,
            destination_identity=policy.destination_identity,
            object_count=len(manifest.objects),
        )
        raw = sign_publication_receipt(receipt, key=secret, key_id=key_id)
        store.put_once(marker, raw, len(raw))
        existing = complete_receipt(
            store, marker, policy, policy_sha256, key_file=key_file, key_id=key_id
        )
        assert_complete_matches(existing, manifest, digest)

    raw_marker = store.read(marker, CHUNK)
    if raw_marker != sign_publication_receipt(existing, key=secret, key_id=key_id):
        raise BackupSetError("Independent backup receipt changed during verification.")
    write_receipt(receipt_path, raw_marker)
    print(f"Published and independently verified backup set {set_id}.")


def publish_attempt(
    source: Path, policy_data: tuple[RecoveryPolicy, str], inventory_path: Path
) -> None:
    policy, policy_sha256 = policy_data
    try:
        attempt = ScheduledAttempt.model_validate_json(
            metadata_bytes(source, MAX_SCHEDULED_ATTEMPT_BYTES)
        )
        inventory = CaptureInventoryIdentity.model_validate_json(
            metadata_bytes(inventory_path, CHUNK)
        )
        if (
            attempt.source_sha != inventory.source_sha
            or inventory.source_environment != policy.source_environment
        ):
            raise BackupSetError("Scheduled backup attempt differs from the approved inventory.")
        receipt = ScheduledAttemptReceipt(
            **attempt.model_dump(),
            source_environment=policy.source_environment,
            policy_revision=policy.revision,
            policy_sha256=policy_sha256,
            configuration_sha256=inventory.configuration_sha256,
        )
    except ValueError:
        raise BackupSetError("Scheduled backup attempt or inventory is invalid.") from None
    key_file, key_id = key_settings()
    raw = sign_scheduled_attempt(receipt, key=authentication_key(key_file, key_id), key_id=key_id)
    RecoveryStore(policy.destination_identity).put_scheduled_attempt(raw)
    print("Published and independently verified scheduled backup attempt status.")


def fetch(set_id: str, policy_data: tuple[RecoveryPolicy, str], destination: Path) -> None:
    policy, policy_sha256 = policy_data
    store = RecoveryStore(policy.destination_identity)
    key_file, key_id = key_settings()
    marker = store.key(set_id, COMPLETE)
    receipt = complete_receipt(
        store, marker, policy, policy_sha256, key_file=key_file, key_id=key_id
    )
    raw = store.read(store.key(set_id, MANIFEST), MAX_MANIFEST_BYTES)
    signature = store.read(store.key(set_id, SIGNATURE), CHUNK)
    if raw is None or signature is None:
        raise BackupSetError("Independent backup manifest or signature is missing.")
    digest = hashlib.sha256(raw).hexdigest()
    manifest = decode_manifest(raw, signature, policy=policy_data, require_authenticated=True)
    assert isinstance(manifest, AuthenticatedManifest)
    assert_complete_matches(receipt, manifest, digest)
    if store.read(store.key(set_id, IDENTITY), CHUNK) != digest.encode("ascii"):
        raise BackupSetError("Completed backup identity is missing or differs.")
    ensure_spool(
        destination.parent,
        max(
            policy.minimum_spool_free_bytes,
            sum(item.size_bytes for item in encrypted_artifacts(manifest)),
        ),
    )
    destination.mkdir(mode=0o700)
    try:
        for artifact in encrypted_artifacts(manifest):
            with (destination / artifact.file).open("wb") as target:
                if not store.verify(
                    store.key(set_id, artifact.file),
                    artifact.sha256,
                    artifact.size_bytes,
                    output=target,
                ):
                    raise BackupSetError("An independent backup artifact is missing.")
        (destination / SIGNATURE).write_bytes(signature)
        (destination / MANIFEST).write_bytes(raw)
    except BaseException:
        shutil.rmtree(destination)
        raise
    print(f"Fetched and authenticated independent backup set {set_id}.")


def read_retention_candidates(
    store: RecoveryStore, policy_data: tuple[RecoveryPolicy, str], at: datetime
) -> list[RetentionCandidate]:
    policy, digest = policy_data
    key_file, key_id = key_settings()
    receipts = [
        complete_receipt(store, key, policy, digest, key_file=key_file, key_id=key_id)
        for key in store.complete_keys()
    ]
    return [
        RetentionCandidate(
            backup_set_id=item.backup_set_id,
            manifest_sha256=item.manifest_sha256,
            snapshot_at_utc=item.snapshot_at_utc,
        )
        for item in retention_candidates(receipts, policy, at)
    ]


def retention_preview(policy_data: tuple[RecoveryPolicy, str], output: Path) -> None:
    policy, digest = policy_data
    at = datetime.now(UTC)
    store = RecoveryStore(policy.destination_identity)
    plan = RetentionPlan(
        policy_sha256=digest,
        destination_identity=policy.destination_identity,
        planned_at_utc=at,
        candidates=read_retention_candidates(store, policy_data, at),
    )
    data = canonical_bytes(plan)
    write_receipt(output, data)
    plan_digest = hashlib.sha256(data).hexdigest()
    print(f"Previewed {len(plan.candidates)} eligible complete sets. SHA-256 {plan_digest}.")


def retention_apply(
    policy_data: tuple[RecoveryPolicy, str], plan_file: Path, approval_file: Path, output: Path
) -> None:
    policy, digest = policy_data
    at = datetime.now(UTC)
    if output.resolve() in {plan_file.resolve(), approval_file.resolve()}:
        raise BackupSetError("Retention output must preserve its plan and authorization inputs.")
    raw = metadata_bytes(plan_file, MAX_MANIFEST_BYTES)
    approval_data = metadata_bytes(approval_file, CHUNK)
    if approval_file.stat().st_mode & 0o077:
        raise BackupSetError("Retention authorization must be an owner-only file.")
    plan = RetentionPlan.model_validate_json(raw)
    approval = RetentionAuthorization.model_validate_json(approval_data)
    plan_sha256 = hashlib.sha256(raw).hexdigest()
    if (
        plan_sha256 != approval.plan_sha256
        or plan.policy_sha256 != digest
        or plan.destination_identity != policy.destination_identity
        or not plan.planned_at_utc
        <= approval.authorized_from_utc
        <= at
        < approval.authorized_until_utc
        or len({item.backup_set_id for item in plan.candidates}) != len(plan.candidates)
    ):
        raise BackupSetError(
            "Retention authorization is outside its approved plan, scope or window."
        )

    store = RecoveryStore(policy.destination_identity)
    key_file, key_id = key_settings()
    eligible = {
        item.backup_set_id: item for item in read_retention_candidates(store, policy_data, at)
    }
    prepared: list[tuple[RetentionCandidate, list[str]]] = []
    for candidate in plan.candidates:
        set_id = candidate.backup_set_id
        if eligible.get(set_id) != candidate:
            raise BackupSetError("An approved retention set changed or is now protected.")
        manifest_bytes = store.read(store.key(set_id, MANIFEST), MAX_MANIFEST_BYTES)
        signature = store.read(store.key(set_id, SIGNATURE), CHUNK)
        if (
            manifest_bytes is None
            or hashlib.sha256(manifest_bytes).hexdigest() != candidate.manifest_sha256
        ):
            raise BackupSetError("An approved retention set no longer matches its manifest.")
        manifest = decode_manifest(
            manifest_bytes, signature, policy=policy_data, require_authenticated=True
        )
        assert isinstance(manifest, AuthenticatedManifest)
        if manifest.backup_set_id != set_id:
            raise BackupSetError("Retention set ID no longer matches the authenticated manifest.")
        prepared.append((candidate, [item.file for item in encrypted_artifacts(manifest)]))

    removed: list[str] = []
    write_receipt(
        output,
        json.dumps(
            {
                "operation": "backup_set_retention",
                "outcome": "started",
                "plan_sha256": plan_sha256,
            },
            sort_keys=True,
        ).encode(),
    )
    try:
        for candidate, names in prepared:
            if datetime.now(UTC) >= approval.authorized_until_utc:
                raise BackupSetError("Retention approval expired before all sets were processed.")
            set_id = candidate.backup_set_id
            marker = store.key(set_id, COMPLETE)
            receipt = complete_receipt(
                store, marker, policy, digest, key_file=key_file, key_id=key_id
            )
            if receipt.manifest_sha256 != candidate.manifest_sha256:
                raise BackupSetError("Retention receipt changed during execution.")
            # Invalidate visibility first, so interruption cannot leave a partial
            # set advertised as a verified recovery point.
            store.remove(marker)
            if store.read(marker, CHUNK) is not None:
                raise BackupSetError("Retention could not remove the complete marker.")
            for name in [*names, MANIFEST, SIGNATURE]:
                store.remove(store.key(set_id, name))
            removed.append(set_id)
    finally:
        write_receipt(
            output,
            json.dumps(
                {
                    "operation": "backup_set_retention",
                    "outcome": "pass" if len(removed) == len(prepared) else "fail",
                    "plan_sha256": plan_sha256,
                    "completed_at_utc": datetime.now(UTC).isoformat(),
                    "removed_set_ids": removed,
                },
                sort_keys=True,
            ).encode(),
        )
    print(f"Removed {len(removed)} sets from the approved retention plan.")


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


async def verify_database(url: str, manifest: BackupManifest) -> None:
    engine = create_async_engine(async_database_url(url))
    try:
        async with engine.connect() as connection:
            if await schema_heads(connection) != sorted(manifest.alembic_heads):
                raise BackupSetError("The restored database schema differs from the manifest.")
            snapshot_at = (
                manifest.snapshot_at_utc
                if isinstance(manifest, AuthenticatedManifest)
                else manifest.captured_from
            )
            if not (await references(connection, snapshot_at)) <= {
                item.key for item in manifest.objects
            }:
                raise BackupSetError(
                    "The restored database references objects outside the backup set."
                )
    finally:
        await engine.dispose()


def verify_plaintext(path: Path, artifact: Artifact) -> None:
    if path.stat().st_size != artifact.size_bytes or sha256_file(path) != artifact.sha256:
        raise BackupSetError("Decrypted bytes differ from the authenticated manifest.")


def dump_size_and_heads(path: Path) -> tuple[int, list[str]]:
    # pg_dump's plain format emits COPY for the Alembic version table. Limit
    # each read because another table may contain a very large data row.
    marker = b"COPY public.alembic_version (version_num) FROM stdin;\n"
    total = 0
    heads = []
    inside_copy = False
    at_line_start = True
    with gzip.open(path, "rb") as stream:
        while line := stream.readline(4096):
            total += len(line)
            if at_line_start and line == marker:
                inside_copy = True
            elif inside_copy:
                if line == b"\\.\n":
                    inside_copy = False
                elif re.fullmatch(rb"[a-zA-Z0-9_]{1,64}\n", line):
                    heads.append(line.strip().decode("ascii"))
                else:
                    raise BackupSetError("Invalid Alembic revision in database dump.")
            at_line_start = line.endswith(b"\n")
    return total, sorted(heads)


async def restore(
    source: Path,
    manifest: BackupManifest,
    password: str,
    *,
    policy: RecoveryPolicy | None = None,
    configuration_destination: Path | None = None,
) -> dict[str, object]:
    started = datetime.now(UTC)
    if configuration_destination and (
        not isinstance(manifest, AuthenticatedManifest)
        or configuration_destination.exists()
        or configuration_destination.is_symlink()
    ):
        raise BackupSetError(
            "Configuration recovery requires an authenticated set and a new directory."
        )
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
        if policy:
            ensure_spool(
                temporary,
                max(
                    policy.minimum_spool_free_bytes,
                    sum(item.size_bytes for item in encrypted_artifacts(manifest)),
                ),
            )
        app_dump = decrypt(source, manifest.application_dump, temporary, password)
        inspect_backup(app_dump)
        grafana_dump = None
        if manifest.grafana_dump:
            grafana_dump = decrypt(source, manifest.grafana_dump, temporary, password)
            inspect_backup(grafana_dump)
        configuration_files = []
        if isinstance(manifest, AuthenticatedManifest):
            verify_plaintext(app_dump, manifest.application_dump_plaintext)
            app_size, heads = dump_size_and_heads(app_dump)
            revisions = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
            if heads != sorted(manifest.alembic_heads) or any(
                revisions.get_revision(head) is None for head in heads
            ):
                raise BackupSetError("The application dump has incompatible migration heads.")
            grafana_size = 0
            if grafana_dump and manifest.grafana_dump_plaintext:
                verify_plaintext(grafana_dump, manifest.grafana_dump_plaintext)
                grafana_size, _ = dump_size_and_heads(grafana_dump)
            ensure_spool(temporary, max(app_size, grafana_size))
            for config in [*manifest.configuration_artifacts, manifest.capture_receipt]:
                path = decrypt(source, config.encrypted, temporary, password)
                verify_plaintext(path, config.plaintext)
                configuration_files.append((config, path))
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
        database_restored = datetime.now(UTC)
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
        if configuration_destination:
            configuration_destination.mkdir(mode=0o700)
            for config, path in configuration_files:
                output = configuration_destination / require_relative_path(config.path)
                output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copyfile(path, output)
                output.chmod(0o600)
    assurance = (
        "authenticated format 2"
        if isinstance(manifest, AuthenticatedManifest)
        else "legacy checksum-only format 1"
    )
    print(f"Restored {assurance} backup set and verified {len(manifest.objects)} object checksums.")
    result: dict[str, object] = {
        "operation": "disposable_artifact_restore",
        "outcome": "pass",
        "assurance": assurance,
        "source_sha": manifest.source_sha,
        "restore_started_at_utc": started.isoformat(),
        "database_restored_at_utc": database_restored.isoformat(),
        "objects_verified_at_utc": datetime.now(UTC).isoformat(),
        "expected_migration_heads": manifest.alembic_heads,
        "observed_migration_heads": manifest.alembic_heads,
        "required_object_count": len(manifest.objects),
        "restored_object_count": len(manifest.objects),
    }
    if isinstance(manifest, AuthenticatedManifest):
        result.update(
            backup_set_id=manifest.backup_set_id,
            manifest_sha256=hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
            snapshot_at_utc=manifest.snapshot_at_utc.isoformat(),
            configuration_sha256=manifest.configuration_sha256,
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    capture_args = subcommands.add_parser("capture")
    capture_args.add_argument("--destination", type=Path, required=True)
    capture_args.add_argument("--source-sha", required=True)
    capture_args.add_argument("--consistency-note", required=True)
    capture_args.add_argument("--extra-objects", type=Path)
    capture_args.add_argument("--policy", type=Path)
    capture_args.add_argument("--capture-receipt", type=Path)
    capture_args.add_argument("--configuration-root", type=Path)
    policy_args = subcommands.add_parser("policy-check")
    policy_args.add_argument("--policy", type=Path, required=True)
    schedule_args = subcommands.add_parser("schedule")
    schedule_args.add_argument("--policy", type=Path, required=True)
    schedule_args.add_argument("--output", type=Path, required=True)
    attempt_args = subcommands.add_parser("publish-attempt")
    attempt_args.add_argument("source", type=Path)
    attempt_args.add_argument("--policy", type=Path, required=True)
    attempt_args.add_argument("--inventory", type=Path, required=True)
    for operation in ("retention-preview", "retention-apply"):
        retention_args = subcommands.add_parser(operation)
        retention_args.add_argument("--policy", type=Path, required=True)
        retention_args.add_argument("--output", type=Path, required=True)
        if operation == "retention-apply":
            retention_args.add_argument("--plan", type=Path, required=True)
            retention_args.add_argument("--authorization", type=Path, required=True)
    for command in ("verify", "restore", "publish", "fetch"):
        action = subcommands.add_parser(command)
        action.add_argument("source", type=str if command == "fetch" else Path)
        action.add_argument("--policy", type=Path, required=command in {"publish", "fetch"})
        if command in {"verify", "restore"}:
            action.add_argument("--require-authenticated", action="store_true")
        if command in {"restore", "publish"}:
            action.add_argument("--receipt", type=Path, required=command == "publish")
        if command == "restore":
            action.add_argument("--configuration-destination", type=Path)
        if command == "fetch":
            action.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        policy = read_policy(args.policy) if args.policy else None
        if args.command == "policy-check" and policy:
            print(
                policy[0].maximum_capture_pause_seconds, policy[0].maximum_publication_delay_minutes
            )
            return
        if args.command == "schedule" and policy:
            write_receipt(args.output, render_timer(policy[0]).encode())
            return
        if args.command == "retention-preview" and policy:
            retention_preview(policy, args.output)
            return
        if args.command == "retention-apply" and policy:
            retention_apply(policy, args.plan, args.authorization, args.output)
            return
        if args.command == "verify":
            manifest = load_verified_manifest(
                args.source, policy=policy, require_authenticated=args.require_authenticated
            )
            assurance = (
                "authenticated format 2"
                if isinstance(manifest, AuthenticatedManifest)
                else "legacy checksum-only format 1"
            )
            print(f"Verified {assurance} encrypted artifacts for {len(manifest.objects)} objects.")
            return
        if args.command == "publish" and policy:
            publish(args.source, policy, args.receipt)
            return
        if args.command == "publish-attempt" and policy:
            publish_attempt(args.source, policy, args.inventory)
            return
        if args.command == "fetch" and policy:
            fetch(args.source, policy, args.destination)
            return
        password = os.getenv("BACKUP_ENCRYPTION_PASSWORD")
        if not password:
            raise BackupSetError("BACKUP_ENCRYPTION_PASSWORD is required.")
        if args.command == "capture":
            asyncio.run(capture(args, password))
        else:
            source = args.source
            manifest = load_verified_manifest(
                source, policy=policy, require_authenticated=args.require_authenticated
            )
            result = asyncio.run(
                restore(
                    source,
                    manifest,
                    password,
                    policy=policy[0] if policy else None,
                    configuration_destination=args.configuration_destination,
                )
            )
            if args.receipt:
                write_receipt(args.receipt, json.dumps(result, sort_keys=True).encode())
    except BackupSetError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit(f"Backup-set operation failed ({type(error).__name__}).") from None


def render_timer(policy: RecoveryPolicy) -> str:
    interval = policy.backup_interval_minutes
    if interval > 1440:
        raise BackupSetError("Use an approved external scheduler for intervals beyond one day.")
    slots = [
        f"OnCalendar=*-*-* {minute // 60:02d}:{minute % 60:02d}:00 UTC"
        for minute in range(0, 1440, interval)
    ]
    return "\n".join(
        [
            "[Unit]",
            "Description=Capture the independently recoverable Garrisons backup set",
            "",
            "[Timer]",
            *slots,
            "Persistent=true",
            "AccuracySec=1s",
            "Unit=backup-set.service",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )


if __name__ == "__main__":
    main()
