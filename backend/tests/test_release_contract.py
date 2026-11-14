from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile, ZipInfo

import pytest

from scripts import release_contract as contract
from scripts.launch_evidence import strict_verdict

SHA = "a" * 40
CONFIG = "b" * 64
BACKUP_SET_ID = "b" * 32
NOW = datetime.now(UTC).replace(microsecond=0)
STAGE_START = NOW - timedelta(hours=1)
STAGE_END = NOW - timedelta(minutes=30)
DEPLOYED = NOW - timedelta(minutes=19)
FINAL_START = NOW - timedelta(minutes=18)
FINAL_END = NOW - timedelta(minutes=10)


class Bundle:
    def __init__(self, parent: Path) -> None:
        self.root = (parent / "evidence").resolve()
        self.root.mkdir()
        self.trust = self.root.parent / "trusted.json"
        self.approvals: dict[str, Any] = {}
        self.ci_artifacts: list[dict[str, Any]] = []
        self.recovery_artifacts: dict[str, list[dict[str, Any]]] = {}
        self.observation_artifacts: list[dict[str, Any]] = []
        self.inventory_artifacts: list[dict[str, Any]] = []
        self.deployment_artifacts: list[dict[str, Any]] = []
        self.alert_artifacts: dict[str, list[dict[str, Any]]] = {}
        self.sequence = 0
        self.artifact = self.write("artifacts/report.json", {"actual": "Synthetic fixture"})
        self.artifact["sensitivity"] = "sanitized"

    def write(self, name: str, value: Any) -> dict[str, Any]:
        return self.write_bytes(name, json.dumps(value, sort_keys=True).encode())

    def write_bytes(self, name: str, raw: bytes) -> dict[str, Any]:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}

    def approval(
        self,
        purpose: str,
        digest: str,
        role: str,
        identity: str,
        *,
        at: datetime = NOW - timedelta(minutes=5),
        **extras: Any,
    ) -> dict[str, Any]:
        self.sequence += 1
        approval = {
            "purpose": purpose,
            "approver_identity": identity,
            "authority_role": role,
            "subject_sha256": digest,
            "approved_at": at.isoformat(),
            "approval_artifact": self.artifact,
            **extras,
        }
        ref = self.write(f"approvals/approval-{self.sequence}.json", approval)
        self.approvals[ref["sha256"]] = {
            "purpose": purpose,
            "approver_identity": identity,
            "authority_role": role,
            "provenance_reference": f"fixture-approval-{self.sequence}",
            "verified_by": "Independent Fixture Reviewer",
            "verified_at": NOW.isoformat(),
        }
        return ref

    def validator(self, phase: str, **extra: Any) -> contract.Validation:
        self.trust.write_text(
            json.dumps({"format_version": 1, "verified_approvals": self.approvals})
        )
        target = extra.pop("target", "test")
        return contract.Validation(
            self.root, self.trust, phase=phase, sha=SHA, target=target, token=None, **extra
        )

    def receipt(
        self,
        kind: str,
        result: Any,
        phase: str = "predeploy",
        *,
        executor: str = "Fixture Executor",
        start: datetime | None = None,
    ) -> dict[str, Any]:
        start = start or (STAGE_START if phase == "predeploy" else FINAL_START)
        end = STAGE_END if phase == "predeploy" else FINAL_END
        row = {
            "receipt_id": f"{phase}-{kind}",
            "kind": kind,
            "phase": phase,
            "source_sha": SHA,
            "environment": "test",
            "configuration_sha256": CONFIG,
            "synthetic": True,
            "started_at": start.isoformat(),
            "completed_at": end.isoformat(),
            "executed_by": executor,
            "tool": "fixture tests",
            "outcome": "pass",
            "results": result,
            "artifacts": [
                self.artifact,
                *(self.ci_artifacts if kind == "ci" else []),
                *(self.recovery_artifacts[phase] if kind == "recovery" else []),
                *(self.observation_artifacts if kind == "observation" else []),
                *(self.inventory_artifacts if kind == "data_reconciliation" else []),
                *(self.deployment_artifacts if kind == "deployment" else []),
                *(self.alert_artifacts.get(phase, []) if kind == "observability" else []),
            ],
        }
        row["review"] = self.approval(
            "review_receipt",
            contract.canonical_digest(row),
            "release_reviewer",
            "Fixture Release Reviewer",
        )
        return self.write(f"receipts/{phase}-{kind}.json", row)

    def alert(
        self, name: str, start: datetime, phase: str, profile_hash: str
    ) -> dict[str, Any]:
        times = ["trigger_at", "evaluated_at", "fired_at", "recovered_at", "resolved_at"]
        result = {
            "rule_id": name,
            "environment": "test",
            "synthetic": True,
            **{
                key: (start + timedelta(seconds=index)).isoformat()
                for index, key in zip((0, 1, 2, 6, 7), times, strict=True)
            },
            "message_id": f"fixture-{name}",
            "recipient": "Fixture Primary",
            "independent_path": True,
            "acknowledged_at": (start + timedelta(seconds=5)).isoformat(),
        }
        for notification, received, message_id, key in (
            ("firing", start + timedelta(seconds=3), result["message_id"], "firing_delivery"),
            ("resolved", start + timedelta(seconds=8), f"resolved-{name}", "resolution_delivery"),
        ):
            prefix = f"artifacts/{phase}-{name}-{notification}"
            receipt = self.write_bytes(f"{prefix}.eml", f"Message-ID: {message_id}\n".encode())
            delivery = self.write(
                f"{prefix}.json",
                {
                    "rule_id": name,
                    "environment": "test",
                    "profile_sha256": profile_hash,
                    "notification": notification,
                    "message_id": message_id,
                    "recipient": result["recipient"],
                    "destination": "operator@example.test",
                    "received_at": received.isoformat(),
                    "receipt_ref": receipt,
                },
            )
            self.alert_artifacts.setdefault(phase, []).extend(
                {**ref, "sensitivity": "sanitized"} for ref in (receipt, delivery)
            )
            result[key] = delivery
        result["acknowledgement_ref"] = self.approval(
            "acknowledge_alert",
            contract.canonical_digest(
                {
                    key: value
                    for key, value in result.items()
                    if key not in {"recovered_at", "resolved_at", "resolution_delivery"}
                }
            ),
            "alert_recipient",
            "Fixture Primary",
            at=start + timedelta(seconds=5),
        )
        return result

    def uat(self, phase: str, support: dict[str, Any], start: datetime) -> list[dict[str, Any]]:
        results = []
        devices = support["desktop_targets"] + [device("operations", "Operator")]
        for scenario, targets in support["scenario_platform_map"].items():
            if (int(scenario.removeprefix("UAT-")) in contract.FINAL_SCENARIOS) != (
                phase == "final"
            ):
                continue
            for target in targets:
                platform = target["platform"]
                for current in devices:
                    if current["platform"] != platform:
                        continue
                    row = {
                        "scenario_id": scenario,
                        "role": target["role"],
                        "fixture_version": "fixture-v1",
                        "source_sha": SHA,
                        "environment": "test",
                        "configuration_sha256": CONFIG,
                        "device": current,
                        "physical_device": False,
                        "executed_at": start.isoformat(),
                        "expected": "Authorized operation succeeds",
                        "actual": "Synthetic authorized operation succeeded",
                        "outcome": "pass",
                        "artifact_sha256": [self.artifact["sha256"]],
                        "defect_ids": [],
                        "tester": "Fixture Tester",
                    }
                    row["reviewer_approval"] = self.approval(
                        "review_uat", contract.canonical_digest(row), "qa_lead", "Fixture QA Lead"
                    )
                    results.append(row)
        return results


def device(platform: str, browser: str) -> dict[str, str]:
    return {
        "platform": platform,
        "device_model": f"Fixture {platform} model",
        "os_version": "1.2.3",
        "browser": browser,
        "browser_version": "123.1",
    }


def true(*keys: str) -> dict[str, bool]:
    return dict.fromkeys(keys, True)


def decision_values(bundle: Bundle) -> dict[str, dict[str, Any]]:
    ref = bundle.artifact
    matrix = {
        f"UAT-{index:02}": [
            {"platform": platform, "role": role}
            for platform in sorted(contract.required_platforms(f"UAT-{index:02}"))
            for role in (
                ["operator"]
                if platform == "operations"
                else [
                    sorted(group)[0]
                    for group in contract.UAT_REQUIRED_ROLES.get(f"UAT-{index:02}", ({"operator"},))
                ]
            )
        ]
        for index in range(2, 41)
    }
    matrix["UAT-01"] = [{"platform": "desktop", "role": role} for role in sorted(contract.ROLE_IDS)]
    return {
        "D-27-SCOPE": {
            "delivery_scope": "launch_readiness_only",
            "accepted_inventory_sha256": ref["sha256"],
            "excluded_requirement_ids": ["G-01"],
        },
        "D-28-POLICY": {
            "policy_id": "fixture-retention",
            "mode": "retain_only",
            "classes": [
                {
                    "class_id": "fixture-activity",
                    "predicates": [{"event_type": "activity", "action_prefix": "record."}],
                    "start_event": "created_at",
                    "duration_unit": "days",
                    "duration_value": 30,
                    "hold_behavior": "no_holds",
                }
            ],
            "unknown_disposition": "preserve_and_report",
            "holds_required": False,
        },
        "D-29-RECOVERY": {
            "policy_id": "fixture-recovery",
            "rpo_minutes": 60,
            "rto_minutes": 60,
            "backup_interval_minutes": 5,
            "maximum_capture_pause_seconds": 60,
            "maximum_publication_delay_minutes": 5,
            "minimum_spool_free_bytes": 1000,
            "retention_rules": {
                "daily_days": 2,
                "monthly_months": 2,
                "keep_last_good": 2,
                "held_set_ids": [],
            },
            "destination_identity": {
                "endpoint": "backup.example.test",
                "bucket": "fixture-backup",
                "prefix": "fixture/recovery",
                "secure": True,
            },
            "failure_domains": {
                "source": "fixture primary",
                "destination": "fixture secondary",
            },
            "key_custodians": ["Fixture Key One", "Fixture Key Two"],
            "operator": "Fixture Restore Operator",
            "substitute_operator": "Fixture Restore Substitute",
            "exercise_interval": "P30D",
            "required_artifact_categories": [
                "application_database",
                "configuration",
                "objects",
            ],
            "required_configuration_paths": ["compose.vps.yml"],
        },
        "D-30-OPERATIONS": {
            "profile_id": "fixture-operations",
            "environment": "test",
            "targets": ["https://health.example.test"],
            "probe_interval_seconds": 30,
            "failure_threshold": 2,
            "recovery_threshold": 2,
            "repeat_interval_seconds": 600,
            "acknowledgement_limit_seconds": 120,
            "primary_responder": "Fixture Primary",
            "substitute_responder": "Fixture Substitute",
            "recipient_ref": ref,
            "transport_ref": ref,
            "maintenance_rules_ref": ref,
        },
        "D-32-SUPPORT": {
            "desktop_targets": [device("desktop", "Chrome"), device("desktop", "Edge")],
            "physical_mobile_targets": [],
            "scenario_platform_map": matrix,
            "network_profiles": ["Fixture impaired network"],
            "budgets": {"reload_ms": 2000},
            "testers": ["Fixture Tester"],
        },
        "D-33-BUSINESS": {
            "assignment_export": ref,
            "accepted_samples": dict.fromkeys(
                ("boq", "report_pdf", "invoice_payment", "document_revision", "analytics_export"),
                ref,
            ),
            "timezone": "UTC",
            "currency": "QAR",
            "precision": 2,
            "tax_rounding_ref": ref,
            "material_approval_threshold": "250.00",
            "numbering_rules_ref": ref,
            "import_sources": [{"artifact": ref, "rows": 1, "control_totals": totals()}],
            "signatories": {role: f"Fixture {role}" for role in contract.FINAL_ROLES},
            "release_authorizer": "Fixture Release Authorizer",
        },
    }


