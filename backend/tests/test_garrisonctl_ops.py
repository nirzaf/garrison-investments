from __future__ import annotations

import argparse
import io
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from scripts import garrisonctl
from scripts import garrisonctl_ops as ops
from scripts.garrisonctl_common import AUTH, CONFLICT, CONNECTION, FAILED, CLIError, Context

BASE = "http://127.0.0.1:8000"
SECRET = "fixture-value-with-no-approval-authority"
POLICY = {
    "business_currency": "USD",
    "business_timezone": "Asia/Qatar",
    "material_approval_threshold": "1250.00",
}


def cli(
    *args: str,
    handler: Any = None,
) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    transport = httpx.MockTransport(handler) if handler else None
    status = garrisonctl.run([*args, "--base-url", BASE, "--json"], stdout=out, transport=transport)
    return status, json.loads(out.getvalue())


def private_proposal(path: Path, **values: str) -> str:
    path.write_text(json.dumps({**POLICY, **values}), encoding="utf-8")
    return str(path)


@pytest.fixture
def host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "deploy"
    state.mkdir()
    for name, data in {
        "production.env": f"# fixture\nMAIL_PASSWORD='{SECRET}'\nLOG_PURGE_ENABLED=false\n",
        "compose.vps.yml": "services: {}\n",
        "deploy.lock": "",
    }.items():
        path = state / name
        path.write_text(data, encoding="utf-8")
        path.chmod(0o600)

    # Exercise writes inside a private fixture. Real host reads require root-owned path components.
    original = ops.release_contract.open_evidence

    @contextmanager
    def fixture_evidence(path: Path, *, protected: bool = False):
        assert protected
        with original(path) as stream:
            yield stream

    monkeypatch.setattr(ops.release_contract, "open_evidence", fixture_evidence)
    monkeypatch.setattr(ops, "_host_state", lambda path: path)
    return state


def test_host_apply_writes_private_candidate_and_audit_without_mutating_live_env(
    host_state: Path,
    tmp_path: Path,
) -> None:
    proposed = private_proposal(tmp_path / "policy.json")
    source = host_state / "production.env"
    before = source.read_bytes()
    status, plan = cli("config", "plan", "--file", proposed, "--host-state", str(host_state))
    assert status == 0
    assert not (host_state / "config-candidates").exists()
    assert plan["data"]["changes"] == {
        "material_approval_threshold": {"current": "1000.00", "proposed": "1250.00"}
    }
    status, applied = cli(
        "config",
        "apply",
        "--file",
        proposed,
        "--host-state",
        str(host_state),
        "--expect",
        plan["data"]["plan_sha256"],
        "--apply",
        "--approval-reference",
        "OPS-420",
    )
    assert status == 0
    assert applied["outcome"] == "prepared" and applied["changed"] is True
    assert source.read_bytes() == before
    candidate = Path(applied["data"]["candidate"])
    audit = Path(applied["data"]["audit_record"])
    assert candidate.read_bytes() == before + b"MATERIAL_APPROVAL_THRESHOLD=1250.00\n"
    assert candidate.stat().st_mode & 0o777 == audit.stat().st_mode & 0o777 == 0o600
    receipt = json.loads(audit.read_text(encoding="utf-8"))
    assert receipt["approval_reference"] == "OPS-420"
    assert receipt["activation"] == "pending_release_procedure"
    assert SECRET not in json.dumps((plan, applied, receipt))


@pytest.mark.parametrize("reason", ["currency", "drift"])
def test_host_apply_refuses_unreconciled_currency_and_stale_snapshot(
    host_state: Path,
    tmp_path: Path,
    reason: str,
) -> None:
    proposed = private_proposal(
        tmp_path / "policy.json", business_currency="LKR" if reason == "currency" else "USD"
    )
    status, plan = cli("config", "plan", "--file", proposed, "--host-state", str(host_state))
    assert status == 0
    if reason == "drift":
        with (host_state / "production.env").open("a", encoding="utf-8") as stream:
            stream.write("# snapshot changed\n")
    status, response = cli(
        "config",
        "apply",
        "--file",
        proposed,
        "--host-state",
        str(host_state),
        "--expect",
        plan["data"]["plan_sha256"],
        "--apply",
        "--approval-reference",
        "OPS-420",
    )
    assert status == CONFLICT and response["changed"] is False
    assert not (host_state / "config-candidates").exists()


