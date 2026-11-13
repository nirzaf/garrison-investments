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
    assert check(50).event is None
    assert check(60).event == "escalation"
    assert check(70, ready).delivery == "none"
    assert check(80, ready).event == "resolved"
    assert check(90, ready).event is None
    saved = monitor.MonitorState.model_validate_json(state_file.read_bytes())
    assert saved.checks["readiness"].resolved == start + timedelta(seconds=80)


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


def test_long_maintenance_resumes_initial_delivery_before_escalating(
    tmp_path: Path, backup_probe
) -> None:
    start, backup, *_ = backup_probe
    end = start + timedelta(minutes=4)
    configured = profile(
        failure_threshold=1,
        probe_interval_seconds=20,
        backup=backup,
        maintenance=[
            {
                "check_ids": ["readiness"],
                "approved_by": "Operator A",
                "approval_ref": "fixture",
                "starts_at": start,
                "ends_at": end,
            }
        ],
    )
    path = tmp_path / "state.json"
    deliveries = []

    def send(check_id, event, message_id, recipient):
        deliveries.append((check_id, event, recipient))
        return message_id

    def sample(check_id, result, now):
        return monitor.observe(
            configured, monitor.load_state(path, "fixture"), path, check_id, result, now, send
        )

    outage = monitor.Result(ok=False, category="timeout")
    assert sample("readiness", outage, start).suppressed
    during = end - timedelta(seconds=1)
    muted = sample("readiness", outage, during)
    assert muted.suppressed and muted.event == "initial" and muted.delivery == "none"
    freshness = sample("recovery", monitor.check_backup(backup, "staging", during, 4), during)
    assert freshness.result.category == "backup_current" and not freshness.suppressed
    assert not deliveries

    resumed = sample("readiness", outage, end)
    assert not resumed.suppressed and resumed.event == "initial" and resumed.delivery == "accepted"
    assert deliveries == [("readiness", "initial", configured.transport.recipients[0])]
    before_limit = sample("readiness", outage, end + timedelta(seconds=49))
    assert before_limit.event == "repeat"
    at_limit = sample("readiness", outage, end + timedelta(seconds=50))
    assert at_limit.event == "escalation" and at_limit.delivery == "accepted"
    assert deliveries[-1] == (
        "readiness",
        "escalation",
        configured.transport.escalation_recipients[0],
    )


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


@pytest.mark.parametrize("mode", ["smtp_starttls", "usesend"])
def test_missing_transport_credentials_preserve_probe_results_and_pending_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, backup_probe
) -> None:
    _, backup, *_ = backup_probe
    transport = profile().transport.model_dump()
    if mode == "usesend":
        transport.update(mode=mode, endpoint="https://mail.example.invalid/send")
    configured = profile(
        transport=transport, failure_threshold=1, backup=backup, probe_interval_seconds=20
    )
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(configured.model_dump_json(), encoding="utf-8")
    digest = sha256(profile_path.read_bytes()).hexdigest()
    receipt = tmp_path / "receipt.json"
    for name in ("SMTP_USERNAME", "SMTP_PASSWORD", "USESEND_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    probe_results = iter(
        [
            monitor.Result(ok=True, category="ready"),
            monitor.Result(ok=False, category="timeout"),
            monitor.Result(ok=False, category="timeout"),
        ]
    )
    monkeypatch.setattr(monitor, "check_url", lambda *_: next(probe_results))
    assert monitor.run(profile_path, digest, tmp_path, receipt) == 1
    healthy = monitor.Receipt.model_validate_json(receipt.read_bytes())
    assert not healthy.transport_ready
    assert healthy.observations[0].result.category == "ready"
    assert healthy.observations[1].result.category == "backup_current"

    assert monitor.run(profile_path, digest, tmp_path, receipt) == 1
    failure = monitor.Receipt.model_validate_json(receipt.read_bytes())
    assert not failure.transport_ready
    assert failure.observations[0].delivery == "failed"
    state_file = tmp_path / f"{configured.profile_id}.json"
    pending = monitor.load_state(state_file, digest).checks["readiness"]
    assert pending.pending_event == "initial"
    assert pending.last_sent is None
    assert pending.pending_recipients == configured.transport.recipients
    assert pending.notified_recipients == []

    delivered = []

    def send(check_id, event, message_id, recipient):
        delivered.append((check_id, event, recipient))
        return message_id

    monkeypatch.setattr(monitor, "transport_sender", lambda _: send)
    assert monitor.run(profile_path, digest, tmp_path, receipt) == 1
    retried = monitor.Receipt.model_validate_json(receipt.read_bytes())
    assert retried.transport_ready
    assert retried.observations[0].delivery == "accepted"
    assert delivered == [("readiness", "initial", configured.transport.recipients[0])]
    assert monitor.load_state(state_file, digest).checks["readiness"].pending_event is None


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


