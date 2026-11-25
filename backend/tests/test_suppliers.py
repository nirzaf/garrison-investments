from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.notification import Notification
from app.models.supplier import Supplier
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.suppliers import SupplierUpdateRequest
from app.services.supplier_service import SupplierService
from app.tasks.maintenance import _check_supplier_tds_expiry
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
        email=f"supplier-{role}-{uuid4().hex}@example.com",
        full_name=f"{role} Supplier User",
        role=role,
        employee_code=f"SUP-{uuid4().hex[:8]}",
        phone="+97455550777",
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


class FakeMinioClient:
    def presigned_get_object(
        self,
        bucket: str,
        object_key: str,
        expires=None,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        del bucket, expires, response_headers
        return f"https://files.example.test/{object_key}"


async def test_operation_manager_can_create_update_filter_deactivate_and_download_tds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    operations_director, password = await create_user("operations_director")
    monkeypatch.setattr(
        "app.services.supplier_service.SupplierService._upload_object",
        lambda self, object_key, data, content_type: None,
    )
    monkeypatch.setattr(
        "app.services.supplier_service.minio_signed_url_client",
        lambda settings: FakeMinioClient(),
    )

    async with create_test_client() as client:
        token = await login_for_token(client, operations_director, password)
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
            json={
                "rating": "B",
                "compliance_status": "pending",
                "tds_expiry_date": None,
                "expected_revision": supplier["revision"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert updated.status_code == 200
        assert updated.json()["rating"] == "B"
        assert updated.json()["tds_expiry_date"] is None
        assert updated.json()["tds_days_remaining"] is None

        async def revise(session: AsyncSession, rating: str) -> int:
            await SupplierService(session).update_supplier(
                UUID(supplier["id"]),
                SupplierUpdateRequest(rating=rating, expected_revision=updated.json()["revision"]),
                operations_director,
            )
            return 200

        edits = await race_sessions(
            lambda session: revise(session, "B1"), lambda session: revise(session, "B2")
        )
        assert status_counts(edits) == {200: 1, 409: 1}
        assert error_codes(edits) == ["SUPPLIER_REVISION_CONFLICT"]
        stale = await client.patch(
            f"/api/v1/suppliers/{supplier['id']}",
            json={"rating": "C", "expected_revision": supplier["revision"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert stale.status_code == 409
        assert stale.json()["error_code"] == "SUPPLIER_REVISION_CONFLICT"
        invalid = await client.patch(
            f"/api/v1/suppliers/{supplier['id']}",
            json={"tds_expiry_date": "2027-02-29", "name": None},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert invalid.status_code == 422
        missing_rev = await client.patch(
            f"/api/v1/suppliers/{supplier['id']}",
            json={"rating": "A"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert missing_rev.status_code == 422

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

        missing_delete_rev = await client.delete(
            f"/api/v1/suppliers/{supplier['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert missing_delete_rev.status_code == 422
        deactivated = await client.delete(
            f"/api/v1/suppliers/{supplier['id']}",
            params={"expected_revision": uploaded.json()["revision"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False
        historical = await client.get(
            f"/api/v1/suppliers/{supplier['id']}/tds-document",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert historical.status_code == 200
        inactive = await client.get(
            "/api/v1/suppliers",
            params={"active": False, "search": "Compliant Supplier"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert {item["id"] for item in inactive.json()["items"]} >= {supplier["id"]}


async def test_supplier_tds_expiry_reminder_notifies_accounts_and_operations() -> None:
    await skip_if_database_unavailable()
    admin_exec, _ = await create_user("administrative_executive")
    operations_director, _ = await create_user("operations_director")
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
        assert admin_exec.id in recipient_ids
        assert operations_director.id in recipient_ids


async def test_supplier_tds_expiry_window_uses_the_business_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M9: just after local midnight the UTC date is still yesterday in Qatar."""
    await skip_if_database_unavailable()
    admin_exec, _ = await create_user("administrative_executive")
    # 2026-11-11T22:00Z is 2026-11-12T01:00 in Asia/Qatar (UTC+3).
    frozen = datetime(2026, 11, 11, 22, 0, tzinfo=UTC)
    monkeypatch.setattr("app.tasks.maintenance.utc_now", lambda: frozen)
    monkeypatch.setattr("app.utils.time.utc_now", lambda: frozen)

    async with AsyncSessionLocal() as session:
        supplier = Supplier(
            name=f"Boundary Supplier {uuid4().hex[:6]}",
            category="Civil",
            rating="A",
            payment_terms="30 days",
            contact_person="Compliance Contact",
            phone="+97455550888",
            email=f"boundary-{uuid4().hex}@example.com",
            address="Doha",
            tax_registration_number=f"TAX-{uuid4().hex[:8]}",
            tds_certificate_number="TDS-BOUNDARY",
            # Exactly 30 days after the business date, one day after the UTC date.
            tds_expiry_date=date(2026, 12, 12),
            compliance_status="compliant",
        )
        session.add(supplier)
        await session.commit()
        await session.refresh(supplier)
        supplier_id = supplier.id

    await _check_supplier_tds_expiry()

    async with AsyncSessionLocal() as session:
        notified = await session.scalar(
            select(Notification).where(
                Notification.title == "Supplier TDS expiring",
                Notification.reference_id == supplier_id,
                Notification.user_id == admin_exec.id,
            )
        )
    assert notified is not None, "the 30-day window was anchored to the UTC date"
