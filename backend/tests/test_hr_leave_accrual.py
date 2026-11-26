import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine
from app.models.user import User
from app.schemas.hr import LeaveAccrualResponse
from app.services import hr_leave_accrual
from app.services.hr_leave_accrual import _credit, _prorated_credit
from app.utils.exceptions import AppException
from tests.test_hr import (
    _auth,
    _client,
    _create_portal_user,
    _login,
    _publish_leave_calendar,
    skip_if_database_unavailable,
)


@pytest.fixture(autouse=True)
async def isolated_pool():
    await engine.dispose()
    yield
    await engine.dispose()


def test_monthly_rounding_reconciles_to_annual_entitlement() -> None:
    annual = Decimal("10.01")
    monthly = [_credit(annual, month) for month in range(1, 13)]
    assert sum(monthly) == annual
    assert monthly[:2] == [Decimal("0.83"), Decimal("0.84")]
    assert _prorated_credit(Decimal("1.00"), 15, 29) == Decimal("0.52")
    assert _prorated_credit(Decimal("10.01"), 183, 366) == Decimal("5.01")


@pytest.mark.asyncio
async def test_paid_accrual_is_reviewed_idempotent_and_reconciled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    _, hr_email, password = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    _, staff_email, _ = await _create_portal_user("quantity_surveyor", password)
    base = "/api/v1/hr"
    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))
        staff = _auth(await _login(client, staff_email, password))

        async def employee(join_date: str) -> str:
            response = await client.post(
                f"{base}/employees",
                headers=hr,
                json={
                    "employee_code": f"AC-{uuid4().hex[:8]}",
                    "first_name": "Synthetic",
                    "last_name": "Accrual",
                    "employment_status": "active",
                    "join_date": join_date,
                },
            )
            assert response.status_code == 201, response.text
            return str(response.json()["id"])

        employee_id = await employee("2025-01-01")
        partial_employee = await employee("2025-02-15")
        leave_type = await client.post(
            f"{base}/leave/types",
            headers=hr,
            json={"code": f"L-{uuid4().hex[:6]}", "name": "Synthetic paid accrual"},
        )
        assert leave_type.status_code == 201
        leave_type_id = leave_type.json()["id"]
        proposal = await client.post(
            f"{base}/leave/policies",
            headers=hr,
            json={
                "code": f"P-{uuid4().hex[:6]}",
                "name": "Synthetic monthly entitlement",
                "leave_type_id": leave_type_id,
                "annual_entitlement_days": "10.01",
                "accrual_frequency": "monthly",
                "effective_from": "2025-01-01",
                "effective_to": "2025-12-31",
            },
        )
        assert proposal.status_code == 201, proposal.text
        policy_id = proposal.json()["id"]
        preview = f"{base}/leave/accrual/preview"
        apply = f"{base}/leave/accrual/apply"
        payload = {
            "employee_id": employee_id,
            "leave_type_id": leave_type_id,
            "year": 2025,
            "month": 2,
        }
        assert (await client.post(preview, headers=staff, json=payload)).status_code == 403
        assert (await client.post(preview, headers=hr, json=payload)).status_code == 404
        approved = await client.post(
            f"{base}/leave/policies/{policy_id}/decision",
            headers=reviewer,
            json={"decision": "approved"},
        )
        assert approved.status_code == 200, approved.text
        partial = await client.post(
            preview, headers=hr, json={**payload, "employee_id": partial_employee}
        )
        assert partial.json()["error_code"] == "LEAVE_ACCRUAL_EMPLOYMENT_PERIOD"
        annual = await client.post(preview, headers=hr, json={**payload, "month": None})
        assert annual.json()["error_code"] == "LEAVE_ACCRUAL_FREQUENCY"
        future = await client.post(preview, headers=hr, json={**payload, "year": 2100})
        assert future.status_code == 422
        quoted = await client.post(preview, headers=hr, json=payload)
        assert quoted.status_code == 200, quoted.text
        plan = quoted.json()
        assert plan["days"] == "0.84" and plan["policy_id"] == policy_id
        assert plan["ledger_entry_id"] is None
        posting = {**payload, "expected_digest": plan["digest"]}
        assert (await client.post(apply, headers=reviewer, json=posting)).status_code == 409
        responses = await asyncio.gather(
            *(client.post(apply, headers=hr, json=posting) for _ in range(2))
        )
        assert all(response.status_code == 200 for response in responses)
        receipt = responses[0].json()["ledger_entry_id"]
        assert receipt and responses[1].json()["ledger_entry_id"] == receipt
        readback = await client.post(preview, headers=reviewer, json=payload)
        assert readback.json()["ledger_entry_id"] == receipt and readback.json()["digest"] is None
        overlapping = await client.post(preview, headers=hr, json={**payload, "month": None})
        assert overlapping.status_code == 409
        balances = await client.get(
            f"{base}/leave/balances/{employee_id}?leave_year=2025", headers=hr
        )
        balance = next(
            row for row in balances.json()["items"] if row["leave_type_id"] == leave_type_id
        )
        assert Decimal(balance["balance_days"]) == Decimal("0.84")
        catch_up_employee = await employee("2025-01-01")
        catch_up_payload = {
            "employee_id": catch_up_employee,
            "leave_type_id": leave_type_id,
            "year": 2025,
            "start_month": 1,
            "end_month": 3,
        }
        catch_up = f"{base}/leave/accrual/catch-up"
        first_month = {**payload, "employee_id": catch_up_employee, "month": 1}
        first_quote = await client.post(preview, headers=hr, json=first_month)
        first_saved = await client.post(
            apply, headers=hr, json={**first_month, "expected_digest": first_quote.json()["digest"]}
        )
        assert first_saved.status_code == 200, first_saved.text
        assert (
            await client.post(f"{catch_up}/preview", headers=staff, json=catch_up_payload)
        ).status_code == 403
        assert (
            await client.post(
                f"{catch_up}/preview", headers=hr, json={**catch_up_payload, "start_month": 4}
            )
        ).status_code == 422
        range_preview = await client.post(f"{catch_up}/preview", headers=hr, json=catch_up_payload)
        assert range_preview.status_code == 200, range_preview.text
        range_plan = range_preview.json()
        assert range_plan["pending_days"] == "1.67"
        assert [item["ledger_entry_id"] for item in range_plan["periods"]] == [
            first_saved.json()["ledger_entry_id"],
            None,
            None,
        ]
        range_apply = {**catch_up_payload, "expected_digest": range_plan["digest"]}
        assert (
            await client.post(f"{catch_up}/apply", headers=reviewer, json=range_apply)
        ).status_code == 409
        assert (
            await client.post(f"{catch_up}/apply", headers=hr, json={**range_apply, "end_month": 4})
        ).status_code == 409
        unchanged = await client.post(f"{catch_up}/preview", headers=hr, json=catch_up_payload)
        assert unchanged.json() == range_plan
        record = hr_leave_accrual._record_accrual

        async def fail_on_last_credit(
            session: AsyncSession, quote: LeaveAccrualResponse, digest: str, actor: User
        ) -> LeaveAccrualResponse:
            saved = await record(session, quote, digest, actor)
            if quote.period_start.month == 3:
                raise AppException("Synthetic posting failure.", status_code=409)
            return saved

        with monkeypatch.context() as failure:
            failure.setattr(hr_leave_accrual, "_record_accrual", fail_on_last_credit)
            assert (
                await client.post(f"{catch_up}/apply", headers=hr, json=range_apply)
            ).status_code == 409
        after_rollback = await client.post(f"{catch_up}/preview", headers=hr, json=catch_up_payload)
        assert after_rollback.json() == range_plan

        range_responses = await asyncio.gather(
            *(client.post(f"{catch_up}/apply", headers=hr, json=range_apply) for _ in range(2))
        )
        assert all(response.status_code == 200 for response in range_responses)
        saved_range = range_responses[0].json()
        assert saved_range == range_responses[1].json()
        assert saved_range["digest"] is None
        assert len({item["ledger_entry_id"] for item in saved_range["periods"]}) == 3
        assert all(item["ledger_entry_id"] for item in saved_range["periods"])
        reviewer_readback = (
            await client.post(f"{catch_up}/preview", headers=reviewer, json=catch_up_payload)
        ).json()
        assert [item["ledger_entry_id"] for item in reviewer_readback["periods"]] == [
            item["ledger_entry_id"] for item in saved_range["periods"]
        ]
        assert all(item["outcome"] == "already_posted" for item in reviewer_readback["periods"])

        manual = {
            "employee_id": employee_id,
            "leave_type_id": leave_type_id,
            "entry_type": "opening_balance",
            "days_delta": "4",
            "leave_year": 2025,
            "reason": "Synthetic opening",
        }
        assert (
            await client.post(f"{base}/leave/ledger", headers=hr, json=manual)
        ).status_code == 409
        second_employee = await employee("2025-01-01")
        opening = await client.post(
            f"{base}/leave/ledger", headers=hr, json={**manual, "employee_id": second_employee}
        )
        assert opening.status_code == 201, opening.text
        blocked = await client.post(
            preview, headers=hr, json={**payload, "employee_id": second_employee}
        )
        assert blocked.json()["error_code"] == "LEAVE_ACCRUAL_MANUAL_BALANCE"

        rollover_preview = f"{base}/leave/rollover/preview"
        rollover_apply = f"{base}/leave/rollover/apply"
        rollover = {"employee_id": employee_id, "leave_type_id": leave_type_id, "source_year": 2025}
        assert (
            await client.post(rollover_preview, headers=staff, json=rollover)
        ).status_code == 403
        no_expiry = await client.post(rollover_preview, headers=hr, json=rollover)
        assert no_expiry.json()["error_code"] == "LEAVE_ROLLOVER_EXPIRY_NOT_APPROVED"
        closing = await client.post(
            f"{base}/leave/policies",
            headers=hr,
            json={
                "code": f"P-{uuid4().hex[:6]}",
                "name": "Permanent year-end rule",
                "leave_type_id": leave_type_id,
                "employment_category": "permanent",
                "annual_entitlement_days": "0",
                "accrual_frequency": "manual",
                "effective_from": "2025-12-31",
                "effective_to": "2025-12-31",
                "max_carry_forward_days": "0.50",
                "expire_excess_on_rollover": True,
            },
        )
        assert closing.status_code == 201
        decision = await client.post(
            f"{base}/leave/policies/{closing.json()['id']}/decision",
            headers=reviewer,
            json={"decision": "approved"},
        )
        assert decision.status_code == 200
        await _publish_leave_calendar(client, hr, reviewer, "2025-12-01", "2025-12-31")
        old_request = {
            "employee_id": employee_id,
            "leave_type_id": leave_type_id,
            "start_date": "2025-12-10",
            "end_date": "2025-12-10",
        }
        leave = await client.post(f"{base}/leave/requests", headers=hr, json=old_request)
        assert leave.status_code == 201
        pending = await client.post(rollover_preview, headers=hr, json=rollover)
        assert pending.json()["error_code"] == "LEAVE_ROLLOVER_PENDING_REQUESTS"
        adjustment = {**manual, "entry_type": "adjustment", "days_delta": "3"}
        assert (
            await client.post(f"{base}/leave/ledger", headers=hr, json=adjustment)
        ).status_code == 201
        leave_url = f"{base}/leave/requests/{leave.json()['id']}/decision"
        assert (
            await client.post(
                leave_url,
                headers=reviewer,
                json={
                    "decision": "approved",
                    "expected_revision": leave.json()["record_revision"],
                },
            )
        ).status_code == 200
        stale = await client.post(rollover_preview, headers=hr, json=rollover)
        assert stale.status_code == 200
        assert (
            await client.post(f"{base}/leave/ledger", headers=hr, json=adjustment)
        ).status_code == 201
        assert (
            await client.post(
                rollover_apply,
                headers=hr,
                json={**rollover, "expected_digest": stale.json()["digest"]},
            )
        ).status_code == 409
        quote = await client.post(rollover_preview, headers=hr, json=rollover)
        assert quote.status_code == 200, quote.text
        assert quote.json()["carried_days"] == "0.50"
        assert quote.json()["expired_days"] == "5.34"
        confirmation = {**rollover, "expected_digest": quote.json()["digest"]}
        results = await asyncio.gather(
            *(client.post(rollover_apply, headers=hr, json=confirmation) for _ in range(2))
        )
        assert all(row.status_code == 200 for row in results)
        assert results[0].json()["receipt_id"] == results[1].json()["receipt_id"]
        for year, expected in [(2025, "0"), (2026, "0.50")]:
            balances = await client.get(
                f"{base}/leave/balances/{employee_id}?leave_year={year}", headers=hr
            )
            balance = next(
                row for row in balances.json()["items"] if row["leave_type_id"] == leave_type_id
            )
            assert Decimal(balance["balance_days"]) == Decimal(expected)
        manual_late = await client.post(f"{base}/leave/ledger", headers=hr, json=adjustment)
        assert manual_late.json()["error_code"] == "LEAVE_YEAR_CLOSED"
        duplicate_carry = await client.post(
            f"{base}/leave/ledger",
            headers=hr,
            json={**manual, "leave_year": 2026, "entry_type": "carry_forward"},
        )
        assert duplicate_carry.json()["error_code"] == "LEAVE_ROLLOVER_ALREADY_POSTED"
        late_leave = await client.post(f"{base}/leave/requests", headers=hr, json=old_request)
        assert late_leave.json()["error_code"] == "LEAVE_YEAR_CLOSED"
        current = await client.get(
            f"{base}/leave/requests/{leave.json()['id']}/decision", headers=reviewer
        )
        assert current.status_code == 200, current.text
        late_cancel = await client.post(
            leave_url,
            headers=reviewer,
            json={
                "decision": "cancelled",
                "expected_revision": current.json()["record_revision"],
            },
        )
        assert late_cancel.json()["error_code"] == "LEAVE_YEAR_CLOSED"
        late_accrual = await client.post(preview, headers=hr, json={**payload, "month": 3})
        assert late_accrual.json()["error_code"] == "LEAVE_YEAR_CLOSED"


