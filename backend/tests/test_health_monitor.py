from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from scripts import health_monitor as monitor


def profile(**overrides) -> monitor.Profile:
    values = {
        "profile_id": "qa-monitor",
        "revision": "fixture",
        "source_sha": "a" * 40,
        "approval_ref": "synthetic-profile",
        "environment": "staging",
        "approved_hosts": ["portal.example.invalid"],
        "targets": [
            {"check_id": "readiness", "url": "https://portal.example.invalid/health/readiness"}
        ],
        "transport": {
            "mode": "smtp_starttls",
            "sender": "monitor@example.invalid",
            "recipients": ["primary@example.invalid"],
            "escalation_recipients": ["substitute@example.invalid"],
            "endpoint": "smtp.example.invalid:587",
        },
        "timeout_seconds": 4,
        "probe_interval_seconds": 10,
        "failure_threshold": 2,
        "recovery_threshold": 2,
        "repeat_interval_seconds": 20,
        "acknowledgement_limit_seconds": 50,
        "heartbeat_window_seconds": 40,
        "primary_responder": "Operator A",
        "substitute_responder": "Operator B",
    }
    values.update(overrides)
    return monitor.Profile.model_validate(values)


@pytest.mark.parametrize(
    ("content", "content_type", "expected"),
    [
        (b'{"status":"ready","database":"connected"}', "application/json", "ready"),
        (b'{"status":"ready","database":"disconnected"}', "application/json", "unexpected_content"),
        (b"<html>Login</html>", "text/html", "unexpected_content"),
        (b"{", "application/json", "unexpected_content"),
        (b"x" * 4097, "application/json", "response_too_large"),
    ],
)
def test_checks_status_and_content(content: bytes, content_type: str, expected: str) -> None:
    def responder(_):
        return httpx.Response(200, headers={"Content-Type": content_type}, content=content)

    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        result = monitor.check_url(client, profile().targets[0].url)
    assert result.category == expected
    assert result.ok is (expected == "ready")
    assert content.decode() not in result.model_dump_json() or content == b"{"


def test_rejects_redirects_outside_origin_and_records_timeout() -> None:
    target = profile().targets[0].url
    requested = []

    def redirect(request):
        requested.append(request.url)
        return httpx.Response(302, headers={"Location": "https://other.example.invalid/"})

    def timeout(request):
        raise httpx.ReadTimeout("private.example.invalid?secret=redacted", request=request)

    with httpx.Client(transport=httpx.MockTransport(redirect)) as client:
        assert monitor.check_url(client, target).category == "invalid_redirect"
    assert len(requested) == 1
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        assert monitor.check_url(client, target).category == "timeout"


def test_notification_retry_repeat_escalation_and_resolution(tmp_path: Path) -> None:
    configured = profile()
    state = monitor.MonitorState(profile_sha256="test")
    state_file = tmp_path / "state.json"
    fail = monitor.Result(ok=False, category="transport")
    ready = monitor.Result(ok=True, category="ready")
    start = datetime(2026, 11, 12, tzinfo=UTC)
    attempts = []

    def sender(check_id, event, message_id, recipient):
        assert check_id == "readiness"
        attempts.append((event, message_id))
        if len(attempts) == 1:
            raise OSError("synthetic failure")
        return message_id

    def check(seconds, result=fail):
        return monitor.observe(
            configured,
            state,
            state_file,
            "readiness",
            result,
            start + timedelta(seconds=seconds),
            sender,
        )

    assert check(0).delivery == "none"
    assert check(10).delivery == "failed"
    assert check(20).delivery == "accepted"
    assert attempts[0] == attempts[1]
    assert check(30).delivery == "none"
    assert check(40).event == "repeat"
    assert check(50).event == "escalation"
    assert check(60, ready).delivery == "none"
    assert check(70, ready).event == "resolved"
    assert check(80, ready).event is None
    saved = monitor.MonitorState.model_validate_json(state_file.read_bytes())
    assert saved.checks["readiness"].resolved == start + timedelta(seconds=70)


