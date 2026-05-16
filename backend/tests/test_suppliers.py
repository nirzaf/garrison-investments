from datetime import date
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.notification import Notification
from app.models.supplier import Supplier
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.tasks.maintenance import _check_supplier_tds_expiry
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
        email=f"supplier-{role}-{uuid4().hex}@example.com",
        full_name=f"{role} Supplier User",
        role=role,
        employee_code=f"SUP-{uuid4().hex[:8]}",
        phone="+97455550777",
        designation=role.replace("_", " ").title(),
        password_hash=hash_password(password),
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


class FakeMinioClient:
    def presigned_get_object(self, bucket: str, object_key: str, expires=None) -> str:
        del bucket, expires
        return f"https://files.example.test/{object_key}"


async def test_accounts_can_create_update_filter_deactivate_and_download_tds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    accounts, password = await create_user("accounts")
    monkeypatch.setattr(
        "app.services.supplier_service.SupplierService._upload_object",
        lambda self, object_key, data, content_type: None,
    )
    monkeypatch.setattr(
        "app.services.supplier_service.SupplierService._client",
        lambda self: FakeMinioClient(),
    )

    async with create_test_client() as client:
        token = await login_for_token(client, accounts, password)
        created = await client.post(
            "/api/v1/suppliers",
            json={
                "name": "Compliant Supplier",
                "category": "Electrical",
                "rating": "A",
                "payment_terms": "45 days",
                "contact_person": "Accounts Contact",
                "phone": "+97455550888",
                "email": f"compliant-{uuid4().hex}@example.com",
                "address": "Doha",
                "tax_registration_number": f"TAX-{uuid4().hex[:8]}",
                "tds_certificate_number": "TDS-2026",
                "tds_expiry_date": "2027-05-16",
                "compliance_status": "compliant",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 201
        supplier = created.json()

        updated = await client.patch(
            f"/api/v1/suppliers/{supplier['id']}",
            json={"rating": "B", "compliance_status": "pending"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert updated.status_code == 200
        assert updated.json()["rating"] == "B"

        filtered = await client.get(
            "/api/v1/suppliers",
            params={"compliance_status": "pending", "search": "Compliant"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert filtered.status_code == 200
        assert any(item["id"] == supplier["id"] for item in filtered.json()["items"])

        uploaded = await client.post(
            f"/api/v1/suppliers/{supplier['id']}/tds-document",
            files={"file": ("tds.pdf", b"%PDF-1.4 supplier tds", "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["tds_document_key"].startswith("suppliers/")

        download = await client.get(
            f"/api/v1/suppliers/{supplier['id']}/tds-document",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert download.status_code == 200
        assert download.json()["url"].startswith("https://files.example.test/")

        deactivated = await client.delete(
            f"/api/v1/suppliers/{supplier['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False


async def test_supplier_tds_expiry_reminder_notifies_accounts_and_operations() -> None:
    await skip_if_database_unavailable()
    accounts, _ = await create_user("accounts")
    operation_manager, _ = await create_user("operation_manager")
    async with AsyncSessionLocal() as session:
        supplier = Supplier(
            name=f"Expiring Supplier {uuid4().hex[:6]}",
            category="Civil",
            rating="A",
            payment_terms="30 days",
            contact_person="Compliance Contact",
            phone="+97455550888",
            email=f"expiring-{uuid4().hex}@example.com",
            address="Doha",
            tax_registration_number=f"TAX-{uuid4().hex[:8]}",
            tds_certificate_number="TDS-EXP",
            tds_expiry_date=date(2026, 5, 30),
            compliance_status="compliant",
        )
        session.add(supplier)
        await session.commit()
        await session.refresh(supplier)

    result = await _check_supplier_tds_expiry()

    assert result.endswith("supplier TDS expiry notifications sent")
    async with AsyncSessionLocal() as session:
        notifications = list(
            (
                await session.scalars(
                    select(Notification).where(
                        Notification.title == "Supplier TDS expiring",
                        Notification.reference_id == supplier.id,
                    )
                )
            ).all()
        )
        recipient_ids = {notification.user_id for notification in notifications}
        assert accounts.id in recipient_ids
        assert operation_manager.id in recipient_ids
