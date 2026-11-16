import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


def test_interview_cli_checks_private_inputs_and_reads_saved_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    actor, app_id, interview_id = (str(uuid4()) for _ in range(3))
    stamp = "2026-11-16T12:00:00Z"
    private_name = "Synthetic Private Interviewer"
    private_notes = "Synthetic private feedback"
    row: dict[str, object] = {}
    writes: list[str] = []
    interview_path = "/api/v1/hr/interviews"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": ["hr:recruitment:manage"]})
        if path == f"/api/v1/hr/applications/{app_id}":
            return httpx.Response(
                200, json={"id": app_id, "stage": "shortlisted", "updated_at": stamp}
            )
        if request.method == "GET":
            assert request.url.params["application_id"] == app_id
            return httpx.Response(200, json={"items": [row] if row else [], "total": bool(row)})
        writes.append(request.method)
        posted = json.loads(request.content)
        if request.method == "POST":
            assert path == interview_path
            assert posted.pop("expected_application_updated_at") == stamp
            assert posted.pop("interview_id") == interview_id
            assert posted["interviewer_name"] == private_name
            row.update(
                posted,
                id=interview_id,
                status="scheduled",
                recommendation="pending",
                updated_at=stamp,
            )
            return httpx.Response(201, json=row)
        assert request.method == "PATCH" and path == f"{interview_path}/{interview_id}"
        assert posted.pop("expected_updated_at") == stamp
        assert posted["feedback_notes"] == private_notes
        row.update(posted, updated_at="2026-11-16T13:00:00Z")
        return httpx.Response(200, json=row)

    def invoke(command: str, *options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "interviews", command, *options, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        assert private_name not in stdout.getvalue() and private_notes not in stdout.getvalue()
        return code, json.loads(stdout.getvalue())

    path = tmp_path / "private.json"
    path.touch(mode=0o600)
    schedule = {
        "application_id": app_id,
        "interview_id": interview_id,
        "interviewer_name": private_name,
        "scheduled_at": "2026-11-20T09:30:00+03:00",
    }
    path.write_text(json.dumps(schedule))
    file_args = ["--file", str(path)]
    code, preview = invoke("schedule", *file_args, "--dry-run")
    assert code == 0 and not writes
    apply = ["--apply", "--expect", preview["data"]["plan_sha256"]]
    path.write_text(json.dumps({**schedule, "round_number": 2}))
    assert invoke("schedule", *file_args, *apply)[0] == 4
    assert not writes
    path.write_text(json.dumps(schedule))
    assert invoke("schedule", *file_args, *apply)[0] == 0
    assert (
        invoke("list", "--application-id", app_id)[1]["data"]["items"][0]["status"] == "scheduled"
    )

    edits = {"status": "completed", "recommendation": "hire", "feedback_notes": private_notes}
    path.write_text(json.dumps(edits))
    update = ["--application-id", app_id, "--interview-id", interview_id, *file_args]
    code, preview = invoke("update", *update, "--dry-run")
    assert code == 0 and writes == ["POST"]
    apply = ["--apply", "--expect", preview["data"]["plan_sha256"]]
    row["updated_at"] = "2026-11-16T12:00:01Z"
    assert invoke("update", *update, *apply)[0] == 4
    assert writes == ["POST"]
    row["updated_at"] = stamp
    code, receipt = invoke("update", *update, *apply)
    assert code == 0 and receipt["data"]["status"] == "completed"
    assert row["feedback_notes"] == private_notes and writes == ["POST", "PATCH"]
