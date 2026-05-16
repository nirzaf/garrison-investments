from uuid import uuid4

import httpx
import pytest

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
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


async def test_accounts_can_create_update_filter_and_deactivate_suppliers() -> None:
    await skip_if_database_unavailable()
    accounts, password = await create_user("accounts")

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

        deactivated = await client.delete(
            f"/api/v1/suppliers/{supplier['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False
