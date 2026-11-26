from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.database import AsyncSessionLocal, engine
from app.models.hr import HrEmployee, HrEmployeePrivate
from app.utils.permissions import BUSINESS_ROLES
from app.utils.time import business_today
from tests.test_daily_reports import (
    create_test_client,
    create_user,
    login_for_token,
    report_payload,
    setup_project_team,
    skip_if_database_unavailable,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def test_dashboard_summary_counts_pending_reports_and_notifications() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        await client.post(
            f"/api/v1/reports/{report['id']}/submit",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        response = await client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert response.status_code == 200
        summary = response.json()
        assert summary["pending_reports"] >= 1
        assert summary["unread_notifications"] >= 1


async def test_celebration_cards_are_minimal_paginated_and_business_role_scoped() -> None:
    await skip_if_database_unavailable()
    today = business_today()
    birthday_in_window = today + timedelta(days=6)
    birthday_outside = today + timedelta(days=7)
    anniversary_outside = today + timedelta(days=30)

    async with AsyncSessionLocal() as session:
        birthday_employee = HrEmployee(
            employee_code=f"CE-{uuid4().hex[:10]}",
            first_name="Upcoming",
            last_name="Birthday",
            full_name="Upcoming Birthday Synthetic",
            employment_status="active",
            join_date=today - timedelta(days=365 * 5),
        )
        birthday_outside_employee = HrEmployee(
            employee_code=f"CE-{uuid4().hex[:10]}",
            first_name="Outside",
            last_name="Birthday",
            full_name="Outside Birthday Synthetic",
            employment_status="active",
            join_date=today - timedelta(days=365 * 5),
        )
        anniversary_employee = HrEmployee(
            employee_code=f"CE-{uuid4().hex[:10]}",
            first_name="Upcoming",
            last_name="Anniversary",
            full_name="Upcoming Anniversary Synthetic",
            employment_status="active",
            join_date=date(today.year - 3, today.month, today.day),
        )
        anniversary_outside_employee = HrEmployee(
            employee_code=f"CE-{uuid4().hex[:10]}",
            first_name="Outside",
            last_name="Anniversary",
            full_name="Outside Anniversary Synthetic",
            employment_status="active",
            join_date=date(
                anniversary_outside.year - 2,
                anniversary_outside.month,
                anniversary_outside.day,
            ),
        )
        session.add_all(
            [
                birthday_employee,
                birthday_outside_employee,
                anniversary_employee,
                anniversary_outside_employee,
            ]
        )
        await session.flush()
        session.add_all(
            [
                HrEmployeePrivate(
                    employee_id=birthday_employee.id,
                    date_of_birth=date(1980, birthday_in_window.month, birthday_in_window.day),
                ),
                HrEmployeePrivate(
                    employee_id=birthday_outside_employee.id,
                    date_of_birth=date(1980, birthday_outside.month, birthday_outside.day),
                ),
            ]
        )
        await session.commit()

    async with create_test_client() as client:
        for role in sorted(BUSINESS_ROLES):
            email, password = await create_user(role)
            token = await login_for_token(client, email, password)
            headers = {"Authorization": f"Bearer {token}"}
            birthdays = await client.get("/api/v1/dashboard/birthdays", headers=headers)
            anniversaries = await client.get("/api/v1/dashboard/anniversaries", headers=headers)
            assert birthdays.status_code == 200, birthdays.text
            assert anniversaries.status_code == 200, anniversaries.text
            assert birthdays.headers["cache-control"] == "private, no-store"
            birthday_names = {item["name"] for item in birthdays.json()["items"]}
            assert "Upcoming Birthday Synthetic" in birthday_names
            assert "Outside Birthday Synthetic" not in birthday_names
            birthday_item = next(
                item for item in birthdays.json()["items"]
                if item["name"] == "Upcoming Birthday Synthetic"
            )
            assert set(birthday_item) == {"name", "day", "month"}
            anniversary_names = {item["name"] for item in anniversaries.json()["items"]}
            assert "Upcoming Anniversary Synthetic" in anniversary_names
            assert "Outside Anniversary Synthetic" not in anniversary_names
            anniversary_item = next(
                item for item in anniversaries.json()["items"]
                if item["name"] == "Upcoming Anniversary Synthetic"
            )
            assert anniversary_item["completed_years"] == 3
            assert set(anniversary_item) == {"name", "day", "month", "completed_years"}
            page = await client.get(
                "/api/v1/dashboard/birthdays?limit=1&offset=0", headers=headers
            )
            assert page.status_code == 200
            assert page.json()["limit"] == 1 and page.json()["offset"] == 0
        assert (await client.get("/api/v1/dashboard/birthdays")).status_code == 401
        assert (await client.get("/api/v1/dashboard/anniversaries")).status_code == 401
