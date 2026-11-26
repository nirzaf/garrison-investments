import asyncio
from datetime import UTC, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.database import AsyncSessionLocal, engine
from app.models.hr import (
    HrEmployee,
    HrEmploymentPeriod,
    HrHoliday,
    HrOffboardingCase,
    HrOvertimeRequest,
    HrPayrollPeriod,
    HrRosterAllocation,
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
            work_days_json=[("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[day.weekday()]],
            standard_start_time=time(8, 30),
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
        "check_in_at": f"{day.isoformat()}T07:12:00+03:00",
        "check_out_at": f"{day.isoformat()}T16:00:00+03:00",
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
                if key not in {"project_id", "overtime_hours", "check_in_at", "check_out_at"}
            },
            headers=hr,
        )
        assert manual.status_code == 409, manual.text
        assert manual.json()["error_code"] == "SITE_ATTENDANCE_WORKFLOW_REQUIRED"

        async with AsyncSessionLocal() as session:
            missing, csv_content = await reconcile_payroll_time_inputs(
                session, period, {employee.id}
            )
            finding = next(
                issue for issue in missing.issues if issue.code == "missing_site_attendance"
            )
            assert (finding.project_id, finding.work_date) == (project.id, day)
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
        assert entry["submission"]["requirements"]["arrival_variance_seconds"] == 720
        assert entry["submission"]["requirements"]["scheduled_start_at"].startswith(
            f"{day.isoformat()}T04:00:00"
        )
        assessment = entry["submission"]["requirements"]["arrival_assessment"]
        assert assessment["source"] == "shift"
        assert assessment["timezone"] == "Asia/Qatar"
        assert assessment["status"] == "after_scheduled_start"
        assert assessment["minutes_after_start"] == 12
        from app.schemas.hr import SiteAttendanceCreateRequest
        from app.services.hr_site_attendance_service import HrSiteAttendanceService

        async with AsyncSessionLocal() as session:
            worker_row = await session.get(HrEmployee, employee.id)
            assert worker_row is not None
            service = HrSiteAttendanceService(session)
            for check_in, expected_status, expected_minutes in (
                (f"{day.isoformat()}T06:59:59+03:00", "on_time", None),
                (f"{day.isoformat()}T07:00:00+03:00", "on_time", None),
                (f"{day.isoformat()}T07:00:01+03:00", "after_scheduled_start", 1),
                (f"{day.isoformat()}T08:00:00+04:00", "on_time", None),
                (None, "unresolved", None),
            ):
                arrival_payload = SiteAttendanceCreateRequest.model_validate(
                    {
                        **payload,
                        "check_in_at": check_in,
                        "check_out_at": payload["check_out_at"] if check_in else None,
                    }
                )
                _, _, saved_assessment = await service._arrival_schedule_snapshot(
                    arrival_payload, worker_row
                )
                assert saved_assessment.status == expected_status
                assert saved_assessment.minutes_after_start == expected_minutes

            roster = HrRosterAllocation(
                id=uuid4(),
                employee_id=employee.id,
                project_id=project.id,
                calendar_id=calendar.id,
                shift_id=None,
                employee_name=employee.full_name,
                project_name=project.name,
                work_date=day,
                timezone="Asia/Qatar",
                starts_at=datetime.combine(day, time(6, 45), tzinfo=timezone(timedelta(hours=3))),
                ends_at=datetime.combine(day, time(15), tzinfo=timezone(timedelta(hours=3))),
                planned_hours=Decimal("8.00"),
                created_by_id=supervisor.id,
            )
            session.add(roster)
            await session.flush()
            _, _, roster_assessment = await service._arrival_schedule_snapshot(
                SiteAttendanceCreateRequest.model_validate(
                    {**payload, "check_in_at": f"{day.isoformat()}T07:12:00+03:00"}
                ),
                worker_row,
            )
            assert roster_assessment.source == "roster"
            assert roster_assessment.source_reference_id == roster.id
            assert roster_assessment.minutes_after_start == 27
            await session.delete(roster)

            calendar_worker = HrEmployee(
                employee_code=f"CAL-{uuid4().hex[:8]}",
                first_name="Calendar",
                last_name="Worker",
                full_name="Calendar Worker",
                employment_status="active",
                join_date=day - timedelta(days=2),
                work_calendar_id=calendar.id,
            )
            overnight_worker = HrEmployee(
                employee_code=f"NIGHT-{uuid4().hex[:8]}",
                first_name="Night",
                last_name="Worker",
                full_name="Night Worker",
                employment_status="active",
                join_date=day - timedelta(days=2),
                work_calendar_id=calendar.id,
            )
            session.add_all([calendar_worker, overnight_worker])
            await session.flush()
            calendar_payload = SiteAttendanceCreateRequest.model_validate(
                {
                    **payload,
                    "employee_id": str(calendar_worker.id),
                    "check_in_at": f"{day.isoformat()}T08:30:00+03:00",
                }
            )
            _, _, calendar_assessment = await service._arrival_schedule_snapshot(
                calendar_payload, calendar_worker
            )
            assert calendar_assessment.source == "calendar"
            assert calendar_assessment.status == "on_time"
            assert calendar_assessment.minutes_after_start is None

            session.add(
                HrHoliday(calendar_id=calendar.id, holiday_date=day, name="Synthetic holiday")
            )
            await session.flush()
            _, _, holiday_assessment = await service._arrival_schedule_snapshot(
                calendar_payload, calendar_worker
            )
            assert holiday_assessment.status == "not_applicable"

            absent_payload = SiteAttendanceCreateRequest.model_validate(
                {
                    **payload,
                    "attendance_status": "absent",
                    "check_in_at": None,
                    "check_out_at": None,
                    "worked_hours": Decimal("0"),
                    "overtime_hours": Decimal("0"),
                }
            )
            _, _, absent_assessment = await service._arrival_schedule_snapshot(
                absent_payload, worker_row
            )
            assert absent_assessment.status == "not_applicable"

            no_calendar_worker = HrEmployee(
                employee_code=f"NOCAL-{uuid4().hex[:8]}",
                first_name="No",
                last_name="Calendar",
                full_name="No Calendar",
                employment_status="active",
                join_date=day - timedelta(days=2),
            )
            session.add(no_calendar_worker)
            await session.flush()
            no_calendar_date = day + timedelta(days=10)
            no_calendar_payload = SiteAttendanceCreateRequest.model_validate(
                {
                    **payload,
                    "employee_id": str(no_calendar_worker.id),
                    "work_date": no_calendar_date.isoformat(),
                    "check_in_at": f"{no_calendar_date.isoformat()}T08:30:00+03:00",
                }
            )
            _, _, no_calendar_assessment = await service._arrival_schedule_snapshot(
                no_calendar_payload, no_calendar_worker
            )
            assert no_calendar_assessment.status == "unresolved"

            overnight_date = day + timedelta(days=1)
            session.add(
                HrShiftAssignment(
                    employee_id=overnight_worker.id,
                    calendar_id=calendar.id,
                    project_id=project.id,
                    shift_name="Overnight site shift",
                    effective_from=overnight_date,
                    effective_to=overnight_date,
                    start_time=time(22),
                    end_time=time(6),
                )
            )
            await session.flush()
            overnight_payload = SiteAttendanceCreateRequest.model_validate(
                {
                    **payload,
                    "employee_id": str(overnight_worker.id),
                    "work_date": overnight_date.isoformat(),
                    "check_in_at": f"{overnight_date.isoformat()}T22:00:01+03:00",
                    "check_out_at": (
                        f"{(overnight_date + timedelta(days=1)).isoformat()}T06:00:00+03:00"
                    ),
                }
            )
            _, _, overnight_assessment = await service._arrival_schedule_snapshot(
                overnight_payload, overnight_worker
            )
            assert overnight_assessment.source == "shift"
            assert overnight_assessment.status == "after_scheduled_start"
            assert overnight_assessment.minutes_after_start == 1
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
        missing_reason = await client.post(
            f"{site_path}/{entry_id}/correction",
            json={
                **payload,
                "expected_revision": returned.json()["record_revision"],
                "notes": "Time checked.",
            },
            headers=writer,
        )
        assert missing_reason.status_code == 422, missing_reason.text
        corrected = await client.post(
            f"{site_path}/{entry_id}/correction",
            json={
                **payload,
                "expected_revision": returned.json()["record_revision"],
                "notes": "Time checked.",
                "correction_reason": "Corrected after checking the site register.",
            },
            headers=writer,
        )
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["submission"]["submission_revision"] == 2
        assert corrected.json()["stage"] == "pending_engineer"
        assert corrected.json()["submission"]["requirements"]["correction_reason"] == (
            "Corrected after checking the site register."
        )

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
            finding = next(
                issue for issue in result.issues if issue.code == "site_overtime_mismatch"
            )
            assert (finding.project_id, finding.work_date) == (project.id, day)
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
            json={
                **payload,
                "expected_revision": approved["record_revision"],
                "correction_reason": "Correct an entry in a closed timesheet period.",
            },
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


async def test_historical_payroll_obligations_match_project_and_work_date() -> None:
    await skip_if_database_unavailable()
    from app.models.hr import HrAttendanceEntry
    from app.models.project import Project

    manager, _ = await create_user("group_project_manager")
    engineer, _ = await create_user("mep_project_manager")
    required = await create_project(manager, engineer)
    other = await create_project(manager, engineer)
    day = business_today() - timedelta(days=10)
    second_day = day + timedelta(days=1)
    period = HrPayrollPeriod(
        id=uuid4(),
        period_code="historical-site-test",
        period_start=day,
        period_end=second_day,
        pay_date=second_day,
    )
    async with AsyncSessionLocal.begin() as session:
        project = await session.get(Project, required.id)
        assert project is not None
        project.status = "completed"
        employee = HrEmployee(
            employee_code=f"HIST-{uuid4().hex[:8]}",
            first_name="Former",
            last_name="Worker",
            full_name="Former Worker",
            employment_status="terminated",
            join_date=day - timedelta(days=10),
            termination_date=second_day,
        )
        calendar = HrWorkCalendar(
            code=f"HIST-{uuid4().hex[:6]}",
            name="Historical site",
            project_id=required.id,
            timezone="Asia/Qatar",
            status="published",
            published_at=utc_now(),
            effective_from=day,
            effective_to=second_day,
        )
        session.add_all([employee, calendar])
        await session.flush()
        session.add_all(
            [
                HrShiftAssignment(
                    employee_id=employee.id,
                    calendar_id=calendar.id,
                    project_id=required.id,
                    shift_name="Site",
                    effective_from=day,
                    effective_to=second_day,
                    start_time=time(7),
                    end_time=time(16),
                ),
                HrAttendanceEntry(
                    employee_id=employee.id,
                    project_id=other.id,
                    work_date=day,
                    attendance_status="present",
                    status="approved",
                    source="site",
                ),
            ]
        )
        await session.flush()
        result, _ = await reconcile_payroll_time_inputs(session, period, {employee.id})
        missing = {
            (issue.employee_id, issue.project_id, issue.work_date)
            for issue in result.issues
            if issue.code == "missing_site_attendance"
        }
        assert missing == {(employee.id, required.id, date) for date in (day, second_day)}
        employee.join_date = None
        await session.flush()
        result, _ = await reconcile_payroll_time_inputs(session, period, {employee.id})
        unresolved = [
            issue
            for issue in result.issues
            if issue.code == "site_employment_eligibility_unresolved"
        ]
        assert {issue.work_date for issue in unresolved} == {day, second_day}


async def test_payroll_time_preview_blocks_duplicate_and_cross_project_roster_obligations() -> None:
    await skip_if_database_unavailable()

    manager, _ = await create_user("group_project_manager")
    engineer, _ = await create_user("mep_project_manager")
    first = await create_project(manager, engineer)
    second = await create_project(manager, engineer)
    day = business_today() - timedelta(days=12)
    period = HrPayrollPeriod(
        id=uuid4(),
        period_code=f"roster-conflict-{uuid4().hex[:8]}",
        period_start=day,
        period_end=day,
        pay_date=day,
    )
    async with AsyncSessionLocal() as session:
        calendar = HrWorkCalendar(
            code=f"CONFLICT-{uuid4().hex[:8]}",
            name="Synthetic conflict calendar",
            timezone="Asia/Qatar",
            status="published",
            published_at=utc_now(),
            effective_from=day,
            effective_to=day,
            work_days_json=[("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[day.weekday()]],
        )
        employee = HrEmployee(
            employee_code=f"ROSTER-{uuid4().hex[:8]}",
            first_name="Synthetic",
            last_name="Roster",
            full_name="Synthetic Roster Conflict",
            employment_status="active",
            join_date=day - timedelta(days=30),
        )
        session.add_all([calendar, employee])
        await session.flush()
        session.add_all(
            [
                HrRosterAllocation(
                    id=uuid4(),
                    employee_id=employee.id,
                    project_id=first.id,
                    calendar_id=calendar.id,
                    employee_name=employee.full_name,
                    project_name="First project",
                    work_date=day,
                    timezone="Asia/Qatar",
                    starts_at=datetime.combine(day, time(7), tzinfo=UTC),
                    ends_at=datetime.combine(day, time(15), tzinfo=UTC),
                    planned_hours=Decimal("8.00"),
                ),
                HrRosterAllocation(
                    id=uuid4(),
                    employee_id=employee.id,
                    project_id=first.id,
                    calendar_id=calendar.id,
                    employee_name=employee.full_name,
                    project_name="First project",
                    work_date=day,
                    timezone="Asia/Qatar",
                    starts_at=datetime.combine(day, time(7), tzinfo=UTC),
                    ends_at=datetime.combine(day, time(15), tzinfo=UTC),
                    planned_hours=Decimal("8.00"),
                ),
                HrRosterAllocation(
                    id=uuid4(),
                    employee_id=employee.id,
                    project_id=second.id,
                    calendar_id=calendar.id,
                    employee_name=employee.full_name,
                    project_name="Second project",
                    work_date=day,
                    timezone="Asia/Qatar",
                    starts_at=datetime.combine(day, time(7), tzinfo=UTC),
                    ends_at=datetime.combine(day, time(15), tzinfo=UTC),
                    planned_hours=Decimal("8.00"),
                ),
                HrTimesheet(
                    employee_id=employee.id,
                    project_id=first.id,
                    period_start=day,
                    period_end=day,
                    status="locked",
                    regular_hours=Decimal("8.00"),
                    approved_at=utc_now(),
                ),
            ]
        )
        await session.flush()
        result, csv_content = await reconcile_payroll_time_inputs(
            session, period, {employee.id}
        )
        conflicts = [issue for issue in result.issues if issue.code == "site_assignment_conflict"]
        assert {(issue.project_id, issue.candidate_count) for issue in conflicts} == {
            (first.id, 3),
            (second.id, 3),
        }
        assert not any(issue.code == "missing_site_attendance" for issue in result.issues)
        assert csv_content is None


async def test_historical_site_attendance_uses_evidence_and_preserves_period_locks() -> None:
    await skip_if_database_unavailable()
    from app.models.project import Project

    supervisor, supervisor_password = await create_user("site_supervisor")
    engineer, engineer_password = await create_user("mep_project_manager")
    manager, _ = await create_user("group_project_manager")
    hr_manager, hr_password = await create_user("hr_manager")
    project = await create_project(manager, engineer)
    work_date = business_today() - timedelta(days=14)

    async with AsyncSessionLocal() as session:
        project_row = await session.get(Project, project.id)
        assert project_row is not None
        project_row.status = "completed"
        calendar = HrWorkCalendar(
            code=f"HIST-{uuid4().hex[:6]}",
            name="Historical site schedule",
            project_id=project.id,
            timezone="Asia/Qatar",
            status="published",
            published_at=utc_now(),
            effective_from=work_date - timedelta(days=20),
            effective_to=work_date,
        )
        employee = HrEmployee(
            employee_code=f"FORMER-{uuid4().hex[:8]}",
            first_name="Former",
            last_name="Worker",
            full_name="Former Worker",
            employment_status="terminated",
            join_date=work_date - timedelta(days=30),
            termination_date=work_date + timedelta(days=1),
        )
        session.add_all(
            [
                calendar,
                employee,
                ProjectMember(project_id=project.id, user_id=supervisor.id),
            ]
        )
        await session.flush()
        offboarding = HrOffboardingCase(
            id=uuid4(),
            employee_id=employee.id,
            separation_type="resignation",
            last_working_date=work_date + timedelta(days=1),
            status="completed",
            completed_at=utc_now(),
        )
        session.add(offboarding)
        await session.flush()
        session.add_all(
            [
                HrEmploymentPeriod(
                    employee_id=employee.id,
                    started_on=work_date - timedelta(days=30),
                    ended_on=work_date + timedelta(days=1),
                    separation_case_id=offboarding.id,
                ),
                HrShiftAssignment(
                    employee_id=employee.id,
                    calendar_id=calendar.id,
                    project_id=project.id,
                    shift_name="Historical site shift",
                    effective_from=work_date - timedelta(days=1),
                    effective_to=work_date,
                    start_time=time(7),
                    end_time=time(16),
                ),
            ]
        )
        await session.commit()

    body = {
        "employee_id": str(employee.id),
        "project_id": str(project.id),
        "work_date": work_date.isoformat(),
        "attendance_status": "present",
        "check_in_at": f"{work_date.isoformat()}T07:00:00+03:00",
        "check_out_at": f"{work_date.isoformat()}T16:00:00+03:00",
        "worked_hours": "8.00",
        "overtime_hours": "0.00",
    }

    async with create_test_client() as client:
        async def headers_for(user, password):
            return {"Authorization": f"Bearer {await login_for_token(client, user, password)}"}

        writer = await headers_for(supervisor, supervisor_password)
        engineer_headers = await headers_for(engineer, engineer_password)
        hr_headers = await headers_for(hr_manager, hr_password)
        workers = await client.get(
            "/api/v1/hr/site-attendance/workers",
            params={
                "project_id": str(project.id),
                "work_date": work_date.isoformat(),
                "historical": True,
            },
            headers=writer,
        )
        assert workers.status_code == 200, workers.text
        assert [row["id"] for row in workers.json()["items"]] == [str(employee.id)]
        project_options = await client.get(
            "/api/v1/hr/site-attendance/project-options",
            params={"historical": True, "search": project.name},
            headers=writer,
        )
        assert project_options.status_code == 200, project_options.text
        assert [row["id"] for row in project_options.json()] == [str(project.id)]
        active_options = await client.get(
            "/api/v1/hr/site-attendance/project-options",
            params={"search": project.name},
            headers=writer,
        )
        assert active_options.status_code == 200, active_options.text
        assert active_options.json() == []

        missing_reason = await client.post("/api/v1/hr/site-attendance", json=body, headers=writer)
        assert missing_reason.status_code == 409, missing_reason.text
        assert missing_reason.json()["error_code"] == "HISTORICAL_REASON_REQUIRED"

        submitted = await client.post(
            "/api/v1/hr/site-attendance",
            json={**body, "historical_reason": "Reconcile the verified site register."},
            headers=writer,
        )
        assert submitted.status_code == 201, submitted.text
        entry_id = submitted.json()["id"]
        assert submitted.json()["submission"]["requirements"]["historical_reason"] == (
            "Reconcile the verified site register."
        )
        assert submitted.json()["submission"]["requirements"]["historical_remediation"] is True
        engineer_decision = await client.post(
            f"/api/v1/hr/site-attendance/{entry_id}/decision",
            json={"expected_revision": 1, "stage": "engineer", "decision": "approved"},
            headers=engineer_headers,
        )
        assert engineer_decision.status_code == 200, engineer_decision.text
        hr_decision = await client.post(
            f"/api/v1/hr/site-attendance/{entry_id}/decision",
            json={
                "expected_revision": engineer_decision.json()["record_revision"],
                "stage": "hr",
                "decision": "approved",
            },
            headers=hr_headers,
        )
        assert hr_decision.status_code == 200, hr_decision.text

        dropped_mode = await client.post(
            f"/api/v1/hr/site-attendance/{entry_id}/correction",
            json={
                **body,
                "expected_revision": hr_decision.json()["record_revision"],
                "correction_reason": "Check the historical record again.",
            },
            headers=writer,
        )
        assert dropped_mode.status_code == 422, dropped_mode.text
        assert dropped_mode.json()["error_code"] == "HISTORICAL_REASON_REQUIRED"

        corrected = await client.post(
            f"/api/v1/hr/site-attendance/{entry_id}/correction",
            json={
                **body,
                "historical_reason": "Reconcile the verified site register.",
                "expected_revision": hr_decision.json()["record_revision"],
                "correction_reason": "Correct the recorded arrival from the signed register.",
            },
            headers=writer,
        )
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["submission"]["submission_revision"] == 2
        corrected_engineer = await client.post(
            f"/api/v1/hr/site-attendance/{entry_id}/decision",
            json={
                "expected_revision": corrected.json()["record_revision"],
                "stage": "engineer",
                "decision": "approved",
            },
            headers=engineer_headers,
        )
        assert corrected_engineer.status_code == 200, corrected_engineer.text
        corrected_hr = await client.post(
            f"/api/v1/hr/site-attendance/{entry_id}/decision",
            json={
                "expected_revision": corrected_engineer.json()["record_revision"],
                "stage": "hr",
                "decision": "approved",
            },
            headers=hr_headers,
        )
        assert corrected_hr.status_code == 200, corrected_hr.text
        history = await client.get(
            f"/api/v1/hr/site-attendance/{entry_id}/history", headers=writer
        )
        assert history.status_code == 200, history.text
        assert [row["submission_revision"] for row in history.json()] == [2, 1]
        assert history.json()[1]["requirements"]["historical_reason"] == (
            "Reconcile the verified site register."
        )
        assert history.json()[0]["requirements"]["correction_reason"].startswith(
            "Correct the recorded arrival"
        )
        assert history.json()[0]["requirements"]["historical_remediation"] is True

        async with AsyncSessionLocal.begin() as session:
            session.add(
                HrTimesheet(
                    id=uuid4(),
                    employee_id=employee.id,
                    project_id=project.id,
                    period_start=work_date,
                    period_end=work_date,
                    regular_hours=Decimal("8.00"),
                    overtime_hours=Decimal("0.00"),
                    status="locked",
                )
            )
        locked = await client.post(
            f"/api/v1/hr/site-attendance/{entry_id}/correction",
            json={
                **body,
                "historical_reason": "Reconcile the verified site register.",
                "expected_revision": corrected_hr.json()["record_revision"],
                "correction_reason": "Attempt correction after payroll lock.",
            },
            headers=writer,
        )
        assert locked.status_code == 409
        assert "locked timesheet period" in locked.json()["detail"]
