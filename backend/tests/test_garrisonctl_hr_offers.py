import io
import json
import stat
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


def test_offer_cli_binds_private_terms_and_reads_back_both_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    actor, application, first, second = (str(uuid4()) for _ in range(4))
    stamp = "2026-11-16T12:00:00Z"
    later = "2026-11-16T13:00:00Z"
    note = "Synthetic private offer notes"
    path = "/api/v1/hr/offers"
    offers: dict[str, dict] = {}
    writes: list[str] = []
    permissions = ["hr:recruitment:manage"]

    def handler(request: httpx.Request) -> httpx.Response:
        route = request.url.path
        if route == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": permissions})
        if route == f"/api/v1/hr/applications/{application}":
            return httpx.Response(
                200, json={"id": application, "stage": "evaluation", "updated_at": stamp}
            )
        if request.method == "GET":
            if route == path:
                assert request.url.params["limit"] == "1"
                assert request.url.params["application_id"] == application
                return httpx.Response(200, json={"items": [offers[second]], "total": 2})
            return httpx.Response(200, json=offers[route.split("/")[-1]])
        writes.append(route)
        payload = json.loads(request.content)
        assert payload["notes"] == note
        if route.endswith("/decision"):
            assert (
                payload["expected_version_number"] == 1 and payload["expected_updated_at"] == stamp
            )
            offers[first].update(status="approved", updated_at=later)
            return httpx.Response(200, json=offers[first])
        if route == path:
            assert payload["expected_application_updated_at"] == stamp
            identity, version = first, 1
        else:
            assert route == f"{path}/{first}/reissue"
            assert payload["expected_updated_at"] == later
            identity, version = second, 2
            offers[first].update(status="superseded", superseded_by_id=second)
        offers[identity] = {
            "id": identity,
            "offer_code": payload["offer_code"],
            "application_id": application,
            "valid_until": payload["valid_until"],
            "version_number": version,
            "status": "draft",
            "updated_at": stamp,
            "supersedes_offer_id": first if version == 2 else None,
            "notes": note,
            "proposed_salary_masked": "private-salary-placeholder",
        }
        return httpx.Response(201, json=offers[identity])

    def invoke(command: str, *options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "offers", command, *options, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        assert (
            note not in stdout.getvalue() and "private-salary-placeholder" not in stdout.getvalue()
        )
        return code, json.loads(stdout.getvalue())

    private_file = tmp_path / "terms.json"
    private_file.touch(mode=0o600)

    def store(payload: dict) -> None:
        private_file.write_text(json.dumps(payload))

    file_args = ["--file", str(private_file)]
    terms = {
        "offer_code": "TEST-OFFER-1",
        "proposed_title": "Coordinator",
        "valid_until": "2026-12-01",
        "notes": note,
    }
    store({**terms, "application_id": application})
    code, preview = invoke("draft", *file_args, "--dry-run")
    assert code == 0 and not writes
    apply = ["--apply", "--expect", preview["data"]["plan_sha256"]]
    store({**terms, "application_id": application, "notes": "Changed terms"})
    assert invoke("draft", *file_args, *apply)[0] == 4 and not writes
    store({**terms, "application_id": application})
    assert invoke("draft", *file_args, *apply)[0] == 0
    exported = tmp_path / "offer.json"
    status_args = ["--offer-id", first, "--output", str(exported)]
    assert invoke("status", *status_args)[0] == 0
    assert stat.S_IMODE(exported.stat().st_mode) == 0o600
    assert json.loads(exported.read_text())["notes"] == note
    assert invoke("status", *status_args)[0] != 0

    offers[first]["status"] = "pending_approval"
    file_args = ["--offer-id", first, *file_args]
    store({"status": "approved", "notes": note})
    assert invoke("decide", *file_args, "--dry-run")[0] == 3
    permissions.append("hr:employees:sensitive")
    code, preview = invoke("decide", *file_args, "--dry-run")
    assert code == 0
    assert (
        invoke("decide", *file_args, "--apply", "--expect", preview["data"]["plan_sha256"])[0] == 0
    )

    store({**terms, "offer_code": "TEST-OFFER-2"})
    code, preview = invoke("reissue", *file_args, "--dry-run")
    assert code == 0
    code, receipt = invoke(
        "reissue", *file_args, "--apply", "--expect", preview["data"]["plan_sha256"]
    )
    assert code == 0
    assert receipt["data"]["supersedes_offer_id"] == first
    assert receipt["data"]["prior_offer"]["superseded_by_id"] == second
    assert (
        invoke("list", "--application-id", application, "--limit", "1")[1]["data"]["items"][0]["id"]
        == second
    )
    assert writes == [path, f"{path}/{first}/decision", f"{path}/{first}/reissue"]
