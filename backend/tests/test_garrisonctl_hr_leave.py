import io
import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


def test_leave_cli_uses_single_request_and_verifies_persisted_reversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    operator, leave = (str(uuid4()) for _ in range(2))
    path = f"/api/v1/hr/leave/requests/{leave}/decision"
    row: dict[str, Any] = {
        "id": leave, "status": "approved", "record_revision": 3,
        "manager_recommendation": None, "decided_by_id": operator,
    }
    private_notes = "Synthetic private absence notes"
    writes = []

    def request_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200, json={"id": operator, "permissions": ["hr:leave:approve"]}
            )
        assert request.url.path == path
        if request.method == "GET":
            return httpx.Response(200, json=row)
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload == {
            "decision": "cancelled", "expected_revision": row["record_revision"],
            "notes": private_notes,
        }
        writes.append(payload)
        row.update(status="cancelled", record_revision=row["record_revision"] + 1)
        return httpx.Response(200, json={**row, "decision_notes": private_notes})

    def invoke(*options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [
                "hr", "leave", "requests", "decide", "--leave-request-id", leave,
                "--decision", "cancelled", "--notes", private_notes, *options, "--json",
            ],
            transport=httpx.MockTransport(request_handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert private_notes not in stdout.getvalue() + stderr.getvalue()
        return code, json.loads(stdout.getvalue())

    code, preview = invoke("--dry-run")
    assert code == 0 and not writes
    row["record_revision"] += 1
    assert invoke("--apply", "--expect", preview["data"]["plan_sha256"])[0] == 4
    assert not writes
    code, preview = invoke("--dry-run")
    assert code == 0
    code, result = invoke("--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and result["data"] == row and result["changed"]
    assert row["status"] == "cancelled" and len(writes) == 1


def test_supervisor_leave_review_cli_uses_current_scoped_revision_without_hr_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    operator, leave = str(uuid4()), str(uuid4())
    item: dict[str, Any] = {
        "id": leave,
        "employee_name": "Synthetic Worker",
        "start_date": "2026-12-01",
        "end_date": "2026-12-02",
        "chargeable_units": "2.00",
        "is_half_day": False,
        "status": "submitted",
        "record_revision": 1,
    }
    writes: list[dict[str, Any]] = []

    def request_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": operator, "permissions": []})
        if request.url.path == "/api/v1/hr/me/leave-reviews" and request.method == "GET":
            return httpx.Response(
                200,
                json={"items": [item], "total": 1, "offset": 0, "limit": 100},
            )
        assert request.url.path == f"/api/v1/hr/me/leave-reviews/{leave}/decision"
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload == {
            "decision": "approved",
            "expected_revision": item["record_revision"],
            "notes": None,
        }
        writes.append(payload)
        item.update(status="approved", record_revision=item["record_revision"] + 1)
        return httpx.Response(
            200,
            json={
                **item,
                "allowed_actions": [],
                "route_status": "final",
            },
        )

    def invoke(*options: str) -> tuple[int, dict[str, Any]]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [
                "hr",
                "leave",
                "reviews",
                "decide",
                "--leave-request-id",
                leave,
                "--expected-revision",
                str(item["record_revision"]),
                "--decision",
                "approved",
                *options,
                "--json",
            ],
            transport=httpx.MockTransport(request_handler),
            stdout=stdout,
            stderr=stderr,
        )
        return code, json.loads(stdout.getvalue())

    code, preview = invoke("--dry-run")
    assert code == 0 and preview["outcome"] == "preview" and not writes
    # A stale plan must not decide the newly revised request.
    item["record_revision"] = 2
    stale_code = garrisonctl.run(
        [
            "hr",
            "leave",
            "reviews",
            "decide",
            "--leave-request-id",
            leave,
            "--expected-revision",
            "1",
            "--decision",
            "approved",
            "--apply",
            "--expect",
            preview["data"]["plan_sha256"],
            "--json",
        ],
        transport=httpx.MockTransport(request_handler),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert stale_code == 4 and not writes

    code, current_preview = invoke("--dry-run")
    assert code == 0
    code, result = invoke("--apply", "--expect", current_preview["data"]["plan_sha256"])
    assert code == 0 and result["data"]["status"] == "approved"
    assert result["data"]["record_revision"] == 3
    assert result["data"]["route_status"] == "final"
    assert len(writes) == 1


def test_leave_baseline_cli_binds_apply_to_preview_and_reads_back_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.setenv("GARRISON_ENVIRONMENT", "local")
    operator, employee, leave_type = (str(uuid4()) for _ in range(3))
    digest, receipt = "a" * 64, str(uuid4())
    applied = False

    def request_handler(request: httpx.Request) -> httpx.Response:
        nonlocal applied
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200, json={"id": operator, "permissions": ["hr:leave:approve"]}
            )
        if request.url.path == "/api/v1/hr/leave/entitlement-baseline/preview":
            return httpx.Response(
                200,
                json={
                    "employee_id": employee,
                    "leave_type_id": leave_type,
                    "year": 2026,
                    "as_of_date": "2026-11-26",
                    "current_balance": "1.00",
                    "verified_balance": "5.00",
                    "adjustment_days": "4.00",
                    "recognized_due_dates": [],
                    "supporting_reference": "ROSTER-REVIEW-1",
                    "digest": digest,
                    "receipt_id": receipt if applied else None,
                },
            )
        assert request.url.path == "/api/v1/hr/leave/entitlement-baseline/apply"
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload["expected_digest"] == digest
        applied = True
        return httpx.Response(
            200,
            json={
                "employee_id": employee,
                "leave_type_id": leave_type,
                "year": 2026,
                "as_of_date": "2026-11-26",
                "current_balance": "1.00",
                "verified_balance": "5.00",
                "adjustment_days": "4.00",
                "recognized_due_dates": [],
                "supporting_reference": "ROSTER-REVIEW-1",
                "digest": digest,
                "receipt_id": receipt,
            },
        )

    args = [
        "hr",
        "leave",
        "baseline",
        "apply",
        "--employee-id",
        employee,
        "--leave-type-id",
        leave_type,
        "--year",
        "2026",
        "--as-of-date",
        "2026-11-26",
        "--verified-balance",
        "5.00",
        "--supporting-reference",
        "ROSTER-REVIEW-1",
    ]

    def invoke(*options: str) -> tuple[int, dict[str, Any]]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [*args, *options, "--json"],
            transport=httpx.MockTransport(request_handler),
            stdout=stdout,
            stderr=stderr,
        )
        return code, json.loads(stdout.getvalue())

    code, preview = invoke("--dry-run")
    assert code == 0 and preview["outcome"] == "preview" and not applied
    code, result = invoke("--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and result["changed"] and applied
    assert result["data"]["receipt_id"] == receipt


@pytest.mark.parametrize(
    ("command", "route_action", "route_status", "extra", "expected_payload"),
    [
        (
            "fallback",
            "fallback",
            "hr_fallback",
            [
                "--reason-code",
                "manager_absent",
                "--reason",
                "Synthetic manager absence",
            ],
            {
                "reason_code": "manager_absent",
                "reason": "Synthetic manager absence",
                "until": None,
            },
        ),
        (
            "refresh-route",
            "refresh",
            "supervisor",
            [],
            {},
        ),
    ],
)
def test_leave_route_cli_requires_preview_and_reads_back_current_revision(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    route_action: str,
    route_status: str,
    extra: list[str],
    expected_payload: dict[str, Any],
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.setenv("GARRISON_ENVIRONMENT", "local")
    operator, leave = str(uuid4()), str(uuid4())
    revision = 4
    decision_state: dict[str, Any] = {
        "id": leave,
        "status": "submitted",
        "record_revision": revision,
        "route_status": "stale",
        "allowed_actions": ["fallback", "refresh_route"],
    }
    writes: list[dict[str, Any]] = []
    endpoint_action = "fallback" if route_action == "fallback" else "route-refresh"
    expected_route = f"/api/v1/hr/leave/requests/{leave}/{endpoint_action}"

    def request_handler(request: httpx.Request) -> httpx.Response:
        nonlocal decision_state
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200,
                json={"id": operator, "permissions": ["hr:leave:approve"]},
            )
        if request.method == "GET":
            assert request.url.path == f"/api/v1/hr/leave/requests/{leave}/decision"
            return httpx.Response(200, json=decision_state)
        assert request.method == "POST"
        assert request.url.path == expected_route
        payload = json.loads(request.content)
        assert payload["expected_revision"] == revision
        assert {key: payload.get(key) for key in expected_payload} == expected_payload
        writes.append(payload)
        decision_state = {
            **decision_state,
            "record_revision": revision + 1,
            "route_status": route_status,
            "allowed_actions": ["decide"],
        }
        return httpx.Response(200, json=decision_state)

    args = [
        "hr",
        "leave",
        "requests",
        command,
        "--leave-request-id",
        leave,
        "--expected-revision",
        str(revision),
        *extra,
    ]

    def invoke(*options: str) -> tuple[int, dict[str, Any]]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [*args, *options, "--json"],
            transport=httpx.MockTransport(request_handler),
            stdout=stdout,
            stderr=stderr,
        )
        return code, json.loads(stdout.getvalue())

    code, preview = invoke("--dry-run")
    assert code == 0 and preview["outcome"] == "preview" and not writes
    code, result = invoke("--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and result["changed"]
    assert result["data"]["record_revision"] == revision + 1
    assert result["data"]["route_status"] == route_status
    assert len(writes) == 1
