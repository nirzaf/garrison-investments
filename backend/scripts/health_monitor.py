"""Run the approved independent uptime and backup freshness checks."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import re
import signal
import smtplib
import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    ValidationError,
    model_validator,
)

MAX_BODY = 4096
CHECK_ID = r"^[a-z][a-z0-9-]{0,63}$"
EMAIL = re.compile(r"^[^\s<>,@]+@[^\s<>,@]+\.[^\s<>,@]+$")
Event = Literal["initial", "repeat", "escalation", "resolved"]
Sender = Callable[[str, Event, str, str], str]


class MonitorError(RuntimeError):
    """A check or profile failure whose message is safe to show to operators."""


@contextmanager
def deadline(seconds: float) -> Iterator[None]:
    def timed_out(*_args: object) -> None:
        raise TimeoutError("Monitor operation exceeded its deadline.")

    handler = signal.signal(signal.SIGALRM, timed_out)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, handler)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def https_origin(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or any(char.isspace() for char in url)
        or "\\" in url
    ):
        raise MonitorError("A target must be an HTTPS URL without credentials, query or fragment.")
    return parts.hostname, parts.port or 443


class Target(StrictModel):
    check_id: str = Field(pattern=CHECK_ID)
    url: str


class Transport(StrictModel):
    mode: Literal["smtp_starttls", "smtp_tls", "usesend"]
    sender: str
    recipients: list[str] = Field(min_length=1)
    escalation_recipients: list[str] = Field(min_length=1)
    endpoint: str

    @model_validator(mode="after")
    def validate_addresses(self) -> Transport:
        if any(
            not EMAIL.fullmatch(value)
            for value in (self.sender, *self.recipients, *self.escalation_recipients)
        ):
            raise ValueError("invalid sender or recipients")
        if self.mode == "usesend":
            https_origin(self.endpoint)
        else:
            parts = urlsplit(f"//{self.endpoint}")
            if (
                not parts.hostname
                or parts.port is None
                or parts.username is not None
                or parts.path
                or parts.query
                or parts.fragment
                or not 1 <= parts.port <= 65535
                or not re.fullmatch(r"[A-Za-z0-9.-]+", parts.hostname)
            ):
                raise ValueError("SMTP endpoint must be a host and port")
        return self


class Maintenance(StrictModel):
    check_ids: list[str] = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approval_ref: str = Field(min_length=1)
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class BackupCheck(StrictModel):
    check_id: str = Field(pattern=CHECK_ID)
    policy_file: Path
    key_file: Path
    key_id: str = Field(min_length=1)
    policy_revision: str = Field(min_length=1)
    policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rpo_minutes: PositiveInt
    alert_margin_minutes: PositiveInt

    @model_validator(mode="after")
    def validate_backup(self) -> BackupCheck:
        if (
            not self.policy_file.is_absolute()
            or not self.key_file.is_absolute()
            or self.alert_margin_minutes >= self.rpo_minutes
        ):
            raise ValueError("invalid independent backup check")
        return self


class Profile(StrictModel):
    profile_id: str = Field(pattern=CHECK_ID)
    revision: str = Field(min_length=1)
    source_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    approval_ref: str = Field(min_length=1)
    environment: str = Field(pattern=CHECK_ID)
    approved_hosts: list[str] = Field(min_length=1)
    targets: list[Target] = Field(min_length=1)
    transport: Transport
    timeout_seconds: int = Field(ge=1, le=30)
    probe_interval_seconds: PositiveInt
    failure_threshold: PositiveInt
    recovery_threshold: PositiveInt
    repeat_interval_seconds: PositiveInt
    acknowledgement_limit_seconds: PositiveInt
    primary_responder: str = Field(min_length=1)
    substitute_responder: str = Field(min_length=1)
    heartbeat_window_seconds: PositiveInt
    backup: BackupCheck | None = None
    maintenance: list[Maintenance] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_profile(self) -> Profile:
        ids = [target.check_id for target in self.targets]
        if self.backup:
            ids.append(self.backup.check_id)
        elif self.environment == "production":
            raise ValueError(
                "production monitoring requires the independent backup freshness check"
            )
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate check identity")
        if (
            not self.approval_ref.strip()
            or not self.primary_responder.strip()
            or not self.substitute_responder.strip()
            or self.primary_responder.strip() == self.substitute_responder.strip()
        ):
            raise ValueError("an approval and two distinct responders are required")
        if any(
            https_origin(target.url)[0] not in self.approved_hosts
            or urlsplit(target.url).path != "/health/readiness"
            for target in self.targets
        ):
            raise ValueError("readiness URL must match an approved HTTPS host")
        if (
            2 * len(ids) * self.timeout_seconds >= self.probe_interval_seconds
            or min(self.repeat_interval_seconds, self.acknowledgement_limit_seconds)
            < self.probe_interval_seconds
            or self.heartbeat_window_seconds <= self.probe_interval_seconds
        ):
            raise ValueError("timing is incompatible with the probe interval")
        for window in self.maintenance:
            if (
                not set(window.check_ids).issubset(ids)
                or not window.approved_by.strip()
                or not window.approval_ref.strip()
                or not 0 < (window.ends_at - window.starts_at).total_seconds() <= 86400
            ):
                raise ValueError("maintenance must be approved, bounded and scoped")
        return self


class Result(StrictModel):
    ok: bool
    category: str
    status: int | None = None
    digest: str | None = None
    snapshot_at: AwareDatetime | None = None


def check_url(client: httpx.Client, url: str) -> Result:
    origin = https_origin(url)
    try:
        for _ in range(4):
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return Result(
                            ok=False, category="invalid_redirect", status=response.status_code
                        )
                    url = urljoin(url, location)
                    try:
                        if https_origin(url) != origin:
                            return Result(ok=False, category="invalid_redirect")
                    except (MonitorError, ValueError):
                        return Result(ok=False, category="invalid_redirect")
                    continue
                if response.status_code != 200:
                    return Result(ok=False, category="http_status", status=response.status_code)
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    != "application/json"
                ):
                    return Result(ok=False, category="unexpected_content", status=200)
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=MAX_BODY):
                    if len(body) + len(chunk) > MAX_BODY:
                        return Result(ok=False, category="response_too_large", status=200)
                    body.extend(chunk)
                digest = hashlib.sha256(body).hexdigest()
                try:
                    data = json.loads(body)
                except (ValueError, UnicodeError):
                    return Result(
                        ok=False, category="unexpected_content", status=200, digest=digest
                    )
                ok = (
                    isinstance(data, dict)
                    and data.get("status") == "ready"
                    and data.get("database") == "connected"
                )
                return Result(
                    ok=ok,
                    category="ready" if ok else "unexpected_content",
                    status=200,
                    digest=digest,
                )
        return Result(ok=False, category="redirect_limit")
    except httpx.TimeoutException:
        return Result(ok=False, category="timeout")
    except httpx.HTTPError:
        return Result(ok=False, category="transport")


class Acknowledgement(StrictModel):
    operator: str
    reference: str
    message_id: str
    recorded_by: str
    at: AwareDatetime


class PendingEscalation(StrictModel):
    recipients: list[str]
    message_reference: AwareDatetime | None


class Incident(StrictModel):
    failures: int = Field(default=0, ge=0)
    recoveries: int = Field(default=0, ge=0)
    first_failure: AwareDatetime | None = None
    started: AwareDatetime | None = None
    first_notification_attempt: AwareDatetime | None = None
    last_attempt: AwareDatetime | None = None
    last_sent: AwareDatetime | None = None
    message_id: str | None = None
    escalated: bool = False
    resolved: AwareDatetime | None = None
    acknowledgement: Acknowledgement | None = None
    last_verified_snapshot: AwareDatetime | None = None
    last_verified_digest: str | None = None
    pending_event: Event | None = None
    pending_recipients: list[str] = Field(default_factory=list)
    pending_escalation: PendingEscalation | None = None
    delivered_messages: list[str] = Field(default_factory=list)
    notified_recipients: list[str] = Field(default_factory=list)


class MonitorState(StrictModel):
    profile_sha256: str
    checks: dict[str, Incident] = Field(default_factory=dict)


def save_json(path: Path, model: BaseModel | dict) -> None:
    with NamedTemporaryFile(mode="w", dir=path.parent, prefix=".monitor-", delete=False) as file:
        temporary = Path(file.name)
        try:
            serialized = (
                model.model_dump_json(indent=2)
                if isinstance(model, BaseModel)
                else json.dumps(model, indent=2)
            )
            file.write(serialized + "\n")
            file.flush()
            os.fsync(file.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def locked_state(path: Path, profile_id: str) -> Iterator[Path]:
    if not path.is_dir() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise MonitorError("Use an existing private state directory.")
    descriptor = os.open(path / f"{profile_id}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MonitorError("Another run holds the monitor lock.") from None
        yield path / f"{profile_id}.json"


def advance(incident: Incident, result: Result, profile: Profile, now: datetime) -> Event | None:
    if result.ok:
        incident.failures = 0
        incident.first_failure = None
        if incident.started is None or incident.resolved is not None:
            return None
        incident.recoveries += 1
        if incident.recoveries < profile.recovery_threshold:
            return None
        if incident.notified_recipients:
            return "resolved"
        incident.resolved = now
        incident.pending_event = None
        incident.pending_recipients.clear()
        incident.pending_escalation = None
        return None

    if incident.resolved is not None:
        incident.failures = 0
        incident.first_failure = None
        incident.started = None
        incident.first_notification_attempt = None
        incident.last_attempt = None
        incident.last_sent = None
        incident.message_id = None
        incident.escalated = False
        incident.resolved = None
        incident.acknowledgement = None
        incident.pending_event = None
        incident.pending_recipients.clear()
        incident.pending_escalation = None
        incident.delivered_messages.clear()
        incident.notified_recipients.clear()
    incident.recoveries = 0
    if incident.pending_event == "resolved":
        incident.pending_event = None
        incident.pending_recipients.clear()
    incident.failures += 1
    if incident.first_failure is None:
        incident.first_failure = now
    if incident.failures < profile.failure_threshold and incident.started is None:
        return None
    if incident.started is None:
        incident.started = incident.first_failure
    notification_started = incident.first_notification_attempt
    if notification_started is None and incident.last_attempt is not None:
        # Older state files recorded attempts without a separate acknowledgement clock.
        notification_started = incident.started
    if (
        not incident.escalated
        and incident.acknowledgement is None
        and notification_started is not None
        and (now - notification_started).total_seconds() >= profile.acknowledgement_limit_seconds
    ):
        return "escalation"
    if incident.pending_event in ("initial", "repeat"):
        return incident.pending_event
    if incident.last_sent is None:
        return "initial"
    if (now - incident.last_sent).total_seconds() >= profile.repeat_interval_seconds:
        return "repeat"
    return None


def transport_sender(profile: Profile) -> Sender:
    transport = profile.transport
    if transport.mode == "usesend":
        if not (key := os.getenv("USESEND_API_KEY")):
            raise MonitorError("The approved useSend transport is missing its credential.")

        def send_usesend(check_id: str, event: Event, message_id: str, recipient: str) -> str:
            response = httpx.post(
                transport.endpoint,
                headers={"Authorization": f"Bearer {key}", "Idempotency-Key": message_id},
                json={
                    "from": transport.sender,
                    "to": [recipient],
                    "subject": subject(profile, check_id, event),
                    "text": f"Monitor notification {message_id}. Follow the incident runbook.",
                },
                timeout=profile.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            )
            response.raise_for_status()
            result = response.json()
            identifier = result.get("emailId") if isinstance(result, dict) else None
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[A-Za-z0-9._:@<>-]{1,200}", identifier
            ):
                raise MonitorError("useSend did not return a usable message identifier.")
            return identifier

        return send_usesend

    username, password = os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD")
    if not username or not password:
        raise MonitorError("The approved SMTP transport requires authentication.")
    parts = urlsplit(f"//{transport.endpoint}")
    assert parts.hostname is not None and parts.port is not None
    host, port = parts.hostname, parts.port
    context = ssl.create_default_context()

    def send_smtp(check_id: str, event: Event, message_id: str, recipient: str) -> str:
        message = EmailMessage()
        message["From"] = transport.sender
        message["To"] = recipient
        message["Subject"] = subject(profile, check_id, event)
        message["Message-ID"] = message_id
        message.set_content(
            "Check the independent monitor and follow the approved incident runbook."
        )
        if transport.mode == "smtp_tls":
            connection: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, timeout=profile.timeout_seconds, context=context
            )
        else:
            connection = smtplib.SMTP(host, port, timeout=profile.timeout_seconds)
        with connection as smtp:
            if transport.mode == "smtp_starttls":
                smtp.starttls(context=context)
            smtp.login(username, password)
            if smtp.send_message(message):
                raise MonitorError("SMTP refused one or more approved recipients.")
        return message_id

    return send_smtp


def recipients(transport: Transport, event: Event, incident: Incident) -> list[str]:
    if event == "resolved":
        selected = incident.notified_recipients
    elif event == "escalation":
        selected = transport.escalation_recipients
    else:
        selected = transport.recipients
    return list(dict.fromkeys(selected))


def subject(profile: Profile, check_id: str, event: Event) -> str:
    return f"Garrisons {profile.environment} {check_id}: {event}"


class Observation(StrictModel):
    check_id: str
    result: Result
    event: Event | None
    suppressed: bool
    delivery: Literal["none", "accepted", "failed"]
    message_id: str | None
    acknowledgement: Acknowledgement | None


class Receipt(StrictModel):
    profile_id: str
    profile_revision: str
    source_sha: str
    environment: str
    profile_sha256: str
    checked_at: AwareDatetime
    completed_at: AwareDatetime
    executed_by: str
    observations: list[Observation]
    transport_ready: bool = True


def observe(
    profile: Profile,
    state: MonitorState,
    state_file: Path,
    check_id: str,
    result: Result,
    now: datetime,
    send: Sender,
) -> Observation:
    incident = state.checks.setdefault(check_id, Incident())
    if incident.pending_event == "escalation":
        # Read older state files that kept escalation in the primary delivery slot.
        incident.pending_escalation = PendingEscalation(
            recipients=incident.pending_recipients, message_reference=incident.last_sent
        )
        incident.pending_event = None
        incident.pending_recipients = []
    if result.ok and result.snapshot_at:
        if incident.last_verified_snapshot and (
            result.snapshot_at < incident.last_verified_snapshot
            or (
                result.snapshot_at == incident.last_verified_snapshot
                and result.digest != incident.last_verified_digest
            )
        ):
            result = Result(ok=False, category="backup_receipt_older_than_verified")
        else:
            incident.last_verified_snapshot = result.snapshot_at
            incident.last_verified_digest = result.digest
    event = advance(incident, result, profile, now)
    suppressed = any(
        check_id in window.check_ids and window.starts_at <= now < window.ends_at
        for window in profile.maintenance
    )
    delivery: Literal["none", "accepted", "failed"] = "none"
    message_id = None
    if event and not suppressed:
        if event == "initial" and incident.last_attempt is None:
            incident.first_notification_attempt = now
        deliveries: list[tuple[Event, list[str], datetime | None]] = []
        if event == "escalation":
            if incident.pending_escalation is None:
                incident.pending_escalation = PendingEscalation(
                    recipients=recipients(profile.transport, event, incident),
                    message_reference=incident.last_sent,
                )
            escalation = incident.pending_escalation
            deliveries.append((event, escalation.recipients, escalation.message_reference))
            if incident.pending_event is None and incident.last_sent is None:
                incident.pending_event = "initial"
                incident.pending_recipients = recipients(profile.transport, "initial", incident)
        elif incident.pending_event != event:
            incident.pending_event = event
            incident.pending_recipients = recipients(profile.transport, event, incident)
        if incident.pending_event:
            deliveries.append(
                (incident.pending_event, incident.pending_recipients, incident.last_sent)
            )
        incident.last_attempt = now
        for sending_event, pending, message_reference in deliveries:
            try:
                with deadline(profile.timeout_seconds / len(deliveries)):
                    for recipient in list(pending):
                        message_key = hashlib.sha256(
                            f"{state.profile_sha256}:{check_id}:{incident.started}:"
                            f"{sending_event}:{message_reference}:{recipient}".encode()
                        ).hexdigest()
                        save_json(state_file, state)
                        try:
                            delivered_id = send(
                                check_id,
                                sending_event,
                                f"<{message_key}@garrisons-monitor>",
                                recipient,
                            )
                        except TimeoutError:
                            raise
                        except (
                            OSError,
                            smtplib.SMTPException,
                            httpx.HTTPError,
                            ValueError,
                            MonitorError,
                        ):
                            continue
                        pending.remove(recipient)
                        if recipient not in incident.notified_recipients:
                            incident.notified_recipients.append(recipient)
                        if delivered_id not in incident.delivered_messages:
                            incident.delivered_messages.append(delivered_id)
                        incident.message_id = delivered_id
                        if sending_event == event:
                            message_id = delivered_id
                        save_json(state_file, state)
            except TimeoutError:
                pass
        delivery = "failed" if any(pending for _, pending, _ in deliveries) else "accepted"
        for sending_event, pending, _ in deliveries:
            if pending:
                continue
            if sending_event == "escalation":
                incident.escalated = True
                incident.pending_escalation = None
            else:
                incident.last_sent = now
                incident.pending_event = None
                if sending_event == "resolved":
                    incident.resolved = now
                    incident.pending_escalation = None
    save_json(state_file, state)
    return Observation(
        check_id=check_id,
        result=result,
        event=event,
        suppressed=suppressed,
        delivery=delivery,
        message_id=message_id,
        acknowledgement=incident.acknowledgement,
    )


def check_backup(profile: BackupCheck, environment: str, now: datetime, timeout: int) -> Result:
    from scripts.backup_set_contract import read_policy
    from scripts.backup_set_storage import read_latest_publication, read_latest_scheduled_attempt

    try:
        policy, policy_sha = read_policy(profile.policy_file)
        if (
            policy_sha != profile.policy_sha256
            or policy.revision != profile.policy_revision
            or policy.rpo_minutes != profile.rpo_minutes
            or policy.source_environment != environment
        ):
            return Result(ok=False, category="backup_policy_mismatch")
        with deadline(timeout):
            # Attempt status tracks scheduler failures independently of the recovery point.
            try:
                attempt = read_latest_scheduled_attempt(
                    profile.policy_file,
                    key_file=profile.key_file,
                    key_id=profile.key_id,
                    timeout=timeout,
                    expected_policy_sha256=profile.policy_sha256,
                )
            except Exception:
                return Result(ok=False, category="backup_attempt_unavailable_or_invalid")
            now = max(now, datetime.now(UTC))
            if (
                attempt.source_environment != environment
                or attempt.policy_revision != profile.policy_revision
                or attempt.policy_sha256 != profile.policy_sha256
                or attempt.configuration_sha256 != profile.configuration_sha256
                or not attempt.started_at_utc <= attempt.completed_at_utc <= now
            ):
                return Result(ok=False, category="backup_attempt_mismatch")
            if attempt.outcome == "fail":
                category = (
                    "backup_resume_failed" if attempt.phase == "resume" else "backup_attempt_failed"
                )
                return Result(ok=False, category=category)
            if attempt.outcome != "pass" or attempt.phase != "complete":
                return Result(ok=False, category="backup_attempt_mismatch")
            if now - attempt.completed_at_utc >= timedelta(
                minutes=policy.backup_interval_minutes + policy.maximum_publication_delay_minutes
            ):
                return Result(ok=False, category="backup_attempt_overdue")
            receipt = read_latest_publication(
                profile.policy_file,
                key_file=profile.key_file,
                key_id=profile.key_id,
                timeout=timeout,
                expected_policy_sha256=profile.policy_sha256,
            )
        now = max(now, datetime.now(UTC))
        age = (now - receipt.snapshot_at_utc).total_seconds()
        if (
            receipt.source_environment != environment
            or receipt.policy_revision != profile.policy_revision
            or receipt.policy_sha256 != profile.policy_sha256
            or receipt.configuration_sha256 != profile.configuration_sha256
            or not receipt.snapshot_at_utc <= receipt.remote_verified_at_utc <= now
        ):
            return Result(ok=False, category="backup_receipt_mismatch")
        if (
            receipt.remote_verified_at_utc - receipt.snapshot_at_utc
        ).total_seconds() > policy.maximum_publication_delay_minutes * 60:
            return Result(ok=False, category="backup_publication_late")
    except Exception:
        # Provider exceptions can contain private object names and request URLs.
        return Result(ok=False, category="backup_receipt_unavailable_or_invalid")
    ok = age < (profile.rpo_minutes - profile.alert_margin_minutes) * 60
    return Result(
        ok=ok,
        category="backup_current" if ok else "backup_stale",
        digest=receipt.manifest_sha256,
        snapshot_at=receipt.snapshot_at_utc,
    )


def load_profile(profile_path: Path, expected_sha256: str) -> tuple[Profile, str]:
    if (
        profile_path.is_symlink()
        or not profile_path.is_file()
        or profile_path.stat().st_mode & 0o022
    ):
        raise MonitorError("The approved profile must be protected from shared writes.")
    profile_bytes = profile_path.read_bytes()
    digest = hashlib.sha256(profile_bytes).hexdigest()
    if digest != expected_sha256:
        raise MonitorError("Monitor profile differs from the approved digest.")
    return Profile.model_validate_json(profile_bytes), digest


def load_state(state_file: Path, digest: str) -> MonitorState:
    if state_file.is_symlink() or (state_file.exists() and not state_file.is_file()):
        raise MonitorError("Monitor state must be a regular file.")
    if not state_file.exists():
        return MonitorState(profile_sha256=digest)
    state = MonitorState.model_validate_json(state_file.read_bytes())
    if state.profile_sha256 != digest:
        raise MonitorError("State belongs to a different approved profile.")
    return state


def acknowledge(
    profile_path: Path,
    expected_sha256: str,
    state_dir: Path,
    check_id: str,
    operator: str,
    reference: str,
    message_id: str,
) -> None:
    profile, digest = load_profile(profile_path, expected_sha256)
    if (
        operator not in {profile.primary_responder, profile.substitute_responder}
        or not reference.strip()
    ):
        raise MonitorError("Acknowledgement requires an approved responder and receipt reference.")
    with locked_state(state_dir, profile.profile_id) as state_file:
        state = load_state(state_file, digest)
        incident = state.checks.get(check_id)
        if (
            incident is None
            or incident.started is None
            or incident.resolved
            or message_id not in incident.delivered_messages
            or incident.acknowledgement is not None
        ):
            raise MonitorError("Only an active delivered incident can be acknowledged once.")
        incident.acknowledgement = Acknowledgement(
            operator=operator,
            reference=reference,
            message_id=message_id,
            recorded_by=pwd.getpwuid(os.geteuid()).pw_name,
            at=datetime.now(UTC),
        )
        incident.pending_escalation = None
        save_json(state_file, state)


def heartbeat_rule(profile: Profile) -> dict:
    window = profile.heartbeat_window_seconds
    query = (
        f'absent_over_time({{environment="{profile.environment}", service="backend"}} '
        '| json | message="http_request_completed" | route="/health/readiness" '
        f"| status_code=200 [{window}s])"
    )
    return {
        "apiVersion": 1,
        "groups": [
            {
                "orgId": 1,
                "name": f"{profile.environment} readiness ingestion",
                "folder": "Garrison Alerts",
                "interval": f"{profile.probe_interval_seconds}s",
                "rules": [
                    {
                        "uid": f"garrison-heartbeat-{profile.environment}",
                        "title": f"Missing {profile.environment} readiness logs",
                        "condition": "B",
                        "noDataState": "OK",
                        "execErrState": "Alerting",
                        "for": "0s",
                        "labels": {"service": "backend", "severity": "critical"},
                        "annotations": {
                            "summary": "The approved readiness completion stream is missing."
                        },
                        "data": [
                            {
                                "refId": "A",
                                "datasourceUid": "loki",
                                "relativeTimeRange": {"from": window, "to": 0},
                                "model": {
                                    "refId": "A",
                                    "expr": query,
                                    "queryType": "instant",
                                    "datasource": {"type": "loki", "uid": "loki"},
                                },
                            },
                            {
                                "refId": "B",
                                "datasourceUid": "__expr__",
                                "relativeTimeRange": {"from": 0, "to": 0},
                                "model": {
                                    "refId": "B",
                                    "expression": "A",
                                    "type": "classic_conditions",
                                    "datasource": {"type": "__expr__", "uid": "__expr__"},
                                    "conditions": [
                                        {
                                            "evaluator": {"params": [0], "type": "gt"},
                                            "operator": {"type": "and"},
                                            "query": {"params": ["A"]},
                                            "reducer": {"params": [], "type": "last"},
                                            "type": "query",
                                        }
                                    ],
                                },
                            },
                        ],
                    }
                ],
            }
        ],
    }


def run(profile_path: Path, expected_sha256: str, state_dir: Path, receipt_path: Path) -> int:
    profile, digest = load_profile(profile_path, expected_sha256)
    transport_ready = True
    try:
        send = transport_sender(profile)
    except MonitorError:
        transport_ready = False

        def send(_check_id: str, _event: Event, _message_id: str, _recipient: str) -> str:
            raise MonitorError("The configured notification transport is unavailable.")

    with locked_state(state_dir, profile.profile_id) as state_file:
        if receipt_path.resolve() in {state_file.resolve(), profile_path.resolve()} or (
            receipt_path.resolve() == state_dir.resolve() / f"{profile.profile_id}.lock"
        ):
            raise MonitorError("The receipt must use a separate output file.")
        state = load_state(state_file, digest)
        now = datetime.now(UTC)
        with httpx.Client(
            timeout=profile.timeout_seconds, follow_redirects=False, trust_env=False
        ) as client:
            observations = []
            for target in profile.targets:
                try:
                    with deadline(profile.timeout_seconds):
                        result = check_url(client, target.url)
                except TimeoutError:
                    result = Result(ok=False, category="timeout")
                observations.append(
                    observe(
                        profile, state, state_file, target.check_id, result, datetime.now(UTC), send
                    )
                )
        if profile.backup:
            observations.append(
                observe(
                    profile,
                    state,
                    state_file,
                    profile.backup.check_id,
                    check_backup(profile.backup, profile.environment, now, profile.timeout_seconds),
                    datetime.now(UTC),
                    send,
                )
            )
        save_json(
            receipt_path,
            Receipt(
                profile_id=profile.profile_id,
                profile_revision=profile.revision,
                source_sha=profile.source_sha,
                profile_sha256=digest,
                environment=profile.environment,
                checked_at=now,
                completed_at=datetime.now(UTC),
                executed_by=pwd.getpwuid(os.geteuid()).pw_name,
                observations=observations,
                transport_ready=transport_ready,
            ),
        )
    return int(
        not transport_ready
        or any(
            not observation.result.ok or observation.delivery == "failed"
            for observation in observations
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--state-dir", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--receipt", type=Path)
    mode.add_argument("--heartbeat-rule", type=Path)
    mode.add_argument("--acknowledge", metavar="CHECK_ID")
    parser.add_argument("--operator")
    parser.add_argument("--ack-ref")
    parser.add_argument("--message-id")
    args = parser.parse_args()
    try:
        if args.heartbeat_rule:
            if args.heartbeat_rule.resolve() == args.profile.resolve():
                raise MonitorError("The rule must use a separate output file.")
            profile, _ = load_profile(args.profile, args.profile_sha256)
            save_json(args.heartbeat_rule, heartbeat_rule(profile))
            return
        if args.state_dir is None:
            parser.error("--state-dir is required for probes and acknowledgements")
        if args.acknowledge:
            if not args.operator or not args.ack_ref or not args.message_id:
                parser.error("--acknowledge requires --operator, --ack-ref and --message-id")
            acknowledge(
                args.profile,
                args.profile_sha256,
                args.state_dir,
                args.acknowledge,
                args.operator,
                args.ack_ref,
                args.message_id,
            )
            return
        result = run(args.profile, args.profile_sha256, args.state_dir, args.receipt)
    except (OSError, ValueError, ValidationError, MonitorError):
        parser.exit(2, "Monitor configuration, credentials or state could not be validated.\n")
    raise SystemExit(result)


if __name__ == "__main__":
    main()
