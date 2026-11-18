"""Trusted inputs and authenticated receipts for complete recovery sets."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import stat
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

HEX_SHA256 = r"^[a-f0-9]{64}$"
SOURCE_SHA = r"^[a-f0-9]{40}$"
SET_ID = r"^[a-f0-9]{32}$"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
AUTH_ALGORITHM: Final = "HMAC-SHA256"


class BackupSetError(Exception):
    pass


def canonical_bytes(model: BaseModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def require_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(character) < 32 for character in value)
    ):
        raise BackupSetError("Recovery path contains unsafe components.")
    return path


class DestinationIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    endpoint: str = Field(min_length=1)
    bucket: str = Field(min_length=3)
    prefix: str = Field(min_length=1)
    secure: bool

    @model_validator(mode="after")
    def validate_destination(self) -> Self:
        parsed = urlsplit(f"//{self.endpoint}")
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.bucket)
            or not re.fullmatch(r"[a-zA-Z0-9/_-]+", self.prefix)
        ):
            raise ValueError("Invalid recovery destination.")
        require_relative_path(self.prefix)
        return self


class FailureDomains(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: str = Field(min_length=1)
    destination: str = Field(min_length=1)


class RetentionRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_days: int = Field(gt=0, strict=True)
    monthly_months: int = Field(gt=0, strict=True)
    keep_last_good: int = Field(gt=0, strict=True)
    held_set_ids: set[str]

    @model_validator(mode="after")
    def validate_holds(self) -> Self:
        if any(not re.fullmatch(SET_ID, item) for item in self.held_set_ids):
            raise ValueError("Recovery holds require explicit backup set IDs.")
        return self


class RecoveryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision_id: Literal["D-29-RECOVERY", "SAME-HOST-LOCAL-BACKUP"]
    policy_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    rpo_minutes: int = Field(gt=0, strict=True)
    rto_minutes: int = Field(gt=0, strict=True)
    backup_interval_minutes: int = Field(gt=0, strict=True)
    maximum_capture_pause_seconds: int = Field(gt=0, strict=True)
    maximum_publication_delay_minutes: int = Field(gt=0, strict=True)
    minimum_spool_free_bytes: int = Field(gt=0, strict=True)
    retention_rules: RetentionRules
    destination_identity: DestinationIdentity
    failure_domains: FailureDomains
    key_custodians: list[str] = Field(min_length=2)
    operator: str = Field(min_length=1)
    substitute_operator: str = Field(min_length=1)
    exercise_interval: str = Field(min_length=1)
    required_artifact_categories: set[
        Literal["application_database", "grafana_database", "objects", "configuration"]
    ]
    required_configuration_paths: set[str] = Field(min_length=1)
    source_environment: str = Field(min_length=1)
    approval_ref: str = Field(min_length=1)
    approved_at: AwareDatetime

    @property
    def local_only(self) -> bool:
        return self.decision_id == "SAME-HOST-LOCAL-BACKUP"

    @property
    def backup_scope(self) -> Literal["same-host-local"] | None:
        return "same-host-local" if self.local_only else None

    @model_validator(mode="after")
    def validate_objectives(self) -> Self:
        if (
            self.backup_interval_minutes + self.maximum_publication_delay_minutes > self.rpo_minutes
            or (self.failure_domains.source == self.failure_domains.destination) != self.local_only
            or len({item.strip() for item in self.key_custodians if item.strip()}) < 2
            or self.operator == self.substitute_operator
            or not {"application_database", "objects", "configuration"}
            <= self.required_artifact_categories
        ):
            raise ValueError(
                "Recovery policy objectives, coverage, or separation are inconsistent."
            )
        endpoint = self.destination_identity.endpoint
        for path in self.required_configuration_paths:
            require_relative_path(path)
        if not self.destination_identity.secure and (
            self.source_environment != "test" or urlsplit(f"//{endpoint}").hostname not in LOOPBACK
        ):
            raise ValueError("Verified TLS is required outside an isolated loopback test.")
        return self


class CaptureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_sha: str = Field(pattern=SOURCE_SHA)
    source_environment: str = Field(min_length=1)
    configuration_sha256: str = Field(pattern=HEX_SHA256)
    image_digests: dict[str, str] = Field(min_length=1)
    configuration_files: list[str] = Field(min_length=1)
    quiescence_started_at_utc: AwareDatetime
    writers_paused: Literal[True]
    operator: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_recovery_inputs(self) -> Self:
        if len(set(self.configuration_files)) != len(self.configuration_files) or any(
            not re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
            for digest in self.image_digests.values()
        ):
            raise ValueError("Invalid recovery configuration or image inventory.")
        for value in self.configuration_files:
            require_relative_path(value)
        return self


class AuthenticationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_sha256: str = Field(pattern=HEX_SHA256)
    key_id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    algorithm: Literal["HMAC-SHA256"]
    signature: str = Field(pattern=HEX_SHA256)


class PublicationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backup_scope: Literal["same-host-local"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    backup_set_id: str = Field(pattern=SET_ID)
    manifest_sha256: str = Field(pattern=HEX_SHA256)
    snapshot_at_utc: AwareDatetime
    remote_verified_at_utc: AwareDatetime
    source_sha: str = Field(pattern=SOURCE_SHA)
    source_environment: str = Field(min_length=1)
    policy_revision: str = Field(min_length=1)
    policy_sha256: str = Field(pattern=HEX_SHA256)
    configuration_sha256: str = Field(pattern=HEX_SHA256)
    destination_identity: DestinationIdentity
    object_count: int = Field(ge=0, strict=True)
    outcome: Literal["pass"] = "pass"

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if (
            self.snapshot_at_utc.utcoffset() != timedelta(0)
            or self.remote_verified_at_utc.utcoffset() != timedelta(0)
            or self.remote_verified_at_utc < self.snapshot_at_utc
        ):
            raise ValueError("Publication requires ordered UTC timestamps.")
        return self


class ScheduledAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_sha: str = Field(pattern=SOURCE_SHA)
    started_at_utc: AwareDatetime
    completed_at_utc: AwareDatetime
    phase: Literal[
        "preflight",
        "spool",
        "quiescence",
        "capture",
        "resume",
        "publication",
        "cleanup",
        "complete",
    ]
    outcome: Literal["pass", "fail"]

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        if (
            self.started_at_utc.utcoffset() != timedelta(0)
            or self.completed_at_utc.utcoffset() != timedelta(0)
            or self.completed_at_utc < self.started_at_utc
        ):
            raise ValueError("Scheduled backup attempt requires ordered UTC timestamps.")
        if self.outcome == "pass" and self.phase != "complete":
            raise ValueError("Only a complete scheduled backup attempt can pass.")
        return self


class ScheduledAttemptReceipt(ScheduledAttempt):
    source_environment: str = Field(min_length=1, max_length=100)
    policy_revision: str = Field(min_length=1, max_length=100)
    policy_sha256: str = Field(pattern=HEX_SHA256)
    configuration_sha256: str = Field(pattern=HEX_SHA256)


class CaptureInventoryIdentity(BaseModel):
    source_sha: str = Field(pattern=SOURCE_SHA)
    source_environment: str = Field(min_length=1)
    configuration_sha256: str = Field(pattern=HEX_SHA256)


class SignedReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    algorithm: Literal["HMAC-SHA256"]
    signature: str = Field(pattern=HEX_SHA256)


class SignedPublicationReceipt(SignedReceipt):
    receipt: PublicationReceipt


class SignedScheduledAttemptReceipt(SignedReceipt):
    receipt: ScheduledAttemptReceipt


class RestoreDrillReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backup_scope: Literal["same-host-local"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    backup_set_id: str = Field(pattern=SET_ID)
    manifest_sha256: str = Field(pattern=HEX_SHA256)
    source_sha: str = Field(pattern=SOURCE_SHA)
    source_environment: str = Field(min_length=1, max_length=100)
    policy_revision: str = Field(min_length=1, max_length=100)
    policy_sha256: str = Field(pattern=HEX_SHA256)
    covers_database: bool
    covers_objects: bool
    outcome: Literal["pass", "fail"]
    rto_minutes: int = Field(ge=0, strict=True)
    started_at_utc: AwareDatetime
    verified_at_utc: AwareDatetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if (
            self.started_at_utc.utcoffset() != timedelta(0)
            or self.verified_at_utc.utcoffset() != timedelta(0)
            or self.verified_at_utc < self.started_at_utc
        ):
            raise ValueError("Restore drill requires ordered UTC timestamps.")
        return self


class SignedRestoreDrillReceipt(SignedReceipt):
    receipt: RestoreDrillReceipt


class RetentionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backup_set_id: str = Field(pattern=SET_ID)
    manifest_sha256: str = Field(pattern=HEX_SHA256)
    snapshot_at_utc: AwareDatetime


class RetentionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal[1] = 1
    policy_sha256: str = Field(pattern=HEX_SHA256)
    destination_identity: DestinationIdentity
    planned_at_utc: AwareDatetime
    candidates: list[RetentionCandidate]


class RetentionAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    purpose: Literal["backup_set_retention"]
    plan_sha256: str = Field(pattern=HEX_SHA256)
    approval_ref: str = Field(min_length=1)
    approver: str = Field(min_length=1)
    authorized_from_utc: AwareDatetime
    authorized_until_utc: AwareDatetime


def authentication_key(key_file: Path, key_id: str) -> bytes:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", key_id):
        raise BackupSetError("Invalid backup authentication key identifier.")
    try:
        status = key_file.lstat()
        if not stat.S_ISREG(status.st_mode) or status.st_mode & 0o077 or status.st_size != 32:
            raise BackupSetError("Backup authentication requires a restricted 32-byte key file.")
        key = key_file.read_bytes()
    except OSError:
        raise BackupSetError("Backup authentication key could not be read.") from None
    if len(key) != 32:
        raise BackupSetError("Backup authentication requires exactly 32 key bytes.")
    return key


def receipt_signature(receipt: BaseModel, key: bytes, domain: str) -> str:
    payload = domain.encode("ascii") + b"\x00" + canonical_bytes(receipt)
    return hmac.digest(key, payload, "sha256").hex()


def sign_publication_receipt(receipt: PublicationReceipt, *, key: bytes, key_id: str) -> bytes:
    return canonical_bytes(
        SignedPublicationReceipt(
            receipt=receipt,
            key_id=key_id,
            algorithm=AUTH_ALGORITHM,
            signature=receipt_signature(receipt, key, "publication"),
        )
    )


def verify_receipt_signature(
    signed: SignedPublicationReceipt | SignedScheduledAttemptReceipt | SignedRestoreDrillReceipt,
    raw: bytes,
    *,
    key_file: Path,
    key_id: str,
    domain: str,
) -> None:
    if signed.key_id != key_id:
        raise BackupSetError("Unknown backup authentication key identifier.")
    expected = receipt_signature(signed.receipt, authentication_key(key_file, key_id), domain)
    if canonical_bytes(signed) != raw or not hmac.compare_digest(signed.signature, expected):
        raise BackupSetError(f"Backup {domain} receipt authentication failed.")


def verify_publication_receipt(
    raw: bytes, *, key_file: Path, key_id: str, local_only: bool = False
) -> PublicationReceipt:
    try:
        signed = SignedPublicationReceipt.model_validate_json(raw)
    except ValueError:
        raise BackupSetError("Backup publication receipt has an invalid format.") from None
    verify_receipt_signature(signed, raw, key_file=key_file, key_id=key_id, domain="publication")
    if (signed.receipt.backup_scope == "same-host-local") != local_only:
        raise BackupSetError("Backup receipt does not match the requested recovery scope.")
    return signed.receipt


def sign_scheduled_attempt(receipt: ScheduledAttemptReceipt, *, key: bytes, key_id: str) -> bytes:
    return canonical_bytes(
        SignedScheduledAttemptReceipt(
            receipt=receipt,
            key_id=key_id,
            algorithm=AUTH_ALGORITHM,
            signature=receipt_signature(receipt, key, "scheduled-attempt"),
        )
    )


def verify_scheduled_attempt(raw: bytes, *, key_file: Path, key_id: str) -> ScheduledAttemptReceipt:
    try:
        signed = SignedScheduledAttemptReceipt.model_validate_json(raw)
    except ValueError:
        raise BackupSetError("Scheduled backup attempt receipt has an invalid format.") from None
    verify_receipt_signature(
        signed, raw, key_file=key_file, key_id=key_id, domain="scheduled-attempt"
    )
    return signed.receipt


def sign_restore_drill(receipt: RestoreDrillReceipt, *, key: bytes, key_id: str) -> bytes:
    return canonical_bytes(
        SignedRestoreDrillReceipt(
            receipt=receipt,
            key_id=key_id,
            algorithm=AUTH_ALGORITHM,
            signature=receipt_signature(receipt, key, "restore-drill"),
        )
    )


def verify_restore_drill(
    raw: bytes, *, key_file: Path, key_id: str, local_only: bool = False
) -> RestoreDrillReceipt:
    try:
        signed = SignedRestoreDrillReceipt.model_validate_json(raw)
    except ValueError:
        raise BackupSetError("Restore drill receipt has an invalid format.") from None
    verify_receipt_signature(signed, raw, key_file=key_file, key_id=key_id, domain="restore-drill")
    if (signed.receipt.backup_scope == "same-host-local") != local_only:
        raise BackupSetError("Backup receipt does not match the requested recovery scope.")
    return signed.receipt


def read_policy(path: Path, *, local_only: bool = False) -> tuple[RecoveryPolicy, str]:
    if path.is_symlink():
        raise BackupSetError("Recovery policy must be a regular operator-provided file.")
    try:
        raw = path.read_bytes()
        policy = RecoveryPolicy.model_validate_json(raw)
        if policy.local_only != local_only:
            raise BackupSetError("Backup policy does not match the requested recovery scope.")
        return policy, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError):
        raise BackupSetError("Approved recovery policy could not be validated.") from None
