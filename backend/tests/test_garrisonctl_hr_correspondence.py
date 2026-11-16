import io
import json
import stat
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_correspondence_cli_workflow(
    decision: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    maker, reviewer, application, draft, template = (str(uuid4()) for _ in range(5))
    app_path = f"/api/v1/hr/applications/{application}"
    path = f"{app_path}/correspondence"
    actor = maker
    writes: list[str] = []
    reason = "Synthetic private rejection reason"
    subject = "Synthetic protected letter subject"
    body = "Synthetic protected letter body"
    original_digest = "a" * 64
    row = {
        "id": draft,
        "subject": subject,
        "body": body,
        "status": "draft",
        "digest": original_digest,
        "created_at": "2026-11-16T12:00:00Z",
        "decided_at": None,
        "rejection_reason": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        route = request.url.path
        if route == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": ["hr:recruitment:manage"]})
        if request.method == "GET":
            if route == "/api/v1/hr/candidate-correspondence/templates":
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": template,
                                "name": "Rejection",
                                "is_active": True,
                                "subject_template": subject,
                                "body_template": body,
                            }
                        ],
                        "total": 1,
                    },
                )
            if route == app_path:
                return httpx.Response(200, json={"id": application, "stage": "rejected"})
            if route == path:
                assert request.url.params["limit"] == "10"
                return httpx.Response(
                    200, json={"items": [{"id": draft, "status": row["status"]}], "total": 1}
                )
            assert route == f"{path}/{draft}"
            return httpx.Response(
                200, json={**row, "can_decide": actor == reviewer and row["status"] == "draft"}
            )
        assert request.method == "POST"
        writes.append(route)
        payload = json.loads(request.content)
        if route == path:
            assert actor == maker and payload == {"draft_id": draft, "template_id": template}
        else:
            assert route == f"{path}/{draft}/decision" and actor == reviewer
            assert payload == {
                "decision": decision,
                "expected_digest": row["digest"],
                "reason": reason if decision == "rejected" else None,
            }
            row.update(status=decision, decided_at="2026-11-16T12:01:00Z")
        return httpx.Response(200, json=row)

    def invoke(command: str, *options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        references: list[str] = []
        if command != "templates":
            references.extend(("--application-id", application))
        if command in {"draft", "status", "decide"}:
            references.extend(("--draft-id", draft))
        code = garrisonctl.run(
            [
                "hr",
                "correspondence",
                command,
                *references,
                *options,
                "--json",
            ],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        for private in (subject, body, reason):
            assert private not in stdout.getvalue()
        return code, json.loads(stdout.getvalue())

    assert invoke("templates")[1]["data"]["items"] == [
        {"id": template, "name": "Rejection", "is_active": True}
    ]
    code, preview = invoke("draft", "--template-id", template, "--dry-run")
    assert code == 0 and writes == []
    preview_hash = preview["data"]["plan_sha256"]
    actor = reviewer
    assert invoke("draft", "--template-id", template, "--apply", "--expect", preview_hash)[0] == 4
    assert writes == []
    actor = maker
    assert invoke("draft", "--template-id", template, "--apply", "--expect", preview_hash)[0] == 0
    assert writes == [path]
    assert invoke("list", "--limit", "10")[1]["data"]["items"] == [{"id": draft, "status": "draft"}]

    output = tmp_path / "letter.json"
    assert invoke("status", "--output", str(output))[0] == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text())["body"] == row["body"]
    assert invoke("status", "--output", str(output))[0] != 0
    assert json.loads(output.read_text())["body"] == row["body"]

    decision_args = ["--decision", decision, "--content-sha256", original_digest]
    reason_file = tmp_path / "reason.txt"
    if decision == "rejected":
        reason_file.write_text(reason)
        reason_file.chmod(0o600)
        decision_args += ["--reason-file", str(reason_file)]
    assert invoke("decide", *decision_args, "--dry-run")[0] == 4
    actor = reviewer
    code, preview = invoke("decide", *decision_args, "--dry-run")
    assert code == 0
    apply_args = ["--apply", "--expect", preview["data"]["plan_sha256"]]
    if decision == "rejected":
        reason_file.write_text("Changed reason")
        assert invoke("decide", *decision_args, *apply_args)[0] == 4
        reason_file.write_text(reason)
    row["digest"] = "b" * 64
    assert invoke("decide", *decision_args, *apply_args)[0] == 4
    row["digest"] = original_digest
    assert writes == [path]
    code, receipt = invoke("decide", *decision_args, *apply_args)
    assert code == 0 and receipt["data"]["status"] == decision
    assert writes == [path, f"{path}/{draft}/decision"]
    assert invoke("decide", *decision_args, *apply_args)[0] == 4
    assert writes == [path, f"{path}/{draft}/decision"]
