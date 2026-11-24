import asyncio
from datetime import time, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.database import AsyncSessionLocal, engine
from app.models.hr import (
    HrEmployee,
    HrOvertimeRequest,
    HrPayrollPeriod,
    HrShiftAssignment,
    HrTimesheet,
    HrWorkCalendar,
)
from app.models.project_member import ProjectMember
from app.services.hr_payroll_time import reconcile_payroll_time_inputs
from app.utils.security import utc_now
from app.utils.time import business_today
from tests.test_inventory import (
    create_project,
    create_test_client,
    create_user,
    login_for_token,
    skip_if_database_unavailable,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def test_site_attendance_requires_independent_engineer_and_hr_checks() -> None:
    await skip_if_database_unavailable()
    supervisor, supervisor_password = await create_user("site_supervisor")
    engineer, engineer_password = await create_user("mep_project_manager")
    other_engineer, other_password = await create_user("mep_project_manager")
    manager, _ = await create_user("group_project_manager")
    hr_manager, hr_password = await create_user("hr_manager")
    project = await create_project(manager, engineer)
    day = business_today()
    period = HrPayrollPeriod(
        id=uuid4(), period_code="site-test", period_start=day, period_end=day, pay_date=day
    )

    async with AsyncSessionLocal() as session:
        calendar = HrWorkCalendar(
            code=f"SITE-{uuid4().hex[:6]}",
            name="Site hours",
            project_id=project.id,
            timezone="Asia/Qatar",
            status="published",
            published_at=utc_now(),
            effective_from=day - timedelta(days=1),
            effective_to=day + timedelta(days=1),
        )
        member = ProjectMember(project_id=project.id, user_id=supervisor.id)
        employee = HrEmployee(
            employee_code=f"WORK-{uuid4().hex[:8]}",
            first_name="Test",
            last_name="Worker",
            full_name="Test Worker",
            employment_status="active",
            join_date=day - timedelta(days=2),
        )
        session.add_all([calendar, member, employee])
        await session.flush()
        session.add(
            HrShiftAssignment(
                employee_id=employee.id,
                calendar_id=calendar.id,
                project_id=project.id,
                shift_name="Site",
                effective_from=day,
                effective_to=day,
                start_time=time(7),
                end_time=time(16),
            )
        )
        await session.commit()

    payload = {
        "employee_id": str(employee.id),
        "project_id": str(project.id),
        "work_date": day.isoformat(),
        "attendance_status": "present",
        "worked_hours": "8.00",
        "overtime_hours": "1.00",
    }

    async with create_test_client() as client:

        async def headers_for(user, password):
            return {"Authorization": f"Bearer {await login_for_token(client, user, password)}"}

        writer = await headers_for(supervisor, supervisor_password)
        reviewer = await headers_for(engineer, engineer_password)
        outsider = await headers_for(other_engineer, other_password)
        hr = await headers_for(hr_manager, hr_password)

        forbidden_directory = await client.get("/api/v1/hr/employees", headers=writer)
        assert forbidden_directory.status_code == 403
        workers = await client.get(
            "/api/v1/hr/site-attendance/workers",
            params={"project_id": str(project.id), "work_date": day.isoformat()},
            headers=writer,
        )
        assert workers.status_code == 200, workers.text
        assert workers.json()["items"] == [
            {
                "id": str(employee.id),
                "employee_code": employee.employee_code,
                "full_name": employee.full_name,
            }
        ]

        # A direct HR record without a project ID must still honor the site assignment.
        manual = await client.post(
            "/api/v1/hr/attendance",
            json={
                key: value
                for key, value in payload.items()
                if key not in {"project_id", "overtime_hours"}
            },
            headers=hr,
        )
        assert manual.status_code == 409, manual.text
        assert manual.json()["error_code"] == "SITE_ATTENDANCE_WORKFLOW_REQUIRED"

        async with AsyncSessionLocal() as session:
            missing, csv_content = await reconcile_payroll_time_inputs(
                session, period, {employee.id}
            )
            assert any(issue.code == "missing_site_attendance" for issue in missing.issues)
            assert csv_content is None

        site_path = "/api/v1/hr/site-attendance"
        counts_path = f"{site_path}/completeness"
        counts_params = {"project_id": str(project.id), "work_date": day.isoformat()}
        counts = await client.get(counts_path, params=counts_params, headers=writer)
        assert counts.status_code == 200, counts.text
        assert counts.json()["missing_workers"] == 1
        assert counts.json()["items"][0]["id"] == str(employee.id)
        outside = await client.get(counts_path, params=counts_params, headers=outsider)
        assert outside.status_code in (403, 404)
        empty = await client.get(
            counts_path,
            params={**counts_params, "work_date": (day - timedelta(days=1)).isoformat()},
            headers=hr,
        )
        assert empty.json()["empty_roster"] is True
        created = await client.post(site_path, json=payload, headers=writer)
        assert created.status_code == 201, created.text
        entry = created.json()
        entry_id = entry["id"]
        assert entry["stage"] == "pending_engineer"
        action = f"{site_path}/{entry_id}/decision"
        proposed = {"expected_revision": entry["record_revision"], "decision": "approved"}
        early = await client.post(action, json={**proposed, "stage": "hr"}, headers=hr)
        assert early.status_code == 409
        foreign = await client.post(
            action, json={**proposed, "stage": "engineer"}, headers=outsider
        )
        assert foreign.status_code == 404
        self_review = await client.post(
            action, json={**proposed, "stage": "engineer"}, headers=writer
        )
        assert self_review.status_code == 403

        reviewed = await client.post(
            action, json={**proposed, "stage": "engineer"}, headers=reviewer
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["stage"] == "pending_hr"
        dashboard = "/api/v1/dashboard/summary"
        pending_summary = await client.get(dashboard, headers=reviewer)
        assert pending_summary.status_code == 200, pending_summary.text
        assert pending_summary.json()["site_operations"]["confirmed_present_today"] == 0
        async with AsyncSessionLocal() as session:
            result, csv_content = await reconcile_payroll_time_inputs(
                session, period, {employee.id}
            )
            assert any(
                issue.code == "pending_attendance" and issue.record_id == UUID(entry_id)
                for issue in result.issues
            )
            assert csv_content is None

        wrong_route = await client.post(
            f"/api/v1/hr/attendance/{entry_id}/decision",
            json={"decision": "approved", "expected_revision": reviewed.json()["record_revision"]},
            headers=hr,
        )
        assert wrong_route.status_code == 409, wrong_route.text
        assert wrong_route.json()["error_code"] == "SITE_ATTENDANCE_WORKFLOW_REQUIRED"

        returned = await client.post(
            action,
            json={
                "expected_revision": reviewed.json()["record_revision"],
                "stage": "hr",
                "decision": "returned",
                "comments": "Reconcile the recorded time.",
            },
            headers=hr,
        )
        assert returned.status_code == 200, returned.text
        corrected = await client.post(
            f"{site_path}/{entry_id}/correction",
            json={
                **payload,
                "expected_revision": returned.json()["record_revision"],
                "notes": "Time checked.",
            },
            headers=writer,
        )
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["submission"]["submission_revision"] == 2
        assert corrected.json()["stage"] == "pending_engineer"

        reviewed_again = await client.post(
            action,
            json={
                "stage": "engineer",
                "decision": "approved",
                "expected_revision": corrected.json()["record_revision"],
            },
            headers=reviewer,
        )
        assert reviewed_again.status_code == 200, reviewed_again.text
        checks = await asyncio.gather(
            *[
                client.post(
                    action,
                    json={
                        "stage": "hr",
                        "decision": "approved",
                        "expected_revision": reviewed_again.json()["record_revision"],
                    },
                    headers=hr,
                )
                for _ in range(2)
            ]
        )
        assert sorted(check.status_code for check in checks) == [200, 409]
        approved = next(check.json() for check in checks if check.status_code == 200)
        assert approved["stage"] == "approved"
        complete = await client.get(counts_path, params=counts_params, headers=hr)
        assert complete.json()["is_complete"] is True
        assert complete.json()["confirmed_workers"] == 1
        confirmed_summary = await client.get(dashboard, headers=reviewer)
        foreign_summary = await client.get(dashboard, headers=outsider)
        hr_summary = await client.get(dashboard, headers=hr)
        assert confirmed_summary.json()["site_operations"]["confirmed_present_today"] == 1
        assert foreign_summary.json()["site_operations"]["confirmed_present_today"] == 0
        assert hr_summary.json()["site_operations"] is None

        sheet_id = uuid4()
        async with AsyncSessionLocal() as session:
            session.add(
                HrTimesheet(
                    id=sheet_id,
                    employee_id=employee.id,
                    project_id=project.id,
                    period_start=day,
                    period_end=day,
                    status="locked",
                    regular_hours=Decimal("8"),
                    approved_at=utc_now(),
                )
            )
            await session.commit()
            result, csv_content = await reconcile_payroll_time_inputs(
                session, period, {employee.id}
            )
            assert any(issue.code == "site_overtime_mismatch" for issue in result.issues)
            assert csv_content is None
            sheet = await session.get(HrTimesheet, sheet_id)
            assert sheet is not None
            sheet.overtime_hours = Decimal("1")
            session.add(
                HrOvertimeRequest(
                    employee_id=employee.id,
                    project_id=project.id,
                    work_date=day,
                    requested_hours=Decimal("1"),
                    approved_hours=Decimal("1"),
                    reason="Approved site overtime",
                    status="approved",
                    decided_at=utc_now(),
                )
            )
            await session.commit()
            result, csv_content = await reconcile_payroll_time_inputs(
                session, period, {employee.id}
            )
            assert result.issues == []
            assert csv_content

        locked = await client.post(
            f"{site_path}/{entry_id}/correction",
            json={**payload, "expected_revision": approved["record_revision"]},
            headers=writer,
        )
        assert locked.status_code == 409
        assert "locked timesheet period" in locked.json()["detail"]
        history = await client.get(f"{site_path}/{entry_id}/history", headers=writer)
        assert [row["hr_decision"] for row in history.json()] == ["approved", "returned"]
        summary = await client.get(
            site_path,
            params={"project_id": str(project.id), "work_date": day.isoformat()},
            headers=writer,
        )
        assert summary.json()["confirmed_present"] == 1