def totals() -> list[dict[str, str]]:
    return [{"metric": "line amount", "expected": "12.50", "observed": "12.50", "unit": "QAR"}]


def heads() -> list[str]:
    return ["202605310005"]


def runtime() -> dict[str, Any]:
    return {
        "schema_heads": heads(),
        "image_digests": {"backend": "sha256:" + "e" * 64, "frontend": "sha256:" + "f" * 64},
        "frontend_sha256": "c" * 64,
        "service_worker_sha256": "d" * 64,
    }


def github_stub(path: str, token: str | None) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = [
        {
            "id": i, "name": name, "head_sha": SHA, "status": "completed",
            "conclusion": "success", "run_id": 11, "run_attempt": 1,
        }
        for i, name in enumerate(sorted(contract.CI_JOBS), 1)
    ]
    if "/jobs?" in path:
        return {"jobs": jobs, "total_count": len(jobs)}
    if "/artifacts?" in path:
        artifacts = []
        for job in jobs:
            fixture = ci_archive_fixture(job["id"], job["name"])
            if fixture is None:
                continue
            name, archive, _ = fixture
            artifacts.append({
                "name": name,
                "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
                "size_in_bytes": len(archive),
                "workflow_run": {"id": 11, "head_sha": SHA, "head_branch": "main"},
            })
        return {"artifacts": artifacts, "total_count": len(artifacts)}
    parts = path.split("/")
    run_id = int(parts[2])
    ci = run_id == 11
    return {
        "id": run_id,
        "head_sha": SHA,
        "head_branch": "main",
        "head_repository": {"full_name": contract.REPOSITORY},
        "path": ".github/workflows/ci.yml" if ci else ".github/workflows/deploy.yml",
        "event": "push" if ci else "workflow_run",
        "status": "completed",
        "conclusion": "success",
        "triggering_actor": {"login": "fixture-deployer"},
        "run_attempt": int(parts[4]) if len(parts) > 3 else 1,
        "run_started_at": (DEPLOYED - timedelta(minutes=1)).isoformat(),
        "updated_at": FINAL_START.isoformat(),
    }


def test_release_dispatch_uses_existing_green_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    def dispatch(path: str, token: str | None) -> dict[str, Any]:
        return {**github_stub(path, token), "event": "workflow_dispatch"}

    monkeypatch.setattr(contract, "github_record", dispatch)
    assert contract.checked_run(12, SHA, None, ci=False)["event"] == "workflow_dispatch"
    with pytest.raises(contract.ContractError, match="GitHub run does not match"):
        contract.checked_run(11, SHA, None, ci=True)


@pytest.mark.parametrize(
    ("run_id", "sha", "status", "expected_operator"),
    [
        (12, SHA, "in_progress", "deploy-operator"),
        (11, SHA, "in_progress", None),
        (12, "0" * 40, "in_progress", None),
        (12, SHA, "completed", None),
    ],
)
def test_operator_comes_from_active_deployment_not_ci(
    monkeypatch: pytest.MonkeyPatch,
    run_id: int,
    sha: str,
    status: str,
    expected_operator: str | None,
) -> None:
    def active_run(path: str, token: str | None) -> dict[str, Any]:
        return {
            **github_stub(path, token),
            "status": status,
            "actor": {"login": "initial-operator"},
            "triggering_actor": {"login": "deploy-operator"},
        }

    monkeypatch.setattr(contract, "github_record", active_run)
    if expected_operator is None:
        with pytest.raises(contract.ContractError, match="GitHub run does not match"):
            contract.deployment_operator(run_id, sha, None)
    else:
        assert contract.deployment_operator(run_id, sha, None) == expected_operator


def ci_archive_fixture(job_id: int, job_name: str) -> tuple[str, bytes, bytes] | None:
    suite = next((name for name, jobs in contract.CI_TEST_JOBS.items() if job_name in jobs), None)
    if suite is None:
        return None
    suffix = f"-{job_name.split(' (')[1][0]}" if suite != "frontend" else ""
    raw = (
        f'<testsuites><testsuite tests="1"><testcase name="test-job-{job_id}"/>'
        "</testsuite></testsuites>"
    ).encode()
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(ZipInfo("frontend.xml" if suite == "frontend" else "test-report.xml"), raw)
    return f"ci-1-{suite}{suffix}", stream.getvalue(), raw


def ci_receipt(bundle: Bundle) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = [
        {
            "id": i,
            "name": name,
            "url": f"{contract.run_url(11)}/job/{i}",
            "conclusion": "success",
        }
        for i, name in enumerate(sorted(contract.CI_JOBS), 1)
    ]
    suites = []
    for suite, names in contract.CI_TEST_JOBS.items():
        reports = []
        for job in jobs:
            if job["name"] not in names:
                continue
            job_id = job["id"]
            fixture = ci_archive_fixture(job_id, job["name"])
            assert fixture is not None
            name, zipped, raw = fixture
            report = bundle.write_bytes(f"artifacts/ci-job-{job_id}.xml", raw)
            archive = bundle.write_bytes(f"artifacts/{name}.zip", zipped)
            bundle.ci_artifacts.append({**report, "sensitivity": "sanitized"})
            bundle.ci_artifacts.append({**archive, "sensitivity": "sanitized"})
            reports.append({"job_id": job_id, "report": report, "archive": archive})
        suites.append(
            {
                "name": suite,
                "passed": len(reports),
                "failed": 0,
                "skipped": 0,
                "warnings": 2 if suite == "backend" else 0,
                "reports": reports,
            }
        )
    return {
        "run_id": 11,
        "run_attempt": 1,
        "run_url": contract.run_url(11),
        "repository": contract.REPOSITORY,
        "ref": "refs/heads/main",
        "conclusion": "success",
        "jobs": jobs,
        "suites": suites,
        "checks": true(
            "lint", "typing", "openapi", "typescript_contract", "frontend_build", "compose"
        ),
    }


@pytest.mark.parametrize(
    "job", ["Browser regressions (1/2)", "Browser regressions (2/2)", "Backend tests (2/2)"]
)
def test_ci_receipt_requires_all_parallel_suites(tmp_path: Path, job: str) -> None:
    bundle = Bundle(tmp_path)
    receipt = ci_receipt(bundle)
    receipt["jobs"] = [row for row in receipt["jobs"] if row["name"] != job]
    with pytest.raises(contract.ContractError, match="Required CI jobs are missing"):
        contract.receipt_ci(receipt, bundle.validator("predeploy").evidence, SHA, None, 11)


def test_ci_receipt_uses_the_recorded_attempt_after_a_failed_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = Bundle(tmp_path)
    receipt = ci_receipt(bundle)
    requested = []

    def runs(path: str, token: str | None) -> dict[str, Any]:
        requested.append(path)
        result = github_stub(path, token)
        if path == "actions/runs/11":
            return {**result, "run_attempt": 2, "conclusion": "failure"}
        return result

    monkeypatch.setattr(contract, "github_record", runs)
    contract.receipt_ci(receipt, bundle.validator("predeploy").evidence, SHA, None, 11)
    assert requested == [
        "actions/runs/11/attempts/1",
        "actions/runs/11/attempts/1/jobs?per_page=100",
        "actions/runs/11/artifacts?per_page=100",
    ]


@pytest.mark.parametrize(("field", "value"), [("run_id", 12), ("run_attempt", 2)])
def test_ci_receipt_rejects_jobs_from_another_run_or_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: int
) -> None:
    bundle = Bundle(tmp_path)

    def runs(path: str, token: str | None) -> dict[str, Any]:
        result = github_stub(path, token)
        if "/jobs?" in path:
            result["jobs"][0][field] = value
        return result

    monkeypatch.setattr(contract, "github_record", runs)
    with pytest.raises(contract.ContractError, match="GitHub jobs differ"):
        contract.receipt_ci(
            ci_receipt(bundle), bundle.validator("predeploy").evidence, SHA, None, 11
        )


