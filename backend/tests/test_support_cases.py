import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from app.api.v1.support import CSRF_COOKIE, SESSION_COOKIE
from app.database import AsyncSessionLocal
from app.models.support_cases import SupportCaseEvent, SupportOperatorGrant
from tests.test_auth import skip_if_database_unavailable
from tests.test_garrisonctl import invoke
from tests.test_support_custody import login
from tests.test_support_identity import API, SUPPORT_ORIGIN, client
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool

CASES = f"{API}/cases"


async def case_operator(browser: httpx.AsyncClient) -> UUID:
    operator, _, _ = await login(browser, custodian=False)
    async with AsyncSessionLocal() as session:
        session.add(SupportOperatorGrant(operator_id=operator, capability="cases.manage"))
        await session.commit()
    return operator


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_case_visibility_revision_and_audit() -> None:
    await skip_if_database_unavailable()
    async with client() as owner, client() as other, client() as no_grant:
        operator = await case_operator(owner)
        await case_operator(other)
        await login(no_grant, custodian=False)
        assert (await no_grant.get(CASES)).status_code == 403
        assert (await other.get(CASES)).json() == {"items": [], "next_cursor": None}

        payload = {
            "external_ref": f"incident-{uuid4()}",
            "severity": "high",
            "reason_code": "availability",
        }
        assert (
            await owner.post(CASES, json=payload, headers={"x-support-csrf": ""})
        ).status_code == 403
        first = await owner.post(CASES, json=payload)
        assert first.status_code == 201, first.text
        assert first.headers["cache-control"] == "no-store"
        case = first.json()
        assert case["owner_id"] == str(operator)
        assert case["status"] == "open"
        assert case["revision"] == 1
        assert (await owner.post(CASES, json=payload)).status_code == 409

        path = f"{CASES}/{case['id']}"
        blocked = await other.get(path)
        missing = await other.get(f"{CASES}/{uuid4()}")
        assert blocked.status_code == missing.status_code == 404
        assert blocked.json()["error_code"] == missing.json()["error_code"]
        assert (await owner.get(path)).json() == case

        assert (
            await owner.post(CASES, json={**payload, "external_ref": f"incident-{uuid4()}"})
        ).status_code == 201
        page = (await owner.get(CASES, params={"limit": 1})).json()
        cursor = page["next_cursor"]
        assert cursor
        second = await owner.get(CASES, params={"limit": 1, "cursor": cursor})
        assert [item["id"] for item in second.json()["items"]] == [case["id"]]
        assert second.json()["next_cursor"] is None
        assert (await other.get(CASES, params={"cursor": cursor})).status_code == 422
        assert (await owner.get(CASES, params={"cursor": "invalid"})).status_code == 422

        route = f"{path}/transitions"
        first_step = {"status": "investigating", "reason_code": "availability"}
        assert (await owner.post(route, json=first_step)).status_code == 422
        assert (
            await other.post(route, json=first_step, headers={"If-Match": '"1"'})
        ).status_code == 404
        assert (
            await owner.post(
                route, json={**first_step, "status": "mitigated"}, headers={"If-Match": '"1"'}
            )
        ).status_code == 409
        a, b = await asyncio.gather(
            owner.post(route, json=first_step, headers={"If-Match": '"1"'}),
            owner.post(route, json=first_step, headers={"If-Match": '"1"'}),
        )
        assert sorted((a.status_code, b.status_code)) == [200, 409]
        mitigated = await owner.post(
            route, json={**first_step, "status": "mitigated"}, headers={"If-Match": '"2"'}
        )
        assert mitigated.status_code == 200
        assert mitigated.json()["revision"] == 3
        assert (
            await owner.post(
                route, json={**first_step, "status": "closed"}, headers={"If-Match": '"3"'}
            )
        ).status_code == 422
        assert (await owner.get(path)).json()["status"] == "mitigated"
        async with AsyncSessionLocal() as session:
            events = await session.scalars(
                select(SupportCaseEvent)
                .where(SupportCaseEvent.case_id == UUID(case["id"]))
                .order_by(SupportCaseEvent.occurred_at)
            )
            history = list(events)
            assert all(event.operator_id == operator for event in history)
            assert [
                (event.status, event.revision)
                for event in history
                if event.action == "transitioned"
            ] == [("investigating", 2), ("mitigated", 3)]
            await session.execute(
                delete(SupportOperatorGrant).where(SupportOperatorGrant.operator_id == operator)
            )
            await session.commit()
        assert (await owner.get(path)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_cli_creates_transitions_and_respects_real_support_scope(tmp_path: Path) -> None:
    await skip_if_database_unavailable()
    tmp_path.chmod(0o700)
    loop = asyncio.get_running_loop()
    async with client() as owner, client() as other:
        await case_operator(owner)
        await case_operator(other)

        def private_file(path: Path, payload: dict[str, object]) -> str:
            path.write_text(json.dumps(payload))
            path.chmod(0o600)
            return str(path)

        def technical_flags(browser: httpx.AsyncClient, filename: str) -> list[str]:
            return ["--session-file", private_file(tmp_path / filename, {
                "origin": SUPPORT_ORIGIN, "support_token": browser.cookies[SESSION_COOKIE],
                "support_csrf": browser.cookies[CSRF_COOKIE],
            })]

        def bridge(req: httpx.Request) -> httpx.Response:
            assert req.url.host == "superadmin.garrisons.lk"
            request = owner.request(
                req.method, str(req.url), headers=req.headers, content=req.content,
            )
            result = asyncio.run_coroutine_threadsafe(request, loop).result(timeout=30)
            return httpx.Response(
                result.status_code, headers=result.headers, content=result.content,
            )

        async def change(command: list[str], body: dict[str, object], label: str) -> dict:
            args = [*command, *technical_flags(owner, "owner.json"), "--input",
                    private_file(tmp_path / f"{label}-input.json", body)]
            plan, receipt = tmp_path / f"{label}-plan.json", tmp_path / f"{label}-receipt.json"
            code, preview = await asyncio.to_thread(
                invoke, [*args, "--dry-run", "--output", str(plan)], bridge
            )
            assert code == 0, preview
            code, result = await asyncio.to_thread(invoke, [
                *args, "--apply", "--plan", str(plan), "--expect", preview["data"]["plan_sha256"],
                "--output", str(receipt),
            ], bridge)
            assert code == 0, result
            return json.loads(receipt.read_text())

        created = await change(["support", "cases", "create"], {
            "external_ref": f"synthetic-{uuid4()}", "reason_code": "functional", "severity": "low",
        }, "create")
        case = created["id"]
        assert created["revision"] == 1
        changed = await change(
            ["support", "cases", "transition", "--case", case],
            {"status": "investigating", "reason_code": "functional"}, "transition",
        )
        assert changed["revision"] == 2
        assert changed["status"] == "investigating"
        denied = tmp_path / "denied.json"
        result, envelope = await asyncio.to_thread(invoke, [
            "support", "cases", "show", "--case", case, "--output", str(denied),
            *technical_flags(other, "other.json"),
        ], bridge)
        assert result != 0 and envelope["errors"][0]["details"]["http_status"] == 404
        assert not denied.exists()
        async with AsyncSessionLocal() as db:
            events = await db.scalars(
                select(SupportCaseEvent.action).where(SupportCaseEvent.case_id == UUID(case))
            )
            assert {"created", "transitioned", "read"} <= set(events)
