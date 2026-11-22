import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[2] / "deploy/forward097_reconcile.py"
spec = importlib.util.spec_from_file_location("forward097_reconcile", FILE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

REPLACEMENT_SHA = "a" * 40
MAIN_SHA = "b" * 40
BACKEND_ID = "sha256:" + "1" * 64
FRONTEND_ID = "sha256:" + "2" * 64
ASSET_HASH = "3" * 64
WORKER_HASH = "4" * 64
CI_RUN = "44734573582"
CI_ATTEMPT = "1"
MAIN_CI_RUN = "500"
MAIN_CI_ATTEMPT = "2"
DEPLOY_RUN = "600"
DEPLOY_ATTEMPT = "1"


def _write(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    path.write_bytes(raw)
    path.chmod(mode)


def _historical_records() -> dict[str, bytes]:
    records = {
        "forward097.attempt": (
            "Forward093-to097 in progress; no secured-backup guarantee.\n"
            + "".join(
                json.dumps({"phase": phase}, separators=(",", ":")) + "\n"
                for phase in (
                    "permit_consumed_before_migration",
                    "schema097_verified",
                    "contained_failure",
                )
            )
        ).encode(),
        "forward097.used": json.dumps(
            {
                "sha": "9da001055094115af77ee5f9611cae253fd3bc49",
                "source": "202605310093",
                "target": module.SCHEMA,
                "ci_run": 44506276841,
                "deploy_run": 44513571888,
                "mode": "forward-only-093-to-097",
            },
            separators=(",", ":"),
        ).encode(),
        "forward097.reopen-commit": json.dumps(
            {
                "sha": "9da001055094115af77ee5f9611cae253fd3bc49",
                "ci_run": "44506276841",
                "deploy_run": "44513571888",
                "schema": module.SCHEMA,
                "state": "verified-serving-committed",
                "receipt": "pending-observed-reopen",
            },
            separators=(",", ":"),
        ).encode(),
        "forward097.recovery-attempt": (
            "".join(
                json.dumps(item, separators=(",", ":")) + "\n"
                for item in (
                    {"phase": "authorized_forward_recovery_started", "original_run": 44513571888},
                    {"phase": "recovered_guarded_smoke_verified"},
                    {"phase": "reopening_authorized_after_writer_verification"},
                    {"phase": "writers_started_after_checkpoint"},
                    {"phase": "ingress_reopened"},
                    {"phase": "recovery_observed_complete"},
                )
            )
        ).encode(),
    }
    return records


def _make_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    owner = os.getuid()
    state = tmp_path / "deploy"
    releases = tmp_path / "releases"
    state.mkdir(mode=0o700)
    releases.mkdir(mode=0o700)
    historical = _historical_records()
    monkeypatch.setattr(
        module,
        "EVIDENCE_HASHES",
        {name: hashlib.sha256(raw).hexdigest() for name, raw in historical.items()},
    )
    for name, raw in historical.items():
        _write(state / name, raw)

    predecessor = releases / module.UNATTESTED_SHA
    predecessor.mkdir(mode=0o755)
    _write(
        predecessor / ".images.env",
        (
            f"GARRISON_BACKEND_IMAGE={module.UNATTESTED_BACKEND_REF}\n"
            "GARRISON_FRONTEND_IMAGE=garrison-portal-release-frontend:"
            f"{module.UNATTESTED_SHA}\n"
        ).encode(),
    )

    replacement = releases / f"{REPLACEMENT_SHA}.test"
    replacement.mkdir(mode=0o755)
    _write(replacement / "SOURCE_COMMIT", f"{REPLACEMENT_SHA}\n".encode())
    backend_ref = f"garrison-portal-release-backend:{REPLACEMENT_SHA}"
    frontend_ref = f"garrison-portal-release-frontend:{REPLACEMENT_SHA}"
    _write(
        replacement / ".images.env",
        f"GARRISON_BACKEND_IMAGE={backend_ref}\nGARRISON_FRONTEND_IMAGE={frontend_ref}\n".encode(),
    )
    receipt = (
        "Status: Deployed — Formal Acceptance Pending\n"
        f"Commit: {REPLACEMENT_SHA}\n"
        f"CI run: {CI_RUN}\nCI attempt: {CI_ATTEMPT}\n"
        f"Deploy run: {DEPLOY_RUN}\nDeploy attempt: {DEPLOY_ATTEMPT}\n"
        "UTC: 2026-11-20T18:00:00Z\n"
        "Frontend asset: /assets/index-test_1.js\n"
        f"Asset SHA-256: {ASSET_HASH}\nService worker SHA-256: {WORKER_HASH}\n"
        f"Backend image: {BACKEND_ID}\nFrontend image: {FRONTEND_ID}\n"
        # The host release script serializes heads with `tr '\\n' ' '`, leaving
        # a trailing separator for a single head.
        f"Schema heads: {module.SCHEMA} \n"
    ).encode()
    _write(replacement / "DEPLOYED", receipt)
    (state / "current").symlink_to(replacement)
    monkeypatch.setattr(
        module,
        "_runtime_snapshot",
        lambda _release, _fields, _sha: {
            "schema_head": module.SCHEMA,
            "backend_image_ref": backend_ref,
            "backend_image_id": BACKEND_ID,
            "frontend_image_ref": frontend_ref,
            "frontend_image_id": FRONTEND_ID,
            "services": {},
            "worker_ping_count": 1,
            "beat_started": True,
            "readiness": {"status": "ready", "database": "connected"},
            "frontend_asset_sha256": ASSET_HASH,
            "service_worker_sha256": WORKER_HASH,
        },
    )
    identities = {
        "expected_sha": REPLACEMENT_SHA,
        "ci_run": CI_RUN,
        "ci_attempt": CI_ATTEMPT,
        "main_sha": MAIN_SHA,
        "main_ci_run": MAIN_CI_RUN,
        "main_ci_attempt": MAIN_CI_ATTEMPT,
        "deploy_run": DEPLOY_RUN,
        "deploy_attempt": DEPLOY_ATTEMPT,
        "owner_uid": owner,
    }
    return state, releases, replacement, historical, identities


def test_beat_startup_marker_is_read_from_docker_logs_stderr(monkeypatch):
    marker = json.dumps(
        {"logger": "celery.beat", "message": "beat: Starting..."}
    ).encode()
    completed = module.subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b"stdout has no marker\n", stderr=marker
    )
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: completed)

    assert module._beat_started(
        {"started_at": "2026-11-22T04:14:43.000000000Z"},
        "garrison-portal-celery_beat-1",
    ) is True


