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
from scripts.garrisonctl_common import AUTH, CONFLICT
from tests.test_hr import _auth, _client, _create_portal_user, _login, skip_if_database_unavailable
from tests.test_hr import hr_fernet_env as hr_fernet_env
from tests.test_hr import isolated_engine_pool as isolated_engine_pool


def test_compensation_cli_steps_and_protects_private_terms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)

    proposer, reviewer, outsider, employee, term = (str(uuid4()) for _ in range(5))
    actor = proposer
    grants = ["hr:payroll:sensitive", "hr:payroll:approve"]
    prefix = "/api/v1/hr/compensation"
    proposal = {
        "employee_id": employee,
        "effective_from": "2026-11-01",
        "currency": "LKR",
        "pay_frequency": "monthly",
        "base_salary": "123456.78",
        "allowances_json": {"restrictedAllowance": "201.25"},
    }
    term_row: dict | None = None
    writes = []
    revealed_reads = []
    submitted = tmp_path / "proposed.json"
    submitted.touch(mode=0o600)
    submitted.write_text(json.dumps(proposal))
    downloaded = tmp_path / "review.json"
    decision = tmp_path / "decision.json"
    decision.touch(mode=0o600)
    decision.write_text(json.dumps({"decision": "approve"}))

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal term_row
        route = request.url.path
        if route == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": grants})
        if request.method == "GET":
            assert route == f"{prefix}/{employee}"
            items = []
            if term_row is not None:
                row = dict(term_row)
                if request.url.params.get("term_id"):
                    assert request.url.params["term_id"] == term
                if request.url.params.get("reveal_sensitive") == "true":
                    revealed_reads.append(actor)
                else:
                    row.update(base_salary_plain=None, allowances_json=None, rejection_reason=None)
                items.append(row)
            return httpx.Response(200, json={"items": items, "total": len(items)})

        writes.append(route)
        payload = json.loads(request.content)
        if route == prefix:
            assert payload == proposal
            term_row = {
                "id": term,
                "employee_id": employee,
                "effective_from": proposal["effective_from"],
                "currency": proposal["currency"],
                "pay_frequency": proposal["pay_frequency"],
                "base_salary_plain": proposal["base_salary"],
                "base_salary_masked": "********",
                "allowances_json": proposal["allowances_json"],
                "approval_status": "proposed",
                "is_current": False,
                "proposed_by_id": proposer,
                "approved_by_id": None,
                "approved_at": None,
                "created_at": "2026-11-17T09:00:00Z",
            }
            return httpx.Response(201, json=term_row)
        assert route == f"{prefix}/{term}/decision"
        assert payload == {"decision": "approve", "reason": None}
        assert term_row is not None
        term_row.update(
            approval_status="approved",
            is_current=True,
            approved_by_id=actor,
            approved_at="2026-11-17T09:20:00Z",
        )
        return httpx.Response(200, json=term_row)

    def invoke(*args: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "compensation", *args, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert all(
            value not in stdout.getvalue() + stderr.getvalue()
            for value in ("123456.78", "201.25", "restrictedAllowance")
        )
        return code, json.loads(stdout.getvalue())

    code, preview = invoke("propose", "--file", str(submitted), "--dry-run")
    assert code == 0 and not writes and not revealed_reads
    plan = preview["data"]["plan_sha256"]
    actor = outsider
    assert invoke("propose", "--file", str(submitted), "--apply", "--expect", plan)[0] == CONFLICT
    assert not writes
    actor = proposer
    assert invoke("propose", "--file", str(submitted), "--apply", "--expect", plan)[0] == 0
    assert writes == [prefix]
    assert revealed_reads == [proposer]

    code, listing = invoke("list", "--employee-id", employee)
    assert code == 0 and listing["data"]["items"][0]["approval_status"] == "proposed"
    assert revealed_reads == [proposer]
    assert invoke("show", "--employee-id", employee, "--term-id", term)[0] == 0
    assert revealed_reads == [proposer]
    actor = reviewer
    show = ("show", "--employee-id", employee, "--term-id", term, "--output", str(downloaded))
    assert invoke(*show)[0] == 0
    assert json.loads(downloaded.read_text())["base_salary_plain"] == proposal["base_salary"]
    assert stat.S_IMODE(downloaded.stat().st_mode) == 0o600

    arguments = ("decide", "--file", str(decision), "--review-file", str(downloaded))
    actor = proposer
    assert invoke(*arguments, "--dry-run")[0] == CONFLICT
    actor = reviewer
    grants = ["hr:payroll:sensitive"]
    assert invoke(*arguments, "--dry-run")[0] == AUTH
    grants.append("hr:payroll:approve")
    code, review = invoke(*arguments, "--dry-run")
    assert code == 0 and writes == [prefix]
    expected = review["data"]["plan_sha256"]
    assert term_row is not None
    term_row["base_salary_plain"] = "999999.99"
    assert invoke(*arguments, "--apply", "--expect", expected)[0] == CONFLICT
    assert writes == [prefix]
    term_row["base_salary_plain"] = proposal["base_salary"]
    code, result = invoke(*arguments, "--apply", "--expect", expected)
    assert code == 0
    assert result["data"]["approved_by_id"] == reviewer
    assert writes == [prefix, f"{prefix}/{term}/decision"]
    assert invoke(*arguments, "--apply", "--expect", expected)[0] == CONFLICT
    assert writes == [prefix, f"{prefix}/{term}/decision"]


@pytest.mark.asyncio
async def test_compensation_cli_with_real_hr_api(
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
    _, maker_email, password = await _create_portal_user("hr_manager")
    reviewer_id, reviewer_email, _ = await _create_portal_user("hr_manager")
    salary = "45678.29"
    async with _client() as api:
        maker = await _login(api, maker_email, password)
        reviewer = await _login(api, reviewer_email, password)
        person = await api.post(
            "/api/v1/hr/employees",
            headers=_auth(maker),
            json={
                "employee_code": f"CLI-SAL-{uuid4().hex[:10]}",
                "first_name": "Synthetic",
                "last_name": "CLI Compensation",
            },
        )
        assert person.status_code == 201, person.text
        employee = person.json()["id"]

        proposed = tmp_path / "new-term.json"
        proposed.touch(mode=0o600)
        proposed.write_text(
            json.dumps(
                {
                    "employee_id": employee,
                    "effective_from": "2026-11-01",
                    "currency": "LKR",
                    "base_salary": salary,
                    "pay_frequency": "monthly",
                }
            )
        )
        review = tmp_path / "term-review.json"
        decision = tmp_path / "term-decision.json"
        decision.touch(mode=0o600)
        decision.write_text('{"decision":"approve"}')

        loop = asyncio.get_running_loop()

        def transport(request: httpx.Request) -> httpx.Response:
            path = request.url.raw_path.decode("ascii")
            result = asyncio.run_coroutine_threadsafe(
                api.request(
                    request.method,
                    path,
                    headers=request.headers,
                    content=request.content,
                ),
                loop,
            ).result(timeout=10)
            return httpx.Response(
                result.status_code, headers=result.headers, content=result.content
            )

        async def invoke(token: str, *args: str) -> dict:
            monkeypatch.setenv("GARRISON_ACCESS_TOKEN", token)
            stdout, stderr = io.StringIO(), io.StringIO()
            code = await asyncio.to_thread(
                garrisonctl.run,
                ["hr", "compensation", *args, "--json"],
                transport=httpx.MockTransport(transport),
                stdout=stdout,
                stderr=stderr,
            )
            assert salary not in stdout.getvalue() + stderr.getvalue()
            assert code == 0, stdout.getvalue() + stderr.getvalue()
            return json.loads(stdout.getvalue())["data"]

        args = ("propose", "--file", str(proposed))
        plan = await invoke(maker, *args, "--dry-run")
        term = await invoke(maker, *args, "--apply", "--expect", plan["plan_sha256"])
        assert term["approval_status"] == "proposed"
        result = await invoke(
            reviewer,
            "show",
            "--employee-id",
            employee,
            "--term-id",
            term["id"],
            "--output",
            str(review),
        )
        assert result["id"] == term["id"]
        assert json.loads(review.read_text())["base_salary_plain"] == salary
        review_args = ("decide", "--file", str(decision), "--review-file", str(review))
        plan = await invoke(reviewer, *review_args, "--dry-run")
        applied = await invoke(reviewer, *review_args, "--apply", "--expect", plan["plan_sha256"])
        assert applied["approved_by_id"] == reviewer_id and applied["approval_status"] == "approved"
