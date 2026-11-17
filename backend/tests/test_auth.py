import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.config import Settings
from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.auth import AuthOtpChallenge, AuthRefreshToken, AuthSession
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailDeliveryError
from app.utils.recovery_destination import verified_recovery_destination
from app.utils.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_secret,
    utc_now,
)

pytestmark = pytest.mark.asyncio
RETIRED_ROLE_KEYS = json.loads(Path(__file__).with_name("business_role_matrix.json").read_text())[
    "retired_roles"
]


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


async def create_test_user(
    *,
    email: str,
    role: str = "managing_director",
    password: str = "Start123!",
    must_change_password: bool = True,
) -> None:
    async with AsyncSessionLocal() as session:
        users = UserRepository(session)
        await users.add(
            User(
                email=email,
                full_name="Auth Test User",
                role=role,
                employee_code=f"TEST-{uuid4().hex[:8]}",
                password_hash=hash_password(password),
                must_change_password=must_change_password,
            )
        )
        await session.commit()


def create_test_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_request_validation_uses_the_error_contract_without_echoing_inputs() -> None:
    submitted = "not-an-email@example.com"
    async with create_test_client() as client:
        response = await client.post("/api/v1/auth/login", json={"email": [submitted]})
    assert response.status_code == 422
    payload = response.json()
    assert payload["error_code"] == "VALIDATION_ERROR"
    assert isinstance(payload["detail"], str)
    assert {tuple(issue["loc"]) for issue in payload["errors"]} == {
        ("body", "email"),
        ("body", "password"),
    }
    assert all(set(issue) == {"loc", "msg", "type"} for issue in payload["errors"])
    assert submitted not in response.text


async def test_login_otp_me_refresh_and_logout_flow() -> None:
    await skip_if_database_unavailable()
    email = f"auth-{uuid4().hex}@example.com"
    password = "Start123!"
    await create_test_user(email=email, password=password)

    async with create_test_client() as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )

        assert login_response.status_code == 200
        challenge = login_response.json()
        assert challenge["challenge_id"]
        assert len(challenge["dev_otp"]) == 6

        otp_response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
        )

        assert otp_response.status_code == 200
        token_payload = otp_response.json()
        assert token_payload["access_token"]
        assert token_payload["user"]["email"] == email
        assert client.cookies.get("refresh_token")

        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token_payload['access_token']}"},
        )

        assert me_response.status_code == 200
        assert me_response.json()["email"] == email

        refresh_response = await client.post("/api/v1/auth/refresh")

        assert refresh_response.status_code == 200
        assert refresh_response.json()["access_token"]
        first = decode_access_token(token_payload["access_token"])
        rotated = decode_access_token(refresh_response.json()["access_token"])
        assert UUID(first["sid"]) == UUID(rotated["sid"])

        logout_response = await client.post("/api/v1/auth/logout")

        assert logout_response.status_code == 200
        assert (
            await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {refresh_response.json()['access_token']}"},
            )
        ).status_code == 401
        assert not client.cookies.get("refresh_token")


@pytest.mark.parametrize("retired_role", [*RETIRED_ROLE_KEYS, "hr_executive", "super_admin"])
async def test_role_unavailable_to_business_auth_cannot_login_or_receive_reset_challenge(
    retired_role: str,
) -> None:
    await skip_if_database_unavailable()
    email = f"retired-role-{retired_role}-{uuid4().hex}@example.com"
    password = "Start123!"
    await create_test_user(email=email, role=retired_role, password=password)

    legacy_refresh = f"pre-cutover-refresh-{uuid4().hex}"
    legacy_otp = "246810"
    async with AsyncSessionLocal() as session:
        user_id = await session.scalar(select(User.id).where(User.email == email))
        assert user_id is not None
        challenge = AuthOtpChallenge(
            user_id=user_id,
            purpose="login",
            otp_hash=hash_secret(legacy_otp),
            expires_at=utc_now() + timedelta(minutes=5),
        )
        session.add(challenge)
        session.add(
            AuthRefreshToken(
                user_id=user_id,
                token_hash=hash_secret(legacy_refresh),
                expires_at=utc_now() + timedelta(minutes=5),
            )
        )
        await session.commit()
    # A stale role claim must not substitute for the rejected database role.
    legacy_access, _ = create_access_token(user_id, "managing_director")

    async with create_test_client() as client:
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        reset = await client.post("/api/v1/auth/password-reset/request", json={"email": email})
        otp_login = await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": str(challenge.id), "otp": legacy_otp},
        )
        refresh = await client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": legacy_refresh},
        )
        authenticated = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {legacy_access}"},
        )

    assert login.status_code == 401
    assert login.json()["error_code"] == "LOGIN_FAILED"
    assert reset.status_code == 200
    assert reset.json()["challenge_id"] is None
    assert otp_login.status_code == 401
    assert otp_login.json()["error_code"] == "OTP_FAILED"
    assert "refresh_token=" not in otp_login.headers.get("set-cookie", "")
    assert refresh.status_code == 401
    assert refresh.json()["error_code"] == "REFRESH_TOKEN_INVALID"
    assert authenticated.status_code == 401
    assert authenticated.json()["error_code"] == "INVALID_TOKEN"
    async with AsyncSessionLocal() as session:
        challenge = await session.scalar(
            select(AuthOtpChallenge.id).where(
                AuthOtpChallenge.user_id == user_id,
                AuthOtpChallenge.purpose == "password_reset",
            )
        )
        assert challenge is None
        assert (
            await session.scalar(
                select(AuthRefreshToken.id).where(
                    AuthRefreshToken.user_id == user_id,
                    AuthRefreshToken.token_hash == hash_secret(legacy_refresh),
                    AuthRefreshToken.revoked_at.is_(None),
                )
            )
            is not None
        )