def test_host_candidate_rejects_symlink_storage(host_state: Path, tmp_path: Path) -> None:
    proposed = private_proposal(tmp_path / "policy.json")
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    (host_state / "config-candidates").symlink_to(target, target_is_directory=True)
    status, plan = cli("config", "plan", "--file", proposed, "--host-state", str(host_state))
    assert status == 0
    status, response = cli(
        "config",
        "apply",
        "--file",
        proposed,
        "--host-state",
        str(host_state),
        "--expect",
        plan["data"]["plan_sha256"],
        "--apply",
        "--approval-reference",
        "OPS-420",
    )
    assert status != 0 and response["changed"] is False
    assert not list(target.iterdir())


@pytest.mark.parametrize(
    ("group", "endpoint"),
    [("logs", "/api/v1/log-events"), ("audit", "/api/v1/audit-logs")],
)
def test_log_queries_reuse_authorized_endpoints_and_clean_results(
    tmp_path: Path,
    group: str,
    endpoint: str,
) -> None:
    token = tmp_path / "access"
    token.write_text(SECRET, encoding="utf-8")
    token.chmod(0o600)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == endpoint
        assert request.method == "GET"
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        assert bool(request.headers.get("x-log-cli-session")) is (group == "logs")
        assert request.url.params["search"] == "change"
        return httpx.Response(
            200,
            headers={"x-request-id": "diag-fixture"},
            json={
                "total": 1,
                "items": [
                    {
                        "action": "finance.policy",
                        "context_payload": {"password": SECRET},
                        "endpoint": "/download?X-Amz-Signature=signed-material",
                    }
                ],
            },
        )

    status, result = cli(
        group, "search", "--query", "change", "--token-file", str(token), handler=handler
    )
    assert status == 0 and result["request_id"] == "diag-fixture"
    item = result["data"]["items"][0]
    assert "context_payload" not in item
    assert item["endpoint"] == "/download"
    assert SECRET not in json.dumps(result)


def test_tail_returns_one_envelope_from_bounded_sample(tmp_path: Path) -> None:
    token = tmp_path / "access"
    token.write_text(SECRET, encoding="utf-8")
    token.chmod(0o600)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/log-events/stream"
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=': keep-alive\n\ndata: {"action":"fixture"}\n\n',
        )

    status, result = cli(
        "logs", "tail", "--max-events", "1", "--token-file", str(token), handler=handler
    )
    assert status == 0
    assert result["data"] == {"items": [{"action": "fixture"}], "finished_by": "event_limit"}


def test_tail_resumes_from_header_and_reports_revocation(tmp_path: Path) -> None:
    token = tmp_path / "access"
    token.write_text(SECRET, encoding="utf-8")
    token.chmod(0o600)
    cursor = "a0300f69-121f-449c-bfa0-7e204feafbad"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Last-Event-ID"] == cursor
        assert cursor not in str(request.url) and SECRET not in str(request.url)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"action":"fixture"}\n\n: closed authorization_ended\n\n',
        )

    status, result = cli(
        "logs", "tail", "--last-event-id", cursor, "--token-file", str(token), handler=handler
    )
    assert status == 0
    assert result["data"] == {
        "items": [{"action": "fixture"}],
        "finished_by": "authorization_ended",
    }


