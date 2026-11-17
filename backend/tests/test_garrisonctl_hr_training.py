import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


@pytest.mark.parametrize("resource", ["courses", "enrollments"])
def test_training_cli_confirms_actor_and_reads_persisted_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    operator, reviewer, employee, course, created = (str(uuid4()) for _ in range(5))
    actor = operator
    allowed = True
    rows: list[dict] = []
    path = f"/api/v1/hr/training/{resource}"
    file = tmp_path / "training.json"
    proposed = (
        {"code": "IND-1", "title": "Synthetic induction", "duration_hours": "1.5"}
        if resource == "courses"
        else {"employee_id": employee, "course_id": course, "scheduled_date": "2026-11-20"}
    )
    file.write_text(json.dumps(proposed))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={
                "id": actor,
                "permissions": ["hr:training:manage"] if allowed else [],
            })
        assert request.url.path == path
        if request.method == "GET":
            assert request.url.params.get("employee_id") == proposed.get("employee_id")
            return httpx.Response(200, json={"items": rows, "total": len(rows)})
        assert request.method == "POST" and actor == operator
        assert not rows
        payload = json.loads(request.content)
        assert all(payload[key] == value for key, value in proposed.items())
        if resource == "courses":
            payload["duration_hours"] = "1.50"
        row = {"id": created, **payload}
        rows.append(row)
        return httpx.Response(201, json=row)

    def invoke(command: str, *args: str) -> tuple[int, dict]:
        stdout = io.StringIO()
        code = garrisonctl.run(
            ["hr", "training", resource, command, *args, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=io.StringIO(),
        )
        return code, json.loads(stdout.getvalue())

    allowed = False
    assert invoke("create", "--file", str(file), "--dry-run")[0] != 0
    allowed = True
    code, preview = invoke("create", "--file", str(file), "--dry-run")
    assert code == 0 and not rows
    checksum = preview["data"]["plan_sha256"]
    actor = reviewer
    assert invoke("create", "--file", str(file), "--apply", "--expect", checksum)[0] == 4
    assert not rows
    actor = operator
    code, result = invoke("create", "--file", str(file), "--apply", "--expect", checksum)
    assert code == 0 and result["data"]["id"] == created
    filters = () if resource == "courses" else ("--employee-id", employee)
    assert invoke("list", *filters)[1]["data"] == {"items": rows, "total": 1}


def test_training_enrollment_update_rechecks_state_at_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    actor, employee, enrollment = (str(uuid4()) for _ in range(3))
    path = "/api/v1/hr/training/enrollments"
    row = {"id": enrollment, "employee_id": employee, "status": "enrolled"}
    race_on_apply = False
    writes: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": ["hr:training:manage"]})
        if request.method == "GET":
            assert request.url.path == path and request.url.params["employee_id"] == employee
            return httpx.Response(200, json={"items": [row]})
        assert request.method == "PATCH" and request.url.path == f"{path}/{enrollment}"
        payload = json.loads(request.content)
        writes.append(payload)
        if race_on_apply:
            row["status"] = "in_progress"
        if payload["expected_status"] != row["status"]:
            return httpx.Response(409, json={"detail": "The enrollment changed."})
        row["status"] = payload["status"]
        return httpx.Response(200, json=row)

    def invoke(*args: str) -> tuple[int, dict]:
        stdout = io.StringIO()
        code = garrisonctl.run(
            [
                "hr", "training", "enrollments", "update", "--employee-id", employee,
                "--enrollment-id", enrollment, "--status", "cancelled", *args, "--json",
            ],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=io.StringIO(),
        )
        return code, json.loads(stdout.getvalue())

    code, preview = invoke("--dry-run")
    assert code == 0 and not writes
    checksum = preview["data"]["plan_sha256"]
    race_on_apply = True
    assert invoke("--apply", "--expect", checksum)[0] == 4
    assert row["status"] == "in_progress"
    assert invoke("--apply", "--expect", checksum)[0] == 4
    assert writes == [{"status": "cancelled", "expected_status": "enrolled"}]

    race_on_apply = False
    code, preview = invoke("--dry-run")
    assert code == 0
    code, result = invoke("--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and result["data"]["status"] == "cancelled"
    assert writes[-1] == {"status": "cancelled", "expected_status": "in_progress"}
    assert invoke("--dry-run")[0] == 4
