import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


def test_onboarding_cli_checks_task_snapshot_and_probation_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    actor, employee, case_id, task_id = (str(uuid4()) for _ in range(4))
    stamp = "2026-11-16T12:00:00Z"
    later = "2026-11-16T13:00:00Z"
    evidence, reason = "Synthetic checklist evidence", "Synthetic probation reasoning"
    permissions = ["hr:onboarding:manage"]
    task = {
        "id": task_id,
        "code": "ONB-HR-01",
        "status": "pending",
        "assignee_role": "hr",
        "is_mandatory": True,
        "updated_at": stamp,
        "evidence_notes": None,
    }
    case = {
        "id": case_id,
        "employee_id": employee,
        "offer_id": None,
        "status": "open",
        "employee_status": "onboarding",
        "employee_revision": 1,
        "employee_category": "probation",
        "updated_at": stamp,
        "tasks": [task],
    }
    base = "/api/v1/hr/onboarding"
    created = False
    writes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal created
        path = request.url.path
        if path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": permissions})
        if request.method == "GET":
            if path == base:
                assert request.url.params["employee_id"] == employee
                found = created and request.url.params.get("case_status") in (None, case["status"])
                return httpx.Response(
                    200, json={"items": [case] if found else [], "total": int(found)}
                )
            assert path == f"{base}/{case_id}"
            return httpx.Response(200, json=case)
        payload = json.loads(request.content)
        writes.append(path)
        if path == base:
            assert request.method == "POST" and not created
            created = True
            case.update(payload)
        elif path == f"{base}/tasks/{task_id}":
            assert request.method == "PATCH" and payload == {
                "status": "completed",
                "evidence_notes": evidence,
                "expected_updated_at": stamp,
            }
            case.update(status="completed")
            task.update(status="completed", evidence_notes=evidence, updated_at=later)
        else:
            assert path == f"{base}/{case_id}/probation-review"
            assert payload["expected_employee_revision"] == case["employee_revision"]
            assert payload["reason"] == reason
            if payload["outcome"] == "extend":
                case.update(probation_end_date=payload["new_end_date"], employee_revision=3)
            else:
                case.update(
                    employee_status="active", employee_category="permanent", employee_revision=4
                )
        return httpx.Response(200, json=case)

    def invoke(command: str, *args: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "onboarding", command, *args, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        assert evidence not in stdout.getvalue() and reason not in stdout.getvalue()
        return code, json.loads(stdout.getvalue())

    private = tmp_path / "input.json"
    private.touch(mode=0o600)
    file_args = ["--file", str(private)]
    case_args = ["--case-id", case_id]

    def apply_args(command: str, *args: str) -> list[str]:
        code, preview = invoke(command, *args, "--dry-run")
        assert code == 0
        return ["--apply", "--expect", preview["data"]["plan_sha256"]]

    private.write_text(
        json.dumps(
            {
                "employee_id": employee,
                "start_date": "2026-11-01",
                "probation_end_date": "2026-12-01",
            }
        )
    )
    assert invoke("create", *file_args, *apply_args("create", *file_args))[0] == 0
    assert invoke("list", "--employee-id", employee)[1]["data"]["total"] == 1

    private.write_text(json.dumps({"status": "completed", "evidence_notes": evidence}))
    task_args = [*case_args, "--task-id", task_id, *file_args]
    assert invoke("task", *task_args, "--dry-run")[0] == 3
    permissions.append("hr:employees:sensitive")
    apply = apply_args("task", *task_args)
    task["updated_at"] = later
    assert invoke("task", *task_args, *apply)[0] == 4
    task["updated_at"] = stamp
    assert invoke("task", *task_args, *apply)[1]["data"]["status"] == "completed"
    detail = tmp_path / "case.json"
    assert invoke("status", *case_args, "--output", str(detail))[0] == 0
    assert json.loads(detail.read_text())["tasks"][0]["evidence_notes"] == evidence

    case.update(employee_status="on_probation", employee_revision=2)
    probation = [*case_args, *file_args]
    private.write_text(
        json.dumps({"outcome": "extend", "reason": reason, "new_end_date": "2027-01-01"})
    )
    apply = apply_args("probation", *probation)
    case["employee_revision"] = 3
    assert invoke("probation", *probation, *apply)[0] == 4
    case["employee_revision"] = 2
    assert invoke("probation", *probation, *apply)[1]["data"]["probation_end_date"] == "2027-01-01"
    private.write_text(
        json.dumps({"outcome": "confirm", "reason": reason, "confirmed_category": "permanent"})
    )
    assert (
        invoke("probation", *probation, *apply_args("probation", *probation))[1]["data"][
            "employee_status"
        ]
        == "active"
    )
    assert writes == [base, f"{base}/tasks/{task_id}", *[f"{base}/{case_id}/probation-review"] * 2]
