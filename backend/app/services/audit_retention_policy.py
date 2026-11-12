from __future__ import annotations

import calendar
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    ValidationError,
    model_validator,
)
from sqlalchemy import DateTime, and_, case, extract, func, null, or_, type_coerce
from sqlalchemy.sql.elements import ColumnElement

from app.models.activity_log import ActivityLog

_MAX_POLICY_BYTES = 256 * 1024
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")]
Reference = Annotated[str, StringConstraints(min_length=1, max_length=512, pattern=r"\S")]
EventType = Literal[
    "api_request",
    "audit",
    "error",
    "log_access",
    "security_event",
    "state_change",
    "system_event",
    "user_action",
]


class AuditRetentionPolicyError(ValueError):
    """Safe operational error with no policy file contents or local path."""


class RetentionPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: EventType
    action: Identifier | None = None
    action_prefix: Identifier | None = None

    @model_validator(mode="after")
    def exactly_one_action_match(self) -> RetentionPredicate:
        if (self.action is None) == (self.action_prefix is None):
            raise ValueError("A predicate requires exactly one action or action_prefix.")
        return self

    def matches(self, action: str, event_type: str) -> bool:
        return self.event_type == event_type and (
            action == self.action
            if self.action is not None
            else action.startswith(self.action_prefix or "")
        )

    def overlaps(self, other: RetentionPredicate) -> bool:
        if self.event_type != other.event_type:
            return False
        if self.action is not None:
            return other.matches(self.action, self.event_type)
        if other.action is not None:
            return self.matches(other.action, other.event_type)
        assert self.action_prefix is not None and other.action_prefix is not None
        return self.action_prefix.startswith(other.action_prefix) or other.action_prefix.startswith(
            self.action_prefix
        )

    def sql(self) -> ColumnElement[bool]:
        action_filter = (
            ActivityLog.action == self.action
            if self.action is not None
            else ActivityLog.action.startswith(self.action_prefix, autoescape=True)
        )
        return and_(ActivityLog.event_type == self.event_type, action_filter)