def test_junit_counts_derive_results_from_actual_cases() -> None:
    report = b"""<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="4" errors="1" failures="1">
  <testsuite tests="4" errors="1" failures="1" skipped="1">
    <testcase name="pass"/>
    <testcase name="failure"><failure/></testcase>
    <testcase name="error"><error/></testcase>
    <testcase name="skip"><skipped/></testcase>
  </testsuite>
</testsuites>
"""
    assert contract.junit_counts(report) == {"passed": 1, "failed": 2, "skipped": 1}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b'{"passed": 1, "failed": 0, "skipped": 0}', "Invalid JUnit XML"),
        (b"<testsuite", "Invalid JUnit XML"),
        (b"<testsuite tests='1'/>", "JUnit suite totals differ"),
        (b"<testsuites/>", "must contain individual test cases"),
        (
            b"<!DOCTYPE testsuite><testsuite><testcase name='example'/></testsuite>",
            "DTD",
        ),
        (
            b"<testsuite><testcase name='example'><error/><skipped/></testcase></testsuite>",
            "conflicting outcomes",
        ),
    ],
)
def test_junit_rejects_invalid_or_summary_only_xml(raw: bytes, message: str) -> None:
    with pytest.raises(contract.ContractError, match=message):
        contract.junit_counts(raw)


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("substituted-report", "published GitHub archive"),
        ("wrong-archive", "does not match the published GitHub archive"),
        ("unclassified-archive", "archive is missing from the classified receipt artifacts"),
        ("missing-shard", "missing its JUnit report"),
        ("duplicate-job", "unexpected or duplicated"),
        ("wrong-suite", "unexpected or duplicated"),
        ("reused-path", "reused across CI jobs"),
        ("reused-digest", "reused across CI jobs"),
        ("tampered-file", "digest differs"),
        ("unclassified-file", "missing from the classified receipt artifacts"),
        ("incorrect-count", "counts differ from the receipt"),
        ("concealed-failure", "counts differ from the receipt"),
        ("concealed-skip", "counts differ from the receipt"),
    ],
)
def test_ci_receipt_requires_hashed_job_reports_matching_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, message: str
) -> None:
    monkeypatch.setattr(contract, "github_record", github_stub)
    bundle = Bundle(tmp_path)
    receipt = ci_receipt(bundle)
    backend = next(suite for suite in receipt["suites"] if suite["name"] == "backend")
    browser = next(suite for suite in receipt["suites"] if suite["name"] == "browser")
    first, second = backend["reports"]
    artifact_hashes = {artifact["sha256"] for artifact in bundle.ci_artifacts}
    if scenario == "missing-shard":
        backend["reports"].pop()
    elif scenario == "duplicate-job":
        second["job_id"] = first["job_id"]
    elif scenario == "wrong-suite":
        second["job_id"] = browser["reports"][0]["job_id"]
    elif scenario == "reused-path":
        second["report"]["path"] = first["report"]["path"]
    elif scenario == "reused-digest":
        raw = (bundle.root / first["report"]["path"]).read_bytes()
        second["report"] = bundle.write_bytes("artifacts/copied-report.xml", raw)
    elif scenario == "tampered-file":
        path = bundle.root / first["report"]["path"]
        path.write_bytes(path.read_bytes().replace(b"test-job", b"fake-job"))
    elif scenario == "unclassified-file":
        artifact_hashes.remove(first["report"]["sha256"])
    elif scenario == "incorrect-count":
        backend["passed"] += 1
    elif scenario == "substituted-report":
        first["report"] = bundle.write_bytes(
            "artifacts/substitute.xml", b"<testsuite><testcase name='substitute'/></testsuite>"
        )
        artifact_hashes.add(first["report"]["sha256"])
    elif scenario == "wrong-archive":
        first["archive"] = second["archive"]
    elif scenario == "unclassified-archive":
        artifact_hashes.remove(first["archive"]["sha256"])
    else:
        outcome = "error" if scenario == "concealed-failure" else "skipped"
        raw = f'<testsuite><testcase name="altered"><{outcome}/></testcase></testsuite>'.encode()
        first["report"] = bundle.write_bytes("artifacts/altered.xml", raw)
        artifact_hashes.add(first["report"]["sha256"])

    with pytest.raises(contract.ContractError, match=message):
        contract.receipt_ci(
            receipt,
            bundle.validator("predeploy").evidence,
            SHA,
            None,
            11,
            artifact_hashes=artifact_hashes,
        )


def phase_results(
    bundle: Bundle,
    phase: str,
    decisions: dict[str, Any],
    *,
    include_restore_receipt: bool = True,
    restore_override: dict[str, Any] | None = None,
    classify_restore_receipt: bool = True,
    category_override: dict[str, int] | None = None,
) -> dict[str, Any]:
    start = STAGE_START if phase == "predeploy" else FINAL_START
    backup_policy = decisions["D-29-RECOVERY"]
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
    artifact_counts = {
        "application_database": 1,
        "configuration": 1,
        "objects": 1,
        "grafana_database": 0,
    }
    artifact_counts.update(category_override or {})
    manifest_ref = bundle.write(
        f"artifacts/{phase}-backup-manifest.json",
        {
            "format_version": 2,
            "backup_set_id": BACKUP_SET_ID,
            "source_sha": SHA,
            "source_environment": "test",
            "configuration_sha256": CONFIG,
            "policy_sha256": backup_policy["policy_ref"]["sha256"],
            "policy_revision": backup_policy["revision"],
            "alembic_heads": heads(),
            "image_digests": runtime()["image_digests"],
            "snapshot_at_utc": start.isoformat(),
            "objects": [{"key": "fixture/file"}],
            "application_dump": bundle.artifact,
            "configuration_artifacts": [
                {
                    "path": "compose.vps.yml",
                    "plaintext": bundle.artifact,
                    "encrypted": bundle.artifact,
                }
            ],
        },
    )
    auth_ref = bundle.write(
        f"artifacts/{phase}-backup-auth.json",
        {
            "manifest_sha256": manifest_ref["sha256"],
            "key_id": "fixture-key",
            "algorithm": "HMAC-SHA256",
            "signature": "e" * 64,
        },
    )
    publication_ref = bundle.write(
        f"artifacts/{phase}-publication.json",
        {
            "receipt": {
                "backup_set_id": BACKUP_SET_ID,
                "manifest_sha256": manifest_ref["sha256"],
                "snapshot_at_utc": start.isoformat(),
                "remote_verified_at_utc": (start + timedelta(seconds=1)).isoformat(),
                "source_sha": SHA,
                "source_environment": "test",
                "configuration_sha256": CONFIG,
                "policy_revision": backup_policy["revision"],
                "policy_sha256": backup_policy["policy_ref"]["sha256"],
                "destination_identity": backup_policy["destination_identity"],
                "object_count": 1,
                "outcome": "pass",
            },
            "key_id": "fixture-key",
            "algorithm": "HMAC-SHA256",
            "signature": "f" * 64,
        },
    )
    restore_receipt: dict[str, Any] = {}
    if include_restore_receipt:
        original = bundle.write(
            f"artifacts/{phase}-restore.json",
            {
                "operation": "disposable_artifact_restore",
                "outcome": "pass",
                "assurance": "authenticated format 2",
                "source_sha": SHA,
                "backup_set_id": BACKUP_SET_ID,
                "manifest_sha256": manifest_ref["sha256"],
                "configuration_sha256": CONFIG,
                "snapshot_at_utc": start.isoformat(),
                "restore_started_at_utc": (start + timedelta(seconds=4)).isoformat(),
                "database_restored_at_utc": (start + timedelta(seconds=5)).isoformat(),
                "objects_verified_at_utc": (start + timedelta(seconds=6)).isoformat(),
                "expected_migration_heads": heads(),
                "observed_migration_heads": heads(),
                "required_object_count": 1,
                "restored_object_count": 1,
                "restored_category_counts": {
                    "application_database": 1,
                    "configuration": 1,
                    "objects": 1,
                    "grafana_database": 0,
                },
                **(restore_override or {}),
            },
        )
        restore_receipt["restore_receipt"] = original
    bundle.recovery_artifacts[phase] = [
        {**ref, "sensitivity": "sanitized"} for ref in (manifest_ref, auth_ref, publication_ref)
    ]
    if restore_receipt and classify_restore_receipt:
        bundle.recovery_artifacts[phase].append(
            {**restore_receipt["restore_receipt"], "sensitivity": "sanitized"}
        )
    return {
        "retention": {
            "policy_sha256": decisions["D-28-POLICY"]["policy_ref"]["sha256"],
            "mode": "retain_only",
            "purge_enabled": False,
            "legacy_counts": {"total": 0, "resolved": 0, "unknown_preserved": 0, "unresolved": 0},
            "assertions": true(
                "future_protected", "unknown_protected", "archived_queries", "capacity_reviewed"
            ),
        },
        "recovery": {
            **restore_receipt,
            "backup_set_id": BACKUP_SET_ID,
            "manifest_sha256": manifest_ref["sha256"],
            "manifest_auth_sha256": auth_ref["sha256"],
            "publication_sha256": publication_ref["sha256"],
            "policy_sha256": backup_policy["policy_ref"]["sha256"],
            "backup_format_version": 2,
            "destination_identity": backup_policy["destination_identity"],
            "required_object_count": 1,
            "restored_object_count": 1,
            "required_category_counts": artifact_counts,
            "restored_category_counts": artifact_counts,
            "expected_schema_heads": heads(),
            "observed_schema_heads": heads(),
            "control_totals": totals(),
            "second_operator": backup_policy["substitute_operator"],
            "rpo_minutes": 60,
            "rto_minutes": 60,
            "capture_pause_seconds": 4,
            **{
                key: (start + timedelta(seconds=index)).isoformat()
                for index, key in enumerate(times)
            },
            "assertions": true(
                "primary_unavailable",
                "independent_key_access",
                "independent_configuration",
                "independent_destination",
                "authenticated_manifest",
                "object_checksums",
                "business_workflows",
            ),
        },
        "observability": {
            "profile_sha256": decisions["D-30-OPERATIONS"]["profile_ref"]["sha256"],
            "trace_ids": ["fixture-web", "fixture-worker"],
            "alert_events": [
                bundle.alert(
                    rule, start, phase, decisions["D-30-OPERATIONS"]["profile_ref"]["sha256"]
                )
                for rule in sorted(contract.ALERT_RULES)
            ],
            "assertions": true(
                "ingestion", "pipeline_silence", "off_host_failure", "backup_freshness"
            ),
        },
        "uat": {
            "scenarios": bundle.uat(phase, decisions["D-32-SUPPORT"], start),
            "measurements": {"reload_ms": 60},
            "assertions": true("relevant_suite", "independent_controls", "network_profiles"),
        },
    }


def scheduled_observation(
    bundle: Bundle, subject: dict[str, Any], decisions: dict[str, Any]
) -> dict[str, Any]:
    manifest_ref, _, publication_ref, *_ = bundle.recovery_artifacts["final"]
    attempt_ref = bundle.write(
        "artifacts/scheduled-backup-attempt.json",
        {
            "source_sha": SHA,
            "started_at_utc": FINAL_START.isoformat(),
            "completed_at_utc": (FINAL_START + timedelta(seconds=2)).isoformat(),
            "phase": "complete",
            "outcome": "pass",
        },
    )
    checks = []
    for check_id, backup_digest in (("portal", None), ("backup", manifest_ref["sha256"])):
        checks.append(
            {
                "check_id": check_id,
                "result": {
                    "ok": True,
                    "category": "backup_current" if backup_digest else "ready",
                    "status": None if backup_digest else 200,
                    "digest": backup_digest or "a" * 64,
                    "snapshot_at": FINAL_START.isoformat() if backup_digest else None,
                    "attempt_started_at": FINAL_START.isoformat() if backup_digest else None,
                    "attempt_completed_at": (
                        (FINAL_START + timedelta(seconds=2)).isoformat() if backup_digest else None
                    ),
                },
                "event": None,
                "suppressed": False,
                "delivery": "none",
                "message_id": None,
                "acknowledgement": None,
            }
        )
    operations = decisions["D-30-OPERATIONS"]
    monitor_ref = bundle.write(
        "artifacts/scheduled-monitor.json",
        {
            "source_sha": SHA,
            "environment": "test",
            "profile_id": operations["profile_id"],
            "profile_revision": operations["revision"],
            "profile_sha256": operations["profile_ref"]["sha256"],
            "checked_at": (FINAL_START + timedelta(seconds=3)).isoformat(),
            "completed_at": (FINAL_START + timedelta(seconds=4)).isoformat(),
            "executed_by": "Fixture Monitor",
            "observations": checks,
            "transport_ready": True,
        },
    )
    bundle.observation_artifacts = [
        {**ref, "sensitivity": "sanitized"} for ref in (attempt_ref, publication_ref, monitor_ref)
    ]
    return {
        "approved_window_seconds": 300,
        "window_approval": bundle.approval(
            "approve_observation_window",
            contract.canonical_digest(
                {"release_subject_sha256": subject["sha256"], "approved_window_seconds": 300}
            ),
            "operations_owner",
            decisions["D-33-BUSINESS"]["signatories"]["operations_owner"],
            at=STAGE_END,
        ),
        "incidents": [],
        "scheduled_backup": {"attempt_ref": attempt_ref, "publication_ref": publication_ref},
        "scheduled_monitoring": monitor_ref,
    }