@pytest.fixture
def backup_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
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
    attempt = SimpleNamespace(
        source_environment="staging",
        policy_revision="1",
        policy_sha256="a" * 64,
        configuration_sha256="b" * 64,
        started_at_utc=now - timedelta(minutes=11),
        completed_at_utc=now - timedelta(minutes=8),
        phase="complete",
        outcome="pass",
    )
    monkeypatch.setattr(backup_set_storage, "read_latest_publication", lambda *_a, **_k: evidence)
    monkeypatch.setattr(
        backup_set_storage, "read_latest_scheduled_attempt", lambda *_a, **_k: attempt
    )
    approved_policy = SimpleNamespace(
        source_environment="staging",
        revision="1",
        rpo_minutes=20,
        backup_interval_minutes=16,
        maximum_publication_delay_minutes=2,
    )
    monkeypatch.setattr(backup_set_contract, "read_policy", lambda _: (approved_policy, "a" * 64))
    return now, policy, approved_policy, attempt, evidence


def test_authenticated_backup_snapshot_and_failure_preserve_prior_verified_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backup_probe,
) -> None:
    from scripts import backup_set_storage

    now, policy, approved_policy, _, evidence = backup_probe
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


@pytest.mark.parametrize(
    ("phase", "category"),
    [("publication", "backup_attempt_failed"), ("resume", "backup_resume_failed")],
)
def test_failed_scheduled_backup_alerts_with_a_fresh_publication_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backup_probe,
    phase: str,
    category: str,
) -> None:
    from scripts import backup_set_storage

    now, policy, _, attempt, publication = backup_probe
    approved = profile(backup=policy, probe_interval_seconds=20)
    state = monitor.MonitorState(profile_sha256="test")
    state_file = tmp_path / "state.json"
    reads = []
    deliveries = []

    def read_attempt(*args, **kwargs):
        assert args == (policy.policy_file,)
        assert kwargs == {
            "key_file": policy.key_file,
            "key_id": policy.key_id,
            "timeout": approved.timeout_seconds,
            "expected_policy_sha256": policy.policy_sha256,
        }
        reads.append("attempt")
        return attempt

    def read_publication(*_args, **_kwargs):
        reads.append("publication")
        return publication

    def send(check_id, event, message_id, recipient):
        assert check_id == policy.check_id
        deliveries.append((event, message_id, recipient))
        if len(deliveries) == 1:
            raise OSError("synthetic refusal")
        return message_id

    monkeypatch.setattr(backup_set_storage, "read_latest_scheduled_attempt", read_attempt)
    monkeypatch.setattr(backup_set_storage, "read_latest_publication", read_publication)

    def check(seconds):
        at = now + timedelta(seconds=seconds)
        result = monitor.check_backup(policy, "staging", at, approved.timeout_seconds)
        return monitor.observe(approved, state, state_file, policy.check_id, result, at, send)

    assert check(0).result.category == "backup_current"
    previous = state.checks[policy.check_id].last_verified_snapshot
    assert reads == ["attempt", "publication"]
    attempt.outcome = "fail"
    attempt.phase = phase
    attempt.started_at_utc = now + timedelta(seconds=1)
    attempt.completed_at_utc = now + timedelta(seconds=5)
    first_failure = check(20)
    assert first_failure.result.category == category and first_failure.event is None
    assert first_failure.result.digest is None and first_failure.result.snapshot_at is None
    assert check(40).delivery == "failed"
    retried = check(60)
    assert retried.event == "initial" and retried.delivery == "accepted"
    assert deliveries[0] == deliveries[1]
    assert reads == ["attempt", "publication", "attempt", "attempt", "attempt"]
    assert state.checks[policy.check_id].last_verified_snapshot == previous
    assert state.checks[policy.check_id].last_verified_digest == "c" * 64

    attempt.outcome = "pass"
    attempt.phase = "complete"
    attempt.started_at_utc = now + timedelta(seconds=60)
    attempt.completed_at_utc = now + timedelta(seconds=65)
    publication.snapshot_at_utc = now + timedelta(seconds=61)
    publication.remote_verified_at_utc = now + timedelta(seconds=64)
    publication.manifest_sha256 = "d" * 64
    assert check(80).event is None
    recovered = check(100)
    assert recovered.event == "resolved" and recovered.delivery == "accepted"
    assert recovered.result.category == "backup_current"
    saved = monitor.load_state(state_file, "test").checks[policy.check_id]
    assert saved.last_verified_snapshot == publication.snapshot_at_utc
    assert saved.last_verified_digest == "d" * 64

    # A cleanup retry can re-verify an immutable set without publishing a new receipt.
    attempt.started_at_utc = now + timedelta(seconds=101)
    attempt.completed_at_utc = now + timedelta(seconds=105)
    repeated = check(120)
    assert repeated.result.category == "backup_current" and repeated.event is None
    assert repeated.result.snapshot_at == publication.snapshot_at_utc
    assert repeated.result.digest == publication.manifest_sha256


