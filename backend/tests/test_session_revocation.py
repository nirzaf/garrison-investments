"""H6 — every credential change must revoke all live refresh sessions, atomically."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.auth import AuthRefreshToken
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.security import hash_password

pytestmark = pytest.mark.asyncio

PASSWORD = "Start123!"
NEW_PASSWORD = "Rotated456!"


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


def create_test_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def create_user(role: str = "civil_engineer") -> User:
    user = User(
        email=f"revoke-{uuid4().hex}@example.com",
        full_name=f"{role} Revoke User",
        role=role,
        employee_code=f"REV-{uuid4().hex[:8]}",
        phone="+97455550555",
        designation=role.replace("_", " ").title(),
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
    )
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def open_session(email: str, password: str = PASSWORD) -> tuple[str, str]:
    """Log in on a fresh client and return (access_token, refresh_token)."""
    async with create_test_client() as client:
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        challenge = login.json()
        verify = await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
        )
        assert verify.status_code == 200, verify.text
        return verify.json()["access_token"], verify.cookies["refresh_token"]


async def refresh(refresh_token: str) -> httpx.Response:
    async with create_test_client() as client:
        client.cookies.set("refresh_token", refresh_token, path="/api/v1/auth")
        return await client.post("/api/v1/auth/refresh")


async def live_token_count(user_id: UUID) -> int:
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(
            select(AuthRefreshToken.id).where(
                AuthRefreshToken.user_id == user_id,
                AuthRefreshToken.revoked_at.is_(None),
            )
        )
        return len(list(rows))


async def test_change_password_revokes_every_session_not_just_the_caller() -> None:
    await skip_if_database_unavailable()
    user = await create_user()
    first_access, first_refresh = await open_session(user.email)
    _, second_refresh = await open_session(user.email)
    assert await live_token_count(user.id) == 2

    async with create_test_client() as client:
        response = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {first_access}"},
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )

    assert response.status_code == 200, response.text
    assert await live_token_count(user.id) == 0
    for token in (first_refresh, second_refresh):
        revoked = await refresh(token)
        assert revoked.status_code == 401
        assert revoked.json()["error_code"] == "REFRESH_TOKEN_INVALID"


async def test_password_reset_revokes_every_session() -> None:
    await skip_if_database_unavailable()
    user = await create_user()
    _, first_refresh = await open_session(user.email)
    _, second_refresh = await open_session(user.email)

    async with create_test_client() as client:
        requested = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": user.email}
        )
        assert requested.status_code == 200, requested.text
        challenge = requested.json()
        confirmed = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "challenge_id": challenge["challenge_id"],
                "otp": challenge["dev_otp"],
                "new_password": NEW_PASSWORD,
            },
        )

    assert confirmed.status_code == 200, confirmed.text
    assert await live_token_count(user.id) == 0
    for token in (first_refresh, second_refresh):
        assert (await refresh(token)).status_code == 401


async def test_password_change_serializes_refresh_and_invalidates_pending_otps() -> None:
    await skip_if_database_unavailable()
    user = await create_user()
    access, refresh_token = await open_session(user.email)
    async with create_test_client() as client:
        pending = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )
        assert pending.status_code == 200
        challenge = pending.json()
        changed, rotated = await asyncio.gather(
            client.post(
                "/api/v1/auth/change-password",
                headers={"Authorization": f"Bearer {access}"},
                json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            ),
            refresh(refresh_token),
        )
        assert changed.status_code == 200
        assert rotated.status_code in {200, 401}
        if rotated.status_code == 200:
            assert (await refresh(rotated.cookies["refresh_token"])).status_code == 401
        stale = await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
        )
        assert stale.status_code == 401
    assert await live_token_count(user.id) == 0
    await open_session(user.email, NEW_PASSWORD)


async def test_admin_password_reset_revokes_every_session() -> None:
    await skip_if_database_unavailable()
    admin = await create_user(role="admin")
    target = await create_user()
    admin_access, _ = await open_session(admin.email)
    _, first_refresh = await open_session(target.email)
    _, second_refresh = await open_session(target.email)

    async with create_test_client() as client:
        response = await client.post(
            f"/api/v1/users/{target.id}/reset-password",
            headers={"Authorization": f"Bearer {admin_access}"},
            json={"new_password": NEW_PASSWORD},
        )

    assert response.status_code == 200, response.text
    assert await live_token_count(target.id) == 0
    # The admin's own session is untouched: only the target's credentials changed.
    assert await live_token_count(admin.id) == 1
    for token in (first_refresh, second_refresh):
        assert (await refresh(token)).status_code == 401


async def test_failed_change_password_leaves_sessions_alive() -> None:
    await skip_if_database_unavailable()
    user = await create_user()
    access, refresh_token = await open_session(user.email)

    async with create_test_client() as client:
        response = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {access}"},
            json={"current_password": "WrongPass1!", "new_password": NEW_PASSWORD},
        )

    assert response.status_code == 400
    assert await live_token_count(user.id) == 1
    assert (await refresh(refresh_token)).status_code == 200


async def test_logout_still_revokes_only_its_own_session() -> None:
    await skip_if_database_unavailable()
    user = await create_user()
    _, first_refresh = await open_session(user.email)
    _, second_refresh = await open_session(user.email)

    async with create_test_client() as client:
        client.cookies.set("refresh_token", first_refresh, path="/api/v1/auth")
        response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert await live_token_count(user.id) == 1
    assert (await refresh(first_refresh)).status_code == 401
    assert (await refresh(second_refresh)).status_code == 200