def test_beat_startup_marker_missing_from_both_docker_log_streams(monkeypatch):
    completed = module.subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b"worker log\n", stderr=b"scheduler loading\n"
    )
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: completed)

    with pytest.raises(
        module.ReconciliationError, match="Celery beat startup was not observed"
    ):
        module._beat_started(
            {"started_at": "2026-11-22T04:14:43.000000000Z"},
            "garrison-portal-celery_beat-1",
        )


def test_incident_evidence_hashes_and_timestamps_are_read_only(tmp_path, monkeypatch):
    state, _, _, historical, _ = _make_fixture(tmp_path, monkeypatch)
    before = {name: (state / name).read_bytes() for name in historical}
    evidence = module.validate_incident_evidence(state, owner_uid=os.getuid())

    assert set(evidence) == set(historical)
    assert all(len(item["sha256"]) == 64 for item in evidence.values())
    assert all(
        item["mtime_ns"] > 0 and item["mtime_utc"].endswith("+00:00") for item in evidence.values()
    )
    assert {name: (state / name).read_bytes() for name in historical} == before


def test_runtime_snapshot_accepts_actual_celery_beat_compose_identity(monkeypatch):
    backend_ref = f"garrison-portal-release-backend:{REPLACEMENT_SHA}"
    frontend_ref = f"garrison-portal-release-frontend:{REPLACEMENT_SHA}"
    images = (
        f"GARRISON_BACKEND_IMAGE={backend_ref}\n"
        f"GARRISON_FRONTEND_IMAGE={frontend_ref}\n"
    ).encode()
    services = {
        "garrison-portal-backend-1": "backend",
        "garrison-portal-celery_worker-1": "celery_worker",
        "garrison-portal-celery_beat-1": "celery_beat",
        "garrison-portal-nginx-1": "nginx",
    }

    monkeypatch.setattr(module, "_secure_read", lambda *_args: images)
    monkeypatch.setattr(
        module,
        "_container_snapshot",
        lambda name: {
            "service": services[name],
            "image_id": BACKEND_ID,
            "image_ref": backend_ref,
            "healthy": "healthy",
            "started_at": "2026-11-22T03:00:00Z",
        },
    )
    monkeypatch.setattr(
        module,
        "_run",
        lambda args, **_kwargs: (
            BACKEND_ID if backend_ref in args else FRONTEND_ID
        ).encode(),
    )
    monkeypatch.setattr(module, "_schema_head", lambda: module.SCHEMA)
    monkeypatch.setattr(module, "_worker_ping", lambda _name: 1)
    monkeypatch.setattr(module, "_beat_started", lambda _container, _name: True)
    responses = {
        f"{module.PORTAL}/health/readiness": b'{"status":"ready","database":"connected"}',
        f"{module.PORTAL}/login": b"login",
        f"{module.PORTAL}/assets/index-test_1.js": b"asset",
        f"{module.PORTAL}/sw.js": b"worker",
    }
    monkeypatch.setattr(module, "_http", lambda url: responses[url])

    fields = {
        "Backend image": BACKEND_ID,
        "Frontend image": FRONTEND_ID,
        "Frontend asset": "/assets/index-test_1.js",
        "Asset SHA-256": hashlib.sha256(b"asset").hexdigest(),
        "Service worker SHA-256": hashlib.sha256(b"worker").hexdigest(),
    }

    result = module._runtime_snapshot(Path("/unused"), fields, REPLACEMENT_SHA)

    assert result["services"]["beat"]["service"] == "celery_beat"
    assert result["beat_started"] is True


