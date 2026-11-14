import asyncio
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.approval import Approval
from app.models.finance import Invoice, Payment
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.supplier import Supplier
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.finance import InvoiceUpdateRequest, PaymentCreateRequest
from app.services.audit_service import AuditService
from app.services.finance_service import FinanceService
from app.utils.security import utc_now
from tests.concurrency_helpers import error_codes, race_sessions, status_counts
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


class FakeMinioClient:
    def presigned_get_object(self, bucket: str, object_key: str, expires=None) -> str:
        del bucket, expires
        return f"https://files.example.test/{object_key}"

    def remove_object(self, bucket: str, object_key: str) -> None:
        del bucket, object_key


async def test_invoice_payment_budget_and_finance_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    monkeypatch.setattr(
        "app.services.finance_service.FinanceService._upload_object",
        lambda self, object_key, data, content_type: None,
    )
    monkeypatch.setattr(
        "app.services.finance_service.minio_signed_url_client",
        lambda settings: FakeMinioClient(),
    )
    admin, _ = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    engineer, engineer_password = await create_user("civil_engineer")
    operation_manager, op_password = await create_user("operation_manager")
    project_manager, pm_password = await create_user("project_manager")
    project, supplier = await create_project_and_supplier(admin)
    async with AsyncSessionLocal() as session:
        session.add(
            ProjectMember(
                project_id=project.id,
                user_id=project_manager.id,
                role_in_project="Project Manager",
            )
        )
        await session.commit()

    async with create_test_client() as client:
        accounts_token = await login_for_token(client, accounts, accounts_password)
        engineer_token = await login_for_token(client, engineer, engineer_password)
        op_token = await login_for_token(client, operation_manager, op_password)
        pm_token = await login_for_token(client, project_manager, pm_password)

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

        attachment = await client.post(
            f"/api/v1/finance/invoices/{invoice['id']}/attachment",
            files={"file": ("invoice.pdf", b"%PDF-1.4 invoice", "application/pdf")},
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert attachment.status_code == 200
        assert attachment.json()["attachment_key"].startswith("finance/invoices/")

        attachment_url = await client.get(
            f"/api/v1/finance/invoices/{invoice['id']}/attachment",
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert attachment_url.status_code == 200
        assert attachment_url.json()["url"].startswith("https://files.example.test/")

        list_invoices_called = False

        async def fail_if_route_dependency_is_bypassed(*args, **kwargs):
            nonlocal list_invoices_called
            del args, kwargs
            list_invoices_called = True
            raise AssertionError("finance service should not be reached")

        with monkeypatch.context() as blocked_route:
            blocked_route.setattr(
                "app.services.finance_service.FinanceService.list_invoices",
                fail_if_route_dependency_is_bypassed,
            )
            blocked = await client.get(
                "/api/v1/finance/invoices",
                headers={"Authorization": f"Bearer {engineer_token}"},
            )
        assert blocked.status_code == 403
        assert list_invoices_called is False

        project_manager_visible = await client.get(
            "/api/v1/finance/invoices",
            headers={"Authorization": f"Bearer {pm_token}"},
        )
        assert project_manager_visible.status_code == 200
        assert any(item["id"] == invoice["id"] for item in project_manager_visible.json()["items"])

        blocked_payment = await client.post(
            f"/api/v1/finance/invoices/{invoice['id']}/payments",
            json={
                "payment_date": date.today().isoformat(),
                "amount": "315.00",
                "method": "bank_transfer",
                "reference_number": "PAY-001",
            },
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert blocked_payment.status_code == 409

        blocked_direct_approval = await client.patch(
            f"/api/v1/finance/invoices/{invoice['id']}",
            json={"status": "approved"},
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert blocked_direct_approval.status_code == 403
        assert (
            blocked_direct_approval.json()["error_code"]
            == "INVOICE_OPERATION_MANAGER_APPROVAL_REQUIRED"
        )

        approvals = await client.get(
            "/api/v1/approvals",
            headers={"Authorization": f"Bearer {op_token}"},
        )
        assert approvals.status_code == 200
        approval = next(
            item for item in approvals.json()["items"] if item["request_id"] == invoice["id"]
        )
        approved = await client.post(
            f"/api/v1/approvals/{approval['id']}/approve",
            json={"comments": "Approved for payment."},
            headers={"Authorization": f"Bearer {op_token}"},
        )
        assert approved.status_code == 200

        partial = await client.post(
            f"/api/v1/finance/invoices/{invoice['id']}/payments",
            json={
                "payment_date": date.today().isoformat(),
                "amount": "100.00",
                "method": "bank_transfer",
                "reference_number": "PAY-001",
            },
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert partial.status_code == 200
        assert partial.json()["payment_status"] == "partial"
        assert len(partial.json()["payments"]) == 1

        paid = await client.post(
            f"/api/v1/finance/invoices/{invoice['id']}/payments",
            json={
                "payment_date": date.today().isoformat(),
                "amount": "215.00",
                "method": "bank_transfer",
                "reference_number": "PAY-002",
            },
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert paid.status_code == 200
        assert paid.json()["payment_status"] == "paid"
        assert len(paid.json()["payments"]) == 2

        summary = await client.get(
            f"/api/v1/finance/projects/{project.id}/budget-summary",
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert summary.status_code == 200
        assert summary.json()["invoiced_total"] == "315.00"
        assert summary.json()["paid_total"] == "315.00"


async def test_invoice_attachment_upload_is_compensated_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    uploaded_keys: list[str] = []
    deleted_keys: list[str] = []

    def fake_upload(self, object_key: str, data: bytes, content_type: str) -> None:
        del self, data, content_type
        uploaded_keys.append(object_key)

    def fake_delete(self, object_key: str) -> None:
        del self
        deleted_keys.append(object_key)

    record_audit = AuditService.record

    async def fail_attachment_audit(self, *args, **kwargs):
        if kwargs.get("action") == "finance.invoices.attachment_uploaded":
            raise RuntimeError("audit write failed")
        return await record_audit(self, *args, **kwargs)

    monkeypatch.setattr(
        "app.services.finance_service.FinanceService._upload_object",
        fake_upload,
    )
    monkeypatch.setattr(
        "app.services.finance_service.FinanceService._delete_object",
        fake_delete,
    )
    monkeypatch.setattr(
        "app.services.audit_service.AuditService.record",
        fail_attachment_audit,
    )

    admin, _ = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    project, supplier = await create_project_and_supplier(admin)

    async with create_test_client() as client:
        accounts_token = await login_for_token(client, accounts, accounts_password)
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
            },
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert created.status_code == 201
        invoice = created.json()

        with pytest.raises(RuntimeError, match="audit write failed"):
            await client.post(
                f"/api/v1/finance/invoices/{invoice['id']}/attachment",
                files={"file": ("invoice.pdf", b"%PDF-1.4 invoice", "application/pdf")},
                headers={"Authorization": f"Bearer {accounts_token}"},
            )

    assert len(uploaded_keys) == 1
    assert deleted_keys == uploaded_keys


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


async def create_invoice_via_api(
    client: httpx.AsyncClient,
    token: str,
    project: Project,
    supplier: Supplier,
    amount: str = "300.00",
) -> dict:
    response = await client.post(
        "/api/v1/finance/invoices",
        json={
            "invoice_number": f"INV-{uuid4().hex[:8]}",
            "project_id": str(project.id),
            "supplier_id": str(supplier.id),
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "amount": amount,
            "tax_amount": "0.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def approval_for(invoice_id: str) -> Approval | None:
    async with AsyncSessionLocal() as session:
        return await session.scalar(
            select(Approval).where(
                Approval.request_type == "invoice",
                Approval.request_id == UUID(invoice_id),
                Approval.deleted_at.is_(None),
            )
        )


async def test_business_currency_policy_and_historical_approval_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    admin, admin_password = await create_user("admin")
    engineer, engineer_password = await create_user("civil_engineer")
    project, supplier = await create_project_and_supplier(admin)
    policy = Settings(app_env="test", business_currency="USD")
    monkeypatch.setattr("app.services.approval_service.get_settings", lambda: policy)
    monkeypatch.setattr("app.services.finance_service.get_settings", lambda: policy)
    monkeypatch.setattr("app.api.v1.finance.get_settings", lambda: policy)
    async with create_test_client() as client:
        admin_token = await login_for_token(client, admin, admin_password)
        engineer_token = await login_for_token(client, engineer, engineer_password)
        history = await create_invoice_via_api(client, admin_token, project, supplier)
        policy = Settings(app_env="test", business_currency="LKR")
        created = await create_invoice_via_api(client, admin_token, project, supplier)
        assert (await client.get("/api/v1/finance/policy")).status_code == 401
        engineer_headers = {"Authorization": f"Bearer {engineer_token}"}
        configured = await client.get("/api/v1/finance/policy", headers=engineer_headers)
        assert configured.status_code == 200
        assert configured.json() == policy.business_policy().model_dump(mode="json")

        reconciliation_path = "/api/v1/finance/policy/reconciliation"
        denied = await client.get(reconciliation_path, headers=engineer_headers)
        assert denied.status_code == 403
        report = await client.get(
            reconciliation_path, headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert report.status_code == 200
        assert report.json()["unlabelled_row_counts"]["invoices"] >= 2
        assert {row["currency"] for row in report.json()["approval_currency_counts"]} >= {
            "USD", "LKR"
        }

    old_approval = await approval_for(history["id"])
    new_approval = await approval_for(created["id"])
    assert old_approval is not None and old_approval.currency == "USD"
    assert new_approval is not None and new_approval.currency == "LKR"


async def patch_status(client: httpx.AsyncClient, token: str, invoice_id: str, status: str):
    return await client.patch(
        f"/api/v1/finance/invoices/{invoice_id}",
        json={"status": status},
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_budget_summary_excludes_draft_rejected_and_soft_deleted_invoices() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    project, _ = await create_project_and_supplier(admin)

    await add_invoice(project, Decimal("300.00"), status="submitted")
    approved = await add_invoice(project, Decimal("200.00"), status="approved")
    await add_invoice(project, Decimal("900.00"), status="draft")
    await add_invoice(project, Decimal("800.00"), status="rejected")
    removed = await add_invoice(project, Decimal("700.00"), status="approved", deleted=True)
    await add_payment(approved, Decimal("50.00"))
    await add_payment(approved, Decimal("75.00"))
    # A payment on a soft-deleted invoice is not money the project has spent.
    await add_payment(removed, Decimal("700.00"))

    async with create_test_client() as client:
        token = await login_for_token(client, accounts, accounts_password)
        response = await client.get(
            f"/api/v1/finance/projects/{project.id}/budget-summary",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["invoiced_total"] == "500.00"
    assert body["paid_total"] == "125.00"
    assert body["remaining_budget"] == "500.00"


async def test_invoice_cannot_be_returned_to_draft() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    project, supplier = await create_project_and_supplier(admin)

    async with create_test_client() as client:
        token = await login_for_token(client, accounts, accounts_password)
        invoice = await create_invoice_via_api(client, token, project, supplier)

        rejected = await patch_status(client, token, invoice["id"], "draft")
        assert rejected.status_code == 409
        assert rejected.json()["error_code"] == "INVOICE_STATUS_TRANSITION_INVALID"

        unchanged = await client.get(
            f"/api/v1/finance/invoices/{invoice['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert unchanged.json()["status"] == "submitted"

    # A refused transition must not touch the approval workflow either.
    approval = await approval_for(invoice["id"])
    assert approval is not None
    assert approval.status == "pending"


async def test_direct_invoice_approval_resolves_the_linked_approval() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    manager, manager_password = await create_user("operation_manager")
    project, supplier = await create_project_and_supplier(admin)

    async with create_test_client() as client:
        accounts_token = await login_for_token(client, accounts, accounts_password)
        manager_token = await login_for_token(client, manager, manager_password)
        invoice = await create_invoice_via_api(client, accounts_token, project, supplier)

        approved = await patch_status(client, manager_token, invoice["id"], "approved")
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["approved_by"] == str(manager.id)

        # The invoice is now payable, which is the whole point of approving it.
        paid = await client.post(
            f"/api/v1/finance/invoices/{invoice['id']}/payments",
            json={
                "payment_date": date.today().isoformat(),
                "amount": "300.00",
                "method": "bank_transfer",
            },
            headers={"Authorization": f"Bearer {accounts_token}"},
        )
        assert paid.status_code == 200, paid.text
        assert paid.json()["payment_status"] == "paid"

    approval = await approval_for(invoice["id"])
    assert approval is not None
    assert approval.status == "approved", "the approval inbox must not stay pending"
    assert approval.decided_at is not None


async def test_approved_invoice_cannot_be_resubmitted_or_approved_again() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    manager, manager_password = await create_user("operation_manager")
    project, supplier = await create_project_and_supplier(admin)

    async with create_test_client() as client:
        accounts_token = await login_for_token(client, accounts, accounts_password)
        manager_token = await login_for_token(client, manager, manager_password)
        invoice = await create_invoice_via_api(client, accounts_token, project, supplier)
        assert (
            await patch_status(client, manager_token, invoice["id"], "approved")
        ).status_code == 200

        for illegal in ("submitted", "approved", "draft"):
            refused = await patch_status(client, manager_token, invoice["id"], illegal)
            assert refused.status_code == 409, illegal
            assert refused.json()["error_code"] == "INVOICE_STATUS_TRANSITION_INVALID"

        still_approved = await client.get(
            f"/api/v1/finance/invoices/{invoice['id']}",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert still_approved.json()["status"] == "approved"


async def test_invoice_rejection_resolves_the_approval_and_allows_resubmission() -> None:
    await skip_if_database_unavailable()
    admin, admin_password = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    manager, manager_password = await create_user("operation_manager")
    project, supplier = await create_project_and_supplier(admin)

    async with create_test_client() as client:
        accounts_token = await login_for_token(client, accounts, accounts_password)
        manager_token = await login_for_token(client, manager, manager_password)
        admin_token = await login_for_token(client, admin, admin_password)
        invoice = await create_invoice_via_api(client, admin_token, project, supplier)

        rejected = await patch_status(client, manager_token, invoice["id"], "rejected")
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        original = await approval_for(invoice["id"])
        assert original is not None and original.status == "rejected"
        assert original.decided_at is not None

        resubmitted = await patch_status(client, accounts_token, invoice["id"], "submitted")
        assert resubmitted.status_code == 200, resubmitted.text
        assert resubmitted.json()["status"] == "submitted"

        async with AsyncSessionLocal() as session:
            pending = await session.scalar(
                select(Approval).where(
                    Approval.request_id == UUID(invoice["id"]),
                    Approval.status == "pending",
                )
            )
            assert pending is not None and pending.id != original.id
            pending.approver_id = manager.id
            approval_id = pending.id
            await session.commit()

        approval_url = f"/api/v1/approvals/{approval_id}"
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        creator_view = await client.get(approval_url, headers=admin_headers)
        assert creator_view.status_code == 200
        assert creator_view.json()["allowed_actions"] == []
        creator_decision = await client.post(
            f"{approval_url}/override",
            json={"decision": "approved", "reason": "Creator cannot decide the new cycle."},
            headers=admin_headers,
        )
        assert creator_decision.status_code == 403

        direct, inbox = await asyncio.gather(
            patch_status(client, manager_token, invoice["id"], "approved"),
            client.post(
                f"/api/v1/approvals/{approval_id}/approve",
                json={"comments": "Reviewed"},
                headers={"Authorization": f"Bearer {manager_token}"},
            ),
        )
        assert sorted([direct.status_code, inbox.status_code]) == [200, 409]

    async with AsyncSessionLocal() as session:
        approval = await session.get(Approval, approval_id)
        updated_invoice = await session.get(Invoice, UUID(invoice["id"]))
        assert approval is not None and approval.status == "approved"
        assert updated_invoice is not None and updated_invoice.status == "approved"
        assert updated_invoice.revision == resubmitted.json()["revision"] + 1


async def test_finance_supplier_options_are_minimal_paged_and_independent_of_management() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    manager, manager_password = await create_user("project_manager")
    engineer, engineer_password = await create_user("civil_engineer")
    operations, operations_password = await create_user("operation_manager")
    project, supplier = await create_project_and_supplier(admin)
    other, second = await create_project_and_supplier(admin)
    async with AsyncSessionLocal() as session:
        session.add(ProjectMember(project_id=project.id, user_id=manager.id))
        await session.commit()

    async with create_test_client() as client:
        account_token = await login_for_token(client, accounts, accounts_password)
        manager_token = await login_for_token(client, manager, manager_password)
        engineer_token = await login_for_token(client, engineer, engineer_password)
        operations_token = await login_for_token(client, operations, operations_password)
        headers = {"Authorization": f"Bearer {account_token}"}
        for token in (account_token, manager_token):
            finance_headers = {"Authorization": f"Bearer {token}"}
            seen = set()
            for offset in (0, 1):
                response = await client.get(
                    "/api/v1/finance/supplier-options",
                    params={"search": "Finance Supplier", "limit": 1, "offset": offset},
                    headers=finance_headers,
                )
                assert response.status_code == 200
                item = response.json()["items"][0]
                assert set(item) == {"id", "name"}
                seen.add(item["id"])
            assert len(seen) == 2
            record = await create_invoice_via_api(client, token, project, supplier)
            assert record["supplier_name"] == supplier.name
            directory = await client.get("/api/v1/suppliers", headers=finance_headers)
            tds = await client.get(
                f"/api/v1/suppliers/{supplier.id}/tds-document", headers=finance_headers
            )
            assert directory.status_code == tds.status_code == 403
            edit = await client.patch(
                f"/api/v1/suppliers/{supplier.id}",
                json={"name": "Forbidden"},
                headers=finance_headers,
            )
            deactivate = await client.delete(
                f"/api/v1/suppliers/{supplier.id}", headers=finance_headers
            )
            assert edit.status_code == deactivate.status_code == 403
        options_denied = await client.get(
            "/api/v1/finance/supplier-options",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert options_denied.status_code == 403
        missing_supplier = {
            "invoice_number": f"INV-{uuid4().hex[:8]}",
            "project_id": str(project.id),
            "invoice_date": date.today().isoformat(),
            "due_date": date.today().isoformat(),
            "amount": "12.30",
            "supplier_id": None,
        }
        unlinked = await client.post(
            "/api/v1/finance/invoices", json=missing_supplier, headers=headers
        )
        assert unlinked.status_code == 201 and unlinked.json()["supplier_id"] is None
        forged = await client.post(
            "/api/v1/finance/invoices",
            json={**missing_supplier, "project_id": str(other.id)},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert forged.status_code == 403
        await client.delete(
            f"/api/v1/suppliers/{second.id}",
            headers={"Authorization": f"Bearer {operations_token}"},
        )
        stale_selection = await client.post(
            "/api/v1/finance/invoices",
            json={**missing_supplier, "supplier_id": str(second.id)},
            headers=headers,
        )
        assert stale_selection.status_code == 422
        assert stale_selection.json()["error_code"] == "INVOICE_SUPPLIER_INACTIVE"
        options = await client.get(
            "/api/v1/finance/supplier-options", params={"search": second.name}, headers=headers
        )
        assert options.json() == {"items": [], "total": 0}


async def test_corrected_invoice_reopens_one_approval_and_protects_posted_payments() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    manager, manager_password = await create_user("operation_manager")
    project, supplier = await create_project_and_supplier(admin)
    async with create_test_client() as client:
        accounts_token = await login_for_token(client, accounts, accounts_password)
        manager_token = await login_for_token(client, manager, manager_password)
        accounts_headers = {"Authorization": f"Bearer {accounts_token}"}
        invoice = await create_invoice_via_api(client, accounts_token, project, supplier)
        own = await create_invoice_via_api(client, manager_token, project, supplier)
        url = f"/api/v1/finance/invoices/{invoice['id']}"
        disallowed = await client.patch(
            url, json={"amount": "1", "expected_revision": 1}, headers=accounts_headers
        )
        assert disallowed.status_code == 409
        rejected = await patch_status(client, manager_token, invoice["id"], "rejected")
        assert rejected.status_code == 200 and rejected.json()["revision"] == 2
        duplicate = await client.patch(
            url,
            json={"invoice_number": own["invoice_number"], "expected_revision": 2},
            headers=accounts_headers,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error_code"] == "INVOICE_NUMBER_CONFLICT"
        changed = await client.patch(
            url,
            json={
                "expected_revision": 2,
                "amount": "210.75",
                "tax_amount": "4.25",
                "supplier_id": None,
                "due_date": (date.today() + timedelta(days=45)).isoformat(),
                "notes": "Corrected values",
            },
            headers=accounts_headers,
        )
        assert changed.status_code == 200, changed.text
        assert Decimal(changed.json()["total_amount"]) == Decimal("215.00")
        assert changed.json()["supplier_id"] is None
        resubmission = {"status": "submitted", "expected_revision": changed.json()["revision"]}
        resubmitted = await client.patch(url, json=resubmission, headers=accounts_headers)
        assert resubmitted.status_code == 200
        stale = await client.patch(url, json=resubmission, headers=accounts_headers)
        assert (
            stale.status_code == 409 and stale.json()["error_code"] == "INVOICE_REVISION_CONFLICT"
        )
        approval_denied = await patch_status(client, accounts_token, invoice["id"], "approved")
        assert approval_denied.status_code == 403
        assert "approve" not in own["allowed_actions"]
        own_approval = await patch_status(client, manager_token, own["id"], "approved")
        assert own_approval.status_code == 403
        assert own_approval.json()["error_code"] == "INVOICE_SELF_APPROVAL_FORBIDDEN"
        approved = await patch_status(client, manager_token, invoice["id"], "approved")
        assert approved.status_code == 200
        paid = await client.post(
            f"{url}/payments",
            json={
                "amount": "115.05",
                "payment_date": date.today().isoformat(),
                "method": "bank_transfer",
            },
            headers=accounts_headers,
        )
        assert paid.status_code == 200
        assert paid.json()["payment_status"] == "partial"
        assert Decimal(paid.json()["outstanding_amount"]) == Decimal("99.95")
        cannot_reject = await patch_status(client, manager_token, invoice["id"], "rejected")
        assert cannot_reject.status_code == 409
        assert cannot_reject.json()["error_code"] == "INVOICE_HAS_PAYMENTS"
        final = await client.post(
            f"{url}/payments",
            json={
                "amount": "99.95",
                "payment_date": date.today().isoformat(),
                "method": "bank_transfer",
            },
            headers=accounts_headers,
        )
        assert final.status_code == 200
        assert Decimal(final.json()["outstanding_amount"]) == 0
        assert len(final.json()["payments"]) == 2

    async with AsyncSessionLocal() as session:
        approvals = (
            await session.scalars(
                select(Approval).where(Approval.request_id == UUID(invoice["id"]))
            )
        ).all()
        assert {approval.status: approval.amount for approval in approvals} == {
            "rejected": Decimal("300.00"),
            "approved": Decimal("215.00"),
        }


async def test_invoice_correction_resubmission_and_payment_rejection_races_serialize() -> None:
    await skip_if_database_unavailable()
    admin, _ = await create_user("admin")
    accounts, accounts_password = await create_user("accounts")
    manager, manager_password = await create_user("operation_manager")
    project, supplier = await create_project_and_supplier(admin)
    async with create_test_client() as client:
        accounts_token = await login_for_token(client, accounts, accounts_password)
        manager_token = await login_for_token(client, manager, manager_password)
        rejected = await create_invoice_via_api(client, accounts_token, project, supplier)
        approved = await create_invoice_via_api(client, accounts_token, project, supplier)
        assert (
            await patch_status(client, manager_token, rejected["id"], "rejected")
        ).status_code == 200
        assert (
            await patch_status(client, manager_token, approved["id"], "approved")
        ).status_code == 200

    async def change(
        session: AsyncSession, invoice_id: str, actor_id: UUID, payload: InvoiceUpdateRequest
    ) -> int:
        actor = await session.get(User, actor_id)
        assert actor is not None
        await FinanceService(session).update_invoice(UUID(invoice_id), payload, actor)
        return 200

    correction = InvoiceUpdateRequest(amount=Decimal("100.00"), expected_revision=2)
    resubmission = InvoiceUpdateRequest(status="submitted", expected_revision=2)
    results = await race_sessions(
        lambda session: change(session, rejected["id"], accounts.id, correction),
        lambda session: change(session, rejected["id"], accounts.id, resubmission),
    )
    assert status_counts(results) == {200: 1, 409: 1}
    assert error_codes(results) == ["INVOICE_REVISION_CONFLICT"]

    async def pay(session: AsyncSession) -> int:
        actor = await session.get(User, accounts.id)
        assert actor is not None
        await FinanceService(session).create_payment(
            UUID(approved["id"]),
            PaymentCreateRequest(
                amount=Decimal("50.00"), payment_date=date.today(), method="bank_transfer"
            ),
            actor,
        )
        return 200

    results = await race_sessions(
        pay,
        lambda session: change(
            session, approved["id"], manager.id, InvoiceUpdateRequest(status="rejected")
        ),
    )
    assert status_counts(results) == {200: 1, 409: 1}
    assert error_codes(results)[0] in {"INVOICE_NOT_APPROVED", "INVOICE_HAS_PAYMENTS"}
    async with AsyncSessionLocal() as session:
        invoice = await session.get(Invoice, UUID(approved["id"]))
        assert invoice is not None
        assert (invoice.status == "approved") == bool(invoice.payments)


async def test_payment_replay_keeps_one_record_and_rejects_a_changed_intent() -> None:
    await skip_if_database_unavailable()
    accounts, accounts_password = await create_user("accounts")
    manager, manager_password = await create_user("operation_manager")
    project, supplier = await create_project_and_supplier(manager)
    async with create_test_client() as client:
        account_token = await login_for_token(client, accounts, accounts_password)
        manager_token = await login_for_token(client, manager, manager_password)
        first = await create_invoice_via_api(client, account_token, project, supplier)
        second = await create_invoice_via_api(client, account_token, project, supplier)
        for invoice in (first, second):
            approval = await patch_status(client, manager_token, invoice["id"], "approved")
            assert approval.status_code == 200
        headers = {
            "Authorization": f"Bearer {account_token}",
            "Idempotency-Key": str(uuid4()),
        }
        url = f"/api/v1/finance/invoices/{first['id']}/payments"
        payment = {
            "payment_date": date.today().isoformat(),
            "amount": "50.00",
            "method": "bank_transfer",
        }
        requests = await asyncio.gather(
            client.post(url, headers=headers, json=payment),
            client.post(url, headers=headers, json=payment),
        )
        assert all(response.status_code == 200 for response in requests)
        created, replayed = (response.json() for response in requests)
        assert created["payments"] == replayed["payments"]
        assert len(created["payments"]) == 1
        assert Decimal(replayed["outstanding_amount"]) == Decimal("250.00")
        assert replayed["revision"] == created["revision"]

        changed = await client.post(url, headers=headers, json={**payment, "amount": "51.00"})
        wrong_invoice = await client.post(
            f"/api/v1/finance/invoices/{second['id']}/payments", headers=headers, json=payment
        )
        for response in (changed, wrong_invoice):
            assert response.status_code == 409
            assert response.json()["error_code"] == "PAYMENT_REPLAY_CONFLICT"
        persisted = await client.get(f"/api/v1/finance/invoices/{first['id']}", headers=headers)
        assert persisted.json()["payments"] == created["payments"]