def ledger(phase: str) -> list[dict[str, Any]]:
    result = []
    for workstream in sorted(contract.WORKSTREAMS):
        controls = []
        for name in sorted(contract.controls_for(workstream)):
            pending = phase == "predeploy" and name in contract.CONTROL_FINAL_ONLY
            stage = "final" if name in contract.CONTROL_FINAL_ONLY else "predeploy"
            evidence = [f"{stage}-{kind}" for kind in sorted(contract.required_receipt_kinds(name))]
            controls.append(
                {
                    "control_id": name,
                    "status": "pending_live" if pending else "accepted",
                    "receipt_ids": [] if pending else evidence,
                }
            )
        status = (
            "pending_live"
            if any(item["status"] == "pending_live" for item in controls)
            else "accepted"
        )
        result.append({"workstream_id": workstream, "status": status, "controls": controls})
    return result


def reconciliation_inventory(
    bundle: Bundle, population: str, policy_hash: str, *, rows: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    label = population if rows is None else f"{population}-observed"
    if population == "retention":
        reports = [
            bundle.write(
                f"artifacts/retention-{category}.json",
                {
                    "category": category,
                    "cutoff_utc": STAGE_START.isoformat(),
                    "policy_sha256": policy_hash,
                    "counts": {category: 0},
                    "rows": [],
                    "next_after": None,
                },
            )
            for category in ("missing", "unknown", "shorter_than_policy")
        ]
    else:
        reports = [bundle.write(f"artifacts/{label}-report.json", rows or [])]
    ref = bundle.write(
        f"artifacts/{label}-inventory.json",
        {
            "source_sha": SHA,
            "environment": "test",
            "configuration_sha256": CONFIG,
            "population": population,
            "tool": contract.RECONCILIATION_TOOLS[population],
            "started_at": STAGE_START.isoformat(),
            "completed_at": STAGE_END.isoformat(),
            "exit_code": 0,
            "reports": reports,
        },
    )
    bundle.inventory_artifacts.extend(
        {**artifact, "sensitivity": "restricted"} for artifact in [ref, *reports]
    )
    return ref


def manifest(
    bundle: Bundle,
    phase: str = "predeploy",
    *,
    deployment_ci_attempt: int = 1,
    host_receipt_override: dict[str, str] | None = None,
    classify_host_receipt: bool = True,
) -> dict[str, Any]:
    decisions = decision_values(bundle)
    decision_refs = {}
    for key, value in decisions.items():
        payload = {
            **value,
            "decision_id": key,
            "revision": "fixture-v1",
            "approved_at": (NOW - timedelta(minutes=5)).isoformat(),
        }
        if key == "D-28-POLICY":
            policy = {**payload, "schema_version": 1, "approval_ref": "fixture-retention-approval"}
            policy["default_unknown_disposition"] = policy.pop("unknown_disposition")
            payload["policy_ref"] = bundle.write("artifacts/retention-policy.json", policy)
        if key == "D-29-RECOVERY":
            policy = {
                **payload,
                "source_environment": "test",
                "approval_ref": "fixture-recovery-approval",
            }
            payload["policy_ref"] = bundle.write("artifacts/recovery-policy.json", policy)
        if key == "D-30-OPERATIONS":
            transport = {
                "mode": "smtp_tls",
                "sender": "sender@example.test",
                "endpoint": "smtp.example.test:465",
            }
            recipients = {
                "recipients": ["operator@example.test"],
                "escalation_recipients": ["substitute@example.test"],
            }
            payload["transport_ref"] = bundle.write("artifacts/monitor-transport.json", transport)
            payload["recipient_ref"] = bundle.write("artifacts/monitor-recipients.json", recipients)
            profile = {
                **payload,
                "targets": [{"url": url, "check_id": "portal"} for url in payload["targets"]],
                "transport": {**transport, **recipients},
                "backup": {"check_id": "backup"},
            }
            payload["profile_ref"] = bundle.write("artifacts/monitor-profile.json", profile)
        payload["approval_ref"] = bundle.approval(
            key,
            contract.canonical_digest(payload),
            contract.DECISION_ROLES[key],
            f"Fixture Owner {key}",
        )
        decision_refs[key] = bundle.write(f"decisions/{key}.json", payload)
        decisions[key] = payload
    registry = bundle.write("scope/control-registry.json", contract.control_registry())
    subject = bundle.write(
        "release_subject.json",
        {
            "release_id": "fixture-release",
            "repository": contract.REPOSITORY,
            "source_sha": SHA,
            "environment": "test",
            "configuration_sha256": CONFIG,
            "inventory_sha256": bundle.artifact["sha256"],
            "control_registry_sha256": registry["sha256"],
            "decision_sha256": {key: ref["sha256"] for key, ref in decision_refs.items()},
            "support_matrix_sha256": contract.canonical_digest(
                decisions["D-32-SUPPORT"]["scenario_platform_map"]
            ),
            **runtime(),
        },
    )
    approvals: dict[str, Any] = {
        "deployment_authorization": bundle.approval(
            "deployment_authorization",
            subject["sha256"],
            "release_authorizer",
            "Fixture Release Authorizer",
            at=NOW - timedelta(minutes=25),
            source_sha=SHA,
            environment="test",
            valid_from=(NOW - timedelta(minutes=20)).isoformat(),
            valid_until=(NOW + timedelta(minutes=20)).isoformat(),
            authorization_reference="fixture-ticket-17",
        )
    }
    results = phase_results(bundle, "predeploy", decisions)
    business = decisions["D-33-BUSINESS"]
    results.update(
        ci=ci_receipt(bundle),
        data_reconciliation={
            "assignment_sha256": bundle.artifact["sha256"],
            "sample_sha256": {
                key: ref["sha256"] for key, ref in business["accepted_samples"].items()
            },
            "imports": [
                {"source_sha256": bundle.artifact["sha256"], "rows": 1, "control_totals": totals()}
            ],
            "exceptions": {
                population: {
                    "inventory_ref": reconciliation_inventory(
                        bundle, population, decisions["D-28-POLICY"]["policy_ref"]["sha256"]
                    ),
                    "observed_ids": [],
                    "dispositions": [],
                }
                for population in contract.RECONCILIATION_TOOLS
            },
            "assertions": true("least_privilege", "launch_data", "legacy_owner_review"),
        },
    )
    receipts = {
        f"predeploy-{kind}": bundle.receipt(
            kind,
            value,
            executor="Fixture Restore Operator" if kind == "recovery" else "Fixture Executor",
        )
        for kind, value in results.items()
    }
    ledger_ref = bundle.write("ledger.json", ledger(phase))
    defects = bundle.write("defects.json", [])
    result = {
        "format_version": 1,
        "release_id": "fixture-release",
        "repository": contract.REPOSITORY,
        "source_sha": SHA,
        "target_environment": "test",
        "release_subject": subject,
        "scope": {
            "accepted_inventory": bundle.artifact,
            "control_registry": registry,
            "excluded_requirement_ids": ["G-01"],
            "delivery_scope": "launch_readiness_only",
        },
        "decisions": list(decision_refs.values()),
        "ledger": ledger_ref,
        "defects": defects,
        "approvals": approvals,
        "receipts": list(receipts.values()),
        "validation_profile": {
            "validator_version": 1,
            "validator_sha256": hashlib.sha256(Path(contract.__file__).read_bytes()).hexdigest(),
            "control_registry_sha256": registry["sha256"],
        },
    }
    predeploy_payload = dict(result)
    if phase == "final":
        predeploy_payload["ledger"] = bundle.write(
            "ledger-predeploy.json", ledger("predeploy")
        )
    predeploy_manifest = bundle.write("manifests/predeploy.json", predeploy_payload)
    predeploy_verdict = bundle.write(
        "artifacts/PREDEPLOY.json",
        {
            "generated_at": STAGE_END.isoformat(),
            "phase": "predeploy",
            "status": "ready_for_authorized_deployment",
            "accepted_scope_complete": False,
            "ready_for_authorized_deployment": True,
            "source_sha": SHA,
            "target_environment": "test",
            "release_id": "fixture-release",
            "manifest_sha256": predeploy_manifest["sha256"],
            "subject_sha256": subject["sha256"],
            "configuration_sha256": CONFIG,
            "runtime_identity": runtime(),
            "validator_version": 1,
            "validator_sha256": hashlib.sha256(Path(contract.__file__).read_bytes()).hexdigest(),
            "control_registry_sha256": registry["sha256"],
            "trust_registry_sha256": "d" * 64,
            "verified_receipt_ids": sorted(f"predeploy-{kind}" for kind in results),
            "blockers": [],
        },
    )
    bundle.deployment_artifacts.extend(
        [
            {**predeploy_manifest, "sensitivity": "sanitized"},
            {**predeploy_verdict, "sensitivity": "sanitized"},
        ]
    )
    if phase == "final":
        readback = {
            **runtime(),
            "readiness": {"status": "ready", "database": "connected"},
            "services": true("backend", "frontend", "worker", "database", "storage"),
        }
        host_fields = {
            "Status": "Deployed — Formal Acceptance Pending",
            "Commit": SHA,
            "CI run": "11",
            "CI attempt": str(deployment_ci_attempt),
            "Deploy run": "22",
            "Deploy attempt": "1",
            "Predeploy verdict SHA-256": predeploy_verdict["sha256"],
            "Predeploy manifest SHA-256": predeploy_manifest["sha256"],
            "UTC": DEPLOYED.isoformat(),
            "Frontend asset": "/assets/index-fixture.js",
            "Asset SHA-256": readback["frontend_sha256"],
            "Service worker SHA-256": readback["service_worker_sha256"],
            "Backend image": readback["image_digests"]["backend"],
            "Frontend image": readback["image_digests"]["frontend"],
            "Schema heads": " ".join(readback["schema_heads"]) + " ",
            **(host_receipt_override or {}),
        }
        data = "".join(f"{key}: {value}\n" for key, value in host_fields.items())
        host_ref = bundle.write_bytes("artifacts/DEPLOYED", data.encode())
        if classify_host_receipt:
            bundle.deployment_artifacts.append({**host_ref, "sensitivity": "sanitized"})
        final = phase_results(bundle, "final", decisions)
        final.update(
            deployment={
                "run_id": 22,
                "run_url": contract.run_url(22),
                "run_attempt": 1,
                "ci_run_id": 11,
                "ci_run_attempt": deployment_ci_attempt,
                "deployed_at": DEPLOYED.isoformat(),
                "readback": readback,
                "predeploy_manifest": predeploy_manifest,
                "predeploy_verdict": predeploy_verdict,
                "host_receipt": host_ref,
            },
            runtime_readback=readback,
            observation=scheduled_observation(bundle, subject, decisions),
            handover={
                "primary": "Fixture Primary",
                "substitute": "Fixture Substitute",
                "access_verified": True,
                "custody_ref": bundle.artifact,
                "runbook_ref": bundle.artifact,
            },
        )
        receipts.update(
            {
                f"final-{kind}": bundle.receipt(
                    kind,
                    value,
                    "final",
                    start=DEPLOYED if kind == "deployment" else FINAL_START,
                    executor="Fixture Restore Operator"
                    if kind == "recovery"
                    else "Fixture Executor",
                )
                for kind, value in final.items()
            }
        )
        acceptance = bundle.write(
            "acceptance_bundle.json",
            {
                "release_subject_sha256": subject["sha256"],
                "receipt_sha256": {name: ref["sha256"] for name, ref in receipts.items()},
                "ledger_sha256": ledger_ref["sha256"],
                "defects_sha256": defects["sha256"],
            },
        )
        result.update(receipts=list(receipts.values()), acceptance_bundle=acceptance)
        approvals["final_acceptance"] = [
            bundle.approval("final_acceptance", acceptance["sha256"], role, name)
            for role, name in business["signatories"].items()
        ]
    return result


@pytest.mark.parametrize("phase", ["predeploy", "final"])
def test_complete_synthetic_contract_never_claims_live_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    monkeypatch.setattr(contract, "github_record", github_stub)
    bundle = Bundle(tmp_path)
    bundle.write("release_manifest.json", manifest(bundle, phase))
    verdict = bundle.validator(phase).run(bundle.root / "release_manifest.json")
    assert verdict["status"] == "validated_test_evidence"
    assert verdict["accepted_scope_complete"] is False
    assert verdict["ready_for_authorized_deployment"] is False


@pytest.mark.parametrize(
    "field",
    ["manifest_sha256", "runtime_identity", "control_registry_sha256", "verified_receipt_ids"],
)
def test_predeploy_verdict_rejects_unbound_identity_fields(
    tmp_path: Path, field: str
) -> None:
    bundle = Bundle(tmp_path)
    data = manifest(bundle, "final")
    deployment_ref = next(
        ref
        for ref in data["receipts"]
        if json.loads((bundle.root / ref["path"]).read_text())["kind"] == "deployment"
    )
    deployment_receipt = json.loads((bundle.root / deployment_ref["path"]).read_text())
    result = deployment_receipt["results"]
    subject = json.loads((bundle.root / data["release_subject"]["path"]).read_text())
    predeploy_ref = result["predeploy_verdict"]
    verdict = json.loads((bundle.root / predeploy_ref["path"]).read_text())
    manifest_ref = result["predeploy_manifest"]
    predeploy_manifest = json.loads((bundle.root / manifest_ref["path"]).read_text())
    receipt_hashes = contract.verify_predeploy_manifest(
        predeploy_manifest,
        bundle.validator("final").evidence,
        release_id="fixture-release",
        source_sha=SHA,
        target_environment="test",
        subject_sha256=data["release_subject"]["sha256"],
        configuration_sha256=CONFIG,
        inventory_sha256=data["scope"]["accepted_inventory"]["sha256"],
        control_registry_sha256=data["scope"]["control_registry"]["sha256"],
        decision_sha256=subject["decision_sha256"],
        validator_sha256=hashlib.sha256(Path(contract.__file__).read_bytes()).hexdigest(),
    )
    verdict[field] = {
        "manifest_sha256": "f" * 64,
        "runtime_identity": {**runtime(), "schema_heads": ["other-head"]},
        "control_registry_sha256": "e" * 64,
        "verified_receipt_ids": ["unapproved-receipt"],
    }[field]

    with pytest.raises(contract.ContractError, match="matching successful predeployment verdict"):
        contract.verify_predeploy_verdict(
            verdict,
            SHA,
            "fixture-release",
            "test",
            data["release_subject"]["sha256"],
            CONFIG,
            manifest_ref["sha256"],
            runtime(),
            data["scope"]["control_registry"]["sha256"],
            sorted(receipt_hashes),
            hashlib.sha256(Path(contract.__file__).read_bytes()).hexdigest(),
            DEPLOYED,
        )


@pytest.mark.parametrize(
    ("problem", "reason"),
    [
        ("missing", "Missing alert delivery evidence"),
        ("wrong-profile", "differs from the reviewed rule, route or recipient"),
        ("unclassified", "must be classified artifacts"),
        ("early-resolution", "outside its execution window"),
        ("reused-id", "must have distinct delivery evidence"),
        ("reused-receipt", "must have distinct delivery evidence"),
        ("wrong-destination", "for the same destination"),
        ("unapproved-destination", "use an unapproved monitor destination"),
        ("ack-before-receipt", "acknowledgement exceeded the approved bound"),
    ],
)
def test_observability_requires_matching_firing_and_resolution_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str, reason: str
) -> None:
    class AlertBundle(Bundle):
        def alert(
            self, name: str, start: datetime, phase: str, profile_hash: str
        ) -> dict[str, Any]:
            result = super().alert(name, start, phase, profile_hash)
            if problem == "missing":
                del result["resolution_delivery"]
                return result
            if problem == "unclassified":
                self.alert_artifacts[phase].pop()
                return result
            if problem == "unapproved-destination":
                for key in ("firing_delivery", "resolution_delivery"):
                    original = result[key]
                    path = original["path"]
                    record = json.loads((self.root / path).read_text())
                    record["destination"] = "unapproved@example.test"
                    ref = self.write(path, record)
                    artifacts = self.alert_artifacts[phase]
                    artifacts[:] = [a for a in artifacts if a["sha256"] != original["sha256"]]
                    artifacts.append({**ref, "sensitivity": "sanitized"})
                    result[key] = ref
                return result
            key = "firing_delivery" if problem == "ack-before-receipt" else "resolution_delivery"
            original = result[key]
            path = original["path"]
            record = json.loads((self.root / path).read_text())
            firing = json.loads(
                (self.root / result["firing_delivery"]["path"]).read_text()
            )
            field, value = {
                "wrong-profile": ("profile_sha256", "0" * 64),
                "early-resolution": ("received_at", start.isoformat()),
                "reused-id": ("message_id", firing["message_id"]),
                "reused-receipt": ("receipt_ref", firing["receipt_ref"]),
                "wrong-destination": ("destination", "other@example.test"),
                "ack-before-receipt": (
                    "received_at", (start + timedelta(seconds=6)).isoformat()
                ),
            }[problem]
            record[field] = value
            ref = self.write(path, record)
            artifacts = self.alert_artifacts[phase]
            artifacts[:] = [a for a in artifacts if a["sha256"] != original["sha256"]]
            artifacts.append({**ref, "sensitivity": "sanitized"})
            result[key] = ref
            return result

    monkeypatch.setattr(contract, "github_record", github_stub)
    bundle = AlertBundle(tmp_path)
    bundle.write("release_manifest.json", manifest(bundle, "final"))

    with pytest.raises(contract.ContractError, match=reason):
        bundle.validator("final").run(bundle.root / "release_manifest.json")


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("sender", "other-sender@example.test"),
        ("endpoint", "other.example.test:465"),
        ("recipients", ["unapproved@example.test"]),
        ("escalation_recipients", ["unapproved@example.test"]),
    ],
)
def test_operations_rejects_profile_drift_from_the_approved_contact_route(
    tmp_path: Path, field: str, replacement: str | list[str]
) -> None:
    bundle = Bundle(tmp_path)
    decisions = manifest(bundle)["decisions"]
    operation_ref = next(ref for ref in decisions if ref["path"].endswith("D-30-OPERATIONS.json"))
    operation = json.loads((bundle.root / operation_ref["path"]).read_text())
    profile = json.loads((bundle.root / operation["profile_ref"]["path"]).read_text())
    delivery = {
        "mode": "smtp_tls",
        "sender": "sender@example.test",
        "endpoint": "smtp.example.test:465",
    }
    recipients = {
        "recipients": ["operator@example.test"],
        "escalation_recipients": ["substitute@example.test"],
    }
    operation["transport_ref"] = bundle.write("transport.json", delivery)
    operation["recipient_ref"] = bundle.write("recipients.json", recipients)
    profile["transport"] = {**delivery, **recipients, field: replacement}
    operation["profile_ref"] = bundle.write("effective-profile.json", profile)

    with pytest.raises(contract.ContractError, match="differs from the approved contact route"):
        contract.decision_operations(operation, "test", bundle.validator("predeploy").evidence)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"include_restore_receipt": False}, "Missing restore command receipt"),
        ({"classify_restore_receipt": False}, "Restore command receipt must be classified"),
        (
            {"restore_override": {"assurance": "legacy checksum-only format 1"}},
            "authenticated restore",
        ),
        ({"restore_override": {"manifest_sha256": "f" * 64}}, "different backup or release"),
        ({"restore_override": {"configuration_sha256": "f" * 64}}, "different backup or release"),
        (
            {"restore_override": {"observed_migration_heads": ["other"]}},
            "reviewed recovery summary",
        ),
        ({"restore_override": {"restored_object_count": 0}}, "reviewed recovery summary"),
        ({"category_override": {"configuration": 2}}, "manifest category counts"),
        ({"category_override": {"objects": 0}}, "manifest category counts"),
        ({"category_override": {"grafana_database": 1}}, "manifest category counts"),
        (
            {
                "restore_override": {
                    "restored_category_counts": {
                        "application_database": 1,
                        "configuration": 0,
                        "objects": 1,
                        "grafana_database": 0,
                    }
                }
            },
            "Restore command category counts",
        ),
        (
            {"restore_override": {"objects_verified_at_utc": NOW.isoformat()}},
            "reviewed recovery summary",
        ),
    ],
)
def test_recovery_requires_matching_restore_command_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any], reason: str
) -> None:
    monkeypatch.setattr(contract, "github_record", github_stub)
    bundle = Bundle(tmp_path)
    data = manifest(bundle)
    decisions = {}
    for ref in data["decisions"]:
        row = json.loads((bundle.root / ref["path"]).read_text())
        decisions[row["decision_id"]] = row
    result = phase_results(bundle, "predeploy", decisions, **overrides)["recovery"]
    ref = bundle.receipt("recovery", result, executor="Fixture Restore Operator")
    data["receipts"] = [
        ref if item["path"] == ref["path"] else item for item in data["receipts"]
    ]
    bundle.write("release_manifest.json", data)

    with pytest.raises(contract.ContractError, match=reason):
        bundle.validator("predeploy").run(bundle.root / "release_manifest.json")


