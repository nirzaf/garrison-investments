from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
        self.recovery_artifacts: dict[str, list[dict[str, Any]]] = {}
        self.observation_artifacts: list[dict[str, Any]] = []
        self.inventory_artifacts: list[dict[str, Any]] = []
        self.sequence = 0
        self.artifact = self.write("artifacts/report.json", {"actual": "Synthetic fixture"})
        self.artifact["sensitivity"] = "sanitized"

    def write(self, name: str, value: Any) -> dict[str, Any]:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value, sort_keys=True).encode()
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
        return contract.Validation(
            self.root, self.trust, phase=phase, sha=SHA, target="test", token=None, **extra
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
                *(self.recovery_artifacts[phase] if kind == "recovery" else []),
                *(self.observation_artifacts if kind == "observation" else []),
                *(self.inventory_artifacts if kind == "data_reconciliation" else []),
            ],
        }
        row["review"] = self.approval(
            "review_receipt",
            contract.canonical_digest(row),
            "release_reviewer",
            "Fixture Release Reviewer",
        )
        return self.write(f"receipts/{phase}-{kind}.json", row)

    def alert(self, name: str, start: datetime) -> dict[str, Any]:
        times = ["trigger_at", "evaluated_at", "fired_at", "recovered_at", "resolved_at"]
        result = {
            "rule_id": name,
            "environment": "test",
            "synthetic": True,
            **{
                key: (start + timedelta(seconds=index)).isoformat()
                for index, key in enumerate(times)
            },
            "message_id": f"fixture-{name}",
            "recipient": "Fixture Primary",
            "independent_path": True,
            "acknowledged_at": (start + timedelta(seconds=5)).isoformat(),
        }
        result["acknowledgement_ref"] = self.approval(
            "acknowledge_alert",
            contract.canonical_digest(result),
            "alert_recipient",
            "Fixture Primary",
            at=start + timedelta(seconds=5),
        )
        return result

    def uat(self, phase: str, support: dict[str, Any], start: datetime) -> list[dict[str, Any]]:
        results = []
        devices = (
            support["desktop_targets"]
            + support["physical_mobile_targets"]
            + [device("operations", "Operator")]
        )
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
                        "physical_device": platform in {"ios", "android"},
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
            "physical_mobile_targets": [device("ios", "Safari"), device("android", "Chrome")],
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
    jobs = [
        {"id": i, "name": name, "head_sha": SHA, "status": "completed", "conclusion": "success"}
        for i, name in enumerate(sorted(contract.CI_JOBS), 1)
    ]
    if "/jobs?" in path:
        return {"jobs": jobs, "total_count": len(jobs)}
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


