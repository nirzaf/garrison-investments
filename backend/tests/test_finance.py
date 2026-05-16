from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.project import Project
from app.models.supplier import Supplier
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.security import hash_password

pytestmark = pytest.mark.asyncio


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
        email=f"finance-{role}-{uuid4().hex}@example.com",
        full_name=f"{role} Finance User",
        role=role,
        employee_code=f"FIN-{uuid4().hex[:8]}",
        phone="+97455550999",
        designation=role.replace("_", " ").title(),
        password_hash=hash_password(password),
        must_change_password=False,
    )
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(user)
        await session.commit()
        await session.refresh(user)
    return user, password


async def create_project_and_supplier(admin: User) -> tuple[Project, Supplier]:
    async with AsyncSessionLocal() as session:
        project = Project(
            name=f"Finance Test {uuid4().hex[:6]}",
            code=f"FIN-{uuid4().hex[:6]}",
            location="Doha",
            description="Finance test project",
            scope_of_work="Finance test scope",
            status="active",
            budget_amount=Decimal("1000.00"),
            start_date=date.today(),
            target_end_date=date.today() + timedelta(days=30),
            client_name="Test Client",
            contract_number=f"C-{uuid4().hex[:6]}",
            progress_percentage=Decimal("10.00"),
            created_by=admin.id,
        )
        supplier = Supplier(
            name=f"Finance Supplier {uuid4().hex[:6]}",
            category="Civil",
            rating="A",
            payment_terms="30 days",
            contact_person="Finance Contact",
            phone="+97455550123",
            email=f"finance-supplier-{uuid4().hex}@example.com",
            address="Doha",
            tax_registration_number=f"TAX-{uuid4().hex[:8]}",
            tds_certificate_number="TDS-FIN",
            tds_expiry_date=date.today() + timedelta(days=365),
            compliance_status="compliant",
        )
        session.add_all([project, supplier])
        await session.commit()
        await session.refresh(project)
        await session.refresh(supplier)
        return project, supplier


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


async def test_invoice_payment_budget_and_finance_visibility() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    engineer, engineer_password = await create_user("civil_engineer")
    await create_user("operation_manager")
    project, supplier = await create_project_and_supplier(admin)

    async with create_test_client() as client:
        accounts_token = await login_for_token(client, accounts, accounts_password)
        engineer_token = await login_for_token(client, engineer, engineer_password)

        created = await client.post(
            "/api/v1/finance/invoices",
            json={
                "invoice_number": f"INV-{uuid4().hex[:8]}",
                "project_id": str(project.id),
                "supplier_id": str(supplier.id),
                "invoice_date": date.today().isoformat(),
                "due_date": (date.today() + timedelta(days=30)).isoformat(),
                "amount": "300.00",
                "tax_amount": "15.00",
                "notes": "Structured finance test",
            },
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert created.status_code == 201
        invoice = created.json()
        assert invoice["status"] == "submitted"
        assert invoice["payment_status"] == "unpaid"

        blocked = await client.get(
            "/api/v1/finance/invoices",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert blocked.status_code == 403

        paid = await client.post(
            f"/api/v1/finance/invoices/{invoice['id']}/payments",
            json={
                "payment_date": date.today().isoformat(),
                "amount": "315.00",
                "method": "bank_transfer",
                "reference_number": "PAY-001",
            },
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert paid.status_code == 200
        assert paid.json()["payment_status"] == "paid"
        assert len(paid.json()["payments"]) == 1

        summary = await client.get(
            f"/api/v1/finance/projects/{project.id}/budget-summary",
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert summary.status_code == 200
        assert summary.json()["invoiced_total"] == "315.00"
        assert summary.json()["paid_total"] == "315.00"
