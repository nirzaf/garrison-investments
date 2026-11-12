from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import pytest

from scripts import backup_set, backup_set_storage
from scripts.backup_set import AuthenticatedManifest, ConfigurationArtifact, checksum
from scripts.backup_set_contract import (
    BackupSetError,
    DestinationIdentity,
    FailureDomains,
    RecoveryPolicy,
    RetentionRules,
    canonical_bytes,
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
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.writes: list[str] = []
        self.interrupt = False
        self.corrupt = False

    def key(self, set_id: str, name: str) -> str:
        return f"app/test/{set_id}/{name}"

    def read(self, key: str, limit: int) -> bytes | None:
        return self.objects.get(key)

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