async def test_failed_logins_temporarily_lock_account() -> None:
    await skip_if_database_unavailable()
    email = f"lock-{uuid4().hex}@example.com"
    password = "Start123!"
    await create_test_user(email=email, password=password)

    async with create_test_client() as client:
        for _ in range(3):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "Wrong123!"},
            )
            assert response.status_code == 401

        locked_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )

        assert locked_response.status_code == 423


async def test_change_password_clears_forced_change_flag() -> None:
    await skip_if_database_unavailable()
    email = f"change-{uuid4().hex}@example.com"
    password = "Start123!"
    await create_test_user(email=email, password=password)

    async with create_test_client() as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        challenge = login_response.json()
        otp_response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
        )
        access_token = otp_response.json()["access_token"]

        change_response = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": password, "new_password": "Changed123!"},
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert change_response.status_code == 200
        assert client.cookies.get("refresh_token") is None
        assert (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        ).status_code == 401

        login_after_change = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Changed123!"},
        )

        assert login_after_change.status_code == 200


async def test_confirming_password_reset_revokes_existing_access_token() -> None:
    await skip_if_database_unavailable()
    email = f"reset-access-{uuid4().hex}@example.com"
    await create_test_user(email=email, password="Start123!")

    async with create_test_client() as client:
        login = (
            await client.post("/api/v1/auth/login", json={"email": email, "password": "Start123!"})
        ).json()
        token = (
            await client.post(
                "/api/v1/auth/verify-otp",
                json={
                    "challenge_id": login["challenge_id"],
                    "otp": login["dev_otp"],
                },
            )
        ).json()["access_token"]
        reset = (
            await client.post("/api/v1/auth/password-reset/request", json={"email": email})
        ).json()
        confirmed = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "challenge_id": reset["challenge_id"],
                "otp": reset["dev_otp"],
                "new_password": "Changed123!",
            },
        )
        assert confirmed.status_code == 200
        assert (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        ).status_code == 401
        assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_refresh_token_cannot_be_reused_after_rotation() -> None:
    await skip_if_database_unavailable()
    email = f"refresh-{uuid4().hex}@example.com"
    password = "Start123!"
    await create_test_user(email=email, password=password)

    async with create_test_client() as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        challenge = login_response.json()
        await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
        )

        original_refresh_token = client.cookies.get("refresh_token")
        assert original_refresh_token

        refresh_response = await client.post("/api/v1/auth/refresh")

        assert refresh_response.status_code == 200
        rotated_refresh_token = client.cookies.get("refresh_token")
        assert rotated_refresh_token
        assert rotated_refresh_token != original_refresh_token

        reuse_response = await client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": original_refresh_token},
        )

        assert reuse_response.status_code == 401
        assert reuse_response.json()["error_code"] == "REFRESH_TOKEN_INVALID"
        assert (
            await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {refresh_response.json()['access_token']}"},
            )
        ).status_code == 401
        assert (
            await client.post(
                "/api/v1/auth/refresh", cookies={"refresh_token": rotated_refresh_token}
            )
        ).status_code == 401


