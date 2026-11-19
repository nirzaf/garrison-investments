import asyncio
import io
import json
import stat
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.hr import HrCase, HrDocument, HrEmployee
from app.services.hr_crypto import encrypt_hr_value
from app.utils.permissions import PERMISSION_HR_CASES_RESTRICTED, ROLE_PERMISSIONS
from scripts import garrisonctl
from scripts.garrisonctl_common import CONFLICT
from tests.test_hr import (
    _auth,
    _client,
    _create_portal_user,
    _login,
    skip_if_database_unavailable,
)
from tests.test_hr import hr_fernet_env as hr_fernet_env
from tests.test_hr import isolated_engine_pool as isolated_engine_pool


@pytest.mark.asyncio
async def test_hr_restricted_case_scope_and_encrypted_notes(monkeypatch) -> None:
    await skip_if_database_unavailable()
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        "hr_manager",
        ROLE_PERMISSIONS["hr_manager"] | {PERMISSION_HR_CASES_RESTRICTED},
    )
    owner_id, owner_email, password = await _create_portal_user("hr_manager")
    outsider_id, outsider_email, _ = await _create_portal_user("hr_manager")
    _, director_email, _ = await _create_portal_user("managing_director")
    subject, restricted_file = uuid4(), uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            HrEmployee(
                id=subject,
                employee_code=f"CASE-{uuid4().hex[:10]}",
                first_name="Synthetic",
                last_name="Case Subject",
                full_name="Synthetic Case Subject",
                user_id=UUID(outsider_id),
            )
        )
        await session.flush()
        session.add(
            HrDocument(
                id=restricted_file,
                employee_id=subject,
                title="Synthetic private evidence",
                category="disciplinary",
                document_type="disciplinary",
            )
        )
        await session.commit()

    route = "/api/v1/hr/cases"
    request = {
        "case_code": f"CASE-{uuid4().hex[:10]}",
        "employee_id": str(subject),
        "case_type": "grievance",
        "title": "Synthetic case title",
        "details": "synthetic-private-case-detail",
    }
    async with _client() as client:
        owner = _auth(await _login(client, owner_email, password))
        outsider = _auth(await _login(client, outsider_email, password))
        director = _auth(await _login(client, director_email, password))
        assert (await client.get(route, headers=director)).status_code == 403
        assert (await client.post(route, json=request, headers=outsider)).status_code == 403
        created = await client.post(route, json=request, headers=owner)
        assert created.status_code == 201, created.text
        assert created.headers["cache-control"] == "no-store"
        protected_url = f"/api/v1/hr/documents/{restricted_file}"
        assert (await client.get(protected_url, headers=owner)).status_code == 404
        assert (await client.get(f"{protected_url}/download", headers=owner)).status_code == 404
        case_id = UUID(created.json()["id"])
        detail = f"{route}/{case_id}"
        assert created.json()["details_plain"] == request["details"]
        assert (await client.get(route, headers=outsider)).json() == {"items": [], "total": 0}
        assert (await client.get(detail, headers=outsider)).status_code == 404
        assert (
            await client.post(
                f"{detail}/close",
                json={"status": "closed", "expected_state_sha256": "0" * 64},
                headers=outsider,
            )
        ).status_code == 404

        listing = (await client.get(route, headers=owner, params={"limit": 1})).json()
        assert listing["total"] == 1
        assert listing["items"][0]["id"] == str(case_id)
        assert listing["items"][0]["details_plain"] is None
        first_review = await client.get(detail, headers=owner)
        assert first_review.json()["details_plain"] == request["details"]
        first_digest = first_review.headers["x-hr-case-review"]

        # Omitting or supplying a stale review digest must fail closed without mutating the case.
        assert (
            await client.post(
                f"{detail}/close",
                json={"status": "investigating"},
                headers=owner,
            )
        ).status_code == 422
        stale_review = await client.post(
            f"{detail}/close",
            json={"status": "investigating", "expected_state_sha256": "0" * 64},
            headers=owner,
        )
        assert stale_review.status_code == 409
        assert stale_review.json()["error_code"] == "HR_CASE_REVIEW_STALE"

        notes = "synthetic-private-resolution-text"
        response = await client.post(
            f"{detail}/close",
            json={
                "status": "investigating",
                "resolution_notes": notes,
                "expected_state_sha256": first_digest,
            },
            headers=owner,
        )
        assert response.status_code == 200, response.text
        from app.schemas.hr import HrCaseResponse

        investigating_digest = HrCaseResponse.model_validate(
            response.json()
        ).reviewed_state_sha256()
        assert investigating_digest != first_digest
        # Reusing the pre-update digest is rejected as stale.
        assert (
            await client.post(
                f"{detail}/close",
                json={"status": "closed", "expected_state_sha256": first_digest},
                headers=owner,
            )
        ).status_code == 409
        closed = await asyncio.gather(
            *[
                client.post(
                    f"{detail}/close",
                    json={"status": "closed", "expected_state_sha256": investigating_digest},
                    headers=owner,
                )
                for _ in range(2)
            ]
        )
        assert sorted(response.status_code for response in closed) == [200, 409]
        result = (await client.get(detail, headers=owner)).json()
        assert result["resolution_notes"] == notes and result["status"] == "closed"
        assert (await client.get(route, headers=owner)).json()["items"][0][
            "resolution_notes"
        ] is None

        legacy = uuid4()
        async with AsyncSessionLocal() as session:
            session.add(
                HrCase(
                    id=legacy,
                    case_code=f"LEGACY-{legacy.hex[:10]}",
                    case_type="grievance",
                    title="Synthetic historical case",
                    opened_by_id=UUID(owner_id),
                    status="closed",
                    details_encrypted=encrypt_hr_value("synthetic legacy detail"),
                    resolution_notes="synthetic legacy plaintext",
                )
            )
            await session.commit()
        historic = await client.get(f"{route}/{legacy}", headers=owner)
        assert historic.status_code == 200
        assert historic.json()["resolution_notes"] == "synthetic legacy plaintext"
        assert (await client.get(f"{route}/{legacy}", headers=outsider)).status_code == 404

    async with AsyncSessionLocal() as session:
        record = await session.get(HrCase, case_id)
        assert record is not None and record.resolution_notes is not None
        assert request["details"] not in record.details_encrypted
        assert notes not in record.resolution_notes
        assert record.resolution_notes.startswith("hr-case-fernet-v1:")
        audit = list(
            await session.scalars(
                select(ActivityLog).where(
                    ActivityLog.entity_type == "hr_cases", ActivityLog.entity_id == case_id
                )
            )
        )
        assert sum(event.action == "hr.case.closed" for event in audit) == 1
        assert sum(event.action == "hr.case.read" for event in audit) == 2
        assert all(notes not in repr(event.new_values) for event in audit)


