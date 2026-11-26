"""Comprehensive HR & Workforce Management test suite (HR-A through HR-J + CLI)."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import zlib
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID, uuid4
from zipfile import ZipFile

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.activity_log import ActivityLog
from app.models.hr import (
    HrAttendanceEntry,
    HrCertification,
    HrClearanceStep,
    HrDepartment,
    HrDocument,
    HrDocumentVersion,
    HrEmployee,
    HrEmployeePrivate,
    HrEmploymentPeriod,
    HrIssuedLetter,
    HrLeaveLedger,
    HrLeaveType,
    HrOffer,
    HrOnboardingCase,
    HrRequisition,
    HrServiceRequest,
    HrShiftAssignment,
    HrWorkCalendar,
)
from app.models.inventory import InventoryLocationStock
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.hr import (
    HrDocumentDecisionRequest,
    OnboardingCaseCreateRequest,
    OnboardingTaskUpdateRequest,
)
from app.services.hr_crypto import encrypt_hr_value
from app.services.hr_workforce_service import HrWorkforceService
from app.tasks.maintenance import (
    _check_hr_credential_expiry,
    _check_hr_probation_reviews,
    _check_hr_service_request_sla,
)
from app.utils.exceptions import AppException
from app.utils.time import business_today
from scripts import garrisonctl
from scripts.backup_set import references
from tests.password_fixtures import hash_fixture_password


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def hr_fernet_env(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("HR_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["quantity_surveyor", "hr_executive_reader", "hr_executive"])
async def test_hr_onboarding_and_vault_services_authorize_before_record_lookup(role: str) -> None:
    session = Mock(spec=AsyncSession)
    service = HrWorkforceService(session)
    actor = User(role=role)
    record_id = uuid4()
    file = UploadFile(io.BytesIO(b"synthetic evidence"), filename="evidence.pdf")
    calls = (
        lambda: service.list_onboarding_cases(actor=actor),
        lambda: service.get_onboarding_case(record_id, actor),
        lambda: service.create_onboarding_case(
            OnboardingCaseCreateRequest(employee_id=record_id, start_date=date(2026, 7, 1)),
            actor,
        ),
        lambda: service.update_onboarding_task(
            record_id,
            OnboardingTaskUpdateRequest(status="completed", evidence_notes="Checked"),
            actor,
        ),
        lambda: service.list_hr_documents(actor=actor),
        lambda: service.get_hr_document_detail(record_id, actor),
        lambda: service.get_hr_document_download_url(record_id, actor),
        lambda: service.upload_hr_document(
            title="Synthetic evidence",
            document_type="onboarding_evidence",
            category="ordinary",
            employee_id=record_id,
            candidate_id=None,
            issue_date=None,
            expiry_date=None,
            issuing_authority=None,
            reference_number=None,
            is_employee_visible=False,
            file=file,
            actor=actor,
        ),
        lambda: service.upload_hr_document_version(record_id, file, actor),
        lambda: service.decide_hr_document_version(
            record_id, 1, HrDocumentDecisionRequest(decision="approve"), actor
        ),
    )
    for call in calls:
        with pytest.raises(AppException) as denied:
            await call()
        assert denied.value.status_code == 403
    assert not session.mock_calls


async def _create_portal_user(
    role: str, password: str = "Start123!", *, email: str | None = None
) -> tuple[str, str, str]:
    user_email = email or f"{role}-{uuid4().hex}@example.com"
    user_id = ""
    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).add(
            User(
                email=user_email,
                full_name=f"Synthetic {role}",
                role=role,
                employee_code=f"SYN-{uuid4().hex[:8]}",
                phone="+94770000000",
                designation=role.replace("_", " ").title(),
                password_hash=hash_fixture_password(password),
                must_change_password=False,
            )
        )
        await session.commit()
        user_id = str(user.id)
    return user_id, user_email, password


async def _create_legacy_leave_type(name: str, *, is_paid: bool = True) -> str:
    """Seed an already-configured type for tests of legacy generic leave flows."""
    async with AsyncSessionLocal() as session:
        row = HrLeaveType(
            code=f"LEGACY-{uuid4().hex[:12]}",
            name=name,
            is_paid=is_paid,
            is_active=True,
            policy_required=False,
        )
        session.add(row)
        await session.flush()
        leave_type_id = str(row.id)
        await session.commit()
    return leave_type_id


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver"
    )


async def _login(client: httpx.AsyncClient, email: str, password: str) -> str:
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_res.status_code == 200, login_res.text
    challenge = login_res.json()
    verify_res = await client.post(
        "/api/v1/auth/verify-otp",
        json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
    )
    assert verify_res.status_code == 200, verify_res.text
    return str(verify_res.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _pdf_bytes(label: str = "hr-doc") -> bytes:
    return f"%PDF-1.4\n1 0 obj<<>>endobj\n% {label}\n%%EOF".encode()


async def _publish_leave_calendar(client, preparer, reviewer, start, end, holiday=None):
    path = "/api/v1/hr/calendars"
    response = await client.post(
        path,
        headers=preparer,
        json={
            "code": f"LEAVE-{uuid4().hex[:8]}",
            "name": "Synthetic leave calendar",
            "is_default": True,
            "work_days_json": ["MON", "TUE", "WED", "THU", "FRI"],
            "standard_start_time": "08:00",
            "standard_end_time": "17:00",
            "daily_hours": "8.00",
            "effective_from": start,
            "effective_to": end,
            "timezone": "Asia/Colombo",
        },
    )
    assert response.status_code == 201, response.text
    calendar = response.json()
    if holiday:
        response = await client.post(
            "/api/v1/hr/holidays",
            headers=preparer,
            json={
                "calendar_id": calendar["id"],
                "holiday_date": holiday,
                "name": "Fixture holiday",
            },
        )
        assert response.status_code == 201, response.text
        calendar["revision"] += 1
    for action, actor in (("submit", preparer), ("approve", reviewer), ("publish", reviewer)):
        response = await client.post(
            f"{path}/{calendar['id']}/decision",
            headers=actor,
            json={"action": action, "expected_revision": calendar["revision"]},
        )
        assert response.status_code == 200, response.text
        calendar = response.json()
    return calendar


def test_sensitive_hr_fields_require_a_valid_dedicated_key(monkeypatch) -> None:
    monkeypatch.delenv("HR_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(AppException) as missing:
        encrypt_hr_value("synthetic-id")
    assert missing.value.error_code == "HR_ENCRYPTION_UNAVAILABLE"
    monkeypatch.setenv("HR_ENCRYPTION_KEY", "not-a-fernet-key")
    get_settings.cache_clear()
    with pytest.raises(AppException) as invalid:
        encrypt_hr_value("synthetic-id")
    assert invalid.value.error_code == "HR_ENCRYPTION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_hr_a_rbac_separation() -> None:
    await skip_if_database_unavailable()
    _, admin_email, pw = await _create_portal_user("managing_director")
    _, hrm_email, _ = await _create_portal_user("hr_manager", pw)

    async with _client() as client:
        admin_tok = await _login(client, admin_email, pw)
        hrm_tok = await _login(client, hrm_email, pw)

        # Admin cannot access HR operational routes
        assert (
            await client.get("/api/v1/hr/employees", headers=_auth(admin_tok))
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/hr/departments",
                json={"code": "ADMBLK", "name": "Blocked Dept"},
                headers=_auth(admin_tok),
            )
        ).status_code == 403
        assert (
            await client.get("/api/v1/hr/reports/summary", headers=_auth(admin_tok))
        ).status_code == 403
        export_path = "/api/v1/hr/reports/summary.xlsx"
        assert (await client.get(export_path, headers=_auth(admin_tok))).status_code == 403
        export = await client.get(export_path, headers=_auth(hrm_tok))
        assert export.status_code == 200
        assert export.headers["cache-control"] == "no-store"
        assert "attachment" in export.headers["content-disposition"]
        with ZipFile(io.BytesIO(export.content)) as workbook:
            summary_sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
            assert "Total employees" in summary_sheet
            assert "Pending leave requests" in summary_sheet
            assert "@example.com" not in summary_sheet
            assert "salary" not in summary_sheet.lower()
        # Admin CAN view the access request queue
        assert (
            await client.get("/api/v1/hr/access-requests", headers=_auth(admin_tok))
        ).status_code == 200

        # HR roles cannot access Finance, Inventory, or Projects
        for tok in (hrm_tok,):
            assert (
                await client.get("/api/v1/finance/invoices", headers=_auth(tok))
            ).status_code == 403
            assert (
                await client.get("/api/v1/inventory/items", headers=_auth(tok))
            ).status_code == 403
            assert (await client.get("/api/v1/projects", headers=_auth(tok))).status_code == 403
        # HR work does not grant generic audit, account mutation or document access.
        assert (await client.get("/api/v1/audit-logs", headers=_auth(hrm_tok))).status_code == 403
        assert (await client.get("/api/v1/users", headers=_auth(hrm_tok))).status_code == 200
        assert (
            await client.post(
                "/api/v1/users",
                json={
                    "email": f"blocked-{uuid4().hex[:6]}@example.com",
                    "full_name": "Blocked User",
                    "employee_code": f"BLK-{uuid4().hex[:4]}",
                    "phone": "+94770000999",
                    "role": "site_supervisor",
                    "temporary_password": "TempPassword123!",
                },
                headers=_auth(hrm_tok),
            )
        ).status_code == 403

        # HR has the directory grant while an unrelated administrator cannot access the vault.
        emp_res = await client.post(
            "/api/v1/hr/employees",
            json={
                "employee_code": f"HRA-{uuid4().hex[:6]}",
                "first_name": "Sample",
                "last_name": "Engineer",
                "work_email": f"sample-{uuid4().hex[:6]}@example.com",
            },
            headers=_auth(hrm_tok),
        )
        assert emp_res.status_code == 201
        emp_id = emp_res.json()["id"]

        assert (
            await client.get(f"/api/v1/hr/employees/{emp_id}/private", headers=_auth(admin_tok))
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/hr/cases",
                json={
                    "case_code": f"CASE-{uuid4().hex[:6]}",
                    "employee_id": emp_id,
                    "case_type": "grievance",
                    "title": "Blocked Case",
                    "details": "Confidential matter",
                },
                headers=_auth(hrm_tok),
            )
        ).status_code == 403


@pytest.mark.asyncio
async def test_hr_reports_share_filters_and_exclude_restricted_values() -> None:
    await skip_if_database_unavailable()
    _, exec_email, pw = await _create_portal_user("hr_manager")
    _, manager_email, _ = await _create_portal_user("hr_manager", pw)
    _, staff_email, _ = await _create_portal_user("quantity_surveyor", pw)
    day = date(2027, 1, 5)
    marker = f"WRK-{uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        dept = HrDepartment(code=f"{marker}-A", name=f"Department {marker} A")
        other_dept = HrDepartment(code=f"{marker}-B", name=f"Department {marker} B")
        site = Project(
            name=f"Site {marker} A",
            code=f"{marker}-A",
            scope_of_work="Test",
            target_end_date=date(2027, 12, 31),
        )
        other_site = Project(
            name=f"Site {marker} B",
            code=f"{marker}-B",
            scope_of_work="Test",
            target_end_date=date(2027, 12, 31),
        )
        session.add_all((dept, other_dept, site, other_site))
        await session.flush()
        key = {"project_id": str(site.id), "department_id": str(dept.id)}
        first = HrEmployee(
            employee_code=f"{marker}-1",
            first_name="Synthetic",
            last_name="One",
            full_name="Synthetic Employee One",
            work_email="secret-employee-" + marker.lower() + "@example.com",
            department_id=dept.id,
            primary_project_id=site.id,
            employment_status="active",
        )
        second = HrEmployee(
            employee_code=f"{marker}-2",
            first_name="Synthetic",
            last_name="Two",
            full_name="Synthetic Employee Two",
            department_id=other_dept.id,
            primary_project_id=site.id,
            employment_status="terminated",
        )
        third = HrEmployee(
            employee_code=f"{marker}-3",
            first_name="Synthetic",
            last_name="Three",
            full_name="Synthetic Employee Three",
            department_id=dept.id,
            primary_project_id=other_site.id,
            employment_status="on_probation",
        )
        session.add_all((first, second, third))
        await session.flush()
        session.add_all(
            (
                HrAttendanceEntry(employee_id=first.id, work_date=day, attendance_status="absent"),
                HrAttendanceEntry(
                    employee_id=first.id,
                    work_date=date(2027, 1, 6),
                    attendance_status="absent",
                    scheduled_workday=False,
                ),
                HrAttendanceEntry(
                    employee_id=first.id, work_date=date(2027, 1, 4), attendance_status="absent"
                ),
                HrAttendanceEntry(employee_id=second.id, work_date=day, attendance_status="absent"),
                HrAttendanceEntry(employee_id=third.id, work_date=day, attendance_status="absent"),
                HrOnboardingCase(
                    employee_id=third.id, start_date=date(2026, 10, 5), probation_end_date=day
                ),
            )
        )
        for employee, category in ((first, "ordinary"), (first, "medical"), (second, "ordinary")):
            document = HrDocument(
                employee_id=employee.id,
                title=f"Private marker {marker}",
                document_type="contract",
                category=category,
                expiry_date=day,
                status="active",
            )
            session.add(document)
            if category == "medical":
                await session.flush()
                session.add(
                    HrCertification(
                        employee_id=employee.id,
                        document_id=document.id,
                        name=f"Private certification {marker}",
                        expiry_date=day,
                    )
                )
        await session.commit()

    async with _client() as client:
        executive = _auth(await _login(client, exec_email, pw))
        manager = _auth(await _login(client, manager_email, pw))
        staff = _auth(await _login(client, staff_email, pw))
        base = "/api/v1/hr/reports/summary"
        filters = {**key, "date_from": day.isoformat(), "date_to": "2027-01-06"}
        denied = await client.get(base, params=filters, headers=staff)
        assert denied.status_code == 403
        assert "total_employees" not in denied.json()
        sites_url = "/api/v1/hr/reports/sites"
        assert (await client.get(sites_url, headers=staff)).status_code == 403
        first_page = (await client.get(sites_url, headers=executive, params={"limit": 1})).json()
        next_page = (
            await client.get(sites_url, headers=executive, params={"limit": 1, "offset": 1})
        ).json()
        assert first_page["has_more"] is True and len(first_page["items"]) == 1
        assert set(first_page["items"][0]) == {"id", "name"}
        assert first_page["items"][0]["id"] != next_page["items"][0]["id"]

        assert (
            await client.get(base, params={**filters, "date_to": "2027-01-04"}, headers=executive)
        ).status_code == 422
        assert (
            await client.get(base, params={**key, "date_from": day.isoformat()}, headers=executive)
        ).status_code == 422
        scoped = await client.get(base, params=filters, headers=executive)
        assert scoped.status_code == 200, scoped.text
        report = scoped.json()
        assert report["filters"] == filters
        assert report["attendance_window"] == report["due_window"]
        assert report["attendance_exceptions"] == report["credentials_due"] == 1
        assert report["total_employees"] == report["active_employees"] == 1
        assert report["probation_reviews_due"] == report["separated_employees"] == 0
        assert report["training_sessions_due"] == 0
        assert scoped.headers["cache-control"] == "no-store"
        assert (await client.get(base, params=filters, headers=manager)).json()[
            "credentials_due"
        ] == 1
        project_filter = {name: value for name, value in filters.items() if name != "department_id"}
        assert (await client.get(base, params=project_filter, headers=manager)).json()[
            "separated_employees"
        ] == 1
        department_filter = {name: value for name, value in filters.items() if name != "project_id"}
        assert (await client.get(base, params=department_filter, headers=manager)).json()[
            "probation_reviews_due"
        ] == 1

        for extension, mime in (
            ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("csv", "text/csv"),
            ("pdf", "application/pdf"),
        ):
            route = f"{base}.{extension}"
            assert (await client.get(route, params=filters, headers=staff)).status_code == 403
            download = await client.get(route, params=filters, headers=executive)
            assert download.status_code == 200, download.text
            assert download.headers["content-type"].startswith(mime)
            assert download.headers["cache-control"] == "no-store"
            assert f"hr-summary.{extension}" in download.headers["content-disposition"]
            if extension == "xlsx":
                with ZipFile(io.BytesIO(download.content)) as workbook:
                    rendered = workbook.read("xl/worksheets/sheet1.xml") + workbook.read(
                        "docProps/custom.xml"
                    )
                    assert (
                        b"Attendance exceptions" in rendered
                        and day.isoformat().encode() in rendered
                    )
            else:
                rendered = download.content
                if extension == "csv":
                    assert (
                        rendered.startswith(b"Metric,Count")
                        and b"Attendance exceptions,1" in rendered
                    )
                else:
                    assert rendered.startswith(b"%PDF-") and rendered.rstrip().endswith(b"%%EOF")
                    compressed = re.findall(rb"\nstream\r?\n(.*?)endstream", rendered, re.DOTALL)
                    rendered = b"\n".join(
                        zlib.decompress(base64.a85decode(stream.strip(), adobe=True))
                        for stream in compressed
                    )
                    assert (
                        b"Attendance exceptions" in rendered
                        and day.isoformat().encode() in rendered
                    )
            assert marker.encode() not in rendered
            assert all(
                value not in rendered.lower()
                for value in (
                    b"synthetic employee",
                    b"private marker",
                    b"salary",
                )
            )


@pytest.mark.asyncio
async def test_hr_credential_reminders_are_opt_in_private_and_deduplicated(monkeypatch) -> None:
    await skip_if_database_unavailable()
    monkeypatch.delenv("HR_REMINDER_WINDOW_DAYS", raising=False)
    get_settings.cache_clear()
    enqueue = Mock()
    monkeypatch.setattr("app.services.notification_service.send_email_notification.delay", enqueue)
    hr_manager, _, _ = await _create_portal_user("hr_manager")
    executive, _, _ = await _create_portal_user("administrative_executive")
    director, _, _ = await _create_portal_user("managing_director")
    inactive, _, _ = await _create_portal_user("hr_manager")
    marker = "PRIVATE-" + uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        inactive_user = await session.get(User, UUID(inactive))
        assert inactive_user is not None
        inactive_user.is_active = False
        employee = HrEmployee(
            employee_code=marker,
            first_name="Synthetic",
            last_name="Reminder",
            full_name="Synthetic Reminder",
            employment_status="active",
        )
        session.add(employee)
        await session.flush()
        session.add(
            HrDocument(
                employee_id=employee.id,
                title=marker,
                document_type="qualification",
                category="ordinary",
                expiry_date=business_today(),
                status="active",
            )
        )
        await session.commit()

    assert await _check_hr_credential_expiry() == 0
    monkeypatch.setenv("HR_REMINDER_WINDOW_DAYS", "7")
    get_settings.cache_clear()
    runs = sorted(
        await asyncio.gather(_check_hr_credential_expiry(), _check_hr_credential_expiry())
    )
    assert runs[0] == 0 and runs[1] >= 1
    assert await _check_hr_credential_expiry() == 0
    enqueue.assert_not_called()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(Notification).where(
                    Notification.user_id.in_(
                        [UUID(value) for value in (hr_manager, executive, director, inactive)]
                    ),
                    Notification.notification_type == "hr_credential_expiry",
                )
            )
        ).all()
        assert {str(row.user_id) for row in rows} == {hr_manager}
        assert len(rows) == 1
        for row in rows:
            assert row.reference_id is None and row.email_status is None
            assert marker not in f"{row.title} {row.body}"


@pytest.mark.asyncio
async def test_hr_service_request_sla_reminds_only_active_authorized_users(monkeypatch) -> None:
    await skip_if_database_unavailable()
    monkeypatch.delenv("HR_SERVICE_REQUEST_SLA_DAYS", raising=False)
    get_settings.cache_clear()
    enqueue = Mock()
    monkeypatch.setattr("app.services.notification_service.send_email_notification.delay", enqueue)
    manager, _, _ = await _create_portal_user("hr_manager")
    successor, _, _ = await _create_portal_user("hr_manager")
    fallback, _, _ = await _create_portal_user("hr_manager")
    director, _, _ = await _create_portal_user("managing_director")
    inactive, _, _ = await _create_portal_user("hr_manager")
    marker = f"REQ-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        inactive_user = await session.get(User, UUID(inactive))
        assert inactive_user is not None
        inactive_user.is_active = False
        employee = HrEmployee(
            employee_code=marker,
            first_name="Synthetic",
            last_name="Requester",
            full_name="Synthetic Requester",
            employment_status="active",
        )
        session.add(employee)
        await session.flush()
        eligible = HrServiceRequest(
            request_code=marker,
            employee_id=employee.id,
            request_type="general_inquiry",
            subject=marker,
            status="completed",
            created_at=now - timedelta(days=7),
        )
        recent = HrServiceRequest(
            request_code=f"{marker}-RECENT",
            employee_id=employee.id,
            request_type="general_inquiry",
            subject=marker,
            status="in_review",
            created_at=now - timedelta(days=7) + timedelta(seconds=1),
        )
        session.add_all([eligible, recent])
        await session.commit()
        request_id = eligible.id

    assert await _check_hr_service_request_sla() == 0
    monkeypatch.setenv("HR_SERVICE_REQUEST_SLA_DAYS", "7")
    monkeypatch.setattr("app.tasks.maintenance.utc_now", lambda: now)
    get_settings.cache_clear()
    assert await _check_hr_service_request_sla() == 0

    async with AsyncSessionLocal() as session:
        request = await session.get(HrServiceRequest, request_id)
        assert request is not None
        request.status = "approved"
        request.assigned_to_id = UUID(manager)
        await session.commit()
    runs = sorted(
        await asyncio.gather(_check_hr_service_request_sla(), _check_hr_service_request_sla())
    )
    assert runs == [0, 1]
    assert await _check_hr_service_request_sla() == 0
    async with AsyncSessionLocal() as session:
        request = await session.get(HrServiceRequest, request_id)
        assert request is not None
        request.assigned_to_id = UUID(successor)
        await session.commit()
    assert await _check_hr_service_request_sla() == 1
    assert await _check_hr_service_request_sla() == 0
    async with AsyncSessionLocal() as session:
        request = await session.get(HrServiceRequest, request_id)
        assert request is not None
        request.assigned_to_id = UUID(inactive)
        await session.commit()
    # An invalid owner is treated like an unassigned request on the next sweep.
    assert await _check_hr_service_request_sla() >= 1
    assert await _check_hr_service_request_sla() == 0
    enqueue.assert_not_called()
    tracked_users = [UUID(value) for value in (manager, successor, fallback, director, inactive)]
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(Notification).where(
                    Notification.user_id.in_(tracked_users),
                    Notification.notification_type == "hr_service_request_sla",
                )
            )
        ).all()
        assert {str(row.user_id) for row in rows} == {manager, successor, fallback}
        assert len(rows) == 3
        for row in rows:
            assert row.reference_id is None and row.email_status is None
            assert marker not in f"{row.title} {row.body}"
        request = await session.get(HrServiceRequest, request_id)
        assert request is not None
        request.status = "completed"
        recent_request = await session.get(HrServiceRequest, recent.id)
        assert recent_request is not None
        recent_request.status = "completed"
        await session.commit()


@pytest.mark.asyncio
async def test_hr_b_org_revisions_cycles_and_encrypted_private_vault() -> None:
    await skip_if_database_unavailable()
    tag = uuid4().hex[:6]
    _, hrm_email, pw = await _create_portal_user("hr_manager")

    async with _client() as client:
        tok = await _login(client, hrm_email, pw)

        dept = await client.post(
            "/api/v1/hr/departments",
            json={"code": f"ENG-{tag[:4]}", "name": "Engineering Ops"},
            headers=_auth(tok),
        )
        assert dept.status_code == 201
        dept_id = dept.json()["id"]

        pos = await client.post(
            "/api/v1/hr/positions",
            json={
                "code": f"QS-{tag[:4]}",
                "title": "Lead Quantity Surveyor",
                "department_id": dept_id,
                "headcount_limit": 1,
            },
            headers=_auth(tok),
        )
        assert pos.status_code == 201
        pos_id = pos.json()["id"]

        emp1 = await client.post(
            "/api/v1/hr/employees",
            json={
                "employee_code": f"E1-{tag}",
                "first_name": "Manager",
                "last_name": f"One {tag}",
                "department_id": dept_id,
                "position_id": pos_id,
            },
            headers=_auth(tok),
        )
        assert emp1.status_code == 201
        emp1_id = emp1.json()["id"]

        # Second employee in same headcount-limited position blocked without override
        blocked = await client.post(
            "/api/v1/hr/employees",
            json={
                "employee_code": f"E2-{tag}",
                "first_name": "Staff",
                "last_name": f"Two {tag}",
                "department_id": dept_id,
                "position_id": pos_id,
            },
            headers=_auth(tok),
        )
        assert blocked.status_code == 409

        emp2 = await client.post(
            "/api/v1/hr/employees",
            json={
                "employee_code": f"E2-{tag}",
                "first_name": "Staff",
                "last_name": f"Two {tag}",
                "department_id": dept_id,
                "position_id": pos_id,
                "manager_employee_id": emp1_id,
                "override_headcount": True,
            },
            headers=_auth(tok),
        )
        assert emp2.status_code == 201
        emp2_id = emp2.json()["id"]

        # Manager cycle rejection: making emp1 report to emp2 creates a cycle
        cyc = await client.patch(
            f"/api/v1/hr/employees/{emp1_id}",
            json={"expected_revision": 1, "manager_employee_id": emp2_id},
            headers=_auth(tok),
        )
        assert cyc.status_code == 422

        # Valid update bumps revision & stale revision fails with 409
        upd = await client.patch(
            f"/api/v1/hr/employees/{emp1_id}",
            json={"expected_revision": 1, "work_location": "Colombo HQ"},
            headers=_auth(tok),
        )
        assert upd.status_code == 200
        assert upd.json()["record_revision"] == 2

        stale = await client.patch(
            f"/api/v1/hr/employees/{emp1_id}",
            json={"expected_revision": 1, "work_location": "Stale Edit"},
            headers=_auth(tok),
        )
        assert stale.status_code == 409

        hist = await client.get(f"/api/v1/hr/employees/{emp1_id}/history", headers=_auth(tok))
        assert hist.status_code == 200
        assert hist.json()["total"] >= 2

        # Org chart returns hierarchy
        org = await client.get("/api/v1/hr/org-chart", headers=_auth(tok))
        assert org.status_code == 200
        assert org.json()["total_employees"] >= 2

        # Encrypted private vault stores ciphertext and masks default reads
        priv_put = await client.put(
            f"/api/v1/hr/employees/{emp1_id}/private",
            json={"expected_revision": upd.json()["record_revision"], "national_id": "901234567V"},
            headers=_auth(tok),
        )
        assert priv_put.status_code == 200
        assert priv_put.json()["record_revision"] == 3
        masked_body = (
            await client.get(f"/api/v1/hr/employees/{emp1_id}/private", headers=_auth(tok))
        ).json()
        assert masked_body["national_id_masked"].endswith("567V")
        assert masked_body["national_id_plain"] is None

        revealed_body = (
            await client.get(
                f"/api/v1/hr/employees/{emp1_id}/private?reveal_sensitive=true",
                headers=_auth(tok),
            )
        ).json()
        assert revealed_body["national_id_plain"] == "901234567V"
        assert revealed_body["bank_account_plain"] is None

        async with AsyncSessionLocal() as session:
            row = await session.scalar(
                select(HrEmployeePrivate).where(HrEmployeePrivate.employee_id == UUID(emp1_id))
            )
            assert row is not None
            assert row.national_id_encrypted is not None
            assert "901234567V" not in row.national_id_encrypted


@pytest.mark.asyncio
async def test_hr_c_three_party_access_requests_and_session_revocation() -> None:
    await skip_if_database_unavailable()
    _, admin_email, pw = await _create_portal_user("managing_director")
    _, hre_email, _ = await _create_portal_user("hr_manager", pw)
    _, hrm_email, _ = await _create_portal_user("hr_manager", pw)
    staff_email = f"provisioned-{uuid4().hex[:8]}@example.com"

    async with _client() as client:
        admin_tok = await _login(client, admin_email, pw)
        hre_tok = await _login(client, hre_email, pw)
        hrm_tok = await _login(client, hrm_email, pw)

        emp = await client.post(
            "/api/v1/hr/employees",
            json={
                "employee_code": f"HRC-{uuid4().hex[:6]}",
                "first_name": "Portal",
                "last_name": "Staff",
                "work_email": staff_email,
                "work_phone": "+97455550000",
                "employment_status": "draft",
            },
            headers=_auth(hre_tok),
        )
        assert emp.status_code == 201
        emp_id = emp.json()["id"]

        # One HR Manager submits the provision request
        req_res = await client.post(
            "/api/v1/hr/access-requests",
            json={
                "employee_id": emp_id,
                "request_type": "provision",
                "requested_role": "quantity_surveyor",
                "requested_email": staff_email,
                "submit_immediately": True,
            },
            headers=_auth(hre_tok),
        )
        assert req_res.status_code == 201
        req_id = req_res.json()["id"]

        # The preparing HR Manager cannot approve their own request
        assert (
            await client.post(
                f"/api/v1/hr/access-requests/{req_id}/decision",
                json={"action": "hr_approve"},
                headers=_auth(hre_tok),
            )
        ).status_code == 403

        # Admin cannot admin_action before hr_approve
        assert (
            await client.post(
                f"/api/v1/hr/access-requests/{req_id}/decision",
                json={"action": "admin_action", "temporary_password": "TempPass123!"},
                headers=_auth(admin_tok),
            )
        ).status_code == 409

        # HR Manager approves, then Admin provisions portal user
        assert (
            await client.post(
                f"/api/v1/hr/access-requests/{req_id}/decision",
                json={"action": "hr_approve", "notes": "Approved for project site"},
                headers=_auth(hrm_tok),
            )
        ).status_code == 200

        provisioned = await client.post(
            f"/api/v1/hr/access-requests/{req_id}/decision",
            json={"action": "admin_action", "temporary_password": "TempPass123!"},
            headers=_auth(admin_tok),
        )
        assert provisioned.status_code == 200
        assert provisioned.json()["status"] == "admin_actioned"
        user_id = provisioned.json()["linked_user_id"]
        assert user_id is not None

        # Provisioned user logs in cleanly, then deactivate request revokes session immediately
        staff_tok = await _login(client, staff_email, "TempPass123!")
        assert (await client.get("/api/v1/auth/me", headers=_auth(staff_tok))).status_code == 200

        deact_req = await client.post(
            "/api/v1/hr/access-requests",
            json={
                "employee_id": emp_id,
                "request_type": "deactivate",
                "submit_immediately": True,
            },
            headers=_auth(hre_tok),
        )
        deact_id = deact_req.json()["id"]
        assert (
            await client.post(
                f"/api/v1/hr/access-requests/{deact_id}/decision",
                json={"action": "hr_approve"},
                headers=_auth(hrm_tok),
            )
        ).status_code == 200
        assert (
            await client.post(
                f"/api/v1/hr/access-requests/{deact_id}/decision",
                json={"action": "admin_action"},
                headers=_auth(admin_tok),
            )
        ).status_code == 200

        assert (await client.get("/api/v1/auth/me", headers=_auth(staff_tok))).status_code == 401


@pytest.mark.asyncio
async def test_hr_d_workbook_preview_and_idempotent_apply() -> None:
    await skip_if_database_unavailable()
    tag = uuid4().hex[:6]
    _, hrm_email, pw = await _create_portal_user("hr_manager")

    async with _client() as client:
        tok = await _login(client, hrm_email, pw)

        csv_rows = [
            "User Name,Email,Portal Access Required,Role to Assign,"
            "Role Description,Privileges,Access Scope",
            f"Staff {tag} One,s1-{tag}@example.com,Yes,group_project_manager,"
            "PM,Manage projects,Assigned",
            f"Staff {tag} Two,Need email,Yes,quantity_surveyor,QS,Submit,Assigned",
            f"Staff {tag} Three,s3-{tag}@example.com,No,,None,None,None",
            f"Staff {tag} Four,s4-{tag}@example.com,Yes,Custom Estimator,Est,Track BOQ,Assigned",
            f"Staff {tag} Five,s5-{tag}@example.com,Yes,administrative_executive,"
            "Exec,Finance,Company",
            f"Staff {tag} Six,Need email,No,,Field,Site,Site",
            f"Staff {tag} Seven,s7-{tag}@example.com,Yes,site_supervisor,Sup,Inventory,Company",
            f"Staff {tag} Eight,s8-{tag}@example.com,Yes,senior_site_supervisor,"
            "SrSup,Updates,Assigned",
            f"Staff {tag} Nine,s9-{tag}@example.com,Yes,hr_manager,HR,Directory,Company",
            f"Staff {tag} Ten,s10-{tag}@example.com,Yes,operations_director,Ops,Company,Company",
        ]
        csv_bytes = ("\n".join(csv_rows) + "\n").encode("utf-8")

        preview = await client.post(
            "/api/v1/hr/imports/workbook-preview",
            files={"file": ("staff.csv", csv_bytes, "text/csv")},
            headers=_auth(tok),
        )
        assert preview.status_code == 200
        p = preview.json()
        assert p["total_rows"] == 10
        assert p["blocked_missing_email_rows"] >= 1
        assert p["unmapped_role_rows"] == 1
        missing_id = "Missing Employee ID for account onboarding."
        missing_phone = "Missing Mobile Number for account onboarding."
        assert set(p["rows"][0]["issues"]) == {missing_id, missing_phone}
        assert p["rows"][2]["issues"] == []

        expanded_rows = [
            f"{csv_rows[0]},Employee ID,Mobile Number",
            f"{csv_rows[1]},00017,+94770000017",
            f"{csv_rows[2]},00018,TBD",
            f"{csv_rows[3]},,",
            f"{csv_rows[4]},,0770000019",
        ]
        expanded = await client.post(
            "/api/v1/hr/imports/workbook-preview",
            files={"file": ("expanded.csv", "\n".join(expanded_rows).encode(), "text/csv")},
            headers=_auth(tok),
        )
        assert expanded.status_code == 200
        expanded_preview = expanded.json()["rows"]
        assert expanded_preview[0]["issues"] == []
        assert missing_id not in expanded_preview[1]["issues"]
        assert missing_phone in expanded_preview[1]["issues"]
        assert expanded_preview[2]["issues"] == []
        assert missing_id in expanded_preview[3]["issues"]
        assert missing_phone not in expanded_preview[3]["issues"]
        assert "00017" not in expanded.text and "+94770000017" not in expanded.text

        # Re-preview with explicit role override resolves Custom Estimator cleanly
        preview2 = await client.post(
            "/api/v1/hr/imports/workbook-preview",
            files={"file": ("staff.csv", csv_bytes, "text/csv")},
            data={
                "explicit_role_overrides_json": json.dumps(
                    {"Custom Estimator": "quantity_surveyor"}
                )
            },
            headers=_auth(tok),
        )
        assert preview2.status_code == 200
        p2 = preview2.json()
        assert p2["unmapped_role_rows"] == 0

        rows_input = [
            {
                "user_name": r["user_name"],
                "email_source": r["email_source"],
                "portal_access_required": r["portal_access_required_raw"],
                "role_to_assign": r["role_source"],
                "role_description_auto": r["role_description_auto"],
                "privileges_auto": r["privileges_auto"],
                "access_scope_auto": r["access_scope_auto"],
            }
            for r in p2["rows"]
        ]
        apply_payload = {
            "rows": rows_input,
            "explicit_role_overrides": {"Custom Estimator": "quantity_surveyor"},
            "allow_missing_email_draft": True,
            "create_access_requests": True,
        }
        applied = await client.post(
            "/api/v1/hr/imports/workbook-apply", json=apply_payload, headers=_auth(tok)
        )
        assert applied.status_code == 200
        assert applied.json()["employees_created"] == 10
        assert applied.json()["access_requests_created"] == 7

        # Re-applying same workbook is strictly idempotent
        reapplied = await client.post(
            "/api/v1/hr/imports/workbook-apply", json=apply_payload, headers=_auth(tok)
        )
        assert reapplied.status_code == 200
        assert reapplied.json()["employees_created"] == 0
        assert reapplied.json()["access_requests_created"] == 0


@pytest.mark.asyncio
async def test_hr_e_recruitment_offer_and_onboarding() -> None:
    await skip_if_database_unavailable()
    _, hrm_email, pw = await _create_portal_user("hr_manager")

    async with _client() as client:
        tok = await _login(client, hrm_email, pw)

        assert (
            await client.post(
                "/api/v1/hr/requisitions",
                json={
                    "requisition_code": f"REQ-BAD-{uuid4().hex[:5]}",
                    "title": "Invalid Headcount",
                    "headcount_requested": 0,
                },
                headers=_auth(tok),
            )
        ).status_code == 422

        req = await client.post(
            "/api/v1/hr/requisitions",
            json={
                "requisition_code": f"REQ-{uuid4().hex[:5]}",
                "title": "Site Foreman",
                "headcount_requested": 2,
            },
            headers=_auth(tok),
        )
        assert req.status_code == 201
        assert req.json()["headcount_requested"] == 2
        req_id = req.json()["id"]

        for step in ("submitted", "approved", "open"):
            assert (
                await client.post(
                    f"/api/v1/hr/requisitions/{req_id}/decision",
                    json={"status": step},
                    headers=_auth(tok),
                )
            ).status_code == 200

        cand = await client.post(
            "/api/v1/hr/candidates",
            json={
                "candidate_code": f"CAND-{uuid4().hex[:5]}",
                "full_name": "Candidate One",
                "email": f"cand-{uuid4().hex[:6]}@example.com",
            },
            headers=_auth(tok),
        )
        assert cand.status_code == 201

        app = await client.post(
            "/api/v1/hr/applications",
            json={"requisition_id": req_id, "candidate_id": cand.json()["id"]},
            headers=_auth(tok),
        )
        assert app.status_code == 201
        app_id = app.json()["id"]

        await _stage_application_for_interview(client, app_id, _auth(tok))
        iv = await client.post(
            "/api/v1/hr/interviews",
            json={"application_id": app_id, "interview_type": "technical"},
            headers=_auth(tok),
        )
        assert iv.status_code == 201
        assert (
            await client.patch(
                f"/api/v1/hr/interviews/{iv.json()['id']}",
                json={"status": "completed"},
                headers=_auth(tok),
            )
        ).status_code == 200
        assert (
            await client.patch(
                f"/api/v1/hr/applications/{app_id}/stage",
                json={"stage": "evaluation"},
                headers=_auth(tok),
            )
        ).status_code == 200

        offer = await client.post(
            "/api/v1/hr/offers",
            json={
                "offer_code": f"OFR-{uuid4().hex[:5]}",
                "application_id": app_id,
                "proposed_title": "Site Foreman",
                "valid_until": business_today().isoformat(),
            },
            headers=_auth(tok),
        )
        assert offer.status_code == 201
        assert offer.json()["version_number"] == 1
        assert offer.json()["valid_until"] == business_today().isoformat()
        offer_id = offer.json()["id"]

        for status_step in ("pending_approval", "approved", "issued", "accepted"):
            res = await client.post(
                f"/api/v1/hr/offers/{offer_id}/decision",
                json={"status": status_step, "expected_version_number": 1},
                headers=_auth(tok),
            )
            assert res.status_code == 200

        converted = await client.post(
            f"/api/v1/hr/offers/{offer_id}/convert",
            json={"employee_code": f"OB-{uuid4().hex[:6]}"},
            headers=_auth(tok),
        )
        assert converted.status_code == 200

        cases = (await client.get("/api/v1/hr/onboarding", headers=_auth(tok))).json()["items"]
        target_case = next(c for c in cases if c["employee_id"] == converted.json()["employee_id"])
        assert len(target_case["tasks"]) >= 1
        for task in target_case["tasks"]:
            assert (
                await client.patch(
                    f"/api/v1/hr/onboarding/tasks/{task['id']}",
                    json={"status": "completed", "evidence_notes": "Done"},
                    headers=_auth(tok),
                )
            ).status_code == 200


async def _stage_application_for_interview(client, application_id, headers):
    for stage in ("screening", "shortlisted", "interview"):
        response = await client.patch(
            f"/api/v1/hr/applications/{application_id}/stage",
            json={"stage": stage},
            headers=headers,
        )
        assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_offer_conversion_respects_requisition_capacity() -> None:
    await skip_if_database_unavailable()
    _, hr_email, password = await _create_portal_user("hr_manager")
    _, staff_email, _ = await _create_portal_user("quantity_surveyor", password)
    base = "/api/v1/hr"

    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        staff = _auth(await _login(client, staff_email, password))

        async def post(path, payload, expected=201):
            result = await client.post(f"{base}/{path}", json=payload, headers=hr)
            assert result.status_code == expected, result.text
            return result.json()

        req = await post(
            "requisitions",
            {
                "requisition_code": f"CAP-{uuid4().hex[:8]}",
                "title": "Synthetic recruitment capacity",
                "headcount_requested": 1,
            },
        )
        req_id = req["id"]
        for status in ("submitted", "approved", "open"):
            await post(f"requisitions/{req_id}/decision", {"status": status}, 200)

        async def accepted_offer():
            candidate = await post(
                "candidates",
                {"candidate_code": f"CAN-{uuid4().hex[:8]}", "full_name": "Synthetic Candidate"},
            )
            application = await post(
                "applications", {"requisition_id": req_id, "candidate_id": candidate["id"]}
            )
            app_id = application["id"]
            await _stage_application_for_interview(client, app_id, hr)
            interview = await post(
                "interviews", {"application_id": app_id, "interview_type": "technical"}
            )
            response = await client.patch(
                f"{base}/interviews/{interview['id']}", json={"status": "completed"}, headers=hr
            )
            assert response.status_code == 200, response.text
            response = await client.patch(
                f"{base}/applications/{app_id}/stage", json={"stage": "evaluation"}, headers=hr
            )
            assert response.status_code == 200, response.text
            offer = await post(
                "offers",
                {
                    "offer_code": f"OFR-{uuid4().hex[:8]}",
                    "application_id": app_id,
                    "proposed_title": "Synthetic Role",
                },
            )
            for status in ("pending_approval", "approved", "issued", "accepted"):
                await post(f"offers/{offer['id']}/decision", {"status": status}, 200)
            return offer["id"], {"employee_code": f"CAP-{uuid4().hex[:8]}"}

        conversions = [await accepted_offer(), await accepted_offer()]
        offer_id, payload = conversions[0]
        decision_path = f"{base}/requisitions/{req_id}/decision"
        early = await client.post(decision_path, json={"status": "filled"}, headers=hr)
        assert early.status_code == 409
        assert early.json()["error_code"] == "REQUISITION_VACANCIES_REMAIN"
        await post(f"requisitions/{req_id}/decision", {"status": "on_hold"}, 200)
        held = await client.post(f"{base}/offers/{offer_id}/convert", json=payload, headers=hr)
        assert held.status_code == 409
        assert held.json()["error_code"] == "REQUISITION_NOT_OPEN"
        await post(f"requisitions/{req_id}/decision", {"status": "open"}, 200)
        denied = await client.post(f"{base}/offers/{offer_id}/convert", json=payload, headers=staff)
        assert denied.status_code == 403
        assert (await client.get(f"{base}/offers/{offer_id}", headers=staff)).status_code == 403
        responses = await asyncio.gather(
            *(
                client.post(f"{base}/offers/{offer_id}/convert", json=payload, headers=hr)
                for offer_id, payload in conversions
            )
        )
        assert sorted(result.status_code for result in responses) == [200, 409]
        winner = next(i for i, result in enumerate(responses) if result.status_code == 200)
        assert responses[1 - winner].json()["error_code"] == "REQUISITION_CAPACITY_REACHED"
        offer_id, payload = conversions[winner]
        retry = await post(f"offers/{offer_id}/convert", payload, 200)
        assert retry["id"] == responses[winner].json()["id"]
        assert retry["employee_id"] == responses[winner].json()["employee_id"]
        readback = await client.get(f"{base}/offers/{offer_id}", headers=hr)
        assert readback.status_code == 200
        assert readback.json()["status"] == "converted"
        assert readback.json()["converted_employee_id"] == retry["employee_id"]

        applications = await client.get(
            f"{base}/applications", params={"requisition_id": req_id}, headers=hr
        )
        assert applications.status_code == 200
        assert sum(row["stage"] == "hired" for row in applications.json()["items"]) == 1
        requisitions = await client.get(f"{base}/requisitions", headers=hr)
        assert requisitions.status_code == 200
        saved = next(row for row in requisitions.json()["items"] if row["id"] == req_id)
        assert saved["status"] == "filled"


@pytest.mark.asyncio
async def test_hr_recruitment_requisition_rejection_and_offer_expiry_versioning(
    monkeypatch,
) -> None:
    await skip_if_database_unavailable()
    _, hrm_email, hrm_pw = await _create_portal_user("hr_manager")
    _, reviewer_email, reviewer_pw = await _create_portal_user("hr_manager")
    _, sup_email, sup_pw = await _create_portal_user("site_supervisor")
    base_today = date(2027, 3, 10)
    monkeypatch.setattr("app.services.hr_workforce_service.business_today", lambda: base_today)

    async with _client() as client:
        hr = _auth(await _login(client, hrm_email, hrm_pw))
        reviewer = _auth(await _login(client, reviewer_email, reviewer_pw))
        sup = _auth(await _login(client, sup_email, sup_pw))

        # --- HR-008: Requisition rejection persistence, headcount, and access control ---
        assert (
            await client.post(
                "/api/v1/hr/requisitions",
                json={"requisition_code": f"REQ-DENY-{uuid4().hex[:5]}", "title": "Denied"},
                headers=sup,
            )
        ).status_code == 403

        req = await client.post(
            "/api/v1/hr/requisitions",
            json={
                "requisition_code": f"REQ-REJ-{uuid4().hex[:5]}",
                "title": "MEP Engineer",
                "headcount_requested": 3,
            },
            headers=hr,
        )
        assert req.status_code == 201
        req_id = req.json()["id"]
        assert req.json()["headcount_requested"] == 3
        assert (
            await client.post(
                f"/api/v1/hr/requisitions/{req_id}/decision",
                json={"status": "submitted"},
                headers=hr,
            )
        ).status_code == 200

        # Non-HR user cannot reject or view requisitions.
        assert (
            await client.post(
                f"/api/v1/hr/requisitions/{req_id}/decision",
                json={"status": "rejected", "notes": "Unauthorized"},
                headers=sup,
            )
        ).status_code == 403
        assert (await client.get("/api/v1/hr/requisitions", headers=sup)).status_code == 403
        req_path = f"/api/v1/hr/requisitions/{req_id}"
        assert (await client.get(req_path, headers=sup)).status_code == 403
        snapshot = await client.get(req_path, headers=hr)
        assert snapshot.status_code == 200 and snapshot.headers["cache-control"] == "no-store"
        assert (
            await client.post(
                f"{req_path}/decision",
                json={
                    "status": "rejected",
                    "notes": "Stale decision",
                    "expected_updated_at": req.json()["updated_at"],
                },
                headers=hr,
            )
        ).status_code == 409

        # Blank rejection reason fails with 422.
        assert (
            await client.post(
                f"/api/v1/hr/requisitions/{req_id}/decision",
                json={"status": "rejected", "notes": "   "},
                headers=hr,
            )
        ).status_code == 422

        confidential_reason = "Confidential budget hold for confidential restructuring."
        rejected = await client.post(
            f"/api/v1/hr/requisitions/{req_id}/decision",
            json={
                "status": "rejected",
                "notes": confidential_reason,
                "expected_updated_at": snapshot.json()["updated_at"],
            },
            headers=hr,
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["rejection_reason"] == confidential_reason

        listed_reqs = await client.get(
            "/api/v1/hr/requisitions",
            headers=hr,
            params={"code": req.json()["requisition_code"], "req_status": "rejected", "limit": 1},
        )
        assert listed_reqs.status_code == 200
        assert listed_reqs.json()["total"] == 1
        reloaded_req = next(item for item in listed_reqs.json()["items"] if item["id"] == req_id)
        assert reloaded_req["rejection_reason"] == confidential_reason
        assert reloaded_req["headcount_requested"] == 3

        async with AsyncSessionLocal() as session:
            req_row = await session.get(HrRequisition, UUID(req_id))
            assert req_row is not None and req_row.rejection_reason == confidential_reason
            audit_rows = list(
                await session.scalars(
                    select(ActivityLog).where(
                        ActivityLog.entity_type == "hr_requisitions",
                        ActivityLog.entity_id == UUID(req_id),
                        ActivityLog.action == "hr.requisition.rejected",
                    )
                )
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].new_values is None

        # --- HR-010: Offer expiry boundaries, concurrency, and immutable versioned terms ---
        open_req = await client.post(
            "/api/v1/hr/requisitions",
            json={
                "requisition_code": f"REQ-OPEN-{uuid4().hex[:5]}",
                "title": "Quantity Surveyor",
                "headcount_requested": 2,
            },
            headers=hr,
        )
        assert open_req.status_code == 201
        open_req_id = open_req.json()["id"]
        for step in ("submitted", "approved", "open"):
            assert (
                await client.post(
                    f"/api/v1/hr/requisitions/{open_req_id}/decision",
                    json={"status": step},
                    headers=hr,
                )
            ).status_code == 200

        cand = await client.post(
            "/api/v1/hr/candidates",
            json={
                "candidate_code": f"CAND-V-{uuid4().hex[:5]}",
                "full_name": "Candidate Versioned",
            },
            headers=hr,
        )
        assert cand.status_code == 201
        app = await client.post(
            "/api/v1/hr/applications",
            json={"requisition_id": open_req_id, "candidate_id": cand.json()["id"]},
            headers=hr,
        )
        assert app.status_code == 201
        app_id = app.json()["id"]
        await _stage_application_for_interview(client, app_id, hr)
        iv = await client.post(
            "/api/v1/hr/interviews",
            json={"application_id": app_id, "interview_type": "technical"},
            headers=hr,
        )
        assert (
            await client.patch(
                f"/api/v1/hr/interviews/{iv.json()['id']}",
                json={"status": "completed"},
                headers=hr,
            )
        ).status_code == 200
        assert (
            await client.patch(
                f"/api/v1/hr/applications/{app_id}/stage",
                json={"stage": "evaluation"},
                headers=hr,
            )
        ).status_code == 200

        # Salary without payroll permission fails closed with 403.
        assert (
            await client.post(
                "/api/v1/hr/offers",
                json={
                    "offer_code": f"OFR-SAL-{uuid4().hex[:5]}",
                    "application_id": app_id,
                    "proposed_title": "Quantity Surveyor",
                    "proposed_salary": "150000",
                },
                headers=hr,
            )
        ).status_code == 403

        # Past valid_until rejected on creation.
        assert (
            await client.post(
                "/api/v1/hr/offers",
                json={
                    "offer_code": f"OFR-PAST-{uuid4().hex[:5]}",
                    "application_id": app_id,
                    "proposed_title": "Quantity Surveyor",
                    "valid_until": (base_today - timedelta(days=1)).isoformat(),
                },
                headers=hr,
            )
        ).status_code == 422

        v1_deadline = base_today + timedelta(days=3)
        upload = await client.post(
            "/api/v1/hr/documents",
            data={
                "title": "Synthetic offer file",
                "document_type": "candidate_offer",
                "category": "confidential",
                "candidate_id": cand.json()["id"],
            },
            files={
                "file": ("offer-v1.pdf", b"%PDF-1.4\nOffer version one\n%%EOF", "application/pdf")
            },
            headers=hr,
        )
        assert upload.status_code == 201, upload.text
        file = upload.json()
        v1_file_id = file["versions"][0]["id"]
        v1_payload = {
            "offer_code": f"OFR-V1-{uuid4().hex[:5]}",
            "application_id": app_id,
            "proposed_title": "Junior QS",
            "valid_until": v1_deadline.isoformat(),
            "notes": "Initial terms",
            "document_version_id": v1_file_id,
        }
        assert (
            await client.post("/api/v1/hr/offers", json=v1_payload, headers=hr)
        ).status_code == 404
        assert (
            await client.post(
                f"/api/v1/hr/documents/{file['id']}/versions/1/decision",
                json={"decision": "approve"},
                headers=reviewer,
            )
        ).status_code == 200
        v1 = await client.post(
            "/api/v1/hr/offers",
            json=v1_payload,
            headers=hr,
        )
        assert v1.status_code == 201
        v1_id = v1.json()["id"]
        assert v1.json()["document_version_id"] == v1_file_id
        assert (
            await client.get(f"/api/v1/hr/offers/{v1_id}/document", headers=sup)
        ).status_code == 403
        replacement = await client.post(
            f"/api/v1/hr/documents/{file['id']}/versions",
            files={
                "file": ("offer-v2.pdf", b"%PDF-1.4\nOffer version two\n%%EOF", "application/pdf")
            },
            headers=hr,
        )
        assert replacement.status_code == 201
        assert (
            await client.post(
                f"/api/v1/hr/documents/{file['id']}/versions/2/decision",
                json={"decision": "approve"},
                headers=reviewer,
            )
        ).status_code == 200
        old_link = await client.get(f"/api/v1/hr/offers/{v1_id}/document", headers=hr)
        assert old_link.status_code == 200 and old_link.headers["cache-control"] == "no-store"
        assert old_link.json()["version_number"] == 1
        assert (
            await client.post(
                f"/api/v1/hr/offers/{v1_id}/decision",
                json={"status": "pending_approval", "expected_updated_at": "2001-01-01T00:00:00Z"},
                headers=hr,
            )
        ).status_code == 409
        current = v1.json()
        for step in ("pending_approval", "approved", "issued"):
            decision = await client.post(
                f"/api/v1/hr/offers/{v1_id}/decision",
                json={"status": step, "expected_updated_at": current["updated_at"]},
                headers=hr,
            )
            assert decision.status_code == 200
            current = decision.json()

        # Offer cannot be marked expired on or before valid_until.
        monkeypatch.setattr("app.services.hr_workforce_service.business_today", lambda: v1_deadline)
        assert (
            await client.post(
                f"/api/v1/hr/offers/{v1_id}/decision",
                json={"status": "expired"},
                headers=hr,
            )
        ).status_code == 409

        # Once past valid_until, concurrent expiry vs acceptance yields one expiry and
        # rejects the accept attempt.
        monkeypatch.setattr(
            "app.services.hr_workforce_service.business_today",
            lambda: v1_deadline + timedelta(days=1),
        )
        accept_attempt = client.post(
            f"/api/v1/hr/offers/{v1_id}/decision",
            json={"status": "accepted"},
            headers=hr,
        )
        expire_attempt = client.post(
            f"/api/v1/hr/offers/{v1_id}/decision",
            json={"status": "expired"},
            headers=hr,
        )
        concurrent = await asyncio.gather(accept_attempt, expire_attempt)
        assert sorted(res.status_code for res in concurrent) == [200, 409]
        assert (
            await client.post(
                f"/api/v1/hr/offers/{v1_id}/convert",
                json={"employee_code": f"EXP-{uuid4().hex[:5]}"},
                headers=hr,
            )
        ).status_code == 409

        # Reissuing creates v2 while preserving v1's original terms as immutable.
        new_today = v1_deadline + timedelta(days=1)
        v2_deadline = new_today + timedelta(days=5)
        monkeypatch.setattr("app.services.hr_workforce_service.business_today", lambda: new_today)
        reissue_payload = {
            "offer_code": f"OFR-V2-{uuid4().hex[:5]}",
            "proposed_title": "Senior QS",
            "valid_until": v2_deadline.isoformat(),
            "notes": "Updated title and validity",
            "document_version_id": replacement.json()["versions"][0]["id"],
        }
        assert (
            await client.post(
                f"/api/v1/hr/offers/{v1_id}/reissue",
                json={**reissue_payload, "expected_updated_at": current["updated_at"]},
                headers=hr,
            )
        ).status_code == 409
        expired = next(response.json() for response in concurrent if response.status_code == 200)
        assert (
            await client.post(
                f"/api/v1/hr/offers/{v1_id}/reissue",
                json={**reissue_payload, "document_version_id": v1_file_id},
                headers=hr,
            )
        ).status_code == 422
        v2 = await client.post(
            f"/api/v1/hr/offers/{v1_id}/reissue",
            json={**reissue_payload, "expected_updated_at": expired["updated_at"]},
            headers=hr,
        )
        assert v2.status_code == 201
        v2_id = v2.json()["id"]
        assert v2.json()["version_number"] == 2
        assert v2.json()["supersedes_offer_id"] == v1_id
        assert v2.json()["proposed_title"] == "Senior QS"
        new_link = await client.get(f"/api/v1/hr/offers/{v2_id}/document", headers=hr)
        assert new_link.status_code == 200 and new_link.json()["version_number"] == 2
        for offset, expected_id in enumerate((v2_id, v1_id)):
            page = await client.get(
                "/api/v1/hr/offers",
                headers=hr,
                params={"application_id": app_id, "limit": 1, "offset": offset},
            )
            assert page.status_code == 200
            assert page.json()["total"] == 2 and page.json()["items"][0]["id"] == expected_id

        # Verify v1 stays superseded and preserves its initial terms.
        async with AsyncSessionLocal() as session:
            v1_row = await session.get(HrOffer, UUID(v1_id))
            assert v1_row is not None
            assert v1_row.status == "superseded"
            assert v1_row.superseded_by_id == UUID(v2_id)
            assert v1_row.superseded_at is not None
            assert v1_row.proposed_title == "Junior QS"
            assert v1_row.valid_until == v1_deadline

        # Superseded v1 cannot be transitioned, accepted, converted, or reissued again.
        assert (
            await client.post(
                f"/api/v1/hr/offers/{v1_id}/decision",
                json={"status": "accepted"},
                headers=hr,
            )
        ).status_code == 409
        assert (
            await client.post(
                f"/api/v1/hr/offers/{v1_id}/convert",
                json={"employee_code": f"STALE-{uuid4().hex[:5]}"},
                headers=hr,
            )
        ).status_code == 409
        assert (
            await client.post(
                f"/api/v1/hr/offers/{v1_id}/reissue",
                json={
                    "offer_code": f"OFR-V3-{uuid4().hex[:5]}",
                    "proposed_title": "Duplicate",
                },
                headers=hr,
            )
        ).status_code == 409

        # Stale expected_version_number on v2 returns 409.
        assert (
            await client.post(
                f"/api/v1/hr/offers/{v2_id}/decision",
                json={"status": "pending_approval", "expected_version_number": 1},
                headers=hr,
            )
        ).status_code == 409

        # Approve, issue, and accept v2 on the exact deadline day (`today == valid_until`),
        # then convert.
        for step in ("pending_approval", "approved", "issued"):
            assert (
                await client.post(
                    f"/api/v1/hr/offers/{v2_id}/decision",
                    json={"status": step, "expected_version_number": 2},
                    headers=hr,
                )
            ).status_code == 200

        monkeypatch.setattr("app.services.hr_workforce_service.business_today", lambda: v2_deadline)
        accepted_v2 = await client.post(
            f"/api/v1/hr/offers/{v2_id}/decision",
            json={"status": "accepted", "expected_version_number": 2},
            headers=hr,
        )
        assert accepted_v2.status_code == 200
        assert accepted_v2.json()["status"] == "accepted"

        converted_v2 = await client.post(
            f"/api/v1/hr/offers/{v2_id}/convert",
            json={"employee_code": f"VER-{uuid4().hex[:5]}"},
            headers=hr,
        )
        assert converted_v2.status_code == 200


@pytest.mark.asyncio
async def test_probation_review_extends_then_confirms_with_current_revision(monkeypatch) -> None:
    await skip_if_database_unavailable()
    hr_id, hr_email, hr_password = await _create_portal_user("hr_manager")
    staff_id, staff_email, staff_password = await _create_portal_user("site_supervisor")
    today = business_today()
    async with _client() as client:
        hr = _auth(await _login(client, hr_email, hr_password))
        staff = _auth(await _login(client, staff_email, staff_password))
        employee = await client.post(
            "/api/v1/hr/employees",
            json={
                "employee_code": f"PROB-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Probation",
                "employment_category": "probation",
            },
            headers=hr,
        )
        assert employee.status_code == 201
        employee_id = employee.json()["id"]
        onboarding = await client.post(
            "/api/v1/hr/onboarding",
            json={
                "employee_id": employee_id,
                "start_date": (today - timedelta(days=30)).isoformat(),
                "probation_end_date": today.isoformat(),
            },
            headers=hr,
        )
        assert onboarding.status_code == 201
        case = onboarding.json()
        outcome_url = f"/api/v1/hr/onboarding/{case['id']}/probation-review"
        request = {
            "outcome": "confirm",
            "reason": "Checklist and work reviewed.",
            "expected_employee_revision": case["employee_revision"],
        }
        assert (await client.post(outcome_url, json=request, headers=staff)).status_code == 403
        assert (await client.post(outcome_url, json=request, headers=hr)).status_code == 409

        case_path = f"/api/v1/hr/onboarding/{case['id']}"
        assert (await client.get(case_path, headers=staff)).status_code == 403
        current = await client.get(case_path, headers=hr)
        assert current.headers["cache-control"] == "no-store"
        assert current.json()["id"] == case["id"]
        first_task = case["tasks"][0]
        race = await asyncio.gather(
            *(
                client.patch(
                    f"/api/v1/hr/onboarding/tasks/{first_task['id']}",
                    json={
                        "status": "in_progress",
                        "evidence_notes": evidence,
                        "expected_updated_at": first_task["updated_at"],
                    },
                    headers=hr,
                )
                for evidence in ("Reviewed evidence A.", "Reviewed evidence B.")
            )
        )
        assert sorted(result.status_code for result in race) == [200, 409]
        listed = await client.get(
            "/api/v1/hr/onboarding",
            params={"employee_id": employee_id, "case_status": "in_progress", "limit": 1},
            headers=hr,
        )
        assert listed.json()["total"] == 1 and listed.json()["items"][0]["id"] == case["id"]
        for task in next(result.json() for result in race if result.status_code == 200)["tasks"]:
            complete = await client.patch(
                f"/api/v1/hr/onboarding/tasks/{task['id']}",
                json={
                    "status": "completed",
                    "evidence_notes": "Verified by HR.",
                    "expected_updated_at": task["updated_at"],
                },
                headers=hr,
            )
            assert complete.status_code == 200
        assert complete.json()["status"] == "completed"
        activated = await client.post(
            f"/api/v1/hr/employees/{employee_id}/status",
            json={
                "status": "on_probation",
                "expected_revision": complete.json()["employee_revision"],
                "reason": "Onboarding complete.",
            },
            headers=hr,
        )
        assert activated.status_code == 200
        request["expected_employee_revision"] = activated.json()["record_revision"]
        async with AsyncSessionLocal() as session:
            owned = await session.get(HrEmployee, UUID(employee_id))
            assert owned is not None
            owned.user_id = UUID(hr_id)
            await session.commit()
            assert (await client.post(outcome_url, json=request, headers=hr)).status_code == 403
            owned.user_id = None
            await session.commit()

        monkeypatch.delenv("HR_PROBATION_REVIEW_REMINDER_DAYS", raising=False)
        get_settings.cache_clear()
        assert await _check_hr_probation_reviews() == 0
        monkeypatch.setenv("HR_PROBATION_REVIEW_REMINDER_DAYS", "7")
        get_settings.cache_clear()
        assert await _check_hr_probation_reviews() > 0
        assert await _check_hr_probation_reviews() == 0
        async with AsyncSessionLocal() as session:
            notice = await session.scalar(
                select(Notification.id).where(
                    Notification.user_id == UUID(staff_id),
                    Notification.notification_type == "hr_probation_review",
                )
            )
            assert notice is None

        assert (await client.post(outcome_url, json=request, headers=hr)).status_code == 422
        new_date = (today + timedelta(days=15)).isoformat()
        extended = await client.post(
            outcome_url,
            json={**request, "outcome": "extend", "new_end_date": new_date},
            headers=hr,
        )
        assert extended.status_code == 200
        assert extended.json()["probation_end_date"] == new_date
        assert extended.json()["employee_status"] == "on_probation"
        confirm_request = {**request, "confirmed_category": "contract"}
        assert (await client.post(outcome_url, json=confirm_request, headers=hr)).status_code == 409
        confirm_request["expected_employee_revision"] = extended.json()["employee_revision"]
        responses = await asyncio.gather(
            *(client.post(outcome_url, json=confirm_request, headers=hr) for _ in range(2))
        )
        assert sorted(response.status_code for response in responses) == [200, 409]
        confirmed = next(response.json() for response in responses if response.status_code == 200)
        assert confirmed["employee_status"] == "active"
        assert confirmed["employee_category"] == "contract"
        history = await client.get(f"/api/v1/hr/employees/{employee_id}/history", headers=hr)
        assert history.status_code == 200
        assert [item["change_type"] for item in history.json()["items"]][:2] == [
            "probation:confirm",
            "probation:extend",
        ]


@pytest.mark.asyncio
async def test_hr_project_assignment_uses_project_permissions_and_atomic_decisions() -> None:
    await skip_if_database_unavailable()
    admin_id, admin_email, password = await _create_portal_user("managing_director")
    _, hr_email, _ = await _create_portal_user("hr_manager", password)
    worker_id, worker_email, _ = await _create_portal_user("group_project_manager", password)
    async with AsyncSessionLocal() as session:
        projects = [
            Project(
                name=name,
                code=f"HRP-{uuid4().hex[:8]}",
                status="active",
                target_end_date=business_today() + timedelta(days=30),
                scope_of_work="Synthetic assignment verification.",
                created_by=UUID(admin_id),
            )
            for name in ("Synthetic assignment site", "Other assignment site")
        ]
        session.add_all(projects)
        await session.flush()
        project_id, other_project = [str(project.id) for project in projects]
        await session.commit()

    async with _client() as client:
        admin = _auth(await _login(client, admin_email, password))
        hr = _auth(await _login(client, hr_email, password))
        worker = _auth(await _login(client, worker_email, password))
        projects_url = f"/api/v1/projects/{project_id}"
        queue = f"{projects_url}/hr-assignment-requests"
        assert (await client.get(projects_url, headers=worker)).status_code == 404
        picker = await client.get(
            "/api/v1/hr/project-assignment-options",
            params={"search": "Synthetic assignment site"},
            headers=hr,
        )
        option = next(item for item in picker.json()["items"] if item["id"] == project_id)
        assert set(option) == {"id", "code", "name"}
        employee = await client.post(
            "/api/v1/hr/employees",
            json={
                "employee_code": f"LINK-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Assignment",
                "work_email": worker_email,
                "work_location": "West site",
                "primary_project_id": project_id,
                "employment_status": "active",
            },
            headers=hr,
        )
        assert employee.status_code == 201
        employee_id = employee.json()["id"]
        assert (
            await client.post(
                f"/api/v1/hr/employees/{employee_id}/link-account",
                json={"user_id": worker_id},
                headers=admin,
            )
        ).status_code == 200
        org = await client.get("/api/v1/hr/org-chart", headers=hr)
        node = next(node for node in org.json()["roots"] if node["employee_id"] == employee_id)
        assert node["work_location"] == "West site"
        assert node["primary_assignment"] == "inactive"
        assert "primary_project_id" not in node

        endpoint = f"/api/v1/hr/employees/{employee_id}/project-assignment-requests"
        payload = {"project_id": project_id, "action": "assign", "reason": "Review staffing."}
        pending = await client.post(endpoint, json=payload, headers=hr)
        assert pending.status_code == 201
        request_id = pending.json()["id"]
        assert (await client.post(endpoint, json=payload, headers=hr)).status_code == 409
        assert (await client.get(projects_url, headers=worker)).status_code == 404
        assert (await client.get(queue, headers=hr)).status_code == 403
        assert (await client.get(queue, headers=worker)).status_code == 404
        revision = (await client.get(projects_url, headers=admin)).json()["revision"]
        approve = {"decision": "approve", "expected_project_revision": revision}
        decision_endpoint = f"{queue}/{request_id}/decision"
        assert (await client.post(decision_endpoint, json=approve, headers=hr)).status_code == 403
        assert (
            await client.post(
                f"/api/v1/projects/{other_project}/hr-assignment-requests/{request_id}/decision",
                json=approve,
                headers=admin,
            )
        ).status_code == 404
        stale = await client.post(
            decision_endpoint,
            json={**approve, "expected_project_revision": revision + 1},
            headers=admin,
        )
        assert stale.status_code == 409
        assert (await client.get(queue, headers=admin)).json()["items"][0]["status"] == "pending"
        decisions = await asyncio.gather(
            *(client.post(decision_endpoint, json=approve, headers=admin) for _ in range(2))
        )
        assert sorted(response.status_code for response in decisions) == [200, 409]
        assert (await client.get(projects_url, headers=worker)).status_code == 200
        org = await client.get("/api/v1/hr/org-chart", headers=hr)
        node = next(node for node in org.json()["roots"] if node["employee_id"] == employee_id)
        assert node["primary_assignment"] == "active"

        removal = await client.post(endpoint, json={**payload, "action": "revoke"}, headers=hr)
        assert removal.status_code == 201
        remove_endpoint = f"{queue}/{removal.json()['id']}/decision"
        assert (
            await client.post(
                remove_endpoint,
                json={"decision": "reject", "expected_project_revision": revision + 1},
                headers=admin,
            )
        ).status_code == 422
        assert (
            await client.post(
                remove_endpoint,
                json={
                    "decision": "reject",
                    "expected_project_revision": revision + 1,
                    "note": "Staffing still needed.",
                },
                headers=admin,
            )
        ).json()["status"] == "rejected"
        assert (await client.get(projects_url, headers=worker)).status_code == 200
        removal = await client.post(endpoint, json={**payload, "action": "revoke"}, headers=hr)
        assert removal.status_code == 201
        remove_endpoint = f"{queue}/{removal.json()['id']}/decision"
        assert (
            await client.post(
                remove_endpoint,
                json={"decision": "approve", "expected_project_revision": revision + 1},
                headers=admin,
            )
        ).status_code == 200
        assert (await client.get(projects_url, headers=worker)).status_code == 404


@pytest.mark.asyncio
async def test_hr_f_document_vault_rbac_and_compliance() -> None:
    await skip_if_database_unavailable()
    _, hrm_email, pw = await _create_portal_user("hr_manager")
    _, hre_email, _ = await _create_portal_user("quantity_surveyor", pw)
    _, reviewer_email, _ = await _create_portal_user("hr_manager", pw)

    async with _client() as client:
        hrm_tok = await _login(client, hrm_email, pw)
        hre_tok = await _login(client, hre_email, pw)
        reviewer_tok = await _login(client, reviewer_email, pw)

        # Executable file rejected
        bad = await client.post(
            "/api/v1/hr/documents",
            data={"title": "Bad", "document_type": "other", "category": "ordinary"},
            files={"file": ("malware.exe", b"MZ\x90\x00bad", "application/octet-stream")},
            headers=_auth(hrm_tok),
        )
        assert bad.status_code == 422

        soon = (date.today() + timedelta(days=10)).isoformat()
        ord_doc = await client.post(
            "/api/v1/hr/documents",
            data={
                "title": "Safety Orientation",
                "document_type": "safety_cert",
                "category": "ordinary",
                "expiry_date": soon,
            },
            files={"file": ("safety.pdf", _pdf_bytes("ord"), "application/pdf")},
            headers=_auth(hrm_tok),
        )
        assert ord_doc.status_code == 201

        conf_doc = await client.post(
            "/api/v1/hr/documents",
            data={
                "title": "Employment Contract",
                "document_type": "contract",
                "category": "confidential",
            },
            files={"file": ("disc.pdf", _pdf_bytes("disc"), "application/pdf")},
            headers=_auth(hrm_tok),
        )
        assert conf_doc.status_code == 201
        conf_id = conf_doc.json()["id"]

        ordinary_id = ord_doc.json()["id"]
        assert ord_doc.json()["status"] == "pending"
        assert "object_key" not in ord_doc.json()["versions"][0]
        assert (
            await client.get(f"/api/v1/hr/documents/{ordinary_id}/download", headers=_auth(hre_tok))
        ).status_code == 403
        for document_id in (ordinary_id, conf_id):
            endpoint = f"/api/v1/hr/documents/{document_id}/versions/1/decision"
            assert (
                await client.post(endpoint, json={"decision": "approve"}, headers=_auth(hrm_tok))
            ).status_code == 403
            assert (
                await client.post(
                    endpoint, json={"decision": "approve"}, headers=_auth(reviewer_tok)
                )
            ).status_code == 200
        assert (
            await client.get(
                f"/api/v1/hr/documents/{ordinary_id}/download", headers=_auth(reviewer_tok)
            )
        ).status_code == 200
        assert (
            await client.get(f"/api/v1/hr/documents/{conf_id}/download", headers=_auth(hre_tok))
        ).status_code == 403
        original = await client.get(
            f"/api/v1/hr/documents/{conf_id}/download", headers=_auth(hrm_tok)
        )
        assert original.status_code == 200
        assert original.headers["Cache-Control"] == "no-store"
        public_link = original.json()["download_url"]
        async with httpx.AsyncClient() as storage:
            downloaded = await storage.get(public_link)
            assert downloaded.status_code == 200
            assert downloaded.content == _pdf_bytes("disc")
        revision = await client.post(
            f"/api/v1/hr/documents/{conf_id}/versions",
            files={"file": ("revision.pdf", _pdf_bytes("revision"), "application/pdf")},
            headers=_auth(hrm_tok),
        )
        assert revision.status_code == 201
        assert revision.json()["current_version"] == 1
        assert (
            await client.get(f"/api/v1/hr/documents/{conf_id}/download", headers=_auth(hrm_tok))
        ).json()["version_number"] == 1
        assert (
            await client.post(
                f"/api/v1/hr/documents/{conf_id}/versions/2/decision",
                json={"decision": "approve"},
                headers=_auth(reviewer_tok),
            )
        ).json()["current_version"] == 2

        async with engine.connect() as connection:
            stored_keys = set(
                await connection.scalars(
                    select(HrDocumentVersion.object_key).where(
                        HrDocumentVersion.document_id == UUID(conf_id)
                    )
                )
            )
            assert len(stored_keys) == 2
            assert stored_keys <= await references(connection, datetime.now(UTC))

        comp = await client.get(
            "/api/v1/hr/compliance/expiring?within_days=30", headers=_auth(hrm_tok)
        )
        assert comp.status_code == 200
        assert any(item["record_id"] == ord_doc.json()["id"] for item in comp.json()["items"])

        candidate = await client.post(
            "/api/v1/hr/candidates",
            json={"candidate_code": f"CV-{uuid4().hex[:8]}", "full_name": "Synthetic Candidate"},
            headers=_auth(hrm_tok),
        )
        assert candidate.status_code == 201
        candidate_id = candidate.json()["id"]
        cv_metadata = {
            "title": "Synthetic CV",
            "document_type": "candidate_cv",
            "candidate_id": candidate_id,
        }
        cv_file = {"file": ("candidate.pdf", _pdf_bytes("cv"), "application/pdf")}
        assert (
            await client.post(
                "/api/v1/hr/documents",
                data={**cv_metadata, "category": "ordinary"},
                files=cv_file,
                headers=_auth(hrm_tok),
            )
        ).status_code == 422
        cv_metadata["category"] = "confidential"
        uploads = await asyncio.gather(
            *(
                client.post(
                    "/api/v1/hr/documents",
                    data=cv_metadata,
                    files=cv_file,
                    headers=_auth(hrm_tok),
                )
                for _ in range(2)
            )
        )
        assert sorted(response.status_code for response in uploads) == [201, 409]
        cv = next(response for response in uploads if response.status_code == 201)
        cv_id = cv.json()["id"]
        assert cv.json()["candidate_id"] == candidate_id
        detail_path = f"/api/v1/hr/documents/{cv_id}"
        detail = await client.get(detail_path, headers=_auth(reviewer_tok))
        assert detail.status_code == 200 and detail.headers["cache-control"] == "no-store"
        assert detail.json()["versions"][0]["status"] == "pending"
        assert (await client.get(detail_path, headers=_auth(hre_tok))).status_code == 403
        candidates = await client.get(
            "/api/v1/hr/candidates",
            params={"search": candidate.json()["candidate_code"]},
            headers=_auth(hrm_tok),
        )
        assert candidates.json()["items"][0]["resume_document_id"] == cv_id
        listed = await client.get(
            "/api/v1/hr/documents",
            params={"candidate_id": candidate_id, "document_type": "candidate_cv"},
            headers=_auth(hrm_tok),
        )
        assert [item["id"] for item in listed.json()["items"]] == [cv_id]
        assert (
            await client.get(
                "/api/v1/hr/documents",
                params={"candidate_id": str(uuid4())},
                headers=_auth(hrm_tok),
            )
        ).json()["items"] == []
        assert (
            await client.get(
                "/api/v1/hr/documents",
                params={"candidate_id": candidate_id},
                headers=_auth(hre_tok),
            )
        ).status_code == 403
        cv_download = f"/api/v1/hr/documents/{cv_id}/download"
        assert (
            await client.get(cv_download, params={"version_number": 1}, headers=_auth(hrm_tok))
        ).status_code == 404
        review_link = await client.get(
            cv_download, params={"version_number": 1}, headers=_auth(reviewer_tok)
        )
        assert review_link.status_code == 200
        async with httpx.AsyncClient() as storage:
            assert (await storage.get(review_link.json()["download_url"])).content == _pdf_bytes(
                "cv"
            )
        assert (
            await client.post(
                f"/api/v1/hr/documents/{cv_id}/versions/1/decision",
                json={"decision": "approve"},
                headers=_auth(reviewer_tok),
            )
        ).status_code == 200
        assert (await client.get(cv_download, headers=_auth(hrm_tok))).status_code == 200
        assert (await client.get(cv_download, headers=_auth(hre_tok))).status_code == 403
        assert (
            await client.post(
                f"{detail_path}/versions",
                data={"expected_latest_version": "0"},
                files=cv_file,
                headers=_auth(hrm_tok),
            )
        ).status_code == 409
        revisions = await asyncio.gather(
            *(
                client.post(
                    f"{detail_path}/versions",
                    data={"expected_latest_version": "1"},
                    files=cv_file,
                    headers=_auth(hrm_tok),
                )
                for _ in range(2)
            )
        )
        assert sorted(response.status_code for response in revisions) == [201, 409]
        latest = await client.get(detail_path, headers=_auth(hrm_tok))
        assert [version["version_number"] for version in latest.json()["versions"]] == [2, 1]


@pytest.mark.asyncio
async def test_hr_g_calendars_attendance_timesheets_and_overtime() -> None:
    await skip_if_database_unavailable()
    _, hrm_email, pw = await _create_portal_user("hr_manager")
    _, recorder_email, _ = await _create_portal_user("hr_manager", pw)

    async with _client() as client:
        tok = await _login(client, hrm_email, pw)
        recorder = await _login(client, recorder_email, pw)

        emp = await client.post(
            "/api/v1/hr/employees",
            json={
                "employee_code": f"ATT-{uuid4().hex[:6]}",
                "first_name": "Site",
                "last_name": "Crew",
            },
            headers=_auth(tok),
        )
        emp_id = emp.json()["id"]

        cal = await client.post(
            "/api/v1/hr/calendars",
            json={
                "code": f"CAL-{uuid4().hex[:5]}",
                "name": "Synthetic calendar",
                "work_days_json": ["MON", "TUE", "WED", "THU", "FRI"],
                "standard_start_time": "08:00",
                "standard_end_time": "17:00",
                "daily_hours": "8.00",
                "effective_from": "2026-06-01",
                "effective_to": "2026-06-30",
                "timezone": "Asia/Colombo",
            },
            headers=_auth(tok),
        )
        assert cal.status_code == 201
        holiday = {
            "calendar_id": str(uuid4()),
            "holiday_date": "2026-06-03",
            "name": "Synthetic holiday",
        }
        assert (
            await client.post("/api/v1/hr/holidays", json=holiday, headers=_auth(tok))
        ).status_code == 404
        holiday["calendar_id"] = cal.json()["id"]
        _, staff_email, _ = await _create_portal_user("quantity_surveyor", pw)
        staff = await _login(client, staff_email, pw)
        assert (
            await client.post("/api/v1/hr/holidays", json=holiday, headers=_auth(staff))
        ).status_code == 403
        assert (
            await client.post("/api/v1/hr/holidays", json=holiday, headers=_auth(tok))
        ).status_code == 201
        assert (
            await client.post("/api/v1/hr/holidays", json=holiday, headers=_auth(tok))
        ).status_code == 409

        att = await client.post(
            "/api/v1/hr/attendance",
            json={
                "employee_id": emp_id,
                "work_date": "2026-06-02",
                "attendance_status": "present",
                "worked_hours": "8.00",
            },
            headers=_auth(tok),
        )
        assert att.status_code == 201

        corr = await client.post(
            "/api/v1/hr/attendance/corrections",
            json={
                "employee_id": emp_id,
                "work_date": "2026-06-02",
                "attendance_entry_id": att.json()["id"],
                "requested_status": "site_duty",
                "requested_worked_hours": "10.00",
                "reason": "Extended concrete pour",
            },
            headers=_auth(recorder),
        )
        assert corr.status_code == 201
        assert (
            await client.post(
                f"/api/v1/hr/attendance/corrections/{corr.json()['id']}/decision",
                json={"decision": "approved"},
                headers=_auth(tok),
            )
        ).status_code == 200

        ts = await client.post(
            "/api/v1/hr/timesheets",
            json={
                "employee_id": emp_id,
                "period_start": "2026-06-01",
                "period_end": "2026-06-07",
                "regular_hours": "40.00",
                "overtime_hours": "2.00",
                "submit": True,
            },
            headers=_auth(recorder),
        )
        assert ts.status_code == 201
        ot = await client.post(
            "/api/v1/hr/overtime",
            json={
                "employee_id": emp_id,
                "work_date": "2026-06-04",
                "requested_hours": "2.00",
                "reason": "Synthetic extra shift",
            },
            headers=_auth(recorder),
        )
        assert ot.status_code == 201
        for route, row in (
            ("attendance", att), ("attendance/corrections", corr),
            ("timesheets", ts), ("overtime", ot),
        ):
            detail_path = f"/api/v1/hr/{route}/{row.json()['id']}"
            detail = await client.get(detail_path, headers=_auth(tok))
            assert detail.status_code == 200
            assert detail.headers["cache-control"] == "no-store"
            assert detail.json()["id"] == row.json()["id"]
            assert detail.json()["employee_id"] == emp_id
            assert (await client.get(detail_path, headers=_auth(staff))).status_code == 403
            missing = await client.get(f"/api/v1/hr/{route}/{uuid4()}", headers=_auth(tok))
            assert missing.status_code == 404
        assert (
            await client.post(
                f"/api/v1/hr/timesheets/{ts.json()['id']}/decision",
                json={"decision": "approved"},
                headers=_auth(tok),
            )
        ).status_code == 200


@pytest.mark.asyncio
async def test_work_calendar_requires_independent_review_and_preserves_published_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    monkeypatch.setattr(
        "app.services.hr_site_attendance_service.business_today", lambda: date(2027, 1, 5)
    )
    _, preparer_email, pw = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", pw)
    _, executive_email, _ = await _create_portal_user("hr_manager", pw)
    _, staff_email, _ = await _create_portal_user("quantity_surveyor", pw)
    supervisor_id, supervisor_email, _ = await _create_portal_user("site_supervisor", pw)
    engineer_id, _, _ = await _create_portal_user("mep_project_manager", pw)
    async with AsyncSessionLocal() as session:
        project = Project(
            name="Calendar test site",
            code=f"HR-{uuid4().hex[:10]}",
            scope_of_work="Test scheduling",
            status="active",
            target_end_date=date(2027, 12, 31),
        )
        session.add(project)
        await session.flush()
        project_id = str(project.id)
        session.add_all([
            ProjectMember(project_id=project.id, user_id=UUID(supervisor_id)),
            ProjectMember(project_id=project.id, user_id=UUID(engineer_id)),
        ])
        await session.commit()

    async with _client() as client:
        preparer = _auth(await _login(client, preparer_email, pw))
        reviewer = _auth(await _login(client, reviewer_email, pw))
        executive = _auth(await _login(client, executive_email, pw))
        staff = _auth(await _login(client, staff_email, pw))
        supervisor = _auth(await _login(client, supervisor_email, pw))
        employee = await client.post(
            "/api/v1/hr/employees",
            headers=preparer,
            json={
                "employee_code": f"CAL-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Worker",
                "employment_status": "active",
                "primary_project_id": project_id,
            },
        )
        assert employee.status_code == 201, employee.text
        employee_id = employee.json()["id"]
        calendars = "/api/v1/hr/calendars"
        calendar_data = {
            "code": f"CAL-{uuid4().hex[:8]}",
            "name": "Test calendar",
            "project_id": project_id,
            "work_days_json": ["MON", "TUE"],
            "standard_start_time": "07:30",
            "standard_end_time": "16:00",
            "daily_hours": "7.5",
            "effective_from": "2027-01-01",
            "effective_to": "2027-01-31",
            "timezone": "Asia/Colombo",
        }
        invalid = await client.post(
            calendars, json={**calendar_data, "timezone": "unconfigured"}, headers=preparer
        )
        assert invalid.status_code == 422
        assert (
            await client.post(
                calendars,
                json={**calendar_data, "standard_start_time": "07:30:00+05:30"},
                headers=preparer,
            )
        ).status_code == 422
        created = await client.post(calendars, json=calendar_data, headers=preparer)
        assert created.status_code == 201, created.text
        calendar = created.json()
        url = f"{calendars}/{calendar['id']}"

        async def decide(path, revision, action, headers):
            return await client.post(
                f"{path}/decision",
                headers=headers,
                json={
                    "expected_revision": revision,
                    "action": action,
                },
            )

        async def schedule(day, headers):
            return await client.get(
                "/api/v1/hr/schedule",
                headers=headers,
                params={
                    "employee_id": employee_id,
                    "work_date": day,
                },
            )

        assert (await schedule("2027-01-04", executive)).json()["is_workday"] is None
        assert (await schedule("2027-01-04", staff)).status_code == 403
        holiday = {
            "calendar_id": calendar["id"],
            "holiday_date": "2027-01-04",
            "name": "Test holiday",
        }
        assert (
            await client.post("/api/v1/hr/holidays", json=holiday, headers=executive)
        ).status_code == 201
        assert (await decide(url, 1, "submit", preparer)).status_code == 409
        assert (await decide(url, 2, "submit", preparer)).status_code == 200
        assert (await decide(url, 3, "approve", preparer)).status_code == 403
        assert (await decide(url, 3, "approve", staff)).status_code == 403
        assert (await decide(url, 3, "approve", reviewer)).status_code == 200
        assert (await decide(url, 4, "publish", reviewer)).status_code == 200
        assert (await decide(url, 5, "publish", reviewer)).status_code == 409
        assert (
            await client.patch(
                url, json={**calendar_data, "expected_revision": 5}, headers=preparer
            )
        ).status_code == 409
        assert (
            await client.post(
                "/api/v1/hr/holidays",
                json={**holiday, "holiday_date": "2027-01-05"},
                headers=preparer,
            )
        ).status_code == 409

        workday = (await schedule("2027-01-05", executive)).json()
        assert workday["calendar"]["id"] == calendar["id"]
        assert workday["is_workday"] is True
        day_off = (await schedule("2027-01-04", executive)).json()
        assert day_off["is_workday"] is False and day_off["holiday"]["name"] == "Test holiday"
        assert (await schedule("2027-02-01", executive)).json()["is_workday"] is None

        leave_type = await client.post(
            "/api/v1/hr/leave/types",
            headers=preparer,
            json={"code": f"L-{uuid4().hex[:8]}", "name": "Synthetic shift leave"},
        )
        assert leave_type.status_code == 201
        assert leave_type.json()["is_active"] is False
        legacy_leave_type_id = await _create_legacy_leave_type("Synthetic calendar leave")
        quote_path = f"/api/v1/hr/leave/employees/{employee_id}/units"
        quote_dates = {
            "leave_type_id": legacy_leave_type_id,
            "start_date": "2027-01-04",
            "end_date": "2027-01-05",
        }
        assert (await client.get(quote_path, params=quote_dates, headers=staff)).status_code == 403
        before_shift = await client.get(quote_path, params=quote_dates, headers=reviewer)
        assert before_shift.status_code == 200 and before_shift.json()["days_requested"] == "1"
        override = await _publish_leave_calendar(
            client, preparer, reviewer, "2027-01-04", "2027-01-04"
        )
        override_shift = await client.post(
            "/api/v1/hr/shifts",
            headers=reviewer,
            json={
                "employee_id": employee_id,
                "calendar_id": override["id"],
                "shift_name": "Holiday override in assigned calendar",
                "effective_from": "2027-01-04",
                "effective_to": "2027-01-04",
                "start_time": "06:30",
                "end_time": "14:30",
            },
        )
        assert override_shift.status_code == 201, override_shift.text
        with_shift = await client.get(quote_path, params=quote_dates, headers=reviewer)
        assert with_shift.status_code == 200 and with_shift.json()["days_requested"] == "2"

        shift = {
            "employee_id": employee_id,
            "calendar_id": calendar["id"],
            "shift_name": "Test shift",
            "effective_from": "2027-01-05",
            "effective_to": "2027-01-20",
            "start_time": "06:30",
            "end_time": "14:30",
        }
        shifts = "/api/v1/hr/shifts"
        assert (
            await client.post(
                shifts, json={**shift, "effective_to": "2027-02-05"}, headers=reviewer
            )
        ).status_code == 422
        assert (await client.post(shifts, json=shift, headers=reviewer)).status_code == 201
        assert (await client.post(shifts, json=shift, headers=reviewer)).status_code == 409
        assert (await schedule("2027-01-05", executive)).json()["shift"][
            "shift_name"
        ] == "Test shift"
        open_ended_calendar = await client.post(
            calendars,
            headers=preparer,
            json={
                **calendar_data,
                "code": f"CAL-{uuid4().hex[:8]}",
                "name": "Open-ended shift calendar",
                "work_days_json": ["SAT"],
                "effective_from": "2027-03-01",
                "effective_to": "2027-03-31",
            },
        )
        assert open_ended_calendar.status_code == 201, open_ended_calendar.text
        open_calendar = open_ended_calendar.json()
        for action, actor in (("submit", preparer), ("approve", reviewer), ("publish", reviewer)):
            response = await client.post(
                f"{calendars}/{open_calendar['id']}/decision",
                headers=actor,
                json={"action": action, "expected_revision": open_calendar["revision"]},
            )
            assert response.status_code == 200, response.text
            open_calendar = response.json()
        open_shift = await client.post(
            shifts,
            headers=reviewer,
            json={
                "employee_id": employee_id,
                "calendar_id": open_calendar["id"],
                "shift_name": "Open-ended Saturday shift",
                "effective_from": "2027-03-01",
                "effective_to": None,
                "start_time": "07:00",
                "end_time": "15:00",
            },
        )
        assert open_shift.status_code == 201, open_shift.text
        open_shift_quote = await client.get(
            quote_path,
            params={
                "leave_type_id": legacy_leave_type_id,
                "start_date": "2027-03-06",
                "end_date": "2027-03-06",
            },
            headers=reviewer,
        )
        assert open_shift_quote.status_code == 200, open_shift_quote.text
        assert open_shift_quote.json()["days_requested"] == "1"

        attendance_path = "/api/v1/hr/attendance"
        site_path = "/api/v1/hr/site-attendance"
        attendance = {
            "employee_id": employee_id,
            "work_date": "2027-01-05",
            "attendance_status": "present",
            "check_in_at": "2027-01-04T20:00:00Z",
            "check_out_at": "2027-01-05T04:00:00Z",
            "worked_hours": "8.00",
        }
        wrong_local_date = await client.post(
            site_path,
            json={**attendance, "project_id": project_id, "check_in_at": "2027-01-04T17:00:00Z"},
            headers=supervisor,
        )
        assert wrong_local_date.status_code == 422
        direct = await client.post(attendance_path, json=attendance, headers=executive)
        assert direct.status_code == 409
        assert direct.json()["error_code"] == "SITE_ATTENDANCE_WORKFLOW_REQUIRED"
        recorded = await client.post(
            site_path, json={**attendance, "project_id": project_id}, headers=supervisor
        )
        assert recorded.status_code == 201, recorded.text
        assert recorded.json()["stage"] == "pending_engineer"
        recorded_id = UUID(recorded.json()["id"])
        async with AsyncSessionLocal() as session:
            entry = await session.get(HrAttendanceEntry, recorded_id)
            assert entry is not None
            assert str(entry.calendar_id) == calendar["id"]
            assert entry.scheduled_workday is True
            assert entry.shift_assignment_id is not None

        # The two later revisions are individually valid but overlap one another.
        new_calendar_urls = []
        for offset in (1, 2):
            draft = await client.post(
                calendars,
                headers=executive,
                json={
                    **calendar_data,
                    "code": f"CAL-{uuid4().hex[:8]}",
                    "effective_from": f"2027-02-0{offset}",
                    "effective_to": "2027-02-28",
                },
            )
            assert draft.status_code == 201, draft.text
            new_url = f"{calendars}/{draft.json()['id']}"
            assert (await decide(new_url, 1, "submit", executive)).status_code == 200
            assert (await decide(new_url, 2, "approve", reviewer)).status_code == 200
            new_calendar_urls.append(new_url)
        attempts = await asyncio.gather(
            *(decide(new_url, 3, "publish", reviewer) for new_url in new_calendar_urls)
        )
        assert sorted(response.status_code for response in attempts) == [200, 409]
        assert (await schedule("2027-01-05", executive)).json()["calendar"]["id"] == calendar["id"]
        history = await client.get(
            attendance_path, params={"employee_id": employee_id}, headers=reviewer
        )
        assert history.json()["items"][0]["calendar_id"] == calendar["id"]


@pytest.mark.asyncio
async def test_manager_recommendations_are_scoped_advisory_and_revision_checked(
    monkeypatch,
) -> None:
    await skip_if_database_unavailable()
    monkeypatch.delenv("HR_LINE_MANAGER_REVIEW_ENABLED", raising=False)
    monkeypatch.delenv("HR_SELF_TIME_SUBMISSION_ENABLED", raising=False)
    get_settings.cache_clear()
    hr_id, hr_email, pw = await _create_portal_user("hr_manager")
    exec_id, exec_email, _ = await _create_portal_user("hr_manager", pw)
    supervisor_id, supervisor_email, _ = await _create_portal_user("group_project_manager", pw)
    employee_id, employee_email, _ = await _create_portal_user("quantity_surveyor", pw)
    async with AsyncSessionLocal() as session:

        async def linked(user_id, email, name, manager_id=None):
            employee = HrEmployee(
                user_id=UUID(user_id),
                work_email=email,
                employee_code=f"SYN-MR-{uuid4().hex[:8]}",
                first_name="Synthetic",
                last_name=name,
                full_name=f"Synthetic {name}",
                employment_status="active",
                manager_employee_id=manager_id,
            )
            session.add(employee)
            await session.flush()
            return employee.id

        manager_record_id = await linked(supervisor_id, supervisor_email, "Reviewer")
        hr_employee_id = await linked(hr_id, hr_email, "HR")
        employee_record_id = await linked(employee_id, employee_email, "Worker", manager_record_id)
        await linked(exec_id, exec_email, "Executive")
        await session.commit()

    async with _client() as client:
        hr = _auth(await _login(client, hr_email, pw))
        executive = _auth(await _login(client, exec_email, pw))
        manager = _auth(await _login(client, supervisor_email, pw))
        worker = _auth(await _login(client, employee_email, pw))
        base = "/api/v1/hr"
        queue = f"{base}/me/manager-reviews"
        sheet_path = f"{base}/me/timesheets"
        profile = f"{base}/employees/{employee_record_id}"
        assert (await client.get(queue, headers=manager)).status_code == 404
        assert (await client.get(sheet_path, headers=worker)).status_code == 404
        assert (await client.get(f"{base}/me/workflow-options", headers=worker)).json() == {
            "can_recommend": False,
            "self_time_submission_enabled": False,
            "can_decide_leave": False,
            "hr_leave_approver_configured": True,
        }
        monkeypatch.setenv("HR_LINE_MANAGER_REVIEW_ENABLED", "true")
        monkeypatch.setenv("HR_SELF_TIME_SUBMISSION_ENABLED", "true")
        get_settings.cache_clear()

        grant = {"enabled": True, "expected_revision": 1}
        assert (
            await client.put(f"{profile}/manager-review", json=grant, headers=manager)
        ).status_code == 403
        assigned = await client.put(f"{profile}/manager-review", json=grant, headers=hr)
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["line_manager_reviewer_id"] == str(manager_record_id)
        assert (await client.get(f"{base}/me/workflow-options", headers=manager)).json()[
            "can_recommend"
        ]
        assert (await client.get(f"{base}/employees", headers=manager)).status_code == 403

        leave_type = await client.post(
            f"{base}/leave/types",
            headers=hr,
            json={"code": f"L-{uuid4().hex[:8]}", "name": "Synthetic paid leave", "is_paid": True},
        )
        assert leave_type.status_code == 201, leave_type.text
        assert leave_type.json()["is_active"] is False
        leave_type_id = await _create_legacy_leave_type("Synthetic configured paid leave")
        await _publish_leave_calendar(client, hr, executive, "2027-01-05", "2027-01-06")
        assert (
            await client.post(
                f"{base}/leave/ledger",
                headers=hr,
                json={
                    "employee_id": str(employee_record_id),
                    "leave_type_id": leave_type_id,
                    "entry_type": "opening_balance",
                    "days_delta": "5.00",
                    "leave_year": 2027,
                    "reason": "Fixture",
                },
            )
        ).status_code == 201
        leave = await client.post(
            f"{base}/me/leave-requests",
            headers=worker,
            json={
                "leave_type_id": leave_type_id,
                "start_date": "2027-01-05",
                "end_date": "2027-01-05",
                "days_requested": "1.00",
                "reason": "Private synthetic detail",
            },
        )
        assert leave.status_code == 201, leave.text
        leave_id = leave.json()["id"]
        assert leave.json()["approval_route"] == "supervisor"
        final_leave = f"{base}/leave/requests/{leave_id}/decision"
        decision = {"decision": "approved", "expected_revision": 1}
        assert (await client.post(final_leave, headers=manager, json=decision)).status_code == 403
        missing_revision = await client.post(
            final_leave, headers=hr, json={"decision": "approved"}
        )
        assert missing_revision.status_code == 409
        assert missing_revision.json()["error_code"] == "REVISION_REQUIRED"
        stale_revision = await client.post(
            final_leave,
            headers=hr,
            json={"decision": "approved", "expected_revision": 2},
        )
        assert stale_revision.status_code == 409
        assert stale_revision.json()["error_code"] == "REVISION_CONFLICT"
        too_early = await client.post(final_leave, headers=hr, json=decision)
        assert too_early.status_code == 403
        assert too_early.json()["error_code"] == "LEAVE_SUPERVISOR_DECISION_REQUIRED"
        supervisor_queue = f"{base}/me/leave-reviews"
        assert len((await client.get(supervisor_queue, headers=manager)).json()["items"]) == 1
        assert (await client.get(supervisor_queue, headers=worker)).json()["items"] == []
        assert (await client.get(queue, headers=manager)).json()["items"] == []
        assert (await client.get(queue, headers=executive)).json()["items"] == []
        assert (
            await client.post(
                f"{queue}/leave/{leave_id}",
                headers=worker,
                json={"recommendation": "support", "expected_revision": 1},
            )
        ).status_code == 404
        async with AsyncSessionLocal() as session:
            assert not (
                await session.scalars(
                    select(HrLeaveLedger.id).where(
                        HrLeaveLedger.reference_request_id == UUID(leave_id)
                    )
                )
            ).all()
        rejected = await client.post(
            f"{supervisor_queue}/{leave_id}/decision",
            headers=manager,
            json={"decision": "rejected", "expected_revision": 1, "notes": "Correct date"},
        )
        assert rejected.status_code == 200, rejected.text
        async with AsyncSessionLocal() as session:
            pending_action = await session.scalar(
                select(Notification).where(
                    Notification.reference_type == "hr_leave_request",
                    Notification.reference_id == UUID(leave_id),
                    Notification.event_code == "submitted",
                    Notification.event_revision == 1,
                )
            )
            assert pending_action is not None
            assert pending_action.superseded_at is not None
            assert pending_action.email_status in {"queued", "skipped", "failed", "sent"}
        submission = f"{base}/me/leave-requests/{leave_id}/submission"
        correction = {
            "leave_type_id": leave_type_id,
            "start_date": "2027-01-06",
            "end_date": "2027-01-06",
            "days_requested": "1.00",
            "expected_revision": 2,
            "reason": "Updated synthetic detail",
        }
        assert (await client.put(submission, headers=manager, json=correction)).status_code == 404
        assert (
            await client.put(
                submission, headers=worker, json={**correction, "employee_id": str(hr_employee_id)}
            )
        ).status_code == 422
        crossed_year = {**correction, "end_date": "2028-01-01"}
        assert (await client.put(submission, headers=worker, json=crossed_year)).status_code == 422
        resubmissions = await asyncio.gather(
            *(client.put(submission, headers=worker, json=correction) for _ in range(2))
        )
        assert sorted(response.status_code for response in resubmissions) == [200, 409]
        saved = next(response.json() for response in resubmissions if response.status_code == 200)
        assert saved["id"] == leave_id and saved["record_revision"] == 3
        assert saved["start_date"] == correction["start_date"] and saved["status"] == "submitted"
        finals = await asyncio.gather(
            *(
                client.post(
                    f"{supervisor_queue}/{leave_id}/decision",
                    headers=manager,
                    json={"decision": "approved", "expected_revision": 3},
                )
                for _ in range(2)
            )
        )
        assert sorted(response.status_code for response in finals) == [200, 409]
        missing_reversal_revision = await client.post(
            final_leave,
            headers=hr,
            json={"decision": "cancelled", "notes": "Synthetic reversal"},
        )
        assert missing_reversal_revision.status_code == 409
        assert missing_reversal_revision.json()["error_code"] == "REVISION_REQUIRED"
        assert (
            await client.post(
                final_leave,
                headers=hr,
                json={
                    "decision": "cancelled",
                    "expected_revision": 4,
                    "notes": "Synthetic entitlement restored on cancellation",
                },
            )
        ).status_code == 200
        async with AsyncSessionLocal() as session:
            balances = (
                await session.scalars(
                    select(HrLeaveLedger.days_delta).where(
                        HrLeaveLedger.reference_request_id == UUID(leave_id)
                    )
                )
            ).all()
            assert sorted(balances) == [-1, 1]

        fallback_leave = await client.post(
            f"{base}/me/leave-requests",
            headers=worker,
            json={
                "leave_type_id": leave_type_id,
                "start_date": "2027-01-05",
                "end_date": "2027-01-05",
                "days_requested": "1.00",
                "reason": "Synthetic fallback request",
            },
        )
        assert fallback_leave.status_code == 201, fallback_leave.text
        fallback_id = fallback_leave.json()["id"]
        from app.services.hr_workforce_service import HrWorkforceService

        async def no_leave_approver(
            self: HrWorkforceService, request, *, excluded_ids=None
        ) -> list[UUID]:
            return []

        with monkeypatch.context() as unavailable:
            unavailable.setattr(
                HrWorkforceService,
                "_eligible_hr_leave_approver_ids",
                no_leave_approver,
            )
            routed = await client.post(
                f"{base}/leave/requests/{fallback_id}/fallback",
                headers=hr,
                json={
                    "reason_code": "manager_temporarily_unavailable",
                    "reason": "Supervisor unavailable during review window",
                    "expected_revision": 1,
                    "until": "2027-01-04",
                },
            )
        assert routed.status_code == 200, routed.text
        assert routed.json()["approval_route"] == "hr_fallback"
        assert routed.json()["status"] == "submitted"
        assert routed.json()["setup_error_code"] == "LEAVE_APPROVER_NOT_CONFIGURED"
        hr_approved = await client.post(
            f"{base}/leave/requests/{fallback_id}/decision",
            headers=hr,
            json={"decision": "approved", "expected_revision": 2},
        )
        assert hr_approved.status_code == 200, hr_approved.text

        sheet_body = {
            "period_start": "2027-01-11",
            "period_end": "2027-01-15",
            "regular_hours": "36.50",
        }
        assert (
            await client.post(
                sheet_path, headers=worker, json={**sheet_body, "employee_id": str(hr_employee_id)}
            )
        ).status_code == 422
        sheet = await client.post(sheet_path, headers=worker, json=sheet_body)
        assert sheet.status_code == 201, sheet.text
        sheet_id = sheet.json()["id"]
        assert (await client.get(sheet_path, headers=manager)).json()["items"] == []
        review_sheet = f"{queue}/timesheet/{sheet_id}"
        assert (
            await client.post(
                review_sheet,
                headers=manager,
                json={"recommendation": "support", "expected_revision": 1},
            )
        ).status_code == 200
        final_sheet = f"{base}/timesheets/{sheet_id}/decision"
        assert (
            await client.post(
                final_sheet,
                headers=hr,
                json={
                    "decision": "rejected",
                    "notes": "Correct the total",
                    "expected_revision": 2,
                },
            )
        ).status_code == 200
        edited = await client.put(
            f"{sheet_path}/{sheet_id}/submission",
            headers=worker,
            json={
                "regular_hours": "35.00",
                "expected_revision": 3,
            },
        )
        assert edited.status_code == 200, edited.text
        assert (
            edited.json()["regular_hours"] == "35.00"
            and edited.json()["manager_recommendation"] is None
        )
        assert (
            await client.post(
                final_sheet, headers=hr, json={"decision": "approved", "expected_revision": 4}
            )
        ).status_code == 409

        overtime = await client.post(
            f"{base}/me/overtime",
            headers=worker,
            json={
                "work_date": "2027-01-16",
                "requested_hours": "2.25",
                "reason": "Private synthetic detail",
            },
        )
        assert overtime.status_code == 201, overtime.text
        overtime_id = overtime.json()["id"]
        # Changing a reporting relationship revokes the old grant. Reassigning it requires HR.
        moved = await client.patch(
            profile,
            headers=executive,
            json={
                "expected_revision": assigned.json()["record_revision"],
                "manager_employee_id": str(hr_employee_id),
            },
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["line_manager_reviewer_id"] is None
        assert (
            await client.post(
                f"{queue}/overtime/{overtime_id}",
                headers=manager,
                json={
                    "recommendation": "support",
                    "expected_revision": 1,
                },
            )
        ).status_code == 404
        assert (await client.get(queue, headers=manager)).json()["items"] == []
        closed_without_reviewer = await client.post(
            final_sheet,
            headers=hr,
            json={"decision": "approved", "expected_revision": 4},
        )
        assert closed_without_reviewer.status_code == 200, closed_without_reviewer.text
        again = await client.put(
            f"{profile}/manager-review",
            headers=hr,
            json={
                "enabled": True,
                "expected_revision": moved.json()["record_revision"],
            },
        )
        assert again.status_code == 200, again.text
        assert (
            await client.post(
                f"{queue}/overtime/{overtime_id}",
                headers=hr,
                json={
                    "recommendation": "support",
                    "expected_revision": 1,
                },
            )
        ).status_code == 200
        assert (
            await client.post(
                f"{base}/overtime/{overtime_id}/decision",
                headers=hr,
                json={
                    "decision": "approved",
                    "expected_revision": 2,
                },
            )
        ).status_code == 403

        monkeypatch.delenv("HR_LINE_MANAGER_REVIEW_ENABLED")
        get_settings.cache_clear()
        assert (
            await client.post(
                f"{base}/overtime/{overtime_id}/decision",
                headers=hr,
                json={"decision": "approved", "expected_revision": 2},
            )
        ).status_code == 403


@pytest.mark.asyncio
async def test_hr_h_leave_ledger_self_approval_block_and_reversal() -> None:
    await skip_if_database_unavailable()
    hrm_uid, hrm_email, pw = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager")
    staff_uid, staff_email, _ = await _create_portal_user("quantity_surveyor", pw)

    async with _client() as client:
        hrm_tok = await _login(client, hrm_email, pw)
        reviewer_tok = await _login(client, reviewer_email, pw)
        staff_tok = await _login(client, staff_email, pw)

        # Link employee directly using a Managing Director user
        _, admin_email, _ = await _create_portal_user("managing_director", pw)
        admin_tok = await _login(client, admin_email, pw)

        emp = await client.post(
            "/api/v1/hr/employees",
            json={
                "employee_code": f"LV-{uuid4().hex[:6]}",
                "first_name": "Leave",
                "last_name": "Tester",
                "work_email": staff_email,
                "employment_status": "active",
                "join_date": "2020-01-01",
            },
            headers=_auth(hrm_tok),
        )
        emp_id = emp.json()["id"]
        assert (
            await client.post(
                f"/api/v1/hr/employees/{emp_id}/link-account",
                json={"user_id": staff_uid},
                headers=_auth(admin_tok),
            )
        ).status_code == 200

        lt = await client.post(
            "/api/v1/hr/leave/types",
            json={"code": f"ANN-{uuid4().hex[:4]}", "name": "Annual Leave"},
            headers=_auth(hrm_tok),
        )
        assert lt.status_code == 201
        assert lt.json()["is_active"] is False
        lt_id = await _create_legacy_leave_type("Synthetic legacy annual leave")
        staff = _auth(staff_tok)
        quote_path = "/api/v1/hr/me/leave-units"
        period = {"leave_type_id": lt_id, "start_date": "2026-07-01", "end_date": "2026-07-05"}
        missing_schedule = await client.get(quote_path, params=period, headers=staff)
        assert missing_schedule.status_code == 409
        assert missing_schedule.json()["error_code"] == "LEAVE_SCHEDULE_MISSING"
        await _publish_leave_calendar(
            client, _auth(hrm_tok), _auth(reviewer_tok), "2026-07-01", "2026-07-06", "2026-07-03"
        )
        quote = await client.get(quote_path, params=period, headers=staff)
        assert quote.status_code == 200, quote.text
        assert quote.json()["days_requested"] == "2"
        weekend = await client.get(
            quote_path, params={**period, "start_date": "2026-07-04"}, headers=staff
        )
        assert weekend.status_code == 422
        assert weekend.json()["error_code"] == "NO_LEAVE_WORKDAYS"
        half = await client.get(
            quote_path,
            params={
                **period,
                "end_date": period["start_date"],
                "is_half_day": "true",
                "half_day_period": "morning",
            },
            headers=staff,
        )
        assert half.status_code == 200, half.text
        assert half.json()["days_requested"] == "0.50"
        spoof = await client.post(
            "/api/v1/hr/me/leave-requests", json={**period, "days_requested": "1"}, headers=staff
        )
        assert spoof.status_code == 409
        assert spoof.json()["error_code"] == "LEAVE_UNITS_MISMATCH"

        assert (
            await client.post(
                "/api/v1/hr/leave/ledger",
                json={
                    "employee_id": emp_id,
                    "leave_type_id": lt_id,
                    "entry_type": "opening_balance",
                    "days_delta": "14.00",
                    "leave_year": 2026,
                    "reason": "Annual entitlement",
                },
                headers=_auth(hrm_tok),
            )
        ).status_code == 201

        req = await client.post(
            "/api/v1/hr/me/leave-requests",
            json={
                **period,
                "is_half_day": False,
                "submit_immediately": True,
            },
            headers=_auth(staff_tok),
        )
        assert req.status_code == 201
        lr_id = req.json()["id"]

        # HR Manager self-submitted leave request cannot be self-approved
        self_req = await client.post(
            "/api/v1/hr/leave/requests",
            json={
                "employee_id": emp_id,
                "leave_type_id": lt_id,
                "start_date": "2026-07-06",
                "end_date": "2026-07-06",
                "days_requested": "1.00",
                "is_half_day": False,
                "submit_immediately": True,
            },
            headers=_auth(hrm_tok),
        )
        assert (
            await client.post(
                f"/api/v1/hr/leave/requests/{self_req.json()['id']}/decision",
                json={
                    "decision": "approved",
                    "expected_revision": self_req.json()["record_revision"],
                },
                headers=_auth(hrm_tok),
            )
        ).status_code == 403

        # Two approvals for one request may post only one ledger debit.
        async def approve():
            return await client.post(
                f"/api/v1/hr/leave/requests/{lr_id}/decision",
                json={"decision": "approved", "expected_revision": req.json()["record_revision"]},
                headers=_auth(hrm_tok),
            )

        decisions = await asyncio.gather(approve(), approve())
        assert sorted(response.status_code for response in decisions) == [200, 409]
        bal1 = (
            await client.get(
                f"/api/v1/hr/leave/balances/{emp_id}?leave_year=2026", headers=_auth(hrm_tok)
            )
        ).json()["items"]
        bal1_item = next(item for item in bal1 if item["leave_type_id"] == lt_id)
        assert float(bal1_item["balance_days"]) == pytest.approx(12.0)

        decision_path = f"/api/v1/hr/leave/requests/{lr_id}/decision"
        approved_revision = req.json()["record_revision"] + 1
        assert (await client.get(decision_path, headers=staff)).status_code == 403
        decision_state = await client.get(decision_path, headers=_auth(hrm_tok))
        assert decision_state.status_code == 200
        assert decision_state.headers["cache-control"] == "no-store"
        assert decision_state.json() == {
            "id": lr_id,
            "status": "approved",
            "record_revision": req.json()["record_revision"] + 1,
            "manager_recommendation": None,
            "decided_by_id": str(hrm_uid),
            "allowed_actions": [],
            "route_status": "final",
        }
        queue = "/api/v1/hr/leave/requests"
        page_params = {"employee_id": emp_id, "limit": 1}
        first = await client.get(queue, headers=_auth(hrm_tok), params=page_params)
        second = await client.get(
            queue, headers=_auth(hrm_tok), params={**page_params, "offset": 1}
        )
        assert first.json()["total"] == second.json()["total"] == 2
        assert [
            first.json()["items"][0]["id"], second.json()["items"][0]["id"],
        ] == [self_req.json()["id"], lr_id]
        approved = await client.get(
            queue, headers=_auth(hrm_tok), params={**page_params, "req_status": "approved"}
        )
        assert approved.json()["total"] == 1 and approved.json()["items"][0]["id"] == lr_id
        assert (await client.get(queue, headers=staff, params=page_params)).status_code == 403
        assert (
            await client.post(
                decision_path,
                json={"decision": "cancelled", "expected_revision": approved_revision},
                headers=_auth(hrm_tok),
            )
        ).status_code == 422
        reversal = {
            "decision": "cancelled",
            "expected_revision": approved_revision,
            "notes": "Verified schedule change",
        }
        assert (await client.post(decision_path, json=reversal, headers=staff)).status_code == 403
        assert (await client.post(
            f"/api/v1/hr/me/leave-requests/{lr_id}/cancel", headers=staff
        )).status_code == 409
        async with AsyncSessionLocal() as session:
            debit = await session.scalar(
                select(HrLeaveLedger).where(HrLeaveLedger.reference_request_id == UUID(lr_id))
            )
            assert debit is not None
            debit_id = debit.id
            debit.days_delta = Decimal("-1.00")
            await session.commit()
        inconsistent = await client.post(decision_path, json=reversal, headers=_auth(hrm_tok))
        assert inconsistent.status_code == 409 and "ledger debit" in inconsistent.json()["detail"]
        async with AsyncSessionLocal() as session:
            debit = await session.get(HrLeaveLedger, debit_id)
            assert debit is not None
            debit.days_delta = Decimal("-2.00")
            await session.commit()
        reversals = await asyncio.gather(*(
            client.post(decision_path, json=reversal, headers=_auth(hrm_tok)) for _ in range(2)
        ))
        assert sorted(response.status_code for response in reversals) == [200, 409]
        async with AsyncSessionLocal() as session:
            entries = (await session.scalars(
                select(HrLeaveLedger).where(HrLeaveLedger.reference_request_id == UUID(lr_id))
            )).all()
            assert sorted((entry.entry_type, entry.days_delta) for entry in entries) == [
                ("reversal", Decimal("2.00")), ("taken", Decimal("-2.00")),
            ]
            assert next(entry.id for entry in entries if entry.entry_type == "taken") == debit_id
        bal2 = (
            await client.get(
                f"/api/v1/hr/leave/balances/{emp_id}?leave_year=2026", headers=_auth(hrm_tok)
            )
        ).json()["items"]
        bal2_item = next(item for item in bal2 if item["leave_type_id"] == lt_id)
        assert float(bal2_item["balance_days"]) == pytest.approx(14.0)

        preparer, reviewer = _auth(hrm_tok), _auth(reviewer_tok)
        assert (
            await client.post(
                f"/api/v1/hr/leave/requests/{self_req.json()['id']}/decision",
                headers=preparer,
                json={
                    "decision": "cancelled",
                    "expected_revision": self_req.json()["record_revision"],
                },
            )
        ).status_code == 200
        paid_type = await client.post(
            "/api/v1/hr/leave/types",
            headers=preparer,
            json={"code": f"L-{uuid4().hex[:8]}", "name": "Dated paid leave"},
        )
        assert paid_type.status_code == 201
        policy_type = paid_type.json()["id"]
        policy_path = "/api/v1/hr/leave/policies"
        policy_input = {
            "name": "Synthetic entitlement",
            "leave_type_id": policy_type,
            "annual_entitlement_days": "12.00",
            "effective_from": "2026-07-01",
            "effective_to": "2026-07-03",
            "allow_negative_balance": True,
        }

        async def propose(extra):
            return await client.post(
                policy_path,
                headers=preparer,
                json={**policy_input, "code": f"P-{uuid4().hex[:8]}", **extra},
            )

        instant = await propose({"approve_immediately": True})
        assert instant.status_code == 422
        assert (await propose({"effective_to": "2026-06-30"})).status_code == 422
        drafts = [await propose({}), await propose({})]
        assert all(row.status_code == 201 and row.json()["status"] == "draft" for row in drafts)
        urls = [f"{policy_path}/{row.json()['id']}/decision" for row in drafts]
        approval = {"decision": "approved"}
        assert (await client.post(urls[0], headers=staff, json=approval)).status_code == 403
        assert (await client.post(urls[0], headers=preparer, json=approval)).status_code == 403
        concurrent = await asyncio.gather(
            *(client.post(url, headers=reviewer, json=approval) for url in urls)
        )
        assert sorted(row.status_code for row in concurrent) == [200, 409]
        conflict = next(index for index, row in enumerate(concurrent) if row.status_code == 409)
        assert concurrent[conflict].json()["error_code"] == "LEAVE_POLICY_OVERLAP"
        rejected = await client.post(
            urls[conflict],
            headers=reviewer,
            json={"decision": "rejected", "reason": "Overlap with reviewed policy"},
        )
        assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
        assert (
            await client.post(urls[conflict], headers=reviewer, json=approval)
        ).status_code == 409
        adjacent = await propose(
            {
                "effective_from": "2026-07-04",
                "effective_to": "2026-07-31",
                "allow_negative_balance": False,
            }
        )
        assert adjacent.status_code == 201
        assert (
            await client.post(
                f"{policy_path}/{adjacent.json()['id']}/decision", headers=reviewer, json=approval
            )
        ).status_code == 200
        req_path = "/api/v1/hr/me/leave-requests"
        spans_boundary = await client.post(
            req_path,
            headers=staff,
            json={
                "leave_type_id": policy_type,
                "start_date": "2026-07-02",
                "end_date": "2026-07-06",
            },
        )
        assert spans_boundary.status_code == 201, spans_boundary.text
        boundary_id = spans_boundary.json()["id"]
        blocked = await client.post(
            f"/api/v1/hr/leave/requests/{boundary_id}/decision",
            headers=reviewer,
            json={
                **approval,
                "expected_revision": spans_boundary.json()["record_revision"],
            },
        )
        assert blocked.status_code == 409
        assert blocked.json()["error_code"] == "INSUFFICIENT_LEAVE_BALANCE"
        assert (
            await client.post(f"{req_path}/{boundary_id}/cancel", headers=staff)
        ).status_code == 200
        within = await client.post(
            req_path,
            headers=staff,
            json={
                "leave_type_id": policy_type,
                "start_date": "2026-07-02",
                "end_date": "2026-07-02",
            },
        )
        assert within.status_code == 201
        approved = await client.post(
            f"/api/v1/hr/leave/requests/{within.json()['id']}/decision",
            headers=reviewer,
            json={**approval, "expected_revision": within.json()["record_revision"]},
        )
        assert approved.status_code == 200, approved.text


@pytest.mark.asyncio
async def test_hr_service_request_owner_can_reopen_with_current_version() -> None:
    await skip_if_database_unavailable()
    _, hr_email, password = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    _, director_email, _ = await _create_portal_user("managing_director", password)
    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))
        director = _auth(await _login(client, director_email, password))

        async def linked_staff() -> tuple[dict[str, str], str]:
            user_id, email, _ = await _create_portal_user("quantity_surveyor", password)
            created = await client.post(
                "/api/v1/hr/employees",
                headers=hr,
                json={
                    "employee_code": f"REQ-{uuid4().hex[:8]}",
                    "first_name": "Synthetic",
                    "last_name": "Request",
                    "work_email": email,
                    "employment_status": "active",
                },
            )
            assert created.status_code == 201
            employee_id = created.json()["id"]
            linked = await client.post(
                f"/api/v1/hr/employees/{employee_id}/link-account",
                headers=director,
                json={"user_id": user_id},
            )
            assert linked.status_code == 200
            return _auth(await _login(client, email, password)), employee_id

        owner, employee_id = await linked_staff()
        other, _ = await linked_staff()
        created = await client.post(
            "/api/v1/hr/me/requests",
            headers=owner,
            json={"request_type": "employment_letter", "subject": "Synthetic confirmation"},
        )
        assert created.status_code == 201
        request_id = created.json()["id"]
        reopen = f"/api/v1/hr/me/requests/{request_id}/reopen"
        resolve = f"/api/v1/hr/requests/{request_id}/resolve"
        opened_version = {"expected_updated_at": created.json()["updated_at"]}
        assert (await client.post(reopen, headers=owner, json=opened_version)).status_code == 409
        assert (
            await client.post(resolve, headers=owner, json={"status": "in_review"})
        ).status_code == 403
        review = await client.post(
            resolve, headers=hr, json={**opened_version, "status": "in_review"}
        )
        assert review.status_code == 200

        assign = f"/api/v1/hr/requests/{request_id}/assign"
        assignees = "/api/v1/hr/requests/assignees"
        assert (await client.get(assignees, headers=owner)).status_code == 403
        options = (await client.get(assignees, headers=hr)).json()
        assert options and all(set(option) == {"id", "full_name"} for option in options)
        reviewer_user = (await client.get("/api/v1/auth/me", headers=reviewer)).json()["id"]
        prior_owner = review.json()["assigned_to_id"]
        assignment = {
            "assigned_to_id": reviewer_user,
            "expected_updated_at": review.json()["updated_at"],
            "reason": "Synthetic handoff",
        }
        assert (await client.post(assign, headers=owner, json=assignment)).status_code == 403
        director_user = (await client.get("/api/v1/auth/me", headers=director)).json()["id"]
        assert director_user not in {option["id"] for option in options}
        assert (
            await client.post(
                assign, headers=hr, json={**assignment, "assigned_to_id": director_user}
            )
        ).status_code == 404
        assert (
            await client.post(assign, headers=hr, json={**assignment, "reason": " "})
        ).status_code == 422
        handoffs = await asyncio.gather(
            *(client.post(assign, headers=hr, json=assignment) for _ in range(2))
        )
        assert sorted(result.status_code for result in handoffs) == [200, 409]
        assigned = next(result.json() for result in handoffs if result.status_code == 200)
        assert assigned["assigned_to_id"] == reviewer_user
        assert assigned["status"] == "in_review"
        assert assigned["created_at"] == review.json()["created_at"]
        refused = await client.post(
            resolve,
            headers=hr,
            json={"status": "completed", "expected_updated_at": assigned["updated_at"]},
        )
        assert refused.json()["error_code"] == "HR_SERVICE_REQUEST_ASSIGNED_ELSEWHERE"
        async with AsyncSessionLocal() as session:
            events = list(
                await session.scalars(
                    select(ActivityLog).where(
                        ActivityLog.action == "hr.service_request.assigned",
                        ActivityLog.entity_id == UUID(request_id),
                    )
                )
            )
            assert len(events) == 1
            assert events[0].old_values == {"assigned_to_id": prior_owner}
            assert events[0].new_values == {"assigned_to_id": reviewer_user}
            assert events[0].comments == "Synthetic handoff"

        doc = await client.post(
            "/api/v1/hr/documents",
            headers=hr,
            data={
                "employee_id": employee_id,
                "title": "Synthetic response",
                "document_type": "other",
                "category": "ordinary",
                "is_employee_visible": "true",
            },
            files={"file": ("response.pdf", _pdf_bytes(), "application/pdf")},
        )
        assert doc.status_code == 201
        doc_id = doc.json()["id"]
        active = await client.post(
            f"/api/v1/hr/documents/{doc_id}/versions/1/decision",
            headers=reviewer,
            json={"decision": "approve"},
        )
        assert active.status_code == 200
        approved = await client.post(
            resolve,
            headers=reviewer,
            json={
                "status": "approved",
                "expected_updated_at": assigned["updated_at"],
                "generated_document_id": doc_id,
                "resolution_notes": "Synthetic response delivered.",
            },
        )
        assert approved.status_code == 200
        completed = await client.post(
            resolve,
            headers=reviewer,
            json={"status": "completed", "expected_updated_at": approved.json()["updated_at"]},
        )
        assert completed.status_code == 200
        assert completed.json()["generated_document_id"] == doc_id
        assert completed.json()["resolution_notes"] == "Synthetic response delivered."
        revision = {"expected_updated_at": completed.json()["updated_at"]}
        assert (await client.post(reopen, headers=other, json=revision)).status_code == 404
        assert (await client.post(reopen, headers=owner, json=opened_version)).status_code == 409
        first, second = await asyncio.gather(
            client.post(reopen, headers=owner, json=revision),
            client.post(reopen, headers=owner, json=revision),
        )
        assert sorted([first.status_code, second.status_code]) == [200, 409]
        assert (
            await client.post(resolve, headers=hr, json={**opened_version, "status": "in_review"})
        ).status_code == 409
        requests = await client.get("/api/v1/hr/me/requests", headers=owner)
        reopened = requests.json()["items"][0]
        assert reopened["id"] == request_id
        assert reopened["status"] == "open"
        assert reopened["assigned_to_id"] is None
        assert reopened["resolved_at"] is None
        assert reopened["generated_document_id"] == doc_id

        extra_ids = set()
        for category in ("document_request", "data_correction", "leave_inquiry"):
            inquiry = await client.post(
                "/api/v1/hr/me/requests",
                headers=owner,
                json={"request_type": category, "subject": f"Synthetic {category}"},
            )
            assert inquiry.status_code == 201
            assert inquiry.json()["request_type"] == category
            assert inquiry.json()["employee_id"] == employee_id
            extra_ids.add(inquiry.json()["id"])
        own = await client.get("/api/v1/hr/me/requests", headers=owner)
        foreign = await client.get("/api/v1/hr/me/requests", headers=other)
        assert extra_ids <= {row["id"] for row in own.json()["items"]}
        assert extra_ids.isdisjoint(row["id"] for row in foreign.json()["items"])
        queue = "/api/v1/hr/requests"
        filters: dict[str, str | int] = {
            "employee_id": employee_id, "req_status": "open", "limit": 2
        }
        assert (await client.get(queue, headers=owner, params=filters)).status_code == 403
        first = await client.get(queue, headers=hr, params=filters)
        second = await client.get(queue, headers=hr, params={**filters, "offset": 2})
        assert first.status_code == second.status_code == 200
        assert first.json()["total"] == second.json()["total"] == 4
        first_ids = {row["id"] for row in first.json()["items"]}
        second_ids = {row["id"] for row in second.json()["items"]}
        assert len(first_ids) == len(second_ids) == 2
        assert first_ids.isdisjoint(second_ids)
        assert first_ids | second_ids == extra_ids | {request_id}
        empty = await client.get(queue, headers=hr, params={**filters, "req_status": "completed"})
        assert empty.json() == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_hr_salary_confirmation_uses_current_approved_compensation(monkeypatch) -> None:
    from app.utils.permissions import (
        PERMISSION_HR_PAYROLL_APPROVE,
        PERMISSION_HR_PAYROLL_SENSITIVE,
        ROLE_PERMISSIONS,
    )

    await skip_if_database_unavailable()
    _, maker_email, password = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    owner_id, owner_email, _ = await _create_portal_user("quantity_surveyor", password)
    _, outsider_email, _ = await _create_portal_user("quantity_surveyor", password)
    _, director_email, _ = await _create_portal_user("managing_director", password)
    original = ROLE_PERMISSIONS["hr_manager"]
    monkeypatch.setitem(
        ROLE_PERMISSIONS, "hr_manager",
        original | {PERMISSION_HR_PAYROLL_APPROVE, PERMISSION_HR_PAYROLL_SENSITIVE},
    )
    base = "/api/v1/hr"
    async with _client() as client:
        maker, reviewer, owner, outsider, director = [
            _auth(await _login(client, email, password))
            for email in (maker_email, reviewer_email, owner_email, outsider_email, director_email)
        ]
        employee = await client.post(f"{base}/employees", headers=maker, json={
            "employee_code": f"SAL-{uuid4().hex[:12]}", "first_name": "Synthetic",
            "last_name": "Salary Letter", "work_email": owner_email, "employment_status": "active",
        })
        assert employee.status_code == 201
        employee_id = employee.json()["id"]
        employee_path = f"{base}/employees/{employee_id}"
        assert (await client.post(
            f"{employee_path}/link-account", headers=director, json={"user_id": owner_id}
        )).status_code == 200
        template = await client.post(f"{base}/letter-templates", headers=maker, json={
            "code": f"SAL-{uuid4().hex[:12]}", "name": "Salary confirmation",
            "letter_type": "salary_confirmation", "subject_template": "For {full_name}",
            "body_template": "Base compensation {salary_currency} {base_salary}, {pay_frequency}.",
        })
        assert template.status_code == 201
        selection = {"template_id": template.json()["id"], "employee_id": employee_id}
        render = f"{base}/letters/render"
        assert (await client.post(render, headers=maker, json=selection)).status_code == 409
        assert (await client.post(render, headers=maker, json={
            **selection, "extra_vars": {"base_salary": "1"}
        })).status_code == 422

        async def approve_term(effective_from: str, *, salary: str = "23456.78") -> str:
            term = await client.post(f"{base}/compensation", headers=maker, json={
                "employee_id": employee_id, "effective_from": effective_from, "currency": "LKR",
                "base_salary": salary, "pay_frequency": "monthly",
            })
            assert term.status_code == 201
            term_id = term.json()["id"]
            assert (await client.post(
                f"{base}/compensation/{term_id}/decision", headers=reviewer,
                json={"decision": "approve"},
            )).status_code == 200
            return str(term_id)

        async def preview() -> str:
            response = await client.post(render, headers=maker, json=selection)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["body"] == "Base compensation LKR 23456.78, monthly."
            return str(response.json()["digest"])

        async def save(digest: str) -> str:
            draft_id = str(uuid4())
            result = await client.post(f"{base}/letters/drafts", headers=maker, json={
                **selection, "expected_digest": digest, "draft_id": draft_id,
            })
            assert result.status_code == 201
            return draft_id

        first_source = await approve_term("2021-01-01")
        await approve_term("2090-01-01", salary="99999.99")
        old_digest = await preview()
        stale = await save(old_digest)
        stale_path = f"{employee_path}/letters/{stale}/decision"
        current_source = await approve_term("2022-01-01")
        current_digest = await preview()
        assert current_digest != old_digest
        assert (await client.post(
            stale_path, headers=reviewer, json={"decision": "issued"}
        )).status_code == 409
        letter_id = await save(current_digest)
        manager_path = f"{employee_path}/letters/{letter_id}"
        employee_letter = f"{base}/me/letters/{letter_id}"
        assert (await client.get(employee_letter, headers=owner)).status_code == 404
        assert (await client.post(
            f"{manager_path}/decision", headers=maker, json={"decision": "issued"}
        )).status_code == 403
        issued = await client.post(
            f"{manager_path}/decision", headers=reviewer, json={"decision": "issued"}
        )
        assert issued.status_code == 200
        own_letter = await client.get(employee_letter, headers=owner)
        assert own_letter.status_code == 200 and own_letter.json()["body"] == issued.json()["body"]
        assert (await client.get(employee_letter, headers=outsider)).status_code == 404
        monkeypatch.setitem(ROLE_PERMISSIONS, "hr_manager", original)
        assert (await client.get(manager_path, headers=reviewer)).status_code == 404
        assert (await client.get(f"{employee_path}/letters", headers=reviewer)).json()["total"] == 0
        assert (await client.get(employee_letter, headers=owner)).status_code == 200

    async with AsyncSessionLocal() as session:
        old = await session.get(HrIssuedLetter, UUID(stale))
        saved = await session.get(HrIssuedLetter, UUID(letter_id))
        assert old is not None and old.compensation_term_id == UUID(first_source)
        assert saved is not None and saved.compensation_term_id == UUID(current_source)
        assert "23456.78" not in saved.content_encrypted


@pytest.mark.asyncio
async def test_hr_i_policies_letters_requests_and_offboarding(monkeypatch) -> None:
    await skip_if_database_unavailable()
    today = date(2026, 11, 16)
    monkeypatch.setattr("app.services.hr_service.business_today", lambda: today)
    _, admin_email, pw = await _create_portal_user("managing_director")
    _, finance_email, _ = await _create_portal_user("operations_director", pw)
    _, hrm_email, _ = await _create_portal_user("hr_manager", pw)
    _, hre_email, _ = await _create_portal_user("hr_manager", pw)
    staff_uid, staff_email, _ = await _create_portal_user("quantity_surveyor", pw)

    async with _client() as client:
        admin_tok = await _login(client, admin_email, pw)
        finance = _auth(await _login(client, finance_email, pw))
        hrm_tok = await _login(client, hrm_email, pw)
        hre_tok = await _login(client, hre_email, pw)
        staff_tok = await _login(client, staff_email, pw)

        emp = await client.post(
            "/api/v1/hr/employees",
            json={
                "employee_code": f"OFF-{uuid4().hex[:6]}",
                "first_name": "Exit",
                "last_name": "User",
                "work_email": staff_email,
                "employment_status": "active",
                "join_date": "2025-01-01",
            },
            headers=_auth(hrm_tok),
        )
        emp_id = emp.json()["id"]
        await client.post(
            f"/api/v1/hr/employees/{emp_id}/link-account",
            json={"user_id": staff_uid},
            headers=_auth(admin_tok),
        )

        # Policy publish + self acknowledgement
        pol = await client.post(
            "/api/v1/hr/policies",
            json={
                "code": f"POL-{uuid4().hex[:4]}",
                "title": "Site Safety Handbook",
                "effective_date": "2026-06-01",
                "content_summary": "Mandatory PPE compliance on active construction sites.",
            },
            headers=_auth(hrm_tok),
        )
        assert pol.status_code == 201
        assert (
            await client.post(
                f"/api/v1/hr/me/policies/{pol.json()['id']}/acknowledge",
                json={"expected_version": "1.0", "notes": "Read and agreed"},
                headers=_auth(staff_tok),
            )
        ).status_code == 200

        # Employees cannot access the HR letter-rendering endpoint
        tpl = await client.post(
            "/api/v1/hr/letter-templates",
            json={
                "code": f"LTR-{uuid4().hex[:4]}",
                "name": "Salary Confirmation",
                "letter_type": "salary_confirmation",
                "subject_template": "Confirmation for {full_name}",
                "body_template": "Employee {full_name} ({employee_code}) is confirmed.",
                "requires_hr_manager": True,
            },
            headers=_auth(hrm_tok),
        )
        assert tpl.status_code == 201
        assert (
            await client.post(
                "/api/v1/hr/letters/render",
                json={"template_id": tpl.json()["id"], "employee_id": emp_id},
                headers=_auth(staff_tok),
            )
        ).status_code == 403
        rendered = await client.post(
            "/api/v1/hr/letters/render",
            json={"template_id": tpl.json()["id"], "employee_id": emp_id},
            headers=_auth(hrm_tok),
        )
        assert rendered.status_code == 403
        malformed = await client.post(
            "/api/v1/hr/letter-templates",
            json={
                "code": f"LTR-{uuid4().hex[:4]}",
                "name": "Invalid Template",
                "letter_type": "custom",
                "subject_template": "Employee {full_name",
                "body_template": "Confirmation body.",
            },
            headers=_auth(hrm_tok),
        )
        assert malformed.status_code == 422

        published_template = await client.post(
            "/api/v1/hr/letter-templates",
            json={
                "code": f"LTR-{uuid4().hex[:6]}",
                "name": "Employment verification",
                "letter_type": "employment_confirmation",
                "subject_template": "Employment for {full_name}",
                "body_template": "Employee {employee_code}: {purpose}",
            },
            headers=_auth(hrm_tok),
        )
        assert published_template.status_code == 201
        letter = {
            "template_id": published_template.json()["id"],
            "employee_id": emp_id,
            "extra_vars": {"purpose": "Synthetic <b>literal</b> confidential use."},
        }
        override = await client.post(
            "/api/v1/hr/letters/render",
            json={**letter, "extra_vars": {"full_name": "different employee"}},
            headers=_auth(hrm_tok),
        )
        assert override.status_code == 422
        preview = await client.post(
            "/api/v1/hr/letters/render", json=letter, headers=_auth(hrm_tok)
        )
        assert preview.status_code == 200
        draft_id = str(uuid4())
        drafts = "/api/v1/hr/letters/drafts"
        draft = {**letter, "expected_digest": preview.json()["digest"], "draft_id": draft_id}
        assert (await client.post(drafts, json=draft, headers=_auth(staff_tok))).status_code == 403
        stale = {**draft, "extra_vars": {"purpose": "Changed after preview."}}
        assert (await client.post(drafts, json=stale, headers=_auth(hrm_tok))).status_code == 409
        saved = await client.post(drafts, json=draft, headers=_auth(hrm_tok))
        assert saved.status_code == 201, saved.text
        assert (
            await client.post(drafts, json=draft, headers=_auth(hrm_tok))
        ).json() == saved.json()
        employee_letter = f"/api/v1/hr/me/letters/{draft_id}"
        manager_letter = f"/api/v1/hr/employees/{emp_id}/letters/{draft_id}"
        decision = f"{manager_letter}/decision"
        assert (await client.get(employee_letter, headers=_auth(staff_tok))).status_code == 404
        assert (
            await client.post(decision, json={"decision": "issued"}, headers=_auth(hrm_tok))
        ).status_code == 403
        assert (
            await client.post(decision, json={"decision": "rejected"}, headers=_auth(hre_tok))
        ).status_code == 422
        issued = await asyncio.gather(
            *(
                client.post(decision, json={"decision": "issued"}, headers=_auth(hre_tok))
                for _ in range(2)
            )
        )
        assert all(result.status_code == 200 for result in issued)
        assert issued[0].json() == issued[1].json()
        assert (
            await client.post(
                decision, json={"decision": "rejected", "reason": "Late"}, headers=_auth(hre_tok)
            )
        ).status_code == 409
        result = await client.get(employee_letter, headers=_auth(staff_tok))
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert result.json()["body"] == preview.json()["body"]
        assert result.json()["can_decide"] is False
        assert (await client.get(manager_letter, headers=_auth(staff_tok))).status_code == 403
        assert (await client.get(employee_letter, headers=_auth(hre_tok))).status_code == 404
        async with AsyncSessionLocal() as session:
            stored = await session.get(HrIssuedLetter, UUID(draft_id))
            assert stored is not None and "confidential use" not in stored.content_encrypted
            issued_logs = list(
                await session.scalars(
                    select(ActivityLog).where(
                        ActivityLog.action == "hr.letter.issued",
                        ActivityLog.entity_id == UUID(draft_id),
                    )
                )
            )
            assert len(issued_logs) == 1
            assert set(issued_logs[0].new_values or {}) == {"template_id", "employee_id"}

        submitted = await client.post(
            "/api/v1/hr/me/requests",
            headers=_auth(staff_tok),
            json={"request_type": "employment_letter", "subject": "Synthetic letter request"},
        )
        assert submitted.status_code == 201
        assert submitted.json()["generated_letter_id"] is None
        request_id = submitted.json()["id"]
        request_path = f"/api/v1/hr/requests/{request_id}"
        resolve_path = f"{request_path}/resolve"
        starting = {
            "status": "in_review",
            "generated_letter_id": draft_id,
            "expected_updated_at": submitted.json()["updated_at"],
        }
        assert (
            await client.post(resolve_path, headers=_auth(hrm_tok), json=starting)
        ).status_code == 422
        review = await client.post(
            resolve_path,
            headers=_auth(hrm_tok),
            json={"status": "in_review", "expected_updated_at": submitted.json()["updated_at"]},
        )
        assert review.status_code == 200
        completion = {
            "status": "completed",
            "generated_letter_id": draft_id,
            "expected_updated_at": review.json()["updated_at"],
        }
        assert (
            await client.post(resolve_path, headers=_auth(staff_tok), json=completion)
        ).status_code == 403
        assert (
            await client.post(
                resolve_path,
                headers=_auth(hrm_tok),
                json={**completion, "expected_updated_at": submitted.json()["updated_at"]},
            )
        ).status_code == 409
        waiting_id = str(uuid4())
        assert (
            await client.post(
                drafts,
                headers=_auth(hrm_tok),
                json={**draft, "draft_id": waiting_id},
            )
        ).status_code == 201
        assert (
            await client.post(
                resolve_path,
                headers=_auth(hrm_tok),
                json={**completion, "generated_letter_id": waiting_id},
            )
        ).status_code == 404
        options = await client.get(
            f"/api/v1/hr/employees/{emp_id}/letters?issued_only=true",
            headers=_auth(hrm_tok),
        )
        assert [row["id"] for row in options.json()["items"]] == [draft_id]
        other_employee = await client.post(
            "/api/v1/hr/employees",
            headers=_auth(hrm_tok),
            json={
                "employee_code": f"REQ-{uuid4().hex[:8]}",
                "first_name": "Another",
                "last_name": "Employee",
            },
        )
        assert other_employee.status_code == 201
        other_request = await client.post(
            "/api/v1/hr/requests",
            headers=_auth(hrm_tok),
            json={
                "request_type": "employment_letter",
                "subject": "Another request",
                "employee_id": other_employee.json()["id"],
            },
        )
        assert other_request.status_code == 201
        other_path = f"/api/v1/hr/requests/{other_request.json()['id']}/resolve"
        other_review = await client.post(
            other_path,
            headers=_auth(hrm_tok),
            json={"status": "in_review"},
        )
        assert other_review.status_code == 200
        unowned_letter = await client.post(
            other_path,
            headers=_auth(hrm_tok),
            json={**completion, "expected_updated_at": other_review.json()["updated_at"]},
        )
        assert unowned_letter.status_code == 404
        completed = await client.post(resolve_path, headers=_auth(hrm_tok), json=completion)
        assert completed.status_code == 200, completed.text
        assert completed.json()["generated_letter_id"] == draft_id
        owned = await client.get("/api/v1/hr/me/requests", headers=_auth(staff_tok))
        assert owned.json()["items"][0]["generated_letter_id"] == draft_id
        reopened = await client.post(
            f"/api/v1/hr/me/requests/{request_id}/reopen",
            headers=_auth(staff_tok),
            json={"expected_updated_at": completed.json()["updated_at"]},
        )
        assert reopened.status_code == 200
        assert reopened.json()["generated_letter_id"] == draft_id
        async with AsyncSessionLocal() as session:
            attachment_log = await session.scalar(
                select(ActivityLog).where(
                    ActivityLog.action == "hr.service_request.completed",
                    ActivityLog.entity_id == UUID(request_id),
                )
            )
            assert attachment_log is not None
            assert attachment_log.new_values is not None
            assert attachment_log.old_values is not None
            assert attachment_log.new_values["generated_letter_id"] == draft_id
            assert attachment_log.old_values["generated_letter_id"] is None

        # An old snapshot stays readable if later employee data changes.
        employee_url = f"/api/v1/hr/employees/{emp_id}"
        current = await client.get(employee_url, headers=_auth(hrm_tok))
        proposal = await client.post(
            f"{employee_url}/employment-changes",
            json={
                "change_type": "profile_correction",
                "effective_date": today.isoformat(),
                "employee_revision": current.json()["record_revision"],
                "updates": {"first_name": "Updated"},
                "reason": "Synthetic employee name correction",
            },
            headers=_auth(hrm_tok),
        )
        assert proposal.status_code == 201, proposal.text
        correction = f"{employee_url}/employment-changes/{proposal.json()['id']}"
        assert (
            await client.post(
                f"{correction}/decision", json={"decision": "approved"}, headers=_auth(hre_tok)
            )
        ).status_code == 200
        amended = await client.post(f"{correction}/apply", headers=_auth(hre_tok))
        assert amended.status_code == 200, amended.text
        assert (await client.get(employee_letter, headers=_auth(staff_tok))).json()[
            "body"
        ] == preview.json()["body"]
        waiting_decision = f"{employee_url}/letters/{waiting_id}/decision"
        blocked = await client.post(
            waiting_decision, json={"decision": "issued"}, headers=_auth(hre_tok)
        )
        assert blocked.status_code == 409
        rejected = await client.post(
            waiting_decision,
            json={"decision": "rejected", "reason": "New employee data."},
            headers=_auth(hre_tok),
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["rejection_reason"] == "New employee data."
        assert (
            await client.get(f"/api/v1/hr/me/letters/{waiting_id}", headers=_auth(staff_tok))
        ).status_code == 404

        # Offboarding clearance gate
        ob = await client.post(
            "/api/v1/hr/offboarding",
            json={
                "employee_id": emp_id,
                "separation_type": "resignation",
                "notice_date": "2026-07-01",
                "last_working_date": "2026-07-31",
            },
            headers=_auth(hrm_tok),
        )
        assert ob.status_code == 201
        case_id = ob.json()["id"]
        custody_url = f"/api/v1/hr/offboarding/{case_id}/custody"
        admin = _auth(admin_tok)
        hr = _auth(hrm_tok)

        async def it_event(kind: str, evidence: str, device: str | None = None):
            payload = {
                "area": "it_admin",
                "event_id": str(uuid4()),
                "kind": kind,
                "evidence_reference": evidence,
                "device_reference": device,
            }
            return await client.post(custody_url, headers=admin, json=payload)

        signoff = {
            "area": "it_admin",
            "event_id": str(uuid4()),
            "kind": "cleared",
            "evidence_reference": "IT-FINAL-1",
        }
        assert (await client.post(custody_url, headers=hr, json=signoff)).status_code == 403
        no_deactivation = await client.post(custody_url, headers=admin, json=signoff)
        assert no_deactivation.status_code == 409
        assert no_deactivation.json()["error_code"] == "ACCESS_REVOCATION_REQUIRED"
        assert (
            await client.get(custody_url, headers=_auth(staff_tok), params={"area": "it_admin"})
        ).status_code == 403

        blocked_comp = await client.post(
            f"/api/v1/hr/offboarding/{case_id}/complete",
            json={"rehire_eligible": True, "exit_interview_notes": "Synthetic interview"},
            headers=_auth(hrm_tok),
        )
        assert blocked_comp.status_code == 409

        access = await client.post(
            "/api/v1/hr/access-requests",
            json={"employee_id": emp_id, "request_type": "deactivate", "submit_immediately": True},
            headers=_auth(hre_tok),
        )
        assert access.status_code == 201
        decision_url = f"/api/v1/hr/access-requests/{access.json()['id']}/decision"
        assert (
            await client.post(decision_url, json={"action": "hr_approve"}, headers=_auth(hrm_tok))
        ).status_code == 200
        assert (
            await client.post(
                decision_url, json={"action": "admin_action"}, headers=_auth(admin_tok)
            )
        ).status_code == 200
        assert (await client.get("/api/v1/auth/me", headers=_auth(staff_tok))).status_code == 401

        for step in ob.json()["steps"]:
            result = await client.patch(
                f"/api/v1/hr/offboarding/steps/{step['id']}",
                json={"status": "cleared", "notes": "Cleared"},
                headers=_auth(hrm_tok),
            )
            expected = (
                403
                if step["department_area"] in {"store_inventory", "it_admin", "finance_accounts"}
                else 200
            )
            assert result.status_code == expected, result.text

        signed_at = (await client.get("/api/v1/hr/access-requests", headers=hr)).json()["items"]
        expected_revocation = next(
            request["admin_actioned_at"]
            for request in signed_at
            if request["id"] == access.json()["id"]
        )
        assert (await it_event("waived", "IT-BLANKET")).status_code == 422
        assert (await it_event("flagged", "IT-LAPTOP-MISSING", "device-a")).status_code == 200
        assert (await it_event("flagged", "IT-PHONE-MISSING", "DEVICE-B")).status_code == 200
        assert (await it_event("flagged", "IT-REPEAT-ALIAS", "DEVICE-A")).status_code == 409
        returned_device = await it_event("returned", "IT-LAPTOP-RETURN", "Device-A")
        assert returned_device.status_code == 200, returned_device.text
        assert returned_device.json()["device_reference"] == "DEVICE-A"
        remaining = await client.get(
            custody_url, headers=hr, params={"area": "it_admin", "limit": 1}
        )
        assert remaining.json()["outstanding_devices"] == 1
        assert remaining.json()["clearance_status"] == "flagged"
        blocked_it = await client.post(custody_url, headers=admin, json=signoff)
        assert blocked_it.status_code == 409
        assert blocked_it.json()["error_code"] == "IT_DEVICES_OUTSTANDING"
        assert (await it_event("waived", "IT-PHONE-EXCEPTION", "DEVICE-B")).status_code == 200
        signed_it = await client.post(custody_url, headers=admin, json=signoff)
        assert signed_it.status_code == 200, signed_it.text
        assert (
            await client.post(custody_url, headers=admin, json=signoff)
        ).json() == signed_it.json()

        clearance = {"event_id": str(uuid4()), "kind": "cleared", "evidence_reference": "STORE-001"}
        assert (await client.post(custody_url, json=clearance, headers=hr)).status_code == 403
        assert (await client.get("/api/v1/hr/offboarding", headers=admin)).status_code == 403

        location = await client.post(
            "/api/v1/inventory/locations",
            json={"name": "Custody Store", "code": uuid4().hex, "location_type": "warehouse"},
            headers=admin,
        )
        assert location.status_code == 201, location.text
        supplier = await client.post(
            "/api/v1/suppliers",
            json={
                "name": f"Custody supplier {uuid4().hex}",
                "category": "Civil",
                "rating": "A",
                "payment_terms": "30 days",
                "contact_person": "Return fixture",
                "phone": "+97455550000",
                "email": f"supplier-{uuid4().hex}@example.com",
                "address": "Fixture",
                "tax_registration_number": f"TAX-{uuid4().hex}",
                "compliance_status": "pending",
            },
            headers=admin,
        )
        assert supplier.status_code == 201, supplier.text
        item = await client.post(
            "/api/v1/inventory/items",
            json={
                "name": "Return fixture",
                "category": "Civil",
                "item_type": "consumable",
                "unit": "Nos",
                "supplier_id": supplier.json()["id"],
            },
            headers=admin,
        )
        assert item.status_code == 201, item.text
        item_id = item.json()["id"]
        movement = {
            "item_id": item_id,
            "quantity": "2",
            "movement_type": "return",
            "to_location_id": location.json()["id"],
            "reference_type": "hr_offboarding_cases",
        }
        for reference_id in (str(uuid4()), case_id):
            posted = await client.post(
                "/api/v1/inventory/movements",
                json={**movement, "reference_id": reference_id},
                headers={**admin, "Idempotency-Key": str(uuid4())},
            )
            assert posted.status_code == 201, posted.text
            returned = {
                "event_id": str(uuid4()),
                "kind": "returned",
                "evidence_reference": "STORE-RETURN-1",
                "movement_id": posted.json()["id"],
            }
            receipt = await client.post(custody_url, json=returned, headers=admin)
            assert receipt.status_code == (200 if reference_id == case_id else 404), receipt.text

        assert (
            await client.post(custody_url, json=returned, headers=admin)
        ).json() == receipt.json()
        duplicate = {**returned, "event_id": str(uuid4()), "evidence_reference": "DUPLICATE"}
        assert (await client.post(custody_url, json=duplicate, headers=admin)).status_code == 409
        changed = {**returned, "evidence_reference": "CHANGED"}
        assert (await client.post(custody_url, json=changed, headers=admin)).status_code == 409
        stock = await client.get(f"/api/v1/inventory/items/{item_id}/stock", headers=admin)
        assert stock.status_code == 200, stock.text
        assert Decimal(stock.json()[0]["on_hand_qty"]) == Decimal("4")
        recorded = await client.get(
            custody_url, params={"event_id": returned["event_id"]}, headers=hr
        )
        assert recorded.status_code == 200, recorded.text
        assert recorded.json()["items"] == [receipt.json()]
        assert recorded.json()["clearance_status"] == "pending"
        assert recorded.json()["case_closed"] is False

        settlement = f"/api/v1/hr/offboarding/{case_id}/settlement"

        def finance_proposal(outcome: str, ref: str, previous: str | None = None) -> dict:
            return {
                "event_id": str(uuid4()),
                "outcome": outcome,
                "evidence_reference": ref,
                "expected_record_id": previous,
            }

        empty = await client.get(settlement, headers=hr)
        assert empty.status_code == 200 and empty.json()["current_record_id"] is None
        assert (await client.get(settlement, headers=_auth(staff_tok))).status_code == 401
        outstanding = finance_proposal("outstanding", "FIN-OPEN-001")
        assert (await client.post(settlement, json=outstanding, headers=hr)).status_code == 403
        proposed = await client.post(settlement, json=outstanding, headers=admin)
        assert proposed.status_code == 200, proposed.text
        assert proposed.json()["status"] == "proposed"
        outstanding_review = {"decision": "approved", "evidence_reference": "FIN-OPEN-REVIEW"}
        review_path = f"{settlement}/{outstanding['event_id']}/review"
        assert (
            await client.post(review_path, json=outstanding_review, headers=admin)
        ).status_code == 403
        assert (
            await client.post(review_path, json=outstanding_review, headers=hr)
        ).status_code == 403
        reviewed = await client.post(review_path, json=outstanding_review, headers=finance)
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["status"] == "approved"
        assert (await client.get(settlement, headers=hr)).json()["clearance_status"] == "flagged"

        candidates = [
            finance_proposal("settled", f"FIN-RACE-{number}", outstanding["event_id"])
            for number in range(2)
        ]
        outcomes = await asyncio.gather(
            *(client.post(settlement, json=payload, headers=admin) for payload in candidates)
        )
        assert sorted(response.status_code for response in outcomes) == [200, 409]
        first = next(response.json() for response in outcomes if response.status_code == 200)
        original_proposal = next(
            payload for payload in candidates if payload["event_id"] == first["id"]
        )
        assert (
            await client.post(settlement, json=original_proposal, headers=admin)
        ).json() == first
        rejected = await client.post(
            f"{settlement}/{first['id']}/review",
            headers=finance,
            json={"decision": "rejected", "evidence_reference": "FIN-REJECTED-REVIEW"},
        )
        assert rejected.status_code == 200, rejected.text
        assert (await client.get(settlement, headers=hr)).json()["clearance_status"] == "flagged"
        stale = finance_proposal("nothing_due", "FIN-STALE")
        assert (await client.post(settlement, json=stale, headers=admin)).status_code == 409
        final_proposal = finance_proposal("settled", "FIN-PAID-001", first["id"])
        recorded = await client.post(settlement, json=final_proposal, headers=admin)
        assert recorded.status_code == 200, recorded.text
        final_review_url = f"{settlement}/{final_proposal['event_id']}/review"
        final_review = {"decision": "approved", "evidence_reference": "FIN-PAID-REVIEW"}
        result = await client.post(final_review_url, json=final_review, headers=finance)
        assert result.status_code == 200, result.text
        assert (await client.get(settlement, headers=hr)).json()["clearance_status"] == "cleared"

        # Legacy approvals cannot substitute for an inventory-owner attestation.
        store_id = next(
            step["id"]
            for step in ob.json()["steps"]
            if step["department_area"] == "store_inventory"
        )
        async with AsyncSessionLocal() as session:
            store = await session.get(HrClearanceStep, UUID(store_id))
            assert store is not None
            store.status = "cleared"
            store.notes = "Legacy clearance"
            await session.commit()
        complete = f"/api/v1/hr/offboarding/{case_id}/complete"
        legacy = await client.post(complete, json={}, headers=hr)
        assert legacy.status_code == 409
        assert legacy.json()["error_code"] == "CUSTODY_CLEARANCE_REQUIRED"
        flagged = await client.post(
            custody_url,
            json={"event_id": str(uuid4()), "kind": "flagged", "evidence_reference": "STORE-FLAG"},
            headers=admin,
        )
        assert flagged.status_code == 200
        assert (await client.post(complete, json={}, headers=hr)).status_code == 409

        signed = await client.post(custody_url, json=clearance, headers=admin)
        assert signed.status_code == 200, signed.text

        it_step_id = next(
            step["id"] for step in ob.json()["steps"] if step["department_area"] == "it_admin"
        )
        async with AsyncSessionLocal() as session:
            it_step = await session.get(HrClearanceStep, UUID(it_step_id))
            assert it_step is not None
            it_step.cleared_at = None
            await session.commit()
        legacy_it = await client.post(complete, json={}, headers=hr)
        assert legacy_it.status_code == 409
        assert legacy_it.json()["error_code"] == "IT_CLEARANCE_REQUIRED"
        assert (await it_event("flagged", "IT-REOPENED", "DEVICE-A")).status_code == 200
        assert (await client.post(complete, json={}, headers=hr)).status_code == 409
        assert (await it_event("returned", "IT-REINSPECTION", "DEVICE-A")).status_code == 200
        assert (await it_event("cleared", "IT-FINAL-2")).status_code == 200

        finance_step_id = next(
            step["id"]
            for step in ob.json()["steps"]
            if step["department_area"] == "finance_accounts"
        )
        async with AsyncSessionLocal() as session:
            finance_step = await session.get(HrClearanceStep, UUID(finance_step_id))
            assert finance_step is not None
            finance_step.cleared_at = None
            await session.commit()
        legacy_finance = await client.post(complete, json={}, headers=hr)
        assert legacy_finance.status_code == 409
        assert legacy_finance.json()["error_code"] == "SEPARATION_SETTLEMENT_REQUIRED"
        new_balance = finance_proposal("outstanding", "FIN-REOPEN-01", final_proposal["event_id"])
        assert (await client.post(settlement, json=new_balance, headers=admin)).status_code == 200
        assert (await client.post(complete, json={}, headers=hr)).status_code == 409
        assert (
            await client.post(final_review_url, json=final_review, headers=finance)
        ).json() == result.json()
        assert (await client.post(complete, json={}, headers=hr)).status_code == 409
        reopened_review = f"{settlement}/{new_balance['event_id']}/review"
        assert (
            await client.post(
                reopened_review,
                headers=finance,
                json={"decision": "approved", "evidence_reference": "FIN-OPEN-2"},
            )
        ).status_code == 200
        cleared = finance_proposal("nothing_due", "FIN-NOTHING-001", new_balance["event_id"])
        assert (await client.post(settlement, json=cleared, headers=admin)).status_code == 200
        approved = await client.post(
            f"{settlement}/{cleared['event_id']}/review",
            headers=finance,
            json={"decision": "approved", "evidence_reference": "FIN-NOTHING-REVIEW"},
        )
        assert approved.status_code == 200, approved.text

        done = await client.post(
            f"/api/v1/hr/offboarding/{case_id}/complete",
            json={"rehire_eligible": True, "exit_interview_notes": "Synthetic interview"},
            headers=_auth(hrm_tok),
        )
        assert done.status_code == 200
        assert done.json()["status"] == "completed"
        retained = await client.get(settlement, headers=hr)
        assert retained.json()["case_closed"] is True
        assert retained.json()["total"] == 5
        assert retained.json()["items"][0] == approved.json()
        after_close = finance_proposal("outstanding", "FIN-AFTER-CLOSE", cleared["event_id"])
        assert (await client.post(settlement, json=after_close, headers=admin)).status_code == 409
        assert done.json()["access_revoked_at"] == expected_revocation
        assert (await it_event("flagged", "IT-AFTER-CLOSE", "DEVICE-C")).status_code == 409
        it_only = await client.get(custody_url, headers=hr, params={"area": "it_admin"})
        assert it_only.json()["outstanding_devices"] == 0
        assert all(row["area"] == "it_admin" for row in it_only.json()["items"])
        stock_only = await client.get(custody_url, headers=hr)
        assert all(row["area"] == "store_inventory" for row in stock_only.json()["items"])
        assert (
            await client.post(custody_url, json=clearance, headers=admin)
        ).json() == signed.json()
        new_event = {**clearance, "event_id": str(uuid4()), "evidence_reference": "STORE-NEW"}
        assert (await client.post(custody_url, json=new_event, headers=admin)).status_code == 409

        former = (await client.get(employee_url, headers=hr)).json()
        assert former["employment_status"] == "resigned"
        period_url = f"{employee_url}/employment-periods"
        original = (await client.get(period_url, headers=hr)).json()["items"][0]
        assert (original["started_on"], original["ended_on"], original["separation_case_id"]) == (
            "2025-01-01",
            "2026-07-31",
            case_id,
        )
        stale_access = await client.post(
            "/api/v1/hr/access-requests",
            json={"employee_id": emp_id, "request_type": "reactivate", "submit_immediately": True},
            headers=_auth(hre_tok),
        )
        assert stale_access.status_code == 201, stale_access.text
        stale_url = f"/api/v1/hr/access-requests/{stale_access.json()['id']}/decision"
        assert (
            await client.post(stale_url, json={"action": "hr_approve"}, headers=hr)
        ).status_code == 200
        assert (
            await client.post(stale_url, json={"action": "admin_action"}, headers=admin)
        ).status_code == 409

        change_url = f"{employee_url}/employment-changes"
        start_on = today + timedelta(days=1)
        rehire = {
            "change_type": "rehire",
            "effective_date": start_on.isoformat(),
            "employee_revision": former["record_revision"],
            "updates": {
                "separation_case_id": case_id,
                "employment_category": "probation",
                "probation_days": 90,
            },
            "reason": "Reviewed return after separation",
        }
        assert (await client.post(change_url, json=rehire, headers=admin)).status_code == 403
        wrong_case = {
            **rehire,
            "updates": {**rehire["updates"], "separation_case_id": str(uuid4())},
        }
        assert (await client.post(change_url, json=wrong_case, headers=hr)).status_code == 409
        proposals = []
        for _ in range(2):
            made = await client.post(change_url, json=rehire, headers=hr)
            assert made.status_code == 201, made.text
            proposal_url = f"{change_url}/{made.json()['id']}"
            approval = {"decision": "approved"}
            assert (
                await client.post(f"{proposal_url}/decision", json=approval, headers=hr)
            ).status_code == 403
            decided = await client.post(
                f"{proposal_url}/decision", json=approval, headers=_auth(hre_tok)
            )
            assert decided.status_code == 200, decided.text
            proposals.append(proposal_url)
        assert (await client.post(f"{proposals[0]}/apply", headers=hr)).status_code == 409
        today = start_on
        outcomes = await asyncio.gather(
            *(client.post(f"{url}/apply", headers=hr) for url in proposals)
        )
        assert sorted(response.status_code for response in outcomes) == [200, 409]
        winner = next(response.json() for response in outcomes if response.status_code == 200)
        replay = await client.post(f"{change_url}/{winner['id']}/apply", headers=hr)
        assert replay.json() == winner
        current = (await client.get(employee_url, headers=hr)).json()
        assert current["id"] == emp_id and current["employee_code"] == former["employee_code"]
        assert current["employment_status"] == "onboarding"
        assert current["join_date"] == start_on.isoformat() and current["termination_date"] is None
        assert (await client.get("/api/v1/auth/me", headers=_auth(staff_tok))).status_code == 401
        assert (
            await client.post(stale_url, json={"action": "admin_action"}, headers=admin)
        ).status_code == 409
        periods = (await client.get(period_url, headers=hr)).json()["items"]
        assert len(periods) == 2 and periods[1] == original
        assert periods[0]["rehire_change_id"] == winner["id"]
        assert periods[0]["started_on"] == start_on.isoformat() and periods[0]["ended_on"] is None
        assert periods[0]["onboarding_case_id"]
        gaps_path = "/api/v1/hr/employment-periods/missing-start"
        assert (await client.get(gaps_path, headers=admin)).status_code == 403
        before_gaps = await client.get(gaps_path, headers=hr, params={"limit": 100})
        assert before_gaps.status_code == 200
        assert original["id"] not in {row["period_id"] for row in before_gaps.json()["items"]}
        async with AsyncSessionLocal() as session:
            historic = await session.get(HrEmploymentPeriod, UUID(original["id"]))
            assert historic is not None
            historic.started_on = None
            await session.commit()
        gaps = await client.get(gaps_path, headers=hr, params={"limit": 100})
        assert gaps.status_code == 200 and gaps.headers["cache-control"] == "no-store"
        assert gaps.json()["total"] == before_gaps.json()["total"] + 1
        gap = next(row for row in gaps.json()["items"] if row["period_id"] == original["id"])
        assert gap == {
            "period_id": original["id"],
            "employee_id": emp_id,
            "employee_code": current["employee_code"],
            "ended_on": original["ended_on"],
            "separation_case_id": original["separation_case_id"],
        }
        assert (await client.get(gaps_path, headers=hr, params={"limit": 101})).status_code == 422
        to_activate = {
            "expected_revision": current["record_revision"],
            "status": "active",
            "reason": "Synthetic attempted activation",
        }
        assert (
            await client.post(f"{employee_url}/status", json=to_activate, headers=hr)
        ).status_code == 409
        assert (
            await client.patch(
                employee_url,
                headers=hr,
                json={
                    "expected_revision": current["record_revision"],
                    "join_date": (today + timedelta(days=1)).isoformat(),
                },
            )
        ).status_code == 409
        history = (await client.get(f"{employee_url}/history", headers=hr)).json()["items"]
        assert sum(row["change_type"] == "rehire" for row in history) == 1
        assert sum(row["change_type"] == "offboarding_completed" for row in history) == 1

        onboarding = await client.get(
            "/api/v1/hr/onboarding", params={"employee_id": emp_id}, headers=hr
        )
        assert onboarding.status_code == 200, onboarding.text
        cases = onboarding.json()["items"]
        assert len(cases) == 1 and cases[0]["id"] == periods[0]["onboarding_case_id"]
        assert cases[0]["probation_end_date"] == (start_on + timedelta(days=90)).isoformat()
        for task in cases[0]["tasks"]:
            reviewed = await client.patch(
                f"/api/v1/hr/onboarding/tasks/{task['id']}",
                headers=hr,
                json={"status": "completed", "evidence_notes": "Synthetic reviewed evidence"},
            )
            assert reviewed.status_code == 200, reviewed.text
        assert (
            await client.post(f"{employee_url}/status", json=to_activate, headers=hr)
        ).status_code == 409
        too_early = await client.post(
            f"{employee_url}/status",
            headers=hr,
            json={**to_activate, "status": "on_probation", "effective_date": "2025-01-01"},
        )
        assert too_early.status_code == 422
        activated = await client.post(
            f"{employee_url}/status", json={**to_activate, "status": "on_probation"}, headers=hr
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["employment_status"] == "on_probation"

        from app.models.hr import HrCompensationTerm, HrPayrollPeriod
        from app.services.hr_payroll_snapshot import _source_terms
        from app.utils.security import utc_now

        async with AsyncSessionLocal() as session:
            old_term = HrCompensationTerm(
                employee_id=UUID(emp_id),
                effective_from=date(2025, 1, 1),
                pay_frequency="monthly",
                currency="LKR",
                base_salary_encrypted="test",
                base_salary_masked="********",
                approved_by_id=UUID(winner["decided_by"]),
                approved_at=utc_now(),
            )
            session.add(old_term)
            await session.flush()
            december = HrPayrollPeriod(
                period_code="synthetic-rehire",
                period_start=date(2026, 12, 1),
                period_end=date(2026, 12, 31),
                pay_date=date(2026, 12, 31),
            )
            with pytest.raises(AppException, match="one approved whole-period monthly term"):
                await _source_terms(session, [UUID(emp_id)], december, "LKR")
            new_term = HrCompensationTerm(
                employee_id=UUID(emp_id),
                effective_from=start_on,
                pay_frequency="monthly",
                currency="LKR",
                base_salary_encrypted="test",
                base_salary_masked="********",
                approved_by_id=UUID(winner["decided_by"]),
                approved_at=utc_now(),
            )
            session.add(new_term)
            await session.flush()
            assert await _source_terms(session, [UUID(emp_id)], december, "LKR") == [new_term]

        fresh_access = await client.post(
            "/api/v1/hr/access-requests",
            json={"employee_id": emp_id, "request_type": "reactivate", "submit_immediately": True},
            headers=_auth(hre_tok),
        )
        assert fresh_access.status_code == 201, fresh_access.text
        fresh_url = f"/api/v1/hr/access-requests/{fresh_access.json()['id']}/decision"
        assert (
            await client.post(fresh_url, json={"action": "hr_approve"}, headers=hr)
        ).status_code == 200
        restored = await client.post(fresh_url, json={"action": "admin_action"}, headers=admin)
        assert restored.status_code == 200, restored.text
        assert (await client.get("/api/v1/auth/me", headers=_auth(staff_tok))).status_code == 401


@pytest.mark.asyncio
async def test_hr_j_payroll_policy_gate_cases_and_cli() -> None:
    await skip_if_database_unavailable()
    _, email, password = await _create_portal_user("hr_manager")
    async with _client() as client:
        token = await _login(client, email, password)
        for endpoint in ("/payroll/policies", "/payroll/runs", "/cases"):
            response = await client.get(f"/api/v1/hr{endpoint}", headers=_auth(token))
            assert response.status_code == 403


def test_garrisonctl_hr_cli_preview_and_apply(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "cli-test-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)

    actor_id = str(uuid4())
    emp_id = str(uuid4())
    offer_id = str(uuid4())
    case_id = str(uuid4())
    leave_type_id = str(uuid4())
    policy_id = str(uuid4())
    policy_actor = actor_id
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(
        json.dumps(
            {
                "code": "CLI-POLICY",
                "name": "Synthetic policy",
                "leave_type_id": leave_type_id,
                "annual_entitlement_days": "12.00",
                "effective_from": "2026-07-01",
                "effective_to": "2026-12-31",
            }
        ),
        encoding="utf-8",
    )
    policy = {"id": policy_id, "code": "CLI-POLICY", "status": "draft", "created_by_id": actor_id}
    quoted_leave_days = "2"
    offer = {
        "id": offer_id,
        "status": "accepted",
        "version_number": 2,
        "updated_at": "2026-11-16T08:00:00Z",
        "converted_employee_id": None,
        "notes": "Synthetic confidential offer notes",
    }
    csv_path = tmp_path / "staffing.csv"
    csv_path.write_text(
        "User Name,Email,Portal Access Required,Role to Assign,"
        "Role Description,Privileges,Access Scope\n"
        "CLI Worker,cli.worker@example.com,Yes,quantity_surveyor,QS,Submit,Assigned\n",
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200,
                json={
                    "id": policy_actor,
                    "role": "hr_manager",
                    "permissions": [
                        "hr:employees:manage",
                        "hr:employees:read",
                        "hr:recruitment:manage",
                        "hr:leave:manage",
                        "hr:policy:manage",
                    ],
                },
                headers={"X-Request-ID": "cli-auth"},
            )
        if request.url.path == f"/api/v1/hr/offers/{offer_id}" and request.method == "GET":
            return httpx.Response(200, json=offer)
        if request.url.path == f"/api/v1/hr/leave/employees/{emp_id}/units":
            assert request.method == "GET"
            assert request.url.params["leave_type_id"] == leave_type_id
            return httpx.Response(200, json={"days_requested": quoted_leave_days})
        if request.url.path == "/api/v1/hr/leave/policies" and request.method == "POST":
            assert json.loads(request.content)["code"] == policy["code"]
            return httpx.Response(201, json=policy)
        if request.url.path == f"/api/v1/hr/leave/policies/{policy_id}/decision":
            assert request.method == "POST" and policy_actor != policy["created_by_id"]
            policy["status"] = json.loads(request.content)["decision"]
            return httpx.Response(200, json=policy)
        if request.url.path == f"/api/v1/hr/leave/policies/{policy_id}":
            assert request.method == "GET"
            return httpx.Response(200, json=policy)
        if request.url.path == "/api/v1/hr/leave/requests":
            assert request.method == "POST"
            assert json.loads(request.content)["days_requested"] == quoted_leave_days
            return httpx.Response(201, json={"days_requested": quoted_leave_days})
        if request.url.path == f"/api/v1/hr/offers/{offer_id}/convert":
            assert request.method == "POST"
            assert json.loads(request.content)["employee_code"] == "CLI-HIRE"
            offer.update(status="converted", converted_employee_id=emp_id)
            return httpx.Response(200, json={"id": case_id, "employee_id": emp_id})
        if request.url.path == "/api/v1/hr/employees" and request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(
                201,
                json={**body, "id": emp_id, "full_name": "CLI Worker", "record_revision": 1},
                headers={"X-Request-ID": "cli-create"},
            )
        if request.url.path == f"/api/v1/hr/employees/{emp_id}" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": emp_id,
                    "employee_code": "CLI-001",
                    "full_name": "CLI Worker",
                    "record_revision": 1,
                },
                headers={"X-Request-ID": "cli-get"},
            )
        if request.url.path == "/api/v1/hr/imports/workbook-preview":
            return httpx.Response(
                200,
                json={
                    "total_rows": 1,
                    "ready_employee_rows": 1,
                    "ready_access_request_rows": 1,
                    "blocked_missing_email_rows": 0,
                    "unmapped_role_rows": 0,
                    "already_linked_rows": 0,
                    "rows": [
                        {
                            "row_number": 2,
                            "user_name": "CLI Worker",
                            "email_source": "cli.worker@example.com",
                            "portal_access_required_raw": "Yes",
                            "portal_access_required": True,
                            "role_source": "quantity_surveyor",
                            "role_description_auto": "Eng",
                            "privileges_auto": "Submit",
                            "access_scope_auto": "Assigned",
                            "status": "ready_for_employee_and_access_request",
                            "role_mapping_status": "valid_portal_role",
                            "mapped_role": "quantity_surveyor",
                            "issues": [],
                            "can_import_employee": True,
                            "can_provision_user": True,
                        }
                    ],
                },
                headers={"X-Request-ID": "cli-preview"},
            )
        if request.url.path == "/api/v1/hr/imports/workbook-apply":
            return httpx.Response(
                200,
                json={
                    "employees_created": 1,
                    "employees_updated": 0,
                    "access_requests_created": 1,
                    "skipped_rows": 0,
                    "blocked_rows": 0,
                    "items": [],
                },
                headers={"X-Request-ID": "cli-apply"},
            )
        return httpx.Response(404, json={"detail": "not found"})

    def call_cli(*args: str) -> tuple[int, dict]:
        out, err = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [*args, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=out,
            stderr=err,
        )
        assert not err.getvalue()
        return code, json.loads(out.getvalue())

    convert = ("hr", "offers", "convert", "--offer-id", offer_id, "--employee-code", "CLI-HIRE")
    code, preview = call_cli(*convert, "--dry-run")
    assert code == 0 and preview["outcome"] == "preview"
    assert "notes" not in preview["data"]["offer"]
    checksum = preview["data"]["plan_sha256"]
    offer["updated_at"] = "2026-11-16T08:01:00Z"
    assert call_cli(*convert, "--apply", "--expect", checksum)[0] == 4
    assert offer["status"] == "accepted"
    code, preview = call_cli(*convert, "--dry-run")
    assert code == 0
    code, result = call_cli(*convert, "--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and result["changed"] is True
    assert result["data"]["onboarding_case_id"] == case_id
    code, saved = call_cli("hr", "offers", "status", "--offer-id", offer_id)
    assert code == 0 and saved["data"]["converted_employee_id"] == emp_id

    leave = (
        "hr",
        "leave",
        "requests",
        "submit",
        "--employee-id",
        emp_id,
        "--leave-type-id",
        leave_type_id,
        "--start-date",
        "2026-07-01",
        "--end-date",
        "2026-07-05",
    )
    assert call_cli(*leave, "--days", "1", "--dry-run")[0] == 4
    code, plan = call_cli(*leave, "--dry-run")
    assert code == 0 and plan["data"]["proposed"]["days_requested"] == "2"
    old_plan = plan["data"]["plan_sha256"]
    quoted_leave_days = "3"
    assert call_cli(*leave, "--apply", "--expect", old_plan)[0] == 4
    code, plan = call_cli(*leave, "--dry-run")
    assert code == 0
    code, posted = call_cli(*leave, "--apply", "--expect", plan["data"]["plan_sha256"])
    assert code == 0 and posted["data"]["days_requested"] == "3"

    propose = ("hr", "leave", "policy", "propose", "--file", str(policy_file))
    code, plan = call_cli(*propose, "--dry-run")
    assert code == 0 and plan["data"]["proposed"]["code"] == "CLI-POLICY"
    code, saved = call_cli(*propose, "--apply", "--expect", plan["data"]["plan_sha256"])
    assert code == 0 and saved["data"]["status"] == "draft"
    decide = ("hr", "leave", "policy", "decide", "--policy-id", policy_id, "--decision", "approved")
    assert call_cli(*decide, "--dry-run")[0] != 0
    policy_actor = str(uuid4())
    code, plan = call_cli(*decide, "--dry-run")
    assert code == 0 and plan["data"]["actor_id"] == policy_actor
    code, saved = call_cli(*decide, "--apply", "--expect", plan["data"]["plan_sha256"])
    assert code == 0 and saved["data"]["status"] == "approved"

    code, env_dry = call_cli(
        "hr",
        "employees",
        "create",
        "--employee-code",
        "CLI-001",
        "--first-name",
        "CLI",
        "--last-name",
        "Worker",
        "--dry-run",
    )
    assert code == 0 and env_dry["outcome"] == "preview"
    checksum = env_dry["data"]["plan_sha256"]

    code, env_apply = call_cli(
        "hr",
        "employees",
        "create",
        "--employee-code",
        "CLI-001",
        "--first-name",
        "CLI",
        "--last-name",
        "Worker",
        "--apply",
        "--expect",
        checksum,
    )
    assert code == 0 and env_apply["changed"] is True

    code, wb_dry = call_cli("hr", "workbook-reconcile", "--file", str(csv_path), "--dry-run")
    assert code == 0 and wb_dry["outcome"] == "preview"
    wb_sha = wb_dry["data"]["plan_sha256"]

    code, wb_bad = call_cli(
        "hr", "workbook-reconcile", "--file", str(csv_path), "--apply", "--expect", "deadbeef"
    )
    assert code == 4

    code, wb_ok = call_cli(
        "hr", "workbook-reconcile", "--file", str(csv_path), "--apply", "--expect", wb_sha
    )
    assert code == 0 and wb_ok["changed"] is True


@pytest.mark.asyncio
async def test_hr_employment_change_independent_dated_and_applied_once(monkeypatch) -> None:
    await skip_if_database_unavailable()
    first_day = date(2026, 11, 16)
    current_day = first_day
    monkeypatch.setattr("app.services.hr_service.business_today", lambda: current_day)
    _, creator_email, pw = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", pw)
    _, viewer_email, _ = await _create_portal_user("quantity_surveyor", pw)
    base = "/api/v1/hr"

    async with _client() as client:
        creator = _auth(await _login(client, creator_email, pw))
        reviewer = _auth(await _login(client, reviewer_email, pw))
        viewer = _auth(await _login(client, viewer_email, pw))

        async def employee(name: str, manager: str | None = None) -> dict:
            created = await client.post(
                f"{base}/employees",
                headers=creator,
                json={
                    "employee_code": f"EC-{uuid4().hex[:8]}",
                    "first_name": "Synthetic",
                    "last_name": name,
                    "employment_status": "active",
                    "manager_employee_id": manager,
                    "join_date": "2025-01-01",
                },
            )
            assert created.status_code == 201, created.text
            return created.json()

        old_manager = await employee("Previous Manager")
        next_manager = await employee("New Manager")
        worker = await employee("Worker", old_manager["id"])
        worker_id = worker["id"]
        employee_path = f"{base}/employees/{worker_id}"
        path = f"{employee_path}/employment-changes"
        async with AsyncSessionLocal() as session:
            row = await session.get(HrEmployee, UUID(worker_id))
            assert row is not None
            row.line_manager_reviewer_id = UUID(old_manager["id"])
            await session.commit()

        due = first_day + timedelta(days=1)
        plan = {
            "change_type": "transfer",
            "employee_revision": worker["record_revision"],
            "effective_date": due.isoformat(),
            "reason": "Synthetic approved transfer",
            "updates": {"manager_employee_id": next_manager["id"], "work_location": "New site"},
        }
        assert (await client.get(path, headers=viewer)).status_code == 403
        assert (await client.post(path, headers=viewer, json=plan)).status_code == 403
        assert (
            await client.post(path, headers=creator, json={**plan, "effective_date": "2026-11-15"})
        ).status_code == 422
        assert (
            await client.post(
                path, headers=creator, json={**plan, "updates": {"manager_employee_id": worker_id}}
            )
        ).status_code == 422
        assert (
            await client.post(
                path,
                headers=creator,
                json={**plan, "updates": {"primary_project_id": str(uuid4())}},
            )
        ).status_code == 422

        response = await client.post(path, headers=creator, json=plan)
        assert response.status_code == 201, response.text
        proposed = response.json()
        change = f"{path}/{proposed['id']}"
        decide = f"{change}/decision"
        apply = f"{change}/apply"
        assert (await client.post(apply, headers=creator)).status_code == 409
        approve = {"decision": "approved"}
        assert (await client.post(decide, headers=creator, json=approve)).status_code == 403
        accepted = await client.post(decide, headers=reviewer, json=approve)
        assert accepted.status_code == 200, accepted.text
        queue = f"{base}/employment-changes/due"
        assert (await client.get(queue, headers=viewer)).status_code == 403
        before_due = await client.get(queue, headers=reviewer)
        assert before_due.json()["as_of"] == first_day.isoformat()
        changes = await client.get(path, headers=reviewer)
        assert changes.json()["as_of"] == first_day.isoformat()
        assert changes.json()["items"][0]["effective_date"] == due.isoformat()
        assert proposed["id"] not in {row["id"] for row in before_due.json()["items"]}
        assert (await client.post(decide, headers=reviewer, json=approve)).json() == accepted.json()
        unchanged = (await client.get(employee_path, headers=creator)).json()
        assert unchanged["manager_employee_id"] == old_manager["id"]
        assert unchanged["line_manager_reviewer_id"] == old_manager["id"]
        assert unchanged["record_revision"] == worker["record_revision"]
        assert (await client.post(apply, headers=creator)).status_code == 409

        current_day = due
        assert (await client.get(path, headers=reviewer)).json()["as_of"] == due.isoformat()
        due_page = await client.get(queue, headers=reviewer, params={"limit": 50})
        assert due_page.status_code == 200 and due_page.headers["Cache-Control"] == "no-store"
        assert due_page.json()["as_of"] == due.isoformat()
        assert next(row for row in due_page.json()["items"] if row["id"] == proposed["id"]) == {
            "id": proposed["id"], "employee_id": worker_id,
            "employee_code": worker["employee_code"], "change_type": "transfer",
            "effective_date": due.isoformat(), "revision_matches": True,
        }
        first_page = await client.get(queue, headers=reviewer, params={"limit": 1})
        next_page = await client.get(queue, headers=reviewer, params={"limit": 1, "offset": 1})
        assert first_page.json()["items"] == due_page.json()["items"][:1]
        assert next_page.json()["items"] == due_page.json()["items"][1:2]
        assert next_page.json()["total"] == due_page.json()["total"]
        applies = await asyncio.gather(
            client.post(apply, headers=creator), client.post(apply, headers=reviewer)
        )
        assert all(result.status_code == 200 for result in applies), [r.text for r in applies]
        assert applies[0].json() == applies[1].json()
        after_apply = (await client.get(queue, headers=reviewer)).json()["items"]
        assert proposed["id"] not in {row["id"] for row in after_apply}
        changed = (await client.get(employee_path, headers=creator)).json()
        assert changed["manager_employee_id"] == next_manager["id"]
        assert changed["line_manager_reviewer_id"] is None
        assert changed["record_revision"] == worker["record_revision"] + 1
        assert changed["primary_project_id"] is None
        history = await client.get(f"{employee_path}/history", headers=creator)
        transfers = [item for item in history.json()["items"] if item["change_type"] == "transfer"]
        assert len(transfers) == 1 and transfers[0]["effective_date"] == due.isoformat()
        assert transfers[0]["previous_snapshot"]["manager_employee_id"] == old_manager["id"]
        assert transfers[0]["new_snapshot"]["manager_employee_id"] == next_manager["id"]

        amended = await client.post(
            path,
            headers=creator,
            json={
                "change_type": "category_amendment",
                "employee_revision": changed["record_revision"],
                "effective_date": due.isoformat(),
                "reason": "Synthetic agreement",
                "updates": {"employment_category": "contract"},
            },
        )
        assert amended.status_code == 201, amended.text
        amendment = f"{path}/{amended.json()['id']}"
        assert (
            await client.post(f"{amendment}/decision", headers=reviewer, json=approve)
        ).status_code == 200
        moved = await client.patch(
            employee_path,
            headers=creator,
            json={
                "expected_revision": changed["record_revision"],
                "work_location": "Current site",
            },
        )
        assert moved.status_code == 200
        due_stale = (await client.get(queue, headers=reviewer)).json()["items"]
        assert not next(
            row for row in due_stale if row["id"] == amended.json()["id"]
        )["revision_matches"]
        assert (await client.post(f"{amendment}/apply", headers=reviewer)).status_code == 409
        results = await client.get(path, headers=creator)
        assert results.json()["total"] == 2

        amendment_plan = amended.json()
        replacement = await client.post(
            path,
            headers=creator,
            json={
                "change_type": "category_amendment",
                "employee_revision": moved.json()["record_revision"],
                "effective_date": amendment_plan["effective_date"],
                "reason": amendment_plan["reason"],
                "updates": amendment_plan["updates"],
            },
        )
        assert replacement.status_code == 201
        replacement_path = f"{path}/{replacement.json()['id']}"
        assert (
            await client.post(f"{replacement_path}/decision", headers=reviewer, json=approve)
        ).status_code == 200
        assert (await client.post(f"{replacement_path}/apply", headers=reviewer)).status_code == 200
        latest = (await client.get(employee_path, headers=creator)).json()
        assert latest["employment_category"] == "contract"

        position = await client.post(
            f"{base}/positions",
            headers=creator,
            json={
                "code": f"EC-P-{uuid4().hex[:8]}",
                "title": "Synthetic grade",
                "headcount_limit": 1,
            },
        )
        assert position.status_code == 201, position.text
        position_id = position.json()["id"]
        next_employee = await employee("Promotion Candidate")

        async def promotion_path(target: dict) -> str:
            url = f"{base}/employees/{target['id']}/employment-changes"
            proposal = await client.post(
                url,
                headers=creator,
                json={
                    "change_type": "promotion",
                    "employee_revision": target["record_revision"],
                    "effective_date": due.isoformat(),
                    "reason": "Synthetic promotion",
                    "updates": {"position_id": position_id},
                },
            )
            assert proposal.status_code == 201, proposal.text
            change = f"{url}/{proposal.json()['id']}"
            assert (
                await client.post(f"{change}/decision", headers=reviewer, json=approve)
            ).status_code == 200
            return f"{change}/apply"

        first_application = await promotion_path(latest)
        second_application = await promotion_path(next_employee)
        candidates = await asyncio.gather(
            client.post(first_application, headers=reviewer),
            client.post(second_application, headers=reviewer),
        )
        assert sorted(result.status_code for result in candidates) == [200, 409]
        conflict = next(result for result in candidates if result.status_code == 409)
        assert conflict.json()["error_code"] == "HEADCOUNT_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_hr_contract_renewal_uses_exact_reviewed_document_versions(monkeypatch) -> None:
    await skip_if_database_unavailable()
    first_day = date(2026, 11, 16)
    day = first_day
    monkeypatch.setattr("app.services.hr_service.business_today", lambda: day)
    _, proposer_email, pw = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", pw)
    base = "/api/v1/hr"

    async with _client() as client:
        author = _auth(await _login(client, proposer_email, pw))
        reviewer = _auth(await _login(client, reviewer_email, pw))

        async def employee(category: str) -> dict:
            result = await client.post(
                f"{base}/employees",
                headers=author,
                json={
                    "employee_code": f"CT-{uuid4().hex[:8]}",
                    "first_name": "Synthetic",
                    "last_name": "Contractor",
                    "employment_status": "active",
                    "employment_category": category,
                    "join_date": "2025-01-01",
                },
            )
            assert result.status_code == 201, result.text
            return result.json()

        async def approve(document: str, version: int) -> None:
            published = await client.post(
                f"{base}/documents/{document}/versions/{version}/decision",
                headers=reviewer,
                json={"decision": "approve"},
            )
            assert published.status_code == 200, published.text

        async def contract(owner: str, expiry: str, *, publish: bool = True) -> str:
            result = await client.post(
                f"{base}/documents",
                headers=author,
                data={
                    "employee_id": owner,
                    "title": "Synthetic dated contract",
                    "document_type": "contract",
                    "category": "confidential",
                    "expiry_date": expiry,
                },
                files={"file": ("contract.pdf", _pdf_bytes(), "application/pdf")},
            )
            assert result.status_code == 201, result.text
            doc_id = result.json()["id"]
            if publish:
                await approve(doc_id, 1)
            return doc_id

        emp = await employee("contract")
        employee_id = emp["id"]
        profile = f"{base}/employees/{employee_id}"
        path = f"{profile}/employment-changes"
        current_doc = await contract(employee_id, first_day.isoformat())
        new_expiry = "2027-05-31"
        renewal_doc = await contract(employee_id, new_expiry, publish=False)
        other = await employee("contract")
        other_doc = await contract(other["id"], new_expiry)
        fields = {
            "current_contract_document_id": current_doc,
            "current_contract_version": 1,
            "renewal_contract_document_id": renewal_doc,
            "renewal_contract_version": 1,
            "contract_end_date": new_expiry,
        }
        due = first_day + timedelta(days=1)
        plan = {
            "change_type": "contract_renewal",
            "employee_revision": emp["record_revision"],
            "effective_date": due.isoformat(),
            "reason": "Reviewed synthetic extension",
            "updates": fields,
        }
        assert (await client.post(path, headers=author, json=plan)).status_code == 404
        assert (
            await client.post(
                path,
                headers=author,
                json={**plan, "updates": {**fields, "renewal_contract_document_id": other_doc}},
            )
        ).status_code == 404
        await approve(renewal_doc, 1)
        assert (
            await client.post(
                path,
                headers=author,
                json={**plan, "effective_date": (due + timedelta(days=1)).isoformat()},
            )
        ).status_code == 422
        assert (
            await client.post(
                path,
                headers=author,
                json={**plan, "updates": {**fields, "contract_end_date": "2027-06-01"}},
            )
        ).status_code == 422

        async def propose_and_review(selection: dict) -> str:
            draft = await client.post(path, headers=author, json=selection)
            assert draft.status_code == 201, draft.text
            change = f"{path}/{draft.json()['id']}"
            accepted = await client.post(
                f"{change}/decision", headers=reviewer, json={"decision": "approved"}
            )
            assert accepted.status_code == 200, accepted.text
            return f"{change}/apply"

        old_apply = await propose_and_review(plan)
        assert (await client.post(old_apply, headers=reviewer)).status_code == 409
        replacement = await client.post(
            f"{base}/documents/{renewal_doc}/versions",
            headers=author,
            files={"file": ("contract-v2.pdf", _pdf_bytes(), "application/pdf")},
        )
        assert replacement.status_code in {200, 201}, replacement.text
        await approve(renewal_doc, 2)
        day = due
        expired_evidence = await client.post(old_apply, headers=reviewer)
        assert expired_evidence.status_code == 409, expired_evidence.text
        assert (await client.get(profile, headers=author)).json()["record_revision"] == emp[
            "record_revision"
        ]

        applied_path = await propose_and_review(
            {**plan, "updates": {**fields, "renewal_contract_version": 2}}
        )
        applied = await client.post(applied_path, headers=reviewer)
        assert applied.status_code == 200, applied.text
        assert (await client.post(applied_path, headers=author)).json() == applied.json()
        updated = (await client.get(profile, headers=author)).json()
        assert updated["record_revision"] == emp["record_revision"] + 1
        assert updated["employment_category"] == "contract"
        assert updated["employment_status"] == "active"
        history = (await client.get(f"{profile}/history", headers=author)).json()["items"]
        retained = [row for row in history if row["change_type"] == "contract_renewal"]
        assert len(retained) == 1
        assert retained[0]["new_snapshot"]["renewal_contract_version"] == 2
        assert retained[0]["new_snapshot"]["contract_end_date"] == new_expiry

        next_doc = await contract(employee_id, "2027-12-31")
        next_term = {
            **plan,
            "employee_revision": updated["record_revision"],
            "effective_date": "2027-06-01",
            "updates": {
                **fields,
                "current_contract_document_id": renewal_doc,
                "current_contract_version": 1,
                "renewal_contract_document_id": next_doc,
                "contract_end_date": "2027-12-31",
            },
        }
        assert (await client.post(path, headers=author, json=next_term)).status_code == 409
        next_term["updates"]["current_contract_version"] = 2
        assert (await client.post(path, headers=author, json=next_term)).status_code == 201


@pytest.mark.asyncio
async def test_hr_payroll_snapshot_freezes_inputs_and_locks_one_approval(monkeypatch) -> None:
    import csv
    import hashlib

    from app.models.hr import (
        HrPayrollExport,
        HrPayrollLine,
        HrPayrollRun,
        HrPayrollSettlementEvent,
        HrPayslipPublication,
    )
    from app.utils.permissions import (
        PERMISSION_HR_PAYROLL_APPROVE,
        PERMISSION_HR_PAYROLL_PREPARE,
        PERMISSION_HR_PAYROLL_SENSITIVE,
        ROLE_PERMISSIONS,
    )

    await skip_if_database_unavailable()
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        "hr_manager",
        ROLE_PERMISSIONS["hr_manager"]
        | {
            PERMISSION_HR_PAYROLL_PREPARE,
            PERMISSION_HR_PAYROLL_APPROVE,
            PERMISSION_HR_PAYROLL_SENSITIVE,
        },
    )
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        "administrative_executive",
        ROLE_PERMISSIONS["administrative_executive"] | {PERMISSION_HR_PAYROLL_PREPARE},
    )
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        "operations_director",
        ROLE_PERMISSIONS["operations_director"]
        | {PERMISSION_HR_PAYROLL_APPROVE, PERMISSION_HR_PAYROLL_SENSITIVE},
    )
    _, preparer_email, password = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    other_user, other_email, _ = await _create_portal_user("administrative_executive", password)
    owner_user, owner_email, _ = await _create_portal_user("quantity_surveyor", password)
    _, director_email, _ = await _create_portal_user("managing_director", password)
    _, approval_only_email, _ = await _create_portal_user("operations_director", password)
    base = "/api/v1/hr"
    payroll = f"{base}/payroll"

    async with _client() as client:
        preparer = _auth(await _login(client, preparer_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))
        other = _auth(await _login(client, other_email, password))
        owner = _auth(await _login(client, owner_email, password))
        director = _auth(await _login(client, director_email, password))
        approval_only = _auth(await _login(client, approval_only_email, password))
        employee = await client.post(
            f"{base}/employees",
            headers=preparer,
            json={
                "employee_code": f"PAY-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Payroll",
                "work_email": owner_email,
                "employment_status": "active",
                "join_date": "2025-01-01",
            },
        )
        assert employee.status_code == 201, employee.text
        employee_id = employee.json()["id"]

        linked = await client.post(
            f"{base}/employees/{employee_id}/link-account",
            headers=director,
            json={"user_id": owner_user},
        )
        assert linked.status_code == 200, linked.text
        other_employee = await client.post(
            f"{base}/employees",
            headers=preparer,
            json={
                "employee_code": f"PAY-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Other",
                "employment_status": "active",
                "work_email": other_email,
            },
        )
        assert other_employee.status_code == 201
        assert (
            await client.post(
                f"{base}/employees/{other_employee.json()['id']}/link-account",
                headers=director,
                json={"user_id": other_user},
            )
        ).status_code == 200

        async def propose_term(start: str, amount: str, target: str = employee_id):
            return await client.post(
                f"{base}/compensation",
                headers=preparer,
                json={
                    "employee_id": target,
                    "effective_from": start,
                    "base_salary": amount,
                    "pay_frequency": "monthly",
                    "currency": "LKR",
                },
            )

        async def term_decision(term_id: str, actor, decision="approve", **fields):
            return await client.post(
                f"{base}/compensation/{term_id}/decision",
                headers=actor,
                json={"decision": decision, **fields},
            )

        async def term(start: str, amount: str, target: str = employee_id) -> str:
            result = await propose_term(start, amount, target)
            assert result.status_code == 201, result.text
            assert result.json()["approval_status"] == "proposed"
            assert result.json()["approved_by_id"] is None
            assert result.json()["base_salary_plain"] is None
            assert result.headers["cache-control"] == "no-store"
            term_id = result.json()["id"]
            approved_term = await term_decision(term_id, reviewer)
            assert approved_term.status_code == 200, approved_term.text
            assert approved_term.json()["approval_status"] == "approved"
            return term_id

        frozen_term = await term("2024-12-01", "100.05")
        await term("2025-02-01", "500.00")
        assert (await propose_term("2025-02-01", "700.00")).status_code == 409
        assert (await propose_term("2025-02-02", "NaN")).status_code == 422
        pending_term = await propose_term("2025-01-15", "999.99")
        assert pending_term.status_code == 201, pending_term.text
        pending_id = pending_term.json()["id"]
        assert (await term_decision(pending_id, preparer)).status_code == 403
        assert (await term_decision(pending_id, other)).status_code == 403
        assert (await propose_term("2025-01-16", "900")).status_code == 409
        assert (
            await client.get(f"{base}/compensation/{employee_id}", headers=director)
        ).status_code == 403
        zero_employee = await client.post(
            f"{base}/employees",
            headers=preparer,
            json={
                "employee_code": f"PAY-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Zero",
                "employment_status": "active",
                "join_date": "2025-01-01",
            },
        )
        assert zero_employee.status_code == 201
        zero_id = zero_employee.json()["id"]
        await term("2025-01-01", "0.00", zero_id)
        period_payload = {
            "period_code": f"PAY-{uuid4().hex[:8]}",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "pay_date": "2025-02-01",
        }
        period = await client.post(f"{payroll}/periods", headers=preparer, json=period_payload)
        assert period.status_code == 201, period.text
        period_id = period.json()["id"]
        overlap = await client.post(
            f"{payroll}/periods",
            headers=preparer,
            json={**period_payload, "period_code": f"PAY-{uuid4().hex[:8]}"},
        )
        assert overlap.status_code == 409

        rules = {
            "calculation_basis": "base_salary_only",
            "currency": "LKR",
            "rounding": "half_up",
            "pay_frequency": "monthly",
            "employee_deduction_rate": "0.10",
        }
        unsupported = await client.post(
            f"{payroll}/policies",
            headers=preparer,
            json={
                "code": f"PAY-{uuid4().hex[:8]}",
                "name": "Unsupported calculation",
                "rules_json": {**rules, "employee_deduction_rate": "NaN"},
            },
        )
        assert unsupported.status_code == 201
        assert (
            await client.post(
                f"{payroll}/policies/{unsupported.json()['id']}/approve", headers=reviewer
            )
        ).status_code == 422
        worked_example = {
            "base_salary": "100.05", "earnings": "0.00", "extra_deductions": "0.00",
            "expected_gross": "100.05", "expected_deductions": "10.01", "expected_net": "90.04",
        }
        controlled_record = {
            "document_reference": "HR-POL-FIXTURE",
            "version": "1.2",
            "effective_from": "2025-01-01",
            "approval_reference": "HR-DECISION-FIXTURE",
            "worked_examples": [worked_example],
        }
        policy_payload = {
            "code": f"PAY-{uuid4().hex[:8]}",
            "name": "Synthetic payroll",
            "rules_json": rules,
            "controlled_record": controlled_record,
        }
        invalid_record = {**controlled_record, "document_reference": "https://example.invalid"}
        assert (await client.post(
            f"{payroll}/policies", headers=preparer,
            json={**policy_payload, "controlled_record": invalid_record},
        )).status_code == 422
        wrong_example = await client.post(
            f"{payroll}/policies", headers=preparer, json={
                **policy_payload, "code": f"PAY-EXAMPLE-{uuid4().hex[:8]}",
                "controlled_record": {
                    **controlled_record,
                    "worked_examples": [{
                        **worked_example, "expected_net": "90.05",
                    }],
                },
            },
        )
        assert wrong_example.status_code == 201
        wrong_policy = f"{payroll}/policies/{wrong_example.json()['id']}"
        old_version = {"expected_updated_at": wrong_example.json()["updated_at"]}
        mismatch = await client.post(f"{wrong_policy}/approve", headers=reviewer, json=old_version)
        assert mismatch.status_code == 422
        assert mismatch.json()["error_code"] == "PAYROLL_EXAMPLE_MISMATCH"
        assert (await client.get(wrong_policy, headers=reviewer)).json()["is_approved"] is False
        correction = {
            **old_version, "name": policy_payload["name"], "rules_json": rules,
            "controlled_record": controlled_record,
        }
        denied_edit = await client.put(f"{wrong_policy}/draft", headers=other, json=correction)
        assert denied_edit.status_code == 403
        corrected = await client.put(f"{wrong_policy}/draft", headers=preparer, json=correction)
        assert corrected.status_code == 200
        assert corrected.json()["id"] == wrong_example.json()["id"]
        assert corrected.json()["updated_at"] != old_version["expected_updated_at"]
        stale_edit = await client.put(f"{wrong_policy}/draft", headers=preparer, json=correction)
        assert stale_edit.status_code == 409
        stale_review = await client.post(
            f"{wrong_policy}/approve", headers=reviewer, json=old_version
        )
        assert stale_review.status_code == 409
        assert stale_review.json()["error_code"] == "PAYROLL_POLICY_REVIEW_STALE"
        current_review = {"expected_updated_at": corrected.json()["updated_at"]}
        assert (await client.post(
            f"{wrong_policy}/approve", headers=reviewer, json=current_review
        )).status_code == 200
        assert (await client.put(
            f"{wrong_policy}/draft", headers=preparer, json={**correction, **current_review}
        )).status_code == 409
        policy = await client.post(
            f"{payroll}/policies",
            headers=preparer,
            json=policy_payload,
        )
        assert policy.status_code == 201, policy.text
        policy_id = policy.json()["id"]
        policy_detail = f"{payroll}/policies/{policy_id}"
        reviewed_policy = await client.get(policy_detail, headers=reviewer)
        assert reviewed_policy.status_code == 200
        assert reviewed_policy.headers["cache-control"] == "no-store"
        assert reviewed_policy.json()["rules_json"] == rules
        assert reviewed_policy.json()["controlled_record"] == controlled_record
        assert reviewed_policy.json()["is_approved"] is False
        assert (await client.get(policy_detail, headers=other)).status_code == 403
        missing_policy = await client.get(f"{payroll}/policies/{uuid4()}", headers=reviewer)
        assert missing_policy.status_code == 404
        policy_approval = f"{policy_detail}/approve"
        assert (await client.post(policy_approval, headers=preparer)).status_code == 409

        async def draft() -> str:
            run = await client.post(
                f"{payroll}/runs",
                headers=preparer,
                json={"payroll_period_id": period_id, "policy_id": policy_id},
            )
            assert run.status_code == 201, run.text
            return f"{payroll}/runs/{run.json()['id']}"

        first = await draft()
        roster = {"employee_ids": [employee_id, zero_id]}
        assert (
            await client.post(f"{first}/calculate", headers=preparer, json=roster)
        ).status_code == 409
        assert (await client.post(
            policy_approval, headers=reviewer,
            json={"expected_updated_at": reviewed_policy.json()["updated_at"]},
        )).status_code == 200
        future_policy = await client.post(
            f"{payroll}/policies", headers=preparer, json={
                **policy_payload, "code": f"PAY-FUTURE-{uuid4().hex[:8]}",
                "controlled_record": {**controlled_record, "effective_from": "2025-01-02"},
            },
        )
        assert future_policy.status_code == 201
        future_policy_id = future_policy.json()["id"]
        assert (await client.post(
            f"{payroll}/policies/{future_policy_id}/approve", headers=reviewer,
            json={"expected_updated_at": future_policy.json()["updated_at"]},
        )).status_code == 200
        future_run = await client.post(
            f"{payroll}/runs", headers=preparer,
            json={"payroll_period_id": period_id, "policy_id": future_policy_id},
        )
        assert future_run.status_code == 201
        premature = await client.post(
            f"{payroll}/runs/{future_run.json()['id']}/calculate", headers=preparer, json=roster,
        )
        assert premature.status_code == 409
        assert premature.json()["error_code"] == "PAYROLL_POLICY_NOT_EFFECTIVE"
        duplicate = {"employee_ids": [employee_id, employee_id]}
        assert (
            await client.post(f"{first}/calculate", headers=preparer, json=duplicate)
        ).status_code == 422
        assert (
            await client.post(f"{first}/calculate", headers=other, json=roster)
        ).status_code == 403
        assert (await client.get(f"{first}/snapshot", headers=other)).status_code == 403
        assert (await client.get(f"{first}/snapshot", headers=reviewer)).status_code == 409

        results = await asyncio.gather(
            *(client.post(f"{first}/calculate", headers=preparer, json=roster) for _ in range(2))
        )
        assert all(item.status_code == 200 for item in results), [item.text for item in results]
        digest = results[0].json()["snapshot_digest"]
        assert digest and results[1].json()["snapshot_digest"] == digest
        snapshot = await client.get(f"{first}/snapshot", headers=reviewer)
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.headers["cache-control"] == "no-store"
        payload = snapshot.json()
        assert payload["controlled_policy_record"] == controlled_record
        assert (payload["gross"], payload["deductions"], payload["net"]) == (
            "100.05",
            "10.01",
            "90.04",
        )
        assert payload["currency"] == "LKR"
        assert len(payload["lines"]) == 2
        assert (
            next(row["term_id"] for row in payload["lines"] if row["employee_id"] == employee_id)
            == frozen_term
        )

        adjustment_policy = await client.post(
            f"{payroll}/policies", headers=preparer,
            json={
                "code": f"PAY-ADJ-{uuid4().hex[:8]}",
                "name": "Synthetic reviewed adjustments policy",
                "rules_json": {
                    **rules, "calculation_basis": "base_salary_with_reviewed_adjustments"
                },
            },
        )
        assert adjustment_policy.status_code == 201
        adjusted_policy_id = adjustment_policy.json()["id"]
        assert (await client.post(
            f"{payroll}/policies/{adjusted_policy_id}/approve", headers=reviewer
        )).status_code == 200
        adjusted_run = await client.post(
            f"{payroll}/runs", headers=preparer,
            json={"payroll_period_id": period_id, "policy_id": adjusted_policy_id},
        )
        assert adjusted_run.status_code == 201
        adjusted = f"{payroll}/runs/{adjusted_run.json()['id']}"
        input_path = f"{adjusted}/adjustments"
        request = {
            "adjustment_id": str(uuid4()), "employee_id": employee_id,
            "kind": "earning", "amount": "12.50", "evidence_reference": "SYNTH-EARNING-1",
        }
        assert (await client.post(input_path, headers=other, json=request)).status_code == 403
        earning = await client.post(input_path, headers=preparer, json=request)
        assert earning.status_code == 200, earning.text
        assert earning.headers["cache-control"] == "no-store"
        assert earning.json() == (await client.post(
            input_path, headers=preparer, json=request
        )).json()
        changed = await client.post(
            input_path, headers=preparer, json={**request, "amount": "12.51"}
        )
        assert changed.status_code == 409
        duplicate_input = await client.post(
            input_path, headers=preparer, json={**request, "adjustment_id": str(uuid4())}
        )
        assert duplicate_input.status_code == 409
        assert (await client.get(input_path, headers=owner)).status_code == 403
        assert (await client.post(
            f"{adjusted}/calculate", headers=preparer, json=roster
        )).status_code == 409
        decision_path = f"{input_path}/{request['adjustment_id']}/decision"
        decision = {"expected_digest": earning.json()["digest"], "decision": "approved"}
        response = await client.post(decision_path, headers=preparer, json=decision)
        assert response.status_code == 403
        assert (await client.post(
            decision_path, headers=reviewer, json={**decision, "expected_digest": "0" * 64}
        )).status_code == 409
        response = await client.post(decision_path, headers=reviewer, json=decision)
        assert response.status_code == 200
        for reference, amount, outcome in (
            ("SYNTH-DEDUCTION-1", "2.50", "approved"),
            ("SYNTH-REJECTED-1", "500.00", "rejected"),
        ):
            proposal_id = str(uuid4())
            proposal = await client.post(
                input_path, headers=preparer,
                json={
                    **request, "adjustment_id": proposal_id, "kind": "deduction",
                    "amount": amount, "evidence_reference": reference,
                },
            )
            assert proposal.status_code == 200
            assert (await client.post(
                f"{input_path}/{proposal_id}/decision", headers=reviewer,
                json={"expected_digest": proposal.json()["digest"], "decision": outcome},
            )).status_code == 200
        assert (await client.post(
            f"{adjusted}/calculate", headers=preparer, json={"employee_ids": [zero_id]}
        )).status_code == 409
        frozen = await client.post(f"{adjusted}/calculate", headers=preparer, json=roster)
        assert frozen.status_code == 200, frozen.text
        assert (await client.post(
            input_path, headers=preparer, json={**request, "adjustment_id": str(uuid4())}
        )).status_code == 409
        adjusted_snapshot = (await client.get(f"{adjusted}/snapshot", headers=reviewer)).json()
        assert (adjusted_snapshot["gross"], adjusted_snapshot["deductions"],
                adjusted_snapshot["net"]) == ("112.55", "12.51", "100.04")
        frozen_line = next(
            row for row in adjusted_snapshot["lines"] if row["employee_id"] == employee_id
        )
        assert {item["evidence_reference"] for item in frozen_line["adjustments"]} == {
            "SYNTH-EARNING-1", "SYNTH-DEDUCTION-1"
        }

        await _publish_leave_calendar(client, preparer, reviewer, "2025-01-01", "2025-01-31")
        # This payroll-input case exercises a preconfigured legacy unpaid type;
        # newly created leave types now remain inactive until HR reviews policy.
        leave_type_id = await _create_legacy_leave_type("Synthetic unpaid", is_paid=False)
        leave_request = await client.post(
            f"{base}/leave/requests", headers=preparer, json={
                "employee_id": employee_id, "leave_type_id": leave_type_id,
                "start_date": "2025-01-07", "end_date": "2025-01-07", "submit_immediately": True,
            },
        )
        assert leave_request.status_code == 201
        leave_decision = f"{base}/leave/requests/{leave_request.json()['id']}/decision"
        approved_leave = await client.post(
            leave_decision,
            headers=reviewer,
            json={
                "decision": "approved",
                "expected_revision": leave_request.json()["record_revision"],
            },
        )
        assert approved_leave.status_code == 200

        sheet = await client.post(
            f"{base}/timesheets", headers=preparer, json={
                "employee_id": employee_id, "period_start": "2025-01-06",
                "period_end": "2025-01-10", "regular_hours": "32.00", "submit": True,
            },
        )
        assert sheet.status_code == 201
        for status in ("approved", "locked"):
            result = await client.post(
                f"{base}/timesheets/{sheet.json()['id']}/decision",
                headers=reviewer, json={"decision": status},
            )
            assert result.status_code == 200

        source_roster = {"employee_ids": [employee_id]}
        source_paths = {
            kind: f"{payroll}/periods/{period_id}/{kind}-inputs/preview"
            for kind in ("time", "leave")
        }
        source_digests = {}
        for kind, source_path in source_paths.items():
            preview = await client.post(source_path, headers=preparer, json=source_roster)
            assert preview.status_code == 200 and preview.json()["issues"] == []
            source_digests[f"{kind}_sha256"] = preview.json()["csv_sha256"]
        assert (await client.post(
            source_paths["leave"], headers=approval_only, json=source_roster
        )).status_code == 403
        sourced_run = await draft()
        observed = await client.post(
            f"{sourced_run}/calculate", headers=preparer,
            json={**source_roster, "source_evidence": source_digests},
        )
        assert observed.status_code == 200
        source_confirmation = {"expected_snapshot_digest": observed.json()["snapshot_digest"]}
        frozen_csv = await client.get(
            f"{sourced_run}/snapshot/sources/leave", headers=approval_only
        )
        assert frozen_csv.status_code == 200
        assert (await client.post(
            leave_decision, headers=reviewer, json={
                "decision": "cancelled", "notes": "Synthetic change after calculation",
                "expected_revision": approved_leave.json()["record_revision"],
            },
        )).status_code == 200
        after_reversal = await client.post(
            source_paths["leave"], headers=preparer, json=source_roster,
        )
        assert after_reversal.json()["unpaid_days"] == "0.00"
        assert after_reversal.json()["csv_sha256"] != source_digests["leave_sha256"]
        stale_approval = await client.post(
            f"{sourced_run}/approve", headers=approval_only, json=source_confirmation,
        )
        assert stale_approval.status_code == 409, stale_approval.text
        assert stale_approval.json()["error_code"] == "PAYROLL_SOURCES_CHANGED"
        retained = await client.get(f"{sourced_run}/snapshot", headers=approval_only)
        assert retained.json()["status"] == "calculated"
        assert retained.json()["digest"] == source_confirmation["expected_snapshot_digest"]
        assert (await client.get(
            f"{sourced_run}/snapshot/sources/leave", headers=approval_only
        )).content == frozen_csv.content

        assert (await term_decision(pending_id, reviewer, "reject")).status_code == 422
        rejection = await term_decision(
            pending_id, reviewer, "reject", reason="Synthetic private review"
        )
        assert rejection.status_code == 200 and rejection.json()["approval_status"] == "rejected"
        assert rejection.json()["rejection_reason"] is None
        assert (await term_decision(pending_id, reviewer)).status_code == 409
        retried = await client.post(f"{first}/calculate", headers=preparer, json=roster)
        assert retried.json()["snapshot_digest"] == digest
        assert (await client.get(f"{first}/snapshot", headers=reviewer)).json() == payload
        wrong_roster = {"employee_ids": [str(uuid4())]}
        assert (
            await client.post(f"{first}/calculate", headers=preparer, json=wrong_roster)
        ).status_code == 409

        confirmation = {"expected_snapshot_digest": digest}
        assert (
            await client.post(f"{first}/publish-payslips", headers=reviewer, json=confirmation)
        ).status_code == 409

        assert (
            await client.post(f"{first}/approve", headers=preparer, json=confirmation)
        ).status_code == 403
        assert (
            await client.post(
                f"{first}/approve", headers=reviewer, json={"expected_snapshot_digest": "0" * 64}
            )
        ).status_code == 409

        # Tampering with a line requires new review even if the old digest is supplied.
        run_id = UUID(results[0].json()["id"])
        async with AsyncSessionLocal() as session:
            line = await session.scalar(
                select(HrPayrollLine).where(
                    HrPayrollLine.payroll_run_id == run_id,
                    HrPayrollLine.employee_id == UUID(employee_id),
                )
            )
            run = await session.get(HrPayrollRun, run_id)
            assert (
                run is not None
                and run.snapshot_encrypted
                and "100.05" not in run.snapshot_encrypted
            )
            assert line is not None and "100.05" not in line.gross_encrypted
            original = line.net_encrypted
            line.net_encrypted = encrypt_hr_value("0.00") or ""
            await session.commit()
        assert (
            await client.post(f"{first}/approve", headers=reviewer, json=confirmation)
        ).status_code == 409
        async with AsyncSessionLocal() as session:
            line = await session.scalar(
                select(HrPayrollLine).where(
                    HrPayrollLine.payroll_run_id == run_id,
                    HrPayrollLine.employee_id == UUID(employee_id),
                )
            )
            assert line is not None
            line.net_encrypted = original
            await session.commit()

        # A different approved term requires a new run even when the amount is identical.
        replacement_term = await term("2025-01-01", "100.05")
        stale_term = await client.post(
            f"{first}/approve", headers=approval_only, json=confirmation
        )
        assert stale_term.status_code == 409, stale_term.text
        assert stale_term.json()["error_code"] == "PAYROLL_COMPENSATION_CHANGED"
        assert (await client.get(f"{first}/snapshot", headers=reviewer)).json() == payload
        assert (
            await client.post(f"{first}/calculate", headers=preparer, json=roster)
        ).json()["snapshot_digest"] == digest

        ready = {}
        for _ in range(2):
            fresh = await draft()
            calculated = await client.post(f"{fresh}/calculate", headers=preparer, json=roster)
            assert calculated.status_code == 200
            fresh_snapshot = (await client.get(f"{fresh}/snapshot", headers=reviewer)).json()
            assert next(
                line["term_id"] for line in fresh_snapshot["lines"]
                if line["employee_id"] == employee_id
            ) == replacement_term
            ready[fresh] = {"expected_snapshot_digest": calculated.json()["snapshot_digest"]}

        approvals = await asyncio.gather(*(
            client.post(f"{candidate}/approve", headers=reviewer, json=approval)
            for candidate, approval in ready.items()
        ))
        assert sorted(item.status_code for item in approvals) == [200, 409]
        approved = next(item for item in approvals if item.status_code == 200)
        winner = f"{payroll}/runs/{approved.json()['id']}"
        repeated = await client.post(
            f"{winner}/approve",
            headers=reviewer,
            json={"expected_snapshot_digest": approved.json()["snapshot_digest"]},
        )
        assert repeated.status_code == 200 and repeated.json() == approved.json()
        locked_term = await propose_term("2025-01-12", "685.55")
        assert locked_term.status_code == 201, locked_term.text
        locked_term_id = locked_term.json()["id"]
        assert (await term_decision(locked_term_id, reviewer)).status_code == 409
        assert (
            await term_decision(locked_term_id, reviewer, "reject", reason="Locked period")
        ).status_code == 200
        future_term = await term("2099-02-01", "1000.00")
        history = await client.get(f"{base}/compensation/{employee_id}", headers=reviewer)
        assert history.status_code == 200 and history.headers["cache-control"] == "no-store"
        active = [row for row in history.json()["items"] if row["is_current"]]
        assert [row["effective_from"] for row in active] == ["2025-02-01"]
        assert all(row["base_salary_plain"] is None for row in history.json()["items"])
        private_history = await client.get(
            f"{base}/compensation/{employee_id}",
            headers=reviewer,
            params={"reveal_sensitive": True},
        )
        assert private_history.status_code == 200
        private_rows = {row["id"]: row for row in private_history.json()["items"]}
        assert private_rows[future_term]["base_salary_plain"] == "1000.00"
        assert private_rows[pending_id]["rejection_reason"] == "Synthetic private review"
        one_term = await client.get(
            f"{base}/compensation/{employee_id}",
            headers=reviewer,
            params={"reveal_sensitive": True, "term_id": pending_id},
        )
        assert one_term.status_code == 200
        assert one_term.json() == {"items": [private_rows[pending_id]], "total": 1}
        unrelated_term = await client.get(
            f"{base}/compensation/{zero_id}",
            headers=reviewer,
            params={"reveal_sensitive": True, "term_id": pending_id},
        )
        assert unrelated_term.status_code == 404
        periods = (await client.get(f"{payroll}/periods", headers=preparer)).json()
        assert next(row for row in periods["items"] if row["id"] == period_id)["status"] == "locked"
        closed = await client.post(
            f"{payroll}/runs",
            headers=preparer,
            json={"payroll_period_id": period_id, "policy_id": policy_id},
        )
        assert closed.status_code == 409

        export = f"{winner}/payment-export"
        preview_url = f"{export}/preview"
        assert (await client.get(preview_url, headers=owner)).status_code == 403
        assert (await client.get(preview_url, headers=other)).status_code == 403
        assert (await client.get(export, headers=reviewer)).status_code == 404
        quoted = await client.get(preview_url, headers=reviewer)
        assert quoted.status_code == 200, quoted.text
        quote = quoted.json()
        assert quote["payment_count"] == 1 and quote["zero_net_count"] == 1
        assert (quote["gross"], quote["deductions"], quote["net"]) == ("100.05", "10.01", "90.04")
        assert quote["receipt"] is None
        export_plan = {
            "expected_snapshot_digest": quote["snapshot_digest"],
            "expected_csv_sha256": quote["csv_sha256"],
        }
        assert (await client.post(export, headers=preparer, json=export_plan)).status_code == 403
        assert (
            await client.post(
                export, headers=reviewer, json={**export_plan, "expected_csv_sha256": "0" * 64}
            )
        ).status_code == 409
        exports = await asyncio.gather(
            *(client.post(export, headers=reviewer, json=export_plan) for _ in range(2))
        )
        assert all(result.status_code == 200 for result in exports), [r.text for r in exports]
        assert exports[0].json() == exports[1].json()
        artifact = await client.get(export, headers=reviewer)
        assert artifact.status_code == 200, artifact.text
        assert artifact.headers["cache-control"] == "no-store"
        assert (
            artifact.headers["x-payroll-export-sha256"]
            == hashlib.sha256(artifact.content).hexdigest()
        )
        assert (await client.get(export, headers=reviewer)).content == artifact.content
        assert (
            employee_id not in artifact.text
            and zero_id not in artifact.text
            and owner_email not in artifact.text
        )
        exported = list(csv.DictReader(io.StringIO(artifact.text)))
        assert len(exported) == 1
        payment = exported[0]
        assert set(payment) == {"payment_reference", "currency", "net_amount"}
        assert payment["currency"] == "LKR" and payment["net_amount"] == "90.04"
        protected = (await client.get(f"{winner}/snapshot", headers=reviewer)).json()
        assert payment["payment_reference"] == next(
            row["payment_reference"]
            for row in protected["lines"]
            if row["employee_id"] == employee_id
        )
        async with AsyncSessionLocal() as session:
            export_id = UUID(approved.json()["id"])
            receipt = await session.get(HrPayrollExport, export_id)
            assert receipt is not None and receipt.csv_sha256 == quote["csv_sha256"]
            payment_line = await session.get(HrPayrollLine, UUID(payment["payment_reference"]))
            assert payment_line is not None and str(payment_line.employee_id) == employee_id
            before = receipt.csv_sha256
            receipt.csv_sha256 = "0" * 64
            await session.commit()
        assert (await client.get(export, headers=reviewer)).status_code == 409
        async with AsyncSessionLocal() as session:
            receipt = await session.get(HrPayrollExport, export_id)
            assert receipt is not None
            receipt.csv_sha256 = before
            await session.commit()

        settlement = f"{winner}/settlements"
        events_url = f"{settlement}/events"
        assert (await client.get(settlement, headers=owner)).status_code == 403
        initial = await client.get(settlement, headers=reviewer)
        assert initial.status_code == 200, initial.text
        assert initial.json()["outstanding"] == "90.04"
        assert initial.json()["payments"][0]["status"] == "pending"

        def event(kind: str, amount: str, **extra) -> dict:
            return {
                "event_id": str(uuid4()),
                "payment_reference": payment["payment_reference"],
                "expected_csv_sha256": quote["csv_sha256"],
                "kind": kind,
                "amount": amount,
                "occurred_on": "2025-02-01",
                "evidence_reference": f"PAY-EVID-{uuid4().hex}",
                **extra,
            }

        failed = event("failed", "0.00")
        assert (await client.post(events_url, headers=owner, json=failed)).status_code == 403
        assert (
            await client.post(
                events_url, headers=reviewer, json={**failed, "expected_csv_sha256": "0" * 64}
            )
        ).status_code == 409
        assert (await client.post(events_url, headers=reviewer, json=failed)).status_code == 200
        state = (await client.get(settlement, headers=reviewer)).json()
        assert state["net_paid"] == "0.00" and state["payments"][0]["status"] == "failed"
        assert (
            await client.post(
                events_url,
                headers=reviewer,
                json=event("paid", "40.00", payment_reference=str(uuid4())),
            )
        ).status_code == 404
        assert (
            await client.post(events_url, headers=reviewer, json=event("paid", "90.05"))
        ).status_code == 409

        initial_paid = event("paid", "40.00")
        posted = await client.post(events_url, headers=reviewer, json=initial_paid)
        assert posted.status_code == 200, posted.text
        assert (
            await client.post(events_url, headers=reviewer, json=initial_paid)
        ).json() == posted.json()
        assert (
            await client.post(
                events_url, headers=reviewer, json={**initial_paid, "amount": "39.00"}
            )
        ).status_code == 409
        assert (
            await client.post(
                events_url, headers=reviewer, json={**initial_paid, "event_id": str(uuid4())}
            )
        ).status_code == 409
        state = (await client.get(settlement, headers=reviewer)).json()
        assert state["outstanding"] == "50.04" and state["payments"][0]["status"] == "partial"
        competing = await asyncio.gather(
            *(
                client.post(events_url, headers=reviewer, json=event("paid", "50.04"))
                for _ in range(2)
            )
        )
        assert sorted(result.status_code for result in competing) == [200, 409]
        final_event = next(result.json()["id"] for result in competing if result.status_code == 200)
        state = (await client.get(settlement, headers=reviewer)).json()
        assert state["fully_reconciled"] and state["outstanding"] == "0.00"
        assert state["payments"][0]["status"] == "settled"
        assert (
            await client.post(
                events_url,
                headers=reviewer,
                json=event("reversed", "40.01", reverses_event_id=initial_paid["event_id"]),
            )
        ).status_code == 409
        assert (
            await client.post(
                events_url,
                headers=reviewer,
                json=event("reversed", "1.00", reverses_event_id=failed["event_id"]),
            )
        ).status_code == 404
        reversal = event("reversed", "40.00", reverses_event_id=initial_paid["event_id"])
        assert (await client.post(events_url, headers=reviewer, json=reversal)).status_code == 200
        state = (await client.get(settlement, headers=reviewer)).json()
        assert not state["fully_reconciled"] and state["outstanding"] == "40.00"
        assert state["payments"][0]["status"] == "partial"
        assert (
            await client.post(
                events_url,
                headers=reviewer,
                json=event("reversed", "1.00", reverses_event_id=initial_paid["event_id"]),
            )
        ).status_code == 409
        assert (
            await client.post(
                events_url,
                headers=reviewer,
                json=event("reversed", "50.04", reverses_event_id=final_event),
            )
        ).status_code == 200
        state = (await client.get(settlement, headers=reviewer)).json()
        assert not state["fully_reconciled"] and state["outstanding"] == "90.04"
        assert state["payments"][0]["status"] == "reversed"
        filtered = await client.get(
            events_url,
            headers=reviewer,
            params={"payment_reference": payment["payment_reference"], "limit": 2},
        )
        assert filtered.json()["total"] == 5 and len(filtered.json()["items"]) == 2
        logged = await client.get(f"{events_url}/{initial_paid['event_id']}", headers=reviewer)
        assert logged.status_code == 200 and logged.json() == posted.json()
        assert logged.headers["cache-control"] == "no-store"
        assert (
            await client.get(f"{events_url}/{initial_paid['event_id']}", headers=owner)
        ).status_code == 403
        assert (await client.get(export, headers=reviewer)).content == artifact.content
        async with AsyncSessionLocal() as session:
            item = await session.get(HrPayrollSettlementEvent, UUID(initial_paid["event_id"]))
            assert item is not None
            assert initial_paid["evidence_reference"] not in item.evidence_encrypted
            assert "40.00" not in item.amount_encrypted
            audit = await session.scalar(
                select(ActivityLog).where(
                    ActivityLog.entity_id == item.id,
                    ActivityLog.action == "hr.payroll_settlement.paid",
                )
            )
            assert audit is not None
            assert set(audit.new_values or {}) == {"run_id", "payment_reference"}

        payslips = f"{base}/me/payslips"
        payslip = f"{payslips}/{approved.json()['id']}"
        assert (await client.get(payslips, headers=owner)).json() == {"items": [], "total": 0}
        assert (await client.get(payslip, headers=owner)).status_code == 404
        assert (await client.get(f"{winner}/snapshot", headers=owner)).status_code == 403
        publish = f"{winner}/publish-payslips"
        accepted_digest = {"expected_snapshot_digest": approved.json()["snapshot_digest"]}
        assert (
            await client.post(publish, headers=preparer, json=accepted_digest)
        ).status_code == 403
        assert (await client.post(publish, headers=owner, json=accepted_digest)).status_code == 403
        assert (
            await client.post(
                publish, headers=reviewer, json={"expected_snapshot_digest": "0" * 64}
            )
        ).status_code == 409
        close = f"{winner}/close"
        close_payload = {
            **accepted_digest,
            "expected_csv_sha256": quote["csv_sha256"],
            "expected_settlement_digest": state["settlement_digest"],
        }
        assert (await client.post(close, headers=reviewer, json=close_payload)).status_code == 409
        releases = await asyncio.gather(
            *(client.post(publish, headers=reviewer, json=accepted_digest) for _ in range(2))
        )
        assert all(release.status_code == 200 for release in releases), [r.text for r in releases]
        assert releases[0].json() == releases[1].json()
        assert (await client.post(close, headers=owner, json=close_payload)).status_code == 403
        assert (await client.post(close, headers=preparer, json=close_payload)).status_code == 403
        assert (await client.post(close, headers=reviewer, json=close_payload)).status_code == 409
        repayment = event("paid", "90.04")
        assert (await client.post(events_url, headers=reviewer, json=repayment)).status_code == 200
        reconciled = (await client.get(settlement, headers=reviewer)).json()
        assert reconciled["fully_reconciled"] and reconciled["closure"] is None
        assert (await client.post(close, headers=reviewer, json=close_payload)).status_code == 409
        close_payload["expected_settlement_digest"] = reconciled["settlement_digest"]
        closures = await asyncio.gather(
            *(client.post(close, headers=reviewer, json=close_payload) for _ in range(2))
        )
        assert all(row.status_code == 200 for row in closures), [row.text for row in closures]
        assert closures[0].json() == closures[1].json()
        assert closures[0].headers["cache-control"] == "no-store"
        state = (await client.get(settlement, headers=reviewer)).json()
        assert state["closure"] == closures[0].json()
        assert (await client.post(events_url, headers=reviewer, json=repayment)).status_code == 200
        late_reversal = event("reversed", "90.04", reverses_event_id=repayment["event_id"])
        assert (
            await client.post(events_url, headers=reviewer, json=late_reversal)
        ).status_code == 409
        assert (await client.get(export, headers=reviewer)).content == artifact.content
        assert (await client.get(payslip)).status_code == 401
        assert (await client.get(payslips, headers=other)).json()["total"] == 0
        assert (await client.get(payslip, headers=other)).status_code == 404
        listed = (await client.get(payslips, headers=owner)).json()
        assert listed["total"] == 1
        assert set(listed["items"][0]) == {
            "run_id",
            "period_start",
            "period_end",
            "pay_date",
            "published_at",
        }
        slip = await client.get(payslip, headers=owner)
        assert slip.status_code == 200, slip.text
        assert slip.headers["cache-control"] == "no-store"
        assert slip.json() == {
            **listed["items"][0],
            "currency": "LKR",
            "gross": "100.05",
            "deductions": "10.01",
            "net": "90.04",
        }

        correction_path = f"{winner}/lines/{payment['payment_reference']}/corrections"
        before_snapshot = (await client.get(f"{winner}/snapshot", headers=reviewer)).json()
        assert before_snapshot["closed_at"]
        assert (await client.get(correction_path, headers=owner)).status_code == 403
        assert (await client.get(correction_path, headers=other)).status_code == 403
        proposal_id = str(uuid4())
        correction = {
            **accepted_digest,
            "correction_id": proposal_id,
            "expected_previous_id": None,
            "gross": "110.05",
            "deductions": "11.01",
            "evidence_reference": "PAY-CORR-PRIVATE-001",
        }
        submitted = await client.post(correction_path, headers=preparer, json=correction)
        assert submitted.status_code == 200, submitted.text
        assert submitted.headers["cache-control"] == "no-store"
        assert submitted.json()["net_delta"] == "9.00"
        replay = await client.post(correction_path, headers=preparer, json=correction)
        assert replay.json() == submitted.json()
        duplicate_correction = await client.post(
            correction_path, headers=preparer, json={**correction, "correction_id": str(uuid4())}
        )
        assert duplicate_correction.status_code == 409
        payload = {"expected_digest": submitted.json()["digest"], "decision": "approved"}
        decision_url = f"{correction_path}/{proposal_id}/decision"
        assert (await client.post(decision_url, headers=preparer, json=payload)).status_code == 403
        stale = await client.post(
            decision_url, headers=reviewer, json={**payload, "expected_digest": "0" * 64}
        )
        assert stale.status_code == 409
        accepted = await client.post(decision_url, headers=reviewer, json=payload)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "approved"
        identical_decision = await client.post(decision_url, headers=reviewer, json=payload)
        assert identical_decision.json() == accepted.json()
        stale_proposal = await client.post(
            correction_path, headers=preparer, json={**correction, "correction_id": str(uuid4())}
        )
        assert stale_proposal.status_code == 409
        next_correction_id = str(uuid4())
        successor = await client.post(
            correction_path, headers=preparer,
            json={
                **correction, "correction_id": next_correction_id,
                "expected_previous_id": proposal_id,
                "gross": "108.05", "evidence_reference": "PAY-CORR-PRIVATE-002",
            },
        )
        assert successor.status_code == 200, successor.text
        assert successor.json()["baseline"]["net"] == "99.04"
        assert successor.json()["net_delta"] == "-2.00"
        approved_successor = await client.post(
            f"{correction_path}/{next_correction_id}/decision", headers=reviewer,
            json={"decision": "approved", "expected_digest": successor.json()["digest"]},
        )
        assert approved_successor.status_code == 200, approved_successor.text
        detail_path = f"{correction_path}/{proposal_id}"
        detail = await client.get(detail_path, headers=reviewer)
        assert detail.status_code == 200 and detail.json() == accepted.json()
        assert detail.headers["cache-control"] == "no-store"
        assert (await client.get(detail_path, headers=owner)).status_code == 403
        wrong_id = await client.get(f"{correction_path}/{uuid4()}", headers=reviewer)
        assert wrong_id.status_code == 404
        history = (await client.get(correction_path, headers=reviewer)).json()
        assert history["current_correction_id"] == next_correction_id
        assert history["baseline"]["net"] == "97.04"
        assert history["total"] == 2
        assert history["items"][0]["previous_id"] == proposal_id
        assert (await client.get(payslip, headers=owner)).json() == slip.json()
        assert (await client.get(export, headers=reviewer)).content == artifact.content
        assert (await client.get(f"{winner}/snapshot", headers=reviewer)).json() == before_snapshot

        async with AsyncSessionLocal() as session:
            key = UUID(approved.json()["id"])
            publication = await session.get(HrPayslipPublication, key)
            assert publication is not None
            events = list(
                await session.scalars(
                    select(ActivityLog).where(
                        ActivityLog.entity_id == key,
                        ActivityLog.action == "hr.payroll_run.payslips_published",
                    )
                )
            )
            assert len(events) == 1 and "90.04" not in str(events[0].new_values)
            publication.snapshot_digest = "0" * 64
            await session.commit()
        assert (await client.get(payslip, headers=owner)).status_code == 409
        assert (await client.get(payslip, headers=other)).status_code == 404

        zero_period = await client.post(
            f"{payroll}/periods", headers=preparer,
            json={
                "period_code": f"ZERO-{uuid4().hex[:8]}",
                "period_start": "2025-02-01",
                "period_end": "2025-02-28",
                "pay_date": "2025-03-01",
            },
        )
        assert zero_period.status_code == 201, zero_period.text
        zero_run = await client.post(
            f"{payroll}/runs", headers=preparer,
            json={"payroll_period_id": zero_period.json()["id"], "policy_id": policy_id},
        )
        assert zero_run.status_code == 201, zero_run.text
        zero_path = f"{payroll}/runs/{zero_run.json()['id']}"
        calculated = await client.post(
            f"{zero_path}/calculate", headers=preparer, json={"employee_ids": [zero_id]}
        )
        assert calculated.status_code == 200, calculated.text
        zero_digest = {"expected_snapshot_digest": calculated.json()["snapshot_digest"]}
        for action in ("approve", "publish-payslips"):
            response = await client.post(
                f"{zero_path}/{action}", headers=reviewer, json=zero_digest
            )
            assert response.status_code == 200, response.text
        zero_state = await client.get(f"{zero_path}/settlements", headers=reviewer)
        assert zero_state.status_code == 200, zero_state.text
        zero_summary = zero_state.json()
        assert zero_summary["fully_reconciled"] and zero_summary["payments"] == []
        zero_closed = await client.post(
            f"{zero_path}/close", headers=reviewer,
            json={
                **zero_digest,
                "expected_csv_sha256": zero_summary["csv_sha256"],
                "expected_settlement_digest": zero_summary["settlement_digest"],
            },
        )
        assert zero_closed.status_code == 200, zero_closed.text


def test_hr_payroll_cli_confirms_snapshot_digest_and_reads_back(tmp_path, monkeypatch) -> None:
    from app.utils.permissions import (
        PERMISSION_HR_PAYROLL_APPROVE,
        PERMISSION_HR_PAYROLL_PREPARE,
        PERMISSION_HR_PAYROLL_SENSITIVE,
    )

    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-cli-token")
    actor = str(uuid4())
    employee = str(uuid4())
    run = str(uuid4())
    digest = "a" * 64
    path = f"/api/v1/hr/payroll/runs/{run}"
    roster = tmp_path / "roster.json"
    roster.write_text(json.dumps([employee]), encoding="utf-8")
    checksums = {"time_sha256": "b" * 64, "leave_sha256": "c" * 64}
    status = "draft"
    published_at = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status, published_at
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200,
                json={
                    "id": actor,
                    "role": "hr_manager",
                    "permissions": [
                        PERMISSION_HR_PAYROLL_PREPARE,
                        PERMISSION_HR_PAYROLL_APPROVE,
                        PERMISSION_HR_PAYROLL_SENSITIVE,
                    ],
                },
            )
        if request.url.path == f"{path}/calculate":
            assert json.loads(request.content) == {
                "employee_ids": [employee], "source_evidence": checksums
            }
            status = "calculated"
        elif request.url.path == f"{path}/approve":
            assert json.loads(request.content) == {"expected_snapshot_digest": digest}
            status = "approved"
        elif request.url.path == f"{path}/publish-payslips":
            assert json.loads(request.content) == {"expected_snapshot_digest": digest}
            published_at = "2026-11-16T10:00:00Z"
            return httpx.Response(
                200,
                json={
                    "run_id": run,
                    "published_at": published_at,
                    "snapshot_digest": digest,
                },
            )
        elif request.url.path == f"{path}/snapshot":
            return httpx.Response(
                200,
                json={
                    "run_id": run,
                    "status": status,
                    "digest": digest,
                    "net": "90.04",
                    "payslips_published_at": published_at,
                    "lines": [{}],
                    "period_start": "2025-01-01",
                    "period_end": "2025-01-31",
                },
            )
        elif request.url.path != path:
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "prepared_by_id": actor,
                "status": status,
                "snapshot_digest": digest if status != "draft" else None,
            },
        )

    def call(*args: str) -> tuple[int, dict]:
        out, err = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "payroll", *args, "--run-id", run, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=out,
            stderr=err,
        )
        assert not err.getvalue()
        return code, json.loads(out.getvalue())

    args: tuple[str, ...] = ("calculate", "--roster-file", str(roster))
    assert call(*args, "--time-sha256", checksums["time_sha256"], "--dry-run")[0] != 0
    args += ("--time-sha256", checksums["time_sha256"], "--leave-sha256", checksums["leave_sha256"])
    code, plan = call(*args, "--dry-run")
    assert code == 0 and status == "draft"
    code, result = call(*args, "--apply", "--expect", plan["data"]["plan_sha256"])
    assert code == 0 and result["data"]["snapshot_digest"] == digest
    code, plan = call("approve", "--dry-run")
    assert code == 0 and plan["data"]["snapshot"]["digest"] == digest
    assert call("approve", "--apply", "--expect", "0" * 64)[0] == 4
    code, result = call("approve", "--apply", "--expect", plan["data"]["plan_sha256"])
    assert code == 0 and result["data"]["status"] == "approved"

    code, plan = call("publish-payslips", "--dry-run")
    assert code == 0 and plan["data"]["employee_count"] == 1
    assert "net" not in plan["data"] and published_at is None
    code, result = call("publish-payslips", "--apply", "--expect", plan["data"]["plan_sha256"])
    assert code == 0 and result["data"]["payslips_published_at"] == published_at
    assert "net" not in result["data"]


def test_hr_payroll_export_cli_checks_exact_private_download(tmp_path, monkeypatch) -> None:
    import hashlib
    import stat

    from app.utils.permissions import PERMISSION_HR_PAYROLL_APPROVE, PERMISSION_HR_PAYROLL_SENSITIVE

    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-export-token")
    run = str(uuid4())
    actor = str(uuid4())
    ref = str(uuid4())
    csv_bytes = f"payment_reference,currency,net_amount\n{ref},LKR,90.04\n".encode()
    digest = hashlib.sha256(csv_bytes).hexdigest()
    snapshot = "a" * 64
    path = f"/api/v1/hr/payroll/runs/{run}/payment-export"
    receipt = None
    received_bytes = csv_bytes

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal receipt
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200,
                json={
                    "id": actor,
                    "role": "hr_manager",
                    "permissions": [PERMISSION_HR_PAYROLL_APPROVE, PERMISSION_HR_PAYROLL_SENSITIVE],
                },
            )
        if request.url.path == f"{path}/preview":
            return httpx.Response(
                200,
                json={
                    "run_id": run,
                    "snapshot_digest": snapshot,
                    "csv_sha256": digest,
                    "payment_count": 1,
                    "net": "90.04",
                    "receipt": receipt,
                },
            )
        if request.url.path == path and request.method == "POST":
            assert json.loads(request.content) == {
                "expected_snapshot_digest": snapshot,
                "expected_csv_sha256": digest,
            }
            receipt = {"run_id": run, "csv_sha256": digest}
            return httpx.Response(200, json=receipt)
        if request.url.path == path and request.method == "GET" and receipt:
            return httpx.Response(
                200,
                content=received_bytes,
                headers={"Content-Type": "text/csv", "X-Payroll-Export-SHA256": digest},
            )
        return httpx.Response(404)

    def call(action: str, *args: str) -> tuple[int, dict]:
        out, err = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "payroll", "payment-export", action, "--run-id", run, *args, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=out,
            stderr=err,
        )
        assert not err.getvalue()
        return code, json.loads(out.getvalue())

    code, preview = call("register", "--dry-run")
    assert code == 0 and receipt is None
    assert call("register", "--apply", "--expect", "0" * 64)[0] == 4
    code, saved = call("register", "--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and saved["data"]["csv_sha256"] == digest
    file = tmp_path / "approved-payroll.csv"
    args = ("--sha256", digest, "--output", str(file))
    received_bytes = b"tampered"
    assert call("download", *args)[0] == 4 and not file.exists()
    received_bytes = csv_bytes
    code, result = call("download", *args)
    assert code == 0 and result["data"]["csv_sha256"] == digest
    assert "90.04" not in json.dumps(result)
    assert file.read_bytes() == csv_bytes
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert call("download", *args)[0] != 0 and file.read_bytes() == csv_bytes


def test_hr_payroll_settlement_cli_binds_private_evidence_and_balance(
    tmp_path, monkeypatch
) -> None:
    from app.utils.permissions import PERMISSION_HR_PAYROLL_APPROVE, PERMISSION_HR_PAYROLL_SENSITIVE

    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-settlement-token")
    actor, run, payment, event_id = (str(uuid4()) for _ in range(4))
    digest = "a" * 64
    path = f"/api/v1/hr/payroll/runs/{run}/settlements"
    evidence = "Opaque-synthetic-evidence"
    event = {
        "event_id": event_id,
        "payment_reference": payment,
        "kind": "paid",
        "amount": "40.00",
        "occurred_on": "2025-02-01",
        "evidence_reference": evidence,
    }
    file = tmp_path / "settlement.json"
    file.write_text(json.dumps(event), encoding="utf-8")
    balance = "90.04"
    recorded = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal recorded
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200,
                json={
                    "id": actor,
                    "role": "hr_manager",
                    "permissions": [PERMISSION_HR_PAYROLL_APPROVE, PERMISSION_HR_PAYROLL_SENSITIVE],
                },
            )
        if request.url.path == path:
            return httpx.Response(
                200,
                json={
                    "run_id": run,
                    "csv_sha256": digest,
                    "payments": [{"payment_reference": payment, "outstanding": balance}],
                },
            )
        if request.url.path == f"{path}/events" and request.method == "POST":
            assert json.loads(request.content) == {
                **event,
                "expected_csv_sha256": digest,
                "reverses_event_id": None,
            }
            recorded = {
                "id": event_id,
                "recorded_at": "2026-11-16T10:00:00Z",
                "evidence_reference": evidence,
            }
            return httpx.Response(200, json=recorded)
        if request.url.path == f"{path}/events/{event_id}" and recorded:
            return httpx.Response(200, json=recorded)
        return httpx.Response(404)

    def call(*args: str) -> tuple[int, dict]:
        out, err = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [
                "hr",
                "payroll",
                "settlement",
                "record",
                "--run-id",
                run,
                "--event-file",
                str(file),
                *args,
                "--json",
            ],
            transport=httpx.MockTransport(handler),
            stdout=out,
            stderr=err,
        )
        assert not err.getvalue()
        return code, json.loads(out.getvalue())

    file.chmod(0o644)
    assert call("--dry-run")[0] != 0
    file.chmod(0o600)
    code, plan = call("--dry-run")
    assert code == 0 and recorded is None and evidence not in json.dumps(plan)
    original = plan["data"]["plan_sha256"]
    event["evidence_reference"] = "Changed-opaque-reference"
    file.write_text(json.dumps(event), encoding="utf-8")
    assert call("--apply", "--expect", original)[0] == 4 and recorded is None
    event["evidence_reference"] = evidence
    file.write_text(json.dumps(event), encoding="utf-8")
    balance = "50.04"
    assert call("--apply", "--expect", original)[0] == 4 and recorded is None
    code, plan = call("--dry-run")
    assert code == 0
    code, result = call("--apply", "--expect", plan["data"]["plan_sha256"])
    assert code == 0 and result["data"]["id"] == event_id
    assert evidence not in json.dumps(result)


@pytest.mark.parametrize(
    ("command", "route"),
    [
        (("attendance",), "attendance"),
        (("attendance", "corrections"), "attendance/corrections"),
        (("timesheets",), "timesheets"),
        (("overtime",), "overtime"),
    ],
)
def test_hr_time_cli_previews_private_input_and_binds_revision(
    tmp_path, monkeypatch, command: tuple[str, ...], route: str,
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-time-cli")
    employee, maker, reviewer, record = (str(uuid4()) for _ in range(4))
    actor = maker
    note = "SYNTHETIC PRIVATE HR TIME NOTE"
    path = f"/api/v1/hr/{route}"
    supports_revision = route != "attendance/corrections"
    input_fields: dict[str, dict[str, str | bool]] = {
        "attendance": {
            "work_date": "2025-06-03", "attendance_status": "present",
            "worked_hours": "7.50", "notes": note,
        },
        "attendance/corrections": {
            "work_date": "2025-06-03", "requested_status": "present",
            "requested_worked_hours": "7.50", "reason": note,
        },
        "timesheets": {
            "period_start": "2025-06-03", "period_end": "2025-06-05",
            "regular_hours": "23.00", "submit": True, "notes": note,
        },
        "overtime": {"work_date": "2025-06-03", "requested_hours": "2.00", "reason": note},
    }
    file = tmp_path / "private-time.json"
    file.write_text(json.dumps({"employee_id": employee, **input_fields[route]}), encoding="utf-8")
    file.chmod(0o600)
    row: dict[str, str | int] = {
        "id": record, "employee_id": employee, "status": "submitted", "notes": note,
    }
    if supports_revision:
        row["record_revision"] = 2
    written = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={
                "id": actor, "role": "hr_manager",
                "permissions": ["hr:attendance:record", "hr:attendance:approve"],
            })
        if request.url.path == path and request.method == "POST":
            payload = json.loads(request.content)
            assert payload["employee_id"] == employee and actor == maker
            assert note in payload.values()
            written.append("create")
            return httpx.Response(201, json=row)
        if request.url.path == f"{path}/{record}" and request.method == "GET":
            return httpx.Response(200, json=row)
        if request.url.path == f"{path}/{record}/decision" and request.method == "POST":
            payload = json.loads(request.content)
            assert actor == reviewer and payload["decision"] == "approved"
            if supports_revision:
                assert payload["expected_revision"] == row["record_revision"]
                row["record_revision"] = int(row["record_revision"]) + 1
            else:
                assert "expected_revision" not in payload
            row["status"] = "approved"
            written.append("decision")
            return httpx.Response(200, json=row)
        return httpx.Response(404)

    def call(*args: str) -> tuple[int, dict]:
        output = io.StringIO()
        status = garrisonctl.run(
            ["hr", *command, *args, "--file", str(file), "--json"],
            transport=httpx.MockTransport(handler), stdout=output, stderr=io.StringIO(),
        )
        return status, json.loads(output.getvalue())

    file.chmod(0o644)
    assert call("create", "--dry-run")[0] != 0
    file.chmod(0o600)
    status, draft = call("create", "--dry-run")
    assert status == 0 and not written and note not in json.dumps(draft)
    status, result = call("create", "--apply", "--expect", draft["data"]["plan_sha256"])
    assert status == 0 and result["data"]["status"] == "submitted"
    assert note not in json.dumps(result)

    actor = reviewer
    file.write_text(json.dumps({"decision": "approved"}), encoding="utf-8")
    decide = ("decide", "--record-id", record)
    status, draft = call(*decide, "--dry-run")
    assert status == 0 and note not in json.dumps(draft)
    if supports_revision:
        row["record_revision"] = int(row["record_revision"]) + 1
    else:
        row["notes"] = "Changed server record"
    assert call(*decide, "--apply", "--expect", draft["data"]["plan_sha256"])[0] == 4
    assert written == ["create"]
    status, draft = call(*decide, "--dry-run")
    assert status == 0
    status, result = call(*decide, "--apply", "--expect", draft["data"]["plan_sha256"])
    assert status == 0 and result["data"]["status"] == "approved"
    assert written == ["create", "decision"] and note not in json.dumps(result)


def test_hr_payroll_correction_cli_binds_private_proposal_and_independent_review(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-correction-token")
    maker, reviewer, run_id, line_id, correction_id = (str(uuid4()) for _ in range(5))
    actor_id = maker
    snapshot_digest = "a" * 64
    previous_id = None
    receipt = None
    path = f"/api/v1/hr/payroll/runs/{run_id}/lines/{line_id}/corrections"
    file = tmp_path / "correction.json"
    detail = {
        "correction_id": correction_id,
        "gross": "211.49",
        "deductions": "33.05",
        "evidence_reference": "PRIVATE-CLI-CORRECTION",
    }
    file.write_text(json.dumps(detail), encoding="utf-8")
    file.chmod(0o600)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal receipt
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={
                "id": actor_id, "role": "hr_manager",
                "permissions": [
                    "hr:payroll:prepare", "hr:payroll:approve", "hr:payroll:sensitive",
                ],
            })
        if request.url.path == f"/api/v1/hr/payroll/runs/{run_id}/snapshot":
            return httpx.Response(200, json={
                "run_id": run_id, "closed_at": "2026-11-16T10:00:00Z",
                "digest": snapshot_digest,
            })
        if request.url.path == path and request.method == "GET":
            return httpx.Response(200, json={
                "line_id": line_id, "current_correction_id": previous_id,
            })
        if request.url.path == path and request.method == "POST":
            assert actor_id == maker
            assert json.loads(request.content) == {
                **detail, "expected_snapshot_digest": snapshot_digest,
                "expected_previous_id": previous_id,
            }
            receipt = {
                "id": correction_id, "line_id": line_id, "previous_id": previous_id,
                "snapshot_digest": snapshot_digest, "digest": "b" * 64, "status": "submitted",
                "submitted_by_id": maker, "evidence_reference": detail["evidence_reference"],
            }
            return httpx.Response(200, json=receipt)
        if request.url.path == f"{path}/{correction_id}" and receipt:
            return httpx.Response(200, json=receipt)
        if request.url.path == f"{path}/{correction_id}/decision" and receipt:
            assert actor_id == reviewer
            assert json.loads(request.content) == {
                "decision": "approved", "expected_digest": receipt["digest"],
            }
            receipt["status"] = "approved"
            return httpx.Response(200, json=receipt)
        return httpx.Response(404)

    def call(*args: str) -> tuple[int, dict]:
        output = io.StringIO()
        status = garrisonctl.run(
            [
                "hr", "payroll", "correction", *args, "--run-id", run_id,
                "--line-id", line_id, "--json",
            ],
            transport=httpx.MockTransport(handler), stdout=output, stderr=io.StringIO(),
        )
        return status, json.loads(output.getvalue())

    def assert_private(result: dict) -> None:
        serialized = json.dumps(result)
        assert all(detail[key] not in serialized for key in (
            "gross", "deductions", "evidence_reference"
        ))

    proposal = ("propose", "--file", str(file))
    file.chmod(0o644)
    assert call(*proposal, "--dry-run")[0] != 0
    file.chmod(0o600)
    code, preview = call(*proposal, "--dry-run")
    assert code == 0 and receipt is None
    assert_private(preview)
    stale = preview["data"]["plan_sha256"]
    previous_id = str(uuid4())
    assert call(*proposal, "--apply", "--expect", stale)[0] == 4
    assert receipt is None
    code, preview = call(*proposal, "--dry-run")
    assert code == 0
    code, result = call(*proposal, "--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and result["data"]["status"] == "submitted"
    assert_private(result)
    approval = (
        "decide", "--correction-id", correction_id, "--decision", "approved", "--digest", "b" * 64,
    )
    assert call(*approval, "--dry-run")[0] == 4
    actor_id = reviewer
    code, preview = call(*approval, "--dry-run")
    assert code == 0
    assert_private(preview)
    assert call(*approval, "--apply", "--expect", stale)[0] == 4
    code, result = call(*approval, "--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and result["data"]["status"] == "approved"
    assert_private(result)


def test_hr_payroll_close_cli_verifies_reviewed_settlement(monkeypatch) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-closure-token")
    actor_id, run_id = str(uuid4()), str(uuid4())
    path = f"/api/v1/hr/payroll/runs/{run_id}"
    settlement_digest = "c" * 64
    receipt: dict | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal receipt
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={
                "id": actor_id, "role": "hr_manager",
                "permissions": ["hr:payroll:approve", "hr:payroll:sensitive"],
            })
        if request.url.path == f"{path}/snapshot":
            return httpx.Response(200, json={
                "run_id": run_id, "status": "approved", "digest": "a" * 64,
                "payslips_published_at": "2026-11-16T10:00:00Z",
                "lines": [{"net": "synthetic-private-line"}],
            })
        if request.url.path == f"{path}/settlements":
            return httpx.Response(200, json={
                "run_id": run_id, "csv_sha256": "b" * 64,
                "settlement_digest": settlement_digest,
                "fully_reconciled": True, "closure": receipt,
            })
        assert request.url.path == f"{path}/close" and request.method == "POST"
        assert json.loads(request.content) == {
            "expected_snapshot_digest": "a" * 64,
            "expected_csv_sha256": "b" * 64,
            "expected_settlement_digest": settlement_digest,
        }
        receipt = {
            "run_id": run_id, "closed_by_id": actor_id,
            "closed_at": "2026-11-16T10:05:00Z", "settlement_digest": settlement_digest,
        }
        return httpx.Response(200, json=receipt)

    def call(*args: str) -> tuple[int, dict]:
        output = io.StringIO()
        status = garrisonctl.run(
            ["hr", "payroll", "close", "--run-id", run_id, *args, "--json"],
            transport=httpx.MockTransport(handler), stdout=output, stderr=io.StringIO(),
        )
        return status, json.loads(output.getvalue())

    code, preview = call("--dry-run")
    assert code == 0 and receipt is None and "synthetic-private-line" not in json.dumps(preview)
    settlement_digest = "d" * 64
    assert call("--apply", "--expect", preview["data"]["plan_sha256"])[0] == 4
    assert receipt is None
    code, preview = call("--dry-run")
    assert code == 0
    code, result = call("--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and result["data"] == receipt


@pytest.mark.parametrize("area", ["store_inventory", "it_admin"])
def test_hr_offboarding_custody_cli_previews_and_verifies_exact_event(
    monkeypatch, area: str
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-custody-token")
    actor, case, event_id = (str(uuid4()) for _ in range(3))
    path = f"/api/v1/hr/offboarding/{case}/custody"
    receipt = {"id": event_id, "kind": "cleared", "evidence_reference": "STORE-CLI-1"}
    clearance_status = "pending"
    writes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200,
                json={
                    "id": actor,
                    "role": "managing_director",
                    "permissions": ["users:manage" if area == "it_admin" else "inventory:manage"],
                },
            )
        assert request.url.path == path
        if request.method == "POST":
            assert json.loads(request.content) == {
                "event_id": event_id,
                "area": area,
                "kind": "cleared",
                "device_reference": None,
                "movement_id": None,
                "evidence_reference": "STORE-CLI-1",
            }
            writes.append(event_id)
            return httpx.Response(200, json=receipt)
        assert request.url.params["area"] == area
        if writes:
            assert request.url.params["event_id"] == event_id
        return httpx.Response(
            200,
            json={
                "items": [receipt] if writes else [],
                "clearance_status": clearance_status,
                "case_closed": False,
                "outstanding_devices": 0,
                "total": len(writes),
            },
        )

    def call(*flags: str) -> tuple[int, dict]:
        out, err = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [
                "hr",
                "offboarding",
                "custody",
                "record",
                "--case-id",
                case,
                "--event-id",
                event_id,
                "--kind",
                "cleared",
                "--area",
                area,
                "--evidence-reference",
                "STORE-CLI-1",
                *flags,
                "--json",
            ],
            transport=httpx.MockTransport(handler),
            stdout=out,
            stderr=err,
        )
        assert not err.getvalue()
        return code, json.loads(out.getvalue())

    code, plan = call("--dry-run")
    assert code == 0 and writes == []
    clearance_status = "flagged"
    assert call("--apply", "--expect", plan["data"]["plan_sha256"])[0] == 4
    assert writes == []
    code, plan = call("--dry-run")
    assert code == 0
    code, result = call("--apply", "--expect", plan["data"]["plan_sha256"])
    assert code == 0 and result["data"] == [receipt]
    assert writes == [event_id]


def test_hr_separation_settlement_cli_previews_and_reads_back(monkeypatch) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    actor, reviewer, case, event_id = (str(uuid4()) for _ in range(4))
    path = f"/api/v1/hr/offboarding/{case}/settlement"
    record: dict | None = None
    status = "pending"
    writes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal record, status
        token = request.headers["authorization"]
        caller = actor if token == "Bearer synthetic-proposer-token" else reviewer
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200,
                json={
                    "id": caller,
                    "role": "managing_director",
                    "permissions": ["users:manage", "financial:view"],
                },
            )
        if request.method == "GET" and request.url.path == path:
            return httpx.Response(
                200,
                json={
                    "items": [record] if record else [],
                    "total": int(record is not None),
                    "case_closed": False,
                    "clearance_status": status,
                    "current_record_id": event_id if record else None,
                },
            )
        if request.method == "POST" and request.url.path == path:
            assert record is None and caller == actor
            assert json.loads(request.content) == {
                "event_id": event_id,
                "expected_record_id": None,
                "outcome": "nothing_due",
                "evidence_reference": "FIN-CLI-1",
            }
            record = {"id": event_id, "status": "proposed", "proposed_by_id": caller}
            writes.append("propose")
            return httpx.Response(200, json=record)
        assert request.method == "POST" and request.url.path == f"{path}/{event_id}/review"
        assert record is not None and caller == reviewer
        assert json.loads(request.content) == {
            "decision": "approved",
            "evidence_reference": "FIN-CLI-2",
        }
        record = {**record, "status": "approved", "reviewed_by_id": caller}
        status = "cleared"
        writes.append("review")
        return httpx.Response(200, json=record)

    def call(actor_id: str, action: str, *flags: str) -> tuple[int, dict]:
        monkeypatch.setenv(
            "GARRISON_ACCESS_TOKEN",
            "synthetic-proposer-token" if actor_id == actor else "synthetic-reviewer-token",
        )
        evidence = "FIN-CLI-1" if action == "propose" else "FIN-CLI-2"
        choice = ["--outcome", "nothing_due"] if action == "propose" else ["--decision", "approved"]
        out, err = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [
                "hr",
                "offboarding",
                "settlement",
                action,
                "--case-id",
                case,
                "--event-id",
                event_id,
                "--evidence-reference",
                evidence,
                *choice,
                *flags,
                "--json",
            ],
            transport=httpx.MockTransport(handler),
            stdout=out,
            stderr=err,
        )
        assert not err.getvalue()
        return code, json.loads(out.getvalue())

    code, plan = call(actor, "propose", "--dry-run")
    assert code == 0 and writes == []
    status = "flagged"
    assert call(actor, "propose", "--apply", "--expect", plan["data"]["plan_sha256"])[0] == 4
    status = "pending"
    assert call(actor, "propose", "--apply", "--expect", plan["data"]["plan_sha256"])[0] == 0
    assert call(actor, "review", "--dry-run")[0] != 0
    assert writes == ["propose"]
    code, plan = call(reviewer, "review", "--dry-run")
    assert code == 0 and writes == ["propose"]
    code, receipt = call(reviewer, "review", "--apply", "--expect", plan["data"]["plan_sha256"])
    assert code == 0 and receipt["data"] == [record] and writes == ["propose", "review"]


@pytest.mark.asyncio
async def test_hr_training_completion_binds_approved_evidence_and_prevents_duplicates() -> None:
    await skip_if_database_unavailable()
    _, hr_email, pw = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", pw)
    staff_id, staff_email, _ = await _create_portal_user("quantity_surveyor", pw)
    other_staff_id, other_staff_email, _ = await _create_portal_user("site_supervisor", pw)
    _, director_email, _ = await _create_portal_user("managing_director", pw)
    today = business_today()
    completed = today - timedelta(days=2)
    expires = today - timedelta(days=1)
    base = "/api/v1/hr"

    async with _client() as client:
        hr = _auth(await _login(client, hr_email, pw))
        reviewer = _auth(await _login(client, reviewer_email, pw))
        staff = _auth(await _login(client, staff_email, pw))
        other_staff = _auth(await _login(client, other_staff_email, pw))
        director = _auth(await _login(client, director_email, pw))

        position = await client.post(
            f"{base}/positions",
            headers=hr,
            json={"code": f"TRP-{uuid4().hex[:8]}", "title": "Safety trainee"},
        )
        assert position.status_code == 201, position.text
        position_id = position.json()["id"]
        async with AsyncSessionLocal() as db:
            site = Project(
                name="Training site",
                code=f"TRS-{uuid4().hex[:8]}",
                scope_of_work="Synthetic",
                target_end_date=today + timedelta(days=90),
            )
            db.add(site)
            await db.flush()
            site_id = str(site.id)
            await db.commit()

        async def create_employee(email: str) -> str:
            response = await client.post(
                f"{base}/employees",
                headers=hr,
                json={
                    "employee_code": f"TRAIN-{uuid4().hex[:8]}",
                    "first_name": "Synthetic",
                    "last_name": "Trainee",
                    "work_email": email,
                    "position_id": position_id if email == staff_email else None,
                    "primary_project_id": site_id if email == staff_email else None,
                    "employment_status": "active",
                },
            )
            assert response.status_code == 201, response.text
            return response.json()["id"]

        assert (await client.get(f"{base}/me/training", headers=staff)).status_code == 404
        employee = await create_employee(staff_email)
        other_employee = await create_employee(other_staff_email)
        for emp_id, user_id in ((employee, staff_id), (other_employee, other_staff_id)):
            link = await client.post(
                f"{base}/employees/{emp_id}/link-account",
                headers=director,
                json={"user_id": user_id},
            )
            assert link.status_code == 200, link.text
        course = await client.post(
            f"{base}/training/courses",
            headers=hr,
            json={
                "code": f"IND-{uuid4().hex[:8]}",
                "title": "Safety induction",
                "is_mandatory": True,
            },
        )
        assert course.status_code == 201, course.text
        rules = f"{base}/training/requirements"
        self_requirements = f"{base}/me/training/requirements"
        course_id = course.json()["id"]
        scoped = {"course_id": course_id, "position_id": position_id, "project_id": site_id}
        assert (await client.post(rules, headers=staff, json=scoped)).status_code == 403
        assert (
            await client.post(rules, headers=hr, json={"course_id": course_id})
        ).status_code == 422
        assert (
            await client.post(rules, headers=hr, json={**scoped, "project_id": str(uuid4())})
        ).status_code == 404
        created_rule = await client.post(rules, headers=hr, json=scoped)
        assert created_rule.status_code == 200, created_rule.text
        repeat = await client.post(rules, headers=hr, json=scoped)
        assert repeat.json() == created_rule.json()
        async with AsyncSessionLocal() as db:
            outsider = await db.get(HrEmployee, UUID(other_employee))
            assert outsider is not None
            outsider.primary_project_id = UUID(site_id)
            await db.commit()
        assert (await client.get(self_requirements, headers=other_staff)).json() == {
            "items": [],
            "total": 0,
        }
        async with AsyncSessionLocal() as db:
            outsider = await db.get(HrEmployee, UUID(other_employee))
            assert outsider is not None
            outsider.primary_project_id = None
            await db.commit()
        position_payload = {"course_id": course_id, "position_id": position_id}
        position_rule, duplicate_position = await asyncio.gather(
            *(client.post(rules, headers=hr, json=position_payload) for _ in range(2))
        )
        assert position_rule.status_code == 200, position_rule.text
        assert duplicate_position.json() == position_rule.json()
        site_rule = await client.post(
            rules, headers=hr, json={"course_id": course_id, "project_id": site_id}
        )
        assert site_rule.status_code == 200, site_rule.text
        assert (await client.get(rules, headers=hr)).json()["total"] == 3

        async def require_state(expected: str) -> None:
            result = await client.get(self_requirements, headers=staff)
            assert result.status_code == 200, result.text
            assert result.json() == {
                "items": [
                    {"course_id": course_id, "course_title": "Safety induction", "status": expected}
                ],
                "total": 1,
            }

        await require_state("required")
        assert (await client.get(self_requirements, headers=other_staff)).json() == {
            "items": [],
            "total": 0,
        }
        enrollments = f"{base}/training/enrollments"
        assignment = {
            "employee_id": employee,
            "course_id": course.json()["id"],
            "scheduled_date": completed.isoformat(),
        }
        opened = await client.post(enrollments, headers=hr, json=assignment)
        assert opened.status_code == 201, opened.text
        assert (await client.post(enrollments, headers=hr, json=assignment)).status_code == 409
        enrollment = opened.json()["id"]
        await require_state("enrolled")
        endpoint = f"{enrollments}/{enrollment}"
        progress = {"status": "in_progress", "expected_status": "enrolled"}
        assert (await client.patch(endpoint, headers=staff, json=progress)).status_code == 403
        in_progress = await client.patch(endpoint, headers=hr, json=progress)
        assert in_progress.status_code == 200
        assert in_progress.json()["status"] == "in_progress"
        stale_cancel = await client.patch(
            endpoint, headers=reviewer, json={"status": "cancelled", "expected_status": "enrolled"}
        )
        assert stale_cancel.status_code == 409
        assert (
            await client.patch(endpoint, headers=hr, json={"status": "completed"})
        ).status_code == 409
        assert (await client.get(f"{endpoint}/completion", headers=staff)).status_code == 403

        async def upload(employee_id: str, label: str, expiry: date = expires) -> str:
            response = await client.post(
                f"{base}/documents",
                headers=hr,
                files={"file": ("training.pdf", _pdf_bytes(label), "application/pdf")},
                data={
                    "employee_id": employee_id,
                    "title": f"Synthetic {label}",
                    "document_type": "training_certificate",
                    "category": "ordinary",
                    "issue_date": completed.isoformat(),
                    "expiry_date": expiry.isoformat(),
                },
            )
            assert response.status_code == 201, response.text
            return response.json()["id"]

        evidence = await upload(employee, "induction")
        other_evidence = await upload(other_employee, "other employee")
        payload = {
            "document_id": evidence,
            "version_number": 1,
            "completed_date": completed.isoformat(),
            "score": "97.50",
        }
        verify = f"{endpoint}/completion"
        assert (await client.post(verify, headers=staff, json=payload)).status_code == 403
        assert (await client.post(verify, headers=hr, json=payload)).status_code == 409
        assert (
            await client.post(verify, headers=hr, json={**payload, "document_id": other_evidence})
        ).status_code == 404

        approval = f"{base}/documents/{evidence}/versions/1/decision"
        assert (
            await client.post(approval, headers=hr, json={"decision": "approve"})
        ).status_code == 403
        approved = await client.post(approval, headers=reviewer, json={"decision": "approve"})
        assert approved.status_code == 200, approved.text
        assert (
            await client.post(
                f"{base}/certifications",
                headers=hr,
                json={"employee_id": employee, "name": "Bypass", "document_id": evidence},
            )
        ).status_code == 409
        assert (
            await client.post(
                verify,
                headers=hr,
                json={**payload, "completed_date": (today + timedelta(days=1)).isoformat()},
            )
        ).status_code == 422

        calls = await asyncio.gather(
            *(client.post(verify, headers=hr, json=payload) for _ in range(2))
        )
        assert all(response.status_code == 200 for response in calls)
        receipt = calls[0].json()
        assert calls[1].json() == receipt
        assert (
            await client.post(verify, headers=hr, json={**payload, "score": "99"})
        ).status_code == 409
        assert (
            await client.patch(endpoint, headers=hr, json={"status": "enrolled"})
        ).status_code == 409

        certs = await client.get(
            f"{base}/certifications", headers=hr, params={"employee_id": employee}
        )
        assert certs.status_code == 200, certs.text
        assert certs.json()["total"] == 1
        certificate = certs.json()["items"][0]
        assert certificate["id"] == receipt["certificate_id"]
        assert certificate["effective_status"] == "expired"
        await require_state("expired")
        mine = await client.get(f"{base}/me/training", headers=staff)
        assert mine.status_code == 200, mine.text
        assert mine.json() == {
            "items": [
                {
                    "enrollment_id": enrollment,
                    "course_title": "Safety induction",
                    "status": "completed",
                    "scheduled_date": completed.isoformat(),
                    "completed_date": completed.isoformat(),
                    "verified": True,
                    "certificate_expiry": expires.isoformat(),
                    "certificate_expired": True,
                }
            ],
            "total": 1,
        }
        other = await client.get(f"{base}/me/training", headers=other_staff)
        assert other.status_code == 200 and other.json() == {"items": [], "total": 0}

        from app.services.hr_reporting import HrReportWindow, count_report_credentials

        async with AsyncSessionLocal() as session:
            selected_employee = select(HrEmployee.id).where(HrEmployee.id == UUID(employee))
            assert (
                await count_report_credentials(
                    session, selected_employee, HrReportWindow(date_from=expires, date_to=expires)
                )
                == 1
            )

        next_enrollment = await client.post(enrollments, headers=hr, json=assignment)
        assert next_enrollment.status_code == 201, next_enrollment.text
        renew = f"{enrollments}/{next_enrollment.json()['id']}/completion"
        assert (await client.post(renew, headers=hr, json=payload)).status_code == 409
        replacement = await client.post(
            f"{base}/documents/{evidence}/versions",
            headers=hr,
            files={"file": ("replacement.pdf", _pdf_bytes("replacement"), "application/pdf")},
        )
        assert replacement.status_code in {200, 201}, replacement.text
        new_version = await client.post(
            f"{base}/documents/{evidence}/versions/2/decision",
            headers=reviewer,
            json={"decision": "approve"},
        )
        assert new_version.status_code == 200, new_version.text
        assert (await client.get(verify, headers=hr)).json() == receipt
        assert (await client.post(renew, headers=hr, json=payload)).status_code == 409
        renewed_evidence = await upload(employee, "renewed induction", today + timedelta(days=30))
        approved_renewal = await client.post(
            f"{base}/documents/{renewed_evidence}/versions/1/decision",
            headers=reviewer,
            json={"decision": "approve"},
        )
        assert approved_renewal.status_code == 200, approved_renewal.text
        renewal = await client.post(
            renew, headers=hr, json={**payload, "document_id": renewed_evidence}
        )
        assert renewal.status_code == 200, renewal.text
        assert renewal.json()["certificate_id"] != receipt["certificate_id"]
        assert (await client.get(verify, headers=hr)).json() == receipt

        extra = await client.post(enrollments, headers=hr, json=assignment)
        assert extra.status_code == 201
        extra_path = f"{enrollments}/{extra.json()['id']}"
        cancelled = await client.patch(
            extra_path, headers=hr, json={"status": "cancelled", "expected_status": "enrolled"}
        )
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        assert (await client.patch(extra_path, headers=hr, json=progress)).status_code == 409
        assert (await client.post(enrollments, headers=hr, json=assignment)).status_code == 201

        await require_state("met")
        for rule in (created_rule, position_rule, site_rule):
            disabled = await client.delete(f"{rules}/{rule.json()['id']}", headers=hr)
            assert disabled.status_code == 204
        assert (await client.get(self_requirements, headers=staff)).json() == {
            "items": [],
            "total": 0,
        }
        restored = await client.post(rules, headers=hr, json=scoped)
        assert restored.json() == created_rule.json()
        await require_state("met")


@pytest.mark.asyncio
@pytest.mark.parametrize("rated", [False, True])
async def test_hr_performance_review_participants_and_immutable_final_history(rated: bool) -> None:
    await skip_if_database_unavailable()
    _, hr_email, pw = await _create_portal_user("hr_manager")
    employee_user, employee_email, _ = await _create_portal_user("quantity_surveyor", pw)
    manager_user, manager_email, _ = await _create_portal_user("group_project_manager", pw)
    outsider_user, outsider_email, _ = await _create_portal_user("group_project_manager", pw)
    _, director_email, _ = await _create_portal_user("managing_director", pw)
    base = "/api/v1/hr"

    async with _client() as client:
        hr = _auth(await _login(client, hr_email, pw))
        own = _auth(await _login(client, employee_email, pw))
        manager = _auth(await _login(client, manager_email, pw))
        outsider = _auth(await _login(client, outsider_email, pw))
        director = _auth(await _login(client, director_email, pw))

        async def linked(user: str, email: str, name: str, reporting_to: str | None = None) -> dict:
            row = await client.post(
                f"{base}/employees",
                headers=hr,
                json={
                    "employee_code": f"PERF-{uuid4().hex[:6]}",
                    "first_name": "Synthetic",
                    "last_name": name,
                    "work_email": email,
                    "employment_status": "active",
                    "manager_employee_id": reporting_to,
                },
            )
            assert row.status_code == 201, row.text
            employee_id = row.json()["id"]
            result = await client.post(
                f"{base}/employees/{employee_id}/link-account",
                headers=director,
                json={"user_id": user},
            )
            assert result.status_code == 200, result.text
            return (await client.get(f"{base}/employees/{employee_id}", headers=hr)).json()

        lead = await linked(manager_user, manager_email, "Lead")
        employee = await linked(employee_user, employee_email, "Employee", lead["id"])
        employee_path = f"{base}/employees/{employee['id']}"
        authorized = await client.put(
            f"{employee_path}/manager-review",
            headers=hr,
            json={"enabled": True, "expected_revision": employee["record_revision"]},
        )
        assert authorized.status_code == 200, authorized.text

        cycle_payload = {
            "code": f"PERF-{uuid4().hex[:6]}",
            "name": "Synthetic Review Cycle",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "rating_scale": ["Developing", "Established", "Advanced"] if rated else [],
        }
        assert (
            await client.post(f"{base}/review-cycles", headers=manager, json=cycle_payload)
        ).status_code == 403
        reversed_cycle = {**cycle_payload, "end_date": "2025-12-31"}
        assert (
            await client.post(f"{base}/review-cycles", headers=hr, json=reversed_cycle)
        ).status_code == 422
        duplicate_labels = {**cycle_payload, "rating_scale": ["Developing", " developing "]}
        assert (
            await client.post(f"{base}/review-cycles", headers=hr, json=duplicate_labels)
        ).status_code == 422
        cycle = await client.post(f"{base}/review-cycles", headers=hr, json=cycle_payload)
        assert cycle.status_code == 201, cycle.text
        assert cycle.json()["rating_scale"] == cycle_payload["rating_scale"]
        draft = {"employee_id": employee["id"], "cycle_id": cycle.json()["id"]}
        assert (
            await client.post(f"{base}/reviews", headers=hr, json={**draft, "status": "closed"})
        ).status_code == 422
        assert (
            await client.post(f"{base}/reviews", headers=hr, json={**draft, "final_rating": "4.25"})
        ).status_code == 422
        assert (await client.post(f"{base}/reviews", headers=hr, json=draft)).status_code == 409
        goal_payload = {
            "employee_id": employee["id"],
            "cycle_name": cycle_payload["code"],
            "title": "Complete the fixture review",
        }
        goal = await client.post(f"{base}/goals", headers=hr, json=goal_payload)
        assert goal.status_code == 201, goal.text
        opened = await client.post(f"{base}/reviews", headers=hr, json=draft)
        assert opened.status_code == 201, opened.text
        assert (await client.post(f"{base}/reviews", headers=hr, json=draft)).status_code == 409
        assert (
            await client.post(f"{base}/goals", headers=hr, json=goal_payload)
        ).status_code == 409
        assert (
            await client.patch(
                f"{base}/goals/{goal.json()['id']}", headers=hr, json={"progress_percent": 80}
            )
        ).status_code == 409

        queue = f"{base}/performance/reviews"
        review_id = opened.json()["id"]
        detail = f"{queue}/{review_id}"
        assert (await client.get(detail, headers=outsider)).status_code == 404
        assert (await client.get(queue, headers=outsider)).json() == {"items": [], "total": 0}
        assert (await client.get(queue, headers=manager)).json()["items"][0][
            "participant"
        ] == "manager"
        assert (await client.get(queue, headers=own)).json()["items"][0][
            "participant"
        ] == "employee"
        assert (await client.get(detail, headers=own)).headers["cache-control"] == "no-store"

        def event(action: str, revision: int, notes: str | None = None) -> dict:
            return {
                "event_id": str(uuid4()),
                "expected_revision": revision,
                "action": action,
                "notes": notes,
            }

        async def post(headers: dict, payload: dict, status: int = 200):
            result = await client.post(f"{detail}/actions", headers=headers, json=payload)
            assert result.status_code == status, result.text
            return result

        await post(outsider, event("acknowledge_goals", 0), 404)
        await post(hr, event("calibrate", 0, "invalid stage"), 403)
        first = event("acknowledge_goals", 0)
        ack = await post(own, first)
        replay = await post(own, first)
        assert ack.json() == replay.json()
        await post(own, event("acknowledge_goals", 1), 403)
        await post(manager, event("acknowledge_goals", 0), 409)
        await post(manager, event("acknowledge_goals", 1))
        await post(own, event("record_progress", 2, "Mid-cycle fixture"))
        self_review = event("submit_self_review", 3, "Self-review fixture")
        if rated:
            await post(own, self_review, 422)
            await post(own, {**self_review, "rating": "Arbitrary"}, 422)
            self_review["rating"] = "Developing"
        else:
            await post(own, {**self_review, "rating": "Arbitrary"}, 422)
        await post(own, self_review)
        first_manager_review = event("submit_manager_review", 4, "Unpublished manager fixture")
        if rated:
            first_manager_review["rating"] = "Established"
        await post(manager, first_manager_review)
        pre_calibration = (await client.get(detail, headers=own)).json()
        assert pre_calibration["status"] == "manager_reviewed"
        assert "Unpublished manager fixture" not in json.dumps(pre_calibration)
        assert not any(
            row["action"] == "submit_manager_review" for row in pre_calibration["events"]
        )

        revision = 5
        final_manager = manager
        assessment = "Unpublished manager fixture"
        if rated:
            successor = await linked(outsider_user, outsider_email, "Successor")
            before = (await client.get(employee_path, headers=hr)).json()
            moved = await client.patch(
                employee_path,
                headers=hr,
                json={
                    "manager_employee_id": successor["id"],
                    "expected_revision": before["record_revision"],
                },
            )
            assert moved.status_code == 200, moved.text
            await post(
                hr,
                {**event("calibrate", revision, "Former manager assessment"), "rating": "Advanced"},
                403,
            )
            enabled = await client.put(
                f"{employee_path}/manager-review",
                headers=hr,
                json={"enabled": True, "expected_revision": moved.json()["record_revision"]},
            )
            assert enabled.status_code == 200, enabled.text
            assert (await client.get(detail, headers=manager)).status_code == 404
            assert (await client.get(detail, headers=outsider)).status_code == 404
            candidate = (await client.get(detail, headers=hr)).json()
            assert candidate["allowed_actions"] == ["reassign_manager"]
            assert candidate["replacement_reviewer_id"] == successor["id"]
            handoff = {
                **event("reassign_manager", revision, "Authorized reporting change"),
                "replacement_reviewer_id": successor["id"],
            }
            await post(hr, {**handoff, "replacement_reviewer_id": lead["id"]}, 409)
            assigned = await post(hr, handoff)
            assert assigned.json()["events"][-1]["previous_reviewer_id"] == lead["id"]
            assert assigned.json()["events"][-1]["replacement_reviewer_id"] == successor["id"]
            assert (await post(hr, handoff)).json() == assigned.json()
            revision += 1
            assert (await client.get(detail, headers=manager)).status_code == 404
            incoming = (await client.get(detail, headers=outsider)).json()
            assert incoming["allowed_actions"] == ["acknowledge_goals"]
            assert "Unpublished manager fixture" not in json.dumps(incoming)
            await post(outsider, event("acknowledge_goals", revision))
            revision += 1
            assessment = "Replacement assessment"
            updated = await post(
                outsider,
                {**event("submit_manager_review", revision, assessment), "rating": "Advanced"},
            )
            assert updated.json()["status"] == "manager_reviewed"
            revision += 1
            final_manager = outsider

        calibration = event("calibrate", revision, "Calibrated fixture")
        if rated:
            await post(hr, {**calibration, "rating": "9.99"}, 422)
            calibration["rating"] = "Advanced"
        await post(hr, calibration)
        revision += 1
        published = (await client.get(detail, headers=own)).json()
        assert assessment in json.dumps(published)
        if rated:
            assert "Unpublished manager fixture" not in json.dumps(published)
            assert published["events"][-1]["rating"] == "Advanced"
        closed = await post(own, event("acknowledge_final", revision))
        assert closed.json()["status"] == "closed"
        revision += 1
        await post(
            final_manager, event("submit_manager_review", revision, "Write after close"), 403
        )
        retained = (await client.get(detail, headers=hr)).json()
        corrected = await post(hr, event("add_addendum", revision, "Correction fixture"))
        assert corrected.json()["events"][:-1] == retained["events"]
        assert corrected.json()["status"] == "closed"
        revision += 1
        await post(hr, event("calibrate", revision, "Rewrite final decision"), 403)
        assert (await client.get(detail, headers=own)).json()["events"][-1][
            "notes"
        ] == "Correction fixture"

        current = (await client.get(employee_path, headers=hr)).json()
        revoked = await client.put(
            f"{employee_path}/manager-review",
            headers=hr,
            json={"enabled": False, "expected_revision": current["record_revision"]},
        )
        assert revoked.status_code == 200, revoked.text
        assert (await client.get(detail, headers=final_manager)).status_code == 404
        assert (await client.get(queue, headers=final_manager)).json()["total"] == 0


@pytest.mark.asyncio
async def test_hr_roster_serializes_overnight_overlaps_and_preserves_attendance() -> None:
    await skip_if_database_unavailable()
    _, hr_email, password = await _create_portal_user("hr_manager")
    staff_id, staff_email, _ = await _create_portal_user("quantity_surveyor", password)
    monday, tuesday = date(2027, 1, 4), date(2027, 1, 5)
    async with AsyncSessionLocal() as session:
        site, other = [
            Project(
                name=name,
                code=f"HR-{uuid4().hex[:10]}",
                scope_of_work="Test scheduling",
                target_end_date=date(2027, 12, 31),
            )
            for name in ("Synthetic base site", "Synthetic allocation site")
        ]
        session.add_all([site, other])
        await session.flush()
        employee = HrEmployee(
            user_id=staff_id,
            employee_code=f"ROSTER-{uuid4().hex[:8]}",
            first_name="Synthetic",
            last_name="Roster",
            full_name="Synthetic Roster",
            primary_project_id=site.id,
            employment_status="active",
            join_date=date(2026, 1, 1),
        )
        calendar = HrWorkCalendar(
            code=f"ROSTER-{uuid4().hex[:8]}",
            name="Synthetic overnight calendar",
            project_id=site.id,
            work_days_json=["MON", "TUE"],
            standard_start_time=time(7),
            standard_end_time=time(16),
            daily_hours=Decimal("7.50"),
            effective_from=monday,
            effective_to=date(2027, 1, 6),
            timezone="Asia/Colombo",
            status="published",
        )
        session.add_all([employee, calendar])
        await session.flush()
        shift = HrShiftAssignment(
            employee_id=employee.id,
            calendar_id=calendar.id,
            shift_name="Night shift",
            effective_from=monday,
            effective_to=monday,
            start_time=time(22),
            end_time=time(8),
        )
        session.add(shift)
        await session.flush()
        employee_id, other_id, calendar_id, shift_id = (
            employee.id,
            other.id,
            calendar.id,
            shift.id,
        )
        stock_before = list(
            await session.execute(
                select(
                    InventoryLocationStock.id,
                    InventoryLocationStock.on_hand_qty,
                    InventoryLocationStock.reserved_qty,
                ).order_by(InventoryLocationStock.id)
            )
        )
        await session.commit()

    url = "/api/v1/hr/roster"
    payload = {
        "employee_id": str(employee_id),
        "project_id": str(other_id),
        "work_date": monday.isoformat(),
    }
    params = {"date_from": monday.isoformat(), "date_to": tuesday.isoformat()}
    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        staff = _auth(await _login(client, staff_email, password))
        attempts = [{**payload, "id": str(uuid4())} for _ in range(2)]
        assert (await client.get(url, headers=staff, params=params)).status_code == 403
        assert (await client.post(url, headers=staff, json=attempts[0])).status_code == 403
        responses = await asyncio.gather(
            *(client.post(url, headers=hr, json=attempt) for attempt in attempts)
        )
        assert sorted(response.status_code for response in responses) == [201, 409], [
            response.text for response in responses
        ]
        winner = next(response.json() for response in responses if response.status_code == 201)
        assert winner["shift_id"] == str(shift_id)
        assert winner["calendar_id"] == str(calendar_id)
        assert Decimal(winner["planned_hours"]) == Decimal("10")
        assert datetime.fromisoformat(winner["ends_at"]) == datetime(2027, 1, 5, 2, 30, tzinfo=UTC)
        detail_url = f"{url}/{winner['id']}"
        detail = await client.get(detail_url, headers=hr)
        assert detail.status_code == 200 and detail.json() == winner
        assert detail.headers["Cache-Control"] == "no-store"
        assert (await client.get(detail_url, headers=staff)).status_code == 403
        assert (await client.get(f"{url}/{uuid4()}", headers=hr)).status_code == 404
        retry = await client.post(url, headers=hr, json={**payload, "id": winner["id"]})
        assert retry.status_code == 201 and retry.json() == winner

        next_day = {**payload, "id": str(uuid4()), "work_date": tuesday.isoformat()}
        assert (await client.post(url, headers=hr, json=next_day)).status_code == 409
        cancel_url = f"{url}/{winner['id']}/cancel"
        assert (
            await client.post(cancel_url, headers=staff, json={"reason": "Denied"})
        ).status_code == 403
        cancellation = {"reason": "  Replacement planned  "}
        cancelled = await client.post(cancel_url, headers=hr, json=cancellation)
        assert cancelled.status_code == 200
        assert cancelled.json()["cancellation_reason"] == "Replacement planned"
        cancelled_detail = await client.get(detail_url, headers=hr)
        assert cancelled_detail.status_code == 200 and cancelled_detail.json() == cancelled.json()
        replay = await client.post(cancel_url, headers=hr, json=cancellation)
        assert replay.json() == cancelled.json()

        day = await client.post(url, headers=hr, json=next_day)
        assert day.status_code == 201, day.text
        assert day.json()["shift_id"] is None
        assert Decimal(day.json()["planned_hours"]) == Decimal("7.50")
        listed = await client.get(url, headers=hr, params={**params, "project_id": str(other_id)})
        assert listed.status_code == 200
        assert listed.json()["items"] == [cancelled.json(), day.json()]
        assert listed.json()["total"] == 2
        assert (
            await client.get(url, headers=hr, params={**params, "date_to": "2027-02-04"})
        ).status_code == 422
        assert (
            await client.post(
                url, headers=hr, json={**next_day, "id": str(uuid4()), "work_date": "2027-01-06"}
            )
        ).status_code == 409

    async with AsyncSessionLocal() as session:
        assert not await session.scalar(
            select(ProjectMember.id).where(
                ProjectMember.user_id == staff_id, ProjectMember.project_id == other_id
            )
        )
        assert not await session.scalar(
            select(HrAttendanceEntry.id).where(HrAttendanceEntry.employee_id == employee_id)
        )
        assert (
            list(
                await session.execute(
                    select(
                        InventoryLocationStock.id,
                        InventoryLocationStock.on_hand_qty,
                        InventoryLocationStock.reserved_qty,
                    ).order_by(InventoryLocationStock.id)
                )
            )
            == stock_before
        )
        audit_events = list(
            await session.scalars(
                select(ActivityLog.action).where(
                    ActivityLog.entity_type == "hr_roster_allocations",
                    ActivityLog.entity_id.in_([UUID(winner["id"]), UUID(next_day["id"])]),
                )
            )
        )
        assert sorted(audit_events) == [
            "hr.roster.allocated",
            "hr.roster.allocated",
            "hr.roster.cancelled",
        ]


@pytest.mark.asyncio
async def test_payroll_time_inputs_reconcile_locked_hours_and_deny_stale_download(
    monkeypatch,
) -> None:
    import csv
    import hashlib

    from app.models.hr import HrOvertimeRequest, HrTimesheet
    from app.utils.permissions import PERMISSION_HR_PAYROLL_PREPARE, ROLE_PERMISSIONS

    await skip_if_database_unavailable()
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        "administrative_executive",
        ROLE_PERMISSIONS["administrative_executive"] | {PERMISSION_HR_PAYROLL_PREPARE},
    )
    _, hr_email, password = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    _, preparer_email, _ = await _create_portal_user("administrative_executive", password)
    payroll = "/api/v1/hr/payroll"
    root = "/api/v1/hr"
    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))
        payroll_actor = _auth(await _login(client, preparer_email, password))
        employee = await client.post(
            f"{root}/employees",
            headers=hr,
            json={
                "employee_code": f"TIME-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Private Name",
                "employment_status": "active",
                "join_date": "2026-01-01",
            },
        )
        assert employee.status_code == 201
        employee_id = employee.json()["id"]
        period = await client.post(
            f"{payroll}/periods",
            headers=payroll_actor,
            json={
                "period_code": f"TIME-{uuid4().hex[:8]}",
                "period_start": "2028-01-01",
                "period_end": "2028-01-31",
                "pay_date": "2028-02-04",
            },
        )
        assert period.status_code == 201, period.text
        period_id = period.json()["id"]
        inputs = f"{payroll}/periods/{period_id}/time-inputs"
        roster = {"employee_ids": [employee_id]}
        assert (await client.post(f"{inputs}/preview", headers=hr, json=roster)).status_code == 403
        assert (
            await client.post(
                f"{inputs}/preview", headers=payroll_actor, json={"employee_ids": [employee_id] * 2}
            )
        ).status_code == 422
        missing = await client.post(f"{inputs}/preview", headers=payroll_actor, json=roster)
        assert missing.status_code == 200, missing.text
        assert missing.json()["issues"][0]["code"] == "missing_locked_timesheet"
        assert missing.json()["regular_hours"] is None

        overtime = await client.post(
            f"{root}/overtime",
            headers=hr,
            json={
                "employee_id": employee_id,
                "work_date": "2028-01-05",
                "requested_hours": "3.00",
                "reason": "Synthetic private request",
            },
        )
        assert overtime.status_code == 201, overtime.text
        overtime_id = overtime.json()["id"]
        sheet = await client.post(
            f"{root}/timesheets",
            headers=hr,
            json={
                "employee_id": employee_id,
                "period_start": "2028-01-03",
                "period_end": "2028-01-09",
                "regular_hours": "37.50",
                "overtime_hours": "2.50",
                "submit": True,
                "notes": "Synthetic private note",
            },
        )
        assert sheet.status_code == 201, sheet.text
        sheet_id = sheet.json()["id"]
        sheet_decision = f"{root}/timesheets/{sheet_id}/decision"
        assert (
            await client.post(sheet_decision, headers=reviewer, json={"decision": "approved"})
        ).status_code == 200
        denied_lock = await client.post(
            sheet_decision, headers=reviewer, json={"decision": "locked"}
        )
        assert denied_lock.status_code == 409
        review = await client.post(f"{inputs}/preview", headers=payroll_actor, json=roster)
        assert {item["code"] for item in review.json()["issues"]} == {
            "missing_locked_timesheet",
            "timesheet_not_locked",
            "pending_overtime",
        }
        assert (
            await client.post(
                f"{root}/overtime/{overtime_id}/decision",
                headers=reviewer,
                json={"decision": "approved", "approved_hours": "2.50"},
            )
        ).status_code == 200
        lock = await client.post(sheet_decision, headers=reviewer, json={"decision": "locked"})
        assert lock.status_code == 200, lock.text

        preview = await client.post(f"{inputs}/preview", headers=payroll_actor, json=roster)
        assert preview.status_code == 200 and preview.headers["cache-control"] == "no-store"
        data = preview.json()
        assert (data["regular_hours"], data["overtime_hours"], data["issues"]) == (
            "37.50",
            "2.50",
            [],
        )
        query = {**roster, "expected_csv_sha256": data["csv_sha256"]}
        denied = await client.post(f"{inputs}.csv", headers=hr, json=query)
        assert denied.status_code == 403
        download = await client.post(f"{inputs}.csv", headers=payroll_actor, json=query)
        assert download.status_code == 200 and download.headers["cache-control"] == "no-store"
        assert hashlib.sha256(download.content).hexdigest() == data["csv_sha256"]
        assert download.headers["x-payroll-export-sha256"] == data["csv_sha256"]
        assert list(csv.DictReader(io.StringIO(download.text))) == [
            {
                "payroll_period_id": period_id,
                "employee_id": employee_id,
                "timesheet_id": sheet_id,
                "timesheet_revision": str(lock.json()["record_revision"]),
                "period_start": "2028-01-03",
                "period_end": "2028-01-09",
                "regular_hours": "37.50",
                "overtime_hours": "2.50",
            }
        ]
        assert "Synthetic" not in download.text

        # A legacy source can be missing a schedule or disagree with a sheet.
        async with AsyncSessionLocal() as session:
            stored_ot = await session.get(HrOvertimeRequest, UUID(overtime_id))
            assert stored_ot is not None
            stored_ot.approved_hours = Decimal("3")
            session.add(
                HrAttendanceEntry(
                    employee_id=UUID(employee_id),
                    work_date=date(2028, 1, 5),
                    status="approved",
                    attendance_status="present",
                    worked_hours=Decimal("8"),
                )
            )
            await session.commit()
        invalid = await client.post(f"{inputs}/preview", headers=payroll_actor, json=roster)
        assert {item["code"] for item in invalid.json()["issues"]} == {
            "attendance_without_schedule",
            "overtime_hours_mismatch",
        }
        assert invalid.json()["csv_sha256"] is None
        assert (
            await client.post(f"{inputs}.csv", headers=payroll_actor, json=query)
        ).status_code == 409

    async with AsyncSessionLocal() as session:
        persisted = await session.get(HrTimesheet, UUID(sheet_id))
        assert persisted is not None and persisted.status == "locked"
        events = list(
            await session.scalars(
                select(ActivityLog.action).where(
                    ActivityLog.entity_type == "hr_payroll_periods",
                    ActivityLog.entity_id == UUID(period_id),
                    ActivityLog.action.like("hr.payroll_time.%"),
                )
            )
        )
        assert events.count("hr.payroll_time.downloaded") == 1
        assert events.count("hr.payroll_time.previewed") == 4


@pytest.mark.asyncio
async def test_payroll_leave_inputs_reconcile_ledger_and_deny_stale_download(monkeypatch) -> None:
    import csv
    import hashlib

    from app.models.hr import (
        HrHoliday,
        HrLeaveLedger,
        HrLeaveRequest,
        HrPayrollLine,
        HrPayrollRun,
    )
    from app.utils.permissions import PERMISSION_HR_PAYROLL_PREPARE, ROLE_PERMISSIONS

    await skip_if_database_unavailable()
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        "administrative_executive",
        ROLE_PERMISSIONS["administrative_executive"] | {PERMISSION_HR_PAYROLL_PREPARE},
    )
    _, hr_email, password = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    _, preparer_email, _ = await _create_portal_user("administrative_executive", password)
    root = "/api/v1/hr"

    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))
        preparer = _auth(await _login(client, preparer_email, password))

        async def create(path, payload, actor=hr):
            response = await client.post(f"{root}/{path}", headers=actor, json=payload)
            assert response.status_code == 201, response.text
            return response.json()["id"]

        employees = [
            await create(
                "employees",
                {
                    "employee_code": f"LEAVE-PAY-{uuid4().hex[:8]}",
                    "first_name": "Synthetic",
                    "last_name": "Private name",
                    "employment_status": "active",
                    "join_date": "2026-01-01",
                },
            )
            for _ in range(2)
        ]
        employee_id, empty_employee = employees
        period_id = await create(
            "payroll/periods",
            {
                "period_code": f"LEAVE-{uuid4().hex[:8]}",
                "period_start": "2039-01-01",
                "period_end": "2039-01-31",
                "pay_date": "2039-02-04",
            },
            preparer,
        )
        path = f"{root}/payroll/periods/{period_id}/leave-inputs"
        roster = {"employee_ids": employees}
        assert (await client.post(f"{path}/preview", headers=hr, json=roster)).status_code == 403
        await _publish_leave_calendar(
            client, hr, reviewer, "2039-01-01", "2039-02-28", "2039-01-31"
        )
        paid = await _create_legacy_leave_type("Synthetic payroll paid leave")
        unpaid = await _create_legacy_leave_type(
            "Synthetic payroll unpaid leave", is_paid=False
        )
        await create(
            "leave/ledger",
            {
                "employee_id": employee_id,
                "leave_type_id": paid,
                "entry_type": "opening_balance",
                "days_delta": "5.00",
                "leave_year": 2039,
                "reason": "Private opening balance",
            },
        )

        async def request(leave_type, first, last, **options):
            return await create(
                "leave/requests",
                {
                    "employee_id": employee_id,
                    "leave_type_id": leave_type,
                    "start_date": first,
                    "end_date": last,
                    "submit_immediately": True,
                    "reason": "Private reason",
                    **options,
                },
            )

        async def decide(request_id, decision):
            current = await client.get(
                f"{root}/leave/requests/{request_id}/decision", headers=reviewer
            )
            assert current.status_code == 200, current.text
            response = await client.post(
                f"{root}/leave/requests/{request_id}/decision",
                headers=reviewer,
                json={
                    "decision": decision,
                    "expected_revision": current.json()["record_revision"],
                    "notes": "Synthetic change",
                },
            )
            assert response.status_code == 200, response.text

        async def preview(employee_ids=employees):
            response = await client.post(
                f"{path}/preview", headers=preparer, json={"employee_ids": employee_ids}
            )
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            return response.json()

        paid_id = await request(paid, "2039-01-03", "2039-01-04")
        pending = await preview()
        assert pending["issues"] == [
            {"employee_id": employee_id, "request_id": paid_id, "code": "pending_leave"}
        ]
        assert pending["csv_sha256"] is None
        await decide(paid_id, "approved")
        unpaid_id = await request(
            unpaid, "2039-01-05", "2039-01-05", is_half_day=True, half_day_period="morning"
        )
        await decide(unpaid_id, "approved")

        reviewed = await preview()
        assert reviewed["issues"] == []
        assert (reviewed["paid_days"], reviewed["unpaid_days"]) == ("2.00", "0.50")
        assert reviewed["approved_request_count"] == 2
        digest = reviewed["csv_sha256"]
        assert (await preview(employees[::-1]))["csv_sha256"] == digest
        assert (await preview([employee_id]))["csv_sha256"] != digest
        query = {**roster, "expected_csv_sha256": digest}
        assert (await client.post(f"{path}.csv", headers=hr, json=query)).status_code == 403
        download = await client.post(f"{path}.csv", headers=preparer, json=query)
        assert download.status_code == 200 and download.headers["cache-control"] == "no-store"
        assert download.headers["x-payroll-export-sha256"] == digest
        assert hashlib.sha256(download.content).hexdigest() == digest
        rows = list(csv.DictReader(io.StringIO(download.text)))
        assert len(rows) == 3
        by_request = {row["leave_request_id"]: row for row in rows}
        assert (by_request[paid_id]["paid"], by_request[paid_id]["days"]) == ("yes", "2.00")
        assert (by_request[unpaid_id]["paid"], by_request[unpaid_id]["days"]) == ("no", "0.50")
        assert by_request[""]["employee_id"] == empty_employee
        assert by_request[""]["record_status"] == "no_approved_leave"
        assert "Private" not in download.text and "Synthetic" not in download.text

        await decide(unpaid_id, "cancelled")
        cancelled = await preview()
        assert cancelled["issues"] == [] and cancelled["unpaid_days"] == "0.00"
        assert cancelled["approved_request_count"] == 1 and cancelled["csv_sha256"] != digest
        assert (await client.post(f"{path}.csv", headers=preparer, json=query)).status_code == 409

        crossing_id = await request(unpaid, "2039-01-28", "2039-02-02")

        async def move_holiday(old: date, new: date) -> None:
            async with AsyncSessionLocal() as session:
                holiday = await session.scalar(
                    select(HrHoliday).where(HrHoliday.holiday_date == old)
                )
                assert holiday is not None
                holiday.holiday_date = new
                await session.commit()

        await move_holiday(date(2039, 1, 31), date(2039, 2, 1))
        changed = await client.post(
            f"{root}/leave/requests/{crossing_id}/decision",
            headers=reviewer,
            json={"decision": "approved", "expected_revision": 1},
        )
        assert changed.status_code == 409
        assert changed.json()["error_code"] == "LEAVE_SCHEDULE_CHANGED"
        await move_holiday(date(2039, 2, 1), date(2039, 1, 31))
        await decide(crossing_id, "approved")
        await move_holiday(date(2039, 1, 31), date(2039, 2, 1))
        crossing = await preview()
        assert crossing["issues"] == [] and crossing["unpaid_days"] == "1.00"
        february_id = await create(
            "payroll/periods",
            {
                "period_code": f"LEAVE-{uuid4().hex[:8]}",
                "period_start": "2039-02-01",
                "period_end": "2039-02-28",
                "pay_date": "2039-03-04",
            },
            preparer,
        )
        february_path = f"{root}/payroll/periods/{february_id}/leave-inputs"
        february = await client.post(f"{february_path}/preview", headers=preparer, json=roster)
        assert february.status_code == 200 and february.json()["unpaid_days"] == "2.00"
        february_csv = await client.post(
            f"{february_path}.csv",
            headers=preparer,
            json={**roster, "expected_csv_sha256": february.json()["csv_sha256"]},
        )
        assert february_csv.status_code == 200
        february_rows = list(csv.DictReader(io.StringIO(february_csv.text)))
        assert (
            next(row for row in february_rows if row["leave_request_id"] == crossing_id)[
                "allocated_work_dates"
            ]
            == "2039-02-01 2039-02-02"
        )

        async with AsyncSessionLocal() as session:
            legacy = await session.get(HrLeaveRequest, UUID(crossing_id))
            assert legacy is not None
            legacy.scheduled_work_dates = [date(2039, 1, 28)] * 3
            await session.commit()
        invalid = await preview()
        assert invalid["issues"][0]["code"] == "leave_work_dates_mismatch"
        async with AsyncSessionLocal() as session:
            legacy = await session.get(HrLeaveRequest, UUID(crossing_id))
            assert legacy is not None
            legacy.scheduled_work_dates = None
            await session.commit()
        unverifiable = await preview()
        assert unverifiable["issues"][0]["code"] == "leave_crosses_period"
        assert unverifiable["csv_sha256"] is None

        evidence_url = f"{root}/leave/requests/{crossing_id}/date-evidence"
        _, evidence_email, _ = await _create_portal_user("hr_manager", password)
        evidence_maker = _auth(await _login(client, evidence_email, password))
        candidates_url = f"{root}/leave/date-evidence/candidates"
        candidates_params = {"employee_id": employee_id, "limit": 1}
        assert (await client.get(candidates_url, headers=preparer)).status_code == 403
        candidates = await client.get(
            candidates_url, headers=evidence_maker, params=candidates_params
        )
        assert candidates.status_code == 200, candidates.text
        assert candidates.headers["cache-control"] == "no-store"
        assert candidates.json()["total"] == 1
        candidate = candidates.json()["items"][0]
        assert candidate["request_id"] == crossing_id
        assert candidate["requires_payroll_correction"] is False
        assert set(candidate) == {
            "request_id", "employee_id", "start_date", "end_date", "approved_units",
            "requires_payroll_correction",
        }
        before = await client.get(evidence_url, headers=evidence_maker)
        assert before.status_code == 200 and before.headers["cache-control"] == "no-store"
        assert (await client.get(evidence_url, headers=preparer)).status_code == 403
        proposal = {
            "proposal_id": str(uuid4()),
            "expected_revision": before.json()["request_revision"],
            "work_dates": ["2039-01-28", "2039-02-01", "2039-02-02"],
            "evidence_reference": "SYNTHETIC-LEGACY-CALENDAR",
        }
        wrong_units = await client.post(
            evidence_url, headers=evidence_maker,
            json={**proposal, "work_dates": ["2039-01-28", "2039-02-01"]},
        )
        assert wrong_units.status_code == 422
        proposed = await client.post(evidence_url, headers=evidence_maker, json=proposal)
        assert proposed.status_code == 200, proposed.text
        assert (await preview())["issues"][0]["code"] == "leave_crosses_period"
        replay = await client.post(evidence_url, headers=evidence_maker, json=proposal)
        assert replay.json() == proposed.json()
        detail_url = f"{evidence_url}/{proposal['proposal_id']}"
        detail = await client.get(detail_url, headers=reviewer)
        assert detail.status_code == 200 and detail.json() == proposed.json()
        assert detail.headers["cache-control"] == "no-store"
        assert (await client.get(detail_url, headers=preparer)).status_code == 403
        decision_url = f"{detail_url}/decision"
        decision = {"decision": "approved", "expected_digest": proposed.json()["digest"]}
        self_review = await client.post(decision_url, headers=evidence_maker, json=decision)
        assert self_review.status_code == 403
        wrong_digest = await client.post(
            decision_url, headers=reviewer, json={**decision, "expected_digest": "0" * 64},
        )
        assert wrong_digest.status_code == 409
        # A payroll approval recorded after proposal still prevents a historical mutation.
        async with AsyncSessionLocal() as session:
            locked_run = HrPayrollRun(payroll_period_id=UUID(period_id), status="approved")
            session.add(locked_run)
            await session.flush()
            locked_run_id = locked_run.id
            session.add(HrPayrollLine(
                payroll_run_id=locked_run_id,
                employee_id=UUID(employee_id),
                gross_encrypted="unused fixture",
                deductions_encrypted="unused fixture",
                net_encrypted="unused fixture",
            ))
            await session.commit()
        while_locked = await client.post(decision_url, headers=reviewer, json=decision)
        assert while_locked.status_code == 409 and "locked payroll" in while_locked.json()["detail"]
        crossing_state = await client.get(
            f"{root}/leave/requests/{crossing_id}/decision", headers=reviewer
        )
        assert crossing_state.status_code == 200
        locked_cancel = await client.post(
            f"{root}/leave/requests/{crossing_id}/decision", headers=reviewer,
            json={
                "decision": "cancelled",
                "expected_revision": crossing_state.json()["record_revision"],
                "notes": "Synthetic locked reversal",
            },
        )
        assert locked_cancel.status_code == 409
        assert locked_cancel.json()["error_code"] == "LEAVE_PAYROLL_LOCKED"
        new_request = await request(unpaid, "2039-01-17", "2039-01-17")
        locked_approval = await client.post(
            f"{root}/leave/requests/{new_request}/decision", headers=reviewer,
            json={"decision": "approved", "expected_revision": 1},
        )
        assert locked_approval.status_code == 409
        assert locked_approval.json()["error_code"] == "LEAVE_PAYROLL_LOCKED"
        await decide(new_request, "cancelled")
        locked_candidates = await client.get(
            candidates_url, headers=evidence_maker, params=candidates_params
        )
        assert locked_candidates.json()["items"][0]["requires_payroll_correction"] is True
        locked_request = (await client.get(evidence_url, headers=evidence_maker)).json()
        assert locked_request["requires_payroll_correction"] and not locked_request["can_propose"]
        async with AsyncSessionLocal() as session:
            locked = await session.get(HrPayrollRun, locked_run_id)
            assert locked is not None
            await session.delete(locked)
            await session.commit()
        accepted = await client.post(decision_url, headers=reviewer, json=decision)
        assert accepted.status_code == 200, accepted.text
        repeated = await client.post(decision_url, headers=reviewer, json=decision)
        assert repeated.json() == accepted.json()
        retained = (await client.get(evidence_url, headers=reviewer)).json()
        assert retained["scheduled_work_dates"] == proposal["work_dates"]
        assert retained["request_revision"] == proposal["expected_revision"] + 1
        resolved = await client.get(
            candidates_url, headers=evidence_maker, params=candidates_params
        )
        assert resolved.json() == {"total": 0, "items": []}
        assert (await preview())["unpaid_days"] == "1.00"
        february_reconciled = await client.post(
            f"{february_path}/preview", headers=preparer, json=roster
        )
        assert february_reconciled.json()["unpaid_days"] == "2.00"
        async with AsyncSessionLocal() as session:
            history = list(await session.scalars(
                select(HrLeaveLedger).where(
                    HrLeaveLedger.reference_request_id == UUID(crossing_id)
                )
            ))
            assert len(history) == 1 and history[0].days_delta == Decimal("-3.00")
        await decide(crossing_id, "cancelled")

        async with AsyncSessionLocal() as session:
            debit = await session.scalar(
                select(HrLeaveLedger).where(HrLeaveLedger.reference_request_id == UUID(paid_id))
            )
            assert debit is not None
            debit.days_delta = Decimal("-1.00")
            await session.commit()
        mismatch = await preview()
        assert mismatch["issues"] == [
            {"employee_id": employee_id, "request_id": paid_id, "code": "leave_ledger_mismatch"}
        ]
        assert mismatch["paid_days"] is None and mismatch["csv_sha256"] is None


@pytest.mark.asyncio
async def test_hr_reimbursement_receipt_retry_and_independent_decisions(monkeypatch) -> None:
    from sqlalchemy import func

    from app.models.finance import Invoice, Payment
    from app.utils.permissions import (
        PERMISSION_HR_PAYROLL_APPROVE,
        PERMISSION_HR_PAYROLL_SENSITIVE,
        ROLE_PERMISSIONS,
    )
    from app.utils.time import business_today

    await skip_if_database_unavailable()
    async with AsyncSessionLocal() as session:
        original_invoices = await session.scalar(select(func.count()).select_from(Invoice))
        original_payments = await session.scalar(select(func.count()).select_from(Payment))
    maker_id, maker_email, password = await _create_portal_user("hr_manager")
    reviewer_id, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    _, recorder_email, _ = await _create_portal_user("hr_manager", password)
    _, director_email, _ = await _create_portal_user("managing_director", password)
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        "hr_manager",
        ROLE_PERMISSIONS["hr_manager"]
        | {PERMISSION_HR_PAYROLL_APPROVE, PERMISSION_HR_PAYROLL_SENSITIVE},
    )
    base = "/api/v1/hr"
    claim_path = f"{base}/reimbursements"
    self_path = f"{base}/me/reimbursements"
    async with _client() as client:
        maker = _auth(await _login(client, maker_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))
        recorder = _auth(await _login(client, recorder_email, password))
        director = _auth(await _login(client, director_email, password))

        async def employee(work_email: str) -> str:
            created = await client.post(
                f"{base}/employees",
                headers=maker,
                json={
                    "employee_code": f"CLAIM-{uuid4().hex[:8]}",
                    "first_name": "Synthetic",
                    "last_name": "Claim",
                    "work_email": work_email,
                    "employment_status": "active",
                },
            )
            assert created.status_code == 201, created.text
            return created.json()["id"]

        owner, outsider = await employee(maker_email), await employee(reviewer_email)
        linked = await client.post(
            f"{base}/employees/{owner}/link-account", headers=director, json={"user_id": maker_id}
        )
        assert linked.status_code == 200, linked.text
        linked = await client.post(
            f"{base}/employees/{outsider}/link-account",
            headers=director,
            json={"user_id": reviewer_id},
        )
        assert linked.status_code == 200, linked.text

        async def upload(employee_id, category="compensation", label="shared synthetic receipt"):
            result = await client.post(
                f"{base}/documents",
                headers=maker,
                data={
                    "employee_id": employee_id,
                    "title": "Synthetic reimbursement",
                    "document_type": "reimbursement_receipt",
                    "category": category,
                },
                files={
                    "file": (
                        "receipt.pdf",
                        _pdf_bytes(label),
                        "application/pdf",
                    )
                },
            )
            assert result.status_code == 201, result.text
            return result.json()

        async def approve(doc):
            decision = await client.post(
                f"{base}/documents/{doc['id']}/versions/1/decision",
                headers=reviewer,
                json={"decision": "approve"},
            )
            assert decision.status_code == 200, decision.text

        benefit_types = f"{base}/benefits/types"
        assignments = f"{base}/benefits/assignments"
        type_payload = {
            "code": f"TEST-TRAVEL-{uuid4().hex[:8]}",
            "name": "Synthetic travel reimbursement",
            "category": "Travel",
            "reimbursement_ceiling": "50.00",
            "reimbursement_currency": "LKR",
            "allows_advances": True,
        }
        assert (
            await client.post(
                benefit_types,
                headers=maker,
                json={**type_payload, "requires_policy_approval": False},
            )
        ).status_code == 422
        proposed = await client.post(benefit_types, headers=maker, json=type_payload)
        assert proposed.status_code == 201 and proposed.json()["approved_at"] is None
        benefit_id = proposed.json()["id"]
        today = business_today()
        today_text = today.isoformat()
        coverage = {
            "employee_id": owner,
            "benefit_type_id": benefit_id,
            "effective_from": today_text,
            "effective_to": (today + timedelta(days=29)).isoformat(),
        }
        assert (await client.post(assignments, headers=maker, json=coverage)).status_code == 409
        policy_approval = f"{benefit_types}/{benefit_id}/approve"
        assert (await client.post(policy_approval, headers=maker)).status_code == 403
        assert (await client.post(policy_approval, headers=reviewer)).status_code == 200
        assert (
            await client.post(assignments, headers=maker, json={**coverage, "effective_to": None})
        ).status_code == 422
        assigned = await client.post(assignments, headers=maker, json=coverage)
        assert assigned.status_code == 201, assigned.text
        assignment_id = assigned.json()["id"]
        assert (await client.post(assignments, headers=maker, json=coverage)).status_code == 409
        outside = await client.post(
            assignments, headers=maker, json={**coverage, "employee_id": outsider}
        )
        assert outside.status_code == 201

        receipt = await upload(owner)
        receipt_id = receipt["id"]
        pending_download = f"{base}/documents/{receipt_id}/download"
        assert (
            await client.get(pending_download, headers=maker, params={"version_number": 1})
        ).status_code == 404
        assert (await client.get(pending_download, headers=reviewer)).status_code == 404
        response = await client.get(
            pending_download, headers=reviewer, params={"version_number": 1}
        )
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        payload = {
            "employee_id": owner,
            "claim_type": type_payload["code"],
            "benefit_assignment_id": assignment_id,
            "claim_date": today_text,
            "amount": "25.75",
            "currency": "LKR",
            "description": "Synthetic reimbursable expense",
            "receipt_document_id": receipt_id,
            "receipt_version_number": 1,
        }
        key = f"claim-{uuid4()}"

        async def submit(body=payload, *, actor=maker, request_key=key):
            return await client.post(
                self_path, headers={**actor, "Idempotency-Key": request_key}, json=body
            )

        assert (await client.get(claim_path, headers=director)).status_code == 403
        assert (await submit(actor=reviewer)).status_code == 404
        assert (
            await submit({**payload, "benefit_assignment_id": outside.json()["id"]})
        ).status_code == 404
        assert (
            await submit({**payload, "claim_date": (today + timedelta(days=30)).isoformat()})
        ).status_code == 409
        assert (await submit({**payload, "claim_type": "Other"})).status_code == 409
        assert (await submit({**payload, "currency": "USD"})).status_code == 409
        assert (await submit({**payload, "amount": "25.755"})).status_code == 422
        assert (await submit()).status_code == 404
        other_receipt = await upload(outsider)
        await approve(other_receipt)
        assert (
            await submit({**payload, "receipt_document_id": other_receipt["id"]})
        ).status_code == 404
        public_receipt = await upload(owner, category="ordinary")
        await approve(public_receipt)
        assert (
            await submit({**payload, "receipt_document_id": public_receipt["id"]})
        ).status_code == 404
        await approve(receipt)
        assert (await submit({**payload, "receipt_version_number": 2})).status_code == 409
        assert (await client.post(self_path, headers=maker, json=payload)).status_code == 422
        first, replay = await asyncio.gather(submit(), submit())
        assert first.status_code == replay.status_code == 201, (first.text, replay.text)
        assert first.headers["cache-control"] == "no-store"
        claim = first.json()
        assert claim["id"] == replay.json()["id"]
        assert claim["amount"] == "25.75"
        assert claim["receipt_version_id"] == receipt["versions"][0]["id"]
        assert (await submit({**payload, "amount": "25.76"})).status_code == 409
        identical = await upload(owner)
        await approve(identical)
        assert (
            await submit(
                {**payload, "receipt_document_id": identical["id"], "amount": "1.00"},
                request_key=f"claim-{uuid4()}",
            )
        ).status_code == 409
        assert (await client.get(self_path, headers=reviewer)).json()["items"] == []

        path = f"{claim_path}/{claim['id']}/decision"
        reference_path = f"{claim_path}/{claim['id']}/payable"

        async def decide(actor, decision, **fields):
            return await client.post(path, headers=actor, json={"decision": decision, **fields})

        assert (await decide(maker, "approved")).status_code == 403
        assert (await client.get(reference_path, headers=director)).status_code == 403
        assert (await client.get(reference_path, headers=reviewer)).status_code == 409
        outcome = {
            "settlement_reference": "TEST-01",
            "expected_payable_sha256": "0" * 64,
            "settled_amount": "25.75",
            "settled_currency": "LKR",
        }
        assert (await decide(recorder, "paid", **outcome)).status_code == 409
        first, second = await asyncio.gather(
            decide(reviewer, "approved"), decide(reviewer, "approved")
        )
        assert sorted([first.status_code, second.status_code]) == [200, 409]
        handoff = await client.get(reference_path, headers=recorder)
        assert handoff.status_code == 200 and handoff.headers["cache-control"] == "no-store"
        payable = handoff.json()
        assert payable["status"] == "approved"
        assert payable["reference"] == {
            "version": "reimbursement-payable-v1",
            "claim_id": claim["id"],
            "payable_reference": claim["claim_code"],
            "employee_id": owner,
            "amount": "25.75",
            "currency": "LKR",
            "approved_at": next(
                result.json()["decided_at"]
                for result in (first, second)
                if result.status_code == 200
            ),
        }
        assert "Synthetic" not in handoff.text and receipt_id not in handoff.text
        assert (await decide(recorder, "paid", **outcome)).status_code == 409
        outcome["expected_payable_sha256"] = payable["reference_sha256"]
        assert (await decide(reviewer, "paid", **outcome)).status_code == 403
        assert (await decide(recorder, "paid")).status_code == 422
        assert (
            await decide(recorder, "paid", **{**outcome, "settled_amount": "25.74"})
        ).status_code == 409
        assert (
            await decide(recorder, "paid", **{**outcome, "settled_currency": "USD"})
        ).status_code == 409
        paid = await decide(recorder, "paid", **outcome)
        assert paid.status_code == 200, paid.text
        assert paid.json()["decided_by_id"] == str(reviewer_id)
        assert paid.json()["settlement_reference"] == "TEST-01"
        assert (await decide(recorder, "paid", **outcome)).status_code == 200
        assert (
            await decide(recorder, "paid", **{**outcome, "settlement_reference": "TEST-02"})
        ).status_code == 409
        assert (await decide(recorder, "rejected", notes="Synthetic")).status_code == 409
        readback = await client.get(reference_path, headers=recorder)
        assert readback.status_code == 200 and readback.json() == {**payable, "status": "paid"}
        new_receipts = [
            await upload(owner, label=f"synthetic follow-up {number}") for number in range(2)
        ]
        for doc in new_receipts:
            await approve(doc)
        contenders = [
            {**payload, "amount": "15.00", "receipt_document_id": doc["id"]} for doc in new_receipts
        ]
        results = await asyncio.gather(
            *(submit(body, request_key=str(uuid4())) for body in contenders)
        )
        assert sorted(response.status_code for response in results) == [201, 409]
        loser = next(i for i, result in enumerate(results) if result.status_code == 409)
        assert results[loser].json()["error_code"] == "BENEFIT_CEILING_EXCEEDED"
        winner_id = results[1 - loser].json()["id"]
        rejected = await client.post(
            f"{claim_path}/{winner_id}/decision",
            headers=reviewer,
            json={"decision": "rejected", "notes": "Synthetic declined claim"},
        )
        assert rejected.status_code == 200
        boundary = await submit({**contenders[loser], "amount": "24.25"}, request_key=str(uuid4()))
        assert boundary.status_code == 201 and boundary.json()["amount"] == "24.25"
        boundary_id = boundary.json()["id"]
        assert (
            await client.post(
                f"{claim_path}/{boundary_id}/decision",
                headers=reviewer,
                json={"decision": "cancelled", "notes": "Synthetic cancellation"},
            )
        ).status_code == 200

        advance_root = f"{base}/advances"
        advance_request = {
            "employee_id": owner,
            "benefit_assignment_id": assignment_id,
            "requested_on": today_text,
            "amount": "24.25",
            "currency": "LKR",
        }
        advance_key = str(uuid4())

        async def advance_submit(body=advance_request, key=advance_key):
            return await client.post(
                advance_root, headers={**maker, "Idempotency-Key": key}, json=body
            )

        assert (
            await client.get(advance_root, headers=director, params={"employee_id": owner})
        ).status_code == 403
        assert (await advance_submit({**advance_request, "amount": "24.26"})).status_code == 409
        made = await advance_submit()
        assert made.status_code == 201, made.text
        assert made.json()["status"] == "submitted" and made.json()["payable_sha256"] is None
        assert (await advance_submit()).json()["id"] == made.json()["id"]
        assert (await advance_submit({**advance_request, "amount": "1.00"})).status_code == 409
        advance = f"{advance_root}/{made.json()['id']}"

        async def update_advance(action, body, actor=recorder):
            return await client.post(f"{advance}/{action}", headers=actor, json=body)

        assert (
            await update_advance("decision", {"decision": "approved"}, maker)
        ).status_code == 403
        approved = await update_advance("decision", {"decision": "approved"}, reviewer)
        assert approved.status_code == 200 and approved.json()["status"] == "approved"
        digest = approved.json()["payable_sha256"]
        assert digest
        payout = {
            "reference": "SYNTHETIC-FUND-01",
            "occurred_on": today_text,
            "amount": "24.25",
            "currency": "LKR",
            "expected_payable_sha256": digest,
        }
        assert (await update_advance("disburse", payout, reviewer)).status_code == 403
        assert (
            await update_advance("disburse", {**payout, "expected_payable_sha256": "0" * 64})
        ).status_code == 409
        funded = await update_advance("disburse", payout)
        assert funded.status_code == 200 and funded.json()["outstanding"] == "24.25"
        assert (await update_advance("disburse", payout)).status_code == 200
        repayment = {
            "reference": "SYNTHETIC-RECOVERY-01",
            "occurred_on": today_text,
            "amount": "4.25",
            "currency": "LKR",
        }
        assert (
            await update_advance("repayments", {**repayment, "reference": payout["reference"]})
        ).status_code == 409
        first, replay = await asyncio.gather(
            update_advance("repayments", repayment), update_advance("repayments", repayment)
        )
        assert first.status_code == replay.status_code == 200
        assert first.json()["outstanding"] == "20.00" and len(replay.json()["recoveries"]) == 1
        assert (
            await update_advance("repayments", {**repayment, "amount": "1.00"})
        ).status_code == 409
        assert (
            await submit({**contenders[loser], "amount": "1.00"}, request_key=str(uuid4()))
        ).json()["error_code"] == "BENEFIT_CEILING_EXCEEDED"
        final_repayment = {**repayment, "amount": "20.00", "reference": "SYNTHETIC-RECOVERY-02"}
        assert (
            await update_advance("repayments", {**final_repayment, "amount": "20.01"})
        ).status_code == 409
        settled = await update_advance("repayments", final_repayment)
        assert settled.status_code == 200 and settled.json()["status"] == "settled"
        assert settled.json()["outstanding"] == "0.00" and settled.json()["recovered"] == "24.25"
        read = await client.get(advance, headers=reviewer)
        assert read.json() == settled.json() and read.headers["cache-control"] == "no-store"
        listed = await client.get(advance_root, headers=reviewer, params={"employee_id": owner})
        assert listed.json() == {"items": [settled.json()], "total": 1}
        assert (
            await submit({**contenders[loser], "amount": "24.25"}, request_key=str(uuid4()))
        ).status_code == 201

    async with AsyncSessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(Invoice)) == original_invoices
        assert await session.scalar(select(func.count()).select_from(Payment)) == original_payments
        events = list(
            await session.scalars(
                select(ActivityLog.action).where(
                    ActivityLog.entity_id == UUID(claim["id"]),
                    ActivityLog.entity_type == "hr_reimbursement_claims",
                )
            )
        )
        assert sorted(events) == [
            "hr.reimbursement.approved",
            "hr.reimbursement.paid",
            "hr.reimbursement.payable_read",
            "hr.reimbursement.payable_read",
            "hr.reimbursement.submitted",
        ]


def test_garrisonctl_advance_operations_bind_private_input_and_verify_readback(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "cli-test-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    employee_id, actor_id, advance_id, assignment_id, request_key = (str(uuid4()) for _ in range(5))
    day = "2026-10-01"
    digest = "b" * 64
    path = f"/api/v1/hr/advances/{advance_id}"
    request_body = {
        "employee_id": employee_id,
        "benefit_assignment_id": assignment_id,
        "requested_on": day,
        "amount": "23.45",
        "currency": "LKR",
    }
    row = {
        **request_body,
        "id": advance_id,
        "status": "submitted",
        "submitted_by_id": actor_id,
        "decided_by_id": None,
        "decided_at": None,
        "payable_sha256": None,
        "disbursed_on": None,
        "disbursement_reference": None,
        "recovered": "0.00",
        "outstanding": "0.00",
        "recoveries": [],
    }
    payment = {
        "reference": "SYNTHETIC-DISBURSEMENT",
        "amount": "23.45",
        "occurred_on": day,
        "currency": "LKR",
        "expected_payable_sha256": digest,
    }
    recovery = {
        "reference": "SYNTHETIC-RECOVERY",
        "amount": "23.45",
        "occurred_on": day,
        "currency": "LKR",
    }
    operations: list[str] = []
    permissions = ["hr:payroll:sensitive", "hr:payroll:approve"]
    incorrect_readback = False

    def handler(request: httpx.Request) -> httpx.Response:
        route = request.url.path
        if route == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor_id, "permissions": permissions})
        if request.method == "GET" and route == path:
            return httpx.Response(200, json=row)
        if request.method == "GET" and route == "/api/v1/hr/advances":
            assert request.url.params["employee_id"] == employee_id
            return httpx.Response(200, json={"items": [row], "total": 1})
        assert request.method == "POST"
        data = json.loads(request.content)
        operations.append(route)
        if route == "/api/v1/hr/advances":
            assert request.headers["idempotency-key"] == request_key
            assert data == request_body
        elif route == f"{path}/decision":
            assert data == {"decision": "approved"}
            row.update(
                status="approved",
                decided_by_id=str(uuid4()),
                decided_at=f"{day}T10:00:00Z",
                payable_sha256=digest,
            )
        elif route == f"{path}/disburse":
            assert data == payment
            row.update(
                status="disbursed",
                disbursed_on=day,
                outstanding="23.45",
                disbursement_reference=payment["reference"],
            )
        elif route == f"{path}/repayments":
            assert data == recovery
            row.update(
                status="settled",
                outstanding="0.00",
                recovered="23.45",
                recoveries=[
                    {"reference": recovery["reference"], "occurred_on": day, "amount": "23.45"}
                ]
                if not incorrect_readback
                else [],
            )
        else:
            pytest.fail(f"Unexpected write route {route}")
        return httpx.Response(200, json=row)

    def private_file(name, data, mode=0o600):
        target = tmp_path / name
        target.write_text(json.dumps(data), encoding="utf-8")
        target.chmod(mode)
        return str(target)

    def invoke(command, *options):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "advance", command, "--json", *options],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        rendered = stdout.getvalue()
        assert all(
            value not in rendered
            for value in (
                "23.45",
                "SYNTHETIC-DISBURSEMENT",
                "SYNTHETIC-RECOVERY",
                request_key,
            )
        )
        return code, json.loads(rendered)

    def dry_run(command, *options):
        before = list(operations)
        code, preview = invoke(command, *options, "--dry-run")
        assert code == 0 and operations == before
        return preview["data"]["plan_sha256"]

    def apply(command, *options):
        plan = dry_run(command, *options)
        code, receipt = invoke(command, *options, "--apply", "--expect", plan)
        assert code == 0
        return receipt["data"]

    form = {**request_body, "idempotency_key": request_key}
    assert (
        invoke("submit", "--file", private_file("request.json", form, 0o644), "--dry-run")[0] != 0
    )
    submission = ("--file", private_file("request.json", form))
    assert apply("submit", *submission)["advance_id"] == advance_id
    key = ("--advance-id", advance_id)
    decision = (*key, "--decision", "approved")
    permissions.remove("hr:payroll:approve")
    assert invoke("decide", *decision, "--dry-run")[0] != 0
    permissions.append("hr:payroll:approve")
    assert apply("decide", *decision)["status"] == "approved"

    output = tmp_path / "payable.json"
    assert invoke("show", *key, "--output", str(output))[0] == 0
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text()) == row
    assert invoke("show", *key, "--output", str(output))[0] != 0

    disbursement = (*key, "--file", private_file("disbursement.json", payment))
    plan = dry_run("confirm-disbursement", *disbursement)
    row["status"] = "cancelled"
    assert invoke("confirm-disbursement", *disbursement, "--apply", "--expect", plan)[0] == 4
    row["status"] = "approved"
    private_file("disbursement.json", {**payment, "reference": "CHANGED"})
    assert invoke("confirm-disbursement", *disbursement, "--apply", "--expect", plan)[0] == 4
    assert len(operations) == 2
    private_file("disbursement.json", payment)
    assert apply("confirm-disbursement", *disbursement)["status"] == "disbursed"

    repayment = (*key, "--file", private_file("recovery.json", recovery))
    plan = dry_run("record-repayment", *repayment)
    incorrect_readback = True
    code, result = invoke("record-repayment", *repayment, "--apply", "--expect", plan)
    assert code != 0 and result["changed"] is None
    assert operations[-1] == f"{path}/repayments"

    row.update(status="disbursed", recoveries=[], recovered="0.00", outstanding="23.45")
    incorrect_readback = False
    assert apply("record-repayment", *repayment)["repayment_count"] == 1
    listed = invoke("list", "--employee-id", employee_id)[1]["data"]
    assert listed["items"][0]["status"] == "settled" and listed["total"] == 1


def test_garrisonctl_reimbursement_exports_and_binds_the_reviewed_payable(tmp_path, monkeypatch):
    from scripts.garrisonctl_common import sha256_json

    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "cli-test-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    actor_id, claim_id, employee_id = (str(uuid4()) for _ in range(3))
    reference = {
        "version": "reimbursement-payable-v1",
        "claim_id": claim_id,
        "payable_reference": "CLM-SYNTH001",
        "employee_id": employee_id,
        "amount": "25.75",
        "currency": "LKR",
        "approved_at": "2026-10-02T10:00:00Z",
    }
    digest = sha256_json(reference)
    status = "approved"
    response_digest = digest
    posted = []
    output = tmp_path / "payable.json"
    settlement = tmp_path / "settlement.json"
    settlement_fields = {
        "expected_payable_sha256": digest,
        "settled_amount": "25.75",
        "settled_currency": "LKR",
        "settlement_reference": "SYNTHETIC-EXTERNAL-01",
    }
    settlement.write_text(json.dumps(settlement_fields), encoding="utf-8")
    settlement.chmod(0o600)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status
        path = request.url.path
        if path == "/api/v1/auth/me":
            return httpx.Response(
                200,
                json={
                    "id": actor_id,
                    "permissions": ["hr:payroll:approve", "hr:payroll:sensitive"],
                },
            )
        if path == f"/api/v1/hr/reimbursements/{claim_id}/payable":
            return httpx.Response(
                200,
                json={
                    "status": status,
                    "reference": reference,
                    "reference_sha256": response_digest,
                },
            )
        assert request.method == "POST" and path == f"/api/v1/hr/reimbursements/{claim_id}/decision"
        posted.append(json.loads(request.content))
        status = "paid"
        return httpx.Response(200, json={"id": claim_id, "status": status})

    def invoke(command: str, *options: str):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "reimbursement", command, "--claim-id", claim_id, "--json", *options],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        text = stdout.getvalue()
        assert not stderr.getvalue()
        assert "25.75" not in text and "SYNTHETIC-EXTERNAL-01" not in text
        return code, json.loads(text)

    response_digest = "0" * 64
    assert invoke("payable", "--output", str(output))[0] == 4
    assert not output.exists()
    response_digest = digest
    code, report = invoke("payable", "--output", str(output))
    assert code == 0 and report["data"]["reference_sha256"] == digest
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text())["reference"] == reference
    assert invoke("payable", "--output", str(output))[0] != 0

    command_options = ("--settlement-file", str(settlement))
    code, preview = invoke("confirm-paid", *command_options, "--dry-run")
    assert code == 0 and not posted
    plan = preview["data"]["plan_sha256"]
    settlement.write_text(
        json.dumps({**settlement_fields, "settlement_reference": "SYNTHETIC-CHANGED"}),
        encoding="utf-8",
    )
    assert invoke("confirm-paid", *command_options, "--apply", "--expect", plan)[0] == 4
    assert not posted
    settlement.write_text(json.dumps(settlement_fields), encoding="utf-8")
    code, receipt = invoke("confirm-paid", *command_options, "--apply", "--expect", plan)
    assert code == 0 and receipt["data"]["status"] == "paid"
    assert posted == [{"decision": "paid", **settlement_fields}]
    assert invoke("payable")[1]["data"]["status"] == "paid"
    assert invoke("payable", "--output", str(tmp_path / "new.json"))[0] == 4


@pytest.mark.parametrize("source", ["time", "leave"])
def test_garrisonctl_payroll_inputs_writes_only_verified_private_bytes(
    tmp_path, monkeypatch, source
):
    import hashlib

    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "cli-test-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    employee_id, period_id = str(uuid4()), str(uuid4())
    roster_file = tmp_path / "roster.json"
    roster_file.write_text(json.dumps([employee_id]), encoding="utf-8")
    roster_file.chmod(0o600)
    output = tmp_path / f"{source}.csv"
    content = b"regular_hours,overtime_hours\n37.50,2.50\n"
    digest = hashlib.sha256(content).hexdigest()
    actual_content = content

    def handler(request: httpx.Request) -> httpx.Response:
        prefix = f"/api/v1/hr/payroll/periods/{period_id}/{source}-inputs"
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200, json={"id": str(uuid4()), "permissions": ["hr:payroll:prepare"]}
            )
        if request.url.path == f"{prefix}/preview":
            assert json.loads(request.content) == {"employee_ids": [employee_id]}
            return httpx.Response(200, json={"csv_sha256": digest, "issues": []})
        assert request.method == "POST" and request.url.path == f"{prefix}.csv"
        assert json.loads(request.content) == {
            "employee_ids": [employee_id],
            "expected_csv_sha256": digest,
        }
        return httpx.Response(
            200,
            content=actual_content,
            headers={"content-type": "text/csv", "x-payroll-export-sha256": digest},
        )

    command = [
        "hr",
        "payroll",
        f"{source}-inputs",
        "--period-id",
        period_id,
        "--roster-file",
        str(roster_file),
    ]

    def invoke(*options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [*command, *options, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        return code, json.loads(stdout.getvalue())

    code, preview = invoke()
    assert code == 0 and preview["data"]["csv_sha256"] == digest
    options = ("--output", str(output), "--sha256", digest)
    actual_content = b"mismatched file"
    assert invoke(*options)[0] == 4
    assert not output.exists()
    actual_content = content
    assert invoke(*options)[0] == 0
    assert output.read_bytes() == content
    assert output.stat().st_mode & 0o777 == 0o600
    assert invoke(*options)[0] != 0
    assert output.read_bytes() == content


@pytest.mark.asyncio
async def test_employee_profile_edits_conflict_and_names_require_review() -> None:
    await skip_if_database_unavailable()
    _, maker_email, password = await _create_portal_user("hr_manager")
    _, checker_email, _ = await _create_portal_user("hr_manager", password)
    _, director_email, _ = await _create_portal_user("managing_director", password)
    employee_user_id, employee_email, _ = await _create_portal_user("quantity_surveyor", password)
    _, unrelated_email, _ = await _create_portal_user("quantity_surveyor", password)
    root = "/api/v1/hr"

    async with _client() as client:
        maker = _auth(await _login(client, maker_email, password))
        checker = _auth(await _login(client, checker_email, password))
        director = _auth(await _login(client, director_email, password))
        owner = _auth(await _login(client, employee_email, password))
        unrelated = _auth(await _login(client, unrelated_email, password))
        created = await client.post(
            f"{root}/employees",
            headers=maker,
            json={
                "employee_code": f"CORR-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Prior",
                "employment_status": "active",
                "work_email": employee_email,
                "join_date": "2025-01-01",
            },
        )
        assert created.status_code == 201, created.text
        employee_id = created.json()["id"]
        url = f"{root}/employees/{employee_id}"
        linked = await client.post(
            f"{url}/link-account", headers=director, json={"user_id": employee_user_id}
        )
        assert linked.status_code == 200
        revision = linked.json()["record_revision"]
        before = await client.get(f"{root}/me", headers=owner)
        assert before.status_code == 200 and before.headers["cache-control"] == "no-store"
        assert before.json()["employee"]["record_revision"] == revision
        assert (await client.get(f"{root}/me", headers=unrelated)).status_code == 404
        assert (await client.get(f"{url}/private", headers=owner)).status_code == 403
        assert (await client.get(f"{url}/private", headers=director)).status_code == 403
        assert (
            await client.patch(f"{root}/me", headers=owner, json={"personal_phone": "000123"})
        ).status_code == 422
        assert (
            await client.patch(
                f"{root}/me",
                headers=owner,
                json={"expected_revision": revision, "first_name": "Forbidden"},
            )
        ).status_code == 422

        owner_write = {"expected_revision": revision, "personal_phone": "000123"}
        vault_write = {"expected_revision": revision, "personal_phone": "000456"}
        competing = await asyncio.gather(
            client.patch(f"{root}/me", headers=owner, json=owner_write),
            client.put(f"{url}/private", headers=maker, json=vault_write),
        )
        assert sorted(response.status_code for response in competing) == [200, 409]
        saved = await client.get(f"{root}/me", headers=owner)
        assert saved.json()["employee"]["record_revision"] == revision + 1
        expected_phone = "000123" if competing[0].status_code == 200 else "000456"
        assert saved.json()["personal_phone"] == expected_phone
        private = await client.get(f"{url}/private", headers=checker)
        assert private.headers["cache-control"] == "no-store"
        assert private.json()["record_revision"] == revision + 1

        revision += 1
        direct = await client.patch(
            url, headers=maker, json={"expected_revision": revision, "last_name": "Bypass"}
        )
        assert direct.status_code == 409
        assert direct.json()["error_code"] == "PROFILE_CORRECTION_REQUIRED"
        proposals = f"{url}/employment-changes"
        draft = {
            "change_type": "profile_correction",
            "effective_date": business_today().isoformat(),
            "employee_revision": revision,
            "reason": "Synthetic verified correction",
            "updates": {"last_name": "  Corrected  "},
        }
        for invalid in ({"last_name": " "}, {"last_name": None}, {"personal_phone": "000789"}):
            assert (
                await client.post(proposals, headers=maker, json={**draft, "updates": invalid})
            ).status_code == 422
        proposal = await client.post(proposals, headers=maker, json=draft)
        assert proposal.status_code == 201, proposal.text
        stale_id = proposal.json()["id"]
        live_change = await client.patch(
            url, headers=maker, json={"expected_revision": revision, "work_location": "Fixture"}
        )
        assert live_change.status_code == 200
        assert (
            await client.post(
                f"{proposals}/{stale_id}/decision", headers=checker, json={"decision": "approved"}
            )
        ).status_code == 409

        proposal = await client.post(
            proposals, headers=maker, json={**draft, "employee_revision": revision + 1}
        )
        assert proposal.status_code == 201, proposal.text
        change = f"{proposals}/{proposal.json()['id']}"
        assert proposal.json()["updates"] == {"last_name": "Corrected"}
        assert (await client.get(change, headers=owner)).status_code == 403
        assert (await client.post(f"{change}/apply", headers=checker)).status_code == 409
        assert (
            await client.post(f"{change}/decision", headers=maker, json={"decision": "approved"})
        ).status_code == 403
        assert (
            await client.post(f"{change}/decision", headers=checker, json={"decision": "approved"})
        ).status_code == 200
        prior = (await client.get(f"{root}/me", headers=owner)).json()
        assert prior["employee"]["last_name"] == "Prior"
        assert (await client.post(f"{change}/apply", headers=checker)).status_code == 200
        assert (await client.post(f"{change}/apply", headers=checker)).status_code == 200
        corrected = (await client.get(f"{root}/me", headers=owner)).json()
        assert corrected["employee"]["full_name"] == "Synthetic Corrected"
        assert corrected["employee"]["record_revision"] == revision + 2
        assert corrected["personal_phone"] == expected_phone
        history = (await client.get(f"{url}/history", headers=maker)).json()["items"]
        corrections = [item for item in history if item["change_type"] == "profile_correction"]
        assert len(corrections) == 1
        assert corrections[0]["previous_snapshot"]["last_name"] == "Prior"
        assert corrections[0]["new_snapshot"]["last_name"] == "Corrected"
        assert "personal_phone" not in corrections[0]["new_snapshot"]

    async with AsyncSessionLocal() as session:
        audit = (
            await session.scalars(
                select(ActivityLog).where(ActivityLog.entity_id == UUID(employee_id))
            )
        ).all()
        assert "000123" not in str([event.new_values for event in audit])
        assert "000456" not in str([event.new_values for event in audit])


@pytest.mark.asyncio
async def test_application_withdrawal_reconciles_open_records_and_retains_private_evidence() -> (
    None
):
    await skip_if_database_unavailable()
    _, hr_email, password = await _create_portal_user("hr_manager")
    _, prior_reviewer_email, _ = await _create_portal_user("hr_manager", password)
    _, staff_email, _ = await _create_portal_user("quantity_surveyor", password)
    base = "/api/v1/hr"
    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        reviewer = _auth(await _login(client, prior_reviewer_email, password))
        staff = _auth(await _login(client, staff_email, password))

        async def post(path, payload, expected=201):
            result = await client.post(f"{base}/{path}", json=payload, headers=hr)
            assert result.status_code == expected, result.text
            return result.json()

        async def opened_requisition():
            row = await post(
                "requisitions",
                {"requisition_code": f"RET-{uuid4().hex[:8]}", "title": "Synthetic retention"},
            )
            for status in ("submitted", "approved", "open"):
                await post(f"requisitions/{row['id']}/decision", {"status": status}, 200)
            return row["id"]

        async def candidate():
            return await post(
                "candidates",
                {"candidate_code": f"CAN-{uuid4().hex[:8]}", "full_name": "Synthetic Candidate"},
            )

        req_id = await opened_requisition()

        async def staged_offer(candidate_id):
            application = await post(
                "applications", {"requisition_id": req_id, "candidate_id": candidate_id}
            )
            app_id = application["id"]
            await _stage_application_for_interview(client, app_id, hr)
            finished = await post("interviews", {"application_id": app_id})
            assert (
                await client.patch(
                    f"{base}/interviews/{finished['id']}", json={"status": "completed"}, headers=hr
                )
            ).status_code == 200
            assert (
                await client.patch(
                    f"{base}/applications/{app_id}/stage", json={"stage": "evaluation"}, headers=hr
                )
            ).status_code == 200
            scheduled = await post("interviews", {"application_id": app_id, "round_number": 2})
            offer = await post(
                "offers",
                {
                    "offer_code": f"OFR-{uuid4().hex[:8]}",
                    "application_id": app_id,
                    "proposed_title": "Synthetic role",
                },
            )
            for status in ("pending_approval", "approved", "issued"):
                await post(f"offers/{offer['id']}/decision", {"status": status}, 200)
            return app_id, finished["id"], scheduled["id"], offer["id"]

        person = await candidate()
        app_id, completed_id, scheduled_id, offer_id = await staged_offer(person["id"])
        parallel = await post(
            "applications",
            {"candidate_id": person["id"], "requisition_id": await opened_requisition()},
        )
        cv = await client.post(
            f"{base}/documents",
            headers=hr,
            data={
                "title": "Synthetic CV",
                "document_type": "candidate_cv",
                "category": "confidential",
                "candidate_id": person["id"],
            },
            files={"file": ("cv.pdf", _pdf_bytes("retention"), "application/pdf")},
        )
        assert cv.status_code == 201, cv.text
        cv_id = cv.json()["id"]
        decision = await client.post(
            f"{base}/documents/{cv_id}/versions/1/decision",
            headers=reviewer,
            json={"decision": "approve"},
        )
        assert decision.status_code == 200, decision.text

        app_url = f"{base}/applications/{app_id}"
        withdrawal = {
            "expected_stage": "evaluation",
            "reason": "Synthetic private withdrawal reason",
            "retention_decision": "retain_until_review",
            "retention_review_on": (business_today() + timedelta(days=3)).isoformat(),
            "retention_policy_reference": "SYNTHETIC-POLICY",
        }
        confirm = {"stage": "withdrawn", "withdrawal": withdrawal}
        assert (await client.get(app_url, headers=staff)).status_code == 403
        assert (
            await client.patch(f"{app_url}/stage", json=confirm, headers=staff)
        ).status_code == 403
        for invalid in (
            {"stage": "withdrawn"},
            {"stage": "withdrawn", "withdrawal": {**withdrawal, "retention_review_on": None}},
            {
                "stage": "withdrawn",
                "withdrawal": {**withdrawal, "retention_review_on": "2000-01-01"},
            },
        ):
            assert (
                await client.patch(f"{app_url}/stage", json=invalid, headers=hr)
            ).status_code == 422
        stale = {"stage": "withdrawn", "withdrawal": {**withdrawal, "expected_stage": "interview"}}
        assert (await client.patch(f"{app_url}/stage", json=stale, headers=hr)).status_code == 409
        responses = await asyncio.gather(
            client.patch(f"{app_url}/stage", json=confirm, headers=hr),
            client.patch(f"{app_url}/stage", json=confirm, headers=hr),
        )
        assert [response.status_code for response in responses] == [200, 200]
        assert responses[0].json() == responses[1].json()
        result = await client.get(app_url, headers=hr)
        assert result.headers["cache-control"] == "no-store"
        assert result.json()["withdrawn_at"] and result.json()["stage"] == "withdrawn"
        assert result.json()["retention_policy_reference"] == "SYNTHETIC-POLICY"
        assert result.json()["withdrawal_reason"] == withdrawal["reason"]
        assert (await client.get(f"{base}/applications/{parallel['id']}", headers=hr)).json()[
            "stage"
        ] == "applied"
        assert (await client.get(f"{base}/offers/{offer_id}", headers=hr)).json()[
            "status"
        ] == "withdrawn"
        interviews = await client.get(
            f"{base}/interviews", headers=hr, params={"application_id": app_id}
        )
        assert {row["id"]: row["status"] for row in interviews.json()["items"]} == {
            completed_id: "completed",
            scheduled_id: "cancelled",
        }
        for path, payload in (
            ("interviews", {"application_id": app_id}),
            (f"offers/{offer_id}/decision", {"status": "accepted"}),
            (
                f"offers/{offer_id}/reissue",
                {"offer_code": "INVALID", "proposed_title": "Synthetic"},
            ),
            (f"offers/{offer_id}/convert", {"employee_code": "INVALID"}),
        ):
            await post(path, payload, 409)
        assert (
            await client.patch(
                f"{base}/interviews/{scheduled_id}", json={"status": "scheduled"}, headers=hr
            )
        ).status_code == 409
        assert (
            await client.get(f"{base}/documents/{cv_id}/download", headers=hr)
        ).status_code == 200
        assert (
            await client.get(f"{base}/documents/{cv_id}/download", headers=staff)
        ).status_code == 403

        second_person = await candidate()
        racing_application, _, _, racing_offer = await staged_offer(second_person["id"])
        no_policy = {
            "stage": "withdrawn",
            "withdrawal": {
                "expected_stage": "evaluation",
                "reason": "Synthetic pending retention review",
                "retention_decision": "policy_review_required",
            },
        }
        withdrawn, accepted = await asyncio.gather(
            client.patch(
                f"{base}/applications/{racing_application}/stage", json=no_policy, headers=hr
            ),
            client.post(
                f"{base}/offers/{racing_offer}/decision", json={"status": "accepted"}, headers=hr
            ),
        )
        assert sorted([withdrawn.status_code, accepted.status_code]) == [200, 409]
        if withdrawn.status_code == 200:
            assert withdrawn.json()["retention_decision"] == "policy_review_required"
            assert withdrawn.json()["retention_review_on"] is None
        else:
            assert withdrawn.json()["error_code"] == "OFFER_ALREADY_ACCEPTED"

    async with AsyncSessionLocal() as session:
        records = list(
            await session.scalars(
                select(ActivityLog).where(
                    ActivityLog.action == "hr.application.withdrawn",
                    ActivityLog.entity_id == UUID(app_id),
                )
            )
        )
        assert len(records) == 1
        assert records[0].new_values == {
            "retention_decision": "retain_until_review",
            "cancelled_interviews": 1,
            "withdrawn_offers": 1,
        }


def test_garrisonctl_withdrawal_requires_matching_preview_without_printing_reason(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "cli-test-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    actor, application = str(uuid4()), str(uuid4())
    source = tmp_path / "withdrawal.json"
    decision = {
        "expected_stage": "screening",
        "reason": "Synthetic private CLI reason",
        "retention_decision": "policy_review_required",
    }

    def write_decision():
        source.write_text(json.dumps(decision), encoding="utf-8")
        source.chmod(0o600)

    row = {"id": application, "stage": "screening", "updated_at": "2026-11-16T10:00:00Z"}
    writes = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal writes
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": ["hr:recruitment:manage"]})
        path = f"/api/v1/hr/applications/{application}"
        if request.method == "GET" and request.url.path == path:
            return httpx.Response(200, json=row)
        assert request.method == "PATCH" and request.url.path == f"{path}/stage"
        content = json.loads(request.content)
        assert content["stage"] == "withdrawn"
        assert content["withdrawal"]["reason"] == decision["reason"]
        writes += 1
        row.update(
            stage="withdrawn",
            retention_decision="policy_review_required",
            withdrawn_at="2026-11-16T10:01:00Z",
            withdrawal_reason=decision["reason"],
        )
        return httpx.Response(200, json=row)

    def invoke(*options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [
                "hr",
                "applications",
                "withdraw",
                "--application-id",
                application,
                "--decision-file",
                str(source),
                *options,
                "--json",
            ],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        assert decision["reason"] not in stdout.getvalue()
        return code, json.loads(stdout.getvalue())

    write_decision()
    code, initial_plan = invoke("--dry-run")
    assert code == 0 and writes == 0
    decision["reason"] = "Synthetic changed private CLI reason"
    write_decision()
    assert invoke("--apply", "--expect", initial_plan["data"]["plan_sha256"])[0] == 4
    assert writes == 0
    code, preview = invoke("--dry-run")
    assert code == 0
    code, saved = invoke("--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and writes == 1
    assert saved["data"]["stage"] == "withdrawn"


@pytest.mark.asyncio
async def test_candidate_correspondence_is_frozen_independent_and_recruitment_scoped() -> None:
    from app.models.hr import HrCandidate, HrCandidateCorrespondence

    await skip_if_database_unavailable()
    _, maker_email, password = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    _, staff_email, _ = await _create_portal_user("quantity_surveyor", password)
    base = "/api/v1/hr"

    async with _client() as client:
        maker = _auth(await _login(client, maker_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))
        staff = _auth(await _login(client, staff_email, password))

        async def post(path, payload, expected=201, headers=maker):
            result = await client.post(f"{base}/{path}", json=payload, headers=headers)
            assert result.status_code == expected, result.text
            return result.json()

        req = await post(
            "requisitions",
            {"requisition_code": f"LETTER-{uuid4().hex[:8]}", "title": "Synthetic Planner"},
        )
        for status in ("submitted", "approved", "open"):
            await post(f"requisitions/{req['id']}/decision", {"status": status}, 200)
        candidate = await post(
            "candidates",
            {
                "candidate_code": f"CAN-{uuid4().hex[:8]}",
                "full_name": "Synthetic Original",
                "email": "private-candidate@example.com",
            },
        )
        application = await post(
            "applications", {"requisition_id": req["id"], "candidate_id": candidate["id"]}
        )
        id_ = application["id"]
        app_url = f"applications/{id_}"
        letters = f"{app_url}/correspondence"
        await _stage_application_for_interview(client, id_, maker)
        completed = await post("interviews", {"application_id": id_})
        assert (
            await client.patch(
                f"{base}/interviews/{completed['id']}", json={"status": "completed"}, headers=maker
            )
        ).status_code == 200
        assert (
            await client.patch(
                f"{base}/{app_url}/stage", json={"stage": "evaluation"}, headers=maker
            )
        ).status_code == 200
        followup = await post("interviews", {"application_id": id_, "round_number": 2})
        offer = await post(
            "offers",
            {
                "offer_code": f"OFR-{uuid4().hex[:8]}",
                "application_id": id_,
                "proposed_title": "Synthetic Planner",
            },
        )
        for status in ("pending_approval", "approved", "issued"):
            await post(f"offers/{offer['id']}/decision", {"status": status}, 200)
        template = {
            "code": f"CORR-{uuid4().hex[:8]}",
            "name": "Synthetic candidate rejection",
            "letter_type": "candidate_rejection",
            "subject_template": "Application for {position_title}",
            "body_template": "Dear {candidate_name}, thank you for your time.",
        }
        await post("letter-templates", {**template, "body_template": "{rejection_reason}"}, 422)
        template_id = (await post("letter-templates", template))["id"]
        regular_templates = await client.get(f"{base}/letter-templates", headers=maker)
        assert template_id not in [row["id"] for row in regular_templates.json()["items"]]
        candidate_templates = await client.get(
            f"{base}/candidate-correspondence/templates", headers=maker
        )
        assert template_id in [row["id"] for row in candidate_templates.json()["items"]]
        assert (
            await client.get(f"{base}/candidate-correspondence/templates", headers=staff)
        ).status_code == 403

        command = {"draft_id": str(uuid4()), "template_id": template_id}
        await post(letters, command, 409)
        rejected = await client.patch(
            f"{base}/{app_url}/stage",
            headers=maker,
            json={"stage": "rejected", "rejection_reason": "Internal confidential decision"},
        )
        assert rejected.status_code == 200
        await post(f"offers/{offer['id']}/decision", {"status": "accepted"}, 409)
        rows = await client.get(f"{base}/interviews", headers=maker, params={"application_id": id_})
        assert {row["id"]: row["status"] for row in rows.json()["items"]} == {
            completed["id"]: "completed",
            followup["id"]: "cancelled",
        }
        await post(letters, {**command, "extra_vars": {"candidate_name": "Unverified"}}, 422)

        draft = await post(letters, command)
        assert await post(letters, command) == draft
        assert not draft["can_decide"] and draft["status"] == "draft"
        assert draft["subject"] == "Application for Synthetic Planner"
        assert draft["body"] == "Dear Synthetic Original, thank you for your time."
        await post(letters, {**command, "draft_id": str(uuid4())}, 409)
        detail_path = f"{letters}/{draft['id']}"
        assert (await client.get(f"{base}/{detail_path}", headers=staff)).status_code == 403
        scoped = await client.get(
            f"{base}/applications/{uuid4()}/correspondence/{draft['id']}", headers=reviewer
        )
        assert scoped.status_code == 404
        listing = await client.get(f"{base}/{letters}", headers=reviewer)
        assert listing.headers["cache-control"] == "no-store"
        assert listing.json()["items"][0]["can_decide"]
        assert "body" not in listing.json()["items"][0]

        approve = {"decision": "approved", "expected_digest": draft["digest"]}
        await post(f"{detail_path}/decision", approve, 403)
        await post(
            f"{detail_path}/decision", {**approve, "expected_digest": "0" * 64}, 409, reviewer
        )
        async with AsyncSessionLocal() as session:
            stored = await session.get(HrCandidateCorrespondence, UUID(draft["id"]))
            assert stored is not None
            assert "Synthetic Original" not in stored.content_encrypted
            source = await session.get(HrCandidate, UUID(candidate["id"]))
            assert source is not None
            source.full_name = "Synthetic Corrected"
            await session.commit()
        await post(f"{detail_path}/decision", approve, 409, reviewer)
        review = {
            "decision": "rejected",
            "expected_digest": draft["digest"],
            "reason": "Synthetic private review reason",
        }
        await post(f"{detail_path}/decision", review, 200, reviewer)

        fresh = await post(letters, {**command, "draft_id": str(uuid4())})
        decision_path = f"{letters}/{fresh['id']}/decision"
        approve["expected_digest"] = fresh["digest"]
        results = await asyncio.gather(
            post(decision_path, approve, 200, reviewer),
            post(decision_path, approve, 200, reviewer),
        )
        assert results[0] == results[1] and results[0]["status"] == "approved"
        assert "Synthetic Corrected" in results[0]["body"]
        assert "private-candidate" not in str(results[0])
        await post(letters, {**command, "draft_id": str(uuid4())}, 409)

    async with AsyncSessionLocal() as session:
        audit = list(
            await session.scalars(
                select(ActivityLog).where(
                    ActivityLog.entity_type == "hr_candidate_correspondence",
                    ActivityLog.entity_id.in_([UUID(draft["id"]), UUID(fresh["id"])]),
                )
            )
        )
        assert sum(row.action == "hr.candidate_correspondence.approved" for row in audit) == 1
        assert "Synthetic private review reason" not in str([row.new_values for row in audit])
        stored = await session.get(HrCandidateCorrespondence, UUID(draft["id"]))
        assert stored is not None and stored.reason_encrypted is not None
        assert "Synthetic private review reason" not in stored.reason_encrypted


@pytest.mark.asyncio
async def test_recruitment_interviewer_lookup_disambiguates_by_employee_code() -> None:
    await skip_if_database_unavailable()
    _, hr_email, password = await _create_portal_user("hr_manager")
    staff_id, staff_email, _ = await _create_portal_user("quantity_surveyor", password)
    peer_id, _, _ = await _create_portal_user("quantity_surveyor", password)
    inactive_id, _, _ = await _create_portal_user("quantity_surveyor", password)
    decoy_id, _, _ = await _create_portal_user("quantity_surveyor", password)
    name = f"Synthetic Interviewer {uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        staff_row = await session.get(User, staff_id)
        peer = await session.get(User, peer_id)
        inactive = await session.get(User, inactive_id)
        decoy = await session.get(User, decoy_id)
        assert staff_row and staff_row.employee_code and peer and inactive and decoy
        staff_row.full_name = peer.full_name = inactive.full_name = name
        inactive.is_active = False
        code = staff_row.employee_code
        decoy.full_name = code
        expected = {staff_id: code, peer_id: peer.employee_code}
        await session.commit()

    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        staff = _auth(await _login(client, staff_email, password))
        url = "/api/v1/hr/interviews/interviewer-options"
        result = await client.get(url, headers=hr, params={"search": name})
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert result.json()["total"] == 2
        assert {row["id"]: row["employee_code"] for row in result.json()["items"]} == expected
        exact = await client.get(url, headers=hr, params={"search": code.lower(), "limit": 1})
        assert exact.status_code == 200
        assert exact.json()["items"] == [
            {"id": str(staff_id), "full_name": name, "employee_code": code}
        ]
        assert (await client.get(url, headers=staff, params={"search": code})).status_code == 403


@pytest.mark.asyncio
async def test_recruitment_shortlist_filters_and_records_one_manual_stage_event() -> None:
    await skip_if_database_unavailable()
    _, hr_email, password = await _create_portal_user("hr_manager")
    staff_id, staff_email, _ = await _create_portal_user("quantity_surveyor", password)
    base = "/api/v1/hr"
    async with _client() as client:
        hr = _auth(await _login(client, hr_email, password))
        staff = _auth(await _login(client, staff_email, password))

        async def post(path, payload, expected=201):
            result = await client.post(f"{base}/{path}", json=payload, headers=hr)
            assert result.status_code == expected, result.text
            return result.json()

        req = await post(
            "requisitions",
            {"requisition_code": f"SHORT-{uuid4().hex[:8]}", "title": "Synthetic foreman"},
        )
        for status in ("submitted", "approved", "open"):
            await post(f"requisitions/{req['id']}/decision", {"status": status}, 200)
        marker = uuid4().hex[:8]

        async def create_application(name, suffix):
            person = await post(
                "candidates",
                {
                    "candidate_code": f"{marker}-{suffix}",
                    "full_name": name,
                    "email": f"short-{suffix}-{marker}@example.com",
                },
            )
            candidate_path = f"{base}/candidates/{person['id']}"
            assert (await client.get(candidate_path, headers=staff)).status_code == 403
            detail = await client.get(candidate_path, headers=hr)
            assert detail.status_code == 200 and detail.headers["cache-control"] == "no-store"
            assert detail.json()["id"] == person["id"]
            await post(
                "applications",
                {
                    "candidate_id": person["id"],
                    "requisition_id": req["id"],
                    "expected_requisition_updated_at": req["updated_at"],
                },
                409,
            )
            return await post(
                "applications",
                {"candidate_id": person["id"], "requisition_id": req["id"]},
            )

        current = await create_application("Synthetic 100% Candidate", "FIRST")
        another = await create_application("Synthetic Other Candidate", "SECOND")
        app_id = current["id"]
        stage_url = f"{base}/applications/{app_id}/stage"
        history_url = f"{base}/applications/{app_id}/activity"

        assert (
            await client.patch(stage_url, headers=staff, json={"stage": "shortlisted"})
        ).status_code == 403
        assert (await client.get(history_url, headers=staff)).status_code == 403
        await post("interviews", {"application_id": app_id}, 409)
        assert (
            await client.patch(stage_url, headers=hr, json={"stage": "shortlisted"})
        ).status_code == 409
        assert (
            await client.patch(stage_url, headers=hr, json={"stage": "screening"})
        ).status_code == 200
        assert (
            await client.patch(
                stage_url,
                headers=hr,
                json={"stage": "shortlisted", "expected_updated_at": current["updated_at"]},
            )
        ).status_code == 409
        await post("interviews", {"application_id": app_id}, 409)
        assert (
            await client.patch(stage_url, headers=hr, json={"stage": "interview"})
        ).status_code == 409
        both = await asyncio.gather(
            client.patch(stage_url, headers=hr, json={"stage": "shortlisted"}),
            client.patch(stage_url, headers=hr, json={"stage": "shortlisted"}),
        )
        assert sorted(result.status_code for result in both) == [200, 409]

        url = f"{base}/applications"
        exact = await client.get(
            url,
            headers=hr,
            params={"requisition_id": req["id"], "candidate_id": current["candidate_id"]},
        )
        assert exact.status_code == 200 and exact.json()["total"] == 1
        assert exact.json()["items"][0]["id"] == app_id
        page = {"requisition_id": req["id"], "search": marker, "limit": 1}
        first = await client.get(url, headers=hr, params=page)
        assert first.status_code == 200 and first.json()["total"] == 2
        second = await client.get(url, headers=hr, params={**page, "offset": 1})
        assert {first.json()["items"][0]["id"], second.json()["items"][0]["id"]} == {
            app_id,
            another["id"],
        }
        found = await client.get(
            url, headers=hr, params={**page, "search": "%", "stage": "shortlisted"}
        )
        assert found.json()["total"] == 1
        item = found.json()["items"][0]
        assert item["id"] == app_id and item["candidate_name"] == "Synthetic 100% Candidate"
        assert item["position_title"] == "Synthetic foreman" and "email" not in item
        assert (await client.get(url, headers=staff, params=page)).status_code == 403
        options_url = f"{base}/interviews/interviewer-options"
        assert (await client.get(options_url, headers=staff)).status_code == 403
        options = await client.get(
            options_url, headers=hr, params={"search": "Synthetic quantity_surveyor", "limit": 100}
        )
        assert options.status_code == 200 and options.headers["cache-control"] == "no-store"
        staff_option = next(row for row in options.json()["items"] if row["id"] == str(staff_id))
        assert staff_option["full_name"] == "Synthetic quantity_surveyor"
        assert set(staff_option) == {"id", "full_name", "employee_code"}

        schedule = {
            "application_id": app_id,
            "interview_id": str(uuid4()),
            "scheduled_at": "2027-02-12T11:00:00+03:00",
            "expected_application_updated_at": item["updated_at"],
            "interviewer_user_id": str(staff_id),
        }
        await post("interviews", {**schedule, "interviewer_user_id": str(uuid4())}, 422)
        await post(
            "interviews",
            {**schedule, "expected_application_updated_at": "2001-01-01T00:00:00Z"},
            409,
        )
        assert (
            await client.post(f"{base}/interviews", headers=staff, json=schedule)
        ).status_code == 403
        scheduled = await asyncio.gather(
            client.post(f"{base}/interviews", headers=hr, json=schedule),
            client.post(f"{base}/interviews", headers=hr, json=schedule),
        )
        assert all(response.status_code == 201 for response in scheduled)
        interview = scheduled[0].json()
        assert {response.json()["id"] for response in scheduled} == {schedule["interview_id"]}
        await post("interviews", {**schedule, "round_number": 2}, 409)
        assert (
            await client.get(f"{base}/interviews", headers=hr, params={"application_id": app_id})
        ).json()["total"] == 1
        async with AsyncSessionLocal() as session:
            invitations = list(
                await session.scalars(
                    select(Notification).where(
                        Notification.user_id == staff_id,
                        Notification.notification_type == "hr_interview_invitation",
                    )
                )
            )
            assert len(invitations) == 1
            assert invitations[0].body == (
                "HR has invited you to an interview. Contact HR for the schedule and details."
            )
            assert invitations[0].email_status is None and invitations[0].reference_id is None
        assert (
            await client.patch(stage_url, headers=hr, json={"stage": "interview"})
        ).status_code == 200
        assert (
            await client.patch(stage_url, headers=hr, json={"stage": "evaluation"})
        ).status_code == 409
        interview_path = f"{base}/interviews/{interview['id']}"
        updates = await asyncio.gather(
            *(
                client.patch(
                    interview_path,
                    headers=hr,
                    json={
                        "status": "completed",
                        "recommendation": value,
                        "expected_updated_at": interview["updated_at"],
                    },
                )
                for value in ("hire", "hold")
            )
        )
        assert sorted(response.status_code for response in updates) == [200, 409]
        assert (
            await client.patch(stage_url, headers=hr, json={"stage": "evaluation"})
        ).status_code == 200

        history = await client.get(history_url, headers=hr, params={"limit": 3})
        assert history.headers["cache-control"] == "no-store"
        assert history.json()["total"] == 5
        rows = history.json()["items"]
        assert [row["stage"] for row in rows] == ["evaluation", "interview", "shortlisted"]
        assert set(rows[2]) == {"id", "stage", "actor_name", "created_at"}
        assert rows[2]["actor_name"] == "Synthetic hr_manager"
        older = await client.get(history_url, headers=hr, params={"limit": 3, "offset": 3})
        assert [row["stage"] for row in older.json()["items"]] == ["screening", "applied"]


def test_garrisonctl_shortlist_rechecks_application_and_verifies_stage(monkeypatch):
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "cli-test-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    actor, application = str(uuid4()), str(uuid4())
    row = {"id": application, "stage": "screening", "updated_at": "2026-11-16T10:00:00Z"}
    writes = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal writes
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": ["hr:recruitment:manage"]})
        path = f"/api/v1/hr/applications/{application}"
        if request.method == "GET" and request.url.path == path:
            return httpx.Response(200, json=row)
        assert request.method == "PATCH" and request.url.path == f"{path}/stage"
        assert json.loads(request.content) == {
            "stage": "shortlisted",
            "expected_updated_at": row["updated_at"],
        }
        writes += 1
        row.update(stage="shortlisted", updated_at="2026-11-16T10:02:00Z")
        return httpx.Response(200, json=row)

    def invoke(*options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [
                "hr",
                "applications",
                "shortlist",
                "--application-id",
                application,
                *options,
                "--json",
            ],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        return code, json.loads(stdout.getvalue())

    code, preview = invoke("--dry-run")
    assert code == 0 and writes == 0
    row["updated_at"] = "2026-11-16T10:01:00Z"
    assert invoke("--apply", "--expect", preview["data"]["plan_sha256"])[0] == 4
    assert writes == 0
    code, preview = invoke("--dry-run")
    assert code == 0
    code, saved = invoke("--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and writes == 1
    assert saved["data"]["stage"] == "shortlisted"
    assert invoke("--dry-run")[0] == 4


def test_company_policy_cli_binds_attachment_and_refuses_unverified_download(
    tmp_path, monkeypatch,
) -> None:
    import hashlib

    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-policy-cli")
    actor, doc_id, policy_id = (str(uuid4()) for _ in range(3))
    expected_bytes = b"%PDF-1.4 synthetic approved edition"
    expected_hash = hashlib.sha256(expected_bytes).hexdigest()
    current_hash = expected_hash
    private_summary = "Private simulated policy summary"
    published: list[dict[str, str | int | bool]] = []
    source = tmp_path / "edition.json"
    source.write_text(json.dumps({
        "code": "SYNTH-POL",
        "title": "Synthetic policy",
        "version": "1.0",
        "effective_date": "2026-01-01",
        "content_summary": private_summary,
        "document_id": doc_id,
        "document_version_number": 1,
    }), encoding="utf-8")
    source.chmod(0o600)
    download = tmp_path / "requested.pdf"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/auth/me":
            return httpx.Response(200, json={
                "id": actor, "role": "hr_manager",
                "permissions": ["hr:employees:read", "hr:policy:manage"],
            })
        if path == f"/api/v1/hr/documents/{doc_id}":
            return httpx.Response(200, json={
                "id": doc_id, "category": "ordinary", "document_type": "policy",
                "current_version": 1,
                "versions": [
                    {"status": "active", "version_number": 1, "sha256_checksum": current_hash}
                ],
            })
        if path == "/api/v1/hr/policies" and request.method == "POST":
            body = json.loads(request.content)
            result = {**body, "id": policy_id, "published_at": "2026-01-01T00:00:00Z"}
            published.append(result)
            return httpx.Response(201, json=result)
        if path == "/api/v1/hr/policies":
            return httpx.Response(200, json={"items": published})
        if path == "/api/v1/hr/me/policies":
            item = {**published[0], "is_current": True, "acknowledged_at": None}
            return httpx.Response(200, json={"items": [item]})
        if path == f"/api/v1/hr/me/policies/{policy_id}/download":
            return httpx.Response(200, json={
                "document_id": doc_id, "version_number": 1, "file_size": len(expected_bytes),
                "sha256_checksum": expected_hash, "download_url": "https://test.example.invalid/x",
            })
        return httpx.Response(404)

    def call(*args: str) -> tuple[int, dict]:
        output = io.StringIO()
        code = garrisonctl.run(
            ["hr", *args, "--json"],
            transport=httpx.MockTransport(handler), stdout=output, stderr=io.StringIO(),
        )
        return code, json.loads(output.getvalue())

    publish = ("company-policy", "publish", "--file", str(source))
    code, preview = call(*publish, "--dry-run")
    assert code == 0 and not published and private_summary not in json.dumps(preview)
    current_hash = "0" * 64
    assert call(*publish, "--apply", "--expect", preview["data"]["plan_sha256"])[0] == 4
    assert not published
    current_hash = expected_hash
    code, result = call(*publish, "--apply", "--expect", preview["data"]["plan_sha256"])
    assert code == 0 and result["data"]["id"] == policy_id
    assert private_summary not in json.dumps(result)
    assert call(
        "my-policy", "acknowledge", "--policy-id", policy_id, "--edition", "2.0",
        "--file-version", "1", "--dry-run",
    )[0] == 4
    monkeypatch.setattr(
        "scripts.garrisonctl_hr._read_signed_hr_file", lambda *_: b"x" * len(expected_bytes)
    )
    download_args = ("my-policy", "download", "--policy-id", policy_id, "--output", str(download))
    assert call(*download_args)[0] == 4
    assert not download.exists()


@pytest.mark.asyncio
async def test_policy_editions_keep_exact_versions_and_employee_receipts(monkeypatch) -> None:
    import hashlib

    from app.models.hr import HrPolicyAcknowledgement, HrPolicyDocument

    await skip_if_database_unavailable()
    today = date(2026, 11, 16)
    monkeypatch.setattr("app.services.hr_workforce_service.business_today", lambda: today)
    _, hr_email, password = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", password)
    _, director_email, _ = await _create_portal_user("managing_director", password)
    owner_id, owner_email, _ = await _create_portal_user("quantity_surveyor", password)
    other_id, other_email, _ = await _create_portal_user("quantity_surveyor", password)
    _, unlinked_email, _ = await _create_portal_user("quantity_surveyor", password)
    base = "/api/v1/hr"
    me = f"{base}/me/policies"
    async with _client() as client:
        maker = _auth(await _login(client, hr_email, password))
        reviewer = _auth(await _login(client, reviewer_email, password))
        director = _auth(await _login(client, director_email, password))
        employee = _auth(await _login(client, owner_email, password))
        other = _auth(await _login(client, other_email, password))
        unlinked = _auth(await _login(client, unlinked_email, password))

        async def link(email, user_id):
            result = await client.post(
                f"{base}/employees",
                headers=maker,
                json={
                    "employee_code": f"POL-{uuid4().hex[:8]}",
                    "first_name": "Synthetic",
                    "last_name": "Reader",
                    "work_email": email,
                    "employment_status": "active",
                    "join_date": "2025-01-01",
                },
            )
            assert result.status_code == 201, result.text
            linked = await client.post(
                f"{base}/employees/{result.json()['id']}/link-account",
                headers=director,
                json={"user_id": user_id},
            )
            assert linked.status_code == 200
            return result.json()["id"]

        owner_employee_id = await link(owner_email, owner_id)
        await link(other_email, other_id)

        metadata = {
            "title": "Synthetic policy asset",
            "document_type": "policy",
            "category": "ordinary",
        }
        file_v1 = {
            "file": ("policy-original.pdf", _pdf_bytes("policy original"), "application/pdf")
        }
        file_v2 = {
            "file": ("policy-replacement.pdf", _pdf_bytes("policy replacement"), "application/pdf")
        }
        assert (
            await client.post(
                f"{base}/documents",
                headers=maker,
                files=file_v1,
                data={**metadata, "employee_id": owner_employee_id},
            )
        ).status_code == 422
        file = await client.post(f"{base}/documents", headers=maker, files=file_v1, data=metadata)
        assert file.status_code == 201, file.text
        document_id = file.json()["id"]
        document = f"{base}/documents/{document_id}"

        async def publish(*, status=201, **values):
            payload = {
                "code": f"ED-{uuid4().hex[:8]}",
                "title": "Synthetic Safety Policy",
                "effective_date": "2026-11-15",
                "content_summary": "Synthetic policy summary",
                "document_id": document_id,
                "document_version_number": 1,
                **values,
            }
            response = await client.post(f"{base}/policies", headers=maker, json=payload)
            assert response.status_code == status, response.text
            return response.json()

        await publish(status=409)
        await publish(status=422, document_version_number=None)
        assert (
            await client.post(
                f"{document}/versions/1/decision", headers=reviewer, json={"decision": "approve"}
            )
        ).status_code == 200
        first = await publish()
        policy_id = first["id"]
        edition = f"{me}/{policy_id}"
        draft = {"expected_version": "1.0", "expected_document_version": 1}
        download = await client.get(f"{edition}/download", headers=employee)
        assert download.status_code == 200 and download.headers["cache-control"] == "no-store"
        assert download.json()["file_name"] == "policy-original.pdf"
        assert download.json()["file_size"] == len(file_v1["file"][1])
        assert download.json()["sha256_checksum"] == hashlib.sha256(file_v1["file"][1]).hexdigest()
        assert (await client.get(f"{edition}/download", headers=unlinked)).status_code == 404
        assert (
            await client.get(f"{base}/me/documents/{document_id}/download", headers=employee)
        ).status_code == 404
        assert (
            await client.post(
                f"{edition}/acknowledge",
                headers=employee,
                json={**draft, "expected_document_version": 2},
            )
        ).status_code == 409
        concurrent = await asyncio.gather(
            client.post(f"{edition}/acknowledge", headers=employee, json=draft),
            client.post(f"{edition}/acknowledge", headers=employee, json=draft),
        )
        assert all(response.status_code == 200 for response in concurrent)
        assert concurrent[0].json() == concurrent[1].json()
        assert concurrent[0].json()["document_version_number"] == 1

        assert (
            await client.post(f"{document}/versions", files=file_v2, headers=maker)
        ).status_code == 201
        assert (
            await client.post(
                f"{document}/versions/2/decision", headers=reviewer, json={"decision": "approve"}
            )
        ).status_code == 200
        assert (await client.get(f"{edition}/download", headers=employee)).json()[
            "file_name"
        ] == "policy-original.pdf"
        await publish(status=409)
        replacement = await publish(
            version="2.0",
            document_version_number=2,
            effective_date="2026-11-17",
            supersedes_policy_id=policy_id,
        )
        await publish(
            status=409,
            version="2.1",
            document_version_number=2,
            effective_date="2026-11-18",
            supersedes_policy_id=policy_id,
        )
        successor = f"{me}/{replacement['id']}"
        request = {"expected_version": "2.0", "expected_document_version": 2}
        assert (await client.get(f"{successor}/download", headers=employee)).status_code == 404
        assert (
            await client.post(f"{successor}/acknowledge", headers=employee, json=request)
        ).status_code == 404
        assert (await client.get(f"{edition}/download", headers=other)).status_code == 200
        today = date(2026, 11, 17)
        listing = await client.get(me, headers=employee)
        by_id = {row["id"]: row for row in listing.json()["items"]}
        assert by_id[policy_id]["acknowledged_at"] and not by_id[policy_id]["is_current"]
        assert (
            by_id[replacement["id"]]["is_current"]
            and not by_id[replacement["id"]]["acknowledged_at"]
        )
        assert (await client.get(f"{edition}/download", headers=other)).status_code == 404
        assert (await client.get(f"{successor}/download", headers=other)).json()[
            "file_name"
        ] == "policy-replacement.pdf"
        assert (
            await client.post(f"{edition}/acknowledge", headers=other, json=draft)
        ).status_code == 404
        receipt = await client.post(f"{successor}/acknowledge", headers=employee, json=request)
        assert receipt.status_code == 200
        assert receipt.json()["policy_version"] == "2.0"

        async with AsyncSessionLocal() as session:
            legacy = HrPolicyDocument(
                code=f"LEGACY-{uuid4().hex[:8]}",
                title="Synthetic legacy link",
                version="1.0",
                effective_date=today,
                content_summary="Body",
                document_id=UUID(document_id),
                published_at=datetime.now(UTC),
            )
            session.add(legacy)
            await session.flush()
            legacy_id = legacy.id
            await session.commit()
        assert (await client.get(f"{me}/{legacy_id}/download", headers=employee)).status_code == 409
        assert (
            await client.post(
                f"{me}/{legacy_id}/acknowledge", headers=employee, json={"expected_version": "1.0"}
            )
        ).status_code == 409

    async with AsyncSessionLocal() as session:
        receipts = list(
            await session.scalars(
                select(HrPolicyAcknowledgement).where(
                    HrPolicyAcknowledgement.employee_id == UUID(owner_employee_id),
                    HrPolicyAcknowledgement.policy_id.in_(
                        [UUID(policy_id), UUID(replacement["id"])]
                    ),
                )
            )
        )
        assert len(receipts) == 2


@pytest.mark.asyncio
async def test_leave_schedule_uses_open_ended_shift_and_rejects_overlaps() -> None:
    await skip_if_database_unavailable()
    day = date(2026, 11, 26)
    employee_id = uuid4()
    default_calendar_id, shift_calendar_id = uuid4(), uuid4()
    async with AsyncSessionLocal() as session:
        default_calendar = HrWorkCalendar(
            id=default_calendar_id,
            code=f"LV-DEFAULT-{uuid4().hex[:8]}",
            name="Synthetic default leave calendar",
            work_days_json=["MON"],
            is_default=True,
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
            timezone="UTC",
            status="published",
            published_at=datetime.now(UTC),
        )
        shift_calendar = HrWorkCalendar(
            id=shift_calendar_id,
            code=f"LV-SHIFT-{uuid4().hex[:8]}",
            name="Synthetic shift leave calendar",
            work_days_json=["THU"],
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
            timezone="UTC",
            status="published",
            published_at=datetime.now(UTC),
        )
        employee = HrEmployee(
            id=employee_id,
            employee_code=f"LV-SHIFT-{uuid4().hex[:8]}",
            first_name="Synthetic",
            last_name="Shift",
            full_name="Synthetic Open Shift",
            employment_status="active",
            join_date=date(2020, 1, 1),
            work_calendar_id=default_calendar_id,
        )
        session.add_all([default_calendar, shift_calendar])
        await session.flush()
        session.add(employee)
        await session.flush()
        session.add(
            HrShiftAssignment(
                id=uuid4(),
                employee_id=employee_id,
                calendar_id=shift_calendar_id,
                shift_name="Open-ended synthetic shift",
                effective_from=day,
                effective_to=None,
                start_time=time(8),
                end_time=time(17),
            )
        )
        await session.flush()
        service = HrWorkforceService(session)
        assert await service._leave_work_dates(employee, day, 1) == [day]

        session.add(
            HrShiftAssignment(
                id=uuid4(),
                employee_id=employee_id,
                calendar_id=shift_calendar_id,
                shift_name="Overlapping synthetic shift",
                effective_from=day,
                effective_to=None,
                start_time=time(9),
                end_time=time(18),
            )
        )
        await session.flush()
        with pytest.raises(AppException) as ambiguous:
            await service._leave_work_dates(employee, day, 1)
        assert ambiguous.value.error_code == "LEAVE_SCHEDULE_AMBIGUOUS"
        await session.rollback()
