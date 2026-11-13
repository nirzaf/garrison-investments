from __future__ import annotations

import gzip
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO
from unittest.mock import AsyncMock, Mock

import pytest

from scripts import backup_set, backup_set_storage
from scripts.backup_set import AuthenticatedManifest, ConfigurationArtifact, checksum
from scripts.backup_set_contract import (
    BackupSetError,
    DestinationIdentity,
    FailureDomains,
    RecoveryPolicy,
    RetentionRules,
    ScheduledAttemptReceipt,
    canonical_bytes,
    sign_scheduled_attempt,
    verify_publication_receipt,
)

TEST_KEY = bytes(range(32))
KEY_ID = "fixture-key"


@pytest.fixture
def recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(UTC)
    key_file = tmp_path / "recovery-key"
    key_file.write_bytes(TEST_KEY)
    key_file.chmod(0o600)
    monkeypatch.setenv("BACKUP_AUTH_KEY_FILE", str(key_file))
    monkeypatch.setenv("BACKUP_AUTH_KEY_ID", KEY_ID)
    policy = RecoveryPolicy(
        decision_id="D-29-RECOVERY",
        policy_id="fixture-policy",
        revision="v1",
        rpo_minutes=240,
        rto_minutes=240,
        backup_interval_minutes=60,
        maximum_capture_pause_seconds=60,
        maximum_publication_delay_minutes=30,
        minimum_spool_free_bytes=1000,
        retention_rules=RetentionRules(
            daily_days=2, monthly_months=2, keep_last_good=1, held_set_ids=set()
        ),
        destination_identity=DestinationIdentity(
            endpoint="localhost:9020", bucket="independent-fixture", prefix="app/test", secure=False
        ),
        failure_domains=FailureDomains(source="primary fixture", destination="recovery fixture"),
        key_custodians=["Fixture Custodian A", "Fixture Custodian B"],
        operator="Fixture Operator",
        substitute_operator="Fixture Substitute",
        exercise_interval="Fixture interval",
        required_artifact_categories={
            "application_database",
            "grafana_database",
            "objects",
            "configuration",
        },
        required_configuration_paths={"compose.yml"},
        source_environment="test",
        approval_ref="fixture-only-policy",
        approved_at=now - timedelta(days=1),
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(canonical_bytes(policy))
    policy_sha256 = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    directory = tmp_path / "capture"
    directory.mkdir()

    def fixture_artifacts(name: str) -> tuple[backup_set.Artifact, backup_set.Artifact]:
        plain = directory / name
        cipher = directory / (name + ".enc")
        plain.write_bytes(b"fixture plaintext " + name.encode())
        cipher.write_bytes(b"fixture ciphertext " + name.encode())
        plain_artifact = checksum(plain)
        plain.unlink()
        return plain_artifact, checksum(cipher)

    app_plain, app = fixture_artifacts("application.sql.gz")
    grafana_plain, grafana = fixture_artifacts("grafana.sql.gz")

    def configuration(path: str) -> ConfigurationArtifact:
        plain, cipher = fixture_artifacts(backup_set.configuration_filename(path))
        return ConfigurationArtifact(path=path, plaintext=plain, encrypted=cipher)

    manifest = AuthenticatedManifest(
        backup_set_id="a" * 32,
        source_sha="b" * 40,
        alembic_heads=["202605310005"],
        captured_from=now,
        captured_to=now,
        consistency_note="Fixture writers stopped",
        source_database="primary.test:5432/app",
        source_grafana_database="primary.test:5432/grafana",
        source_bucket="primary-fixture",
        application_dump=app,
        grafana_dump=grafana,
        objects=[],
        policy_revision=policy.revision,
        policy_sha256=policy_sha256,
        snapshot_at_utc=now,
        source_environment="test",
        configuration_sha256="c" * 64,
        image_digests={"backend": f"sha256:{'d' * 64}"},
        application_dump_plaintext=app_plain,
        grafana_dump_plaintext=grafana_plain,
        configuration_artifacts=[configuration("compose.yml")],
        capture_receipt=configuration("capture-receipt.json"),
    )
    backup_set.write_authenticated_manifest(directory, manifest, TEST_KEY, KEY_ID)
    return directory, manifest, (policy, policy_sha256), policy_path, key_file


class FixtureStore:
    scheduled_attempt_key = f"app/test/{backup_set_storage.SCHEDULED_ATTEMPT}"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.writes: list[str] = []
        self.interrupt = False
        self.corrupt = False

    def key(self, set_id: str, name: str) -> str:
        return f"app/test/{set_id}/{name}"

    def read(self, key: str, limit: int) -> bytes | None:
        return self.objects.get(key)

    def put_scheduled_attempt(self, raw: bytes) -> None:
        self.writes.append(self.scheduled_attempt_key)
        self.objects[self.scheduled_attempt_key] = raw

    def verify(self, key: str, digest: str, size: int, *, output: BinaryIO | None = None) -> bool:
        data = self.objects.get(key)
        if data is None:
            return False
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise BackupSetError("Fixture failed remote readback.")
        if output is not None:
            output.write(data)
        return True

    def put_once(self, key: str, data: bytes, size: int) -> bool:
        if key in self.objects:
            return False
        self.writes.append(key)
        self.objects[key] = data
        return True

    def put_verified_file(self, key: str, path: Path, digest: str, size: int) -> None:
        if self.interrupt:
            raise BackupSetError("Fixture interrupted the transfer.")
        if self.verify(key, digest, size):
            return
        self.put_once(key, b"damaged" if self.corrupt else path.read_bytes(), size)
        assert self.verify(key, digest, size)

    def complete_keys(self):
        return (key for key in self.objects if key.endswith("/complete.json"))


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> FixtureStore:
    store = FixtureStore()
    monkeypatch.setattr(backup_set, "RecoveryStore", lambda destination: store)
    monkeypatch.setattr(backup_set_storage, "RecoveryStore", lambda destination, timeout=60: store)
    return store


def test_signed_manifest_and_ciphertext_reject_tampering(recovery) -> None:
    directory, manifest, policy, _, key_file = recovery
    assert backup_set.load_verified_manifest(directory, policy=policy) == manifest
    manifest_path = directory / backup_set.MANIFEST
    original = manifest_path.read_bytes()
    manifest_path.write_bytes(original + b"\n")
    with pytest.raises(BackupSetError, match="authentication"):
        backup_set.load_verified_manifest(directory, policy=policy)
    manifest_path.write_bytes(original)
    key_file.write_bytes(bytes(reversed(TEST_KEY)))
    with pytest.raises(BackupSetError, match="authentication"):
        backup_set.load_verified_manifest(directory, policy=policy)
    key_file.write_bytes(TEST_KEY)
    (directory / manifest.application_dump.file).write_bytes(b"altered encrypted bytes")
    with pytest.raises(BackupSetError, match="SHA-256"):
        backup_set.load_verified_manifest(directory, policy=policy)


def test_signed_manifest_requires_policy_configuration_inventory(recovery) -> None:
    directory, manifest, (policy, _), _, _ = recovery
    stricter = policy.model_copy(update={"required_configuration_paths": {"other.yml"}})
    digest = hashlib.sha256(canonical_bytes(stricter)).hexdigest()
    signed = manifest.model_copy(update={"policy_sha256": digest})
    backup_set.write_authenticated_manifest(directory, signed, TEST_KEY, KEY_ID)
    with pytest.raises(BackupSetError, match="approved scope"):
        backup_set.load_verified_manifest(directory, policy=(stricter, digest))


@pytest.mark.parametrize("extra_bytes", [-1, 0])
@pytest.mark.parametrize("largest_artifact", ["sql", "object"])
async def test_restore_checks_working_space_after_decrypting_all_artifacts(
    recovery, monkeypatch: pytest.MonkeyPatch, extra_bytes: int, largest_artifact: str
) -> None:
    directory, manifest, (policy, _), _, _ = recovery
    sql = (
        b"CREATE TABLE public.alembic_version (version_num varchar(64));\n"
        b"COPY public.alembic_version (version_num) FROM stdin;\n"
        b"202605310005\n\\.\n" + b"-- padding\n" * 2000
    )
    paths = {}

    def stage(name: str, data: bytes) -> backup_set.Artifact:
        path = directory / name
        path.write_bytes(data)
        paths[f"{path.name}.enc"] = path
        return checksum(path)

    app = stage(manifest.application_dump_plaintext.file, gzip.compress(sql))
    assert manifest.grafana_dump_plaintext is not None
    grafana = stage(
        manifest.grafana_dump_plaintext.file, gzip.compress(b"CREATE TABLE rehearsal (id int);\n")
    )
    configuration = manifest.configuration_artifacts[0]
    config = stage(configuration.plaintext.file, b"# backup configuration\n" * 100)
    receipt = manifest.capture_receipt
    receipt_plaintext = stage(receipt.plaintext.file, b"{}\n")
    objects = []
    if largest_artifact == "object":
        name = f"object-{'a' * 64}"
        ciphertext = directory / f"{name}.enc"
        data = b"x" * (len(sql) + 1000)
        ciphertext.write_bytes(b"fixture ciphertext" + data)
        plain = stage(name, data)
        objects.append(
            backup_set.StoredObject(
                key="fixture/document",
                content_type="application/octet-stream",
                size_bytes=plain.size_bytes,
                sha256=plain.sha256,
                encrypted=checksum(ciphertext),
            )
        )
    manifest = manifest.model_copy(
        update={
            "application_dump_plaintext": app,
            "grafana_dump_plaintext": grafana,
            "configuration_artifacts": [configuration.model_copy(update={"plaintext": config})],
            "capture_receipt": receipt.model_copy(update={"plaintext": receipt_plaintext}),
            "objects": objects,
        }
    )
    working_space = max(len(sql), max((item.size_bytes for item in objects), default=0))
    capacity = sum(path.stat().st_size for path in paths.values()) + working_space + extra_bytes

    def disk_usage(path: Path) -> SimpleNamespace:
        used = sum(file.stat().st_size for file in path.iterdir())
        return SimpleNamespace(free=capacity - used)

    def decrypt(source: Path, artifact: backup_set.Artifact, target: Path, password: str) -> Path:
        plain = paths[artifact.file]
        output = target / plain.name
        output.write_bytes(plain.read_bytes())
        return output

    def readback(client, bucket, key, target, version_id):
        target.write_bytes(paths[objects[0].encrypted.file].read_bytes())

    monkeypatch.setenv("RESTORE_DATABASE_URL", "postgresql://127.0.0.1/garrison_restore_test_app")
    monkeypatch.setenv(
        "RESTORE_GRAFANA_DATABASE_URL", "postgresql://127.0.0.1/garrison_restore_test_grafana"
    )
    monkeypatch.setenv("RESTORE_OBJECT_ENDPOINT", "127.0.0.1:9000")
    monkeypatch.setenv("RESTORE_OBJECT_BUCKET", "garrison-restore-test-app")
    monkeypatch.setenv("RESTORE_OBJECT_ACCESS_KEY", "fixture")
    monkeypatch.setenv("RESTORE_OBJECT_SECRET_KEY", "fixture")
    monkeypatch.setattr(backup_set, "check_empty_database", AsyncMock())
    monkeypatch.setattr(backup_set, "verify_database", AsyncMock())
    storage = Mock()
    storage.bucket_exists.return_value = False
    monkeypatch.setattr(backup_set, "Minio", Mock(return_value=storage))
    monkeypatch.setattr(backup_set, "decrypt", decrypt)
    monkeypatch.setattr(backup_set, "download_object", readback)
    monkeypatch.setattr(backup_set.shutil, "disk_usage", disk_usage)
    restore_database = Mock()
    monkeypatch.setattr(backup_set, "restore_backup", restore_database)

    if extra_bytes < 0:
        with pytest.raises(BackupSetError, match="spool capacity"):
            await backup_set.restore(directory, manifest, "fixture", policy=policy)
        restore_database.assert_not_called()
        storage.make_bucket.assert_not_called()
    else:
        result = await backup_set.restore(directory, manifest, "fixture", policy=policy)
        assert result["outcome"] == "pass"
        assert restore_database.call_count == 2
        storage.make_bucket.assert_called_once_with("garrison-restore-test-app")


def test_reader_rejects_policy_drift_before_opening_destination(recovery, monkeypatch) -> None:
    _, _, _, policy_path, key_file = recovery

    def unavailable(*args, **kwargs):
        pytest.fail("An unapproved policy reached the remote storage client.")

    monkeypatch.setattr(backup_set_storage, "RecoveryStore", unavailable)
    with pytest.raises(BackupSetError, match="approved digest"):
        backup_set_storage.read_latest_publication(
            policy_path, key_file=key_file, key_id=KEY_ID, expected_policy_sha256="0" * 64
        )


def test_independent_round_trip_and_retries(recovery, remote, tmp_path: Path) -> None:
    directory, manifest, policy, policy_path, key_file = recovery
    receipt_file = tmp_path / "latest-success.json"
    receipt_file.write_bytes(b"previous-success-marker")
    remote.interrupt = True
    with pytest.raises(BackupSetError, match="interrupted"):
        backup_set.publish(directory, policy, receipt_file)
    assert receipt_file.read_bytes() == b"previous-success-marker"
    assert not list(remote.complete_keys())

    remote.interrupt = False
    backup_set.publish(directory, policy, receipt_file)
    writes = remote.writes.copy()
    backup_set.publish(directory, policy, receipt_file)
    assert remote.writes == writes
    receipt = verify_publication_receipt(
        receipt_file.read_bytes(), key_file=key_file, key_id=KEY_ID
    )
    assert (
        receipt.manifest_sha256
        == hashlib.sha256((directory / backup_set.MANIFEST).read_bytes()).hexdigest()
    )
    assert (
        backup_set_storage.read_latest_publication(policy_path, key_file=key_file, key_id=KEY_ID)
        == receipt
    )

    destination = tmp_path / "retrieved"
    backup_set.fetch(manifest.backup_set_id, policy, destination)
    assert backup_set.load_verified_manifest(destination, policy=policy) == manifest
    remote.objects.pop(remote.key(manifest.backup_set_id, manifest.application_dump.file))
    with pytest.raises(BackupSetError, match="missing"):
        backup_set.fetch(manifest.backup_set_id, policy, tmp_path / "incomplete")
    assert not (tmp_path / "incomplete").exists()
    with pytest.raises(BackupSetError, match="missing"):
        backup_set.publish(directory, policy, receipt_file)


def test_corrupt_publication_cannot_refresh_success(recovery, remote, tmp_path: Path) -> None:
    directory, manifest, policy, _, _ = recovery
    receipt_file = tmp_path / "latest-success.json"
    remote.corrupt = True
    with pytest.raises(BackupSetError, match="readback"):
        backup_set.publish(directory, policy, receipt_file)
    assert not receipt_file.exists()
    assert not list(remote.complete_keys())
    # The interrupted prefix is bound to its original manifest even before completion.
    manifest.consistency_note = "Other capture tried to reuse the set ID"
    backup_set.write_authenticated_manifest(directory, manifest, TEST_KEY, KEY_ID)
    with pytest.raises(BackupSetError, match="reserved for a different manifest"):
        backup_set.publish(directory, policy, receipt_file)


@pytest.fixture
def scheduled_attempt(recovery, tmp_path: Path) -> tuple[Path, Path]:
    _, manifest, _, _, _ = recovery
    attempt = tmp_path / "last-attempt.json"
    attempt.write_text(
        json.dumps(
            {
                "source_sha": manifest.source_sha,
                "started_at_utc": manifest.captured_from.isoformat(),
                "completed_at_utc": manifest.captured_to.isoformat(),
                "phase": "resume",
                "outcome": "fail",
            }
        )
    )
    inventory = tmp_path / "capture-inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "source_sha": manifest.source_sha,
                "source_environment": manifest.source_environment,
                "configuration_sha256": manifest.configuration_sha256,
                "image_digests": manifest.image_digests,
            }
        )
    )
    return attempt, inventory


