"""Operational adapters for the existing audit, backup, and deployment interfaces."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import socket
import stat
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv.parser import parse_stream
from pydantic import ValidationError

from app.business_policy import BusinessPolicy
from app.utils.redaction import redact_payload
from scripts import health_monitor, log_cli, release_contract
from scripts.backup_set_contract import BackupSetError, read_policy
from scripts.garrisonctl_common import (
    AUTH,
    CONFLICT,
    CONNECTION,
    FAILED,
    CLIError,
    Context,
    Registry,
    Result,
    checked_plan,
    load_json,
    uuid_arg,
)

HOST_STATE = Path("/opt/garrison-portal/deploy")
POLICY_FIELDS = (
    "business_currency",
    "business_timezone",
    "material_approval_threshold",
)
ENV_FIELDS = {name.upper(): name for name in POLICY_FIELDS}
APPROVAL_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/#-]{0,127}")
SHA256 = re.compile(r"[a-f0-9]{64}")
AUDIT_FILTERS = ("query", "action", "entity_type", "user_id")
STREAM_FILTERS = (
    *AUDIT_FILTERS,
    "event_type",
    "severity",
    "endpoint",
    "source_service",
    "storage_tier",
    "created_from",
    "session_id_filter",
)
LOG_FILTERS = (*STREAM_FILTERS, "request_id", "ip_address", "status_code", "created_to")
LOG_OUTPUT_FIELDS = (
    "id",
    "user_id",
    "event_type",
    "severity",
    "action",
    "entity_type",
    "entity_id",
    "request_id",
    "endpoint",
    "http_method",
    "status_code",
    "source_service",
    "storage_tier",
    "created_at",
    "archived_at",
    "retention_until",
)


def read_policy_proposal(path: Path) -> BusinessPolicy:
    data = load_json(path, max_bytes=64 * 1024)
    if not isinstance(data, dict) or set(data) != set(POLICY_FIELDS):
        raise CLIError("Supply all three business settings and no other fields.")
    return _business_policy(data)


def _business_policy(data: dict[str, Any]) -> BusinessPolicy:
    try:
        return BusinessPolicy.model_validate(data)
    except ValidationError as error:
        details = [
            {"field": ".".join(str(part) for part in issue["loc"]), "type": issue["type"]}
            for issue in error.errors(include_input=False, include_url=False, include_context=False)
        ]
        raise CLIError("The business policy is invalid.", details=details) from None


def _protected_read(path: Path, *, limit: int = 64 * 1024, private: bool = False) -> bytes:
    with release_contract.open_evidence(path, protected=True) as stream:
        mode = os.fstat(stream.fileno())
        if private and (mode.st_mode & 0o077 or mode.st_nlink != 1):
            raise CLIError("Production configuration must be an owner-only regular file.", AUTH)
        content = stream.read(limit + 1)
    if not content or len(content) > limit:
        raise CLIError("The protected host file is empty or exceeds its allowed size.", CONFLICT)
    return content


def _host_policy(raw: bytes) -> tuple[BusinessPolicy, list[tuple[str | None, str]]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise CLIError("The protected production environment file is invalid.", CONFLICT) from None
    values = {}
    lines = []
    seen = set()
    for binding in parse_stream(StringIO(text)):
        key = binding.key
        if binding.error or (key is not None and key.upper() in seen):
            raise CLIError("The protected production environment file is ambiguous.", CONFLICT)
        if key is not None:
            seen.add(key.upper())
            if key.upper() in ENV_FIELDS:
                if key not in ENV_FIELDS or binding.value is None:
                    raise CLIError("Business settings require exact uppercase assignments.")
                values[ENV_FIELDS[key]] = binding.value
        lines.append((key, binding.original.string))
    return _business_policy(values), lines


def _effective_remote_policy(ctx: Context) -> BusinessPolicy:
    payload = ctx.request("GET", "/api/v1/finance/policy")
    if not isinstance(payload, dict) or not set(POLICY_FIELDS).issubset(payload):
        raise CLIError("The API returned an incomplete business policy.", CONNECTION)
    return _business_policy({name: payload[name] for name in POLICY_FIELDS})


def _policy_plan(
    args: argparse.Namespace,
    ctx: Context,
    proposal: BusinessPolicy,
    current: BusinessPolicy,
    state: Path | None = None,
    snapshot: bytes | None = None,
) -> dict[str, Any]:
    before = current.model_dump(mode="json")
    after = proposal.model_dump(mode="json")
    changes = {
        name: {"current": before[name], "proposed": after[name]}
        for name in POLICY_FIELDS
        if getattr(current, name) != getattr(proposal, name)
    }
    impacts = {
        "business_currency": "Approval labels and finance displays require owner reconciliation.",
        "business_timezone": "Report dates and date boundaries; existing UTC instants stay intact.",
        "material_approval_threshold": "Future approval routing compares with strict greater-than.",
    }
    data: dict[str, Any] = {
        "current": before,
        "proposed": after,
        "changes": changes,
        "impacts": {name: impacts[name] for name in changes},
        "requires_currency_reconciliation": "business_currency" in changes,
    }
    if state is not None and snapshot is not None:
        data.update(
            host=socket.gethostname(),
            host_state=str(state),
            expected_state_sha256=hashlib.sha256(snapshot).hexdigest(),
        )
    return checked_plan(args, ctx, data)


def _host_state(path: Path) -> Path:
    if os.geteuid() != 0:
        raise CLIError("Run this command as the authorized host operator.", AUTH)
    if not path.is_absolute() or ".." in path.parts or path.name != "deploy":
        raise CLIError("Specify the absolute deployment state directory.")
    return path


def config_plan(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    proposal = read_policy_proposal(args.file)
    if args.host_state is None:
        current = _effective_remote_policy(ctx)
        plan = _policy_plan(args, ctx, proposal, current)
        if plan["requires_currency_reconciliation"]:
            plan["reconciliation"] = "finance policy reconciliation (administrator access)"
        return plan
    state = _host_state(args.host_state)
    try:
        snapshot = _protected_read(state / "production.env", private=True)
    except release_contract.ContractError:
        raise CLIError("The protected production configuration is unavailable.", CONFLICT) from None
    current, _ = _host_policy(snapshot)
    return _policy_plan(args, ctx, proposal, current, state, snapshot)


def config_verify(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    proposal = read_policy_proposal(args.file)
    current = _effective_remote_policy(ctx)
    expected = proposal.model_dump(mode="json")
    effective = current.model_dump(mode="json")
    differences = {
        name: {"expected": expected[name], "effective": effective[name]}
        for name in POLICY_FIELDS
        if getattr(proposal, name) != getattr(current, name)
    }
    if differences:
        raise CLIError(
            "Effective business settings differ from the reviewed proposal.",
            CONFLICT,
            data={"differences": differences},
        )
    return {"verified": True, "effective": effective}


def _render_candidate(
    lines: list[tuple[str | None, str]],
    proposal: BusinessPolicy,
    changes: dict[str, Any],
) -> bytes:
    values = proposal.model_dump(mode="json")
    replacements = {
        key: f"{key}={values[field]}\n" for key, field in ENV_FIELDS.items() if field in changes
    }
    content = "".join(
        replacements.pop(key) if key is not None and key in replacements else value
        for key, value in lines
    )
    if content and not content.endswith("\n") and replacements:
        content += "\n"
    return (content + "".join(replacements.values())).encode("utf-8")


def _private_write(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != data:
        raise OSError("Candidate verification failed.")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_candidate(
    state: Path,
    plan: dict[str, Any],
    candidate: bytes,
    approval: str,
) -> Path:
    root = state / "config-candidates"
    result = root / plan["plan_sha256"]
    installed = False
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise CLIError("Candidate storage must be root-owned and private.", AUTH)
        if os.path.lexists(result):
            raise CLIError(
                "This plan already has a candidate. Review its existing audit record.", CONFLICT
            )
        receipt = {
            "action": "business_config.candidate_prepared",
            "plan_sha256": plan["plan_sha256"],
            "expected_state_sha256": plan["expected_state_sha256"],
            "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
            "approval_reference": approval,
            "effective_uid": os.geteuid(),
            "host": socket.gethostname(),
            "recorded_at": datetime.now(UTC).isoformat(),
            "changes": plan["changes"],
            "activation": "pending_release_procedure",
        }
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=root) as directory:
            temporary = Path(directory)
            _private_write(temporary / "production.env", candidate)
            _private_write(
                temporary / "audit.json",
                (json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
            )
            _fsync_directory(temporary)
            temporary.rename(result)
            installed = True
        _fsync_directory(root)
        _fsync_directory(state)
        return result
    except OSError:
        raise CLIError(
            "The protected candidate and its audit record could not be persisted safely.",
            FAILED,
            changed=None if installed else False,
        ) from None


def config_apply(args: argparse.Namespace, ctx: Context) -> Result:
    if not args.apply or not APPROVAL_REF.fullmatch(args.approval_reference):
        raise CLIError(
            "Candidate preparation requires explicit apply and a valid approval reference."
        )
    proposal = read_policy_proposal(args.file)
    state = _host_state(args.host_state)
    try:
        with release_contract.open_evidence(state / "deploy.lock", protected=True) as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CLIError(
                    "Another deployment or maintenance operation holds the lock.", CONFLICT
                ) from None
            snapshot = _protected_read(state / "production.env", private=True)
            current, lines = _host_policy(snapshot)
            plan = _policy_plan(args, ctx, proposal, current, state, snapshot)
            if plan["requires_currency_reconciliation"]:
                raise CLIError(
                    "Currency changes require owner reconciliation and a reviewed migration.",
                    CONFLICT,
                )
            if not plan["changes"]:
                return Result({"plan_sha256": plan["plan_sha256"], "activation": "not_required"})
            candidate = _render_candidate(lines, proposal, plan["changes"])
            verified, _ = _host_policy(candidate)
            if verified != proposal:
                raise CLIError("The prepared candidate did not match the requested policy.", FAILED)
            path = _write_candidate(state, plan, candidate, args.approval_reference)
    except release_contract.ContractError:
        raise CLIError(
            "Protected deployment inputs or the lock are unavailable.", CONFLICT
        ) from None
    except OSError:
        raise CLIError("The protected deployment lock could not be acquired.", FAILED) from None
    return Result(
        {
            "candidate": str(path / "production.env"),
            "audit_record": str(path / "audit.json"),
            "plan_sha256": plan["plan_sha256"],
            "activation": "pending_release_procedure",
        },
        changed=True,
        outcome="prepared",
    )


def _filters(args: argparse.Namespace, names: tuple[str, ...]) -> dict[str, Any]:
    rename = {"query": "search", "session_id_filter": "session_id"}
    return log_cli._clean_params({rename.get(name, name): getattr(args, name) for name in names})


def _log_page(
    args: argparse.Namespace,
    ctx: Context,
    endpoint: str,
    filters: tuple[str, ...],
    *,
    cli_headers: bool,
) -> Any:
    if not 1 <= args.limit <= 200 or args.offset < 0:
        raise CLIError("Log limits must be 1 through 200 and the offset must be nonnegative.")
    headers = log_cli._cli_headers(str(uuid4())) if cli_headers else {}
    data = ctx.request(
        "GET",
        endpoint,
        params={**_filters(args, filters), "limit": args.limit, "offset": args.offset},
        headers=headers,
    )
    if (
        not isinstance(data, dict)
        or type(data.get("total")) is not int
        or not isinstance(data.get("items"), list)
        or not all(isinstance(item, dict) for item in data["items"])
    ):
        raise CLIError("The API returned an invalid log page.", CONNECTION)
    return {"items": [_log_record(item) for item in data["items"]], "total": data["total"]}


def _log_record(item: dict[str, Any]) -> dict[str, Any]:
    # Historical comments and payloads may predate server-side redaction.
    record = redact_payload({name: item[name] for name in LOG_OUTPUT_FIELDS if name in item})
    endpoint = record.get("endpoint")
    if isinstance(endpoint, str):
        try:
            record["endpoint"] = urlsplit(endpoint).path
        except ValueError:
            record["endpoint"] = None
    return record


def logs_search(args: argparse.Namespace, ctx: Context) -> Any:
    return _log_page(args, ctx, "/api/v1/log-events", LOG_FILTERS, cli_headers=True)


def audit_search(args: argparse.Namespace, ctx: Context) -> Any:
    return _log_page(args, ctx, "/api/v1/audit-logs", AUDIT_FILTERS, cli_headers=False)


def logs_tail(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    if not 1 <= args.max_events <= 200 or not 1 <= args.seconds <= 60:
        raise CLIError("Tail accepts 1 through 200 events and 1 through 60 seconds.")
    events = []
    connected = False
    try:
        with (
            health_monitor.deadline(args.seconds),
            ctx.stream(
                "GET",
                "/api/v1/log-events/stream",
                params=_filters(args, STREAM_FILTERS),
                headers=log_cli._cli_headers(str(uuid4())),
                timeout=args.seconds + 1,
            ) as response,
        ):
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type != "text/event-stream":
                raise CLIError("The API returned an invalid log stream.", CONNECTION)
            connected = True
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = release_contract.strict_json(line.removeprefix("data: ").encode())
                if not isinstance(event, dict):
                    raise CLIError("The API returned an invalid log event.", CONNECTION)
                events.append(_log_record(event))
                if len(events) >= args.max_events:
                    return {"items": events, "finished_by": "event_limit"}
    except TimeoutError:
        if connected:
            return {"items": events, "finished_by": "time_limit"}
        raise CLIError(
            "The API log stream did not connect before the deadline.", CONNECTION
        ) from None
    except release_contract.ContractError:
        raise CLIError("The API returned malformed log event JSON.", CONNECTION) from None
    raise CLIError("The log stream closed before the requested sample finished.", CONNECTION)


def backup_status(args: argparse.Namespace, _ctx: Context) -> Any:
    if not SHA256.fullmatch(args.profile_sha256):
        raise CLIError("Supply the approved monitoring profile SHA-256.")
    try:
        profile, _ = health_monitor.load_profile(args.monitor_profile, args.profile_sha256)
    except (health_monitor.MonitorError, OSError, ValueError):
        raise CLIError(
            "The approved monitoring profile could not be read or verified.", CONFLICT
        ) from None
    if profile.backup is None:
        raise CLIError("The approved monitoring profile has no independent backup check.")
    result = health_monitor.check_backup(
        profile.backup,
        profile.environment,
        datetime.now(UTC),
        profile.timeout_seconds,
        source_sha=profile.source_sha,
    )
    data = result.model_dump(mode="json", exclude_none=True)
    if not result.ok:
        raise CLIError("Independent backup status check failed.", FAILED, data=data)
    return data


def backup_verify(args: argparse.Namespace, _ctx: Context) -> dict[str, Any]:
    # The legacy backup module loads application logging during import.
    with redirect_stdout(sys.stderr):
        from scripts import backup_set

    try:
        policy = read_policy(args.policy) if args.policy is not None else None
        manifest = backup_set.load_verified_manifest(
            args.directory, policy=policy, require_authenticated=args.require_authenticated
        )
    except (BackupSetError, OSError, ValueError):
        raise CLIError("Recovery set verification failed.", FAILED) from None
    return {
        "format_version": manifest.format_version,
        "authenticated": isinstance(manifest, backup_set.AuthenticatedManifest),
        "source_sha": manifest.source_sha,
        "objects_verified": len(manifest.objects),
        "verification": "encrypted_artifacts",
    }


def release_status(args: argparse.Namespace, _ctx: Context) -> dict[str, Any]:
    state = _host_state(args.host_state)
    try:
        # Open a protected state file before resolving the one intentional release symlink.
        _protected_read(state / "compose.vps.yml")
        link = (state / "current").readlink()
        release = Path(os.path.abspath(state / link))
        if release.parent != state.parent / "releases":
            raise CLIError("The active release link is outside the releases directory.", CONFLICT)
        commit = _protected_read(release / "SOURCE_COMMIT", limit=512).decode("ascii").strip()
        receipt = release_contract.deployment_receipt_fields(_protected_read(release / "DEPLOYED"))
        release_contract.digest(commit, "release commit", length=40)
        if (
            receipt.get("Commit") != commit
            or receipt.get("Status") != "Deployed — Formal Acceptance Pending"
        ):
            raise CLIError("The deployment receipt does not match the current release.", CONFLICT)
        deployed = release_contract.utc(receipt.get("UTC"), "deployment timestamp")
        runs = {}
        for field in ("CI run", "CI attempt", "Deploy run", "Deploy attempt"):
            value = receipt.get(field)
            if not value or not re.fullmatch(r"[1-9][0-9]{0,18}", value):
                raise CLIError("The deployment receipt contains an invalid run identity.", CONFLICT)
            runs[field.lower().replace(" ", "_")] = int(value)
    except (release_contract.ContractError, UnicodeError, OSError):
        raise CLIError("The active deployment receipt could not be verified.", CONFLICT) from None
    return {
        "source_sha": commit,
        "recorded_at": deployed.isoformat(),
        "status": "deployed_formal_acceptance_pending",
        "source": "host_deployment_receipt",
        **runs,
    }


def _log_arguments(
    parser: argparse.ArgumentParser,
    filters: tuple[str, ...],
    *,
    pagination: bool = True,
) -> None:
    for name in filters:
        if name == "user_id":
            parser.add_argument("--user-id", type=uuid_arg)
        elif name == "status_code":
            parser.add_argument("--status-code", type=int)
        else:
            parser.add_argument("--" + name.replace("_", "-"))
    if pagination:
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--offset", type=int, default=0)


def register(registry: Registry) -> None:
    plan = registry.add(
        "config plan",
        config_plan,
        permission="authenticated API user or authorized host operator",
        help="Compare a proposed policy with the API or a protected host configuration.",
    )
    plan.add_argument("--file", type=Path, required=True)
    plan.add_argument("--host-state", type=Path, help="Optional root-controlled deployment state.")
    verify_policy = registry.add(
        "config verify",
        config_verify,
        permission="authenticated",
        help="Check activated settings against the reviewed proposal using the API.",
    )
    verify_policy.add_argument("--file", type=Path, required=True)

    apply = registry.add(
        "config apply",
        config_apply,
        permission="authorized root host operator",
        scope="host",
        mutates=True,
        preview=True,
        approval=True,
        help="Prepare a private production.env candidate for the existing deployment procedure.",
    )
    apply.add_argument("--file", type=Path, required=True)
    apply.add_argument("--host-state", type=Path, default=HOST_STATE)
    apply.add_argument(
        "--expect", required=True, help="SHA-256 from the matching host config plan."
    )
    apply.add_argument("--apply", action="store_true", required=True)
    apply.add_argument(
        "--approval-reference", required=True, help="Reference to operator approval."
    )

    search = registry.add("logs search", logs_search, permission="audit:view")
    _log_arguments(search, LOG_FILTERS)
    tail = registry.add(
        "logs tail",
        logs_tail,
        permission="audit:view",
        help="Sample the existing log event stream.",
    )
    _log_arguments(tail, STREAM_FILTERS, pagination=False)
    tail.add_argument("--max-events", type=int, default=20)
    tail.add_argument("--seconds", type=int, default=10)
    audit = registry.add("audit search", audit_search, permission="audit:view")
    _log_arguments(audit, AUDIT_FILTERS)

    status = registry.add(
        "backup status",
        backup_status,
        permission="approved monitor profile and independent backup read credentials",
        scope="host",
        help="Check authenticated independent backup freshness without sending alerts.",
    )
    status.add_argument("--monitor-profile", type=Path, required=True)
    status.add_argument("--profile-sha256", required=True)
    verify = registry.add(
        "backup verify",
        backup_verify,
        permission="recovery set and configured policy/key read access",
        scope="host",
        help="Verify encrypted backup artifacts with the existing recovery tooling.",
    )
    verify.add_argument("--directory", type=Path, required=True)
    verify.add_argument("--policy", type=Path)
    verify.add_argument("--require-authenticated", action="store_true")

    release = registry.add(
        "release status",
        release_status,
        permission="authorized root host operator",
        scope="host",
        help="Read the protected current deployment receipt.",
    )
    release.add_argument("--host-state", type=Path, default=HOST_STATE)