def ci_receipt(bundle: Bundle) -> dict[str, Any]:
    counts = {"passed": 2, "failed": 0, "skipped": 0, "warnings": 0}
    return {
        "run_id": 11,
        "run_url": contract.run_url(11),
        "repository": contract.REPOSITORY,
        "ref": "refs/heads/main",
        "conclusion": "success",
        "jobs": [
            {
                "id": i,
                "name": name,
                "url": f"{contract.run_url(11)}/job/{i}",
                "conclusion": "success",
            }
            for i, name in enumerate(sorted(contract.CI_JOBS), 1)
        ],
        "suites": [
            {"name": name, **counts, "report": bundle.write(f"artifacts/{name}.json", counts)}
            for name in ("backend", "frontend", "browser")
        ],
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


def phase_results(
    bundle: Bundle,
    phase: str,
    decisions: dict[str, Any],
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
    artifact_counts = {item: 1 for item in backup_policy["required_artifact_categories"]}
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
    bundle.recovery_artifacts[phase] = [
        {**ref, "sensitivity": "sanitized"} for ref in (manifest_ref, auth_ref, publication_ref)
    ]
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
            "alert_events": [bundle.alert(rule, start) for rule in sorted(contract.ALERT_RULES)],
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
    manifest_ref, _, publication_ref = bundle.recovery_artifacts["final"]
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
                    "category": "ready",
                    "status": None,
                    "digest": backup_digest,
                    "snapshot_at": FINAL_START.isoformat() if backup_digest else None,
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


def manifest(bundle: Bundle, phase: str = "predeploy") -> dict[str, Any]:
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
            profile = {
                **payload,
                "targets": [{"url": url, "check_id": "portal"} for url in payload["targets"]],
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
            "staging_equivalence_sha256": None,
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
            "staging_equivalence": None,
        },
    }
    if phase == "final":
        readback = {
            **runtime(),
            "readiness": {"status": "ready", "database": "connected"},
            "services": true("backend", "frontend", "worker", "database", "storage"),
        }
        final = phase_results(bundle, "final", decisions)
        final.update(
            deployment={
                "run_id": 22,
                "run_url": contract.run_url(22),
                "run_attempt": 1,
                "ci_run_id": 11,
                "deployed_at": DEPLOYED.isoformat(),
                "readback": readback,
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


def test_uat_matrix_requires_the_specified_role_on_each_device(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path)
    matrix = decision_values(bundle)["D-32-SUPPORT"]["scenario_platform_map"]
    android = next(row for row in matrix["UAT-07"] if row["platform"] == "android")
    assert android["role"] == "civil_supervisor"
    android["role"] = "operator"
    with pytest.raises(contract.ContractError, match="Mandatory UAT role omitted for UAT-07"):
        contract.scenario_matrix(matrix)


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


@pytest.mark.parametrize("change_threshold", [False, True])
def test_reviewed_staging_policy_keeps_production_recovery_objectives(
    tmp_path: Path, change_threshold: bool
) -> None:
    bundle = Bundle(tmp_path)
    data = manifest(bundle)
    decisions = {}
    for ref in data["decisions"]:
        value = json.loads((bundle.root / ref["path"]).read_text())
        decisions[value["decision_id"]] = value

    recovery = decisions["D-29-RECOVERY"]
    stage = json.loads((bundle.root / recovery["policy_ref"]["path"]).read_text())
    stage["source_environment"] = "staging"
    stage["destination_identity"]["prefix"] = "fixture/staging"
    if change_threshold:
        stage["rto_minutes"] += 1
    recovery_ref = bundle.write("stage-recovery.json", stage)

    operations = decisions["D-30-OPERATIONS"]
    profile = json.loads((bundle.root / operations["profile_ref"]["path"]).read_text())
    profile["environment"] = "staging"
    profile_ref = bundle.write("stage-monitor.json", profile)
    equivalence = {
        "production_configuration_sha256": CONFIG,
        "staging_configuration_sha256": "a" * 64,
        "staging_operations_profile": profile_ref,
        "staging_recovery_policy": recovery_ref,
        "differences": [{"setting": "recovery_isolation", "reason": "Independent fixture prefix"}],
    }
    equivalence["review"] = bundle.approval(
        "staging_equivalence",
        contract.canonical_digest(equivalence),
        "operations_owner",
        "Fixture Operations",
    )
    ref = bundle.write("stage-equivalence.json", equivalence)
    validator = bundle.validator("predeploy")
    validator.target = "production"
    validator.configuration = CONFIG
    validator.decisions = decisions
    if change_threshold:
        with pytest.raises(contract.ContractError, match="differs from its approved decision"):
            validator.validate_equivalence(ref)
    else:
        assert validator.validate_equivalence(ref) == ref["sha256"]
        assert validator.stage_recovery is not None
        assert validator.stage_recovery["policy_ref"] == recovery_ref
        assert validator.stage_recovery["destination_identity"]["prefix"] == "fixture/staging"


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
        bundle.recovery_artifacts["predeploy"].pop()
        for index, ref in enumerate(data["receipts"]):
            if ref["path"].endswith("predeploy-recovery.json"):
                receipt = json.loads((bundle.root / ref["path"]).read_text())
                data["receipts"][index] = bundle.receipt(
                    "recovery", receipt["results"], executor=receipt["executed_by"]
                )
    elif mutation == "empty scenario":
        for index, ref in enumerate(data["receipts"]):
            if ref["path"].endswith("predeploy-uat.json"):
                content = json.loads((bundle.root / ref["path"]).read_text())
                content["results"]["scenarios"] = []
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
