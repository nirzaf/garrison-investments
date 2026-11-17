import asyncio
import re
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.services.email_service import EmailDeliveryError
from app.utils.security import create_access_token
from tests.test_auth import create_test_user, skip_if_database_unavailable
from tests.test_auth import isolated_engine_pool as isolated_engine_pool

HOST = "https://superadmin.garrisons.lk"
API = "/api/v1/super-admin"


@pytest.mark.parametrize(
    ("host", "environment", "enabled", "expected"),
    [
        (HOST, "test", False, 404),
        ("https://portal.garrisons.lk", "test", True, 404),
        (HOST, "test", True, 401),
        (HOST, "production", True, 404),
    ],
)
async def test_portal_requires_dedicated_host_activation_and_authentication(
    monkeypatch: pytest.MonkeyPatch, host: str, environment: str, enabled: bool, expected: int
) -> None:
    monkeypatch.setattr(
        "app.api.v1.super_admin.get_settings",
        lambda: Settings(app_env=environment, super_admin_enabled=enabled),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url=host
    ) as client:
        result = await client.get(f"{API}/overview")
    assert result.status_code == expected


@pytest.fixture
def portal_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        super_admin_enabled=True,
        super_admin_otp_key=SecretStr("synthetic-otp-test-key-for-isolated-testing"),
        app_env="test",
        dev_expose_otp=True,
    )
    monkeypatch.setattr("app.api.v1.super_admin.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.auth_service.get_settings", lambda: settings)


@pytest.mark.usefixtures("isolated_engine_pool", "portal_settings")
async def test_technical_login_otp_scope_replay_and_logout(monkeypatch: pytest.MonkeyPatch) -> None:
    await skip_if_database_unavailable()
    email = f"operator-{uuid4().hex}@example.com"
    await create_test_user(email=email, role="super_admin", must_change_password=False)
    pending_email = f"pending-{uuid4().hex}@example.com"
    await create_test_user(email=pending_email, role="super_admin", must_change_password=True)
    director_email = f"director-{uuid4().hex}@example.com"
    await create_test_user(email=director_email)
    outbox: dict[str, str] = {}

    def send(*_: object, recipients: list[str], body: str, subject: str) -> int:
        assert recipients == [email]
        assert subject == "Garrisons Super Admin verification code"
        match = re.search(r"[0-9]{6}", body)
        assert match
        outbox[email] = match.group()
        return 1

    monkeypatch.setattr("app.services.email_service.EmailService.send", send)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url=HOST, headers={"Origin": HOST}
    ) as client:
        for other_email in (pending_email, director_email):
            result = await client.post(
                f"{API}/auth/login", json={"email": other_email, "password": "Start123!"}
            )
            assert result.status_code == 401
        login_data = {"email": email, "password": "Start123!"}
        result = await client.post(
            f"{API}/auth/login", json=login_data, headers={"Origin": "https://portal.garrisons.lk"}
        )
        assert result.status_code == 403
        result = await client.post("/api/v1/auth/login", json=login_data)
        assert result.status_code == 401
        result = await client.post(f"{API}/auth/login", json=login_data)
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert set(result.json()) == {"challenge_id", "expires_at"}
        assert email in outbox
        body = {"challenge_id": result.json()["challenge_id"], "otp": outbox[email]}
        assert (await client.post(f"{API}/auth/login", json=login_data)).status_code == 429
        assert (await client.post("/api/v1/auth/verify-otp", json=body)).status_code == 401
        wrong = "999999" if outbox[email] != "999999" else "999998"
        assert (
            await client.post(f"{API}/auth/verify-otp", json=dict(body, otp=wrong))
        ).status_code == 401

        responses = await asyncio.gather(
            client.post(f"{API}/auth/verify-otp", json=body),
            client.post(f"{API}/auth/verify-otp", json=body),
        )
        assert sorted(response.status_code for response in responses) == [200, 401]
        success = next(response for response in responses if response.status_code == 200)
        assert "set-cookie" not in success.headers
        headers = {"Authorization": f"Bearer {success.json()['access_token']}"}
        overview = await client.get(f"{API}/overview", headers=headers)
        assert overview.status_code == 200
        assert overview.headers["cache-control"] == "no-store"
        assert overview.json()["scope"] == "platform"
        assert set(overview.json()) == {"scope", "source", "status", "observed_at"}
        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401

        business_token, _ = create_access_token(uuid4(), "managing_director")
        denied = await client.get(
            f"{API}/overview", headers={"Authorization": f"Bearer {business_token}"}
        )
        assert denied.status_code == 401
        assert (await client.post(f"{API}/auth/logout", headers=headers)).status_code == 204
        assert (await client.get(f"{API}/overview", headers=headers)).status_code == 401


@pytest.mark.usefixtures("isolated_engine_pool", "portal_settings")
async def test_technical_login_fails_closed_when_mail_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    email = f"operator-{uuid4().hex}@example.com"
    await create_test_user(email=email, role="super_admin", must_change_password=False)

    def fail_delivery(*_: object, **__: object) -> int:
        raise EmailDeliveryError("Synthetic test failure")

    monkeypatch.setattr("app.services.email_service.EmailService.send", fail_delivery)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url=HOST, headers={"Origin": HOST}
    ) as client:
        result = await client.post(
            f"{API}/auth/login", json={"email": email, "password": "Start123!"}
        )
    assert result.status_code == 503
    assert result.json()["error_code"] == "EMAIL_DELIVERY_UNAVAILABLE"
