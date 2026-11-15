"""Comprehensive HR & Workforce Management test suite (HR-A through HR-J + CLI)."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import zlib
from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4
from zipfile import ZipFile

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.hr import (
    HrAttendanceEntry,
    HrCertification,
    HrDepartment,
    HrDocument,
    HrDocumentVersion,
    HrEmployee,
    HrEmployeePrivate,
    HrLeaveLedger,
    HrOnboardingCase,
    HrServiceRequest,
)
from app.models.notification import Notification
from app.models.project import Project
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.hr_crypto import encrypt_hr_value
from app.tasks.maintenance import _check_hr_credential_expiry, _check_hr_service_request_sla
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
        assert report["training_sessions_due"] is None
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
                    b"training sessions",
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
        await session.commit()
    runs = sorted(
        await asyncio.gather(_check_hr_service_request_sla(), _check_hr_service_request_sla())
    )
    assert runs[0] == 0 and runs[1] >= 1
    assert await _check_hr_service_request_sla() == 0
    enqueue.assert_not_called()
    tracked_users = [UUID(value) for value in (manager, director, inactive)]
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(
                select(Notification).where(
                    Notification.user_id.in_(tracked_users),
                    Notification.notification_type == "hr_service_request_sla",
                )
            )
        ).all()
        assert [str(row.user_id) for row in rows] == [manager]
        assert rows[0].reference_id is None and rows[0].email_status is None
        assert marker not in f"{rows[0].title} {rows[0].body}"
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
            json={"national_id": "901234567V"},
            headers=_auth(tok),
        )
        assert priv_put.status_code == 200
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

        req = await client.post(
            "/api/v1/hr/requisitions",
            json={"requisition_code": f"REQ-{uuid4().hex[:5]}", "title": "Site Foreman"},
            headers=_auth(tok),
        )
        assert req.status_code == 201
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
        for next_stage in ("screening", "interview", "evaluation"):
            assert (
                await client.patch(
                    f"/api/v1/hr/applications/{app_id}/stage",
                    json={"stage": next_stage},
                    headers=_auth(tok),
                )
            ).status_code == 200

        offer = await client.post(
            "/api/v1/hr/offers",
            json={
                "offer_code": f"OFR-{uuid4().hex[:5]}",
                "application_id": app_id,
                "proposed_title": "Site Foreman",
            },
            headers=_auth(tok),
        )
        assert offer.status_code == 201
        offer_id = offer.json()["id"]

        for status_step in ("pending_approval", "approved", "issued", "accepted"):
            res = await client.post(
                f"/api/v1/hr/offers/{offer_id}/decision",
                json={"status": status_step},
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
        assert (
            await client.post(
                f"/api/v1/hr/timesheets/{ts.json()['id']}/decision",
                json={"decision": "approved"},
                headers=_auth(tok),
            )
        ).status_code == 200


@pytest.mark.asyncio
async def test_work_calendar_requires_independent_review_and_preserves_published_rules() -> None:
    await skip_if_database_unavailable()
    _, preparer_email, pw = await _create_portal_user("hr_manager")
    _, reviewer_email, _ = await _create_portal_user("hr_manager", pw)
    _, executive_email, _ = await _create_portal_user("hr_manager", pw)
    _, staff_email, _ = await _create_portal_user("quantity_surveyor", pw)
    async with AsyncSessionLocal() as session:
        project = Project(
            name="Calendar test site",
            code=f"HR-{uuid4().hex[:10]}",
            scope_of_work="Test scheduling",
            target_end_date=date(2027, 12, 31),
        )
        session.add(project)
        await session.flush()
        project_id = str(project.id)
        await session.commit()

    async with _client() as client:
        preparer = _auth(await _login(client, preparer_email, pw))
        reviewer = _auth(await _login(client, reviewer_email, pw))
        executive = _auth(await _login(client, executive_email, pw))
        staff = _auth(await _login(client, staff_email, pw))
        employee = await client.post(
            "/api/v1/hr/employees",
            headers=preparer,
            json={
                "employee_code": f"CAL-{uuid4().hex[:8]}",
                "first_name": "Synthetic",
                "last_name": "Worker",
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

        attendance_path = "/api/v1/hr/attendance"
        attendance = {
            "employee_id": employee_id,
            "work_date": "2027-01-05",
            "attendance_status": "present",
            "check_in_at": "2027-01-04T20:00:00Z",
            "check_out_at": "2027-01-05T04:00:00Z",
            "worked_hours": "8.00",
        }
        wrong_local_date = await client.post(
            attendance_path,
            json={**attendance, "check_in_at": "2027-01-04T17:00:00Z"},
            headers=executive,
        )
        assert wrong_local_date.status_code == 422
        recorded = await client.post(attendance_path, json=attendance, headers=executive)
        assert recorded.status_code == 201, recorded.text
        assert recorded.json()["calendar_id"] == calendar["id"]
        assert recorded.json()["scheduled_workday"] is True
        assert recorded.json()["shift_assignment_id"] is not None

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
        leave_type_id = leave_type.json()["id"]
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
        assert leave.json()["requires_manager_recommendation"]
        advice = f"{queue}/leave/{leave_id}"
        final_leave = f"{base}/leave/requests/{leave_id}/decision"
        decision = {"decision": "approved", "expected_revision": 1}
        assert (await client.post(final_leave, headers=manager, json=decision)).status_code == 403
        too_early = await client.post(final_leave, headers=hr, json=decision)
        assert (
            too_early.status_code == 409
            and too_early.json()["error_code"] == "MANAGER_RECOMMENDATION_REQUIRED"
        )
        assert (await client.get(queue, headers=executive)).json()["items"] == []
        assert (
            await client.post(
                advice, headers=worker, json={"recommendation": "support", "expected_revision": 1}
            )
        ).status_code == 404

        row = (await client.get(queue, headers=manager)).json()["items"][0]
        assert set(row) == {
            "kind",
            "id",
            "employee_name",
            "start_date",
            "end_date",
            "requested_amount",
            "record_revision",
        }
        assert row["kind"] == "leave" and row["id"] == leave_id
        attempts = await asyncio.gather(
            *(
                client.post(
                    advice,
                    headers=manager,
                    json={
                        "recommendation": "flag",
                        "expected_revision": 1,
                    },
                )
                for _ in range(2)
            )
        )
        assert sorted(response.status_code for response in attempts) == [200, 409]
        async with AsyncSessionLocal() as session:
            assert not (
                await session.scalars(
                    select(HrLeaveLedger.id).where(
                        HrLeaveLedger.reference_request_id == UUID(leave_id)
                    )
                )
            ).all()
        assert (await client.post(final_leave, headers=hr, json=decision)).status_code == 409
        finals = await asyncio.gather(
            *(
                client.post(
                    final_leave,
                    headers=hr,
                    json={
                        **decision,
                        "expected_revision": 2,
                    },
                )
                for _ in range(2)
            )
        )
        assert sorted(response.status_code for response in finals) == [200, 409]
        assert (
            await client.post(
                final_leave,
                headers=hr,
                json={
                    "decision": "cancelled",
                    "expected_revision": 3,
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
    _, hrm_email, pw = await _create_portal_user("hr_manager")
    staff_uid, staff_email, _ = await _create_portal_user("quantity_surveyor", pw)

    async with _client() as client:
        hrm_tok = await _login(client, hrm_email, pw)
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
        lt_id = lt.json()["id"]

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
                "leave_type_id": lt_id,
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "days_requested": "2.00",
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
                "start_date": "2026-07-05",
                "end_date": "2026-07-05",
                "days_requested": "1.00",
                "is_half_day": False,
                "submit_immediately": True,
            },
            headers=_auth(hrm_tok),
        )
        assert (
            await client.post(
                f"/api/v1/hr/leave/requests/{self_req.json()['id']}/decision",
                json={"decision": "approved"},
                headers=_auth(hrm_tok),
            )
        ).status_code == 403

        # Two approvals for one request may post only one ledger debit.
        async def approve():
            return await client.post(
                f"/api/v1/hr/leave/requests/{lr_id}/decision",
                json={"decision": "approved"},
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

        # Cancel approved leave -> reverses ledger back to 14 days
        assert (
            await client.post(
                f"/api/v1/hr/leave/requests/{lr_id}/decision",
                json={"decision": "cancelled"},
                headers=_auth(hrm_tok),
            )
        ).status_code == 200
        bal2 = (
            await client.get(
                f"/api/v1/hr/leave/balances/{emp_id}?leave_year=2026", headers=_auth(hrm_tok)
            )
        ).json()["items"]
        bal2_item = next(item for item in bal2 if item["leave_type_id"] == lt_id)
        assert float(bal2_item["balance_days"]) == pytest.approx(14.0)


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
                "expected_updated_at": review.json()["updated_at"],
                "generated_document_id": doc_id,
                "resolution_notes": "Synthetic response delivered.",
            },
        )
        assert approved.status_code == 200
        completed = await client.post(
            resolve,
            headers=hr,
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


@pytest.mark.asyncio
async def test_hr_i_policies_letters_requests_and_offboarding() -> None:
    await skip_if_database_unavailable()
    _, admin_email, pw = await _create_portal_user("managing_director")
    _, hrm_email, _ = await _create_portal_user("hr_manager", pw)
    _, hre_email, _ = await _create_portal_user("hr_manager", pw)
    staff_uid, staff_email, _ = await _create_portal_user("quantity_surveyor", pw)

    async with _client() as client:
        admin_tok = await _login(client, admin_email, pw)
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
                json={"notes": "Read and agreed"},
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
        assert rendered.status_code == 200
        assert "Exit User" in rendered.json()["body"]
        override = await client.post(
            "/api/v1/hr/letters/render",
            json={
                "template_id": tpl.json()["id"],
                "employee_id": emp_id,
                "extra_vars": {"full_name": "different employee"},
            },
            headers=_auth(hrm_tok),
        )
        assert override.status_code == 422
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

        # Offboarding clearance gate
        ob = await client.post(
            "/api/v1/hr/offboarding",
            json={
                "employee_id": emp_id,
                "separation_type": "resignation",
                "last_working_date": "2026-07-31",
            },
            headers=_auth(hrm_tok),
        )
        assert ob.status_code == 201
        case_id = ob.json()["id"]

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
            assert (
                await client.patch(
                    f"/api/v1/hr/offboarding/steps/{step['id']}",
                    json={"status": "cleared", "notes": "Cleared"},
                    headers=_auth(hrm_tok),
                )
            ).status_code == 200

        done = await client.post(
            f"/api/v1/hr/offboarding/{case_id}/complete",
            json={"rehire_eligible": True, "exit_interview_notes": "Synthetic interview"},
            headers=_auth(hrm_tok),
        )
        assert done.status_code == 200
        assert done.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_hr_j_payroll_policy_gate_cases_and_cli() -> None:
    await skip_if_database_unavailable()
    _, email, password = await _create_portal_user("hr_manager")
    async with _client() as client:
        token = await _login(client, email, password)
        for endpoint in ("/payroll/policies", "/payroll/runs", "/cases", "/reviews"):
            response = await client.get(f"/api/v1/hr{endpoint}", headers=_auth(token))
            assert response.status_code == 403


def test_garrisonctl_hr_cli_preview_and_apply(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "cli-test-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)

    actor_id = str(uuid4())
    emp_id = str(uuid4())
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
                    "id": actor_id,
                    "role": "hr_manager",
                    "permissions": ["hr:employees:manage", "hr:employees:read"],
                },
                headers={"X-Request-ID": "cli-auth"},
            )
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
