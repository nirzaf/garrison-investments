import asyncio
import io
import json
import stat
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.utils.permissions import (
    PERMISSION_HR_PAYROLL_APPROVE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    ROLE_PERMISSIONS,
)
from app.utils.time import business_today
from scripts import garrisonctl
from scripts.garrisonctl_common import CONFLICT
from tests.test_hr import (
    _auth,
    _client,
    _create_portal_user,
    _login,
    _pdf_bytes,
    skip_if_database_unavailable,
)
from tests.test_hr import hr_fernet_env as hr_fernet_env
from tests.test_hr import isolated_engine_pool as isolated_engine_pool


@pytest.mark.asyncio
async def test_cli_reimbursement_from_approved_receipt_to_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await skip_if_database_unavailable()
    monkeypatch.setenv("GARRISON_API_BASE_URL", "http://127.0.0.1:8425")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    roles = ROLE_PERMISSIONS["hr_manager"]
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        "hr_manager",
        roles | {PERMISSION_HR_PAYROLL_APPROVE, PERMISSION_HR_PAYROLL_SENSITIVE},
    )
    _, maker_email, password = await _create_portal_user("hr_manager")
    reviewer_id, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    _, recorder_email, _ = await _create_portal_user("hr_manager", password)
    _, director_email, _ = await _create_portal_user("managing_director", password)
    amount = "347.18"
    description = "synthetic restricted reimbursement description"
    notes = "synthetic restricted reimbursement decision"
    payment = "synthetic private external reference"
    base = "/api/v1/hr"

    def private_input(name: str, values: dict) -> Path:
        path = tmp_path / name
        path.touch(mode=0o600)
        path.write_text(json.dumps(values))
        return path

    async with _client() as api:
        maker = await _login(api, maker_email, password)
        reviewer = await _login(api, reviewer_email, password)
        recorder = await _login(api, recorder_email, password)
        director = await _login(api, director_email, password)

        async def create(path: str, payload: dict) -> dict:
            result = await api.post(f"{base}/{path}", headers=_auth(maker), json=payload)
            assert result.status_code == 201, result.text
            return result.json()

        employee = await create(
            "employees",
            {
                "employee_code": f"CLI-R-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Reimbursement",
            },
        )
        policy = await create(
            "benefits/types",
            {
                "code": f"CLI-R-{uuid4().hex[:8]}",
                "name": "Synthetic reimbursement",
                "category": "travel",
                "reimbursement_ceiling": "500.00",
                "reimbursement_currency": "LKR",
            },
        )
        approval = await api.post(
            f"{base}/benefits/types/{policy['id']}/approve", headers=_auth(reviewer)
        )
        assert approval.status_code == 200, approval.text
        today = business_today()
        coverage = await create(
            "benefits/assignments",
            {
                "employee_id": employee["id"],
                "benefit_type_id": policy["id"],
                "effective_from": today.isoformat(),
                "effective_to": (today + timedelta(days=10)).isoformat(),
            },
        )
        receipt = await api.post(
            f"{base}/documents",
            headers=_auth(maker),
            data={
                "employee_id": employee["id"],
                "title": "Synthetic reimbursement",
                "document_type": "reimbursement_receipt",
                "category": "compensation",
            },
            files={"file": ("receipt.pdf", _pdf_bytes("synthetic"), "application/pdf")},
        )
        assert receipt.status_code == 201, receipt.text
        document = receipt.json()
        approval = await api.post(
            f"{base}/documents/{document['id']}/versions/1/decision",
            headers=_auth(reviewer),
            json={"decision": "approve"},
        )
        assert approval.status_code == 200, approval.text

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
                ["hr", "reimbursement", *args, "--json"],
                transport=httpx.MockTransport(route),
                stdout=stdout,
                stderr=stderr,
            )
            output = stdout.getvalue() + stderr.getvalue()
            assert all(value not in output for value in (amount, description, notes, payment))
            assert status == expected, output
            return json.loads(stdout.getvalue()).get("data") or {}

        input_file = private_input(
            "request.json",
            {
                "idempotency_key": str(uuid4()),
                "employee_id": employee["id"],
                "claim_type": policy["code"].lower(),
                "benefit_assignment_id": coverage["id"],
                "claim_date": today.isoformat(),
                "amount": amount,
                "description": description,
                "receipt_document_id": document["id"],
                "receipt_version_number": 1,
            },
        )
        submit = ("submit", "--file", str(input_file))
        plan = await invoke(maker, *submit, "--dry-run")
        apply: tuple[str, ...] = (*submit, "--apply", "--expect", plan["plan_sha256"])
        await invoke(reviewer, *apply, expected=CONFLICT)
        claim = await invoke(maker, *apply)
        assert claim["status"] == "submitted"
        assert claim["receipt_version_id"] == document["versions"][0]["id"]
        assert (await invoke(maker, *apply))["id"] == claim["id"]
        request_data = json.loads(input_file.read_text())
        input_file.write_text(json.dumps({**request_data, "amount": "347.19"}))
        changed_plan = await invoke(maker, *submit, "--dry-run")
        await invoke(
            maker, *submit, "--apply", "--expect", changed_plan["plan_sha256"], expected=CONFLICT
        )
        listing = await invoke(maker, "list", "--employee-id", employee["id"])
        assert listing == {"items": [claim], "total": 1}

        claim_path = f"{base}/reimbursements/{claim['id']}"
        assert (await api.get(claim_path, headers=_auth(director))).status_code == 403
        assert (
            await api.get(f"{base}/reimbursements/{uuid4()}", headers=_auth(reviewer))
        ).status_code == 404
        review = tmp_path / "review.json"
        reference = ("--claim-id", claim["id"])
        await invoke(reviewer, "show", *reference, "--output", str(review))
        reviewed = review.read_text()
        assert stat.S_IMODE(review.stat().st_mode) == 0o600
        assert json.loads(reviewed)["description"] == description
        read = await api.get(claim_path, headers=_auth(reviewer))
        assert read.headers["cache-control"] == "no-store"

        decision = private_input("decision.json", {"decision": "approved", "notes": notes})
        decide = ("decide", "--review-file", str(review), "--file", str(decision))
        await invoke(maker, *decide, "--dry-run", expected=CONFLICT)
        review.write_text(reviewed.replace(amount, "347.19"))
        await invoke(reviewer, *decide, "--dry-run", expected=CONFLICT)
        review.write_text(reviewed)
        plan = await invoke(reviewer, *decide, "--dry-run")
        apply = (*decide, "--apply", "--expect", plan["plan_sha256"])
        await invoke(recorder, *apply, expected=CONFLICT)
        approved = await invoke(reviewer, *apply)
        assert approved["status"] == "approved" and approved["decided_by_id"] == reviewer_id
        await invoke(reviewer, *apply, expected=CONFLICT)

        payable_file = tmp_path / "payable.json"
        await invoke(recorder, "payable", *reference, "--output", str(payable_file))
        payable = json.loads(payable_file.read_text())
        settlement = private_input(
            "settlement.json",
            {
                "expected_payable_sha256": payable["reference_sha256"],
                "settlement_reference": payment,
                "settled_amount": amount,
                "settled_currency": "LKR",
            },
        )
        confirm = ("confirm-paid", *reference, "--settlement-file", str(settlement))
        plan = await invoke(recorder, *confirm, "--dry-run")
        paid = await invoke(recorder, *confirm, "--apply", "--expect", plan["plan_sha256"])
        assert paid["status"] == "paid"
        assert (await invoke(recorder, "show", *reference))["status"] == "paid"
