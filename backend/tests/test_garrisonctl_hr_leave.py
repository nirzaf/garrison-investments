import io
import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


def test_leave_cli_uses_single_request_and_verifies_persisted_reversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    operator, leave = (str(uuid4()) for _ in range(2))
    path = f"/api/v1/hr/leave/requests/{leave}/decision"
    row: dict[str, Any] = {
        "id": leave, "status": "approved", "record_revision": 3,
        "manager_recommendation": None, "decided_by_id": operator,
    }
    private_notes = "Synthetic private absence notes"
    writes = []

    def request_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200, json={"id": operator, "permissions": ["hr:leave:approve"]}
            )
        assert request.url.path == path
        if request.method == "GET":
            return httpx.Response(200, json=row)
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload == {
            "decision": "cancelled", "expected_revision": row["record_revision"],
            "notes": private_notes,
        }
        writes.append(payload)
        row.update(status="cancelled", record_revision=row["record_revision"] + 1)
        return httpx.Response(200, json={**row, "decision_notes": private_notes})

    def invoke(*options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [
                "hr", "leave", "requests", "decide", "--leave-request-id", leave,
                "--decision", "cancelled", "--notes", private_notes, *options, "--json",
            ],
            transport=httpx.MockTransport(request_handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert private_notes not in stdout.getvalue() + stderr.getvalue()
        return code, json.loads(stdout.getvalue())

    code, preview = invoke("--dry-run")
    assert code == 0 and not writes
    row["record_revision"] += 1
    assert invoke("--apply", "--expect", preview["data"]["plan_sha256"])[0] == 4
    assert not writes
    code, preview = invoke("--dry-run")
    assert code == 0
    code, result = invoke("--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and result["data"] == row and result["changed"]
    assert row["status"] == "cancelled" and len(writes) == 1