def test_cli_publishes_authenticated_status_without_changing_last_good(
    recovery,
    remote: FixtureStore,
    scheduled_attempt: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, manifest, policy_data, policy_path, key_file = recovery
    latest = tmp_path / "latest-success.json"
    backup_set.publish(directory, policy_data, latest)
    prior_success = latest.read_bytes()
    prior_objects = dict(remote.objects)
    remote.writes.clear()
    attempt, inventory = scheduled_attempt
    monkeypatch.delenv("BACKUP_ENCRYPTION_PASSWORD", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backup_set",
            "publish-attempt",
            str(attempt),
            "--policy",
            str(policy_path),
            "--inventory",
            str(inventory),
        ],
    )
    backup_set.main()
    receipt = backup_set_storage.read_latest_scheduled_attempt(
        policy_path, key_file=key_file, key_id=KEY_ID, expected_policy_sha256=policy_data[1]
    )
    assert receipt.phase == "resume" and receipt.outcome == "fail"
    assert receipt.source_sha == manifest.source_sha
    assert receipt.source_environment == manifest.source_environment
    assert receipt.configuration_sha256 == manifest.configuration_sha256
    assert receipt.policy_revision == policy_data[0].revision
    assert receipt.started_at_utc == manifest.captured_from
    assert receipt.completed_at_utc == manifest.captured_to
    assert remote.writes == [remote.scheduled_attempt_key]
    assert set(remote.objects) == prior_objects.keys() | {remote.scheduled_attempt_key}
    assert all(remote.objects[key] == value for key, value in prior_objects.items())
    assert latest.read_bytes() == prior_success
    last_good = backup_set_storage.read_latest_publication(
        policy_path, key_file=key_file, key_id=KEY_ID
    )
    assert last_good.backup_set_id == manifest.backup_set_id

    attempt_data = json.loads(attempt.read_bytes())
    attempt_data.update(
        phase="complete",
        outcome="pass",
        completed_at_utc=(receipt.completed_at_utc + timedelta(minutes=1)).isoformat(),
    )
    attempt.write_text(json.dumps(attempt_data))
    backup_set.main()
    latest_attempt = backup_set_storage.read_latest_scheduled_attempt(
        policy_path, key_file=key_file, key_id=KEY_ID
    )
    assert latest_attempt.outcome == "pass" and latest_attempt.phase == "complete"
    assert latest_attempt.completed_at_utc > receipt.completed_at_utc
    assert remote.writes == [remote.scheduled_attempt_key] * 2
    assert latest.read_bytes() == prior_success


