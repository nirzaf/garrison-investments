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
    birthday_after_termination = today + timedelta(days=2)

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
        future_dob_employee = HrEmployee(
            employee_code=f"CE-{uuid4().hex[:10]}",
            first_name="Future",
            last_name="DOB",
            full_name="Future DOB Synthetic",
            employment_status="active",
            join_date=today - timedelta(days=365),
        )
        future_join_employee = HrEmployee(
            employee_code=f"CE-{uuid4().hex[:10]}",
            first_name="Future",
            last_name="Join",
            full_name="Future Join Synthetic",
            employment_status="active",
            join_date=today + timedelta(days=1),
        )
        departed_before_birthday = HrEmployee(
            employee_code=f"CE-{uuid4().hex[:10]}",
            first_name="Departed",
            last_name="Birthday",
            full_name="Departed Before Birthday Synthetic",
            employment_status="active",
            join_date=today - timedelta(days=365),
            termination_date=birthday_after_termination - timedelta(days=1),
        )
        departed_before_anniversary = HrEmployee(
            employee_code=f"CE-{uuid4().hex[:10]}",
            first_name="Departed",
            last_name="Anniversary",
            full_name="Departed Before Anniversary Synthetic",
            employment_status="active",
            join_date=date(
                birthday_after_termination.year - 2,
                birthday_after_termination.month,
                birthday_after_termination.day,
            ),
            termination_date=birthday_after_termination - timedelta(days=1),
        )
        session.add_all(
            [
                birthday_employee,
                birthday_outside_employee,
                anniversary_employee,
                anniversary_outside_employee,
                future_dob_employee,
                future_join_employee,
                departed_before_birthday,
                departed_before_anniversary,
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
                HrEmployeePrivate(
                    employee_id=future_dob_employee.id,
                    date_of_birth=date(
                        today.year + 1, birthday_in_window.month, birthday_in_window.day
                    ),
                ),
                HrEmployeePrivate(
                    employee_id=future_join_employee.id,
                    date_of_birth=date(1980, birthday_in_window.month, birthday_in_window.day),
                ),
                HrEmployeePrivate(
                    employee_id=departed_before_birthday.id,
                    date_of_birth=date(
                        1980, birthday_after_termination.month, birthday_after_termination.day
                    ),
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
            assert "Future DOB Synthetic" not in birthday_names
            assert "Future Join Synthetic" not in birthday_names
            assert "Departed Before Birthday Synthetic" not in birthday_names
            birthday_item = next(
                item for item in birthdays.json()["items"]
                if item["name"] == "Upcoming Birthday Synthetic"
            )
            assert set(birthday_item) == {"name", "day", "month"}
            anniversary_names = {item["name"] for item in anniversaries.json()["items"]}
            assert "Upcoming Anniversary Synthetic" in anniversary_names
            assert "Outside Anniversary Synthetic" not in anniversary_names
            assert "Departed Before Anniversary Synthetic" not in anniversary_names
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


async def test_employee_data_quality_review_is_private_and_does_not_return_source_dates() -> None:
    await skip_if_database_unavailable()
    today = business_today()
    async with AsyncSessionLocal() as session:
        missing = HrEmployee(
            employee_code=f"DQ-{uuid4().hex[:10]}",
            first_name="Missing",
            last_name="Birthdate",
            full_name="Missing Birthdate Synthetic",
            employment_status="active",
            join_date=today - timedelta(days=90),
        )
        future = HrEmployee(
            employee_code=f"DQ-{uuid4().hex[:10]}",
            first_name="Future",
            last_name="Source",
            full_name="Future Source Synthetic",
            employment_status="active",
            join_date=today + timedelta(days=1),
        )
        session.add_all([missing, future])
        await session.flush()
        session.add(
            HrEmployeePrivate(
                employee_id=future.id,
                date_of_birth=today + timedelta(days=1),
            )
        )
        await session.commit()

    async with create_test_client() as client:
        hr_email, hr_password = await create_user("hr_manager")
        supervisor_email, supervisor_password = await create_user("site_supervisor")
        hr_headers = {
            "Authorization": f"Bearer {await login_for_token(client, hr_email, hr_password)}"
        }
        supervisor_headers = {
            "Authorization": (
                f"Bearer {await login_for_token(client, supervisor_email, supervisor_password)}"
            )
        }
        path = "/api/v1/hr/employee-data-quality"
        response = await client.get(path, params={"limit": 100}, headers=hr_headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        by_name = {item["full_name"]: item for item in response.json()["items"]}
        assert "missing_birth_date" in by_name["Missing Birthdate Synthetic"]["issue_codes"]
        assert "employment_start_unverified" in by_name["Future Source Synthetic"]["issue_codes"]
        assert "future_birth_date" in by_name["Future Source Synthetic"]["issue_codes"]
        assert not (
            {"date_of_birth", "join_date", "birth_year"}
            & set(by_name["Future Source Synthetic"])
        )
        assert (await client.get(path, headers=supervisor_headers)).status_code == 403