async def test_legacy_refresh_upgrade_preserves_expiry_and_checks_session_owner() -> None:
    await skip_if_database_unavailable()
    email = f"legacy-session-{uuid4().hex}@example.com"
    other_email = f"other-session-{uuid4().hex}@example.com"
    await create_test_user(email=email)
    await create_test_user(email=other_email)
    refresh = f"legacy-refresh-{uuid4().hex}"
    expiry = utc_now() + timedelta(minutes=5)
    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_by_email(email)
        other = await UserRepository(session).get_by_email(other_email)
        assert user and other
        user_id, other_id = user.id, other.id
        session.add(
            AuthRefreshToken(user_id=user_id, token_hash=hash_secret(refresh), expires_at=expiry)
        )
        await session.commit()

    async with create_test_client() as client:
        rotated = await client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh})
        assert rotated.status_code == 200
        claims = decode_access_token(rotated.json()["access_token"])
        session_id = UUID(claims["sid"])
        assert claims["exp"] <= int(expiry.timestamp())
        invalid, _ = create_access_token(other_id, "managing_director", auth_session_id=session_id)
        assert (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {invalid}"})
        ).status_code == 401

    async with AsyncSessionLocal() as session:
        result = await session.get(AuthSession, session_id)
        assert result and result.user_id == user_id and result.expires_at == expiry


async def test_login_otp_is_invalidated_after_max_failed_attempts() -> None:
    await skip_if_database_unavailable()
    email = f"otp-{uuid4().hex}@example.com"
    password = "Start123!"
    await create_test_user(email=email, password=password)

    async with create_test_client() as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )

        assert login_response.status_code == 200
        challenge = login_response.json()

        for _ in range(3):
            failed_response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"challenge_id": challenge["challenge_id"], "otp": "000000"},
            )
            assert failed_response.status_code == 401
            assert failed_response.json()["error_code"] == "OTP_FAILED"

        locked_response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
        )

        assert locked_response.status_code == 401
        assert locked_response.json()["error_code"] == "OTP_FAILED"


async def test_staging_generic_login_otp_allows_login(monkeypatch) -> None:
    await skip_if_database_unavailable()
    email = f"staging-otp-{uuid4().hex}@example.com"
    password = "Start123!"
    await create_test_user(email=email, password=password)

    custom_settings = Settings(
        app_env="staging",
        staging_login_otp="246810",
        dev_expose_otp=False,
    )
    monkeypatch.setattr("app.services.auth_service.get_settings", lambda: custom_settings)

    async with create_test_client() as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )

        assert login_response.status_code == 200
        challenge = login_response.json()
        assert challenge["dev_otp"] is None

        otp_response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": challenge["challenge_id"], "otp": "246810"},
        )

        assert otp_response.status_code == 200
        assert otp_response.json()["user"]["email"] == email


async def test_generic_login_otp_is_ignored_outside_staging(monkeypatch) -> None:
    await skip_if_database_unavailable()
    email = f"prod-otp-{uuid4().hex}@example.com"
    password = "Start123!"
    await create_test_user(email=email, password=password)

    custom_settings = Settings(
        app_env="production",
        staging_login_otp="246810",
        dev_expose_otp=True,
    )
    monkeypatch.setattr("app.services.auth_service.get_settings", lambda: custom_settings)
    # The real code is never echoed in production, so pin it to complete a valid login.
    monkeypatch.setattr("app.services.auth_service.generate_otp", lambda: "135790")
    monkeypatch.setattr("app.services.auth_service.EmailService.send", lambda *_args, **_kwargs: 1)

    async with create_test_client() as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )

        assert login_response.status_code == 200
        challenge = login_response.json()
        # H12: DEV_EXPOSE_OTP=true must not leak the code in a hardened environment.
        assert challenge["dev_otp"] is None

        generic_response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": challenge["challenge_id"], "otp": "246810"},
        )
        valid_response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": challenge["challenge_id"], "otp": "135790"},
        )

        assert generic_response.status_code == 401
        assert valid_response.status_code == 200


async def test_dev_otp_is_never_exposed_in_staging(monkeypatch) -> None:
    await skip_if_database_unavailable()
    email = f"staging-leak-{uuid4().hex}@example.com"
    await create_test_user(email=email)

    custom_settings = Settings(app_env="staging", dev_expose_otp=True)
    monkeypatch.setattr("app.services.auth_service.get_settings", lambda: custom_settings)
    monkeypatch.setattr("app.services.auth_service.EmailService.send", lambda *_args, **_kwargs: 1)

    async with create_test_client() as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Start123!"},
        )

        assert login_response.status_code == 200
        assert login_response.json()["dev_otp"] is None