@pytest.mark.asyncio
async def test_scheduled_leave_accrual_uses_only_selected_reviewed_policies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date
    from types import SimpleNamespace
    from uuid import UUID

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.activity_log import ActivityLog
    from app.models.hr import HrLeaveAccrual, HrLeaveLedger
    from app.tasks import maintenance

    await skip_if_database_unavailable()
    fixed_today = date(2026, 3, 3)
    monkeypatch.setattr(maintenance, "business_today", lambda: fixed_today)
    monkeypatch.setattr(hr_leave_accrual, "business_today", lambda: fixed_today)
    schedule: list[UUID] = []
    monkeypatch.setattr(
        maintenance, "get_settings", lambda: SimpleNamespace(hr_scheduled_leave_policy_ids=schedule)
    )
    _, hr_email, password = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))

        async def create(path, body):
            response = await client.post(f"/api/v1/hr/{path}", json=body, headers=hr)
            assert response.status_code == 201, response.text
            return response.json()["id"]

        async def employee(join_date, category):
            return await create(
                "employees",
                {
                    "employee_code": f"SCHED-{uuid4().hex[:8]}",
                    "first_name": "Synthetic",
                    "last_name": "Accrual",
                    "employment_status": "active",
                    "employment_category": category,
                    "join_date": join_date,
                },
            )

        eligible = await employee("2024-01-01", "permanent")
        override = await employee("2024-01-01", "contract")
        partial = await employee("2026-02-15", "permanent")
        monthly = await create("leave/types", {"code": f"LM-{uuid4().hex[:6]}", "name": "Monthly"})
        annual = await create("leave/types", {"code": f"LA-{uuid4().hex[:6]}", "name": "Annual"})

        async def policy(type_id, frequency, year, category=None, prorate=False):
            return await create(
                "leave/policies",
                {
                    "code": f"PS-{uuid4().hex[:8]}",
                    "name": "Scheduled policy",
                    "leave_type_id": type_id,
                    "annual_entitlement_days": "10.01",
                    "employment_category": category,
                    "accrual_frequency": frequency,
                    "prorate_by_calendar_day": prorate,
                    "effective_from": f"{year}-01-01",
                    "effective_to": f"{year}-12-31",
                },
            )

        month_policy = await policy(monthly, "monthly", 2026, prorate=True)
        unlisted = await policy(monthly, "monthly", 2026, "contract")
        annual_policy = await policy(annual, "annual", 2025)
        assert not any((await maintenance._post_hr_leave_accruals()).values())

        schedule.extend([UUID(month_policy), UUID(annual_policy)])
        assert not any((await maintenance._post_hr_leave_accruals()).values())
        for policy_id in (month_policy, unlisted, annual_policy):
            response = await client.post(
                f"/api/v1/hr/leave/policies/{policy_id}/decision",
                headers=reviewer,
                json={"decision": "approved"},
            )
            assert response.status_code == 200, response.text

        # The scheduled run must leave the manual receipt and its actor intact.
        manual = {"employee_id": override, "leave_type_id": annual, "year": 2025}
        preview = await client.post("/api/v1/hr/leave/accrual/preview", headers=hr, json=manual)
        assert preview.status_code == 200
        posted = await client.post(
            "/api/v1/hr/leave/accrual/apply",
            headers=hr,
            json={**manual, "expected_digest": preview.json()["digest"]},
        )
        assert posted.status_code == 200
        async with AsyncSessionLocal() as session:
            manual_entry = await session.get(HrLeaveLedger, UUID(posted.json()["ledger_entry_id"]))
            assert manual_entry is not None and manual_entry.actor_user_id is not None

        runs = await asyncio.gather(
            maintenance._post_hr_leave_accruals(), maintenance._post_hr_leave_accruals()
        )
        assert sum(counts["posted"] for counts in runs) >= 2
        assert sum(counts["outside_schedule"] for counts in runs) >= 1
        rerun = await maintenance._post_hr_leave_accruals()
        assert rerun["posted"] == 0
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(HrLeaveAccrual, HrLeaveLedger)
                    .join(HrLeaveLedger, HrLeaveLedger.id == HrLeaveAccrual.ledger_id)
                    .where(
                        HrLeaveAccrual.leave_type_id.in_([UUID(monthly), UUID(annual)]),
                        HrLeaveAccrual.employee_id.in_(
                            [UUID(eligible), UUID(override), UUID(partial)]
                        ),
                    )
                )
            ).all()
            scheduled = {
                (receipt.period_start, entry.days_delta)
                for receipt, entry in rows
                if entry.actor_user_id is None
            }
            assert scheduled == {
                (date(2026, 2, 1), Decimal("0.84")),
                (date(2026, 2, 1), Decimal("0.42")),
                (date(2025, 1, 1), Decimal("10.01")),
            }
            assert len(rows) == 4
            prorated = next(receipt for receipt, _ in rows if receipt.employee_id == UUID(partial))
            assert (prorated.eligible_from, prorated.eligible_through) == (
                date(2026, 2, 15),
                date(2026, 2, 28),
            )
            audit = await session.scalars(
                select(ActivityLog).where(
                    ActivityLog.entity_id.in_(
                        [entry.id for _, entry in rows if entry.actor_user_id is None]
                    ),
                    ActivityLog.action == "hr.leave_accrual.posted",
                )
            )
            records = list(audit)
            assert len(records) == 3
            assert all(
                row.user_id is None and row.new_values and row.new_values["source"] == "scheduled"
                for row in records
            )
        readback = await client.post(
            "/api/v1/hr/leave/accrual/preview",
            headers=hr,
            json={"employee_id": partial, "leave_type_id": monthly, "year": 2026, "month": 2},
        )
        assert readback.status_code == 200
        assert readback.json()["ledger_entry_id"] == str(prorated.ledger_id)
        assert readback.json()["eligible_from"] == "2026-02-15"