@pytest.mark.parametrize(
    ("http_status", "body", "expected"),
    [
        (401, "", AUTH),
        (403, "", AUTH),
        (503, "", CONNECTION),
        (200, ": keep-alive\n\n", CONNECTION),
        (200, "data: {invalid}\n\n", CONNECTION),
    ],
)
def test_tail_propagates_api_errors_and_unexpected_end_of_stream(
    tmp_path: Path,
    http_status: int,
    body: str,
    expected: int,
) -> None:
    token = tmp_path / "access"
    token.write_text(SECRET, encoding="utf-8")
    token.chmod(0o600)
    status, result = cli(
        "logs",
        "tail",
        "--token-file",
        str(token),
        handler=lambda _: httpx.Response(
            http_status, headers={"content-type": "text/event-stream"}, text=body
        ),
    )
    assert status == expected and result["outcome"] == "error" and result["data"] is None


def test_backup_status_uses_independent_monitor_without_writing(monkeypatch: pytest.MonkeyPatch):
    profile = Mock(environment="production", timeout_seconds=5, source_sha="b" * 40)
    monkeypatch.setattr(ops.health_monitor, "load_profile", lambda *_: (profile, "a" * 64))
    check = Mock(return_value=ops.health_monitor.Result(ok=False, category="backup_attempt_failed"))
    monkeypatch.setattr(ops.health_monitor, "check_backup", check)
    status, result = cli(
        "backup",
        "status",
        "--monitor-profile",
        "/fixture/profile.json",
        "--profile-sha256",
        "a" * 64,
    )
    assert status == FAILED
    assert result["changed"] is False and result["data"]["category"] == "backup_attempt_failed"
    assert check.call_args.kwargs["source_sha"] == profile.source_sha


def test_backup_verify_missing_manifest_has_json_only_stdout(capsys, tmp_path: Path):
    status, result = cli("backup", "verify", "--directory", str(tmp_path))
    assert status == FAILED and result["outcome"] == "error"
    assert not capsys.readouterr().out


def test_release_status_binds_safe_current_receipt_and_refuses_external_pointer(
    host_state: Path,
    tmp_path: Path,
) -> None:
    release = tmp_path / "releases" / "candidate"
    release.mkdir(parents=True)
    sha = "d" * 40
    (release / "SOURCE_COMMIT").write_text(sha, encoding="ascii")
    (release / "DEPLOYED").write_text(
        "Status: Deployed — Formal Acceptance Pending\n"
        f"Commit: {sha}\nUTC: 2026-11-14T05:00:00Z\n"
        "CI run: 501\nCI attempt: 1\nDeploy run: 502\nDeploy attempt: 2\n",
        encoding="utf-8",
    )
    link = host_state / "current"
    link.symlink_to(release, target_is_directory=True)
    status, result = cli("release", "status", "--host-state", str(host_state))
    assert status == 0
    assert result["data"]["source_sha"] == sha
    assert result["data"]["deploy_attempt"] == 2
    link.unlink()
    link.symlink_to(tmp_path / "outside", target_is_directory=True)
    status, result = cli("release", "status", "--host-state", str(host_state))
    assert status == CONFLICT and result["data"] is None


def test_invalid_host_policy_uses_sanitized_diagnostics(tmp_path: Path) -> None:
    proposal = private_proposal(tmp_path / "policy.json", business_timezone=SECRET)
    with pytest.raises(CLIError) as error:
        ops.config_plan(
            argparse.Namespace(file=Path(proposal), host_state=None), Mock(spec=Context)
        )
    assert SECRET not in str(error.value)
    assert SECRET not in json.dumps(error.value.details)


@pytest.mark.parametrize(("threshold", "code"), [("1250.0", 0), ("1000.00", CONFLICT)])
def test_config_verify_checks_effective_policy(
    tmp_path: Path,
    threshold: str,
    code: int,
) -> None:
    proposal = private_proposal(tmp_path / "policy.json")
    token = tmp_path / "access"
    token.write_text(SECRET, encoding="utf-8")
    token.chmod(0o600)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/finance/policy"
        return httpx.Response(
            200,
            json={
                **POLICY,
                "material_approval_threshold": threshold,
                "invoice_tax_mode": "explicit",
            },
        )

    status, result = cli(
        "config", "verify", "--file", proposal, "--token-file", str(token), handler=handler
    )
    assert status == code and result["changed"] is False
    if code == CONFLICT:
        assert result["data"]["differences"] == {
            "material_approval_threshold": {"expected": "1250.00", "effective": "1000.00"}
        }
    else:
        assert result["data"]["verified"] is True