def test_final_requires_the_ci_attempt_used_by_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract, "github_record", github_stub)
    bundle = Bundle(tmp_path)
    bundle.write("release_manifest.json", manifest(bundle, "final", deployment_ci_attempt=2))

    with pytest.raises(
        contract.ContractError, match="Deployment did not use the accepted CI attempt"
    ):
        bundle.validator("final").run(bundle.root / "release_manifest.json")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("Commit", "b" * 40, "Host deployment receipt differs"),
        ("CI attempt", "2", "Host deployment receipt differs"),
        ("Deploy attempt", "2", "Host deployment receipt differs"),
        ("Service worker SHA-256", "e" * 64, "Host deployment receipt differs"),
        ("Backend image", "sha256:" + "f" * 64, "Host deployment receipt differs"),
        ("Schema heads", "other", "Host deployment receipt differs"),
        ("UTC", NOW.isoformat(), "Host deployment receipt differs"),
        ("Frontend asset", "/assets/../index-fixture.js", "Invalid host deployment frontend asset"),
        ("CI run", "11\nCI run: 11", "duplicate host deployment receipt field"),
    ],
)
def test_final_rejects_a_mismatched_or_malformed_host_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str, reason: str
) -> None:
    monkeypatch.setattr(contract, "github_record", github_stub)
    bundle = Bundle(tmp_path)
    bundle.write(
        "release_manifest.json",
        manifest(bundle, "final", host_receipt_override={field: value}),
    )

    with pytest.raises(contract.ContractError, match=reason):
        bundle.validator("final").run(bundle.root / "release_manifest.json")


