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
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile
from zlib import error as CompressionError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REPOSITORY = "nirzaf/garrison-investments"
VERSION = 1
WORKSTREAMS = {f"G-{number:02}" for number in range(2, 34)}
CONTROL_COUNTS = {27: 4, 28: 11, 29: 13, 30: 11, 32: 10, 33: 12}
RELEASE_CONFIGURATION_FILES = {
    "docker-compose.prod.yml",
    "nginx/nginx.prod.conf",
    "nginx/grafana.prod.conf.template",
    "observability/postgres/init-grafana-db.sh",
    "observability/minio/loki-policy.json",
    "observability/loki-config.yml",
    "observability/alloy-config.alloy",
    "observability/grafana/contact-points/usesend.yml",
    "observability/grafana/dashboards/incidents.json",
    "observability/grafana/dashboards/operations.json",
    "observability/grafana/provisioning/alerting/alerts.yml",
    "observability/grafana/provisioning/alerting/contact-point.yml",
    "observability/grafana/provisioning/dashboards/dashboards.yml",
    "observability/grafana/provisioning/datasources/loki.yml",
}
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
CI_TEST_JOBS = {
    "backend": {"Backend tests (1/2)", "Backend tests (2/2)"},
    "frontend": {"Frontend lint, types, tests and build"},
    "browser": {"Browser regressions (1/2)", "Browser regressions (2/2)"},
}
CI_JOBS = {
    "Backend lint and types",
    "Compose files are valid",
} | set().union(*CI_TEST_JOBS.values())
ROLE_IDS = {
    "managing_director",
    "operations_director",
    "group_project_manager",
    "mep_project_manager",
    "quantity_surveyor",
    "senior_site_supervisor",
    "site_supervisor",
    "hr_manager",
    "hr_executive_reader",
    "administrative_executive",
}
PROJECT_MANAGING_ROLES = {
    "managing_director",
    "operations_director",
    "group_project_manager",
    "mep_project_manager",
}
REPORT_APPROVER_ROLES = PROJECT_MANAGING_ROLES | {"hr_manager"}
SITE_REPORT_ROLES = {"senior_site_supervisor", "site_supervisor"}
UAT_REQUIRED_ROLES = {
    "UAT-02": (
        {"managing_director"},
        {"mep_project_manager", "quantity_surveyor", "site_supervisor"},
    ),
    "UAT-03": ({"managing_director", "operations_director"},),
    "UAT-04": (PROJECT_MANAGING_ROLES,),
    "UAT-05": (PROJECT_MANAGING_ROLES,),
    "UAT-06": (PROJECT_MANAGING_ROLES,),
    "UAT-07": ({"senior_site_supervisor", "site_supervisor"},),
    "UAT-08": ({"quantity_surveyor"}, REPORT_APPROVER_ROLES),
    "UAT-09": (REPORT_APPROVER_ROLES,),
    "UAT-10": ({"managing_director", "operations_director"},),
    "UAT-12": ({"managing_director", "operations_director"},),
    "UAT-13": ({"managing_director", "operations_director"},),
    "UAT-15": ({"managing_director", "operations_director"},),
    "UAT-16": ({"operations_director"},),
    "UAT-20": ({"managing_director"},),
    "UAT-21": (SITE_REPORT_ROLES,),
    "UAT-22": (SITE_REPORT_ROLES,),
    "UAT-23": ({"quantity_surveyor"},),
    "UAT-24": ({"mep_project_manager"},),
    "UAT-27": ({"quantity_surveyor"},),
    "UAT-28": ({"site_supervisor"},),
    "UAT-33": ({"managing_director"},),
}
DESKTOP_BROWSERS = {"Chrome"}
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
        "uat_role_groups": {
            scenario: [sorted(roles) for roles in groups]
            for scenario, groups in UAT_REQUIRED_ROLES.items()
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
        return self._load(ref, strict_json if parse else None)

    def load_junit(self, ref: Any) -> dict[str, int]:
        return self._load(ref, junit_counts)

    def load_deployment_receipt(self, ref: Any) -> dict[str, str]:
        return self._load(ref, deployment_receipt_fields)

    def junit_archive_member(self, ref: Any, name: str) -> str:
        def decode(raw: bytes) -> str:
            limit = 4 * 1024 * 1024
            try:
                with ZipFile(BytesIO(raw)) as archive:
                    members = archive.infolist()
                    require(
                        len(members) == 1
                        and members[0].filename == name
                        and 0 < members[0].file_size <= limit
                        and members[0].compress_type in {ZIP_STORED, ZIP_DEFLATED},
                        "Unexpected member in the published GitHub archive.",
                        3,
                    )
                    with archive.open(members[0]) as report:
                        body = report.read(limit + 1)
                    require(
                        len(body) == members[0].file_size,
                        "Unexpected report size in the published GitHub archive.",
                        3,
                    )
            except (BadZipFile, CompressionError, OSError, EOFError, RuntimeError):
                raise ContractError(3, "Invalid published GitHub archive.") from None
            return hashlib.sha256(body).hexdigest()

        return self._load(ref, decode)

    def _load(self, ref: Any, decoder: Callable[[bytes], Any] | None) -> Any:
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
            if decoder:
                require(expected_size <= 4 * 1024 * 1024, "Parsed evidence exceeds the size limit.")
                raw = file.read(expected_size + 1)
                observed = hashlib.sha256(raw).hexdigest()
            else:
                raw = b""
                observed = hashlib.file_digest(file, "sha256").hexdigest()
        require(
            observed == expected_hash, "Evidence artifact digest differs from its reference.", 3
        )
        return decoder(raw) if decoder else expected_hash

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
    run_id: int,
    sha: str,
    token: str | None,
    *,
    ci: bool,
    active: bool = False,
    attempt: int | None = None,
) -> dict[str, Any]:
    path = f"actions/runs/{run_id}"
    if attempt is not None:
        count(attempt, "workflow run attempt", minimum=1)
        path += f"/attempts/{attempt}"
    run = github_record(path, token)
    repository = run.get("head_repository") or {}
    require(
        run.get("id") == run_id
        and (attempt is None or run.get("run_attempt") == attempt)
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


def deployment_operator(
    run_id: int, sha: str, token: str | None, *, attempt: int | None = None
) -> str:
    run = checked_run(run_id, sha, token, ci=False, active=True, attempt=attempt)
    return workflow_operator(run)


def workflow_operator(run: dict[str, Any]) -> str:
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


MONITOR_TRANSPORT_FIELDS = "mode sender endpoint"
MONITOR_RECIPIENT_FIELDS = "recipients escalation_recipients"


def monitor_contact_route(profile: dict[str, Any]) -> tuple[dict[str, str], dict[str, set[str]]]:
    route = fields(
        profile.get("transport"),
        MONITOR_TRANSPORT_FIELDS + " " + MONITOR_RECIPIENT_FIELDS,
        label="monitor contact route",
    )
    transport = {key: meaningful(route[key], key) for key in MONITOR_TRANSPORT_FIELDS.split()}
    exact(transport["mode"], {"smtp_tls", "smtp_starttls", "usesend"}, "monitor transport mode")
    recipients = {
        key: strings(route[key], f"monitor {key}") for key in MONITOR_RECIPIENT_FIELDS.split()
    }
    return transport, recipients


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
    evidence.load(record["maintenance_rules_ref"])
    approved_transport = fields(
        evidence.load(record["transport_ref"], parse=True),
        MONITOR_TRANSPORT_FIELDS,
        label="approved monitor transport",
    )
    approved_recipients = fields(
        evidence.load(record["recipient_ref"], parse=True),
        MONITOR_RECIPIENT_FIELDS,
        label="approved monitor recipients",
    )
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
    transport, recipients = monitor_contact_route(profile)
    require(
        transport == approved_transport
        and all(
            addresses == strings(approved_recipients[key], key)
            for key, addresses in recipients.items()
        ),
        "Installed monitor profile differs from the approved contact route.",
        3,
    )
    monitor_check_ids(profile)


def monitor_check_ids(profile: dict[str, Any]) -> tuple[set[str], str]:
    backup = profile.get("backup")
    if not isinstance(backup, dict):
        raise ContractError(3, "The approved monitor requires a backup freshness check.")
    backup_id = meaningful(backup.get("check_id"), "backup freshness check ID")
    targets = items(profile.get("targets"), "installed monitor targets")
    require(all(isinstance(row, dict) for row in targets), "Invalid monitor targets.")
    checks = {meaningful(row.get("check_id"), "monitor check ID") for row in targets}
    checks.add(backup_id)
    require(len(checks) == len(targets) + 1, "Monitor check IDs must be distinct.")
    return checks, backup_id


def device_key(target: Any) -> tuple[str, str, str, str, str]:
    row = fields(
        target, "platform device_model os_version browser browser_version", label="supported device"
    )
    return (
        exact(row["platform"], {"desktop"}, "device platform"),
        meaningful(row["device_model"], "device model"),
        meaningful(row["os_version"], "OS version"),
        exact(row["browser"], DESKTOP_BROWSERS, "desktop browser"),
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
                    set(expected[scenario]),
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
        for platform in set(expected[scenario]) - {"operations"}:
            roles = {role for observed_platform, role in pairs if observed_platform == platform}
            require(
                all(roles & group for group in UAT_REQUIRED_ROLES.get(scenario, ())),
                f"Mandatory UAT role omitted for {scenario} on {platform}.",
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
    require(
        {device[3] for device in desktop} == DESKTOP_BROWSERS,
        "Approved desktop targets must include Chrome.",
        3,
    )
    require(
        record["physical_mobile_targets"] == [],
        "Physical mobile targets are outside the approved acceptance scope.",
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


def junit_counts(raw: bytes) -> dict[str, int]:
    """Count individual test results in the JUnit formats emitted by the CI runners."""
    try:
        report = raw.decode("utf-8-sig")
        require(
            not re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", report, re.IGNORECASE),
            "JUnit XML may not contain DTDs or entity declarations.",
            3,
        )
        root = ElementTree.fromstring(report)
    except (UnicodeDecodeError, ElementTree.ParseError):
        raise ContractError(3, "Invalid JUnit XML test report.") from None

    require(root.tag in {"testsuite", "testsuites"}, "Invalid JUnit XML report root.", 3)
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    totals = dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
    outcomes = {"failure": "failures", "error": "errors", "skipped": "skipped"}
    for suite in suites:
        counts = dict.fromkeys(totals, 0)
        for case in suite.findall("testcase"):
            require(bool(case.get("name")), "JUnit test case is missing its name.", 3)
            results = [outcomes[child.tag] for child in case if child.tag in outcomes]
            require(len(results) <= 1, "JUnit test case has conflicting outcomes.", 3)
            counts["tests"] += 1
            if results:
                counts[results[0]] += 1
        for name, value in counts.items():
            require(suite.get(name, str(value)) == str(value), "JUnit suite totals differ.", 3)
            totals[name] += value

    require(
        totals["tests"] > 0 and totals["tests"] == sum(1 for _ in root.iter("testcase")),
        "JUnit report must contain individual test cases in its suites.",
        3,
    )
    for name, value in totals.items():
        require(root.get(name, str(value)) == str(value), "JUnit report totals differ.", 3)
    failed = totals["failures"] + totals["errors"]
    skipped = totals["skipped"]
    return {"passed": totals["tests"] - failed - skipped, "failed": failed, "skipped": skipped}


def receipt_ci(
    payload: Any,
    evidence: Evidence,
    sha: str,
    token: str | None,
    required_run: int | None,
    *,
    artifact_hashes: set[str] | None = None,
) -> None:
    data = fields(
        payload,
        "run_id run_url run_attempt repository ref conclusion jobs suites checks",
        label="CI result",
    )
    run_id = count(data["run_id"], "CI run ID", minimum=1)
    attempt = count(data["run_attempt"], "CI run attempt", minimum=1)
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
    checked_run(run_id, sha, token, ci=True, attempt=attempt)
    live = github_record(f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100", token)
    live_jobs = live.get("jobs")
    if not isinstance(live_jobs, list) or live.get("total_count") != len(live_jobs):
        raise ContractError(5, "Incomplete GitHub job verification.")
    observed = {
        row["id"]: row["name"]
        for row in live_jobs
        if row.get("run_id") == run_id
        and row.get("run_attempt") == attempt
        and row.get("head_sha") == sha
        and row.get("status") == "completed"
        and row.get("conclusion") == "success"
    }
    require(
        all(observed.get(key) == name for key, name in jobs.items()),
        "GitHub jobs differ from the CI evidence.",
        3,
    )

    suites = set()
    report_paths: set[str] = set()
    report_hashes: set[str] = set()
    reports_to_verify = []
    for value in items(data["suites"], "test suites"):
        suite = fields(value, "name passed failed skipped warnings reports", label="test suite")
        name = exact(suite["name"], set(CI_TEST_JOBS), "test suite name")
        require(name not in suites, "Duplicate CI test suite.")
        suites.add(name)
        # Runner warnings are reviewed separately because JUnit does not report them consistently.
        count(suite["warnings"], f"{name} warnings")
        counts = {
            key: count(suite[key], f"{name} {key}", minimum=int(key == "passed"))
            for key in ("passed", "failed", "skipped")
        }
        require(
            counts["failed"] == counts["skipped"] == 0,
            "A CI suite has failures or unexplained skips.",
            4,
        )
        test_jobs = CI_TEST_JOBS[name]
        expected_jobs = {job_id for job_id, job_name in jobs.items() if job_name in test_jobs}
        report_jobs: set[int] = set()
        reported = dict.fromkeys(counts, 0)
        for value in items(suite["reports"], "JUnit job reports"):
            row = fields(value, "job_id report archive", label="JUnit job report")
            job_id = count(row["job_id"], "JUnit report job ID", minimum=1)
            require(
                job_id in expected_jobs and job_id not in report_jobs,
                "JUnit report job is unexpected or duplicated.",
                3,
            )
            report_jobs.add(job_id)
            ref = fields(
                row["report"],
                "path sha256 size_bytes",
                optional="sensitivity",
                label="JUnit report",
            )
            path = "/".join(safe_parts(ref["path"]))
            sha256 = digest(ref["sha256"], "JUnit report")
            require(
                path not in report_paths and sha256 not in report_hashes,
                "JUnit report is reused across CI jobs.",
                3,
            )
            require(
                artifact_hashes is None or sha256 in artifact_hashes,
                "JUnit report is missing from the classified receipt artifacts.",
                3,
            )
            report_paths.add(path)
            report_hashes.add(sha256)
            for key, result in evidence.load_junit(ref).items():
                reported[key] += result
            shard = re.search(r"\(([12])/2\)$", jobs[job_id])
            suffix = f"-{shard[1]}" if shard else ""
            reports_to_verify.append(
                (
                    f"ci-{attempt}-{name}{suffix}",
                    "frontend.xml" if name == "frontend" else "test-report.xml",
                    row["archive"],
                    sha256,
                )
            )
        require(report_jobs == expected_jobs, "A required CI job is missing its JUnit report.", 3)
        require(reported == counts, "JUnit test report counts differ from the receipt.", 3)
    require(suites == set(CI_TEST_JOBS), "Missing a mandatory test suite.", 3)
    catalog = github_record(f"actions/runs/{run_id}/artifacts?per_page=100", token)
    artifacts = catalog.get("artifacts")
    if not isinstance(artifacts, list) or catalog.get("total_count") != len(artifacts):
        raise ContractError(5, "Incomplete GitHub CI artifact verification.")
    for name, member, archive_ref, report_hash in reports_to_verify:
        matches = [item for item in artifacts if item.get("name") == name]
        require(len(matches) == 1, "Missing or ambiguous published GitHub archive.", 3)
        published = matches[0]
        archive = fields(
            archive_ref, "path sha256 size_bytes", optional="sensitivity", label="CI archive"
        )
        published_run = published.get("workflow_run") or {}
        require(
            published.get("digest") == f"sha256:{archive['sha256']}"
            and published.get("size_in_bytes") == archive["size_bytes"]
            and published_run.get("id") == run_id
            and published_run.get("head_sha") == sha
            and published_run.get("head_branch") == "main",
            "CI archive does not match the published GitHub archive.",
            3,
        )
        require(
            artifact_hashes is None or archive["sha256"] in artifact_hashes,
            "CI archive is missing from the classified receipt artifacts.",
            3,
        )
        require(
            evidence.junit_archive_member(archive, member) == report_hash,
            "JUnit report does not match the published GitHub archive.",
            3,
        )
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
        optional="restore_receipt",
        label="recovery result",
    )
    require("restore_receipt" in data, "Missing restore command receipt.", 3)
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


def alert_delivery(
    ref: Any,
    evidence: Evidence,
    artifact_hashes: set[str],
    row: dict[str, Any],
    profile_hash: str,
    notification: str,
    sent_at: datetime,
    end: datetime,
) -> tuple[str, str, datetime, str]:
    record = fields(
        evidence.load(ref, parse=True),
        "rule_id environment profile_sha256 notification message_id recipient destination "
        "received_at receipt_ref",
        label="alert delivery",
    )
    raw_ref = record["receipt_ref"]
    require(
        ref["sha256"] in artifact_hashes and evidence.load(raw_ref) in artifact_hashes,
        "Alert delivery records and notification receipts must be classified artifacts.",
        3,
    )
    require(
        record["rule_id"] == row["rule_id"]
        and record["environment"] == row["environment"]
        and record["profile_sha256"] == profile_hash
        and record["notification"] == notification
        and record["recipient"] == row["recipient"],
        "Alert delivery differs from the reviewed rule, route or recipient.",
        3,
    )
    received = utc(record["received_at"], "alert receipt")
    require(sent_at <= received <= end, "Alert delivery is outside its execution window.", 3)
    return (
        meaningful(record["message_id"], "notification message ID"),
        meaningful(record["destination"], "notification destination"),
        received,
        raw_ref["sha256"],
    )


def receipt_observability(
    payload: Any,
    profile_hash: str,
    approved: dict[str, Any],
    approvals: Approvals,
    environment: str,
    start: datetime,
    end: datetime,
    *,
    artifact_hashes: set[str],
    primary_destinations: set[str],
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
            optional="firing_delivery resolution_delivery",
            label="alert event",
        )
        require(
            {"firing_delivery", "resolution_delivery"} <= row.keys(),
            "Missing alert delivery evidence for firing or resolution.",
            3,
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
        firing_id, firing_destination, firing_received, firing_hash = alert_delivery(
            row["firing_delivery"],
            approvals.evidence,
            artifact_hashes,
            row,
            profile_hash,
            "firing",
            executed[2],
            end,
        )
        resolution_id, resolution_destination, resolution_received, resolution_hash = (
            alert_delivery(
                row["resolution_delivery"],
                approvals.evidence,
                artifact_hashes,
                row,
                profile_hash,
                "resolved",
                executed[4],
                end,
            )
        )
        require(
            firing_id == row["message_id"]
            and resolution_id != firing_id
            and firing_hash != resolution_hash
            and firing_destination.casefold() == resolution_destination.casefold()
            and firing_received <= resolution_received,
            "Firing and resolution must have distinct delivery evidence for the same destination.",
            3,
        )
        recipient = meaningful(row["recipient"], "alert recipient identity")
        if row["independent_path"]:
            require(
                firing_destination in primary_destinations,
                "Independent firing and resolution use an unapproved monitor destination.",
                3,
            )
        ack = utc(row["acknowledged_at"], "alert acknowledgement")
        require(
            firing_received <= ack <= end
            and (ack - executed[2]).total_seconds() <= approved["acknowledgement_limit_seconds"],
            "Alert acknowledgement exceeded the approved bound.",
            4,
        )
        acknowledgement = approvals.check(
            row["acknowledgement_ref"],
            "acknowledge_alert",
            canonical_digest(
                {
                    key: item
                    for key, item in row.items()
                    if key
                    not in {
                        "acknowledgement_ref",
                        "recovered_at",
                        "resolved_at",
                        "resolution_delivery",
                    }
                }
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
    devices = {device_key(value) for value in support["desktop_targets"]}
    observed: set[tuple[str, str, str, str]] = set()
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
        require(
            (platform, role) in matrix[scenario],
            "UAT scenario role/platform is outside the frozen map.",
            3,
        )
        observed.add(
            (scenario, platform, role, row["device"]["browser"] if platform != "operations" else "")
        )
        require(type(row["physical_device"]) is bool, "Invalid physical device marker.")
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
    expected = {
        (scenario, platform, role, browser)
        for scenario, pairs in matrix.items()
        if (int(scenario.removeprefix("UAT-")) in FINAL_SCENARIOS) == (phase == "final")
        for platform, role in pairs
        for browser in (DESKTOP_BROWSERS if platform == "desktop" else ("",))
    }
    require(
        expected <= observed, "A required UAT scenario, platform or role has no executed pass.", 3
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


def verify_repair(
    value: Any, identity: dict[str, str], population: str, exception_id: str, approvals: Approvals
) -> None:
    repair = fields(
        value, "plan_ref backup_ref authorization_ref execution_ref", label="legacy repair evidence"
    )
    scope = {
        **identity,
        "population": population,
        "exception_id": exception_id,
        "plan_sha256": approvals.evidence.load(repair["plan_ref"]),
        "backup_sha256": approvals.evidence.load(repair["backup_ref"]),
    }
    authorization = approvals.check(
        repair["authorization_ref"], "data_repair", canonical_digest(scope)
    )
    meaningful(authorization.get("authorization_reference"), "data repair authorization reference")
    execution = fields(
        approvals.evidence.load(repair["execution_ref"], parse=True),
        "source_sha environment configuration_sha256 population exception_id plan_sha256 "
        "backup_sha256 authorization_sha256 started_at completed_at outcome",
        label="legacy repair execution",
    )
    started, completed = check_execution(
        execution["started_at"], execution["completed_at"], approvals.now, "data repair"
    )
    require(
        all(execution[key] == expected for key, expected in scope.items())
        and authorization.get("source_sha") == identity["source_sha"]
        and authorization.get("environment") == identity["environment"]
        and execution["authorization_sha256"] == repair["authorization_ref"]["sha256"]
        and execution["outcome"] == "pass"
        and utc(authorization["approved_at"], "repair approval")
        <= utc(authorization.get("valid_from"), "repair authorization start")
        <= started
        <= completed
        < utc(authorization.get("valid_until"), "repair authorization expiry"),
        "Legacy repair does not match its approved plan, backup, or execution window.",
        3,
    )


RECONCILIATION_TOOLS = {
    "supervisor_links": "report_supervisor_verification",
    "reservations": "report_inventory_reservation_drift",
    "approvals": "report_inventory_reservation_drift",
    "payments": "report_payment_overages",
    "offline": "repair_offline_duplicates",
    "media_quota": "report_media_quota_drift",
    "retention": "preview_audit_retention",
}


def reconciliation_finding(population: str, value: Any) -> str | None:
    require(isinstance(value, dict), "Invalid reconciliation finding.")
    if population in {"reservations", "approvals"}:
        finding = exact(
            value.get("finding"),
            {
                "stock_reservation_drift",
                "cancelled_request_with_open_approval",
                "cancelled_request_with_reserved_line",
                "open_reservation_without_stock",
                "open_reservation_over_remaining",
            },
            "inventory finding",
        )
        if finding == "cancelled_request_with_open_approval":
            return (
                meaningful(value.get("approval_id"), "approval ID")
                if population == "approvals"
                else None
            )
        if population == "approvals":
            return None
        if finding == "stock_reservation_drift":
            item = meaningful(value.get("item_id"), "stock item ID")
            location = meaningful(value.get("location_id"), "stock location ID")
            return f"{finding}:{item}:{location}"
        return f"{finding}:{meaningful(value.get('line_id'), 'reservation line ID')}"
    if population == "media_quota":
        entity = exact(
            value.get("entity_type"), {"daily_report", "supervisor_update"}, "media owner type"
        )
        return f"{entity}:{meaningful(value.get('entity_id'), 'media owner ID')}"
    key = {"supervisor_links": "update_id", "payments": "invoice_id", "offline": "candidate"}
    return meaningful(value.get(key[population]), "observed exception ID")


def retention_exception_ids(pages: list[Any], policy_sha256: str, completed: datetime) -> set[str]:
    categories = {"missing", "unknown", "shorter_than_policy"}
    totals: dict[str, int] = {}
    seen: dict[str, set[str]] = {category: set() for category in categories}
    cursors: dict[str, str | None] = {}
    cutoff = None
    for page in pages:
        require(isinstance(page, dict), "Invalid retention inventory page.")
        category = exact(page.get("category"), categories, "retention exception category")
        page_cutoff = utc(page.get("cutoff_utc"), "retention inventory cutoff")
        cutoff = cutoff or page_cutoff
        counts = page.get("counts")
        require(isinstance(counts, dict), "Missing retention inventory totals.")
        total = count(counts.get(category), "retention exception total")
        require(
            page["policy_sha256"] == policy_sha256
            and cutoff == page_cutoff
            and cutoff <= completed
            and totals.setdefault(category, total) == total
            and (category not in cursors or cursors[category] is not None),
            "Retention inventory pages differ from the policy, cutoff or population.",
            3,
        )
        ids = []
        for row in items(page.get("rows"), "retention inventory rows", minimum=0):
            require(isinstance(row, dict), "Invalid retention exception row.")
            ids.append(meaningful(row.get("id"), "retention exception ID"))
        previous = cursors.get(category)
        cursor = page["next_after"]
        require(
            ids == sorted(set(ids))
            and (previous is None or bool(ids and ids[0] > previous))
            and (cursor is None or bool(ids and ids[-1] == cursor)),
            "Retention inventory has repeated or invalid page boundaries.",
            3,
        )
        seen[category].update(ids)
        cursors[category] = cursor
    require(
        set(totals) == categories
        and all(
            cursors[category] is None and len(seen[category]) == totals[category]
            for category in categories
        ),
        "Retention exception inventory is incomplete.",
        3,
    )
    return set().union(*seen.values())


def inventory_exception_ids(
    ref: Any,
    population: str,
    approvals: Approvals,
    identity: dict[str, str],
    retention_policy_sha256: str,
    artifact_hashes: set[str],
    receipt_window: tuple[datetime, datetime],
) -> set[str]:
    inventory = fields(
        approvals.evidence.load(ref, parse=True),
        "source_sha environment configuration_sha256 population tool started_at completed_at "
        "exit_code reports",
        label="read-only exception inventory",
    )
    require(
        all(inventory[key] == value for key, value in identity.items())
        and inventory["population"] == population
        and inventory["tool"] == RECONCILIATION_TOOLS[population]
        and type(inventory["exit_code"]) is int
        and inventory["exit_code"] == 0,
        "Legacy inventory execution differs from its release, population or tool.",
        3,
    )
    started, completed = check_execution(
        inventory["started_at"], inventory["completed_at"], approvals.now, "legacy inventory"
    )
    require(
        receipt_window[0] <= started <= completed <= receipt_window[1],
        "Legacy inventory was collected outside its reviewed receipt window.",
        3,
    )
    reports = []
    for report in items(inventory["reports"], "legacy inventory reports"):
        require(
            approvals.evidence.load(report) in artifact_hashes,
            "Legacy inventory report must be attached to the reviewed receipt.",
            3,
        )
        reports.append(approvals.evidence.load(report, parse=True))
    if population == "retention":
        return retention_exception_ids(reports, retention_policy_sha256, completed)
    observed = set()
    for report in reports:
        for row in items(report, "read-only report rows", minimum=0):
            exception = reconciliation_finding(population, row)
            if exception is not None:
                require(exception not in observed, "Duplicate finding in read-only report.", 3)
                observed.add(exception)
    return observed


def receipt_reconciliation(
    payload: Any,
    approved: dict[str, Any],
    records_owner: str,
    approvals: Approvals,
    identity: dict[str, str],
    artifact_hashes: set[str],
    retention_policy_sha256: str,
    receipt_window: tuple[datetime, datetime],
) -> None:
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
    populations = data["exceptions"]
    require(
        isinstance(populations, dict) and set(populations) == RECONCILIATION_TOOLS.keys(),
        "Legacy exception inventory is incomplete.",
        3,
    )
    for name, population in populations.items():
        row = fields(
            population, "inventory_ref observed_ids dispositions", label="legacy exception list"
        )
        inventory_hash = approvals.evidence.load(row["inventory_ref"])
        require(
            inventory_hash in artifact_hashes,
            "Legacy inventory must be attached to the reviewed reconciliation receipt.",
            3,
        )
        remaining = strings(row["observed_ids"], "observed exception IDs", minimum=0)
        require(
            remaining
            == inventory_exception_ids(
                row["inventory_ref"],
                name,
                approvals,
                identity,
                retention_policy_sha256,
                artifact_hashes,
                receipt_window,
            ),
            "Reconciliation exception IDs differ from the attached read-only findings.",
            3,
        )
        role = "records_owner" if name == "retention" else "finance_data_owner"
        owner = records_owner if name == "retention" else approved["signatories"][role]
        for value in items(row["dispositions"], "legacy exception dispositions", minimum=0):
            disposition = fields(
                value,
                "exception_id status reason evidence_ref approval_ref",
                optional="repair",
                label="legacy exception disposition",
            )
            exception_id = meaningful(disposition["exception_id"], "legacy exception ID")
            require(exception_id in remaining, "Unexpected or repeated exception disposition.", 3)
            remaining.remove(exception_id)
            status = exact(
                disposition["status"],
                {"resolved", "protected_exception", "repaired"},
                "legacy exception status",
            )
            meaningful(disposition["reason"], "legacy exception reason")
            approvals.evidence.load(disposition["evidence_ref"])
            approval = approvals.check(
                disposition["approval_ref"],
                "legacy_exception_disposition",
                canonical_digest(
                    {
                        **identity,
                        "population": name,
                        "inventory_sha256": inventory_hash,
                        "disposition": {
                            key: item for key, item in disposition.items() if key != "approval_ref"
                        },
                    }
                ),
                role=role,
            )
            require(
                approval["approver_identity"] == owner,
                "Legacy exception disposition lacks its named owner approval.",
                3,
            )
            require(
                ("repair" in disposition) == (status == "repaired"),
                "A repaired legacy exception requires separate repair evidence.",
                3,
            )
            if status == "repaired":
                verify_repair(disposition["repair"], identity, name, exception_id, approvals)
        require(
            not remaining,
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


def deployment_receipt_fields(raw: bytes) -> dict[str, str]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ContractError(2, "Invalid host deployment receipt encoding.") from None
    result: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition(": ")
        require(
            separator and key not in result and value.strip(),
            "Invalid or duplicate host deployment receipt field.",
        )
        result[key] = value.strip()
    return result


def verify_predeploy_verdict(
    payload: Any,
    sha: str,
    release_id: str,
    target_environment: str,
    subject_sha256: str,
    configuration_sha256: str,
    manifest_sha256: str,
    expected_runtime: dict[str, Any],
    control_registry_sha256: str,
    expected_receipt_ids: list[str],
    validator_sha256: str,
    deployed_at: datetime,
) -> None:
    verdict = fields(
        payload,
        "generated_at phase status accepted_scope_complete ready_for_authorized_deployment "
        "source_sha target_environment release_id manifest_sha256 subject_sha256 "
        "configuration_sha256 runtime_identity validator_version validator_sha256 "
        "control_registry_sha256 trust_registry_sha256 verified_receipt_ids blockers",
        label="predeployment verdict",
    )
    for key in (
        "manifest_sha256",
        "subject_sha256",
        "configuration_sha256",
        "validator_sha256",
        "control_registry_sha256",
        "trust_registry_sha256",
    ):
        digest(verdict[key], f"predeployment verdict {key}")
    require(
        verdict["phase"] == "predeploy"
        and verdict["status"] == "ready_for_authorized_deployment"
        and verdict["accepted_scope_complete"] is False
        and verdict["ready_for_authorized_deployment"] is True
        and verdict["source_sha"] == sha
        and verdict["target_environment"] == target_environment
        and verdict["release_id"] == release_id
        and verdict["subject_sha256"] == subject_sha256
        and verdict["configuration_sha256"] == configuration_sha256
        and verdict["manifest_sha256"] == manifest_sha256
        and runtime_identity(verdict["runtime_identity"]) == expected_runtime
        and verdict["validator_version"] == VERSION
        and verdict["validator_sha256"] == validator_sha256
        and verdict["control_registry_sha256"] == control_registry_sha256
        and verdict["blockers"] == []
        and isinstance(verdict["verified_receipt_ids"], list)
        and verdict["verified_receipt_ids"] == expected_receipt_ids
        and utc(verdict["generated_at"], "predeployment verdict") <= deployed_at,
        "Host deployment is not bound to a matching successful predeployment verdict.",
        3,
    )


def verify_predeploy_manifest(
    payload: Any,
    evidence: Evidence,
    *,
    release_id: str,
    source_sha: str,
    target_environment: str,
    subject_sha256: str,
    configuration_sha256: str,
    inventory_sha256: str,
    control_registry_sha256: str,
    decision_sha256: dict[str, str],
    validator_sha256: str,
) -> dict[str, str]:
    manifest = fields(
        payload,
        "format_version release_id repository source_sha target_environment release_subject "
        "scope decisions ledger receipts approvals defects validation_profile",
        optional="acceptance_bundle",
        label="host-authorized predeployment manifest",
    )
    require(
        type(manifest["format_version"]) is int
        and manifest["format_version"] == VERSION
        and "acceptance_bundle" not in manifest
        and manifest["release_id"] == release_id
        and manifest["repository"] == REPOSITORY
        and manifest["source_sha"] == source_sha
        and manifest["target_environment"] == target_environment,
        "Predeployment manifest identity differs from the deployed release.",
        3,
    )
    subject_ref = fields(
        manifest["release_subject"], "path sha256 size_bytes", label="predeployment subject"
    )
    require(
        subject_ref["sha256"] == subject_sha256,
        "Predeployment manifest does not reference the frozen release subject.",
        3,
    )
    subject = fields(
        evidence.load(manifest["release_subject"], parse=True),
        "release_id repository source_sha environment configuration_sha256 inventory_sha256 "
        "control_registry_sha256 decision_sha256 support_matrix_sha256 " + RUNTIME_FIELDS,
        label="predeployment release subject",
    )
    require(
        subject["release_id"] == release_id
        and subject["repository"] == REPOSITORY
        and subject["source_sha"] == source_sha
        and subject["environment"] == target_environment
        and subject["configuration_sha256"] == configuration_sha256
        and subject["inventory_sha256"] == inventory_sha256
        and subject["control_registry_sha256"] == control_registry_sha256
        and subject["decision_sha256"] == decision_sha256,
        "Predeployment subject differs from the frozen release identity.",
        3,
    )
    scope = fields(
        manifest["scope"],
        "accepted_inventory control_registry excluded_requirement_ids delivery_scope",
        label="predeployment scope",
    )
    require(
        scope["accepted_inventory"]["sha256"] == inventory_sha256
        and scope["control_registry"]["sha256"] == control_registry_sha256
        and scope["excluded_requirement_ids"] == ["G-01"]
        and scope["delivery_scope"] == "launch_readiness_only",
        "Predeployment manifest scope differs from the frozen release.",
        3,
    )
    decisions = [
        fields(ref, "path sha256 size_bytes", label="predeployment decision")["sha256"]
        for ref in items(manifest["decisions"], "predeployment decisions")
    ]
    require(
        len(set(decisions)) == len(decision_sha256)
        and set(decisions) == set(decision_sha256.values()),
        "Predeployment manifest decisions differ from the frozen release.",
        3,
    )
    profile = fields(
        manifest["validation_profile"],
        "validator_version validator_sha256 control_registry_sha256",
        label="predeployment validation profile",
    )
    require(
        profile["validator_version"] == VERSION
        and profile["validator_sha256"] == validator_sha256
        and profile["control_registry_sha256"] == control_registry_sha256,
        "Predeployment manifest was not validated by the trusted release contract.",
        3,
    )
    receipt_hashes: dict[str, str] = {}
    for ref in items(manifest["receipts"], "predeployment receipts"):
        reference = fields(ref, "path sha256 size_bytes", label="predeployment receipt")
        receipt = fields(
            evidence.load(ref, parse=True),
            "receipt_id kind phase source_sha environment configuration_sha256 synthetic "
            "started_at completed_at executed_by tool outcome results artifacts review",
            label="predeployment receipt",
        )
        name = meaningful(receipt["receipt_id"], "predeployment receipt ID")
        require(
            receipt["phase"] == "predeploy"
            and receipt["kind"] in PREDEPLOY_KINDS
            and name not in receipt_hashes,
            "Predeployment manifest contains an invalid or duplicate receipt.",
            3,
        )
        receipt_hashes[name] = reference["sha256"]
    require(bool(receipt_hashes), "Predeployment manifest has no verified receipts.", 3)
    return receipt_hashes


def verify_host_deployment_receipt(
    host: dict[str, str],
    deployed: dict[str, Any],
    sha: str,
    identity: dict[str, Any],
    deployed_at: datetime,
    predeploy_verdict_sha256: str | None = None,
    predeploy_manifest_sha256: str | None = None,
) -> None:
    expected = {
        "Status": "Deployed — Formal Acceptance Pending",
        "Commit": sha,
        "CI run": str(deployed["ci_run_id"]),
        "CI attempt": str(deployed["ci_run_attempt"]),
        "Deploy run": str(deployed["run_id"]),
        "Deploy attempt": str(deployed["run_attempt"]),
        "Asset SHA-256": identity["frontend_sha256"],
        "Service worker SHA-256": identity["service_worker_sha256"],
        "Backend image": identity["image_digests"]["backend"],
        "Frontend image": identity["image_digests"]["frontend"],
    }
    if predeploy_verdict_sha256 is not None:
        expected["Predeploy verdict SHA-256"] = predeploy_verdict_sha256
    if predeploy_manifest_sha256 is not None:
        expected["Predeploy manifest SHA-256"] = predeploy_manifest_sha256
    # New routine launchers attest migration separately from the schema identity.
    # Legacy receipts remain valid and still reject unknown or partial fields.
    migration = host.get("Routine migration")
    if migration is not None:
        require(migration in {"not needed", "upgraded"}, "Invalid routine migration outcome.")
        expected["Routine migration"] = migration
        if migration == "upgraded":
            source = host.get("Migration from", "")
            target = host.get("Migration to", "")
            seconds = host.get("Migration seconds", "")
            require(
                bool(re.fullmatch(r"[A-Za-z0-9_]{1,32}", source))
                and bool(re.fullmatch(r"[A-Za-z0-9_]{1,32}", target))
                and source != target
                and [target] == identity["schema_heads"]
                and bool(re.fullmatch(r"[0-9]+", seconds)),
                "Invalid routine migration receipt evidence.",
            )
            expected.update({
                "Migration from": source, "Migration to": target, "Migration seconds": seconds,
            })
    require(
        host.keys() == expected.keys() | {"UTC", "Schema heads", "Frontend asset"},
        "Invalid host deployment receipt fields.",
    )
    require(
        all(host[key] == value for key, value in expected.items())
        and utc(host["UTC"], "host deployment activation") == deployed_at
        and sorted(host["Schema heads"].split()) == identity["schema_heads"],
        "Host deployment receipt differs from the reviewed activation or frozen build.",
        3,
    )
    require(
        re.fullmatch(r"/assets/index-[A-Za-z0-9_-]+\.js", host["Frontend asset"]),
        "Invalid host deployment frontend asset path.",
    )


def observation(
    payload: Any,
    start: datetime,
    end: datetime,
    decisions: dict[str, Any],
    evidence: Evidence,
    identity: dict[str, str],
    artifact_hashes: set[str],
) -> None:
    data = fields(
        payload,
        "approved_window_seconds window_approval incidents scheduled_backup scheduled_monitoring",
        label="observation result",
    )
    recovery = decisions["D-29-RECOVERY"]
    operations = decisions["D-30-OPERATIONS"]
    cycle = max(recovery["backup_interval_minutes"] * 60, operations["probe_interval_seconds"])
    limit = count(data["approved_window_seconds"], "approved observation window", minimum=cycle)
    require(
        (end - start).total_seconds() >= limit, "Approved observation window has not elapsed.", 3
    )
    backup = fields(
        data["scheduled_backup"], "attempt_ref publication_ref", label="scheduled backup evidence"
    )
    monitor_ref = data["scheduled_monitoring"]
    for ref in (*backup.values(), monitor_ref):
        require(
            evidence.load(ref) in artifact_hashes,
            "Scheduled activity must be attached to the reviewed observation receipt.",
            3,
        )
    attempt = fields(
        evidence.load(backup["attempt_ref"], parse=True),
        "source_sha started_at_utc completed_at_utc phase outcome",
        label="scheduled backup attempt",
    )
    publication = fields(
        evidence.load(backup["publication_ref"], parse=True),
        "receipt key_id algorithm signature",
        label="scheduled backup publication",
    )
    meaningful(publication["key_id"], "scheduled backup key ID")
    digest(publication["signature"], "scheduled publication authentication tag")
    published = fields(
        publication["receipt"],
        "backup_set_id manifest_sha256 snapshot_at_utc remote_verified_at_utc source_sha "
        "source_environment policy_revision policy_sha256 configuration_sha256 "
        "destination_identity object_count outcome",
        label="published scheduled backup",
    )
    meaningful(published["backup_set_id"], "scheduled backup set ID")
    manifest_hash = digest(published["manifest_sha256"], "scheduled backup manifest")
    count(published["object_count"], "scheduled backup object count")
    snapshot = utc(published["snapshot_at_utc"], "scheduled backup snapshot")
    verified = utc(published["remote_verified_at_utc"], "scheduled backup publication")
    attempt_start = utc(attempt["started_at_utc"], "scheduled backup start")
    attempt_end = utc(attempt["completed_at_utc"], "scheduled backup completion")
    require(
        attempt["source_sha"] == published["source_sha"] == identity["source_sha"]
        and attempt["phase"] == "complete"
        and attempt["outcome"] == published["outcome"] == "pass"
        and publication["algorithm"] == "HMAC-SHA256"
        and published["source_environment"] == identity["environment"]
        and published["configuration_sha256"] == identity["configuration_sha256"]
        and published["policy_sha256"] == recovery["policy_ref"]["sha256"]
        and published["policy_revision"] == recovery["revision"]
        and published["destination_identity"] == recovery["destination_identity"]
        and start <= attempt_start <= snapshot <= verified <= attempt_end <= end
        and (verified - snapshot).total_seconds()
        <= recovery["maximum_publication_delay_minutes"] * 60,
        "Scheduled backup failed or differs from the approved release and observation window.",
        4,
    )
    monitor = fields(
        evidence.load(monitor_ref, parse=True),
        "profile_id profile_revision source_sha environment profile_sha256 checked_at completed_at "
        "executed_by observations",
        optional="transport_ready",
        label="scheduled monitor receipt",
    )
    require(
        monitor.get("transport_ready") is True,
        "Scheduled monitor notification transport was unavailable.",
        4,
    )
    meaningful(monitor["executed_by"], "scheduled monitor executor")
    check_start = utc(monitor["checked_at"], "scheduled check time")
    check_end = utc(monitor["completed_at"], "scheduled monitor completion")
    require(
        monitor["source_sha"] == identity["source_sha"]
        and monitor["environment"] == identity["environment"]
        and monitor["profile_sha256"] == operations["profile_ref"]["sha256"]
        and monitor["profile_id"] == operations["profile_id"]
        and monitor["profile_revision"] == operations["revision"]
        and start <= check_start <= check_end <= end
        and attempt_end <= check_end,
        "Scheduled monitor receipt differs from the approved release, profile or window.",
        4,
    )
    profile = evidence.load(operations["profile_ref"], parse=True)
    checks, backup_check = monitor_check_ids(profile)
    for event in items(monitor["observations"], "scheduled monitor observations"):
        row = fields(
            event,
            "check_id result event suppressed delivery message_id acknowledgement",
            label="scheduled monitor check",
        )
        check_id = meaningful(row["check_id"], "scheduled monitor check ID")
        result = fields(
            row["result"],
            "ok category status digest snapshot_at",
            optional="attempt_started_at attempt_completed_at",
            label="scheduled check result",
        )
        require(
            check_id in checks
            and result["ok"] is True
            and row["suppressed"] is False
            and row["delivery"] in {"none", "accepted"},
            "An approved scheduled check failed, was repeated, or was suppressed.",
            4,
        )
        if check_id == backup_check:
            require(
                result["category"] == "backup_current"
                and result["digest"] == manifest_hash
                and utc(result["snapshot_at"], "monitored backup snapshot") == snapshot
                and {"attempt_started_at", "attempt_completed_at"} <= result.keys()
                and utc(result["attempt_started_at"], "monitored attempt start") == attempt_start
                and utc(result["attempt_completed_at"], "monitored attempt completion")
                == attempt_end,
                "Backup freshness did not verify the observed scheduled backup.",
                4,
            )
        else:
            require(
                result["category"] == "ready" and result["status"] == 200,
                "Scheduled readiness was not verified.",
                4,
            )
            digest(result["digest"], "scheduled readiness response")
        checks.remove(check_id)
    require(not checks, "An approved scheduled check was not observed.", 3)
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
    object_count = len(items(manifest.get("objects"), "backup object inventory", minimum=0))
    require(
        object_count == result["required_object_count"]
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
    manifest_counts = {
        "application_database": 1,
        "configuration": len(config_paths),
        "objects": object_count,
        "grafana_database": int(isinstance(manifest.get("grafana_dump"), dict)),
    }
    require(
        "grafana_database" not in decision["required_artifact_categories"]
        or manifest_counts["grafana_database"] == 1,
        "Backup manifest lacks the approved Grafana database.",
        4,
    )
    require(
        result["required_category_counts"] == manifest_counts,
        "Reviewed recovery coverage differs from backup manifest category counts.",
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

    restore_ref = result["restore_receipt"]
    restored = fields(
        evidence.load(restore_ref, parse=True),
        "operation outcome assurance source_sha backup_set_id manifest_sha256 "
        "configuration_sha256 snapshot_at_utc restore_started_at_utc "
        "database_restored_at_utc objects_verified_at_utc expected_migration_heads "
        "observed_migration_heads required_object_count restored_object_count "
        "restored_category_counts",
        label="restore command receipt",
    )
    require(restore_ref["sha256"] in refs, "Restore command receipt must be classified.", 3)
    require(
        restored["operation"] == "disposable_artifact_restore"
        and restored["outcome"] == "pass"
        and restored["assurance"] == "authenticated format 2",
        "Restore command did not complete an authenticated restore.",
        4,
    )
    require(
        quantities(restored["restored_category_counts"], "restore command category")
        == manifest_counts,
        "Restore command category counts differ from the manifest coverage.",
        4,
    )
    require(
        restored["source_sha"] == receipt["source_sha"]
        and restored["configuration_sha256"] == receipt["configuration_sha256"]
        and restored["backup_set_id"] == result["backup_set_id"]
        and restored["manifest_sha256"] == manifest_hash,
        "Restore command receipt identifies a different backup or release.",
        3,
    )
    require(
        all(
            utc(restored[key], "restore command time") == utc(result[key], "recovery summary time")
            for key in (
                "snapshot_at_utc",
                "restore_started_at_utc",
                "database_restored_at_utc",
                "objects_verified_at_utc",
            )
        )
        and restored["expected_migration_heads"] == result["expected_schema_heads"]
        and restored["observed_migration_heads"] == result["observed_schema_heads"]
        and all(
            count(restored[key], f"restore command {key}") == result[key]
            for key in ("required_object_count", "restored_object_count")
        ),
        "Restore command results differ from the reviewed recovery summary.",
        4,
    )


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
        self.target = exact(target, {"production", "test"}, "target environment")
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
        self.inventory_sha256 = ""
        self.control_registry_sha256 = ""
        self.release_id = ""
        self.subject_hash = ""
        self.decision_hashes: dict[str, str] = {}
        self.decision_owners: dict[str, str] = {}
        self.decisions: dict[str, Any] = {}
        self.deploy_window: tuple[datetime, datetime] | None = None
        self.deployment_authorizer = ""
        self.activation_operator: str | None = None
        self.deployed_at: datetime | None = None
        self.observed_window: tuple[datetime, datetime] | None = None
        self.uat_defects: set[str] = set()
        self.receipts: dict[str, dict[str, Any]] = {}
        self.predeploy_receipt_hashes: dict[str, str] | None = None

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
            self.decision_owners[decision] = approval["approver_identity"]
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
        self.inventory_sha256 = inventory
        registry = scope["control_registry"]
        require(
            self.evidence.load(registry, parse=True) == control_registry(),
            "Required control or platform registry changed.",
            3,
        )
        subject = fields(
            self.evidence.load(manifest["release_subject"], parse=True),
            "release_id repository source_sha environment configuration_sha256 inventory_sha256 "
            "control_registry_sha256 decision_sha256 support_matrix_sha256 " + RUNTIME_FIELDS,
            label="frozen release subject",
        )
        self.subject_hash = manifest["release_subject"]["sha256"]
        self.control_registry_sha256 = registry["sha256"]
        self.release_id = meaningful(subject["release_id"], "release ID")
        require(
            self.release_id == manifest["release_id"]
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
            "validator_version validator_sha256 control_registry_sha256",
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

    def authorize_deployment(self, ref: Any) -> None:
        approval = self.approvals.check(
            ref, "deployment_authorization", self.subject_hash, role="release_authorizer"
        )
        require(
            approval.get("source_sha") == self.sha
            and approval.get("environment") == self.target
            and approval["approver_identity"]
            == self.decisions["D-33-BUSINESS"]["release_authorizer"]
            and (
                self.actor is None
                or approval["approver_identity"].casefold() != self.actor.casefold()
            ),
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
        self.deployment_authorizer = approval["approver_identity"]

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
        environment = self.target
        configuration = self.configuration
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
        receipt_identity = {
            "source_sha": self.sha,
            "environment": environment,
            "configuration_sha256": configuration,
        }
        if kind == "ci":
            receipt_ci(
                result,
                self.evidence,
                self.sha,
                self.token,
                self.expected_ci_run,
                artifact_hashes=artifact_hashes,
            )
        elif kind == "retention":
            receipt_retention(
                result,
                self.decisions["D-28-POLICY"],
                self.decisions["D-28-POLICY"]["policy_ref"]["sha256"],
            )
        elif kind == "recovery":
            recovery = self.decisions["D-29-RECOVERY"]
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
            profile_ref = operations["profile_ref"]
            profile = self.evidence.load(profile_ref, parse=True)
            _, recipients = monitor_contact_route(profile)
            receipt_observability(
                result,
                profile_ref["sha256"],
                operations,
                self.approvals,
                environment,
                start,
                end,
                artifact_hashes=artifact_hashes,
                primary_destinations=recipients["recipients"],
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
            receipt_reconciliation(
                result,
                self.decisions["D-33-BUSINESS"],
                self.decision_owners["D-28-POLICY"],
                self.approvals,
                receipt_identity,
                artifact_hashes,
                self.decisions["D-28-POLICY"]["policy_ref"]["sha256"],
                (start, end),
            )
        elif kind == "deployment":
            deployed = fields(
                result,
                "run_id run_url run_attempt ci_run_id ci_run_attempt deployed_at readback "
                "predeploy_manifest predeploy_verdict host_receipt",
                label="deployment result",
            )
            run_id = count(deployed["run_id"], "deployment run ID", minimum=1)
            require(deployed["run_url"] == run_url(run_id), "Invalid deployment run URL.")
            attempt = count(deployed["run_attempt"], "deployment run attempt", minimum=1)
            count(deployed["ci_run_id"], "deployment CI run ID", minimum=1)
            count(deployed["ci_run_attempt"], "deployment CI attempt", minimum=1)
            run = checked_run(run_id, self.sha, self.token, ci=False, attempt=attempt)
            self.activation_operator = workflow_operator(run)
            require(
                self.activation_operator.casefold() != self.deployment_authorizer.casefold(),
                "The actual deployment operator cannot authorize their own deployment.",
                3,
            )
            self.deployed_at = utc(deployed["deployed_at"], "deployment activation")
            assert self.deploy_window is not None
            require(
                start <= self.deployed_at <= end
                and utc(run.get("run_started_at"), "GitHub deployment start")
                <= self.deployed_at
                <= utc(run.get("updated_at"), "GitHub deployment completion")
                and self.deploy_window[0] <= self.deployed_at < self.deploy_window[1],
                "Deployment occurred outside its approval or recorded execution window.",
                3,
            )
            readback(deployed["readback"], self.identity)
            predeploy_ref = fields(
                deployed["predeploy_verdict"],
                "path sha256 size_bytes",
                label="predeployment verdict artifact",
            )
            predeploy_manifest_ref = fields(
                deployed["predeploy_manifest"],
                "path sha256 size_bytes",
                label="host-authorized predeployment manifest artifact",
            )
            require(
                predeploy_ref["sha256"] in artifact_hashes
                and predeploy_manifest_ref["sha256"] in artifact_hashes,
                "The predeployment verdict and manifest must be classified deployment artifacts.",
                3,
            )
            predeploy = self.evidence.load(predeploy_ref, parse=True)
            predeploy_manifest = self.evidence.load(predeploy_manifest_ref, parse=True)
            self.predeploy_receipt_hashes = verify_predeploy_manifest(
                predeploy_manifest,
                self.evidence,
                release_id=self.release_id,
                source_sha=self.sha,
                target_environment=self.target,
                subject_sha256=self.subject_hash,
                configuration_sha256=self.configuration,
                inventory_sha256=self.inventory_sha256,
                control_registry_sha256=self.control_registry_sha256,
                decision_sha256=self.decision_hashes,
                validator_sha256=self.verifier_hash,
            )
            verify_predeploy_verdict(
                predeploy,
                self.sha,
                self.release_id,
                self.target,
                self.subject_hash,
                self.configuration,
                predeploy_manifest_ref["sha256"],
                self.identity,
                self.control_registry_sha256,
                sorted(self.predeploy_receipt_hashes),
                self.verifier_hash,
                self.deployed_at,
            )
            host_ref = deployed["host_receipt"]
            host = self.evidence.load_deployment_receipt(host_ref)
            require(
                host_ref["sha256"] in artifact_hashes,
                "The host deployment receipt must be a classified artifact.",
                3,
            )
            verify_host_deployment_receipt(
                host,
                deployed,
                self.sha,
                self.identity,
                self.deployed_at,
                predeploy_ref["sha256"],
                predeploy_manifest_ref["sha256"],
            )
        elif kind == "runtime_readback":
            readback(result, self.identity)
        elif kind == "observation":
            observation(
                result,
                start,
                end,
                self.decisions,
                self.evidence,
                receipt_identity,
                artifact_hashes,
            )
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
        if self.phase == "final" and self.predeploy_receipt_hashes is not None:
            actual_predeploy = {
                name: ref["sha256"]
                for name, ref in artifact_refs.items()
                if self.receipts[name]["phase"] == "predeploy"
            }
            require(
                self.predeploy_receipt_hashes is not None
                and actual_predeploy == self.predeploy_receipt_hashes,
                "Final evidence does not contain the exact receipts authorized before deployment.",
                3,
            )
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
            require(
                deployment["ci_run_attempt"] == ci["run_attempt"],
                "Deployment did not use the accepted CI attempt.",
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
                and retest["configuration_sha256"] == self.configuration
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
        assert self.activation_operator is not None
        for approval_ref in items(approvals.get("final_acceptance"), "final sign-offs"):
            approval = self.approvals.check(approval_ref, "final_acceptance", ref["sha256"])
            role = exact(approval["authority_role"], FINAL_ROLES, "final authority role")
            require(
                role not in roles
                and approval["approver_identity"]
                == self.decisions["D-33-BUSINESS"]["signatories"][role]
                and approval["approver_identity"] != self.actor
                and approval["approver_identity"].casefold() != self.activation_operator.casefold()
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

    def validate_operations(self, refs: Any) -> None:
        policy = self.decisions["D-28-POLICY"]
        expiry_subject = canonical_digest(
            {
                "source_sha": self.sha,
                "environment": self.target,
                "configuration_sha256": self.configuration,
                "policy_sha256": policy["policy_ref"]["sha256"],
            }
        )
        require_expiry = self.target == "production" and policy["mode"] == "scheduled_expiry"
        matching_expiry = 0
        for ref in items(refs, "operation approvals", minimum=0):
            operation = self.evidence.load(ref, parse=True)
            require(isinstance(operation, dict), "Invalid operation authorization.")
            purpose = exact(
                operation.get("purpose"),
                {"data_repair", "legacy_disposal", "purge"},
                "operation purpose",
            )
            subject = digest(operation.get("subject_sha256"), "operation subject")
            approval = self.approvals.check(ref, purpose, subject)
            if not require_expiry or purpose != "purge" or subject != expiry_subject:
                continue
            activation = self.now if self.phase == "predeploy" else self.deployed_at
            assert activation is not None
            meaningful(approval.get("authorization_reference"), "purge authorization reference")
            require(
                approval["authority_role"] == "release_authorizer"
                and approval["approver_identity"]
                == self.decisions["D-33-BUSINESS"]["release_authorizer"]
                and approval.get("source_sha") == self.sha
                and approval.get("environment") == self.target
                and utc(approval["approved_at"], "purge approval")
                <= utc(approval.get("valid_from"), "purge authorization start")
                <= activation
                < utc(approval.get("valid_until"), "purge authorization expiry"),
                "Scheduled expiry authorization differs from its approved authority or window.",
                3,
            )
            matching_expiry += 1
        require(
            not require_expiry or matching_expiry == 1,
            "Production scheduled expiry requires a separate exact-policy purge authorization.",
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
        self.validate_operations(approvals.get("operations", []))
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


def approved_external_configuration_path(relative: str) -> bool:
    parts = safe_parts(relative)
    if parts in (["secrets", "jwt_private_key"], ["secrets", "jwt_public_key"]):
        return True
    return (
        len(parts) == 5
        and parts[0] == "releases"
        and parts[2:4] == ["nginx", "ssl"]
        and parts[4] in {"fullchain.pem", "privkey.pem"}
    )


def host_configuration(state: Path) -> str:
    value, _ = json_file(state / "authorized-configuration.json", protected=True)
    profile = fields(value, "configuration_sha256 files", label="approved host configuration")
    checksums = profile["files"]
    require(isinstance(checksums, dict), "Invalid approved configuration file map.", 3)

    host_files: set[str] = set()
    release_files: set[str] = set()
    external_files: set[str] = set()
    for name, expected_hash in checksums.items():
        digest(expected_hash, "approved configuration file")
        parts = safe_parts(name)
        require(len(parts) >= 2, "Invalid approved configuration file identity.", 3)
        namespace, relative = parts[0], "/".join(parts[1:])
        if namespace == "host":
            host_files.add(relative)
            root = state
        elif namespace == "release":
            release_files.add(relative)
            continue
        elif namespace == "external":
            external_files.add(relative)
            root = state.parent
            require(
                approved_external_configuration_path(relative),
                "Unapproved external file path in host configuration.",
                3,
            )
        else:
            raise ContractError(3, "Unknown approved configuration file namespace.")

        with open_evidence(root.joinpath(*parts[1:]), protected=True) as file:
            require(
                hashlib.file_digest(file, "sha256").hexdigest() == expected_hash,
                "A protected deployment setting differs from the approved host configuration.",
                3,
            )

    require(
        host_files == {"production.env", "compose.vps.yml"},
        "Approved host configuration must contain exactly the deployment input set.",
        3,
    )
    require(
        release_files == RELEASE_CONFIGURATION_FILES,
        "Approved host configuration does not cover the complete release configuration set.",
        3,
    )
    fullchain_paths = {path for path in external_files if path.endswith("/nginx/ssl/fullchain.pem")}
    private_key_paths = {path for path in external_files if path.endswith("/nginx/ssl/privkey.pem")}
    require(
        {"secrets/jwt_private_key", "secrets/jwt_public_key"} <= external_files
        and len(fullchain_paths) == 1
        and len(private_key_paths) == 1
        and next(iter(fullchain_paths)).removesuffix("fullchain.pem")
        == next(iter(private_key_paths)).removesuffix("privkey.pem")
        and len(external_files) == 4,
        "Approved host configuration omits a mounted key or TLS file.",
        3,
    )

    approved = digest(profile["configuration_sha256"], "approved host configuration")
    actual = canonical_digest(checksums)
    require(
        approved == actual,
        "Approved host configuration digest does not match its protected file hashes.",
        3,
    )
    return actual


def _mounted_tree_hashes(path: Path, *, protected: bool) -> dict[str, str]:
    require(not path.is_symlink(), "A mounted configuration path must not be a symlink.", 3)
    if path.is_file():
        candidates = [path]
    else:
        require(path.is_dir(), "A mounted configuration path is missing or not a file.", 3)
        candidates = sorted(path.rglob("*"))
    result: dict[str, str] = {}
    for candidate in candidates:
        require(not candidate.is_symlink(), "A mounted configuration tree contains a symlink.", 3)
        if candidate.is_dir():
            continue
        if candidate.name == ".gitkeep":
            continue
        require(candidate.is_file(), "A mounted configuration tree contains a special file.", 3)
        with open_evidence(candidate, protected=protected) as file:
            result[candidate.as_posix()] = hashlib.file_digest(file, "sha256").hexdigest()
    return result


def _production_environment(path: Path) -> dict[str, str]:
    with open_evidence(path) as file:
        try:
            lines = file.read().decode("utf-8").splitlines()
        except UnicodeDecodeError:
            raise ContractError(3, "The protected production environment is invalid.") from None
    values: dict[str, str] = {}
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value.startswith("export "):
            value = value[7:].lstrip()
        key, separator, item = value.partition("=")
        key = key.strip()
        require(
            separator
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is not None
            and key not in values,
            "The protected production environment is invalid or ambiguous.",
            3,
        )
        item = item.strip()
        if item and item[0] in {"'", '"'} and len(item) >= 2 and item[-1] == item[0]:
            item = item[1:-1]
        else:
            item = item.split(" #", 1)[0].strip()
        values[key] = item
    return values


def _effective_environment(service: dict[str, Any], service_name: str) -> dict[str, str]:
    raw_environment = service.get("environment") or {}
    environment: dict[str, str] = {}
    entries: list[tuple[Any, Any]]
    if isinstance(raw_environment, dict):
        entries = list(raw_environment.items())
    elif isinstance(raw_environment, list):
        entries = []
        for entry in raw_environment:
            require(
                isinstance(entry, str) and "=" in entry,
                f"Invalid effective application environment for {service_name}.",
                3,
            )
            key, value = entry.split("=", 1)
            entries.append((key, value))
    else:
        raise ContractError(3, f"Invalid effective application environment for {service_name}.")

    for key, value in entries:
        require(
            isinstance(key, str)
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is not None
            and isinstance(value, (str, int, float, bool))
            and key not in environment,
            f"Invalid effective application environment for {service_name}.",
            3,
        )
        environment[key] = str(value).strip().strip("\"'")
    return environment


def configuration_files_from_runtime(
    state: Path, release_root: Path, compose_config: Any
) -> dict[str, str]:
    """Build the nonsecret digest map from host files and effective candidate Compose mounts."""
    candidate_root = release_root.absolute()
    portal_root = state.parent.absolute()
    checksums: dict[str, str] = {}

    for name in ("production.env", "compose.vps.yml"):
        with open_evidence(state / name, protected=True) as file:
            checksums[f"host/{name}"] = hashlib.file_digest(file, "sha256").hexdigest()

    with open_evidence(candidate_root / ".env", protected=True) as file:
        candidate_environment_hash = hashlib.file_digest(file, "sha256").hexdigest()
    require(
        candidate_environment_hash == checksums["host/production.env"],
        "The candidate environment file differs from the pinned production environment.",
        3,
    )
    expected_environment = _production_environment(candidate_root / ".env")
    dotenv_purge_setting = expected_environment.get("LOG_PURGE_ENABLED", "")
    require(
        dotenv_purge_setting.strip("\"'").lower() in {"false", "0", "no", "off"},
        "Production audit deletion must be disabled for this release.",
        3,
    )

    for name in RELEASE_CONFIGURATION_FILES:
        with open_evidence(candidate_root.joinpath(*safe_parts(name)), protected=True) as file:
            checksums[f"release/{name}"] = hashlib.file_digest(file, "sha256").hexdigest()

    require(
        isinstance(compose_config, dict),
        "Invalid effective Compose configuration fields.",
        3,
    )
    compose_fields: dict[str, Any] = {}
    for name, value in compose_config.items():
        require(
            isinstance(name, str),
            "Invalid effective Compose configuration fields.",
            3,
        )
        if name.startswith("x-"):
            require(len(name) > 2, "Invalid effective Compose extension field.", 3)
            continue
        compose_fields[name] = value

    compose = fields(
        compose_fields,
        "services",
        optional="configs name networks secrets version volumes",
        label="effective Compose configuration",
    )
    services = compose["services"]
    require(isinstance(services, dict), "Invalid effective Compose services.", 3)
    for service_name in ("backend", "celery_worker", "celery_beat"):
        service = services.get(service_name)
        require(isinstance(service, dict), "A required application service is absent.", 3)
        environment = _effective_environment(service, service_name)
        if "LOG_PURGE_ENABLED" in environment:
            purge_setting = environment["LOG_PURGE_ENABLED"]
            require(
                purge_setting.lower() in {"false", "0", "no", "off"},
                "Production audit deletion must be disabled for this release.",
                3,
            )
        missing = sorted(set(expected_environment) - set(environment))
        mismatched = sorted(
            key
            for key, expected in expected_environment.items()
            if key in environment and environment[key] != expected
        )
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if mismatched:
            details.append(f"mismatched keys: {', '.join(mismatched)}")
        require(
            not details,
            f"Service {service_name} does not receive the pinned production environment "
            f"({'; '.join(details)}).",
            3,
        )

    release_mounts: set[str] = set()
    external_mounts: dict[str, str] = {}
    for service in services.values():
        require(isinstance(service, dict), "Invalid effective Compose service.", 3)
        mounts = service.get("volumes", [])
        require(isinstance(mounts, list), "Invalid effective Compose mounts.", 3)
        for mount in mounts:
            require(isinstance(mount, dict), "Invalid effective Compose mount.", 3)
            if mount.get("type") != "bind":
                continue
            source = mount.get("source")
            require(
                isinstance(source, str) and Path(source).is_absolute(),
                "Invalid bind mount source.",
                3,
            )
            normalized = Path(os.path.normpath(source))
            if normalized == Path("/var/run/docker.sock"):
                continue
            try:
                normalized.relative_to(candidate_root)
            except ValueError:
                try:
                    normalized.relative_to(portal_root)
                except ValueError:
                    raise ContractError(
                        3, "A bind mount is outside the approved host or release root."
                    ) from None
                for path, file_hash in _mounted_tree_hashes(normalized, protected=True).items():
                    rel_file = Path(path).relative_to(portal_root).as_posix()
                    require(
                        approved_external_configuration_path(rel_file),
                        "An effective external mount path is not approved for "
                        "configuration hashing.",
                        3,
                    )
                    external_mounts[f"external/{rel_file}"] = file_hash
            else:
                for path in _mounted_tree_hashes(normalized, protected=True):
                    rel_file = Path(path).relative_to(candidate_root).as_posix()
                    release_mounts.add(rel_file)

    expected_release_mounts = RELEASE_CONFIGURATION_FILES - {"docker-compose.prod.yml"}
    required_release_mounts = expected_release_mounts - {
        "observability/grafana/contact-points/usesend.yml"
    }
    require(
        required_release_mounts <= release_mounts <= expected_release_mounts,
        "Effective Compose bind mounts do not cover the approved release configuration set.",
        3,
    )
    fullchain_mounts = {
        name for name in external_mounts if name.endswith("/nginx/ssl/fullchain.pem")
    }
    private_key_mounts = {
        name for name in external_mounts if name.endswith("/nginx/ssl/privkey.pem")
    }
    require(
        {"external/secrets/jwt_private_key", "external/secrets/jwt_public_key"}
        <= external_mounts.keys()
        and len(fullchain_mounts) == 1
        and len(private_key_mounts) == 1
        and next(iter(fullchain_mounts)).removesuffix("fullchain.pem")
        == next(iter(private_key_mounts)).removesuffix("privkey.pem")
        and len(external_mounts) == 4,
        "Effective Compose configuration omits a mounted key or TLS file.",
        3,
    )
    checksums.update(external_mounts)
    return checksums


def verify_release_configuration(state: Path, release_root: Path, compose_config: Any) -> None:
    """Verify candidate config bytes and every effective bind-mounted config before activation."""
    approved = host_configuration(state)
    profile, _ = json_file(state / "authorized-configuration.json", protected=True)
    actual_files = configuration_files_from_runtime(state, release_root, compose_config)
    require(
        actual_files == profile["files"] and canonical_digest(actual_files) == approved,
        "Candidate runtime configuration differs from the approved host configuration.",
        3,
    )


def host_main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-state", type=Path, required=True)
    parser.add_argument("--commit")
    parser.add_argument("--ci-run", type=int)
    parser.add_argument("--deploy-run", type=int)
    parser.add_argument("--deploy-attempt", type=int)
    parser.add_argument("--verify-runtime-config-root", type=Path)
    parser.add_argument("--configuration-profile-root", type=Path)
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
        require(
            not (args.verify_runtime_config_root and args.configuration_profile_root),
            "Select only one runtime-configuration operation.",
        )
        if args.configuration_profile_root is not None:
            require(
                args.configuration_profile_root.is_absolute(),
                "Candidate release path must be absolute.",
            )
            compose_config = strict_json(sys.stdin.buffer.read())
            file_map = configuration_files_from_runtime(
                args.host_state, args.configuration_profile_root, compose_config
            )
            print(
                json.dumps(
                    {
                        "configuration_sha256": canonical_digest(file_map),
                        "files": file_map,
                    },
                    sort_keys=True,
                    indent=2,
                )
            )
            return

        if args.verify_runtime_config_root is not None:
            require(
                args.verify_runtime_config_root.is_absolute(),
                "Candidate release path must be absolute.",
            )
            compose_config = strict_json(sys.stdin.buffer.read())
            verify_release_configuration(
                args.host_state, args.verify_runtime_config_root, compose_config
            )
            print(json.dumps({"status": "runtime_configuration_verified"}, sort_keys=True))
            return

        require(
            args.commit is not None
            and args.ci_run is not None
            and args.deploy_run is not None
            and args.deploy_attempt is not None,
            "Predeployment validation requires complete run identities.",
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
            actor=deployment_operator(args.deploy_run, source, token, attempt=args.deploy_attempt),
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
