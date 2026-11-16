import io
import json
import stat
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


def test_requisition_cli_protects_private_input_and_binds_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)

    actor, requisition = str(uuid4()), str(uuid4())
    permissions = ["hr:recruitment:manage"]
    stamp = "2026-11-16T12:00:00Z"
    later = "2026-11-16T13:00:00Z"
    reason = "Synthetic private rejection reason"
    budget = "Synthetic private budget notes"
    path = "/api/v1/hr/requisitions"
    row: dict[str, object] = {}
    writes: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        route = request.url.path
        if route == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": permissions})
        if request.method == "GET" and route == path:
            assert request.url.params["code"] == "REQ-TEST"
            items = [row] if row else []
            return httpx.Response(200, json={"items": items, "total": len(items)})
        if request.method == "GET":
            assert route == f"{path}/{requisition}"
            return httpx.Response(200, json=row)
        payload = json.loads(request.content)
        writes.append(route)
        if route == path:
            assert payload["budget_notes"] == budget
            row.update(payload, id=requisition, status="draft", updated_at=stamp)
            return httpx.Response(201, json=row)
        assert route == f"{path}/{requisition}/decision"
        assert payload == {"status": "rejected", "notes": reason, "expected_updated_at": stamp}
        row.update(status="rejected", rejection_reason=reason, updated_at=later)
        return httpx.Response(200, json=row)

    def invoke(command: str, *options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "requisitions", command, *options, "--json"],
            transport=httpx.MockTransport(serve),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        assert all(value not in stdout.getvalue() for value in (reason, budget))
        return code, json.loads(stdout.getvalue())

    private = tmp_path / "requisition.json"
    private.touch(mode=0o600)
    private.write_text(
        json.dumps(
            {
                "title": "Synthetic position",
                "requisition_code": "REQ-TEST",
                "headcount_requested": 3,
                "budget_notes": budget,
            }
        )
    )
    file_args = ["--file", str(private)]
    code, preview = invoke("create", *file_args, "--dry-run")
    assert code == 0 and not writes
    apply = ["--apply", "--expect", preview["data"]["plan_sha256"]]
    assert invoke("create", *file_args, *apply)[1]["data"]["headcount_requested"] == 3
    assert invoke("create", *file_args, *apply)[0] == 4
    assert invoke("list", "--code", "REQ-TEST")[1]["data"]["total"] == 1

    row.update(status="submitted")
    private.write_text(json.dumps({"status": "rejected", "notes": reason}))
    record = ["--requisition-id", requisition]
    assert invoke("decide", *record, *file_args, "--dry-run")[0] == 3
    permissions.append("hr:employees:sensitive")
    code, preview = invoke("decide", *record, *file_args, "--dry-run")
    assert code == 0 and writes == [path]
    apply = ["--apply", "--expect", preview["data"]["plan_sha256"]]
    row["updated_at"] = later
    assert invoke("decide", *record, *file_args, *apply)[0] == 4
    row["updated_at"] = stamp
    private.write_text(json.dumps({"status": "rejected", "notes": "Changed private reason"}))
    assert invoke("decide", *record, *file_args, *apply)[0] == 4
    assert writes == [path]
    private.write_text(json.dumps({"status": "rejected", "notes": reason}))
    assert invoke("decide", *record, *file_args, *apply)[1]["data"]["status"] == "rejected"
    assert writes == [path, f"{path}/{requisition}/decision"]
    output = tmp_path / "private-detail.json"
    assert invoke("status", *record, "--output", str(output))[0] == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text())["rejection_reason"] == reason
    assert invoke("status", *record, "--output", str(output))[0] != 0
