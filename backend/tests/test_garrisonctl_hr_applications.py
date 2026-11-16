import io
import json
import stat
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


def test_recruitment_cli_binds_application_and_stage_without_printing_private_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    actor, requisition, candidate, application = (str(uuid4()) for _ in range(4))
    stamp, later = "2026-11-16T12:00:00Z", "2026-11-16T12:01:00Z"
    candidates, applications = "/api/v1/hr/candidates", "/api/v1/hr/applications"
    email, notes = "private@example.com", "Synthetic private screening material"
    candidate_row: dict[str, object] = {}
    application_row: dict[str, object] = {}
    writes: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": ["hr:recruitment:manage"]})
        if path == f"/api/v1/hr/requisitions/{requisition}":
            return httpx.Response(
                200,
                json={
                    "id": requisition,
                    "requisition_code": "OPEN",
                    "title": "Job",
                    "status": "open",
                    "headcount_requested": 2,
                    "employment_category": "permanent",
                    "target_join_date": None,
                    "updated_at": stamp,
                },
            )
        if request.method == "GET":
            if path in (candidates, applications):
                if path == applications:
                    assert request.url.params["candidate_id"] == candidate
                    assert request.url.params["requisition_id"] == requisition
                rows = [candidate_row] if path == candidates else [application_row]
                items = [row for row in rows if row]
                return httpx.Response(200, json={"items": items, "total": len(items)})
            if path == f"{candidates}/{candidate}":
                return httpx.Response(200, json=candidate_row)
            assert path == f"{applications}/{application}"
            return httpx.Response(200, json=application_row)
        payload = json.loads(request.content)
        writes.append(path)
        if path == candidates:
            candidate_row.update(payload, id=candidate, status="new", resume_document_id=None)
            return httpx.Response(201, json=candidate_row)
        if path == applications:
            assert payload.pop("expected_requisition_updated_at") == stamp
            application_row.update(payload, id=application, stage="applied", updated_at=stamp)
            return httpx.Response(201, json=application_row)
        assert path == f"{applications}/{application}/stage"
        assert payload.pop("expected_updated_at") == stamp
        application_row.update(payload, updated_at=later)
        return httpx.Response(200, json=application_row)

    def run(group: str, command: str, *options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", group, command, *options, "--json"],
            transport=httpx.MockTransport(serve),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        assert email not in stdout.getvalue() and notes not in stdout.getvalue()
        return code, json.loads(stdout.getvalue())

    source = tmp_path / "private.json"
    source.touch(mode=0o600)
    args = ["--file", str(source)]

    def apply_args(group: str, command: str, *options: str) -> list[str]:
        code, preview = run(group, command, *options, "--dry-run")
        assert code == 0
        return ["--apply", "--expect", preview["data"]["plan_sha256"]]

    source.write_text(
        json.dumps({"candidate_code": "C-1", "full_name": "Synthetic Candidate", "email": email})
    )
    assert run("candidates", "create", *args, *apply_args("candidates", "create", *args))[0] == 0
    assert run("candidates", "list", "--code", "C-1")[1]["data"]["total"] == 1
    output = tmp_path / "candidate.json"
    assert run("candidates", "status", "--candidate-id", candidate, "--output", str(output))[0] == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text())["email"] == email

    source.write_text(
        json.dumps(
            {"candidate_id": candidate, "requisition_id": requisition, "screening_notes": notes}
        )
    )
    commit = apply_args("applications", "create", *args)
    assert run("applications", "create", *args, *commit)[1]["data"]["stage"] == "applied"
    assert run("applications", "create", *args, *commit)[0] == 4
    assert (
        run("applications", "list", "--requisition-id", requisition, "--candidate-id", candidate)[
            1
        ]["data"]["total"]
        == 1
    )

    source.write_text(json.dumps({"stage": "screening", "screening_notes": notes}))
    record = ["--application-id", application, *args]
    commit = apply_args("applications", "stage", *record)
    application_row["updated_at"] = later
    assert run("applications", "stage", *record, *commit)[0] == 4
    application_row["updated_at"] = stamp
    assert run("applications", "stage", *record, *commit)[1]["data"]["stage"] == "screening"
    assert writes == [candidates, applications, f"{applications}/{application}/stage"]