def test_bounded_maintenance_expires_and_lock_prevents_overlapping_checks(tmp_path: Path) -> None:
    start = datetime(2026, 11, 12, tzinfo=UTC)
    configured = profile(
        failure_threshold=1,
        maintenance=[
            {
                "check_ids": ["readiness"],
                "approved_by": "Operator A",
                "approval_ref": "fixture",
                "starts_at": start,
                "ends_at": start + timedelta(seconds=10),
            }
        ],
    )
    state = monitor.MonitorState(profile_sha256="test")
    outcome = monitor.Result(ok=False, category="transport")
    with monitor.locked_state(tmp_path, configured.profile_id) as path:
        with pytest.raises(monitor.MonitorError, match="lock"):
            with monitor.locked_state(tmp_path, configured.profile_id):
                pytest.fail("Overlapping check acquired the same lock")
        first = monitor.observe(
            configured, state, path, "readiness", outcome, start, lambda *_: "msg"
        )
        after = monitor.observe(
            configured,
            state,
            path,
            "readiness",
            outcome,
            start + timedelta(seconds=10),
            lambda *_: "msg",
        )
    assert first.suppressed and first.delivery == "none"
    assert not after.suppressed and after.delivery == "accepted"


def test_corrupt_state_and_invalid_profile_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValidationError):
        monitor.load_state(path, "test")
    with pytest.raises(ValidationError):
        profile(timeout_seconds=30)
    with pytest.raises(ValidationError):
        profile(approved_hosts=["other.example.invalid"])
    with pytest.raises(ValidationError):
        profile(
            transport={
                "mode": "smtp_tls",
                "endpoint": "smtp.example.invalid:465",
                "sender": "sender@example.invalid",
                "recipients": [],
                "escalation_recipients": ["operator@example.invalid"],
            }
        )


def test_heartbeat_targets_the_approved_readiness_stream() -> None:
    rule = monitor.heartbeat_rule(profile())["groups"][0]["rules"][0]
    query = rule["data"][0]["model"]["expr"]
    assert query.startswith('absent_over_time({environment="staging", service="backend"}')
    assert 'message="http_request_completed"' in query
    assert 'route="/health/readiness"' in query
    assert "status_code=200 [40s]" in query
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Alerting"