@pytest.mark.parametrize(
    ("record", "field", "value"),
    [
        ("attempt", "phase", "unknown"),
        ("attempt", "outcome", "pass"),
        ("attempt", "notes", "arbitrary text"),
        ("attempt", "completed_at_utc", "2000-01-01T00:00:00+01:00"),
        ("attempt", "completed_at_utc", "2000-01-01T00:00:00Z"),
        ("inventory", "source_environment", "other-environment"),
        ("inventory", "source_sha", "d" * 40),
    ],
)
def test_scheduled_attempt_rejects_invalid_inputs_before_publication(
    recovery,
    remote: FixtureStore,
    scheduled_attempt: tuple[Path, Path],
    record: str,
    field: str,
    value: str,
) -> None:
    _, _, policy_data, _, _ = recovery
    attempt, inventory = scheduled_attempt
    target = attempt if record == "attempt" else inventory
    edited = json.loads(target.read_bytes())
    edited[field] = value
    target.write_text(json.dumps(edited))
    with pytest.raises(BackupSetError, match="invalid|differs from the approved inventory"):
        backup_set.publish_attempt(attempt, policy_data, inventory)
    assert not remote.writes


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("missing", "receipt is missing"),
        ("tampered", "authentication failed"),
        ("unknown-key", "Unknown backup authentication key"),
        ("other-policy", "does not match the approved scope"),
        ("wrong-environment", "does not match the approved scope"),
        ("wrong-revision", "does not match the approved scope"),
        ("expected-policy-drift", "differs from its approved digest"),
    ],
)
def test_independent_reader_rejects_invalid_scheduled_attempt(
    recovery,
    remote: FixtureStore,
    scheduled_attempt: tuple[Path, Path],
    scenario: str,
    message: str,
) -> None:
    _, _, policy_data, policy_path, key_file = recovery
    attempt, inventory = scheduled_attempt
    backup_set.publish_attempt(attempt, policy_data, inventory)
    key = remote.scheduled_attempt_key
    signed = remote.objects[key]
    expected_digest = None
    key_id = KEY_ID
    if scenario == "missing":
        del remote.objects[key]
    elif scenario == "tampered":
        remote.objects[key] = signed.replace(b'"phase":"resume"', b'"phase":"capture"')
    elif scenario == "unknown-key":
        key_id = "unknown-key"
    elif scenario == "expected-policy-drift":
        expected_digest = "0" * 64
    else:
        field, replacement = {
            "other-policy": ("policy_sha256", "0" * 64),
            "wrong-environment": ("source_environment", "wrong-environment"),
            "wrong-revision": ("policy_revision", "different-revision"),
        }[scenario]
        modified = json.loads(signed)["receipt"]
        modified[field] = replacement
        receipt = ScheduledAttemptReceipt.model_validate(modified)
        remote.objects[key] = sign_scheduled_attempt(receipt, key=TEST_KEY, key_id=KEY_ID)
    with pytest.raises(BackupSetError, match=message):
        backup_set_storage.read_latest_scheduled_attempt(
            policy_path, key_file=key_file, key_id=key_id, expected_policy_sha256=expected_digest
        )