def test_predecessor_is_only_classified_unattested_without_receipt(tmp_path, monkeypatch):
    _, releases, _, _, _ = _make_fixture(tmp_path, monkeypatch)
    predecessor = releases / module.UNATTESTED_SHA
    result = module.validate_unattested_predecessor(predecessor, owner_uid=os.getuid())
    assert result["classification"] == "UNATTESTED"
    assert result["sha"] == module.UNATTESTED_SHA

    _write(predecessor / "DEPLOYED", b"historical receipt\n")
    with pytest.raises(module.ReconciliationError, match="receipt"):
        module.validate_unattested_predecessor(predecessor, owner_uid=os.getuid())


def test_close_is_append_only_exact_and_idempotent(tmp_path, monkeypatch):
    state, releases, replacement, historical, identities = _make_fixture(tmp_path, monkeypatch)
    before = {name: hashlib.sha256((state / name).read_bytes()).hexdigest() for name in historical}

    record, created = module.close_after_verified_replacement(state, releases, **identities)
    receipt_path = state / "forward097.reconciled.json"
    assert created is True
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert record["prior_release"]["classification"] == "UNATTESTED"
    assert record["prior_release"]["sha"] == module.UNATTESTED_SHA
    assert record["replacement"]["release_path"] == str(replacement)
    assert record["replacement"]["schema_head"] == module.SCHEMA
    assert module._verify_reconciliation_record(state, releases, owner_uid=os.getuid()) == record
    assert {
        name: hashlib.sha256((state / name).read_bytes()).hexdigest() for name in historical
    } == before

    replay, replay_created = module.close_after_verified_replacement(state, releases, **identities)
    assert replay == record
    assert replay_created is False