@pytest.mark.asyncio
async def test_managed_leave_profiles_require_review_and_use_service_year_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date
    from uuid import UUID

    await skip_if_database_unavailable()
    # The fixture includes an employee who joins later in this same calendar
    # year. Run after that effective join date so the first-year zero preview
    # is tested for a real employee period, rather than a future hire.
    fixed_today = date(2026, 12, 31)
    monkeypatch.setattr(hr_leave_accrual, "business_today", lambda: fixed_today)
    hr_user_id, hr_email, password = await _create_portal_user("hr_manager")
    reviewer_user_id, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    base = "/api/v1/hr"
    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))

        async def create_employee(join_date: str) -> str:
            response = await client.post(
                f"{base}/employees",
                headers=hr,
                json={
                    "employee_code": f"MANAGED-{uuid4().hex[:8]}",
                    "first_name": "Synthetic",
                    "last_name": "Managed Leave",
                    "employment_status": "active",
                    "employment_category": "permanent",
                    "join_date": join_date,
                },
            )
            assert response.status_code == 201, response.text
            return response.json()["id"]

        def common_rules(profile: str) -> dict:
            return {
                "profile": profile,
                "source_reference": "Synthetic acceptance fixture; not company policy",
                "calendar_year_basis": "calendar_join_year",
                "service_start_rule": "current_continuous_employment_only",
                "rehire_rule": "current_period_only",
                "completed_month_rule": "clamp_from_original_start",
            }

        async def create_managed_policy(
            profile: str,
            entitlement: str,
            frequency: str,
            probe_employee_id: str,
            extra: dict | None = None,
        ) -> tuple[str, str]:
            leave_type = await client.post(
                f"{base}/leave/types",
                headers=hr,
                json={"code": f"M-{uuid4().hex[:8]}", "name": f"Synthetic {profile}"},
            )
            assert leave_type.status_code == 201, leave_type.text
            assert leave_type.json()["is_active"] is False
            type_id = leave_type.json()["id"]
            unavailable = await client.post(
                f"{base}/leave/accrual/preview",
                headers=hr,
                json={"employee_id": probe_employee_id, "leave_type_id": type_id, "year": 2026},
            )
            assert unavailable.status_code == 404
            rules = common_rules(profile)
            if extra:
                rules.update(extra)
            proposal = await client.post(
                f"{base}/leave/policies",
                headers=hr,
                json={
                    "code": f"MP-{uuid4().hex[:8]}",
                    "name": "Synthetic approved-profile fixture",
                    "leave_type_id": type_id,
                    "annual_entitlement_days": entitlement,
                    "accrual_frequency": frequency,
                    "prorate_by_calendar_day": False,
                    "max_carry_forward_days": "0.00",
                    "expire_excess_on_rollover": True,
                    "allow_negative_balance": False,
                    "effective_from": "2024-01-01",
                    "effective_to": "2026-12-31",
                    "entitlement_rules": rules,
                },
            )
            assert proposal.status_code == 201, proposal.text
            policy_id = proposal.json()["id"]
            assert (
                await client.post(
                    f"{base}/leave/policies/{policy_id}/decision",
                    headers=reviewer,
                    json={"decision": "approved"},
                )
            ).status_code == 200
            return type_id, policy_id

        first_year = await create_employee("2026-06-30")
        annual_type, _ = await create_managed_policy(
            "garrisons_annual_v1",
            "14.00",
            "annual",
            first_year,
            {
                "second_year_brackets": [
                    {
                        "from_month": 1,
                        "from_day": 1,
                        "through_month": 12,
                        "through_day": 31,
                        "days": "8.50",
                    }
                ],
                "seven_day_block_basis": "calendar_days",
            },
        )
        managed_ledger_url = f"{base}/leave/ledger"
        for entry_type, expected_error in (
            ("carry_forward", "LEAVE_CARRY_FORWARD_FORBIDDEN"),
            ("adjustment", "LEAVE_ENTITLEMENT_BASELINE_REQUIRED"),
            ("encashment", "LEAVE_ENTITLEMENT_BASELINE_REQUIRED"),
        ):
            blocked_entry = await client.post(
                managed_ledger_url,
                headers=hr,
                json={
                    "employee_id": first_year,
                    "leave_type_id": annual_type,
                    "entry_type": entry_type,
                    "days_delta": "1.00",
                    "leave_year": 2026,
                    "reason": "Synthetic managed leave guard test",
                },
            )
            assert blocked_entry.status_code == 409, blocked_entry.text
            assert blocked_entry.json()["error_code"] == expected_error
        second_year = await create_employee("2025-06-30")
        third_year = await create_employee("2024-02-01")
        preview = f"{base}/leave/accrual/preview"
        unavailable = await client.post(
            preview,
            headers=hr,
            json={"employee_id": first_year, "leave_type_id": annual_type, "year": 2026},
        )
        # Policy review has activated this managed type, so the first-year
        # outcome is a legitimate zero preview rather than a hidden type.
        assert unavailable.status_code == 200, unavailable.text
        assert unavailable.json()["days"] == "0.00"
        assert unavailable.json()["outcome"] == "not_due"
        second = await client.post(
            preview,
            headers=hr,
            json={"employee_id": second_year, "leave_type_id": annual_type, "year": 2026},
        )
        assert second.status_code == 200, second.text
        assert second.json()["days"] == "8.50"
        assert second.json()["due_date"] == "2026-01-01"
        assert second.json()["service_year_band"] == 2
        third = await client.post(
            preview,
            headers=hr,
            json={"employee_id": third_year, "leave_type_id": annual_type, "year": 2026},
        )
        assert third.status_code == 200, third.text
        assert third.json()["days"] == "14.00"
        assert third.json()["service_year_band"] == 3

        from app.database import AsyncSessionLocal
        from app.models.hr import HrLeaveLedger, HrLeaveRequest
        from app.utils.security import utc_now

        year_end_employee = await create_employee("2023-02-01")
        async with AsyncSessionLocal() as session:
            session.add(
                HrLeaveLedger(
                    employee_id=UUID(year_end_employee),
                    leave_type_id=UUID(annual_type),
                    entry_type="opening_balance",
                    days_delta=Decimal("14.00"),
                    leave_year=2025,
                    reason="Synthetic opening balance fixture",
                    actor_user_id=UUID(hr_user_id),
                )
            )
            await session.commit()

        rollover_url = f"{base}/leave/rollover/preview"
        rollover_request = {
            "employee_id": year_end_employee,
            "leave_type_id": annual_type,
            "source_year": 2025,
        }
        blocked = await client.post(rollover_url, headers=hr, json=rollover_request)
        assert blocked.status_code == 409
        assert blocked.json()["error_code"] == "LEAVE_ANNUAL_BLOCK_REQUIRED"
        async with AsyncSessionLocal() as session:
            block = HrLeaveRequest(
                employee_id=UUID(year_end_employee),
                leave_type_id=UUID(annual_type),
                start_date=date(2025, 7, 1),
                end_date=date(2025, 7, 7),
                days_requested=Decimal("7.00"),
                status="approved",
                requested_by_id=UUID(hr_user_id),
                decided_by_id=UUID(reviewer_user_id),
                decided_at=utc_now(),
                decision_notes="Synthetic qualifying annual block",
            )
            session.add(block)
            await session.flush()
            session.add(
                HrLeaveLedger(
                    employee_id=UUID(year_end_employee),
                    leave_type_id=UUID(annual_type),
                    entry_type="taken",
                    days_delta=Decimal("-7.00"),
                    leave_year=2025,
                    reference_request_id=block.id,
                    reason="Synthetic qualifying annual block",
                    actor_user_id=UUID(reviewer_user_id),
                )
            )
            await session.commit()
        rollover = await client.post(rollover_url, headers=hr, json=rollover_request)
        assert rollover.status_code == 200, rollover.text
        assert rollover.json()["carried_days"] == "0.00"
        assert rollover.json()["expired_days"] == "7.00"

        first_year_casual = await create_employee("2026-01-31")
        casual_type, _ = await create_managed_policy(
            "garrisons_casual_v1", "7.00", "monthly", first_year_casual
        )
        second_year_casual = await create_employee("2025-01-31")
        february = await client.post(
            preview,
            headers=hr,
            json={
                "employee_id": first_year_casual,
                "leave_type_id": casual_type,
                "year": 2026,
                "month": 2,
            },
        )
        assert february.status_code == 200, february.text
        assert february.json()["days"] == "0.50"
        assert february.json()["due_date"] == "2026-02-28"
        second_year_casual_quote = await client.post(
            preview,
            headers=hr,
            json={"employee_id": second_year_casual, "leave_type_id": casual_type, "year": 2026},
        )
        assert second_year_casual_quote.status_code == 200, second_year_casual_quote.text
        assert second_year_casual_quote.json()["days"] == "7.00"
        assert second_year_casual_quote.json()["due_date"] == "2026-01-01"