def test_final_requires_the_host_receipt_as_a_classified_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract, "github_record", github_stub)
    bundle = Bundle(tmp_path)
    bundle.write("release_manifest.json", manifest(bundle, "final", classify_host_receipt=False))

    with pytest.raises(contract.ContractError, match="must be a classified artifact"):
        bundle.validator("final").run(bundle.root / "release_manifest.json")


@pytest.mark.parametrize(
    ("operator", "reason"),
    [
        ("fixture release authorizer", "cannot authorize their own deployment"),
        ("fixture FINANCE_DATA_OWNER", "A final approval is duplicated, unauthorized"),
    ],
)
def test_final_uses_actual_deployment_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operator: str, reason: str
) -> None:
    def deployment_run(path: str, token: str | None) -> dict[str, Any]:
        run = github_stub(path, token)
        if path == "actions/runs/22/attempts/1":
            run["triggering_actor"] = {"login": operator}
        return run

    monkeypatch.setattr(contract, "github_record", deployment_run)
    bundle = Bundle(tmp_path)
    bundle.write("release_manifest.json", manifest(bundle, "final"))
    with pytest.raises(contract.ContractError, match=reason):
        bundle.validator("final").run(bundle.root / "release_manifest.json")


def test_final_rejects_activation_before_the_verified_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deployment_run(path: str, token: str | None) -> dict[str, Any]:
        run = github_stub(path, token)
        if path == "actions/runs/22/attempts/1":
            run["run_started_at"] = (DEPLOYED + timedelta(seconds=1)).isoformat()
        return run

    monkeypatch.setattr(contract, "github_record", deployment_run)
    bundle = Bundle(tmp_path)
    bundle.write("release_manifest.json", manifest(bundle, "final"))
    with pytest.raises(contract.ContractError, match="Deployment occurred outside"):
        bundle.validator("final").run(bundle.root / "release_manifest.json")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("short window", "Invalid approved observation window"),
        ("missing evidence", "Scheduled activity must be attached"),
        ("different backup", "Backup freshness did not verify the observed scheduled backup"),
        ("transport unavailable", "Scheduled monitor notification transport was unavailable"),
        ("transport omitted", "Scheduled monitor notification transport was unavailable"),
        ("unverified readiness", "Scheduled readiness was not verified"),
        ("missing attempt identity", "Backup freshness did not verify"),
        ("different attempt", "Backup freshness did not verify the observed scheduled backup"),
    ],
)
def test_final_requires_scheduled_activity_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str, reason: str
) -> None:
    monkeypatch.setattr(contract, "github_record", github_stub)
    bundle = Bundle(tmp_path)
    data = manifest(bundle, "final")
    index, ref = next(
        (index, ref)
        for index, ref in enumerate(data["receipts"])
        if ref["path"].endswith("/final-observation.json")
    )
    result = json.loads((bundle.root / ref["path"]).read_text())["results"]
    if change == "short window":
        result["approved_window_seconds"] = 60
    elif change == "missing evidence":
        bundle.observation_artifacts.pop()
    else:
        monitor_ref = result["scheduled_monitoring"]
        monitor = json.loads((bundle.root / monitor_ref["path"]).read_text())
        if change == "transport unavailable":
            monitor["transport_ready"] = False
        elif change == "transport omitted":
            monitor.pop("transport_ready", None)
        elif change == "unverified readiness":
            monitor["observations"][0]["result"]["status"] = 503
        elif change == "missing attempt identity":
            del monitor["observations"][1]["result"]["attempt_completed_at"]
        elif change == "different attempt":
            monitor["observations"][1]["result"]["attempt_completed_at"] = (
                FINAL_START + timedelta(seconds=3)
            ).isoformat()
        else:
            monitor["observations"][1]["result"]["digest"] = "0" * 64
        result["scheduled_monitoring"] = bundle.write(monitor_ref["path"], monitor)
        bundle.observation_artifacts[-1] = {
            **result["scheduled_monitoring"],
            "sensitivity": "sanitized",
        }
    data["receipts"][index] = bundle.receipt("observation", result, "final")
    bundle.write("release_manifest.json", data)
    with pytest.raises(contract.ContractError, match=reason):
        bundle.validator("final").run(bundle.root / "release_manifest.json")


@pytest.mark.parametrize(
    ("status", "problem", "reason"),
    [
        ("protected_exception", "", ""),
        ("protected_exception", "missing", "unresolved case"),
        ("protected_exception", "wrong owner", "named owner approval"),
        ("protected_exception", "omitted finding", "differ from the attached read-only findings"),
        ("repaired", "", ""),
        ("repaired", "different plan", "approved plan, backup, or execution window"),
    ],
)
def test_reconciliation_checks_owner_disposition_and_repair(
    tmp_path: Path, status: str, problem: str, reason: str
) -> None:
    bundle = Bundle(tmp_path)
    data = manifest(bundle)
    business = json.loads((bundle.root / "decisions/D-33-BUSINESS.json").read_text())
    retention = json.loads((bundle.root / "decisions/D-28-POLICY.json").read_text())
    policy_hash = retention["policy_ref"]["sha256"]
    reference = next(
        ref
        for ref in data["receipts"]
        if ref["path"].endswith("/predeploy-data_reconciliation.json")
    )
    result = json.loads((bundle.root / reference["path"]).read_text())["results"]
    identity = {"source_sha": SHA, "environment": "test", "configuration_sha256": CONFIG}
    population = result["exceptions"]["payments"]
    inventory = reconciliation_inventory(
        bundle, "payments", policy_hash, rows=[{"invoice_id": "fixture-invoice"}]
    )
    population["inventory_ref"] = inventory
    population["observed_ids"] = [] if problem == "omitted finding" else ["fixture-invoice"]
    disposition = {
        "exception_id": "fixture-invoice",
        "status": status,
        "reason": "Fixture owner disposition with reviewed evidence",
        "evidence_ref": bundle.artifact,
    }
    if status == "repaired":
        scope = {
            **identity,
            "population": "payments",
            "exception_id": "fixture-invoice",
            "plan_sha256": bundle.artifact["sha256"],
            "backup_sha256": bundle.artifact["sha256"],
        }
        authorization = bundle.approval(
            "data_repair",
            contract.canonical_digest(scope),
            "finance_data_owner",
            business["signatories"]["finance_data_owner"],
            at=STAGE_START - timedelta(minutes=1),
            source_sha=SHA,
            environment="test",
            valid_from=STAGE_START.isoformat(),
            valid_until=STAGE_END.isoformat(),
            authorization_reference="fixture-repair-approval",
        )
        execution = {
            **scope,
            "authorization_sha256": authorization["sha256"],
            "outcome": "pass",
            "started_at": STAGE_START.isoformat(),
            "completed_at": (STAGE_START + timedelta(minutes=1)).isoformat(),
        }
        if problem == "different plan":
            execution["plan_sha256"] = "0" * 64
        disposition["repair"] = {
            "plan_ref": bundle.artifact,
            "backup_ref": bundle.artifact,
            "authorization_ref": authorization,
            "execution_ref": bundle.write("artifacts/repair.json", execution),
        }
    if problem != "missing":
        disposition["approval_ref"] = bundle.approval(
            "legacy_exception_disposition",
            contract.canonical_digest(
                {
                    **identity,
                    "population": "payments",
                    "inventory_sha256": inventory["sha256"],
                    "disposition": disposition,
                }
            ),
            "finance_data_owner",
            "Other Fixture Owner"
            if problem == "wrong owner"
            else business["signatories"]["finance_data_owner"],
        )
        population["dispositions"] = [disposition]

    def validate() -> None:
        contract.receipt_reconciliation(
            result,
            business,
            "Fixture Records Owner",
            bundle.validator("predeploy").approvals,
            identity,
            {ref["sha256"] for ref in bundle.inventory_artifacts},
            policy_hash,
            (STAGE_START, STAGE_END),
        )

    if reason:
        with pytest.raises(contract.ContractError, match=reason):
            validate()
    else:
        validate()


