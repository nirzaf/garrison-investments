import io
import json
import stat
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl
from scripts.garrisonctl_common import AUTH, CONFLICT


def test_service_request_cli_protects_private_text_and_checks_current_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    actor, employee, req_id, assignee, letter = (str(uuid4()) for _ in range(5))
    permissions = ["hr:requests:process"]
    path = "/api/v1/hr/requests"
    details = f"{path}/{req_id}"
    private_text = "Synthetic private HR request"
    row = {
        "id": req_id,
        "request_code": "HR-001",
        "employee_id": employee,
        "request_type": "employment_letter",
        "status": "in_review",
        "assigned_to_id": None,
        "generated_document_id": None,
        "generated_letter_id": None,
        "updated_at": "2026-11-16T12:00:00Z",
        "subject": private_text,
    }
    writes = []

    def handler(request: httpx.Request) -> httpx.Response:
        route = request.url.path
        if route == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": permissions})
        if request.method == "GET":
            if route == f"{path}/assignees":
                return httpx.Response(200, json=[{"id": assignee, "full_name": "Test HR Manager"}])
            if route == path:
                assert dict(request.url.params) == {
                    "employee_id": employee,
                    "req_status": "in_review",
                    "limit": "10",
                    "offset": "20",
                }
                return httpx.Response(200, json={"items": [row], "total": 21})
            assert route == details
            return httpx.Response(200, json=row)
        payload = json.loads(request.content)
        assert payload.pop("expected_updated_at") == row["updated_at"]
        writes.append(route)
        if route == f"{details}/assign":
            assert payload == {"assigned_to_id": assignee, "reason": private_text}
            row.update(assigned_to_id=assignee, updated_at="2026-11-16T13:00:00Z")
        else:
            assert route == f"{details}/resolve"
            assert payload == {
                "status": "completed",
                "resolution_notes": private_text,
                "generated_letter_id": letter,
            }
            row.update(payload)
        return httpx.Response(200, json=row)

    def invoke(*args: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "requests", *args, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert private_text not in stdout.getvalue() + stderr.getvalue()
        return code, json.loads(stdout.getvalue())

    code, listing = invoke(
        "list",
        "--status",
        "in_review",
        "--employee-id",
        employee,
        "--limit",
        "10",
        "--offset",
        "20",
    )
    assert code == 0 and listing["data"]["total"] == 21
    code, assignees = invoke("assignees")
    assert code == 0 and assignees["data"][0]["id"] == assignee
    output = tmp_path / "detail.json"
    assert invoke("show", "--request-id", req_id, "--output", str(output))[0] == 0
    assert json.loads(output.read_text())["subject"] == private_text
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    source = tmp_path / "input.json"
    source.touch(mode=0o600)
    args = ("--request-id", req_id, "--file", str(source))
    source.write_text(json.dumps({"assigned_to_id": assignee, "reason": private_text}))
    code, preview = invoke("assign", *args, "--dry-run")
    assert code == 0 and not writes
    plan = preview["data"]["plan_sha256"]
    row["updated_at"] = "2026-11-16T12:30:00Z"
    assert invoke("assign", *args, "--apply", "--expect", plan)[0] == CONFLICT
    assert not writes
    code, preview = invoke("assign", *args, "--dry-run")
    assert code == 0
    code, updated = invoke("assign", *args, "--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and updated["data"]["assigned_to_id"] == assignee

    source.write_text(json.dumps({"status": "rejected", "resolution_notes": private_text}))
    assert invoke("resolve", *args, "--dry-run")[0] == AUTH
    assert writes == [f"{details}/assign"]
    source.write_text(
        json.dumps(
            {"status": "completed", "resolution_notes": private_text, "generated_letter_id": letter}
        )
    )
    code, preview = invoke("resolve", *args, "--dry-run")
    assert code == 0
    code, updated = invoke("resolve", *args, "--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and updated["data"]["generated_letter_id"] == letter
    assert writes == [f"{details}/assign", f"{details}/resolve"]