def test_acknowledgement_is_tied_to_a_delivered_incident(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(profile(failure_threshold=1).model_dump_json(), encoding="utf-8")
    digest = sha256(profile_path.read_bytes()).hexdigest()
    with pytest.raises(monitor.MonitorError, match="approved digest"):
        monitor.load_profile(profile_path, "0" * 64)
    approved, _ = monitor.load_profile(profile_path, digest)
    now = datetime.now(UTC)
    state = monitor.MonitorState(profile_sha256=digest)
    with monitor.locked_state(tmp_path, approved.profile_id) as state_path:
        monitor.observe(
            approved,
            state,
            state_path,
            "readiness",
            monitor.Result(ok=False, category="timeout"),
            now,
            lambda *_: "provider-message",
        )
    with pytest.raises(monitor.MonitorError, match="approved responder"):
        monitor.acknowledge(
            profile_path, digest, tmp_path, "readiness", "unknown", "receipt", "provider-message"
        )
    with pytest.raises(monitor.MonitorError, match="active delivered"):
        monitor.acknowledge(
            profile_path, digest, tmp_path, "readiness", "Operator A", "receipt", "other-message"
        )
    monitor.acknowledge(
        profile_path, digest, tmp_path, "readiness", "Operator A", "receipt", "provider-message"
    )
    saved = monitor.load_state(state_path, digest)
    incident = saved.checks["readiness"]
    assert incident.acknowledgement is not None
    assert incident.acknowledgement.message_id == "provider-message"
    assert (
        monitor.advance(
            incident,
            monitor.Result(ok=False, category="timeout"),
            approved,
            now + timedelta(seconds=60),
        )
        == "repeat"
    )


def test_authenticated_backup_snapshot_and_failure_preserve_prior_verified_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from scripts import backup_set_contract, backup_set_storage

    now = datetime.now(UTC)
    policy = monitor.BackupCheck(
        check_id="recovery",
        policy_file=tmp_path / "policy.json",
        key_file=tmp_path / "secret",
        key_id="fixture",
        policy_revision="1",
        policy_sha256="a" * 64,
        configuration_sha256="b" * 64,
        rpo_minutes=20,
        alert_margin_minutes=5,
    )
    evidence = SimpleNamespace(
        source_environment="staging",
        policy_revision="1",
        policy_sha256="a" * 64,
        configuration_sha256="b" * 64,
        manifest_sha256="c" * 64,
        snapshot_at_utc=now - timedelta(minutes=10),
        remote_verified_at_utc=now - timedelta(minutes=9),
    )
    monkeypatch.setattr(backup_set_storage, "read_latest_publication", lambda *_a, **_k: evidence)
    approved_policy = SimpleNamespace(
        source_environment="staging",
        rpo_minutes=20,
        maximum_publication_delay_minutes=2,
    )
    monkeypatch.setattr(backup_set_contract, "read_policy", lambda _: (approved_policy, "a" * 64))
    state = monitor.MonitorState(profile_sha256="test")
    state_file = tmp_path / "state.json"
    approved = profile()

    def check(at: datetime):
        outcome = monitor.check_backup(policy, "staging", at, 4)
        return monitor.observe(
            approved,
            state,
            state_file,
            "recovery",
            outcome,
            at,
            lambda *_: "msg",
        ).result

    assert check(now).category == "backup_current"
    previous = state.checks["recovery"].last_verified_snapshot
    assert check(now + timedelta(minutes=6)).category == "backup_stale"
    assert state.checks["recovery"].last_verified_snapshot == previous
    evidence.snapshot_at_utc -= timedelta(minutes=1)
    assert check(now).category == "backup_receipt_older_than_verified"
    approved_policy.rpo_minutes = 19
    assert check(now).category == "backup_policy_mismatch"
    approved_policy.rpo_minutes = 20
    evidence.remote_verified_at_utc += timedelta(minutes=1)
    assert check(now).category == "backup_publication_late"

    def invalid(*_args, **_kwargs):
        raise ValueError("Invalid authentication")

    monkeypatch.setattr(backup_set_storage, "read_latest_publication", invalid)
    assert check(now).category == "backup_receipt_unavailable_or_invalid"
    assert state.checks["recovery"].last_verified_digest == "c" * 64


def test_failed_primary_retries_only_failed_recipients_and_escalates_to_substitute(
    tmp_path: Path,
) -> None:
    start = datetime.now(UTC)
    original = profile(failure_threshold=1)
    configured = original.model_copy(
        update={
            "transport": original.transport.model_copy(
                update={
                    "recipients": ["works@example.invalid", "rejects@example.invalid"],
                }
            ),
        }
    )
    state = monitor.MonitorState(profile_sha256="test")
    attempts = []

    def send(_check, event, _message, recipient):
        attempts.append((event, recipient))
        if recipient == "rejects@example.invalid":
            raise OSError("synthetic refusal")
        return f"message-{len(attempts)}"

    def check(seconds):
        return monitor.observe(
            configured,
            state,
            tmp_path / "state.json",
            "readiness",
            monitor.Result(ok=False, category="timeout"),
            start + timedelta(seconds=seconds),
            send,
        )

    assert check(0).delivery == "failed"
    assert check(10).delivery == "failed"
    assert check(60).event == "escalation"
    assert attempts == [
        ("initial", "works@example.invalid"),
        ("initial", "rejects@example.invalid"),
        ("initial", "rejects@example.invalid"),
        ("escalation", "substitute@example.invalid"),
    ]
    assert state.checks["readiness"].escalated