@pytest.mark.parametrize("mode", ["delivered", "staging", "echoed", "changed", "failed"])
async def test_recovery_destination_requires_current_email_and_delivered_otp(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await skip_if_database_unavailable()
    email = f"recovery-{uuid4().hex}@example.com"
    await create_test_user(email=email)
    settings = Settings(
        app_env="staging" if mode == "staging" else "test",
        dev_expose_otp=mode == "echoed",
        staging_login_otp="246810" if mode == "staging" else None,
        support_recovery_key=SecretStr("disposable-test-recovery-key-only-not-production"),
    )
    monkeypatch.setattr("app.services.auth_service.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.auth_service.generate_otp", lambda: "193826")

    def mail(*_args, recipients: list[str], subject: str, body: str) -> int:
        assert recipients == [email] and "193826" in body and "Verification" in subject
        if mode == "failed":
            raise EmailDeliveryError("Synthetic delivery failure.")
        return 1

    monkeypatch.setattr("app.services.auth_service.EmailService.send", mail)
    async with create_test_client() as client:
        login = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "Start123!"}
        )
        if mode == "failed":
            assert login.status_code == 503 and "challenge_id" not in login.json()
            async with AsyncSessionLocal() as db:
                user = await UserRepository(db).get_by_email(email)
                assert user is not None and user.recovery_email_digest is None
                rejected = await db.scalar(
                    select(AuthOtpChallenge).where(AuthOtpChallenge.user_id == user.id)
                )
                assert rejected is not None and rejected.delivery_email_digest is None
                assert rejected.consumed_at is not None
            return
        assert login.status_code == 200, login.text
        challenge = login.json()
        assert challenge["dev_otp"] == ("193826" if mode == "echoed" else None)
        async with AsyncSessionLocal() as db:
            user = await UserRepository(db).get_by_email(email, for_update=True)
            assert user is not None and user.recovery_email_verified_at is None
            user_id = user.id
            if mode == "changed":
                user.email = f"changed-{uuid4().hex}@example.com"
                await db.commit()
        verified = await client.post(
            "/api/v1/auth/verify-otp",
            json={
                "challenge_id": challenge["challenge_id"],
                "otp": "246810" if mode == "staging" else "193826",
            },
        )
        assert verified.status_code == 200, verified.text
        assert "recovery_email_digest" not in verified.text
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            assert user is not None
            binding = verified_recovery_destination(
                settings, user.id, user.email, user.recovery_email_digest,
                user.recovery_email_verified_at,
            )
            assert (binding is not None) == (mode == "delivered")
            if binding is not None:
                assert binding not in verified.text and user.email not in binding
                assert verified_recovery_destination(
                    settings, user.id, "different@example.com", binding,
                    user.recovery_email_verified_at,
                ) is None


async def test_auth_returns_service_unavailable_when_otp_delivery_fails(monkeypatch) -> None:
    await skip_if_database_unavailable()
    email = f"otp-mail-{uuid4().hex}@example.com"
    await create_test_user(email=email)
    settings = Settings(app_env="production", dev_expose_otp=True)
    monkeypatch.setattr("app.services.auth_service.get_settings", lambda: settings)

    def reject_delivery(*_args, **_kwargs):
        raise EmailDeliveryError("Provider unavailable.")

    monkeypatch.setattr("app.services.auth_service.EmailService.send", reject_delivery)
    async with create_test_client() as client:
        responses = [
            await client.post("/api/v1/auth/login", json={"email": email, "password": "Start123!"}),
            await client.post("/api/v1/auth/password-reset/request", json={"email": email}),
        ]
    for response in responses:
        assert response.status_code == 503
        assert response.json()["error_code"] == "EMAIL_DELIVERY_UNAVAILABLE"
        assert "challenge_id" not in response.json()


async def test_auth_rate_limit_blocks_repeated_login_attempts(monkeypatch) -> None:
    await skip_if_database_unavailable()
    email = f"limited-{uuid4().hex}@example.com"
    password = "Start123!"
    await create_test_user(email=email, password=password)

    custom_settings = Settings(
        auth_rate_limit_max_requests=1,
        auth_rate_limit_window_seconds=60,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: custom_settings)

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        second_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )

    assert first_response.status_code == 200
    assert first_response.headers["X-RateLimit-Limit"] == "1"
    assert first_response.headers["X-RateLimit-Remaining"] == "0"
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "RATE_LIMITED"
    assert second_response.headers["Retry-After"] == "60"
