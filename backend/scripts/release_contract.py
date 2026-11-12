"""Validate independently reviewed release evidence. The host installs this file separately."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REPOSITORY = "nirzaf/garrison-investments"
VERSION = 1
WORKSTREAMS = {f"G-{number:02}" for number in range(2, 34)}
CONTROL_COUNTS = {27: 4, 28: 11, 29: 13, 30: 11, 32: 10, 33: 12}
DECISION_ROLES = {
    "D-27-SCOPE": "business_sponsor",
    "D-28-POLICY": "records_owner",
    "D-29-RECOVERY": "system_owner",
    "D-30-OPERATIONS": "operations_owner",
    "D-32-SUPPORT": "qa_lead",
    "D-33-BUSINESS": "finance_data_owner",
}
FINAL_ROLES = {"business_sponsor", "finance_data_owner", "qa_lead", "operations_owner"}
PREDEPLOY_KINDS = {"ci", "retention", "recovery", "observability", "uat", "data_reconciliation"}
FINAL_KINDS = {"deployment", "runtime_readback", "observation", "handover"}
LIVE_KINDS = {"retention", "recovery", "observability"}
CI_JOBS = {
    "Backend lint and types",
    "Frontend lint, types, tests and build",
    "Compose files are valid",
    "Backend tests",
}
ROLE_IDS = {
    "admin",
    "general_manager",
    "operation_manager",
    "project_manager",
    "civil_engineer",
    "civil_supervisor",
    "store_keeper",
    "accounts",
}
MOBILE_SCENARIOS = {7, 8, 18, 20, *range(21, 30), 34, 35}
OPERATOR_SCENARIOS = {33, 36, 37, 38, 40}
FINAL_SCENARIOS = {36, 37, 38, 40}
CONTROL_FINAL_ONLY = {
    "AC-28-10",
    "AC-29-02",
    "AC-29-06",
    "AC-30-02",
    "AC-30-06",
    "AC-30-11",
    "AC-32-09",
    "AC-32-10",
    "AC-33-10",
    "AC-33-11",
    "AC-33-12",
}


def controls_for(workstream: str) -> set[str]:
    number = int(workstream.removeprefix("G-"))
    return (
        {f"AC-{number:02}-{index:02}" for index in range(1, CONTROL_COUNTS[number] + 1)}
        if number in CONTROL_COUNTS
        else {f"REG-{workstream}"}
    )


def required_receipt_kinds(control: str) -> set[str]:
    if control.startswith("AC-28-"):
        return {"retention"}
    if control.startswith("AC-29-"):
        return {"recovery"}
    if control.startswith("AC-30-"):
        return {"observability"}
    if control in {"AC-32-04", "AC-33-03", "AC-33-09"}:
        return {"data_reconciliation"}
    if control == "AC-32-09":
        return {"runtime_readback", "observation", "uat"}
    if control == "AC-33-10":
        return {"runtime_readback", "observation", "uat", *LIVE_KINDS}
    if control == "AC-33-12":
        return {"handover"}
    if control == "AC-32-06" or control in {f"AC-33-{n:02}" for n in range(4, 9)}:
        return {"ci"}
    return {"uat"}


def required_platforms(scenario: str) -> set[str]:
    number = int(scenario.removeprefix("UAT-"))
    platforms = {"operations"} if number in {36, 37, 38} else {"desktop"}
    if number in OPERATOR_SCENARIOS:
        platforms.add("operations")
    if number in MOBILE_SCENARIOS:
        platforms.update(("ios", "android"))
    if number == 21:
        platforms.discard("desktop")
    return platforms


def control_registry() -> dict[str, Any]:
    return {
        "format_version": VERSION,
        "excluded_requirement_ids": ["G-01"],
        "controls": {item: sorted(controls_for(item)) for item in sorted(WORKSTREAMS)},
        "control_receipt_kinds": {
            control: sorted(required_receipt_kinds(control))
            for item in sorted(WORKSTREAMS)
            for control in sorted(controls_for(item))
        },
        "final_only_controls": sorted(CONTROL_FINAL_ONLY),
        "uat_platforms": {
            f"UAT-{number:02}": sorted(required_platforms(f"UAT-{number:02}"))
            for number in range(1, 41)
        },
    }


class ContractError(ValueError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def require(condition: Any, message: str, code: int = 2) -> None:
    if not condition:
        raise ContractError(code, message)


def fields(value: Any, required: str, *, optional: str = "", label: str) -> dict[str, Any]:
    mandatory = set(required.split())
    allowed = mandatory | set(optional.split())
    require(
        isinstance(value, dict) and mandatory <= value.keys() <= allowed, f"Invalid {label} fields."
    )
    return value


def meaningful(value: Any, label: str) -> str:
    require(
        isinstance(value, str)
        and value.strip() == value
        and value.lower() not in {"", "tbd", "unknown", "sample", "placeholder", "n/a", "none"},
        f"Invalid {label}.",
    )
    return value


def exact(value: Any, choices: set[str], label: str) -> str:
    require(isinstance(value, str) and value in choices, f"Invalid {label}.")
    return value


def digest(value: Any, label: str, length: int = 64) -> str:
    require(
        isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value),
        f"Invalid {label} digest.",
    )
    return value


def count(value: Any, label: str, *, minimum: int = 0) -> int:
    require(type(value) is int and value >= minimum, f"Invalid {label} count.")
    return value


def positive(value: Any, label: str) -> float:
    require(
        type(value) in {int, float} and 0 < value <= 1e15 and math.isfinite(value),
        f"Invalid {label} limit.",
    )
    return float(value)


def utc(value: Any, label: str) -> datetime:
    require(
        isinstance(value, str)
        and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)", value),
        f"Invalid {label} UTC timestamp.",
    )
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ContractError(2, f"Invalid {label} UTC timestamp.") from None


def items(value: Any, label: str, *, minimum: int = 1) -> list[Any]:
    require(isinstance(value, list) and len(value) >= minimum, f"Missing {label}.", 3)
    return value


def strings(value: Any, label: str, *, minimum: int = 1) -> set[str]:
    values = [meaningful(item, label) for item in items(value, label, minimum=minimum)]
    require(len(set(values)) == len(values), f"Duplicate {label}.")
    return set(values)


def hashes(value: Any, label: str) -> set[str]:
    values = strings(value, label)
    for item in values:
        digest(item, label)
    return values


def canonical_digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def unique_object(entries: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in entries:
        require(name not in result, "Duplicate JSON key.")
        result[name] = value
    return result


def strict_json(data: bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise ContractError(2, "Non-finite JSON number.")

    try:
        return json.loads(data, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, RecursionError) as error:
        if isinstance(error, ContractError):
            raise
        raise ContractError(2, "Invalid JSON evidence.") from None


def safe_parts(value: Any) -> list[str]:
    path = meaningful(value, "evidence path")
    parts = path.split("/")
    require(
        all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", part) for part in parts),
        "Unsafe evidence path.",
    )
    return parts


@contextmanager
def open_evidence(path: Path, *, protected: bool = False):
    """Open regular files beneath real directories, without following symlinks."""
    path = path.absolute()
    require(".." not in path.parts, "Unsafe evidence path.")
    base = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
            os.close(base)
            base = next_fd
            metadata = os.fstat(base)
            if protected:
                require(
                    metadata.st_uid == 0 and metadata.st_mode & 0o022 == 0,
                    "Unsafe host evidence directory ownership or mode.",
                )
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=base)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            require(stat.S_ISREG(metadata.st_mode), "Evidence must be a regular file.")
            if protected:
                require(
                    metadata.st_uid == 0 and metadata.st_mode & 0o022 == 0,
                    "Unsafe host evidence file ownership or mode.",
                )
            yield stream
    except FileNotFoundError:
        raise ContractError(3, "A required evidence file or directory is missing.") from None
    except OSError:
        raise ContractError(2, "Evidence path cannot be opened safely.") from None
    finally:
        os.close(base)


def json_file(path: Path, *, protected: bool = False) -> tuple[Any, str]:
    with open_evidence(path, protected=protected) as file:
        raw = file.read(4 * 1024 * 1024 + 1)
    require(len(raw) <= 4 * 1024 * 1024, "JSON evidence exceeds the size limit.")
    return strict_json(raw), hashlib.sha256(raw).hexdigest()


class Evidence:
    def __init__(self, root: Path, *, protected: bool) -> None:
        self.root = root.absolute()
        self.protected = protected

    def load(self, ref: Any, *, parse: bool = False) -> Any:
        record = fields(ref, "path sha256 size_bytes", optional="sensitivity", label="artifact")
        location = self.root.joinpath(*safe_parts(record["path"]))
        expected_size = count(record["size_bytes"], "artifact size", minimum=1)
        expected_hash = digest(record["sha256"], "artifact")
        if "sensitivity" in record:
            exact(record["sensitivity"], {"restricted", "sanitized"}, "artifact sensitivity")
        with open_evidence(location, protected=self.protected) as file:
            require(
                os.fstat(file.fileno()).st_size == expected_size,
                "Evidence artifact size differs from its reference.",
                3,
            )
            if parse:
                require(expected_size <= 4 * 1024 * 1024, "JSON evidence exceeds the size limit.")
                raw = file.read(expected_size + 1)
                observed = hashlib.sha256(raw).hexdigest()
            else:
                raw = b""
                observed = hashlib.file_digest(file, "sha256").hexdigest()
        require(
            observed == expected_hash, "Evidence artifact digest differs from its reference.", 3
        )
        return strict_json(raw) if parse else expected_hash

    def artifacts(self, references: Any, label: str) -> set[str]:
        result = set()
        for item in items(references, label):
            require(
                isinstance(item, dict) and "sensitivity" in item, "Missing artifact sensitivity."
            )
            result.add(self.load(item))
        return result


def github_record(path: str, token: str | None) -> dict[str, Any]:
    require(token, "GitHub verification credentials are unavailable.", 5)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/{path}", headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            result = strict_json(response.read(4 * 1024 * 1024 + 1))
    except (URLError, TimeoutError, OSError, ContractError):
        raise ContractError(5, "Current GitHub evidence could not be verified.") from None
    require(isinstance(result, dict), "GitHub evidence has an unexpected response.", 5)
    return result


def checked_run(
    run_id: int, sha: str, token: str | None, *, ci: bool, active: bool = False
) -> dict[str, Any]:
    run = github_record(f"actions/runs/{run_id}", token)
    repository = run.get("head_repository") or {}
    require(
        run.get("id") == run_id
        and run.get("head_sha") == sha
        and repository.get("full_name") == REPOSITORY
        and run.get("head_branch") == "main"
        and run.get("path")
        == (".github/workflows/ci.yml" if ci else ".github/workflows/deploy.yml")
        and run.get("event") in ({"push"} if ci else {"workflow_run", "workflow_dispatch"})
        and (
            (not ci and run.get("status") == "in_progress")
            if active
            else (run.get("status") == "completed" and run.get("conclusion") == "success")
        ),
        "GitHub run does not match the required release candidate and workflow.",
        3,
    )
    return run


def deployment_operator(run_id: int, sha: str, token: str | None) -> str:
    run = checked_run(run_id, sha, token, ci=False, active=True)
    actor = run.get("triggering_actor") or run.get("actor")
    if not isinstance(actor, dict):
        raise ContractError(3, "The deployment operator could not be verified from GitHub.")
    return meaningful(actor.get("login"), "GitHub release operator")


def approval_time(value: Any, now: datetime, label: str) -> datetime:
    approved = utc(value, label)
    require(approved <= now, "Approval is dated in the future.", 3)
    return approved


class Approvals:
    """Match exact approval records to a registry populated by independent verification."""

    def __init__(self, evidence: Evidence, path: Path, now: datetime, *, production: bool) -> None:
        require(
            not path.absolute().is_relative_to(evidence.root),
            "The approval trust registry must be outside the release evidence root.",
        )
        value, self.digest = json_file(path, protected=production or evidence.protected)
        registry = fields(
            value, "format_version verified_approvals", label="approval trust registry"
        )
        require(
            type(registry["format_version"]) is int and registry["format_version"] == VERSION,
            "Unsupported approval trust registry version.",
        )
        require(isinstance(registry["verified_approvals"], dict), "Invalid verified approvals.")
        self.entries = registry["verified_approvals"]
        self.evidence = evidence
        self.now = now

    def check(
        self, ref: Any, purpose: str, subject: str, *, role: str | None = None
    ) -> dict[str, Any]:
        value = self.evidence.load(ref, parse=True)
        approval = fields(
            value,
            "purpose approver_identity authority_role subject_sha256 approved_at approval_artifact",
            optional="source_sha environment valid_from valid_until authorization_reference",
            label="approval",
        )
        identity = meaningful(approval["approver_identity"], "approver identity")
        authority = meaningful(approval["authority_role"], "approval authority role")
        approved_at = approval_time(approval["approved_at"], self.now, "approval")
        require(
            approval["purpose"] == purpose
            and approval["subject_sha256"] == subject
            and (role is None or authority == role),
            "Approval does not match the required purpose, subject or authority.",
            3,
        )
        verified = self.entries.get(ref["sha256"])
        require(verified is not None, "Approval lacks independent verification.", 3)
        entry = fields(
            verified,
            "approver_identity authority_role purpose provenance_reference verified_by verified_at",
            label="verified approval",
        )
        require(
            entry["approver_identity"] == identity
            and entry["authority_role"] == authority
            and entry["purpose"] == purpose,
            "Trusted approval provenance does not match its record.",
            3,
        )
        meaningful(entry["provenance_reference"], "verified approval provenance")
        verifier = meaningful(entry["verified_by"], "approval verifier")
        require(
            verifier != identity
            and approval_time(entry["verified_at"], self.now, "provenance verification")
            >= approved_at,
            "Approval requires timely independent verification.",
            3,
        )
        self.evidence.load(approval["approval_artifact"])
        return approval


def check_execution(
    started: Any, completed: Any, now: datetime, label: str
) -> tuple[datetime, datetime]:
    start = utc(started, f"{label} start")
    end = utc(completed, f"{label} completion")
    require(start <= end <= now, f"Invalid {label} execution window.", 3)
    return start, end


def assertions(value: Any, required: set[str], label: str) -> None:
    require(isinstance(value, dict) and required <= value.keys(), f"Missing {label} assertions.", 3)
    require(all(result is True for result in value.values()), f"A {label} assertion failed.", 4)


def quantities(value: Any, label: str) -> dict[str, int]:
    require(isinstance(value, dict) and bool(value), f"Missing {label} counts.", 3)
    return {meaningful(key, label): count(number, label) for key, number in value.items()}


def compare_totals(value: Any, label: str) -> None:
    for row in items(value, label):
        row = fields(row, "metric expected observed unit", label=f"{label} comparison")
        meaningful(row["metric"], "control metric")
        meaningful(row["unit"], "control unit")
        expected = meaningful(row["expected"], "expected total")
        observed = meaningful(row["observed"], "observed total")
        require(expected == observed, f"A {label} control total differs.", 4)


def decision_scope(record: dict[str, Any], scope_hash: str) -> None:
    require(
        record["delivery_scope"] == "launch_readiness_only", "Logistics scope is unresolved.", 3
    )
    require(
        record["accepted_inventory_sha256"] == scope_hash
        and record["excluded_requirement_ids"] == ["G-01"],
        "Scope approval does not match the frozen inventory and exclusion.",
        3,
    )


def decision_retention(record: dict[str, Any], evidence: Evidence) -> None:
    exact(record["mode"], {"retain_only", "scheduled_expiry"}, "retention mode")
    require(
        record["unknown_disposition"] == "preserve_and_report", "Unsafe unknown retention mode."
    )
    require(type(record["holds_required"]) is bool, "Invalid retention hold requirement.")
    class_ids = set()
    for item in items(record["classes"], "retention classes"):
        row = fields(
            item,
            "class_id predicates start_event duration_unit duration_value hold_behavior",
            optional="leap_day_rule",
            label="retention class",
        )
        class_id = meaningful(row["class_id"], "retention class ID")
        require(class_id not in class_ids, "Duplicate retention class.")
        class_ids.add(class_id)
        for raw in items(row["predicates"], "retention predicates"):
            predicate = fields(
                raw, "event_type", optional="action action_prefix", label="retention predicate"
            )
            meaningful(predicate["event_type"], "retention event type")
            actions = [predicate.get(key) for key in ("action", "action_prefix")]
            require(
                sum(action is not None for action in actions) == 1, "Ambiguous retention action."
            )
            meaningful(next(action for action in actions if action is not None), "retention action")
        require(row["start_event"] == "created_at", "Unsupported retention start event.")
        require(
            row["hold_behavior"] == ("retain_held" if record["holds_required"] else "no_holds"),
            "Retention hold behavior differs from the approved decision.",
            3,
        )
        unit = exact(row["duration_unit"], {"days", "calendar_years"}, "retention duration unit")
        count(row["duration_value"], "retention duration", minimum=1)
        if unit == "calendar_years":
            exact(row.get("leap_day_rule"), {"february_28", "march_1"}, "retention leap-day rule")
        else:
            require(
                row.get("leap_day_rule") is None, "A day-based rule cannot set a leap-day rule."
            )
    policy = fields(
        evidence.load(record["policy_ref"], parse=True),
        "schema_version decision_id policy_id revision approved_at approval_ref mode "
        "default_unknown_disposition holds_required classes",
        label="installed retention policy",
    )
    meaningful(policy["approval_ref"], "installed retention policy approval")
    require(
        type(policy["schema_version"]) is int
        and policy["schema_version"] == 1
        and policy["default_unknown_disposition"] == record["unknown_disposition"]
        and utc(policy["approved_at"], "retention policy approval")
        == utc(record["approved_at"], "decision approval")
        and all(
            policy[key] == record[key]
            for key in ("decision_id", "policy_id", "revision", "mode", "holds_required", "classes")
        ),
        "Installed retention policy differs from its approved decision.",
        3,
    )


def decision_recovery(record: dict[str, Any], target: str, evidence: Evidence) -> None:
    interval = count(record["backup_interval_minutes"], "backup interval", minimum=1)
    pause = count(record["maximum_capture_pause_seconds"], "maximum capture pause", minimum=1)
    delay = count(record["maximum_publication_delay_minutes"], "publication delay", minimum=1)
    rpo = count(record["rpo_minutes"], "RPO", minimum=1)
    count(record["rto_minutes"], "RTO", minimum=1)
    require(interval + pause / 60 + delay <= rpo, "Recovery cadence cannot satisfy the RPO.", 4)
    meaningful(record["exercise_interval"], "recovery exercise interval")
    count(record["minimum_spool_free_bytes"], "recovery spool bytes", minimum=1)
    retention = fields(
        record["retention_rules"],
        "daily_days monthly_months keep_last_good held_set_ids",
        label="backup retention",
    )
    for key in ("daily_days", "monthly_months", "keep_last_good"):
        count(retention[key], f"backup retention {key}", minimum=1)
    for item in strings(retention["held_set_ids"], "held backup set IDs", minimum=0):
        digest(item, "held backup set ID", 32)
    domains = fields(record["failure_domains"], "source destination", label="failure domains")
    primary = meaningful(domains["source"], "primary failure domain")
    require(
        meaningful(domains["destination"], "backup failure domain") != primary,
        "Recovery storage must survive loss of the primary.",
        3,
    )
    destination = fields(
        record["destination_identity"], "endpoint bucket prefix secure", label="backup destination"
    )
    for key in ("endpoint", "bucket", "prefix"):
        meaningful(destination[key], f"backup destination {key}")
    require(
        destination["secure"] is True or (target == "test" and destination["secure"] is False),
        "Independent backup destination requires TLS.",
        3,
    )
    strings(record["key_custodians"], "recovery key custodians", minimum=2)
    require(
        meaningful(record["operator"], "recovery operator")
        != meaningful(record["substitute_operator"], "substitute recovery operator"),
        "Recovery requires a separate substitute operator.",
        3,
    )
    categories = strings(record["required_artifact_categories"], "recovery artifact categories")
    require(
        {"application_database", "configuration", "objects"}
        <= categories
        <= {"application_database", "configuration", "objects", "grafana_database"},
        "Recovery policy lacks database, configuration or referenced-object coverage.",
        3,
    )
    for path in strings(record["required_configuration_paths"], "required recovery configuration"):
        safe_parts(path)
    expected = {
        key: value for key, value in record.items() if key not in {"policy_ref", "approval_ref"}
    }
    policy = fields(
        evidence.load(record["policy_ref"], parse=True),
        " ".join(expected) + " approval_ref source_environment",
        label="installed recovery policy",
    )
    meaningful(policy["approval_ref"], "installed recovery policy approval")
    require(policy["source_environment"] == target, "Recovery policy environment differs.", 3)
    require(
        all(policy[key] == value for key, value in expected.items() if key != "approved_at")
        and utc(policy["approved_at"], "recovery policy approval")
        == utc(record["approved_at"], "decision approval"),
        "Installed recovery policy differs from its approved decision.",
        3,
    )


def decision_operations(record: dict[str, Any], target: str, evidence: Evidence) -> None:
    require(record["environment"] == target, "Operations decision targets another environment.", 3)
    strings(record["targets"], "monitor targets")
    for field in (
        "probe_interval_seconds",
        "failure_threshold",
        "recovery_threshold",
        "repeat_interval_seconds",
        "acknowledgement_limit_seconds",
    ):
        count(record[field], f"operations {field}", minimum=1)
    require(
        meaningful(record["primary_responder"], "primary responder")
        != meaningful(record["substitute_responder"], "substitute responder"),
        "Operations requires a separate substitute responder.",
        3,
    )
    for field in ("recipient_ref", "transport_ref", "maintenance_rules_ref", "profile_ref"):
        evidence.load(record[field])
    profile = evidence.load(record["profile_ref"], parse=True)
    require(isinstance(profile, dict), "Invalid installed monitor profile.")
    targets = items(profile.get("targets"), "installed monitor targets")
    require(
        all(isinstance(row, dict) for row in targets)
        and {row.get("url") for row in targets} == set(record["targets"])
        and all(
            profile.get(key) == record[key]
            for key in (
                "profile_id",
                "revision",
                "environment",
                "probe_interval_seconds",
                "failure_threshold",
                "recovery_threshold",
                "repeat_interval_seconds",
                "acknowledgement_limit_seconds",
                "primary_responder",
                "substitute_responder",
            )
        ),
        "Installed monitor profile differs from the approved operations decision.",
        3,
    )


def device_key(target: Any) -> tuple[str, str, str, str, str]:
    row = fields(
        target, "platform device_model os_version browser browser_version", label="supported device"
    )
    return (
        exact(row["platform"], {"desktop", "ios", "android"}, "device platform"),
        meaningful(row["device_model"], "device model"),
        meaningful(row["os_version"], "OS version"),
        meaningful(row["browser"], "browser"),
        meaningful(row["browser_version"], "browser version"),
    )


def scenario_matrix(record: Any) -> dict[str, set[tuple[str, str]]]:
    expected = control_registry()["uat_platforms"]
    require(
        isinstance(record, dict) and set(record) == set(expected), "Incomplete UAT scenario map.", 3
    )
    matrix = {}
    for scenario, raw_targets in record.items():
        targets = [
            fields(row, "platform role", label="scenario platform and role")
            for row in items(raw_targets, "UAT scenario targets")
        ]
        pairs = {
            (
                exact(
                    row["platform"],
                    {"desktop", "ios", "android", "operations"},
                    "scenario platform",
                ),
                meaningful(row["role"], "scenario role"),
            )
            for row in targets
        }
        require(len(pairs) == len(targets), "Duplicate scenario platform and role.")
        require(
            set(expected[scenario]) <= {platform for platform, _ in pairs},
            "Mandatory UAT platform omitted.",
            3,
        )
        matrix[scenario] = pairs
    require(
        {("desktop", role) for role in ROLE_IDS} <= matrix["UAT-01"],
        "Sign-in UAT omits an application role.",
        3,
    )
    return matrix


def decision_support(record: dict[str, Any]) -> None:
    desktop = {device_key(value) for value in items(record["desktop_targets"], "desktop targets")}
    mobile = {
        device_key(value) for value in items(record["physical_mobile_targets"], "physical targets")
    }
    require(all(device[0] == "desktop" for device in desktop), "Invalid desktop platform.")
    require(
        {"Chrome", "Edge"} <= {device[3] for device in desktop}
        and {("ios", "Safari"), ("android", "Chrome")}
        <= {(device[0], device[3]) for device in mobile}
        and all(device[0] != "desktop" for device in mobile),
        "Approved desktop and physical mobile browser targets are incomplete.",
        3,
    )
    scenario_matrix(record["scenario_platform_map"])
    strings(record["network_profiles"], "approved network profiles")
    budgets = record["budgets"]
    require(
        isinstance(budgets, dict) and bool(budgets),
        "Missing performance and data-volume budgets.",
        3,
    )
    for key, value in budgets.items():
        positive(value, meaningful(key, "budget name"))
    strings(record["testers"], "approved testers")


def decision_business(record: dict[str, Any], evidence: Evidence) -> None:
    evidence.load(record["assignment_export"])
    sample_kinds = {"boq", "report_pdf", "invoice_payment", "document_revision", "analytics_export"}
    samples = record["accepted_samples"]
    require(
        isinstance(samples, dict) and set(samples) == sample_kinds,
        "Incomplete business sample list.",
        3,
    )
    for ref in samples.values():
        evidence.load(ref)
    try:
        ZoneInfo(meaningful(record["timezone"], "business timezone"))
    except (ZoneInfoNotFoundError, ValueError):
        raise ContractError(2, "Invalid business timezone.") from None
    require(
        isinstance(record["currency"], str) and re.fullmatch(r"[A-Z]{3}", record["currency"]),
        "Invalid currency code.",
    )
    require(
        count(record["precision"], "business decimal precision") <= 12,
        "Invalid business decimal precision.",
    )
    require(
        isinstance(record["material_approval_threshold"], str)
        and re.fullmatch(r"\d+(?:\.\d+)?", record["material_approval_threshold"]),
        "Invalid exact material approval threshold.",
    )
    for field in ("tax_rounding_ref", "numbering_rules_ref"):
        evidence.load(record[field])
    source_hashes = set()
    for value in items(record["import_sources"], "approved import sources"):
        source = fields(value, "artifact rows control_totals", label="import source")
        source_hash = evidence.load(source["artifact"])
        require(source_hash not in source_hashes, "Duplicate approved import source.")
        source_hashes.add(source_hash)
        count(source["rows"], "approved import rows")
        compare_totals(source["control_totals"], "approved import")
    signatories = record["signatories"]
    require(
        isinstance(signatories, dict) and set(signatories) == FINAL_ROLES,
        "Missing final signatories.",
        3,
    )
    for name in signatories.values():
        meaningful(name, "named signatory")
    meaningful(record["release_authorizer"], "release authorizer")


DECISION_FIELDS = {
    "D-27-SCOPE": "delivery_scope accepted_inventory_sha256 excluded_requirement_ids",
    "D-28-POLICY": "policy_id mode classes unknown_disposition holds_required policy_ref",
    "D-29-RECOVERY": (
        "policy_id rpo_minutes rto_minutes backup_interval_minutes maximum_capture_pause_seconds "
        "maximum_publication_delay_minutes retention_rules destination_identity failure_domains "
        "key_custodians operator substitute_operator exercise_interval "
        "required_artifact_categories "
        "minimum_spool_free_bytes required_configuration_paths policy_ref"
    ),
    "D-30-OPERATIONS": (
        "profile_id environment targets probe_interval_seconds failure_threshold "
        "recovery_threshold "
        "repeat_interval_seconds acknowledgement_limit_seconds primary_responder "
        "substitute_responder "
        "recipient_ref transport_ref maintenance_rules_ref profile_ref"
    ),
    "D-32-SUPPORT": (
        "desktop_targets physical_mobile_targets scenario_platform_map network_profiles "
        "budgets testers"
    ),
    "D-33-BUSINESS": (
        "assignment_export accepted_samples timezone currency precision tax_rounding_ref "
        "material_approval_threshold numbering_rules_ref import_sources signatories "
        "release_authorizer"
    ),
}


def run_url(run_id: int) -> str:
    return f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"


def receipt_ci(
    payload: Any, evidence: Evidence, sha: str, token: str | None, required_run: int | None
) -> None:
    data = fields(
        payload, "run_id run_url repository ref conclusion jobs suites checks", label="CI result"
    )
    run_id = count(data["run_id"], "CI run ID", minimum=1)
    require(
        (required_run is None or run_id == required_run)
        and data["run_url"] == run_url(run_id)
        and data["repository"] == REPOSITORY
        and data["ref"] == "refs/heads/main"
        and data["conclusion"] == "success",
        "CI evidence targets a different release or did not succeed.",
        3,
    )
    jobs: dict[int, str] = {}
    for value in items(data["jobs"], "CI jobs"):
        job = fields(value, "id name url conclusion", label="CI job")
        job_id = count(job["id"], "CI job ID", minimum=1)
        name = meaningful(job["name"], "CI job name")
        require(job_id not in jobs and name not in jobs.values(), "Duplicate CI job.")
        require(
            job["url"] == f"{run_url(run_id)}/job/{job_id}" and job["conclusion"] == "success",
            "CI job is not a verified success.",
            4,
        )
        jobs[job_id] = name
    require(CI_JOBS <= set(jobs.values()), "Required CI jobs are missing.", 3)
    checked_run(run_id, sha, token, ci=True)
    live = github_record(f"actions/runs/{run_id}/jobs?per_page=100", token)
    live_jobs = live.get("jobs")
    if not isinstance(live_jobs, list) or live.get("total_count") != len(live_jobs):
        raise ContractError(5, "Incomplete GitHub job verification.")
    observed = {
        row["id"]: row["name"]
        for row in live_jobs
        if row.get("head_sha") == sha
        and row.get("status") == "completed"
        and row.get("conclusion") == "success"
    }
    require(
        all(observed.get(key) == name for key, name in jobs.items()),
        "GitHub jobs differ from the CI evidence.",
        3,
    )

    suites = set()
    for value in items(data["suites"], "test suites"):
        suite = fields(value, "name passed failed skipped warnings report", label="test suite")
        name = exact(suite["name"], {"backend", "frontend", "browser"}, "test suite name")
        require(name not in suites, "Duplicate CI test suite.")
        suites.add(name)
        counts = {
            key: count(suite[key], f"{name} {key}", minimum=int(key == "passed"))
            for key in ("passed", "failed", "skipped", "warnings")
        }
        require(
            counts["failed"] == counts["skipped"] == 0,
            "A CI suite has failures or unexplained skips.",
            4,
        )
        require(
            evidence.load(suite["report"], parse=True) == counts,
            "Raw test report counts differ from the receipt.",
            3,
        )
    require(suites == {"backend", "frontend", "browser"}, "Missing a mandatory test suite.", 3)
    assertions(
        data["checks"],
        {"lint", "typing", "openapi", "typescript_contract", "frontend_build", "compose"},
        "CI check",
    )


def receipt_retention(payload: Any, decision: dict[str, Any], policy_hash: str) -> None:
    data = fields(
        payload,
        "policy_sha256 mode purge_enabled legacy_counts assertions",
        label="retention result",
    )
    require(
        data["policy_sha256"] == policy_hash and data["mode"] == decision["mode"],
        "Retention receipt does not match the approved policy.",
        3,
    )
    require(
        data["purge_enabled"] is (decision["mode"] == "scheduled_expiry"),
        "Effective retention mode differs from policy.",
        4,
    )
    legacy = fields(
        data["legacy_counts"],
        "total resolved unknown_preserved unresolved",
        label="retention legacy counts",
    )
    for key, value in legacy.items():
        count(value, f"retention {key}")
    require(
        legacy["total"] == legacy["resolved"] + legacy["unknown_preserved"] + legacy["unresolved"]
        and legacy["unresolved"] == 0,
        "Retention legacy population has unresolved or inconsistent counts.",
        4,
    )
    required = {"future_protected", "unknown_protected", "archived_queries", "capacity_reviewed"}
    if decision["mode"] == "scheduled_expiry":
        required |= {"expiry_demonstrated", "destructive_authorization_verified"}
    if decision["holds_required"]:
        required.add("holds_protected")
    assertions(data["assertions"], required, "retention")


def receipt_recovery(
    payload: Any,
    decision: dict[str, Any],
    expected_heads: list[str],
    executor: str,
    start: datetime,
    end: datetime,
) -> None:
    times = (
        "snapshot_at_utc",
        "remote_verified_at_utc",
        "failure_declared_at_utc",
        "key_access_completed_at_utc",
        "restore_started_at_utc",
        "database_restored_at_utc",
        "objects_verified_at_utc",
        "business_ready_at_utc",
    )
    data = fields(
        payload,
        "backup_set_id manifest_sha256 manifest_auth_sha256 publication_sha256 "
        "backup_format_version policy_sha256 destination_identity "
        "required_object_count restored_object_count required_category_counts "
        "restored_category_counts "
        "expected_schema_heads observed_schema_heads control_totals assertions second_operator "
        "rpo_minutes rto_minutes capture_pause_seconds " + " ".join(times),
        label="recovery result",
    )
    digest(data["backup_set_id"], "backup set ID", 32)
    digest(data["manifest_sha256"], "authenticated backup manifest")
    digest(data["manifest_auth_sha256"], "backup authentication record")
    digest(data["publication_sha256"], "signed backup publication record")
    require(
        data["backup_format_version"] == 2, "Recovery requires authenticated backup format 2.", 3
    )
    require(
        data["destination_identity"] == decision["destination_identity"],
        "Recovery destination differs from policy.",
        3,
    )
    require(
        data["policy_sha256"] == decision["policy_ref"]["sha256"],
        "Recovery used a different installed policy.",
        3,
    )
    executed = [utc(data[key], "recovery stage") for key in times]
    require(
        start <= executed[0] <= executed[-1] <= end and executed == sorted(executed),
        "Recovery stage timestamps are inconsistent.",
        3,
    )
    snapshot, verified, failure, _, _, _, _, ready = executed
    rpo = (failure - snapshot).total_seconds() / 60
    rto = (ready - failure).total_seconds() / 60
    require(
        positive(data["rpo_minutes"], "receipt RPO") == decision["rpo_minutes"]
        and positive(data["rto_minutes"], "receipt RTO") == decision["rto_minutes"],
        "Recovery objectives differ from the approved decision.",
        3,
    )
    require(
        rpo <= decision["rpo_minutes"]
        and rto <= decision["rto_minutes"]
        and (verified - snapshot).total_seconds() / 60
        <= decision["maximum_publication_delay_minutes"]
        and count(data["capture_pause_seconds"], "capture pause")
        <= decision["maximum_capture_pause_seconds"],
        "Measured recovery missed an approved objective.",
        4,
    )
    require(
        count(data["required_object_count"], "required object")
        == count(data["restored_object_count"], "restored object"),
        "Recovered object counts differ.",
        4,
    )
    required = quantities(data["required_category_counts"], "required category")
    recovered = quantities(data["restored_category_counts"], "recovered category")
    require(
        set(decision["required_artifact_categories"]) <= required.keys() and required == recovered,
        "Recovery did not cover the approved artifact categories.",
        4,
    )
    require(
        data["expected_schema_heads"] == data["observed_schema_heads"] == expected_heads,
        "Recovered schema heads differ from the release subject.",
        4,
    )
    require(
        executor == decision["operator"]
        and data["second_operator"] == decision["substitute_operator"],
        "Recovery lacks named primary and substitute operator evidence.",
        3,
    )
    compare_totals(data["control_totals"], "recovery")
    assertions(
        data["assertions"],
        {
            "primary_unavailable",
            "independent_key_access",
            "independent_configuration",
            "independent_destination",
            "authenticated_manifest",
            "object_checksums",
            "business_workflows",
        },
        "recovery",
    )


ALERT_RULES = {
    "garrison-unhandled-errors",
    "garrison-http-5xx-burst",
    "garrison-celery-retries",
    "garrison-slow-http",
    "garrison-log-pipeline-errors",
}


def receipt_observability(
    payload: Any,
    profile_hash: str,
    approved: dict[str, Any],
    approvals: Approvals,
    environment: str,
    start: datetime,
    end: datetime,
) -> None:
    data = fields(
        payload, "profile_sha256 trace_ids alert_events assertions", label="observability result"
    )
    require(
        data["profile_sha256"] == profile_hash,
        "Observability profile differs from approved configuration.",
        3,
    )
    strings(data["trace_ids"], "application and worker trace IDs", minimum=2)
    rules = set()
    acknowledged = False
    for value in items(data["alert_events"], "alert events"):
        row = fields(
            value,
            "rule_id environment synthetic trigger_at evaluated_at fired_at recovered_at "
            "resolved_at "
            "message_id recipient acknowledged_at acknowledgement_ref independent_path",
            label="alert event",
        )
        rule = meaningful(row["rule_id"], "alert rule ID")
        require(rule not in rules, "Duplicate alert rule.")
        rules.add(rule)
        require(
            row["environment"] == environment and type(row["synthetic"]) is bool,
            "Invalid alert environment.",
        )
        executed = [
            utc(row[key], "alert stage")
            for key in ("trigger_at", "evaluated_at", "fired_at", "recovered_at", "resolved_at")
        ]
        require(
            start <= executed[0] <= executed[-1] <= end and executed == sorted(executed),
            "Alert stage timestamps are inconsistent.",
            3,
        )
        require(type(row["independent_path"]) is bool, "Invalid independent alert path marker.")
        meaningful(row["message_id"], "provider message ID")
        recipient = meaningful(row["recipient"], "alert recipient identity")
        ack = utc(row["acknowledged_at"], "alert acknowledgement")
        require(
            executed[2] <= ack <= end
            and (ack - executed[2]).total_seconds() <= approved["acknowledgement_limit_seconds"],
            "Alert acknowledgement exceeded the approved bound.",
            4,
        )
        acknowledgement = approvals.check(
            row["acknowledgement_ref"],
            "acknowledge_alert",
            canonical_digest(
                {key: item for key, item in row.items() if key != "acknowledgement_ref"}
            ),
            role="alert_recipient",
        )
        require(
            acknowledgement["approver_identity"] == recipient
            and acknowledgement["approved_at"] == row["acknowledged_at"],
            "Alert acknowledgement provenance differs from the named recipient or time.",
            3,
        )
        acknowledged |= recipient == approved["primary_responder"] and row["independent_path"]
    require(ALERT_RULES <= rules, "Mandatory firing and resolution evidence is missing.", 3)
    require(acknowledged, "The primary responder has not acknowledged the independent path.", 3)
    assertions(
        data["assertions"],
        {"ingestion", "pipeline_silence", "off_host_failure", "backup_freshness"},
        "observability",
    )


def receipt_uat(
    payload: Any,
    support: dict[str, Any],
    evidence: Evidence,
    approvals: Approvals,
    sha: str,
    environment: str,
    configuration: str,
    artifact_hashes: set[str],
    phase: str,
    start: datetime,
    end: datetime,
) -> set[str]:
    data = fields(payload, "scenarios measurements assertions", label="UAT result")
    matrix = scenario_matrix(support["scenario_platform_map"])
    devices = {
        device_key(value)
        for value in support["desktop_targets"] + support["physical_mobile_targets"]
    }
    observed: set[tuple[str, str, str, str]] = set()
    observed_browsers: set[tuple[str, str]] = set()
    defect_ids: set[str] = set()
    for value in items(data["scenarios"], "UAT scenario results"):
        row = fields(
            value,
            "scenario_id role fixture_version source_sha environment configuration_sha256 device "
            "physical_device executed_at expected actual outcome artifact_sha256 defect_ids "
            "tester reviewer_approval",
            optional="retest_receipt",
            label="UAT scenario result",
        )
        scenario = exact(row["scenario_id"], set(matrix), "scenario ID")
        role = meaningful(row["role"], "scenario role")
        require(isinstance(row["device"], dict), "Missing UAT device.")
        if row["device"].get("platform") == "operations":
            fields(
                row["device"],
                "platform device_model os_version browser browser_version",
                label="operator workstation",
            )
            for key in ("device_model", "os_version", "browser", "browser_version"):
                meaningful(row["device"][key], f"operator {key}")
            platform = "operations"
        else:
            device = device_key(row["device"])
            require(device in devices, "UAT device/browser is outside approved support.", 3)
            platform = device[0]
            observed_browsers.add((platform, device[3]))
        require(
            (platform, role) in matrix[scenario],
            "UAT scenario role/platform is outside the frozen map.",
            3,
        )
        observed.add(
            (scenario, platform, role, row["device"]["browser"] if platform != "operations" else "")
        )
        require(type(row["physical_device"]) is bool, "Invalid physical device marker.")
        if platform in {"ios", "android"}:
            require(row["physical_device"] is True, "Mobile UAT requires a physical device.", 3)
        require(
            row["source_sha"] == sha
            and row["environment"] == environment
            and row["configuration_sha256"] == configuration
            and start <= utc(row["executed_at"], "UAT execution") <= end,
            "UAT evidence identity or execution window is stale.",
            3,
        )
        require(row["outcome"] == "pass", "A mandatory UAT scenario did not pass.", 4)
        for key in ("fixture_version", "expected", "actual"):
            meaningful(row[key], f"UAT {key}")
        require(row["tester"] in support["testers"], "UAT tester is outside approved support.", 3)
        require(
            hashes(row["artifact_sha256"], "scenario artifact") <= artifact_hashes,
            "UAT scenario artifact is absent from the verified receipt.",
            3,
        )
        defects = strings(row["defect_ids"], "UAT defect IDs", minimum=0)
        defect_ids.update(defects)
        if defects:
            require("retest_receipt" in row, "A UAT defect lacks retest evidence.", 3)
            retest = fields(
                evidence.load(row["retest_receipt"], parse=True),
                "source_sha environment configuration_sha256 scenario_id defect_ids outcome",
                label="UAT retest",
            )
            require(
                retest["source_sha"] == sha
                and retest["environment"] == environment
                and retest["configuration_sha256"] == configuration
                and retest["scenario_id"] == scenario
                and retest["outcome"] == "pass"
                and set(retest["defect_ids"]) == defects,
                "UAT retest does not pass against the candidate and defect list.",
                4,
            )
        reviewed = {key: item for key, item in row.items() if key != "reviewer_approval"}
        approval = approvals.check(
            row["reviewer_approval"], "review_uat", canonical_digest(reviewed), role="qa_lead"
        )
        require(
            approval["approver_identity"] != row["tester"]
            and utc(approval["approved_at"], "scenario review")
            >= utc(row["executed_at"], "scenario execution"),
            "Each UAT result requires an independent reviewer after execution.",
            3,
        )
    browsers = {"desktop": ("Chrome", "Edge"), "ios": ("Safari",), "android": ("Chrome",)}
    expected = {
        (scenario, platform, role, browser)
        for scenario, pairs in matrix.items()
        if (int(scenario.removeprefix("UAT-")) in FINAL_SCENARIOS) == (phase == "final")
        for platform, role in pairs
        for browser in browsers.get(platform, ("",))
    }
    require(
        expected <= observed, "A required UAT scenario, platform or role has no executed pass.", 3
    )
    if phase == "predeploy":
        require(
            {("desktop", "Chrome"), ("desktop", "Edge"), ("ios", "Safari"), ("android", "Chrome")}
            <= observed_browsers,
            "Desktop and physical mobile UAT coverage is incomplete.",
            3,
        )
    measurements = data["measurements"]
    require(
        isinstance(measurements, dict) and set(support["budgets"]) <= measurements.keys(),
        "Missing approved UAT budget measurements.",
        3,
    )
    require(
        all(
            0 <= measurements[key] <= limit
            for key, limit in support["budgets"].items()
            if type(measurements[key]) in {int, float}
        )
        and all(type(measurements[key]) in {int, float} for key in support["budgets"]),
        "A UAT measurement exceeded its approved budget or is invalid.",
        4,
    )
    assertions(
        data["assertions"], {"relevant_suite", "independent_controls", "network_profiles"}, "UAT"
    )
    return defect_ids


def receipt_reconciliation(payload: Any, approved: dict[str, Any]) -> None:
    data = fields(
        payload,
        "assignment_sha256 sample_sha256 imports exceptions assertions",
        label="reconciliation result",
    )
    require(
        data["assignment_sha256"] == approved["assignment_export"]["sha256"],
        "Assignment export differs from approval.",
        3,
    )
    require(
        data["sample_sha256"]
        == {key: ref["sha256"] for key, ref in approved["accepted_samples"].items()},
        "Business samples differ from the approved artifact set.",
        3,
    )
    expected_sources = {
        source["artifact"]["sha256"]: source for source in approved["import_sources"]
    }
    seen = set()
    for value in items(data["imports"], "import reconciliation", minimum=0):
        row = fields(value, "source_sha256 rows control_totals", label="import reconciliation")
        source_hash = digest(row["source_sha256"], "import source")
        require(
            source_hash in expected_sources and source_hash not in seen,
            "Unexpected or repeated import source.",
        )
        seen.add(source_hash)
        source = expected_sources[source_hash]
        require(
            row["rows"] == source["rows"] and row["control_totals"] == source["control_totals"],
            "Import counts or approved control totals differ.",
            4,
        )
    require(seen == expected_sources.keys(), "An approved import source lacks reconciliation.", 3)
    kinds = {
        "supervisor_links",
        "reservations",
        "approvals",
        "payments",
        "offline",
        "media_quota",
        "retention",
    }
    populations = data["exceptions"]
    require(
        isinstance(populations, dict) and set(populations) == kinds,
        "Legacy exception inventory is incomplete.",
        3,
    )
    for population in populations.values():
        row = fields(population, "observed_ids resolved_ids", label="legacy exception inventory")
        require(
            strings(row["observed_ids"], "observed exception IDs", minimum=0)
            == strings(row["resolved_ids"], "resolved exception IDs", minimum=0),
            "Legacy exception inventory contains an unresolved case.",
            4,
        )
    assertions(
        data["assertions"],
        {"least_privilege", "launch_data", "legacy_owner_review"},
        "reconciliation",
    )


RUNTIME_FIELDS = "schema_heads image_digests frontend_sha256 service_worker_sha256"


def runtime_identity(value: dict[str, Any]) -> dict[str, Any]:
    heads = sorted(strings(value["schema_heads"], "migration heads"))
    require(all(re.fullmatch(r"[A-Za-z0-9_-]+", head) for head in heads), "Invalid migration head.")
    images = fields(value["image_digests"], "backend frontend", label="runtime image")
    require(
        all(
            isinstance(item, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", item)
            for item in images.values()
        ),
        "Invalid runtime image digest.",
    )
    return {
        "schema_heads": heads,
        "image_digests": images,
        "frontend_sha256": digest(value["frontend_sha256"], "frontend asset"),
        "service_worker_sha256": digest(value["service_worker_sha256"], "service worker"),
    }


def readback(payload: Any, identity: dict[str, Any]) -> None:
    data = fields(payload, RUNTIME_FIELDS + " readiness services", label="runtime readback")
    require(
        runtime_identity(data) == identity, "Runtime readback differs from the frozen build.", 3
    )
    ready = fields(data["readiness"], "status database", label="readiness result")
    require(ready == {"status": "ready", "database": "connected"}, "Readiness evidence failed.", 4)
    assertions(
        data["services"],
        {"backend", "frontend", "worker", "database", "storage"},
        "runtime service",
    )


def observation(payload: Any, start: datetime, end: datetime) -> None:
    data = fields(
        payload,
        "approved_window_seconds window_approval incidents scheduled_backup scheduled_monitoring",
        label="observation result",
    )
    limit = count(data["approved_window_seconds"], "approved observation window", minimum=1)
    require(
        (end - start).total_seconds() >= limit, "Approved observation window has not elapsed.", 3
    )
    for key in ("scheduled_backup", "scheduled_monitoring"):
        event = fields(data[key], "event_id at outcome", label="scheduled activity")
        meaningful(event["event_id"], "scheduled activity ID")
        require(
            start <= utc(event["at"], "scheduled activity time") <= end
            and event["outcome"] == "pass",
            "Mandatory scheduled activity failed or is outside the observation window.",
            4,
        )
    for event in items(data["incidents"], "observation incident record", minimum=0):
        row = fields(event, "id status resolution_ref", label="observed incident")
        meaningful(row["id"], "incident ID")
        require(row["status"] == "resolved", "Observation still has an open incident.", 4)


def handover(payload: Any, decisions: dict[str, Any], evidence: Evidence) -> None:
    data = fields(
        payload,
        "primary substitute access_verified custody_ref runbook_ref",
        label="handover result",
    )
    operations = decisions["D-30-OPERATIONS"]
    require(
        data["primary"] == operations["primary_responder"]
        and data["substitute"] == operations["substitute_responder"]
        and data["access_verified"] is True,
        "The named operators have not demonstrated handover access.",
        3,
    )
    evidence.load(data["custody_ref"])
    evidence.load(data["runbook_ref"])


def verify_recovery_artifacts(
    result: dict[str, Any],
    receipt: dict[str, Any],
    evidence: Evidence,
    identity: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    refs = {ref["sha256"]: ref for ref in receipt["artifacts"]}
    manifest_hash = result["manifest_sha256"]
    auth_hash = result["manifest_auth_sha256"]
    publication_hash = result["publication_sha256"]
    require(
        {manifest_hash, auth_hash, publication_hash} <= refs.keys(),
        "Backup manifest, authentication and publication must be verified artifacts.",
        3,
    )
    manifest = evidence.load(refs[manifest_hash], parse=True)
    require(isinstance(manifest, dict), "Invalid authenticated backup manifest.")
    require(
        type(manifest.get("format_version")) is int
        and manifest["format_version"] == 2
        and manifest.get("backup_set_id") == result["backup_set_id"]
        and manifest.get("source_sha") == receipt["source_sha"]
        and manifest.get("source_environment") == receipt["environment"]
        and manifest.get("configuration_sha256") == receipt["configuration_sha256"]
        and manifest.get("policy_sha256") == result["policy_sha256"]
        and manifest.get("policy_revision") == decision["revision"]
        and manifest.get("alembic_heads") == identity["schema_heads"]
        and isinstance(manifest.get("image_digests"), dict)
        and all(
            manifest["image_digests"].get(name) == image
            for name, image in identity["image_digests"].items()
        )
        and utc(manifest.get("snapshot_at_utc"), "backup snapshot")
        == utc(result["snapshot_at_utc"], "recovered snapshot"),
        "Backup manifest identity differs from the release or restored set.",
        3,
    )
    require(
        len(items(manifest.get("objects"), "backup object inventory", minimum=0))
        == result["required_object_count"]
        and isinstance(manifest.get("application_dump"), dict),
        "Backup manifest does not match recovered object or configuration coverage.",
        4,
    )
    config_paths = []
    for value in items(manifest.get("configuration_artifacts"), "backup configuration inventory"):
        entry = fields(value, "path plaintext encrypted", label="backup configuration artifact")
        path = meaningful(entry["path"], "backup configuration path")
        safe_parts(path)
        config_paths.append(path)
    require(
        set(decision["required_configuration_paths"]) <= set(config_paths)
        and len(set(config_paths)) == len(config_paths),
        "Backup manifest omits required configuration paths or repeats them.",
        4,
    )
    require(
        not result["required_category_counts"].get("grafana_database")
        or isinstance(manifest.get("grafana_dump"), dict),
        "Backup manifest lacks the approved Grafana database.",
        4,
    )
    auth = fields(
        evidence.load(refs[auth_hash], parse=True),
        "manifest_sha256 key_id algorithm signature",
        label="backup authentication record",
    )
    require(
        auth["manifest_sha256"] == manifest_hash and auth["algorithm"] == "HMAC-SHA256",
        "Backup authentication does not bind the restored manifest.",
        3,
    )
    meaningful(auth["key_id"], "backup authentication key ID")
    digest(auth["signature"], "backup authentication tag")
    publication = fields(
        evidence.load(refs[publication_hash], parse=True),
        "receipt key_id algorithm signature",
        label="signed backup publication record",
    )
    published = fields(
        publication["receipt"],
        "backup_set_id manifest_sha256 snapshot_at_utc remote_verified_at_utc source_sha "
        "source_environment policy_revision policy_sha256 configuration_sha256 "
        "destination_identity object_count outcome",
        label="backup publication result",
    )
    require(
        publication["key_id"] == auth["key_id"]
        and publication["algorithm"] == auth["algorithm"]
        and published["manifest_sha256"] == manifest_hash
        and published["outcome"] == "pass"
        and published["destination_identity"] == decision["destination_identity"]
        and count(published["object_count"], "published object count")
        == result["required_object_count"]
        and all(
            published[key] == manifest[key]
            for key in (
                "backup_set_id",
                "source_sha",
                "source_environment",
                "policy_revision",
                "policy_sha256",
                "configuration_sha256",
            )
        )
        and all(
            utc(published[key], "backup publication time") == utc(result[key], "recovery time")
            for key in ("snapshot_at_utc", "remote_verified_at_utc")
        ),
        "Signed publication does not match the independently restored set.",
        3,
    )
    digest(publication["signature"], "publication authentication tag")


class Validation:
    def __init__(
        self,
        root: Path,
        trust_registry: Path,
        *,
        phase: str,
        sha: str,
        target: str,
        token: str | None,
        protected: bool = False,
        expected_ci_run: int | None = None,
        expected_config: str | None = None,
        expected_runtime: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> None:
        self.evidence = Evidence(root, protected=protected)
        self.phase = exact(phase, {"predeploy", "final"}, "validation phase")
        self.sha = digest(sha, "candidate source", 40)
        self.target = exact(target, {"production", "staging", "test"}, "target environment")
        self.token = token
        self.expected_ci_run = expected_ci_run
        self.expected_config = expected_config
        self.expected_runtime = expected_runtime
        self.actor = actor
        self.now = datetime.now(UTC)
        self.approvals = Approvals(
            self.evidence, trust_registry, self.now, production=self.target == "production"
        )
        self.verifier_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.configuration = ""
        self.identity: dict[str, Any] = {}
        self.subject_hash = ""
        self.decision_hashes: dict[str, str] = {}
        self.decisions: dict[str, Any] = {}
        self.stage_config: str | None = None
        self.stage_profile: str | None = None
        self.stage_recovery: dict[str, Any] | None = None
        self.deploy_window: tuple[datetime, datetime] | None = None
        self.deployed_at: datetime | None = None
        self.observed_window: tuple[datetime, datetime] | None = None
        self.uat_defects: set[str] = set()
        self.receipts: dict[str, dict[str, Any]] = {}

    def validate_decisions(self, refs: Any, inventory: str) -> None:
        for ref in items(refs, "owner decisions"):
            raw = self.evidence.load(ref, parse=True)
            require(isinstance(raw, dict), "Invalid owner decision.")
            decision = exact(raw.get("decision_id"), set(DECISION_ROLES), "decision ID")
            require(decision not in self.decisions, "Duplicate owner decision.")
            row = fields(
                raw,
                "decision_id revision approval_ref approved_at " + DECISION_FIELDS[decision],
                label="owner decision",
            )
            meaningful(row["revision"], "decision revision")
            reviewed = {key: item for key, item in row.items() if key != "approval_ref"}
            approval = self.approvals.check(
                row["approval_ref"],
                decision,
                canonical_digest(reviewed),
                role=DECISION_ROLES[decision],
            )
            require(
                approval["approved_at"] == row["approved_at"], "Decision approval time differs.", 3
            )
            if decision == "D-27-SCOPE":
                decision_scope(row, inventory)
            if decision == "D-28-POLICY":
                meaningful(row["policy_id"], "retention policy ID")
                decision_retention(row, self.evidence)
            if decision == "D-29-RECOVERY":
                meaningful(row["policy_id"], "recovery policy ID")
                decision_recovery(row, self.target, self.evidence)
            if decision == "D-30-OPERATIONS":
                meaningful(row["profile_id"], "operations profile ID")
                decision_operations(row, self.target, self.evidence)
            if decision == "D-32-SUPPORT":
                decision_support(row)
            if decision == "D-33-BUSINESS":
                decision_business(row, self.evidence)
            self.decisions[decision] = row
            self.decision_hashes[decision] = ref["sha256"]
        require(
            set(self.decisions) == set(DECISION_ROLES), "Missing a mandatory owner decision.", 3
        )

    def validate_equivalence(self, ref: Any) -> str | None:
        if self.target != "production":
            require(ref is None, "Only production releases have staging equivalence.")
            return None
        value = fields(
            self.evidence.load(ref, parse=True),
            "production_configuration_sha256 staging_configuration_sha256 "
            "staging_operations_profile staging_recovery_policy differences review",
            label="staging equivalence",
        )
        require(
            value["production_configuration_sha256"] == self.configuration,
            "Staging equivalence targets a different configuration.",
            3,
        )
        self.stage_config = digest(value["staging_configuration_sha256"], "staging configuration")
        allowed = {
            "mail_transport",
            "mail_recipients",
            "database_endpoint",
            "object_storage_endpoint",
            "public_host",
            "credentials_scope",
            "test_fault_injection",
            "recovery_isolation",
        }
        seen = set()
        for difference in items(
            value["differences"], "reviewed environment differences", minimum=0
        ):
            row = fields(difference, "setting reason", label="configuration difference")
            setting = exact(row["setting"], allowed, "equivalent environment setting")
            require(setting not in seen, "Duplicate environment difference.")
            seen.add(setting)
            meaningful(row["reason"], "configuration equivalence reason")
        reviewed = {key: item for key, item in value.items() if key != "review"}
        self.approvals.check(
            value["review"],
            "staging_equivalence",
            canonical_digest(reviewed),
            role="operations_owner",
        )
        operations = self.decisions["D-30-OPERATIONS"]
        production = self.evidence.load(operations["profile_ref"], parse=True)
        profile_ref = value["staging_operations_profile"]
        stage = self.evidence.load(profile_ref, parse=True)
        require(
            isinstance(stage, dict)
            and stage.get("environment") == "staging"
            and all(
                stage.get(key) == production.get(key)
                for key in (
                    "probe_interval_seconds",
                    "timeout_seconds",
                    "failure_threshold",
                    "recovery_threshold",
                    "repeat_interval_seconds",
                    "acknowledgement_limit_seconds",
                    "heartbeat_window_seconds",
                    "primary_responder",
                    "substitute_responder",
                )
            ),
            "Staging monitoring changed approved operation or escalation thresholds.",
            3,
        )
        self.stage_profile = profile_ref["sha256"]
        recovery = self.decisions["D-29-RECOVERY"]
        stage_policy_ref = value["staging_recovery_policy"]
        stage_policy = self.evidence.load(stage_policy_ref, parse=True)
        require(isinstance(stage_policy, dict), "Invalid staging recovery policy.")
        self.stage_recovery = dict(recovery, policy_ref=stage_policy_ref)
        for key in ("destination_identity", "failure_domains"):
            if stage_policy.get(key) != recovery[key]:
                require("recovery_isolation" in seen, "Unreviewed staging recovery isolation.", 3)
                self.stage_recovery[key] = stage_policy.get(key)
        decision_recovery(self.stage_recovery, "staging", self.evidence)
        return ref["sha256"]

    def validate_subject(self, manifest: dict[str, Any]) -> None:
        scope = fields(
            manifest["scope"],
            "accepted_inventory control_registry excluded_requirement_ids delivery_scope",
            label="release scope",
        )
        require(
            scope["excluded_requirement_ids"] == ["G-01"]
            and scope["delivery_scope"] == "launch_readiness_only",
            "Release scope differs from the specification.",
            3,
        )
        inventory = self.evidence.load(scope["accepted_inventory"])
        registry = scope["control_registry"]
        require(
            self.evidence.load(registry, parse=True) == control_registry(),
            "Required control or platform registry changed.",
            3,
        )
        subject = fields(
            self.evidence.load(manifest["release_subject"], parse=True),
            "release_id repository source_sha environment configuration_sha256 inventory_sha256 "
            "control_registry_sha256 decision_sha256 support_matrix_sha256 "
            "staging_equivalence_sha256 " + RUNTIME_FIELDS,
            label="frozen release subject",
        )
        self.subject_hash = manifest["release_subject"]["sha256"]
        require(
            subject["release_id"] == manifest["release_id"]
            and subject["repository"] == REPOSITORY
            and subject["source_sha"] == self.sha
            and subject["environment"] == self.target
            and subject["inventory_sha256"] == inventory
            and subject["control_registry_sha256"] == registry["sha256"],
            "Frozen release subject does not match the requested scope or identity.",
            3,
        )
        self.configuration = digest(subject["configuration_sha256"], "release configuration")
        require(
            self.expected_config is None or self.configuration == self.expected_config,
            "Effective host configuration differs from the approved subject.",
            3,
        )
        self.identity = runtime_identity(subject)
        require(
            self.expected_runtime is None or self.identity == self.expected_runtime,
            "Built artifacts or schema differ from the approved subject.",
            3,
        )
        self.validate_decisions(manifest["decisions"], inventory)
        require(
            subject["decision_sha256"] == self.decision_hashes
            and subject["support_matrix_sha256"]
            == canonical_digest(self.decisions["D-32-SUPPORT"]["scenario_platform_map"]),
            "Approved decisions or support matrix differ from the release subject.",
            3,
        )
        profile = fields(
            manifest["validation_profile"],
            "validator_version validator_sha256 control_registry_sha256 staging_equivalence",
            label="validation profile",
        )
        require(
            type(profile["validator_version"]) is int
            and profile["validator_version"] == VERSION
            and profile["validator_sha256"] == self.verifier_hash
            and profile["control_registry_sha256"] == registry["sha256"],
            "Validation profile differs from the running validator or control registry.",
            3,
        )
        require(
            subject["staging_equivalence_sha256"]
            == self.validate_equivalence(profile["staging_equivalence"]),
            "Configuration equivalence differs from the release subject.",
            3,
        )

    def authorize_deployment(self, ref: Any) -> None:
        approval = self.approvals.check(
            ref, "deployment_authorization", self.subject_hash, role="release_authorizer"
        )
        require(
            approval.get("source_sha") == self.sha
            and approval.get("environment") == self.target
            and approval["approver_identity"]
            == self.decisions["D-33-BUSINESS"]["release_authorizer"]
            and approval["approver_identity"] != self.actor,
            "Deployment authorization does not match its source, environment or named authority.",
            3,
        )
        meaningful(approval.get("authorization_reference"), "user authorization reference")
        start = utc(approval.get("valid_from"), "authorization start")
        end = utc(approval.get("valid_until"), "authorization expiry")
        approved = utc(approval["approved_at"], "deployment approval")
        require(approved <= start < end, "Invalid deployment authorization window.", 3)
        if self.phase == "predeploy":
            require(start <= self.now < end, "Deployment authorization is not currently valid.", 3)
        self.deploy_window = (start, end)

    def validate_receipt(self, ref: Any) -> None:
        raw = fields(
            self.evidence.load(ref, parse=True),
            "receipt_id kind phase source_sha environment configuration_sha256 synthetic "
            "started_at completed_at executed_by tool outcome results artifacts review",
            label="release receipt",
        )
        name = meaningful(raw["receipt_id"], "receipt ID")
        require(name not in self.receipts, "Duplicate receipt ID.")
        phase = exact(raw["phase"], {"predeploy", "final"}, "receipt phase")
        kinds = PREDEPLOY_KINDS if phase == "predeploy" else FINAL_KINDS | LIVE_KINDS | {"uat"}
        kind = exact(raw["kind"], kinds, "receipt kind")
        require(
            not any(
                row["kind"] == kind and row["phase"] == phase for row in self.receipts.values()
            ),
            "Duplicate receipt kind in this phase.",
        )
        require(
            self.phase == "final" or phase == "predeploy",
            "A predeploy verdict may not use final receipts.",
        )
        environment = (
            "staging"
            if (
                self.target == "production"
                and phase == "predeploy"
                and kind not in {"ci", "data_reconciliation"}
            )
            else self.target
        )
        configuration = self.stage_config if environment != self.target else self.configuration
        assert configuration is not None
        require(
            raw["source_sha"] == self.sha
            and raw["environment"] == environment
            and raw["configuration_sha256"] == configuration
            and raw["synthetic"] is (self.target == "test"),
            "Receipt source, environment, configuration or provenance differs from this release.",
            3,
        )
        require(raw["outcome"] == "pass", "A required receipt did not pass.", 4)
        start, end = check_execution(raw["started_at"], raw["completed_at"], self.now, "receipt")
        executor = meaningful(raw["executed_by"], "receipt executor")
        meaningful(raw["tool"], "execution tool")
        artifact_hashes = self.evidence.artifacts(raw["artifacts"], "receipt artifacts")
        review = self.approvals.check(
            raw["review"],
            "review_receipt",
            canonical_digest({key: value for key, value in raw.items() if key != "review"}),
            role="release_reviewer",
        )
        require(
            review["approver_identity"] != executor
            and utc(review["approved_at"], "review time") >= end,
            "The receipt requires an independent review after execution.",
            3,
        )
        result = raw["results"]
        if kind == "ci":
            receipt_ci(result, self.evidence, self.sha, self.token, self.expected_ci_run)
        elif kind == "retention":
            receipt_retention(
                result,
                self.decisions["D-28-POLICY"],
                self.decisions["D-28-POLICY"]["policy_ref"]["sha256"],
            )
        elif kind == "recovery":
            recovery = (
                self.stage_recovery
                if environment != self.target
                else self.decisions["D-29-RECOVERY"]
            )
            assert recovery is not None
            receipt_recovery(
                result,
                recovery,
                self.identity["schema_heads"],
                executor,
                start,
                end,
            )
            verify_recovery_artifacts(result, raw, self.evidence, self.identity, recovery)
        elif kind == "observability":
            operations = self.decisions["D-30-OPERATIONS"]
            profile = (
                operations["profile_ref"]["sha256"]
                if environment == self.target
                else self.stage_profile
            )
            assert profile is not None
            receipt_observability(
                result, profile, operations, self.approvals, environment, start, end
            )
        elif kind == "uat":
            self.uat_defects.update(
                receipt_uat(
                    result,
                    self.decisions["D-32-SUPPORT"],
                    self.evidence,
                    self.approvals,
                    self.sha,
                    environment,
                    configuration,
                    artifact_hashes,
                    phase,
                    start,
                    end,
                )
            )
        elif kind == "data_reconciliation":
            receipt_reconciliation(result, self.decisions["D-33-BUSINESS"])
        elif kind == "deployment":
            deployed = fields(
                result, "run_id run_url ci_run_id deployed_at readback", label="deployment result"
            )
            run_id = count(deployed["run_id"], "deployment run ID", minimum=1)
            require(deployed["run_url"] == run_url(run_id), "Invalid deployment run URL.")
            checked_run(run_id, self.sha, self.token, ci=False)
            self.deployed_at = utc(deployed["deployed_at"], "deployment activation")
            assert self.deploy_window is not None
            require(
                start <= self.deployed_at <= end
                and self.deploy_window[0] <= self.deployed_at < self.deploy_window[1],
                "Deployment occurred outside its approval or recorded execution window.",
                3,
            )
            readback(deployed["readback"], self.identity)
        elif kind == "runtime_readback":
            readback(result, self.identity)
        elif kind == "observation":
            observation(result, start, end)
            window = self.approvals.check(
                result["window_approval"],
                "approve_observation_window",
                canonical_digest(
                    {
                        "release_subject_sha256": self.subject_hash,
                        "approved_window_seconds": result["approved_window_seconds"],
                    }
                ),
                role="operations_owner",
            )
            require(
                window["approver_identity"]
                == self.decisions["D-33-BUSINESS"]["signatories"]["operations_owner"]
                and utc(window["approved_at"], "observation window approval") <= start,
                "The named operations owner must approve the observation window before execution.",
                3,
            )
            self.observed_window = (start, end)
            for incident in result["incidents"]:
                self.evidence.load(incident["resolution_ref"])
        elif kind == "handover":
            handover(result, self.decisions, self.evidence)
        self.receipts[name] = raw

    def validate_receipts(self, refs: Any) -> dict[str, dict[str, Any]]:
        artifact_refs = {}
        for ref in items(refs, "release receipts"):
            self.validate_receipt(ref)
            name = next(reversed(self.receipts))
            artifact_refs[name] = ref
        observed = {(row["phase"], row["kind"]) for row in self.receipts.values()}
        expected = {("predeploy", kind) for kind in PREDEPLOY_KINDS}
        if self.phase == "final":
            expected |= {("final", kind) for kind in FINAL_KINDS | LIVE_KINDS | {"uat"}}
        require(expected == observed, "A phase-required receipt is missing.", 3)
        if self.phase == "final":
            ci = next(row["results"] for row in self.receipts.values() if row["kind"] == "ci")
            deployment = next(
                row["results"] for row in self.receipts.values() if row["kind"] == "deployment"
            )
            require(
                deployment["ci_run_id"] == ci["run_id"],
                "Deployment did not use the accepted CI run.",
                3,
            )
            if self.deployed_at is None or self.observed_window is None:
                raise ContractError(3, "Final deployment or observation is missing.")
            require(
                self.observed_window[0] >= self.deployed_at,
                "Final observation predates the deployment.",
                3,
            )
            for row in self.receipts.values():
                if row["phase"] == "final" and row["kind"] != "deployment":
                    require(
                        utc(row["started_at"], "live receipt start") >= self.deployed_at,
                        "Final evidence predates deployment.",
                        3,
                    )
        return artifact_refs

    def validate_defects(self, ref: Any) -> None:
        defect_ids = set()
        for value in items(self.evidence.load(ref, parse=True), "defect ledger", minimum=0):
            row = fields(
                value,
                "defect_id workstream_id disposition reproduction_ref retest_ref",
                label="defect",
            )
            name = meaningful(row["defect_id"], "defect ID")
            require(name not in defect_ids, "Duplicate defect ID.")
            defect_ids.add(name)
            exact(row["workstream_id"], WORKSTREAMS, "defect workstream")
            self.evidence.load(row["reproduction_ref"])
            require(row["disposition"] == "resolved", "An in-scope defect remains unresolved.", 4)
            retest = fields(
                self.evidence.load(row["retest_ref"], parse=True),
                "defect_id source_sha configuration_sha256 outcome artifact",
                label="defect retest",
            )
            require(
                retest["defect_id"] == name
                and retest["source_sha"] == self.sha
                and retest["configuration_sha256"] in {self.configuration, self.stage_config}
                and retest["outcome"] == "pass",
                "Defect retest failed or is stale.",
                4,
            )
            self.evidence.load(retest["artifact"])
        require(
            self.uat_defects <= defect_ids, "UAT defects are missing from the closure ledger.", 3
        )

    def validate_ledger(self, ref: Any) -> None:
        workstreams = set()
        for value in items(self.evidence.load(ref, parse=True), "workstream ledger"):
            row = fields(value, "workstream_id status controls", label="workstream")
            workstream = exact(row["workstream_id"], WORKSTREAMS, "workstream ID")
            require(workstream not in workstreams, "Duplicate workstream ID.")
            workstreams.add(workstream)
            required = controls_for(workstream)
            covered = set()
            complete = True
            for control in items(row["controls"], "workstream controls"):
                entry = fields(control, "control_id status receipt_ids", label="acceptance control")
                name = exact(entry["control_id"], required, "control ID")
                require(name not in covered, "Duplicate acceptance control.")
                covered.add(name)
                pending = self.phase == "predeploy" and name in CONTROL_FINAL_ONLY
                if pending:
                    require(
                        entry["status"] == "pending_live" and entry["receipt_ids"] == [],
                        "Predeploy cannot claim a control requiring the live release.",
                        3,
                    )
                    complete = False
                    continue
                require(
                    entry["status"] == "accepted", f"Acceptance control {name} is unresolved.", 4
                )
                references = strings(entry["receipt_ids"], "control receipt IDs")
                require(
                    references <= self.receipts.keys(),
                    "Control refers to an unverified receipt.",
                    3,
                )
                kinds = {
                    self.receipts[item]["kind"]
                    for item in references
                    if name not in CONTROL_FINAL_ONLY or self.receipts[item]["phase"] == "final"
                }
                require(
                    required_receipt_kinds(name) <= kinds,
                    "An acceptance control lacks relevant phase-specific receipts.",
                    3,
                )
            require(covered == required, "Workstream control inventory is incomplete.", 3)
            require(
                row["status"] == ("accepted" if complete else "pending_live"),
                "Workstream status differs from its controls.",
                3,
            )
        require(workstreams == WORKSTREAMS, "Release ledger must contain all 32 workstreams.", 3)

    def validate_final(
        self, manifest: dict[str, Any], receipt_refs: dict[str, Any], approvals: dict[str, Any]
    ) -> None:
        ref = manifest.get("acceptance_bundle")
        if not isinstance(ref, dict):
            raise ContractError(3, "Final evidence requires an acceptance bundle.")
        bundle = fields(
            self.evidence.load(ref, parse=True),
            "release_subject_sha256 receipt_sha256 ledger_sha256 defects_sha256",
            label="acceptance bundle",
        )
        require(
            bundle["release_subject_sha256"] == self.subject_hash
            and bundle["receipt_sha256"]
            == {name: item["sha256"] for name, item in receipt_refs.items()}
            and bundle["ledger_sha256"] == manifest["ledger"]["sha256"]
            and bundle["defects_sha256"] == manifest["defects"]["sha256"],
            "Acceptance bundle does not bind the verified release artifacts.",
            3,
        )
        roles = set()
        assert self.observed_window is not None
        for approval_ref in items(approvals.get("final_acceptance"), "final sign-offs"):
            approval = self.approvals.check(approval_ref, "final_acceptance", ref["sha256"])
            role = exact(approval["authority_role"], FINAL_ROLES, "final authority role")
            require(
                role not in roles
                and approval["approver_identity"]
                == self.decisions["D-33-BUSINESS"]["signatories"][role]
                and approval["approver_identity"] != self.actor
                and utc(approval["approved_at"], "final approval") >= self.observed_window[1],
                "A final approval is duplicated, unauthorized, or predates observation.",
                3,
            )
            roles.add(role)
        require(
            roles == FINAL_ROLES,
            "Final business, finance/data, QA and operations sign-offs are required.",
            3,
        )

    def run(self, path: Path) -> dict[str, Any]:
        path = path.absolute()
        require(
            path.is_relative_to(self.evidence.root), "Manifest must be inside the evidence root."
        )
        safe_parts(path.relative_to(self.evidence.root).as_posix())
        value, manifest_hash = json_file(path, protected=self.evidence.protected)
        manifest = fields(
            value,
            "format_version release_id repository source_sha target_environment "
            "release_subject scope "
            "decisions ledger receipts approvals defects validation_profile",
            optional="acceptance_bundle",
            label="release manifest",
        )
        require(
            type(manifest["format_version"]) is int and manifest["format_version"] == VERSION,
            "Unsupported release contract format.",
        )
        meaningful(manifest["release_id"], "release ID")
        require(
            manifest["repository"] == REPOSITORY
            and manifest["source_sha"] == self.sha
            and manifest["target_environment"] == self.target,
            "Manifest repository, source or target environment differs from the requested release.",
            3,
        )
        self.validate_subject(manifest)
        approvals = fields(
            manifest["approvals"],
            "deployment_authorization",
            optional="final_acceptance operations",
            label="release approvals",
        )
        self.authorize_deployment(approvals["deployment_authorization"])
        receipt_refs = self.validate_receipts(manifest["receipts"])
        self.validate_defects(manifest["defects"])
        self.validate_ledger(manifest["ledger"])
        if self.phase == "final":
            self.validate_final(manifest, receipt_refs, approvals)
        else:
            require(
                "acceptance_bundle" not in manifest and "final_acceptance" not in approvals,
                "A predeploy manifest may not claim final acceptance.",
            )
        if "operations" in approvals:
            for ref in items(approvals["operations"], "operation approvals", minimum=0):
                operation = self.evidence.load(ref, parse=True)
                require(isinstance(operation, dict), "Invalid operation authorization.")
                purpose = exact(
                    operation.get("purpose"),
                    {"data_repair", "legacy_disposal", "purge"},
                    "operation purpose",
                )
                self.approvals.check(
                    ref, purpose, digest(operation.get("subject_sha256"), "operation subject")
                )
        accepted = self.phase == "final" and self.target == "production"
        ready = self.phase == "predeploy" and self.target != "test"
        return {
            "generated_at": self.now.isoformat(),
            "phase": self.phase,
            "status": (
                "accepted_scope_complete"
                if accepted
                else "ready_for_authorized_deployment"
                if ready
                else "validated_staging_evidence"
                if self.target == "staging"
                else "validated_test_evidence"
            ),
            "accepted_scope_complete": accepted,
            "ready_for_authorized_deployment": ready,
            "source_sha": self.sha,
            "target_environment": self.target,
            "release_id": manifest["release_id"],
            "manifest_sha256": manifest_hash,
            "subject_sha256": self.subject_hash,
            "configuration_sha256": self.configuration,
            "runtime_identity": self.identity,
            "validator_version": VERSION,
            "validator_sha256": self.verifier_hash,
            "control_registry_sha256": manifest["validation_profile"]["control_registry_sha256"],
            "trust_registry_sha256": self.approvals.digest,
            "verified_receipt_ids": sorted(self.receipts),
            "blockers": [],
        }


def host_configuration(state: Path) -> str:
    value, _ = json_file(state / "authorized-configuration.json", protected=True)
    profile = fields(
        value, "configuration_sha256 protected_files", label="approved host configuration"
    )
    checksums = profile["protected_files"]
    require(
        isinstance(checksums, dict) and {"production.env", "compose.vps.yml"} <= checksums.keys(),
        "Approved host configuration omits deployment inputs.",
        3,
    )
    for name, expected_hash in checksums.items():
        expected = digest(expected_hash, "protected host file")
        with open_evidence(state.joinpath(*safe_parts(name)), protected=True) as file:
            require(
                hashlib.file_digest(file, "sha256").hexdigest() == expected,
                "A protected deployment setting differs from the approved host configuration.",
                3,
            )
    return digest(profile["configuration_sha256"], "approved host configuration")


def host_main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-state", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--ci-run", type=int, required=True)
    parser.add_argument("--deploy-run", type=int, required=True)
    parser.add_argument("--schema-head", action="append")
    parser.add_argument("--backend-image")
    parser.add_argument("--frontend-image")
    parser.add_argument("--frontend-sha256")
    parser.add_argument("--service-worker-sha256")
    args = parser.parse_args()
    try:
        require(
            os.geteuid() == 0 and args.host_state.is_absolute(),
            "Host validation requires the trusted operator context.",
        )
        source = digest(args.commit, "candidate source", 40)
        observed = (
            args.schema_head,
            args.backend_image,
            args.frontend_image,
            args.frontend_sha256,
            args.service_worker_sha256,
        )
        require(not any(observed) or all(observed), "Complete runtime identities are required.")
        runtime = (
            runtime_identity(
                {
                    "schema_heads": args.schema_head,
                    "image_digests": {
                        "backend": args.backend_image,
                        "frontend": args.frontend_image,
                    },
                    "frontend_sha256": args.frontend_sha256,
                    "service_worker_sha256": args.service_worker_sha256,
                }
            )
            if all(observed)
            else None
        )
        token = sys.stdin.readline(4096).strip()
        state = args.host_state
        root = state / "authorizations" / source
        verifier = Validation(
            root,
            state / "approval-trust.json",
            phase="predeploy",
            sha=source,
            target="production",
            token=token,
            protected=True,
            expected_ci_run=args.ci_run,
            expected_config=host_configuration(state),
            expected_runtime=runtime,
            actor=deployment_operator(args.deploy_run, source, token),
        )
        verdict = verifier.run(root / "release_manifest.json")
        print(json.dumps(verdict, sort_keys=True))
    except ContractError as error:
        print(f"Release authorization blocked. {error}", file=sys.stderr)
        raise SystemExit(error.code) from None
    except (TypeError, ValueError, KeyError, OSError):
        print("Release authorization blocked. Invalid evidence input.", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    host_main()
