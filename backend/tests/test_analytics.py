from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import ZipFile

import httpx
import pytest

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.daily_report import DailyReport
from app.models.finance import Invoice, Payment
from app.models.inventory import InventoryItem, InventoryMovement
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.tasks.report import generate_excel_export
from app.utils.security import utc_now
from tests.password_fixtures import hash_fixture_password
from tests.test_blocking_io_offload import pdf_text

ANALYTICS_PATHS = (
    "/api/v1/analytics/summary",
    "/api/v1/export/project-progress",
    "/api/v1/export/material-usage",
    "/api/v1/export/management-summary",
)


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


async def create_user(role: str, password: str = "Start123!") -> tuple[User, str]:
    user = User(
        email=f"analytics-{role}-{uuid4().hex}@example.com",
        full_name=f"{role} Analytics User",
        role=role,
        employee_code=f"ANL-{uuid4().hex[:8]}",
        phone="+97455551000",
        designation=role.replace("_", " ").title(),
        password_hash=hash_fixture_password(password),
        must_change_password=False,
    )
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(user)
        await session.commit()
        await session.refresh(user)
    return user, password


def create_test_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def login_for_token(client: httpx.AsyncClient, user: User, password: str) -> str:
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )
    challenge = login_response.json()
    verify_response = await client.post(
        "/api/v1/auth/verify-otp",
        json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
    )
    return str(verify_response.json()["access_token"])


