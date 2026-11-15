from uuid import uuid4

import httpx
import pytest

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
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


async def create_user(role: str, password: str = "Start123!") -> tuple[str, str]:
    email = f"audit-{role}-{uuid4().hex}@example.com"
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(
            User(
                email=email,
                full_name=f"{role} Audit User",
                role=role,
                employee_code=f"AUD-{uuid4().hex[:8]}",
                phone="+97455550333",
                designation=role.replace("_", " ").title(),
                password_hash=hash_fixture_password(password),
                must_change_password=False,
            )
        )
        await session.commit()
    return email, password


def create_test_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def login_for_token(client: httpx.AsyncClient, email: str, password: str) -> str:
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    challenge = login_response.json()
    verify_response = await client.post(
        "/api/v1/auth/verify-otp",
        json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
    )
    return str(verify_response.json()["access_token"])


async def test_admin_can_filter_audit_logs_and_non_admin_is_blocked() -> None:
    await skip_if_database_unavailable()
    admin_email, admin_password = await create_user("managing_director")
    engineer_email, engineer_password = await create_user("quantity_surveyor")

    async with AsyncSessionLocal() as session:
        admin = await UserRepository(session).get_by_email(admin_email)
        assert admin is not None
        await AuditService(session).record(
            action="documents.downloaded",
            user_id=admin.id,
            entity_type="documents",
            comments="Test download",
        )
        await session.commit()

    async with create_test_client() as client:
        admin_token = await login_for_token(client, admin_email, admin_password)
        engineer_token = await login_for_token(client, engineer_email, engineer_password)

        response = await client.get(
            "/api/v1/audit-logs",
            params={"action": "documents.downloaded", "search": "download"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] >= 1
        assert any(item["action"] == "documents.downloaded" for item in payload["items"])

        blocked = await client.get(
            "/api/v1/audit-logs",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )

        assert blocked.status_code == 403


async def test_authenticated_request_is_recorded_in_audit_log() -> None:
    await skip_if_database_unavailable()
    admin_email, admin_password = await create_user("managing_director")

    async with create_test_client() as client:
        admin_token = await login_for_token(client, admin_email, admin_password)

        response = await client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "User-Agent": "pytest-audit-client",
            },
        )

        assert response.status_code == 200

    async with AsyncSessionLocal() as session:
        admin = await UserRepository(session).get_by_email(admin_email)
        assert admin is not None

        logs, total = await AuditService(session).list_logs(
            action="http.request",
            user_id=admin.id,
            search="/api/v1/auth/me",
        )

        assert total >= 1
        assert any(
            log.comments == "GET /api/v1/auth/me -> 200"
            and log.context_payload is not None
            and log.context_payload.get("status_code") == 200
            and log.context_payload.get("path") == "/api/v1/auth/me"
            for log in logs
        )