@pytest.mark.parametrize("error", [FileNotFoundError, ValueError])
def test_unavailable_or_unauthenticated_attempt_cannot_hide_behind_a_fresh_backup(
    monkeypatch: pytest.MonkeyPatch, backup_probe, error: type[Exception]
) -> None:
    from scripts import backup_set_storage

    now, policy, *_ = backup_probe

    def missing_or_tampered(*_args, **_kwargs):
        raise error("private-synthetic-storage-details")

    monkeypatch.setattr(backup_set_storage, "read_latest_scheduled_attempt", missing_or_tampered)
    result = monitor.check_backup(policy, "staging", now, 4)
    assert not result.ok and result.category == "backup_attempt_unavailable_or_invalid"
    assert "private-synthetic-storage-details" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_environment", "production"),
        ("policy_revision", "2"),
        ("policy_sha256", "e" * 64),
        ("configuration_sha256", "e" * 64),
        ("started_at_utc", timedelta(minutes=-7)),
        ("completed_at_utc", timedelta(minutes=1)),
        ("phase", "resume"),
    ],
)
def test_mismatched_scheduled_attempt_is_unhealthy(backup_probe, field: str, value) -> None:
    now, policy, _, attempt, _ = backup_probe
    setattr(attempt, field, now + value if isinstance(value, timedelta) else value)
    result = monitor.check_backup(policy, "staging", now, 4)
    assert not result.ok and result.category == "backup_attempt_mismatch"


def test_backup_attempt_overdue_uses_approved_cadence_from_completion(backup_probe) -> None:
    now, policy, approved_policy, attempt, publication = backup_probe
    due = now + timedelta(minutes=1)
    attempt.completed_at_utc = due - timedelta(
        minutes=approved_policy.backup_interval_minutes
        + approved_policy.maximum_publication_delay_minutes
    )
    attempt.started_at_utc = attempt.completed_at_utc - timedelta(minutes=2)
    assert due - publication.snapshot_at_utc < timedelta(
        minutes=policy.rpo_minutes - policy.alert_margin_minutes
    )
    assert monitor.check_backup(policy, "staging", due - timedelta(seconds=1), 4).ok
    result = monitor.check_backup(policy, "staging", due, 4)
    assert not result.ok and result.category == "backup_attempt_overdue"


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
    attempts = []
    primary_recipient_available = False
    state_file = tmp_path / "state.json"

    def send(_check, event, message, recipient):
        attempts.append((event, recipient, message))
        if recipient == "rejects@example.invalid" and not primary_recipient_available:
            raise OSError("synthetic refusal")
        return f"message-{len(attempts)}"

    def check(seconds, *, ok=False):
        return monitor.observe(
            configured,
            monitor.load_state(state_file, "test"),
            state_file,
            "readiness",
            monitor.Result(ok=ok, category="ready" if ok else "timeout"),
            start + timedelta(seconds=seconds),
            send,
        )

    assert check(0).delivery == "failed"
    assert check(10).delivery == "failed"
    escalation = check(60)
    assert escalation.event == "escalation"
    assert escalation.delivery == "failed"
    saved = monitor.load_state(state_file, "test")
    assert saved.checks["readiness"].escalated
    primary_recipient_available = True
    assert check(70).delivery == "accepted"
    assert [(event, recipient) for event, recipient, _message in attempts] == [
        ("initial", "works@example.invalid"),
        ("initial", "rejects@example.invalid"),
        ("initial", "rejects@example.invalid"),
        ("escalation", "substitute@example.invalid"),
        ("initial", "rejects@example.invalid"),
        ("initial", "rejects@example.invalid"),
    ]
    failed_recipient_ids = {
        message
        for event, recipient, message in attempts
        if event == "initial" and recipient == "rejects@example.invalid"
    }
    assert len(failed_recipient_ids) == 1
    assert check(80, ok=True).event is None
    assert check(90, ok=True).delivery == "accepted"
    assert check(100, ok=True).event is None
    assert [(event, recipient) for event, recipient, _message in attempts[-3:]] == [
        ("resolved", "works@example.invalid"),
        ("resolved", "substitute@example.invalid"),
        ("resolved", "rejects@example.invalid"),
    ]


def test_escalation_retry_keeps_its_message_id_after_primary_delivery(tmp_path: Path) -> None:
    start = datetime(2026, 11, 12, tzinfo=UTC)
    configured = profile(failure_threshold=1)
    state_file = tmp_path / "state.json"
    attempts = []

    for seconds in (0, 50, 60):

        def send(_check, event, message, recipient, elapsed=seconds):
            attempts.append((event, message, recipient))
            if elapsed == 0 or (elapsed == 50 and event == "escalation"):
                raise TimeoutError("synthetic timeout")
            return message

        result = monitor.observe(
            configured,
            monitor.load_state(state_file, "test"),
            state_file,
            "readiness",
            monitor.Result(ok=False, category="timeout"),
            start + timedelta(seconds=seconds),
            send,
        )
        assert result.delivery == ("failed" if seconds < 60 else "accepted")

    assert [event for event, _message, _recipient in attempts] == [
        "initial",
        "escalation",
        "initial",
        "escalation",
    ]
    assert attempts[0] == attempts[2]
    assert attempts[1] == attempts[3]
    incident = monitor.load_state(state_file, "test").checks["readiness"]
    assert incident.escalated
    assert incident.pending_event is None and incident.pending_escalation is None