@pytest.mark.asyncio
async def test_managed_leave_approval_requires_reconciliation_for_legacy_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date, timedelta
    from uuid import UUID

    from sqlalchemy import func, select

    from app.database import AsyncSessionLocal
    from app.models.hr import (
        HrEmployee,
        HrLeaveEntitlementBaseline,
        HrLeaveLedger,
        HrLeaveRequest,
        HrWorkCalendar,
    )
    from app.models.notification import Notification
    from app.services import hr_workforce_service
    from app.utils.security import utc_now

    await skip_if_database_unavailable()
    fixed_today = date(2099, 12, 31)
    monkeypatch.setattr(hr_leave_accrual, "business_today", lambda: fixed_today)
    monkeypatch.setattr(hr_workforce_service, "business_today", lambda: fixed_today)
    async with AsyncSessionLocal() as session:
        published_defaults = list(
            await session.scalars(
                select(HrWorkCalendar).where(
                    HrWorkCalendar.is_default.is_(True),
                    HrWorkCalendar.status == "published",
                    HrWorkCalendar.deleted_at.is_(None),
                )
            )
        )
    calendar_day = next(
        candidate
        for offset in range(31)
        if (candidate := date(2099, 12, 1) + timedelta(days=offset)).weekday() < 5
        and not any(
            row.effective_from is not None
            and row.effective_to is not None
            and row.effective_from <= candidate <= row.effective_to
            for row in published_defaults
        )
    )
    maker_id, maker_email, password = await _create_portal_user("hr_manager")
    reviewer_id, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    worker_id, worker_email, _ = await _create_portal_user("quantity_surveyor", password)

    async with _client() as client:
        maker = _auth(await _login(client, maker_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))
        worker = _auth(await _login(client, worker_email, password))
        calendar = await _publish_leave_calendar(
            client, maker, reviewer, calendar_day.isoformat(), calendar_day.isoformat()
        )
        employee_response = await client.post(
            "/api/v1/hr/employees",
            headers=maker,
            json={
                "employee_code": f"BASELINE-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Baseline Worker",
                "employment_status": "active",
                "employment_category": "permanent",
                "join_date": "2024-01-01",
                "work_calendar_id": calendar["id"],
            },
        )
        assert employee_response.status_code == 201, employee_response.text
        employee_id = UUID(employee_response.json()["id"])
        async with AsyncSessionLocal() as session:
            employee = await session.get(HrEmployee, employee_id)
            assert employee is not None
            employee.user_id = UUID(worker_id)
            employee.work_email = worker_email
            await session.commit()

        type_response = await client.post(
            "/api/v1/hr/leave/types",
            headers=maker,
            json={"code": f"MANAGED-{uuid4().hex[:8]}", "name": "Synthetic managed annual"},
        )
        assert type_response.status_code == 201, type_response.text
        leave_type_id = UUID(type_response.json()["id"])
        policy_response = await client.post(
            "/api/v1/hr/leave/policies",
            headers=maker,
            json={
                "code": f"MANAGED-POL-{uuid4().hex[:8]}",
                "name": "Synthetic reviewed managed annual",
                "leave_type_id": str(leave_type_id),
                "annual_entitlement_days": "14.00",
                "accrual_frequency": "annual",
                "max_carry_forward_days": "0.00",
                "expire_excess_on_rollover": True,
                "allow_negative_balance": False,
                "effective_from": "2024-01-01",
                "effective_to": "2099-12-31",
                "entitlement_rules": {
                    "profile": "garrisons_annual_v1",
                    "source_reference": "Synthetic acceptance fixture; not company policy",
                    "calendar_year_basis": "calendar_join_year",
                    "service_start_rule": "current_continuous_employment_only",
                    "rehire_rule": "current_period_only",
                    "completed_month_rule": "clamp_from_original_start",
                    "second_year_brackets": [
                        {
                            "from_month": 1,
                            "from_day": 1,
                            "through_month": 12,
                            "through_day": 31,
                            "days": "8.00",
                        }
                    ],
                    "seven_day_block_basis": "calendar_days",
                },
            },
        )
        assert policy_response.status_code == 201, policy_response.text
        policy_id = UUID(policy_response.json()["id"])
        policy_decision = await client.post(
            f"/api/v1/hr/leave/policies/{policy_id}/decision",
            headers=reviewer,
            json={"decision": "approved"},
        )
        assert policy_decision.status_code == 200, policy_decision.text

        async with AsyncSessionLocal() as session:
            session.add(
                HrLeaveLedger(
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    entry_type="opening_balance",
                    days_delta=Decimal("5.00"),
                    leave_year=2099,
                    reason="Synthetic pre-existing balance for reconciliation regression",
                    actor_user_id=UUID(maker_id),
                )
            )
            await session.commit()

        leave_response = await client.post(
            "/api/v1/hr/me/leave-requests",
            headers=worker,
            json={
                "leave_type_id": str(leave_type_id),
                "start_date": calendar_day.isoformat(),
                "end_date": calendar_day.isoformat(),
                "days_requested": "1.00",
                "reason": "Synthetic managed leave approval regression",
            },
        )
        assert leave_response.status_code == 201, leave_response.text
        request_id = UUID(leave_response.json()["id"])
        assert leave_response.json()["approval_route"] == "hr_fallback"

        decision_url = f"/api/v1/hr/leave/requests/{request_id}/decision"
        blocked = await client.post(
            decision_url,
            headers=reviewer,
            json={"decision": "approved", "expected_revision": 1},
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error_code"] == "LEAVE_ENTITLEMENT_BASELINE_REQUIRED"
        async with AsyncSessionLocal() as session:
            saved_request = await session.get(HrLeaveRequest, request_id)
            assert saved_request is not None
            assert saved_request.status == "submitted"
            assert saved_request.record_revision == 1
            assert (
                await session.scalar(
                    select(func.count(HrLeaveLedger.id)).where(
                        HrLeaveLedger.reference_request_id == request_id
                    )
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count(Notification.id)).where(
                        Notification.reference_type == "hr_leave_request",
                        Notification.reference_id == request_id,
                        Notification.event_code == "approved",
                    )
                )
                == 0
            )

        async with AsyncSessionLocal() as session:
            session.add(
                HrLeaveEntitlementBaseline(
                    id=uuid4(),
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    leave_year=2099,
                    policy_id=policy_id,
                    as_of_date=fixed_today,
                    verified_balance=Decimal("5.00"),
                    recognized_due_dates=[],
                    supporting_reference="Synthetic reviewed baseline receipt",
                    reviewed_by_id=UUID(reviewer_id),
                    reviewed_at=utc_now(),
                    ledger_digest="a" * 64,
                    plan_digest="b" * 64,
                )
            )
            await session.commit()

        approved = await client.post(
            decision_url,
            headers=reviewer,
            json={"decision": "approved", "expected_revision": 1},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["record_revision"] == 2
        async with AsyncSessionLocal() as session:
            debit = await session.scalar(
                select(HrLeaveLedger).where(HrLeaveLedger.reference_request_id == request_id)
            )
            assert debit is not None
            assert debit.entry_type == "taken"
            assert debit.days_delta == Decimal("-1.00")
            assert debit.actor_user_id == UUID(reviewer_id)