def test_retention_inventory_requires_all_pages_for_each_exception_category() -> None:
    policy_hash = "a" * 64
    cutoff = STAGE_START.isoformat()
    pages = [
        {
            "category": category,
            "cutoff_utc": cutoff,
            "policy_sha256": policy_hash,
            "counts": {category: 2 if category == "missing" else 0},
            "rows": [{"id": "fixture-001"}] if category == "missing" else [],
            "next_after": "fixture-001" if category == "missing" else None,
        }
        for category in ("missing", "unknown", "shorter_than_policy")
    ]
    with pytest.raises(contract.ContractError, match="Retention exception inventory is incomplete"):
        contract.retention_exception_ids(pages, policy_hash, STAGE_END)
    pages.append({**pages[0], "rows": [{"id": "fixture-002"}], "next_after": None})
    assert contract.retention_exception_ids(pages, policy_hash, STAGE_END) == {
        "fixture-001", "fixture-002"
    }


def test_uat_matrix_requires_the_specified_role_on_desktop(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path)
    matrix = decision_values(bundle)["D-32-SUPPORT"]["scenario_platform_map"]
    desktop = matrix["UAT-07"][0]
    assert desktop == {"platform": "desktop", "role": "civil_supervisor"}
    desktop["role"] = "operator"
    with pytest.raises(contract.ContractError, match="Mandatory UAT role omitted for UAT-07"):
        contract.scenario_matrix(matrix)


def test_uat_support_requires_chrome_and_edge_only(tmp_path: Path) -> None:
    support = decision_values(Bundle(tmp_path))["D-32-SUPPORT"]
    contract.decision_support(support)
    assert contract.required_platforms("UAT-21") == {"desktop"}
    assert contract.required_platforms("UAT-40") == {"desktop", "operations"}
    with pytest.raises(contract.ContractError, match="must include Chrome and Edge"):
        contract.decision_support({**support, "desktop_targets": [device("desktop", "Chrome")]})
    with pytest.raises(contract.ContractError, match="desktop browser"):
        extra_targets = support["desktop_targets"] + [device("desktop", "Firefox")]
        contract.decision_support({**support, "desktop_targets": extra_targets})
    with pytest.raises(contract.ContractError, match="Physical mobile targets"):
        contract.decision_support({**support, "physical_mobile_targets": [device("ios", "Safari")]})
    support["scenario_platform_map"]["UAT-21"].append(
        {"platform": "android", "role": "civil_engineer"}
    )
    with pytest.raises(contract.ContractError, match="scenario platform"):
        contract.decision_support(support)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("valid", ""),
        ("missing", "separate exact-policy purge authorization"),
        ("different policy", "separate exact-policy purge authorization"),
        ("expired", "Scheduled expiry authorization differs"),
    ],
)
def test_scheduled_expiry_requires_separate_bound_authorization(
    tmp_path: Path, change: str, reason: str
) -> None:
    bundle = Bundle(tmp_path)
    policy_hash = "e" * 64
    approval = bundle.approval(
        "purge",
        contract.canonical_digest(
            {
                "source_sha": SHA,
                "environment": "production",
                "configuration_sha256": CONFIG,
                "policy_sha256": "f" * 64 if change == "different policy" else policy_hash,
            }
        ),
        "release_authorizer",
        "Fixture Release Authorizer",
        at=NOW - timedelta(minutes=5),
        source_sha=SHA,
        environment="production",
        valid_from=(NOW - timedelta(minutes=4)).isoformat(),
        valid_until=(NOW + timedelta(minutes=-1 if change == "expired" else 5)).isoformat(),
        authorization_reference="fixture-separate-purge-approval",
    )
    verifier = bundle.validator("predeploy")
    verifier.target = "production"
    verifier.configuration = CONFIG
    verifier.decisions = {
        "D-28-POLICY": {"policy_ref": {"sha256": policy_hash}, "mode": "scheduled_expiry"},
        "D-33-BUSINESS": {"release_authorizer": "Fixture Release Authorizer"},
    }
    refs = [] if change == "missing" else [approval]
    if reason:
        with pytest.raises(contract.ContractError, match=reason):
            verifier.validate_operations(refs)
    else:
        verifier.validate_operations(refs)


def test_staging_is_not_a_release_acceptance_target(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path)
    with pytest.raises(contract.ContractError, match="target environment"):
        bundle.validator("predeploy", target="staging")


@pytest.mark.parametrize("kind", ["recovery", "observability"])
def test_production_predeploy_receipts_use_production_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    bundle = Bundle(tmp_path)
    validator = bundle.validator("predeploy")
    validator.target = "production"
    validator.configuration = CONFIG
    validator.identity = {"schema_heads": ["fixture-head"]}
    validator.decisions = {
        "D-29-RECOVERY": {"policy_ref": {"sha256": "c" * 64}},
        "D-30-OPERATIONS": {"profile_ref": bundle.artifact},
    }
    start, end = STAGE_START, STAGE_END
    production_receipt_id = f"production-{kind}"
    raw = {
        "receipt_id": production_receipt_id,
        "kind": kind,
        "phase": "predeploy",
        "source_sha": SHA,
        "environment": "production",
        "configuration_sha256": CONFIG,
        "synthetic": False,
        "started_at": start.isoformat(),
        "completed_at": end.isoformat(),
        "executed_by": "Fixture Executor",
        "tool": "fixture check",
        "outcome": "pass",
        "results": {},
        "artifacts": [],
        "review": bundle.artifact,
    }

    def load_receipt(ref: Any, *, parse: bool = False) -> dict[str, Any]:
        return raw

    def artifact_hashes(refs: Any, label: str) -> set[str]:
        return set()

    def verify_approval(
        ref: Any, purpose: str, subject: str, *, role: str | None = None
    ) -> dict[str, Any]:
        return {
            "approver_identity": "Fixture Reviewer",
            "approved_at": NOW.isoformat(),
        }

    monkeypatch.setattr(validator.evidence, "load", load_receipt)
    monkeypatch.setattr(validator.evidence, "artifacts", artifact_hashes)
    monkeypatch.setattr(validator.approvals, "check", verify_approval)
    monkeypatch.setattr(contract, "check_execution", lambda *args, **kwargs: (start, end))
    monkeypatch.setattr(contract, "receipt_recovery", lambda *args, **kwargs: None)
    monkeypatch.setattr(contract, "verify_recovery_artifacts", lambda *args, **kwargs: None)
    monkeypatch.setattr(contract, "receipt_observability", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        contract,
        "monitor_contact_route",
        lambda profile: (None, {"recipients": []}),
    )

    validator.validate_receipt(bundle.artifact)
    assert validator.receipts[production_receipt_id]["environment"] == "production"

    validator.receipts.clear()
    raw["receipt_id"] = f"staging-{kind}"
    raw["environment"] = "staging"
    raw["configuration_sha256"] = "a" * 64
    with pytest.raises(contract.ContractError, match="Receipt source, environment"):
        validator.validate_receipt(bundle.artifact)


@pytest.mark.parametrize(
    ("mutation", "code", "reason"),
    [
        ("unknown field", 2, "manifest fields"),
        ("wrong commit", 3, "differs"),
        ("missing decision", 3, "mandatory owner decision"),
        ("wrong configuration", 3, "host configuration"),
        ("untrusted approval", 3, "independent verification"),
        ("missing authorization", 2, "release approvals"),
        ("wrong authorization SHA", 3, "named authority"),
        ("expired authorization", 3, "not currently valid"),
        ("actor is authorizer", 3, "named authority"),
        ("unverified CI", 5, "credentials"),
        ("predeploy only", 3, "required receipt"),
        ("unsafe path", 2, "Unsafe evidence path"),
        ("tampered file", 3, "size differs"),
        ("duplicate ledger", 2, "Duplicate workstream"),
        ("irrelevant receipt", 3, "relevant phase-specific receipts"),
        ("unsigned publication", 3, "publication must be verified artifacts"),
        ("empty scenario", 3, "UAT scenario results"),
        ("missing Edge result", 3, "required UAT scenario, platform or role"),
    ],
)
def test_strict_gate_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    code: int,
    reason: str,
) -> None:
    if mutation != "unverified CI":
        monkeypatch.setattr(contract, "github_record", github_stub)
    bundle = Bundle(tmp_path)
    data = manifest(bundle)
    expected: dict[str, Any] = {}
    phase = "predeploy"
    if mutation == "unknown field":
        data["complete"] = True
    elif mutation == "wrong commit":
        data["source_sha"] = "0" * 40
    elif mutation == "missing decision":
        data["decisions"].pop()
    elif mutation == "wrong configuration":
        expected["expected_config"] = "0" * 64
    elif mutation == "untrusted approval":
        bundle.approvals.pop(data["approvals"]["deployment_authorization"]["sha256"])
    elif mutation == "missing authorization":
        data["approvals"].clear()
    elif mutation in {"wrong authorization SHA", "expired authorization"}:
        data["approvals"]["deployment_authorization"] = bundle.approval(
            "deployment_authorization",
            data["release_subject"]["sha256"],
            "release_authorizer",
            "Fixture Release Authorizer",
            at=NOW - timedelta(minutes=25),
            source_sha="0" * 40 if mutation == "wrong authorization SHA" else SHA,
            environment="test",
            valid_from=(NOW - timedelta(minutes=20)).isoformat(),
            valid_until=(
                NOW + timedelta(minutes=-1 if mutation == "expired authorization" else 20)
            ).isoformat(),
            authorization_reference="fixture-ticket-18",
        )
    elif mutation == "actor is authorizer":
        expected["actor"] = "fixture RELEASE authorizer"
    elif mutation == "predeploy only":
        phase = "final"
    elif mutation == "unsafe path":
        data["release_subject"]["path"] = "../release_subject.json"
    elif mutation == "tampered file":
        (bundle.root / data["release_subject"]["path"]).write_text("{}")
    elif mutation == "duplicate ledger":
        rows = ledger(phase)
        rows.append(rows[0])
        data["ledger"] = bundle.write("ledger.json", rows)
    elif mutation == "irrelevant receipt":
        rows = ledger(phase)
        next(row for row in rows if row["workstream_id"] == "G-28")["controls"][0][
            "receipt_ids"
        ] = ["predeploy-uat"]
        data["ledger"] = bundle.write("ledger.json", rows)
    elif mutation == "unsigned publication":
        bundle.recovery_artifacts["predeploy"] = [
            ref
            for ref in bundle.recovery_artifacts["predeploy"]
            if not ref["path"].endswith("-publication.json")
        ]
        for index, ref in enumerate(data["receipts"]):
            if ref["path"].endswith("predeploy-recovery.json"):
                receipt = json.loads((bundle.root / ref["path"]).read_text())
                data["receipts"][index] = bundle.receipt(
                    "recovery", receipt["results"], executor=receipt["executed_by"]
                )
    elif mutation in {"empty scenario", "missing Edge result"}:
        for index, ref in enumerate(data["receipts"]):
            if ref["path"].endswith("predeploy-uat.json"):
                content = json.loads((bundle.root / ref["path"]).read_text())
                scenarios = content["results"]["scenarios"]
                if mutation == "empty scenario":
                    scenarios.clear()
                else:
                    edge_result = next(
                        row for row in scenarios if row["device"]["browser"] == "Edge"
                    )
                    scenarios.remove(edge_result)
                data["receipts"][index] = bundle.receipt("uat", content["results"])
    bundle.write("release_manifest.json", data)
    with pytest.raises(contract.ContractError, match=reason) as failed:
        bundle.validator(phase, **expected).run(bundle.root / "release_manifest.json")
    assert failed.value.code == code