@pytest.mark.asyncio
async def test_case_cli_checks_the_reviewed_state_inside_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await skip_if_database_unavailable()
    monkeypatch.setenv("GARRISON_API_BASE_URL", "http://127.0.0.1:8425")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        "hr_manager",
        ROLE_PERMISSIONS["hr_manager"] | {PERMISSION_HR_CASES_RESTRICTED},
    )
    owner_id, owner_email, password = await _create_portal_user("hr_manager")
    _, other_email, _ = await _create_portal_user("hr_manager", password)
    route = "/api/v1/hr/cases"
    title = "synthetic confidential case title"
    detail = "synthetic restricted case narrative"
    note = "synthetic restricted resolution"
    concurrent_note = "synthetic note from second tab"
    code = f"CLI-CASE-{uuid4().hex[:8]}"

    async with _client() as api:
        owner = await _login(api, owner_email, password)
        other = await _login(api, other_email, password)
        loop = asyncio.get_running_loop()
        inject_change = False

        async def send(request: httpx.Request) -> httpx.Response:
            nonlocal inject_change
            path = request.url.raw_path.decode("ascii")
            if inject_change and request.method == "POST" and path.endswith("/close"):
                inject_change = False
                incoming = json.loads(request.content)
                changed = await api.post(
                    path,
                    headers=_auth(owner),
                    json={
                        "status": "investigating",
                        "resolution_notes": concurrent_note,
                        "expected_state_sha256": incoming["expected_state_sha256"],
                    },
                )
                assert changed.status_code == 200, changed.text
            return await api.request(
                request.method, path, headers=request.headers, content=request.content
            )

        def transport(request: httpx.Request) -> httpx.Response:
            result = asyncio.run_coroutine_threadsafe(send(request), loop).result(timeout=10)
            return httpx.Response(
                result.status_code, headers=result.headers, content=result.content
            )

        async def invoke(token: str, *args: str, expected: int = 0) -> dict:
            monkeypatch.setenv("GARRISON_ACCESS_TOKEN", token)
            stdout, stderr = io.StringIO(), io.StringIO()
            status = await asyncio.to_thread(
                garrisonctl.run,
                ["hr", "cases", *args, "--json"],
                transport=httpx.MockTransport(transport),
                stdout=stdout,
                stderr=stderr,
            )
            output = stdout.getvalue() + stderr.getvalue()
            assert all(
                value not in output for value in (title, detail, note, concurrent_note, code)
            )
            assert status == expected, output
            return json.loads(stdout.getvalue())

        request_file = tmp_path / "case.json"
        request_file.touch(mode=0o600)
        request_file.write_text(
            json.dumps(
                {
                    "case_code": code,
                    "case_type": "grievance",
                    "title": title,
                    "details": detail,
                }
            )
        )
        submit = ("open", "--file", str(request_file))
        plan = (await invoke(owner, *submit, "--dry-run"))["data"]
        apply = (*submit, "--apply", "--expect", plan["plan_sha256"])
        await invoke(other, *apply, expected=CONFLICT)
        pending = (await invoke(owner, *apply))["data"]
        assert pending["opened_by_id"] == owner_id and pending["status"] == "open"
        await invoke(owner, *apply, expected=CONFLICT)
        assert (await invoke(owner, "list"))["data"]["total"] == 1
        assert (await invoke(other, "list"))["data"] == {"items": [], "total": 0}
        show = ("show", "--case-id", pending["id"])
        await invoke(other, *show, expected=CONFLICT)
        review = tmp_path / "review.json"
        await invoke(owner, *show, "--output", str(review))
        assert stat.S_IMODE(review.stat().st_mode) == 0o600
        assert json.loads(review.read_text())["details_plain"] == detail
        state = tmp_path / "state.json"
        state.touch(mode=0o600)
        state.write_text(json.dumps({"status": "investigating", "resolution_notes": f" {note} "}))
        update = ("update", "--review-file", str(review), "--file", str(state))
        plan = (await invoke(owner, *update, "--dry-run"))["data"]
        investigated = (await invoke(owner, *update, "--apply", "--expect", plan["plan_sha256"]))[
            "data"
        ]
        assert investigated["status"] == "investigating"
        await invoke(owner, *update, "--dry-run", expected=CONFLICT)
        review.unlink()
        await invoke(owner, *show, "--output", str(review))
        assert json.loads(review.read_text())["resolution_notes"] == note
        state.write_text(json.dumps({"status": "closed"}))
        plan = (await invoke(owner, *update, "--dry-run"))["data"]
        inject_change = True
        failure = await invoke(
            owner, *update, "--apply", "--expect", plan["plan_sha256"], expected=CONFLICT
        )
        assert failure["errors"][0]["details"]["error_code"] == "HR_CASE_REVIEW_STALE"
        review.unlink()
        await invoke(owner, *show, "--output", str(review))
        assert json.loads(review.read_text())["resolution_notes"] == concurrent_note
        plan = (await invoke(owner, *update, "--dry-run"))["data"]
        closed = (await invoke(owner, *update, "--apply", "--expect", plan["plan_sha256"]))["data"]
        assert closed["status"] == "closed" and closed["closed_by_id"] == owner_id
        result = await api.get(f"{route}/{closed['id']}", headers=_auth(owner))
        assert result.json()["resolution_notes"] == concurrent_note
