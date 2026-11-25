"""Role-policy coverage for read-only financial records."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.approval import Approval
from app.models.finance import Invoice, Payment
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.supplier import Supplier
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.finance_service import FinanceService
from app.utils.security import utc_now
from tests.password_fixtures import hash_fixture_password

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
        password_hash=hash_fixture_password(password),
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
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver"
    )


async def login_for_token(client: httpx.AsyncClient, user: User, password: str) -> str:
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": password}
    )
    challenge = login.json()
    verify = await client.post(
        "/api/v1/auth/verify-otp",
        json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
    )
    assert verify.status_code == 200, verify.text
    return str(verify.json()["access_token"])


async def add_invoice(
    project: Project,
    total: Decimal,
    *,
    status: str = "submitted",
    deleted: bool = False,
    supplier_id: UUID | None = None,
) -> Invoice:
    async with AsyncSessionLocal() as session:
        invoice = Invoice(
            invoice_number=f"INV-{uuid4().hex[:8]}",
            project_id=project.id,
            supplier_id=supplier_id,
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


async def add_payment(invoice: Invoice, amount: Decimal) -> Payment:
    async with AsyncSessionLocal() as session:
        payment = Payment(
            invoice_id=invoice.id,
            payment_date=date.today(),
            amount=amount,
            method="bank_transfer",
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        return payment


async def test_finance_access_is_read_only_for_the_ten_role_catalogue() -> None:
    await skip_if_database_unavailable()
    roles = (
        "managing_director",
        "operations_director",
        "group_project_manager",
        "mep_project_manager",
        "quantity_surveyor",
        "senior_site_supervisor",
        "site_supervisor",
        "hr_manager",
        "hr_executive_reader",
        "administrative_executive",
    )
    users_by_role = {role: await create_user(role) for role in roles}
    project, supplier = await create_project_and_supplier(users_by_role["managing_director"][0])
    invoice = await add_invoice(
        project, Decimal("300.00"), status="approved", supplier_id=supplier.id
    )
    other_project, _ = await create_project_and_supplier(users_by_role["managing_director"][0])
    other_invoice = await add_invoice(other_project, Decimal("900.00"), status="approved")
    async with AsyncSessionLocal() as session:
        session.add(
            ProjectMember(
                project_id=project.id,
                user_id=users_by_role["group_project_manager"][0].id,
                role_in_project="Group Project Manager",
            )
        )
        approval = Approval(
            request_type="invoice",
            request_id=invoice.id,
            project_id=project.id,
            submitter_id=users_by_role["managing_director"][0].id,
            approver_id=users_by_role["operations_director"][0].id,
            title=invoice.invoice_number,
            status="pending",
            submitted_at=utc_now(),
            due_at=utc_now() + timedelta(days=1),
        )
        session.add(approval)
        await session.commit()
        approval_id = approval.id

    payload = {
        "invoice_number": f"NEW-{uuid4().hex[:8]}",
        "project_id": str(project.id),
        "supplier_id": str(supplier.id),
        "invoice_date": date.today().isoformat(),
        "due_date": (date.today() + timedelta(days=30)).isoformat(),
        "amount": "100.00",
        "tax_amount": "0.00",
    }
    payment_payload = {
        "payment_date": date.today().isoformat(),
        "amount": "10.00",
        "method": "bank_transfer",
    }

    async with create_test_client() as client:
        director_approval = None
        for role, (user, password) in users_by_role.items():
            token = await login_for_token(client, user, password)
            headers = {"Authorization": f"Bearer {token}"}
            director = role in {"managing_director", "operations_director"}
            can_read_finance = director or role == "group_project_manager"

            for path in (
                "/api/v1/finance/invoices",
                f"/api/v1/finance/invoices/{invoice.id}",
                f"/api/v1/finance/projects/{project.id}/budget-summary",
            ):
                response = await client.get(path, headers=headers)
                assert response.status_code == (200 if can_read_finance else 403), (
                    role,
                    path,
                    response.text,
                )
                if can_read_finance and path.endswith(str(invoice.id)):
                    assert response.json()["allowed_actions"] == []

            if role == "group_project_manager":
                listed = await client.get("/api/v1/finance/invoices", headers=headers)
                assert [item["id"] for item in listed.json()["items"]] == [str(invoice.id)]
                for path in (
                    f"/api/v1/finance/invoices/{other_invoice.id}",
                    f"/api/v1/finance/projects/{other_project.id}/budget-summary",
                    f"/api/v1/finance/invoices?project_id={other_project.id}",
                    "/api/v1/finance/policy/reconciliation",
                    "/api/v1/finance/supplier-options",
                ):
                    denied = await client.get(path, headers=headers)
                    assert denied.status_code == 403, (path, denied.text)

            create = await client.post("/api/v1/finance/invoices", json=payload, headers=headers)
            update = await client.patch(
                f"/api/v1/finance/invoices/{invoice.id}",
                json={"notes": "Attempted change"},
                headers=headers,
            )
            attachment = await client.post(
                f"/api/v1/finance/invoices/{invoice.id}/attachment",
                files={"file": ("invoice.pdf", b"%PDF-1.4 test", "application/pdf")},
                headers=headers,
            )
            payment = await client.post(
                f"/api/v1/finance/invoices/{invoice.id}/payments",
                json=payment_payload,
                headers=headers,
            )
            for response in (create, update, attachment, payment):
                assert response.status_code == 403, (role, response.text)
                if can_read_finance:
                    assert response.json()["error_code"] == "FINANCE_WRITE_FORBIDDEN"

            if role == "operations_director":
                director_approval = await client.post(
                    f"/api/v1/approvals/{approval_id}/approve",
                    json={"comments": "Invoice decisions are disabled."},
                    headers=headers,
                )
                assert director_approval.status_code == 403

    assert director_approval is not None
    async with AsyncSessionLocal() as session:
        stored = await session.get_one(Invoice, invoice.id)
        stored_approval = await session.get_one(Approval, approval_id)
        invoice_count = await session.scalar(
            select(func.count()).select_from(Invoice).where(Invoice.project_id == project.id)
        )
        payment_count = await session.scalar(
            select(func.count()).select_from(Payment).where(Payment.invoice_id == invoice.id)
        )
        assert (stored.status, stored.amount, stored.revision, stored.attachment_key) == (
            "approved",
            Decimal("300.00"),
            1,
            None,
        )
        assert stored_approval.status == "pending"
        assert invoice_count == 1
        assert payment_count == 0


async def test_invoice_attachment_signed_url_is_not_cached() -> None:
    await skip_if_database_unavailable()
    admin, password = await create_user("managing_director")
    project, supplier = await create_project_and_supplier(admin)
    invoice = await add_invoice(
        project, Decimal("100.00"), supplier_id=supplier.id
    )
    async with AsyncSessionLocal() as session:
        stored = await session.get(Invoice, invoice.id)
        assert stored is not None
        stored.attachment_key = f"finance/invoices/{invoice.id}/synthetic.pdf"
        await session.commit()

    async with create_test_client() as client:
        token = await login_for_token(client, admin, password)
        response = await client.get(
            f"/api/v1/finance/invoices/{invoice.id}/attachment",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["expires_in_seconds"] > 0


async def test_finance_supplier_options_are_minimal_paged_and_finance_scoped() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("managing_director")
    project, first_supplier = await create_project_and_supplier(admin)
    del project
    prefix = f"Lookup {uuid4().hex[:6]}"
    async with AsyncSessionLocal() as session:
        existing = await session.get_one(Supplier, first_supplier.id)
        existing.name = f"{prefix} A"
        second = Supplier(
            name=f"{prefix} B",
            category="Electrical",
            rating="B",
            payment_terms="30 days",
            contact_person="Supplier Contact",
            phone="+97455550124",
            email=f"lookup-{uuid4().hex}@example.com",
            address="Doha",
            tax_registration_number="SECRET-TAX",
            tds_certificate_number="SECRET-TDS",
            tds_expiry_date=date.today() + timedelta(days=180),
            compliance_status="compliant",
        )
        session.add(second)
        await session.commit()
        second_id = second.id

    async with create_test_client() as client:
        admin_token = await login_for_token(client, admin, "Start123!")
        first = await client.get(
            "/api/v1/finance/supplier-options",
            params={"search": prefix, "limit": 1},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        next_page = await client.get(
            "/api/v1/finance/supplier-options",
            params={"search": prefix, "limit": 1, "offset": 1},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert first.status_code == next_page.status_code == 200
        assert first.json()["total"] == next_page.json()["total"] == 2
        first_item = first.json()["items"][0]
        second_item = next_page.json()["items"][0]
        assert set(first_item) == set(second_item) == {"id", "name"}
        assert first_item["id"] == str(first_supplier.id)
        assert second_item["id"] == str(second_id)
        assert "SECRET-TAX" not in first.text + next_page.text
        assert "SECRET-TDS" not in first.text + next_page.text

        # Supplier-management permission does not grant financial lookup access.
        mep_manager, mep_password = await create_user("mep_project_manager")
        mep_token = await login_for_token(client, mep_manager, mep_password)
        denied = await client.get(
            "/api/v1/finance/supplier-options",
            headers={"Authorization": f"Bearer {mep_token}"},
        )
        assert denied.status_code == 403


async def test_budget_summary_excludes_draft_rejected_and_soft_deleted_invoices() -> None:
    await skip_if_database_unavailable()
    admin, admin_password = await create_user("managing_director")
    project, _ = await create_project_and_supplier(admin)

    await add_invoice(project, Decimal("300.00"), status="submitted")
    approved = await add_invoice(project, Decimal("200.00"), status="approved")
    await add_invoice(project, Decimal("900.00"), status="draft")
    await add_invoice(project, Decimal("800.00"), status="rejected")
    removed = await add_invoice(project, Decimal("700.00"), status="approved", deleted=True)
    await add_payment(approved, Decimal("50.00"))
    await add_payment(approved, Decimal("75.00"))
    await add_payment(removed, Decimal("700.00"))

    async with create_test_client() as client:
        token = await login_for_token(client, admin, admin_password)
        response = await client.get(
            f"/api/v1/finance/projects/{project.id}/budget-summary",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["invoiced_total"] == "500.00"
    assert body["paid_total"] == "125.00"
    assert body["remaining_budget"] == "500.00"


async def test_invoice_attachment_write_is_denied_before_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    admin, admin_password = await create_user("managing_director")
    project, _ = await create_project_and_supplier(admin)
    invoice = await add_invoice(project, Decimal("100.00"))
    uploads: list[str] = []

    def record_upload(
        self: FinanceService, object_key: str, data: bytes, content_type: str
    ) -> None:
        del self, data, content_type
        uploads.append(object_key)

    monkeypatch.setattr(FinanceService, "_upload_object", record_upload)
    async with create_test_client() as client:
        token = await login_for_token(client, admin, admin_password)
        response = await client.post(
            f"/api/v1/finance/invoices/{invoice.id}/attachment",
            files={"file": ("invoice.pdf", b"%PDF-1.4 test", "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["error_code"] == "FINANCE_WRITE_FORBIDDEN"
    assert uploads == []
    async with AsyncSessionLocal() as session:
        stored = await session.get_one(Invoice, invoice.id)
        assert stored.attachment_key is None and stored.revision == 1