def test_symlinked_evidence_rejected_even_with_matching_hash(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path)
    path = bundle.root / bundle.artifact["path"]
    target = bundle.root.parent / "external"
    path.replace(target)
    path.symlink_to(target)
    with pytest.raises(contract.ContractError, match="opened safely") as failed:
        contract.Evidence(bundle.root, protected=False).load(bundle.artifact)
    assert failed.value.code == 2


def test_strict_cli_disallows_explicit_environment_sha_conflict() -> None:
    args = argparse.Namespace(phase="predeploy", commit=SHA, target="production")
    verdict, code = strict_verdict(args, {"GITHUB_SHA": "b" * 40})
    assert code == 3
    assert verdict["accepted_scope_complete"] is False


def test_host_configuration_digest_binds_host_release_and_external_file_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "deploy"
    state.mkdir()
    external_contents = {
        "secrets/jwt_private_key": b"private-key-fixture",
        "secrets/jwt_public_key": b"public-key-fixture",
        "releases/cert/nginx/ssl/fullchain.pem": b"certificate-fixture",
        "releases/cert/nginx/ssl/privkey.pem": b"private-key-fixture-2",
    }
    files = {
        "host/production.env": hashlib.sha256(b"LOG_PURGE_ENABLED=false\n").hexdigest(),
        "host/compose.vps.yml": hashlib.sha256(b"services: {}\n").hexdigest(),
        **{
            f"release/{name}": hashlib.sha256(name.encode()).hexdigest()
            for name in contract.RELEASE_CONFIGURATION_FILES
        },
        **{
            f"external/{name}": hashlib.sha256(content).hexdigest()
            for name, content in external_contents.items()
        },
    }
    expected = contract.canonical_digest(files)
    profile = {"configuration_sha256": expected, "files": files}
    monkeypatch.setattr(contract, "json_file", lambda path, protected: (profile, "fixture"))

    @contextmanager
    def open_fixture(path: Path, *, protected: bool = False):
        try:
            relative = path.relative_to(state).as_posix()
            content = {
                "production.env": b"LOG_PURGE_ENABLED=false\n",
                "compose.vps.yml": b"services: {}\n",
            }[relative]
        except (KeyError, ValueError):
            relative = path.relative_to(tmp_path).as_posix()
            content = external_contents[relative]
        yield BytesIO(content)

    monkeypatch.setattr(contract, "open_evidence", open_fixture)
    assert contract.host_configuration(state) == expected

    profile["configuration_sha256"] = "f" * 64
    with pytest.raises(contract.ContractError, match="does not match its protected file hashes"):
        contract.host_configuration(state)

    profile["configuration_sha256"] = expected
    files["host/production.env"] = hashlib.sha256(b"LOG_PURGE_ENABLED=true\n").hexdigest()
    with pytest.raises(contract.ContractError, match="deployment setting differs"):
        contract.host_configuration(state)


def test_host_configuration_rejects_missing_runtime_or_external_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {
        "host/production.env": hashlib.sha256(b"LOG_PURGE_ENABLED=false\n").hexdigest(),
        "host/compose.vps.yml": hashlib.sha256(b"services: {}\n").hexdigest(),
    }
    profile = {"configuration_sha256": contract.canonical_digest(files), "files": files}
    monkeypatch.setattr(contract, "json_file", lambda path, protected: (profile, "fixture"))

    @contextmanager
    def open_fixture(path: Path, *, protected: bool = False):
        yield BytesIO(
            b"LOG_PURGE_ENABLED=false\n"
            if path.name == "production.env"
            else b"services: {}\n"
        )

    monkeypatch.setattr(contract, "open_evidence", open_fixture)
    with pytest.raises(contract.ContractError, match="complete release configuration set"):
        contract.host_configuration(tmp_path / "deploy")


def test_candidate_configuration_verification_matches_compose_mounts_without_emitting_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    portal = tmp_path / "portal"
    state = portal / "deploy"
    candidate = portal / "releases" / "candidate"
    state.mkdir(parents=True)
    candidate.mkdir(parents=True)
    host_contents = {
        "production.env": b"LOG_PURGE_ENABLED=false\nSECRET_VALUE=not-for-output\n",
        "compose.vps.yml": b"services: {}\n",
    }
    for name, content in host_contents.items():
        (state / name).write_bytes(content)
    (candidate / ".env").write_bytes(host_contents["production.env"])
    release_contents: dict[str, bytes] = {}
    mounts: list[dict[str, str]] = []
    for name in sorted(contract.RELEASE_CONFIGURATION_FILES):
        content = f"config fixture: {name}\n".encode()
        target = candidate / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        release_contents[name] = content
        if name not in {
            "docker-compose.prod.yml",
            "observability/grafana/contact-points/usesend.yml",
        }:
            mounts.append({
                "type": "bind",
                "source": str(target),
                "target": f"/mounted/{len(mounts)}",
            })

    external_contents = {
        "secrets/jwt_private_key": b"private-key-fixture",
        "secrets/jwt_public_key": b"public-key-fixture",
        "releases/cert/nginx/ssl/fullchain.pem": b"certificate-fixture",
        "releases/cert/nginx/ssl/privkey.pem": b"private-key-fixture-2",
    }
    for name, content in external_contents.items():
        target = portal / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        mounts.append({"type": "bind", "source": str(target), "target": f"/external/{name}"})

    file_map = {
        **{
            f"host/{name}": hashlib.sha256(content).hexdigest()
            for name, content in host_contents.items()
        },
        **{
            f"release/{name}": hashlib.sha256(content).hexdigest()
            for name, content in release_contents.items()
        },
        **{
            f"external/{name}": hashlib.sha256(content).hexdigest()
            for name, content in external_contents.items()
        },
    }
    profile = {"configuration_sha256": contract.canonical_digest(file_map), "files": file_map}
    monkeypatch.setattr(contract, "json_file", lambda path, protected: (profile, "fixture"))
    real_open = contract.open_evidence

    @contextmanager
    def open_fixture(path: Path, *, protected: bool = False):
        with real_open(path, protected=False) as stream:
            yield stream

    monkeypatch.setattr(contract, "open_evidence", open_fixture)
    compose: dict[str, Any] = {
        "services": {
            name: {
                "environment": {
                    "LOG_PURGE_ENABLED": "false",
                    "SECRET_VALUE": "not-for-output",
                    "COMPOSE_DEFAULT": "allowed-extra-value",
                },
                "volumes": [],
            }
            for name in ("backend", "celery_worker", "celery_beat")
        }
    }
    compose["x-keys"] = {"logging": "default"}
    compose["x-logging"] = {"options": {"max-size": "10m"}}
    compose["services"]["grafana"] = {"volumes": mounts}
    generated = contract.configuration_files_from_runtime(state, candidate, compose)
    assert generated == file_map
    profile_json = json.dumps(
        {"configuration_sha256": contract.canonical_digest(generated), "files": generated}
    )
    assert "not-for-output" not in profile_json
    contract.verify_release_configuration(state, candidate, compose)

    compose["services"]["backend"]["environment"]["SECRET_VALUE"] = "wrong-secret"
    with pytest.raises(contract.ContractError, match="mismatched keys: SECRET_VALUE") as error:
        contract.configuration_files_from_runtime(state, candidate, compose)
    assert "not-for-output" not in str(error.value)
    compose["services"]["backend"]["environment"]["SECRET_VALUE"] = "not-for-output"

    compose["unexpected"] = {"ignored": True}
    with pytest.raises(
        contract.ContractError, match="Invalid effective Compose configuration fields"
    ):
        contract.configuration_files_from_runtime(state, candidate, compose)
    del compose["unexpected"]

    usesend_mount = {
        "type": "bind",
        "source": str(candidate / "observability/grafana/contact-points/usesend.yml"),
        "target": "/etc/grafana/provisioning/alerting/contact-point.yml",
    }
    compose["services"]["grafana"]["volumes"].append(usesend_mount)
    assert contract.configuration_files_from_runtime(state, candidate, compose) == file_map
    compose["services"]["grafana"]["volumes"].remove(usesend_mount)

    (candidate / ".env").write_text("LOG_PURGE_ENABLED=true\n")
    with pytest.raises(
        contract.ContractError,
        match="differs from the pinned production environment",
    ):
        contract.configuration_files_from_runtime(state, candidate, compose)
    (candidate / ".env").write_bytes(host_contents["production.env"])

    (candidate / "nginx/nginx.prod.conf").write_bytes(b"changed after approval")
    with pytest.raises(
        contract.ContractError, match="differs from the approved host configuration"
    ):
        contract.verify_release_configuration(state, candidate, compose)

    (candidate / "nginx/nginx.prod.conf").write_bytes(release_contents["nginx/nginx.prod.conf"])
    (portal / "releases/cert/nginx/ssl/privkey.pem").write_bytes(b"rotated-key")
    with pytest.raises(contract.ContractError, match="deployment setting differs"):
        contract.verify_release_configuration(state, candidate, compose)
    (portal / "releases/cert/nginx/ssl/privkey.pem").write_bytes(
        external_contents["releases/cert/nginx/ssl/privkey.pem"]
    )
    compose["services"]["backend"]["environment"]["LOG_PURGE_ENABLED"] = "true"
    with pytest.raises(contract.ContractError, match="audit deletion must be disabled"):
        contract.verify_release_configuration(state, candidate, compose)
    compose["services"]["backend"]["environment"]["LOG_PURGE_ENABLED"] = "false"
    extra_mount = candidate / "unexpected.conf"
    extra_mount.write_text("unapproved runtime input")
    compose["services"]["backend"]["volumes"].append({
        "type": "bind",
        "source": str(extra_mount),
        "target": "/etc/unexpected.conf",
    })
    with pytest.raises(
        contract.ContractError,
        match="do not cover the approved release configuration set",
    ):
        contract.verify_release_configuration(state, candidate, compose)
