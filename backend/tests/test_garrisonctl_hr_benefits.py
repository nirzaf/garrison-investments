import asyncio
import io
import json
import stat
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.utils.permissions import (
    PERMISSION_HR_PAYROLL_APPROVE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    ROLE_PERMISSIONS,
)
from scripts import garrisonctl
from scripts.garrisonctl_common import CONFLICT
from tests.test_hr import _auth, _client, _create_portal_user, _login, skip_if_database_unavailable
from tests.test_hr import hr_fernet_env as hr_fernet_env
from tests.test_hr import isolated_engine_pool as isolated_engine_pool


@pytest.mark.asyncio
async def test_benefit_cli_review_and_coverage_through_hr_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await skip_if_database_unavailable()
    monkeypatch.setenv("GARRISON_API_BASE_URL", "http://127.0.0.1:8425")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        "hr_manager",
        ROLE_PERMISSIONS["hr_manager"]
        | {PERMISSION_HR_PAYROLL_APPROVE, PERMISSION_HR_PAYROLL_SENSITIVE},
    )
    maker_id, maker_email, password = await _create_portal_user("hr_manager")
    reviewer_id, reviewer_email, _ = await _create_portal_user("hr_manager")
    ceiling = "24680.57"
    notes = "synthetic-restricted-coverage-note"
    async with _client() as api:
        maker = await _login(api, maker_email, password)
        reviewer = await _login(api, reviewer_email, password)
        person = await api.post(
            "/api/v1/hr/employees",
            headers=_auth(maker),
            json={
                "employee_code": f"CLI-BEN-{uuid4().hex[:10]}",
                "first_name": "Synthetic",
                "last_name": "Benefit Coverage",
            },
        )
        assert person.status_code == 201, person.text
        employee = person.json()["id"]
        proposal = tmp_path / "benefit-proposal.json"
        proposal.touch(mode=0o600)
        code = f"cli-ben-{uuid4().hex[:10]}"
        proposal.write_text(
            json.dumps(
                {
                    "code": code,
                    "name": "Synthetic capped coverage",
                    "category": "transport",
                    "reimbursement_ceiling": ceiling,
                    "reimbursement_currency": "LKR",
                    "allows_advances": True,
                }
            )
        )
        snapshot = tmp_path / "benefit-review.json"
        bind = tmp_path / "assignment.json"
        bind.touch(mode=0o600)

        loop = asyncio.get_running_loop()

        def route(request: httpx.Request) -> httpx.Response:
            result = asyncio.run_coroutine_threadsafe(
                api.request(
                    request.method,
                    request.url.raw_path.decode("ascii"),
                    headers=request.headers,
                    content=request.content,
                ),
                loop,
            ).result(timeout=10)
            return httpx.Response(
                result.status_code, headers=result.headers, content=result.content
            )

        async def invoke(token: str, *args: str, expected: int = 0) -> dict:
            monkeypatch.setenv("GARRISON_ACCESS_TOKEN", token)
            stdout, stderr = io.StringIO(), io.StringIO()
            status = await asyncio.to_thread(
                garrisonctl.run,
                ["hr", "benefits", *args, "--json"],
                transport=httpx.MockTransport(route),
                stdout=stdout,
                stderr=stderr,
            )
            output = stdout.getvalue() + stderr.getvalue()
            assert ceiling not in output and notes not in output
            assert status == expected, output
            return json.loads(stdout.getvalue()).get("data") or {}

        propose = ("types", "propose", "--file", str(proposal))
        plan = await invoke(maker, *propose, "--dry-run")
        await invoke(
            reviewer, *propose, "--apply", "--expect", plan["plan_sha256"], expected=CONFLICT
        )
        pending = await invoke(maker, *propose, "--apply", "--expect", plan["plan_sha256"])
        assert pending["code"] == code.upper() and pending["proposed_by_id"] == maker_id
        assert pending["has_ceiling"] is True and pending["approved_at"] is None
        benefit_id = pending["id"]

        bind.write_text(
            json.dumps(
                {
                    "employee_id": employee,
                    "benefit_type_id": benefit_id,
                    "effective_from": "2026-11-01",
                    "effective_to": "2026-11-30",
                    "coverage_notes": notes,
                }
            )
        )
        coverage = ("assignments", "create", "--file", str(bind))
        await invoke(maker, *coverage, "--dry-run", expected=CONFLICT)
        await invoke(
            reviewer,
            "types",
            "show",
            "--benefit-type-id",
            benefit_id,
            "--output",
            str(snapshot),
        )
        approved_snapshot = snapshot.read_text()
        assert json.loads(approved_snapshot)["reimbursement_ceiling"] == ceiling
        assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
        approve = ("types", "approve", "--review-file", str(snapshot))
        await invoke(maker, *approve, "--dry-run", expected=CONFLICT)
        snapshot.write_text(approved_snapshot.replace(ceiling, "99999.00"))
        await invoke(reviewer, *approve, "--dry-run", expected=CONFLICT)
        snapshot.write_text(approved_snapshot)
        plan = await invoke(reviewer, *approve, "--dry-run")
        outcome = await invoke(reviewer, *approve, "--apply", "--expect", plan["plan_sha256"])
        assert outcome["approved_by_id"] == reviewer_id

        plan = await invoke(maker, *coverage, "--dry-run")
        assigned = await invoke(maker, *coverage, "--apply", "--expect", plan["plan_sha256"])
        assert assigned["employee_id"] == employee and assigned["benefit_type_id"] == benefit_id
        await invoke(
            maker, *coverage, "--apply", "--expect", plan["plan_sha256"], expected=CONFLICT
        )
        listing = await invoke(maker, "assignments", "list", "--employee-id", employee)
        assert listing["total"] == 1 and listing["items"][0]["id"] == assigned["id"]
        actual = await api.get(
            "/api/v1/hr/benefits/assignments",
            params={"employee_id": employee},
            headers=_auth(maker),
        )
        assert actual.json()["items"][0]["coverage_notes"] == notes