def test_retention_protects_held_daily_monthly_and_last_good(
    recovery, remote, tmp_path: Path
) -> None:
    from scripts.backup_set_contract import PublicationReceipt

    _, _, (policy, policy_sha256), _, _ = recovery
    now = datetime(2026, 11, 12, tzinfo=UTC)
    snapshots = {
        "a": now - timedelta(hours=1),
        "b": now - timedelta(days=1),
        "c": now - timedelta(days=20),
        "d": now - timedelta(days=21),
        "e": now - timedelta(days=80),
        "f": now - timedelta(days=90),
    }
    policy.retention_rules.held_set_ids.add("f" * 32)
    receipts = [
        PublicationReceipt(
            backup_set_id=key * 32,
            manifest_sha256="b" * 64,
            source_sha="c" * 40,
            snapshot_at_utc=when,
            remote_verified_at_utc=when,
            source_environment="test",
            policy_revision=policy.revision,
            policy_sha256=policy_sha256,
            configuration_sha256="d" * 64,
            destination_identity=policy.destination_identity,
            object_count=0,
        )
        for key, when in snapshots.items()
    ]
    assert [
        item.backup_set_id
        for item in backup_set_storage.retention_candidates(receipts, policy, now)
    ] == ["d" * 32, "e" * 32]
    policy.retention_rules.keep_last_good = 2
    assert not backup_set_storage.retention_candidates(receipts[-2:], policy, now)


def test_schedule_uses_policy_intervals(recovery) -> None:
    _, _, (policy, _), _, _ = recovery
    timer = backup_set.render_timer(policy)
    assert timer.count("OnCalendar=") == 24
    assert "OnCalendar=*-*-* 23:00:00 UTC" in timer
