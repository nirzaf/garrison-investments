#!/usr/bin/env python3
"""Root-controlled, append-only reconciliation for the 2026-11-19 forward-097 incident.

This tool never edits or removes the original forward097.* records. It only writes
forward097.reconciled.json after a different, green release is active and verified.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE = Path("/opt/garrison-portal")
STATE = BASE / "deploy"
RELEASES = BASE / "releases"
PORTAL = "https://portal.garrisons.lk"
INCIDENT_ID = "forward097-2026-11-19"
SCHEMA = "202605310097"
UNATTESTED_SHA = "60be439923df92e127540ffc9f0b509879797c1b"
UNATTESTED_CI_RUN = 44726033272
UNATTESTED_BACKEND_IMAGE_ID = (
    "sha256:752ad64dbcd86e33859f49e08621635c4ec50f44ce6cd28b7fee798785591595"
)
UNATTESTED_BACKEND_REF = f"garrison-portal-release-backend:{UNATTESTED_SHA}"
EVIDENCE_HASHES = {
    "forward097.attempt": "ab32230bb12aff52ee0e01b730c8a482ff938f278722a37b88619124f61d5285",
    "forward097.used": "6008a1187648ab3a75a26cdb2aaedf51c64c10d563a4250415a4edd5a02a7b16",
    "forward097.reopen-commit": "647afe4fd22168071a4e8bb8116d73f51eabd26c21bfd16d413524036258283f",
    "forward097.recovery-attempt": (
        "a48925b4bf31f3453d8694c688a95beac033457d1638ab0c0c6eb5b6b8a6c30e"
    ),
}


class ReconciliationError(RuntimeError):
    """A fail-closed incident or release validation error."""


def _secure_directory(path: Path, owner_uid: int) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ReconciliationError(f"Required directory is unavailable: {path}") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid or info.st_mode & 0o022:
        raise ReconciliationError(f"Directory is not protected: {path}")


def _secure_read(path: Path, owner_uid: int, *, mode: int = 0o600) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ReconciliationError(f"Required evidence file is unavailable: {path.name}") from exc
    try:
        info = os.fstat(fd)
        current = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)
            or info.st_uid != owner_uid
            or stat.S_IMODE(info.st_mode) != mode
        ):
            raise ReconciliationError(f"Evidence file has unsafe ownership or mode: {path.name}")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_line(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"Invalid {label} evidence record") from exc
    if not isinstance(value, dict):
        raise ReconciliationError(f"Invalid {label} evidence record")
    return value


def validate_incident_evidence(
    state_dir: Path = STATE, *, owner_uid: int = 0
) -> dict[str, dict[str, int | str]]:
    """Check exact historical bytes and semantics without changing the evidence."""
    evidence: dict[str, dict[str, int | str]] = {}
    records: dict[str, bytes] = {}
    for name, expected in EVIDENCE_HASHES.items():
        path = state_dir / name
        before = path.lstat()
        raw = _secure_read(path, owner_uid)
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ReconciliationError(
                f"Historical incident evidence changed while being read: {name}"
            )
        actual = _sha256(raw)
        if actual != expected:
            raise ReconciliationError(f"Historical incident evidence changed: {name}")
        evidence[name] = {
            "sha256": actual,
            "size_bytes": after.st_size,
            "owner_uid": after.st_uid,
            "group_gid": after.st_gid,
            "mode": oct(stat.S_IMODE(after.st_mode)),
            "mtime_ns": after.st_mtime_ns,
            "mtime_utc": datetime.fromtimestamp(after.st_mtime_ns / 1_000_000_000, UTC).isoformat(
                timespec="microseconds"
            ),
        }
        records[name] = raw

    attempt = records["forward097.attempt"].decode("utf-8").splitlines()
    if attempt[0] != "Forward093-to097 in progress; no secured-backup guarantee.":
        raise ReconciliationError("Original forward migration marker is not recognized")
    if [_json_line(line, "attempt").get("phase") for line in attempt[1:]] != [
        "permit_consumed_before_migration",
        "schema097_verified",
        "contained_failure",
    ]:
        raise ReconciliationError("Original forward attempt phases do not match the incident")

    used = _json_line(records["forward097.used"].decode("utf-8"), "permit-use")
    if (
        used.get("sha") != "9da001055094115af77ee5f9611cae253fd3bc49"
        or used.get("source") != "202605310093"
        or used.get("target") != SCHEMA
        or used.get("ci_run") != 44506276841
        or used.get("deploy_run") != 44513571888
        or used.get("mode") != "forward-only-093-to-097"
    ):
        raise ReconciliationError("Consumed permit does not match the recorded 093-to-097 release")

    committed = _json_line(records["forward097.reopen-commit"].decode("utf-8"), "reopen-commit")
    if (
        committed.get("sha") != used.get("sha")
        or committed.get("ci_run") != str(used.get("ci_run"))
        or committed.get("deploy_run") != str(used.get("deploy_run"))
        or committed.get("schema") != SCHEMA
        or committed.get("state") != "verified-serving-committed"
        or committed.get("receipt") != "pending-observed-reopen"
    ):
        raise ReconciliationError("Forward reopen commit does not bind to the consumed permit")

    recovery_lines = records["forward097.recovery-attempt"].decode("utf-8").splitlines()
    recovery = [_json_line(line, "recovery") for line in recovery_lines]
    phases = [item.get("phase") for item in recovery]
    if (
        not recovery
        or recovery[0].get("original_run") != 44513571888
        or phases
        != [
            "authorized_forward_recovery_started",
            "recovered_guarded_smoke_verified",
            "reopening_authorized_after_writer_verification",
            "writers_started_after_checkpoint",
            "ingress_reopened",
            "recovery_observed_complete",
        ]
    ):
        raise ReconciliationError("Recorded recovery phases are incomplete or inconsistent")
    return evidence


def validate_unattested_predecessor(release_dir: Path, *, owner_uid: int = 0) -> dict[str, str]:
    """Classify only the exact observed predecessor, refusing any pre-existing receipt."""
    try:
        info = release_dir.lstat()
    except OSError as exc:
        raise ReconciliationError("Observed predecessor release is missing") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid or info.st_mode & 0o022:
        raise ReconciliationError("Observed predecessor release path is unsafe")
    if release_dir.name != UNATTESTED_SHA:
        raise ReconciliationError("Current release no longer matches the inspected predecessor")
    for receipt_name in ("SOURCE_COMMIT", "DEPLOYED"):
        receipt = release_dir / receipt_name
        if receipt.exists() or receipt.is_symlink():
            raise ReconciliationError("Predecessor has a receipt; independent review is required")
    images = _secure_read(release_dir / ".images.env", owner_uid)
    image_values = _parse_image_env(images)
    if image_values.get("GARRISON_BACKEND_IMAGE") != UNATTESTED_BACKEND_REF:
        raise ReconciliationError("Predecessor backend image reference changed")
    return {
        "classification": "UNATTESTED",
        "sha": UNATTESTED_SHA,
        "ci_run": str(UNATTESTED_CI_RUN),
        "backend_image_ref": UNATTESTED_BACKEND_REF,
        "backend_image_id": UNATTESTED_BACKEND_IMAGE_ID,
        "reason": (
            "no SOURCE_COMMIT or DEPLOYED receipt; associated CI failed; "
            "no Production deployment record"
        ),
    }


def _parse_image_env(raw: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        if not line:
            continue
        key, sep, value = line.partition("=")
        if (
            not sep
            or key in values
            or key
            not in {
                "GARRISON_BACKEND_IMAGE",
                "GARRISON_FRONTEND_IMAGE",
            }
        ):
            raise ReconciliationError("Release image manifest is invalid")
        if not value or "\x00" in value or "\n" in value:
            raise ReconciliationError("Release image reference is invalid")
        values[key] = value
    if set(values) != {"GARRISON_BACKEND_IMAGE", "GARRISON_FRONTEND_IMAGE"}:
        raise ReconciliationError("Release image manifest is incomplete")
    return values


def parse_deployed_receipt(raw: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        key, sep, value = line.partition(": ")
        if sep:
            if key in values:
                raise ReconciliationError("Deployment receipt has duplicate fields")
            values[key] = value
    required = {
        "Status",
        "Commit",
        "CI run",
        "CI attempt",
        "Deploy run",
        "Deploy attempt",
        "UTC",
        "Backend image",
        "Frontend image",
        "Schema heads",
    }
    if not required <= values.keys():
        raise ReconciliationError("Deployment receipt is incomplete")
    if values["Status"] != "Deployed — Formal Acceptance Pending":
        raise ReconciliationError("Deployment receipt status is not a successful release")
    if not re.fullmatch(r"[0-9a-f]{40}", values["Commit"]):
        raise ReconciliationError("Deployment receipt commit is invalid")
    for field in ("CI run", "CI attempt", "Deploy run", "Deploy attempt"):
        if not re.fullmatch(r"[1-9][0-9]*", values[field]):
            raise ReconciliationError(f"Deployment receipt {field} is invalid")
    if values["Schema heads"].split() != [SCHEMA]:
        raise ReconciliationError("Replacement did not keep the exact production schema")
    for field in ("Backend image", "Frontend image"):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", values[field]):
            raise ReconciliationError(f"Deployment receipt {field} is invalid")
    try:
        deployed_at = datetime.fromisoformat(values["UTC"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReconciliationError("Deployment receipt UTC timestamp is invalid") from exc
    if deployed_at.tzinfo is None or deployed_at.utcoffset() != UTC.utcoffset(deployed_at):
        raise ReconciliationError("Deployment receipt timestamp must be UTC")
    if not re.fullmatch(r"/assets/index-[A-Za-z0-9_-]+\.js", values.get("Frontend asset", "")):
        raise ReconciliationError("Deployment receipt frontend asset path is invalid")
    for field in ("Asset SHA-256", "Service worker SHA-256"):
        if not re.fullmatch(r"[0-9a-f]{64}", values.get(field, "")):
            raise ReconciliationError(f"Deployment receipt {field} is invalid")
    return values


def _run(command: list[str], *, timeout: int = 20) -> bytes:
    try:
        result = subprocess.run(command, capture_output=True, check=True, timeout=timeout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ReconciliationError(f"Required read-only verification failed: {command[0]}") from exc
    return result.stdout


def _docker_json(*args: str) -> Any:
    raw = _run(["docker", *args])
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReconciliationError("Docker returned invalid inspection data") from exc


def _schema_head() -> str:
    raw = _run(
        [
            "docker",
            "exec",
            "garrison-portal-postgres-1",
            "sh",
            "-ec",
            (
                'psql -XqAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" '
                '-d "$POSTGRES_DB" -c "select version_num from alembic_version"'
            ),
        ]
    )
    value = raw.decode("utf-8").strip()
    if value != SCHEMA:
        raise ReconciliationError("Live schema differs from 202605310097")
    return value


def _container_snapshot(name: str) -> dict[str, Any]:
    value = _docker_json("inspect", name)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ReconciliationError(f"Container identity is unavailable: {name}")
    item = value[0]
    state = item.get("State") or {}
    labels = (item.get("Config") or {}).get("Labels") or {}
    if (
        not state.get("Running")
        or state.get("Status") != "running"
        or labels.get("com.docker.compose.project") != "garrison-portal"
    ):
        raise ReconciliationError(
            f"Production service is not running under the expected project: {name}"
        )
    return {
        "container_id": item.get("Id"),
        "image_ref": (item.get("Config") or {}).get("Image"),
        "image_id": item.get("Image"),
        "status": state.get("Status"),
        "healthy": (state.get("Health") or {}).get("Status"),
        "started_at": state.get("StartedAt"),
        "service": labels.get("com.docker.compose.service"),
    }


def _beat_started(container: dict[str, Any], name: str) -> bool:
    command = ["docker", "logs", "--since", str(container["started_at"]), name]
    try:
        result = subprocess.run(command, capture_output=True, check=True, timeout=30)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ReconciliationError(
            f"Required read-only verification failed: {command[0]}"
        ) from exc
    # Docker preserves the container's stdout and stderr as separate streams.
    # Celery's startup marker is written to stderr by the current beat command.
    raw = result.stdout + b"\n" + result.stderr
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(value, dict)
            and value.get("logger") == "celery.beat"
            and value.get("message") == "beat: Starting..."
        ):
            return True
    raise ReconciliationError("Celery beat startup was not observed for the active container")


def _worker_ping(name: str) -> int:
    raw = _run(
        [
            "docker",
            "exec",
            name,
            "celery",
            "-A",
            "app.tasks.celery_app.celery_app",
            "inspect",
            "ping",
            "--json",
            "--timeout=5",
        ],
        timeout=15,
    )
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReconciliationError("Celery worker returned invalid ping data") from exc
    if (
        not isinstance(result, dict)
        or not result
        or any(value != {"ok": "pong"} for value in result.values())
    ):
        raise ReconciliationError("Celery worker ping did not return a clean pong")
    return len(result)


def _http(url: str) -> bytes:
    return _run(["curl", "--fail", "--silent", "--show-error", "--max-time", "12", url], timeout=15)


def _runtime_snapshot(
    release_dir: Path, fields: dict[str, str], release_sha: str
) -> dict[str, Any]:
    images = _parse_image_env(_secure_read(release_dir / ".images.env", 0))
    backend_ref = images["GARRISON_BACKEND_IMAGE"]
    frontend_ref = images["GARRISON_FRONTEND_IMAGE"]
    if backend_ref != f"garrison-portal-release-backend:{release_sha}":
        raise ReconciliationError(
            "Active backend image reference is not bound to the replacement SHA"
        )
    if frontend_ref != f"garrison-portal-release-frontend:{release_sha}":
        raise ReconciliationError(
            "Active frontend image reference is not bound to the replacement SHA"
        )

    backend = _container_snapshot("garrison-portal-backend-1")
    worker = _container_snapshot("garrison-portal-celery_worker-1")
    beat = _container_snapshot("garrison-portal-celery_beat-1")
    nginx = _container_snapshot("garrison-portal-nginx-1")
    image_id = fields["Backend image"]
    frontend_id = (
        _run(["docker", "image", "inspect", "--format", "{{.Id}}", frontend_ref]).decode().strip()
    )
    backend_id = (
        _run(["docker", "image", "inspect", "--format", "{{.Id}}", backend_ref]).decode().strip()
    )
    if fields["Frontend image"] != frontend_id:
        raise ReconciliationError(
            "Frontend image identity differs from the successful deployment receipt"
        )
    if backend_id != image_id:
        raise ReconciliationError(
            "Backend image identity differs from the successful deployment receipt"
        )
    for label, container in (("backend", backend), ("worker", worker), ("beat", beat)):
        expected_service = {"backend": "backend", "worker": "celery_worker", "beat": "celery_beat"}[
            label
        ]
        if (
            container["service"] != expected_service
            or container["image_id"] != image_id
            or container["image_ref"] != backend_ref
        ):
            raise ReconciliationError(f"Active {label} image is not the verified replacement image")
    if backend["healthy"] != "healthy":
        raise ReconciliationError("Backend health check is not healthy")
    expected_services = {
        "worker": "celery_worker",
        "beat": "celery_beat",
        "nginx": "nginx",
    }
    for label, container in (("worker", worker), ("beat", beat), ("nginx", nginx)):
        if container["service"] != expected_services[label]:
            raise ReconciliationError(f"Unexpected Compose service identity for {label}")

    schema = _schema_head()
    worker_count = _worker_ping("garrison-portal-celery_worker-1")
    beat_started = _beat_started(beat, "garrison-portal-celery_beat-1")
    try:
        readiness = json.loads(_http(f"{PORTAL}/health/readiness"))
    except json.JSONDecodeError as exc:
        raise ReconciliationError("Portal readiness returned invalid JSON") from exc
    if readiness != {"status": "ready", "database": "connected"}:
        raise ReconciliationError("Portal readiness did not report a connected database")

    asset_path = fields.get("Frontend asset", "")
    if not re.fullmatch(r"/assets/index-[A-Za-z0-9_-]+\.js", asset_path):
        raise ReconciliationError("Deployment receipt frontend asset path is invalid")
    hashes = {
        "asset": fields.get("Asset SHA-256", ""),
        "service_worker": fields.get("Service worker SHA-256", ""),
    }
    for key, digest in hashes.items():
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ReconciliationError(f"Deployment receipt {key} hash is invalid")
    served_login = _http(f"{PORTAL}/login")
    served_asset = _http(f"{PORTAL}{asset_path}")
    served_worker = _http(f"{PORTAL}/sw.js")
    if (
        _sha256(served_asset) != hashes["asset"]
        or _sha256(served_worker) != hashes["service_worker"]
    ):
        raise ReconciliationError(
            "Served frontend asset or worker differs from the deployment receipt"
        )
    if not served_login:
        raise ReconciliationError("Portal login page is empty")

    return {
        "schema_head": schema,
        "backend_image_ref": backend_ref,
        "backend_image_id": image_id,
        "frontend_image_ref": frontend_ref,
        "frontend_image_id": fields["Frontend image"],
        "services": {"backend": backend, "worker": worker, "beat": beat, "nginx": nginx},
        "worker_ping_count": worker_count,
        "beat_started": beat_started,
        "readiness": readiness,
        "frontend_asset_sha256": hashes["asset"],
        "service_worker_sha256": hashes["service_worker"],
    }


def _current_release(state_dir: Path, releases_dir: Path) -> Path:
    current = state_dir / "current"
    try:
        link = current.lstat()
    except OSError as exc:
        raise ReconciliationError("Production current pointer is missing") from exc
    if not stat.S_ISLNK(link.st_mode):
        raise ReconciliationError("Production current pointer is not a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(releases_dir.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ReconciliationError(
            "Production current pointer escapes the release directory"
        ) from exc
    return resolved


def _validate_replacement_release(
    release_dir: Path,
    *,
    expected_sha: str,
    ci_run: str,
    ci_attempt: str,
    deploy_run: str,
    deploy_attempt: str,
    owner_uid: int,
) -> tuple[dict[str, str], bytes, bytes]:
    _secure_directory(release_dir, owner_uid)
    source = _secure_read(release_dir / "SOURCE_COMMIT", owner_uid).decode("ascii").strip()
    deployed_raw = _secure_read(release_dir / "DEPLOYED", owner_uid)
    fields = parse_deployed_receipt(deployed_raw)
    if (
        source != expected_sha
        or fields["Commit"] != expected_sha
        or fields["CI run"] != ci_run
        or fields["CI attempt"] != ci_attempt
        or fields["Deploy run"] != deploy_run
        or fields["Deploy attempt"] != deploy_attempt
    ):
        raise ReconciliationError(
            "Successful deployment receipt does not match the authorized invocation"
        )
    return fields, deployed_raw, _secure_read(release_dir / ".images.env", owner_uid)


def _reconciliation_path(state_dir: Path) -> Path:
    return state_dir / "forward097.reconciled.json"


def _verify_reconciliation_record(
    state_dir: Path, releases_dir: Path, *, owner_uid: int
) -> dict[str, Any]:
    raw = _secure_read(_reconciliation_path(state_dir), owner_uid)
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReconciliationError("Incident reconciliation receipt is invalid") from exc
    if (
        not isinstance(record, dict)
        or record.get("schema_version") != 1
        or record.get("incident_id") != INCIDENT_ID
        or record.get("status") != "reconciled_after_verified_replacement"
    ):
        raise ReconciliationError("Incident reconciliation receipt is not recognized")
    evidence = validate_incident_evidence(state_dir, owner_uid=owner_uid)
    if record.get("historical_evidence_sha256") != evidence:
        raise ReconciliationError(
            "Incident reconciliation receipt does not bind the preserved evidence"
        )
    replacement = record.get("replacement")
    if not isinstance(replacement, dict):
        raise ReconciliationError("Incident reconciliation receipt lacks its replacement release")
    expected_prior = validate_unattested_predecessor(
        releases_dir / UNATTESTED_SHA, owner_uid=owner_uid
    )
    if record.get("prior_release") != expected_prior:
        raise ReconciliationError("Prior release disposition must remain UNATTESTED")
    try:
        release_path = Path(replacement["release_path"])
        release_info = release_path.lstat()
        if (
            not stat.S_ISDIR(release_info.st_mode)
            or release_info.st_uid != owner_uid
            or release_info.st_mode & 0o022
            or not release_path.name.startswith(f"{replacement['sha']}.")
        ):
            raise ReconciliationError("Incident replacement release directory is unsafe")
        release_dir = release_path.resolve(strict=True)
        release_dir.relative_to(releases_dir.resolve(strict=True))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise ReconciliationError("Incident replacement release path is invalid") from exc
    deployed_raw = _secure_read(release_dir / "DEPLOYED", owner_uid)
    if _sha256(deployed_raw) != replacement.get("deployed_receipt_sha256"):
        raise ReconciliationError("Bound replacement deployment receipt has changed")
    source = _secure_read(release_dir / "SOURCE_COMMIT", owner_uid).decode("ascii").strip()
    fields = parse_deployed_receipt(deployed_raw)
    if (
        source != replacement.get("sha")
        or fields.get("Commit") != replacement.get("sha")
        # DEPLOYED is written from `tr '\\n' ' '` and therefore has one trailing
        # separator after the final head. Validate the semantic list, as the
        # receipt parser already does, instead of comparing that formatting byte.
        or fields.get("Schema heads", "").split() != [SCHEMA]
        or fields.get("Backend image") != replacement.get("backend_image_id")
        or fields.get("CI run") != replacement.get("ci_run")
        or fields.get("CI attempt") != replacement.get("ci_attempt")
        or fields.get("Deploy run") != replacement.get("deploy_run")
        or fields.get("Deploy attempt") != replacement.get("deploy_attempt")
    ):
        raise ReconciliationError(
            "Bound replacement release no longer matches the reconciliation receipt"
        )
    if (
        not isinstance(replacement.get("main_sha"), str)
        or not re.fullmatch(r"[0-9a-f]{40}", replacement["main_sha"])
        or any(
            not isinstance(replacement.get(key), str)
            or not re.fullmatch(r"[1-9][0-9]*", replacement[key])
            for key in ("main_ci_run", "main_ci_attempt")
        )
    ):
        raise ReconciliationError("Reconciliation record lacks exact deployment-main CI identity")
    image_refs = _parse_image_env(_secure_read(release_dir / ".images.env", owner_uid))
    if replacement.get("backend_image_ref") != image_refs.get(
        "GARRISON_BACKEND_IMAGE"
    ) or replacement.get("frontend_image_ref") != image_refs.get("GARRISON_FRONTEND_IMAGE"):
        raise ReconciliationError("Bound replacement image references changed")
    recorded_at = record.get("recorded_at_utc")
    if not isinstance(recorded_at, str):
        raise ReconciliationError("Incident reconciliation timestamp is missing")
    try:
        timestamp = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReconciliationError("Incident reconciliation timestamp is invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != UTC.utcoffset(timestamp):
        raise ReconciliationError("Incident reconciliation timestamp must be UTC")
    return record


def _write_exclusive(path: Path, raw: bytes, *, owner_uid: int) -> None:
    _secure_directory(path.parent, owner_uid)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    fd = os.open(temporary, flags, 0o600)
    published = False
    try:
        if os.geteuid() == 0:
            os.fchown(fd, owner_uid, -1)
        elif os.fstat(fd).st_uid != owner_uid:
            raise ReconciliationError(
                "Cannot create a reconciliation receipt for the expected owner"
            )
        os.fchmod(fd, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise ReconciliationError("Could not finish writing the reconciliation record")
            view = view[written:]
        os.fsync(fd)
        os.link(temporary, path, follow_symlinks=False)
        published = True
    finally:
        os.close(fd)
        if not published:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    temporary.unlink()
    dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def assert_lock_held(state_dir: Path = STATE, *, lock_fd: int = 9, owner_uid: int = 0) -> None:
    lock_path = state_dir / "deploy.lock"
    try:
        path_info = lock_path.lstat()
        fd_info = os.fstat(lock_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as exc:
        raise ReconciliationError("The production deployment lock is not held") from exc
    if (
        not stat.S_ISREG(path_info.st_mode)
        or path_info.st_uid != owner_uid
        or path_info.st_mode & 0o022
        or (path_info.st_dev, path_info.st_ino) != (fd_info.st_dev, fd_info.st_ino)
    ):
        raise ReconciliationError(
            "The lock descriptor does not identify the protected deployment lock"
        )


def preflight(
    state_dir: Path = STATE,
    releases_dir: Path = RELEASES,
    *,
    owner_uid: int = 0,
) -> dict[str, Any]:
    evidence = validate_incident_evidence(state_dir, owner_uid=owner_uid)
    current = _current_release(state_dir, releases_dir)
    prior = validate_unattested_predecessor(current, owner_uid=owner_uid)
    services = {
        name: _container_snapshot(f"garrison-portal-{name}-1")
        for name in ("backend", "celery_worker", "celery_beat", "nginx")
    }
    for name in ("backend", "celery_worker", "celery_beat"):
        item = services[name]
        if (
            item["image_ref"] != UNATTESTED_BACKEND_REF
            or item["image_id"] != UNATTESTED_BACKEND_IMAGE_ID
        ):
            raise ReconciliationError(
                "Observed predecessor containers no longer match the inspected image"
            )
        expected_service = {
            "backend": "backend",
            "celery_worker": "celery_worker",
            "celery_beat": "celery_beat",
        }[name]
        if item["service"] != expected_service:
            raise ReconciliationError("Observed predecessor Compose service identity changed")
    if services["nginx"]["service"] != "nginx":
        raise ReconciliationError("Observed predecessor ingress service identity changed")
    if services["backend"]["healthy"] != "healthy":
        raise ReconciliationError(
            "Predecessor backend is not healthy; replacement preflight is unsafe"
        )
    schema = _schema_head()
    if schema != SCHEMA:
        raise ReconciliationError("Replacement preflight requires schema 202605310097")
    try:
        readiness = json.loads(_http(f"{PORTAL}/health/readiness"))
    except json.JSONDecodeError as exc:
        raise ReconciliationError("Current portal readiness returned invalid JSON") from exc
    if readiness != {"status": "ready", "database": "connected"}:
        raise ReconciliationError("Current portal is not ready for a no-migration replacement")
    return {
        "status": "replacement-preflight-passed",
        "incident_id": INCIDENT_ID,
        "prior_release": prior,
        "historical_evidence_sha256": evidence,
        "schema_head": schema,
        "current_services": services,
        "readiness": readiness,
    }


def close_after_verified_replacement(
    state_dir: Path = STATE,
    releases_dir: Path = RELEASES,
    *,
    expected_sha: str,
    ci_run: str,
    ci_attempt: str,
    main_sha: str,
    main_ci_run: str,
    main_ci_attempt: str,
    deploy_run: str,
    deploy_attempt: str,
    owner_uid: int = 0,
) -> tuple[dict[str, Any], bool]:
    existing_path = _reconciliation_path(state_dir)
    if existing_path.exists() or existing_path.is_symlink():
        existing = _verify_reconciliation_record(state_dir, releases_dir, owner_uid=owner_uid)
        replacement = existing.get("replacement", {})
        if (
            replacement.get("sha") == expected_sha
            and replacement.get("ci_run") == ci_run
            and replacement.get("ci_attempt") == ci_attempt
            and replacement.get("main_sha") == main_sha
            and replacement.get("main_ci_run") == main_ci_run
            and replacement.get("main_ci_attempt") == main_ci_attempt
            and replacement.get("deploy_run") == deploy_run
            and replacement.get("deploy_attempt") == deploy_attempt
        ):
            return existing, False
        raise ReconciliationError("Incident was already reconciled to another verified release")

    evidence = validate_incident_evidence(state_dir, owner_uid=owner_uid)
    current = _current_release(state_dir, releases_dir)
    if current.name.split(".", 1)[0] != expected_sha or expected_sha == UNATTESTED_SHA:
        raise ReconciliationError("Current release is not the selected replacement candidate")
    prior = validate_unattested_predecessor(releases_dir / UNATTESTED_SHA, owner_uid=owner_uid)
    fields, deployed_raw, _ = _validate_replacement_release(
        current,
        expected_sha=expected_sha,
        ci_run=ci_run,
        ci_attempt=ci_attempt,
        deploy_run=deploy_run,
        deploy_attempt=deploy_attempt,
        owner_uid=owner_uid,
    )
    runtime = _runtime_snapshot(current, fields, expected_sha)
    image_refs = _parse_image_env(_secure_read(current / ".images.env", owner_uid))
    if (
        runtime.get("schema_head") != SCHEMA
        or runtime.get("backend_image_id") != fields["Backend image"]
        or runtime.get("frontend_image_id") != fields["Frontend image"]
        or runtime.get("backend_image_ref") != image_refs["GARRISON_BACKEND_IMAGE"]
        or runtime.get("frontend_image_ref") != image_refs["GARRISON_FRONTEND_IMAGE"]
        or runtime.get("readiness") != {"status": "ready", "database": "connected"}
        or type(runtime.get("worker_ping_count")) is not int
        or runtime["worker_ping_count"] < 1
        or runtime.get("beat_started") is not True
        or runtime.get("frontend_asset_sha256") != fields["Asset SHA-256"]
        or runtime.get("service_worker_sha256") != fields["Service worker SHA-256"]
    ):
        raise ReconciliationError(
            "Replacement runtime did not satisfy exact image, schema, ingress, and worker checks"
        )
    replacement = {
        "sha": expected_sha,
        "ci_run": ci_run,
        "ci_attempt": ci_attempt,
        "main_sha": main_sha,
        "main_ci_run": main_ci_run,
        "main_ci_attempt": main_ci_attempt,
        "deploy_run": deploy_run,
        "deploy_attempt": deploy_attempt,
        "release_path": str(current),
        "deployed_receipt_sha256": _sha256(deployed_raw),
        "backend_image_ref": runtime["backend_image_ref"],
        "backend_image_id": runtime["backend_image_id"],
        "frontend_image_ref": runtime["frontend_image_ref"],
        "frontend_image_id": runtime["frontend_image_id"],
        "schema_head": runtime["schema_head"],
        "verification": runtime,
    }
    record = {
        "schema_version": 1,
        "incident_id": INCIDENT_ID,
        "status": "reconciled_after_verified_replacement",
        "recorded_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "prior_release": prior,
        "historical_evidence_sha256": evidence,
        "replacement": replacement,
        "deployed_receipt_fields": fields,
    }
    raw = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        _write_exclusive(existing_path, raw, owner_uid=owner_uid)
    except FileExistsError:
        existing = _verify_reconciliation_record(state_dir, releases_dir, owner_uid=owner_uid)
        replacement = existing.get("replacement", {})
        if replacement.get("sha") == expected_sha and replacement.get(
            "deployed_receipt_sha256"
        ) == _sha256(deployed_raw):
            return existing, False
        raise ReconciliationError(
            "Incident reconciliation receipt was concurrently created"
        ) from None
    return record, True


def _require_root() -> None:
    if os.geteuid() != 0:
        raise ReconciliationError("Incident reconciliation is root-controlled")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "preflight", "close", "verify"))
    parser.add_argument("--lock-fd", type=int, default=9)
    parser.add_argument("--sha")
    parser.add_argument("--ci-run")
    parser.add_argument("--ci-attempt")
    parser.add_argument("--main-sha")
    parser.add_argument("--main-ci-run")
    parser.add_argument("--main-ci-attempt")
    parser.add_argument("--deploy-run")
    parser.add_argument("--deploy-attempt")
    args = parser.parse_args(argv)
    try:
        _require_root()
        for directory in (Path("/opt"), BASE, STATE, RELEASES):
            _secure_directory(directory, 0)
        assert_lock_held(STATE, lock_fd=args.lock_fd, owner_uid=0)
        if args.command == "check":
            result: Any = {
                "status": "incident-evidence-verified",
                "hashes": validate_incident_evidence(),
            }
        elif args.command == "preflight":
            result = preflight()
        elif args.command == "close":
            required = (
                args.sha,
                args.ci_run,
                args.ci_attempt,
                args.main_sha,
                args.main_ci_run,
                args.main_ci_attempt,
                args.deploy_run,
                args.deploy_attempt,
            )
            if not all(required):
                raise ReconciliationError(
                    "close requires exact release, CI, and deployment identities"
                )
            result, created = close_after_verified_replacement(
                expected_sha=args.sha,
                ci_run=args.ci_run,
                ci_attempt=args.ci_attempt,
                main_sha=args.main_sha,
                main_ci_run=args.main_ci_run,
                main_ci_attempt=args.main_ci_attempt,
                deploy_run=args.deploy_run,
                deploy_attempt=args.deploy_attempt,
            )
            result = {"created": created, "record": result}
        else:
            result = _verify_reconciliation_record(STATE, RELEASES, owner_uid=0)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ReconciliationError, ValueError) as exc:
        print(f"incident reconciliation refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