class RetentionClass(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    class_id: Identifier
    predicates: Annotated[tuple[RetentionPredicate, ...], Field(min_length=1)]
    start_event: Literal["created_at"]
    duration_unit: Literal["days", "calendar_years"]
    duration_value: Annotated[StrictInt, Field(gt=0, le=365 * 9999)]
    leap_day_rule: Literal["february_28", "march_1"] | None = None
    hold_behavior: Literal["no_holds", "retain_held"]

    @model_validator(mode="after")
    def validate_duration(self) -> RetentionClass:
        if self.duration_unit == "calendar_years":
            if self.leap_day_rule is None or self.duration_value > 9999:
                raise ValueError(
                    "Calendar years require a supported leap-day rule and valid duration."
                )
        elif self.leap_day_rule is not None:
            raise ValueError("A leap-day rule is only applicable to calendar years.")
        return self

    def deadline(self, created_at: datetime) -> datetime:
        if created_at.utcoffset() is None:
            raise ValueError("Audit timestamps must be timezone-aware.")
        start = created_at.astimezone(UTC)
        if self.duration_unit == "days":
            return start + timedelta(days=self.duration_value)
        year = start.year + self.duration_value
        if start.month == 2 and start.day == 29 and not calendar.isleap(year):
            month, day = (3, 1) if self.leap_day_rule == "march_1" else (2, 28)
            return start.replace(year=year, month=month, day=day)
        return start.replace(year=year)

    def sql_deadline(self) -> ColumnElement[datetime]:
        start = func.timezone("UTC", ActivityLog.created_at)
        if self.duration_unit == "days":
            anniversary = start + func.make_interval(0, 0, 0, self.duration_value)
        else:
            anniversary = start + func.make_interval(self.duration_value)
            if self.leap_day_rule == "march_1":
                anniversary = case(
                    (
                        and_(
                            extract("month", start) == 2,
                            extract("day", start) == 29,
                            extract("day", anniversary) == 28,
                        ),
                        anniversary + func.make_interval(0, 0, 0, 1),
                    ),
                    else_=anniversary,
                )
        return type_coerce(func.timezone("UTC", anniversary), DateTime(timezone=True))


class AuditRetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[StrictInt, Field(ge=1, le=1)]
    decision_id: Literal["D-28-POLICY"]
    policy_id: Identifier
    revision: Identifier
    approved_at: AwareDatetime
    approval_ref: Reference
    mode: Literal["retain_only", "scheduled_expiry"]
    default_unknown_disposition: Literal["preserve_and_report"]
    holds_required: StrictBool
    classes: Annotated[tuple[RetentionClass, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def non_overlapping_classes(self) -> AuditRetentionPolicy:
        if len({rule.class_id for rule in self.classes}) != len(self.classes):
            raise ValueError("Retention class IDs must be unique.")
        predicates: list[RetentionPredicate] = []
        for rule in self.classes:
            if (rule.hold_behavior == "retain_held") != self.holds_required:
                raise ValueError("Class hold behavior must match the approved hold requirement.")
            for predicate in rule.predicates:
                if any(predicate.overlaps(previous) for previous in predicates):
                    raise ValueError("Retention predicates must not overlap.")
                predicates.append(predicate)
        return self

    def classify(self, action: str, event_type: str) -> RetentionClass | None:
        return next(
            (
                rule
                for rule in self.classes
                if any(predicate.matches(action, event_type) for predicate in rule.predicates)
            ),
            None,
        )

    def deadline(
        self, action: str, event_type: str, created_at: datetime, existing: datetime | None
    ) -> datetime | None:
        rule = self.classify(action, event_type)
        if rule is None:
            return existing
        policy_deadline = rule.deadline(created_at)
        return max(existing, policy_deadline) if existing is not None else policy_deadline

    def sql_deadline(self) -> ColumnElement[datetime | None]:
        return type_coerce(
            case(
                *(
                    (or_(*(predicate.sql() for predicate in rule.predicates)), rule.sql_deadline())
                    for rule in self.classes
                ),
                else_=null(),
            ),
            DateTime(timezone=True),
        )


@dataclass(frozen=True)
class VerifiedAuditRetentionPolicy:
    policy: AuditRetentionPolicy
    sha256: str


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON policy field.")
    return result


def load_audit_retention_policy(
    path: str | None, expected_sha256: str | None
) -> VerifiedAuditRetentionPolicy | None:
    if not path and not expected_sha256:
        return None
    if not path or not expected_sha256 or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise AuditRetentionPolicyError("retention_policy_path_or_digest_missing")
    try:
        with Path(path).open("rb") as source:
            content = source.read(_MAX_POLICY_BYTES + 1)
    except OSError:
        raise AuditRetentionPolicyError("retention_policy_unreadable") from None
    if len(content) > _MAX_POLICY_BYTES:
        raise AuditRetentionPolicyError("retention_policy_size_invalid")
    digest = sha256(content).hexdigest()
    if not hmac.compare_digest(digest, expected_sha256):
        raise AuditRetentionPolicyError("retention_policy_digest_mismatch")
    try:
        policy = AuditRetentionPolicy.model_validate(
            json.loads(content, object_pairs_hook=_unique_json_object)
        )
        for rule in policy.classes:
            rule.deadline(datetime.now(UTC))
    except (ValidationError, ValueError, OverflowError, RecursionError):
        raise AuditRetentionPolicyError("retention_policy_schema_invalid") from None
    if policy.approved_at > datetime.now(UTC):
        raise AuditRetentionPolicyError("retention_policy_approval_is_future")
    if policy.holds_required:
        # D-28 must select holds before their conditional schema is installed.
        raise AuditRetentionPolicyError("retention_policy_hold_schema_unavailable")
    return VerifiedAuditRetentionPolicy(policy, digest)


@lru_cache(maxsize=8)
def _pinned_writer_policy(
    path: str | None, expected_sha256: str | None
) -> VerifiedAuditRetentionPolicy | None:
    return load_audit_retention_policy(path, expected_sha256)


def audit_writer_policy(
    path: str | None, expected_sha256: str | None
) -> VerifiedAuditRetentionPolicy | None:
    # A pinned digest identifies immutable policy bytes. Destructive and operator paths
    # independently revalidate the file on every operation.
    try:
        return _pinned_writer_policy(path, expected_sha256)
    except AuditRetentionPolicyError:
        return None