def test_every_mutating_cli_command_requires_preview_and_expect() -> None:
    session_or_custody_exempt = {
        "auth login",
        "auth logout",
        "support auth login",
        "support auth logout",
        "support custody enrollment register",
        "support views end",
    }
    code, envelope = cli("capabilities")
    assert code == 0
    mutating = [
        item for item in envelope["data"]["commands"] if item["mutates"] is True
    ]
    assert len(mutating) >= 10
    for item in mutating:
        if item["command"] in session_or_custody_exempt:
            assert item["supports_preview"] is True
        elif item["command"] == "config apply":
            assert item["supports_preview"] is True
            assert any(arg["name"] == "--expect" for arg in item["arguments"])
        elif item["supports_preview"]:
            assert any(arg["name"] == "--expect" for arg in item["arguments"])
            assert any(
                "--dry-run" in choice["choose_one"] and "--apply" in choice["choose_one"]
                for choice in item["argument_choices"]
            )


def test_backup_ingest_receipt_cli_dry_run_and_apply_guards(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    from scripts.backup_set_contract import (
        DestinationIdentity,
        FailureDomains,
        PublicationReceipt,
        RecoveryPolicy,
        RetentionRules,
        canonical_bytes,
        sign_publication_receipt,
    )

    now = ops.datetime.now(ops.UTC)
    key = bytes(range(32))
    key_file = tmp_path / "backup.key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    policy = RecoveryPolicy(
        decision_id="D-29-RECOVERY",
        policy_id="cli-policy",
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
            endpoint="localhost:9020", bucket="independent-cli", prefix="app/test", secure=False
        ),
        failure_domains=FailureDomains(source="primary", destination="recovery"),
        key_custodians=["Custodian A", "Custodian B"],
        operator="Op A",
        substitute_operator="Op B",
        exercise_interval="monthly",
        required_artifact_categories={"application_database", "objects", "configuration"},
        required_configuration_paths={"compose.yml"},
        source_environment="test",
        approval_ref="fixture",
        approved_at=now,
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(canonical_bytes(policy))
    policy_sha = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    receipt = PublicationReceipt(
        backup_set_id="b" * 32,
        manifest_sha256="c" * 64,
        snapshot_at_utc=now,
        remote_verified_at_utc=now,
        source_sha="d" * 40,
        source_environment="test",
        policy_revision="v1",
        policy_sha256=policy_sha,
        configuration_sha256="e" * 64,
        destination_identity=policy.destination_identity,
        object_count=1,
    )
    receipt_path = tmp_path / "pub.json"
    receipt_path.write_bytes(sign_publication_receipt(receipt, key=key, key_id="cli-key"))

    code, preview = cli(
        "backup",
        "ingest-receipt",
        "--kind",
        "publication",
        "--receipt",
        str(receipt_path),
        "--policy",
        str(policy_path),
        "--policy-sha256",
        policy_sha,
        "--key-file",
        str(key_file),
        "--key-id",
        "cli-key",
        "--dry-run",
    )
    assert code == 0 and preview["outcome"] == "preview" and preview["changed"] is False

    # Stale/mismatched --expect refuses without hitting DB
    code_stale, stale = cli(
        "backup",
        "ingest-receipt",
        "--kind",
        "publication",
        "--receipt",
        str(receipt_path),
        "--policy",
        str(policy_path),
        "--policy-sha256",
        policy_sha,
        "--key-file",
        str(key_file),
        "--key-id",
        "cli-key",
        "--apply",
        "--expect",
        "0" * 64,
    )
    assert code_stale == CONFLICT and stale["changed"] is False