def test_close_refuses_wrong_schema_and_changed_replay(tmp_path, monkeypatch):
    state, releases, replacement, _, identities = _make_fixture(tmp_path, monkeypatch)
    wrong_schema = dict(identities)
    monkeypatch.setattr(
        module,
        "_runtime_snapshot",
        lambda *_args: {"schema_head": "202605310098"},
    )
    with pytest.raises(module.ReconciliationError, match="exact image, schema"):
        module.close_after_verified_replacement(state, releases, **wrong_schema)
    assert not (state / "forward097.reconciled.json").exists()

    monkeypatch.undo()
    second = tmp_path / "second"
    second.mkdir()
    state, releases, _, _, identities = _make_fixture(second, monkeypatch)
    module.close_after_verified_replacement(state, releases, **identities)
    changed = dict(identities, deploy_attempt="2")
    with pytest.raises(module.ReconciliationError, match="another verified release"):
        module.close_after_verified_replacement(state, releases, **changed)


def test_close_refuses_tampered_original_marker(tmp_path, monkeypatch):
    state, releases, _, _, identities = _make_fixture(tmp_path, monkeypatch)
    marker = state / "forward097.attempt"
    marker.write_bytes(marker.read_bytes() + b"tampered\n")
    with pytest.raises(module.ReconciliationError, match="evidence changed"):
        module.close_after_verified_replacement(state, releases, **identities)
    assert not (state / "forward097.reconciled.json").exists()


def test_close_refuses_group_or_world_writable_replacement_directory(tmp_path, monkeypatch):
    state, releases, replacement, _, identities = _make_fixture(tmp_path, monkeypatch)
    replacement.chmod(0o777)

    with pytest.raises(module.ReconciliationError, match="Directory is not protected"):
        module.close_after_verified_replacement(state, releases, **identities)

    assert not (state / "forward097.reconciled.json").exists()


def test_lock_must_be_root_controlled_descriptor_for_lock_file(tmp_path):
    state = tmp_path / "deploy"
    state.mkdir(mode=0o700)
    lock = state / "deploy.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        module.assert_lock_held(state, lock_fd=fd, owner_uid=os.getuid())
        wrong_fd = os.open(tmp_path / "other", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with pytest.raises(module.ReconciliationError, match="lock descriptor"):
                module.assert_lock_held(state, lock_fd=wrong_fd, owner_uid=os.getuid())
        finally:
            os.close(wrong_fd)
    finally:
        os.close(fd)


def test_failed_partial_reconciliation_write_does_not_publish_a_receipt(tmp_path, monkeypatch):
    owner = os.getuid()
    directory = tmp_path / "deploy"
    directory.mkdir(mode=0o700)
    receipt = directory / "forward097.reconciled.json"
    original_write = os.write
    calls = 0

    def fail_after_partial(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(fd, data[:4])
        raise OSError("simulated write failure")

    monkeypatch.setattr(module.os, "write", fail_after_partial)
    with pytest.raises(OSError, match="simulated write failure"):
        module._write_exclusive(receipt, b'{"status":"verified"}\n', owner_uid=owner)

    assert not receipt.exists()
    assert list(directory.glob(".forward097.reconciled.json.*.tmp")) == []


@pytest.mark.parametrize(
    "field,value", [("Schema heads", "202605310098"), ("Backend image", "latest")]
)
def test_deployed_receipt_rejects_schema_or_mutable_image(field, value):
    raw = (
        "Status: Deployed — Formal Acceptance Pending\n"
        f"Commit: {REPLACEMENT_SHA}\nCI run: {CI_RUN}\nCI attempt: {CI_ATTEMPT}\n"
        f"Deploy run: {DEPLOY_RUN}\nDeploy attempt: {DEPLOY_ATTEMPT}\n"
        "UTC: 2026-11-20T18:00:00Z\nFrontend asset: /assets/index-test.js\n"
        f"Asset SHA-256: {ASSET_HASH}\nService worker SHA-256: {WORKER_HASH}\n"
        f"Backend image: {BACKEND_ID}\nFrontend image: {FRONTEND_ID}\n"
        f"Schema heads: {module.SCHEMA}\n"
    ).replace(
        f"{field}: {module.SCHEMA}" if field == "Schema heads" else f"{field}: {BACKEND_ID}",
        f"{field}: {value}",
    )
    with pytest.raises(module.ReconciliationError):
        module.parse_deployed_receipt(raw.encode())