@pytest.mark.asyncio
async def test_scoped_dashboard_analytics_requires_no_general_project_access() -> None:
    await skip_if_database_unavailable()
    manager, manager_password = await create_user("operations_director")
    engineer, engineer_password = await create_user("quantity_surveyor")

    async with create_test_client() as client:
        manager_token = await login_for_token(client, manager, manager_password)
        engineer_token = await login_for_token(client, engineer, engineer_password)

        summary = await client.get(
            "/api/v1/analytics/summary",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert summary.status_code == 200
        assert "projects" in summary.json()

        export = await client.get(
            "/api/v1/export/project-progress",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert export.status_code == 200
        assert export.content.startswith(b"PK")
        with ZipFile(BytesIO(export.content)) as workbook:
            metadata = ElementTree.fromstring(workbook.read("docProps/custom.xml"))
        assert "cumulative" in "".join(metadata.itertext())

        reversed_dates = {"date_from": "2026-05-31", "date_to": "2026-05-30"}
        for path in ANALYTICS_PATHS:
            invalid = await client.get(
                path, params=reversed_dates, headers={"Authorization": f"Bearer {manager_token}"}
            )
            assert invalid.status_code == 422
            assert invalid.json()["error_code"] == "INVALID_ANALYTICS_DATE_RANGE"

        # Quantity Surveyors have dashboard:scoped but no general project read. Their
        # analytics endpoints are allowed and must remain empty without membership.
        scoped_headers = {"Authorization": f"Bearer {engineer_token}"}
        scoped_summary = await client.get(ANALYTICS_PATHS[0], headers=scoped_headers)
        assert scoped_summary.status_code == 200
        assert scoped_summary.json() == {"projects": [], "material_usage": []}
        for path in ANALYTICS_PATHS[1:]:
            scoped_export = await client.get(path, headers=scoped_headers)
            assert scoped_export.status_code == 200, path
            assert scoped_export.content


def test_generate_excel_export_requires_actor_id() -> None:
    with pytest.raises(ValueError, match="Export actor is required"):
        generate_excel_export()


def test_generate_excel_export_delegates_to_management_export(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_generate(export_type: str, actor_id: str, filters: dict) -> str:
        captured["export_type"] = export_type
        captured["actor_id"] = actor_id
        captured["filters"] = filters
        return "exports/material-usage/object-key"

    monkeypatch.setattr("app.tasks.report._generate_management_export", fake_generate)

    actor_id = str(uuid4())
    result = generate_excel_export(
        "material-usage",
        actor_id,
        {"department": "civil", "date_from": "2026-01-01"},
    )

    assert result == "exports/material-usage/object-key"
    assert captured == {
        "export_type": "material-usage",
        "actor_id": actor_id,
        "filters": {"department": "civil", "date_from": "2026-01-01"},
    }


def test_generate_excel_export_rejects_pdf_exports() -> None:
    with pytest.raises(ValueError, match="only supports XLSX exports"):
        generate_excel_export("management-summary", str(uuid4()), {})


async def create_project(admin: User, *, location: str = "Doha") -> Project:
    async with AsyncSessionLocal() as session:
        project = Project(
            name=f"Analytics {uuid4().hex[:6]}",
            code=f"ANL-{uuid4().hex[:6]}",
            location=location,
            description="Analytics aggregation project",
            scope_of_work="Civil works",
            status="active",
            budget_amount=Decimal("10000.00"),
            start_date=date.today(),
            target_end_date=date.today() + timedelta(days=30),
            client_name="Analytics Client",
            contract_number=f"C-{uuid4().hex[:6]}",
            progress_percentage=Decimal("25.00"),
            created_by=admin.id,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project


def xlsx_rows(data: bytes) -> list[list[str]]:
    with ZipFile(BytesIO(data)) as archive:
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    return [
        [cell.text or "" for cell in row.findall("{*}c/{*}is/{*}t")]
        for row in sheet.findall("{*}sheetData/{*}row")
    ]


@pytest.mark.asyncio
async def test_analytics_summary_and_exports_respect_project_scope() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("managing_director")
    manager, manager_password = await create_user("group_project_manager")
    admin_exec, admin_exec_password = await create_user("administrative_executive")
    assigned = await create_project(admin)
    unassigned = await create_project(admin)
    removed = await create_project(admin)
    await add_invoice(assigned, Decimal("123.00"))
    await add_invoice(unassigned, Decimal("789.00"))
    suffix = uuid4().hex[:8]
    shared_name = f"Shared material {suffix}"
    other_name = f"Other material {suffix}"

    async with AsyncSessionLocal() as session:
        member = ProjectMember(project_id=assigned.id, user_id=manager.id)
        shared = InventoryItem(
            name=shared_name, category="Civil", item_type="consumable", unit="kg"
        )
        other = InventoryItem(name=other_name, category="Civil", item_type="consumable", unit="kg")
        session.add_all(
            [member, ProjectMember(project_id=removed.id, user_id=manager.id), shared, other]
        )
        (await session.get_one(Project, removed.id)).deleted_at = utc_now()
        await session.flush()
        for item, project_id, quantity, movement_type in (
            (shared, assigned.id, "2.500", "issue"),
            (shared, assigned.id, "1.000", "consume"),
            (shared, unassigned.id, "31.000", "issue"),
            (shared, unassigned.id, "17.000", "consume"),
            (shared, removed.id, "50.000", "issue"),
            (shared, None, "9.000", "issue"),
            (other, unassigned.id, "43.000", "issue"),
        ):
            session.add(
                InventoryMovement(
                    item_id=item.id,
                    project_id=project_id,
                    quantity=Decimal(quantity),
                    movement_type=movement_type,
                )
            )
        for movement_type in ("issue", "consume"):
            session.add(
                InventoryMovement(
                    item_id=shared.id,
                    project_id=assigned.id,
                    quantity=Decimal("90.000"),
                    movement_type=movement_type,
                    deleted_at=utc_now(),
                )
            )
        await session.commit()
        await session.refresh(member)
        membership_id = member.id

    async with create_test_client() as client:
        manager_token = await login_for_token(client, manager, manager_password)
        manager_headers = {"Authorization": f"Bearer {manager_token}"}
        for params in ({}, {"project_id": str(assigned.id)}):
            summary, progress, material, pdf = [
                await client.get(path, headers=manager_headers, params=params)
                for path in ANALYTICS_PATHS
            ]
            assert [response.status_code for response in (summary, progress, material, pdf)] == [
                200,
                200,
                200,
                200,
            ]
            data = summary.json()
            assert [(row["project_id"], row["invoice_total"]) for row in data["projects"]] == [
                (str(assigned.id), "123.00")
            ]
            assert [
                (row["item_name"], row["issued_quantity"], row["consumed_quantity"])
                for row in data["material_usage"]
            ] == [(shared_name, "2.500", "1.000")]
            assert xlsx_rows(progress.content)[1:] == [[assigned.name, "25.00", "0", "123.00", "0"]]
            assert xlsx_rows(material.content)[1:] == [[shared_name, "2.500", "1.000"]]
            assert pdf.content.startswith(b"%PDF-")
            text = pdf_text(pdf.content)
            for allowed in (assigned.name, shared_name, "2.500", "123.00"):
                assert allowed in text
            for forbidden in (
                unassigned.name,
                removed.name,
                other_name,
                "789.00",
                "31.000",
            ):
                assert forbidden not in text

        for path in ANALYTICS_PATHS:
            denied = await client.get(
                path, headers=manager_headers, params={"project_id": str(unassigned.id)}
            )
            assert denied.status_code == 403, path
            assert denied.json()["error_code"] == "PROJECT_FORBIDDEN"

        async with AsyncSessionLocal() as session:
            (await session.get_one(ProjectMember, membership_id)).deleted_at = utc_now()
            await session.commit()

        empty = await client.get(ANALYTICS_PATHS[0], headers=manager_headers)
        assert empty.status_code == 200
        assert empty.json() == {"projects": [], "material_usage": []}

        admin_exec_token = await login_for_token(client, admin_exec, admin_exec_password)
        company = await client.get(
            ANALYTICS_PATHS[0], headers={"Authorization": f"Bearer {admin_exec_token}"}
        )
        assert company.status_code == 200
        assert {str(assigned.id), str(unassigned.id)} <= {
            row["project_id"] for row in company.json()["projects"]
        }
        assert (
            next(
                row["issued_quantity"]
                for row in company.json()["material_usage"]
                if row["item_name"] == shared_name
            )
            == "92.500"
        )


async def add_invoice(
    project: Project,
    total: Decimal,
    *,
    status: str = "submitted",
    deleted: bool = False,
) -> Invoice:
    async with AsyncSessionLocal() as session:
        invoice = Invoice(
            invoice_number=f"INV-{uuid4().hex[:8]}",
            project_id=project.id,
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            amount=total,
            tax_amount=Decimal("0"),
            total_amount=total,
            status=status,
            payment_status="unpaid",
            deleted_at=utc_now() if deleted else None,
        )
        session.add(invoice)
        await session.commit()
        await session.refresh(invoice)
        return invoice


async def add_payment(invoice: Invoice, amount: Decimal, *, deleted: bool = False) -> Payment:
    async with AsyncSessionLocal() as session:
        payment = Payment(
            invoice_id=invoice.id,
            payment_date=date.today(),
            amount=amount,
            method="bank_transfer",
            deleted_at=utc_now() if deleted else None,
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        return payment


async def add_report(
    project: Project,
    engineer: User,
    report_date: date,
    *,
    deleted: bool = False,
) -> DailyReport:
    async with AsyncSessionLocal() as session:
        report = DailyReport(
            project_id=project.id,
            engineer_id=engineer.id,
            report_date=report_date,
            work_location="Block A",
            work_completed="Analytics aggregation fixture",
            progress_percentage=Decimal("5.00"),
            wir_status="not_required",
            inspection_status="not_required",
            next_day_plan="Continue works",
            supervisor_update_ids=[],
            photo_refs=[],
            attachment_refs=[],
            extra_fields={},
            status="submitted",
            deleted_at=utc_now() if deleted else None,
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report


async def summary_row(client: httpx.AsyncClient, token: str, project: Project) -> dict:
    response = await client.get(
        "/api/v1/analytics/summary",
        params={"project_id": str(project.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["projects"]
    return next(row for row in rows if row["project_id"] == str(project.id))


@pytest.mark.asyncio
async def test_project_totals_survive_the_report_invoice_payment_fan_out() -> None:
    """Two equal-value invoices and three payments must total exactly, not collapse or multiply."""
    await skip_if_database_unavailable()
    admin, _ = await create_user("managing_director")
    manager, manager_password = await create_user("operations_director")
    engineer, _ = await create_user("quantity_surveyor")
    project = await create_project(admin)

    # Equal values are deliberate: SUM(DISTINCT total_amount) would collapse these into one.
    first = await add_invoice(project, Decimal("315.00"), status="approved")
    second = await add_invoice(project, Decimal("315.00"), status="approved")
    # Three payments against two reports: a joined fan-out would double every payment.
    await add_payment(first, Decimal("100.00"))
    await add_payment(first, Decimal("115.00"))
    await add_payment(second, Decimal("100.00"))
    await add_report(project, engineer, date.today())
    await add_report(project, engineer, date.today())

    async with create_test_client() as client:
        token = await login_for_token(client, manager, manager_password)
        row = await summary_row(client, token, project)

    assert row["report_count"] == 2
    assert row["invoice_total"] == "630.00"
    assert row["paid_total"] == "315.00"


@pytest.mark.asyncio
async def test_project_totals_exclude_draft_rejected_and_soft_deleted_records() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("managing_director")
    manager, manager_password = await create_user("operations_director")
    engineer, _ = await create_user("quantity_surveyor")
    project = await create_project(admin)

    counted = await add_invoice(project, Decimal("315.00"), status="approved")
    await add_invoice(project, Decimal("900.00"), status="draft")
    await add_invoice(project, Decimal("800.00"), status="rejected")
    removed = await add_invoice(project, Decimal("700.00"), status="approved", deleted=True)
    await add_payment(counted, Decimal("100.00"))
    await add_payment(removed, Decimal("700.00"))
    await add_payment(counted, Decimal("55.00"), deleted=True)
    await add_report(project, engineer, date.today())
    await add_report(project, engineer, date.today(), deleted=True)

    async with create_test_client() as client:
        token = await login_for_token(client, manager, manager_password)
        row = await summary_row(client, token, project)

    assert row["report_count"] == 1
    assert row["invoice_total"] == "315.00"
    assert row["paid_total"] == "100.00"


@pytest.mark.asyncio
async def test_project_without_reports_in_range_is_still_returned() -> None:
    """A date filter must narrow the report count, not delete projects from the result."""
    await skip_if_database_unavailable()
    admin, _ = await create_user("managing_director")
    manager, manager_password = await create_user("operations_director")
    engineer, _ = await create_user("quantity_surveyor")
    location = f"Analytics Range {uuid4().hex[:8]}"
    busy = await create_project(admin, location=location)
    quiet = await create_project(admin, location=location)
    today = date.today()
    await add_report(busy, engineer, today)
    await add_report(busy, engineer, today - timedelta(days=10))
    await add_invoice(quiet, Decimal("250.00"), status="approved")

    async with create_test_client() as client:
        token = await login_for_token(client, manager, manager_password)
        response = await client.get(
            "/api/v1/analytics/summary",
            params={
                "location": location,
                "date_from": today.isoformat(),
                "date_to": today.isoformat(),
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    rows = {row["project_id"]: row for row in response.json()["projects"]}
    assert str(busy.id) in rows
    assert str(quiet.id) in rows, "a project with no reports in range must still be reported"
    assert rows[str(busy.id)]["report_count"] == 1
    assert rows[str(quiet.id)]["report_count"] == 0
    assert rows[str(quiet.id)]["invoice_total"] == "250.00"
