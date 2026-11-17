import asyncio
import base64
import json
from datetime import timedelta
from hashlib import sha256
from ipaddress import ip_address
from secrets import token_hex, token_urlsafe
from uuid import UUID, uuid4

import cbor2
import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from app.api.v1.support import CSRF_COOKIE, SESSION_COOKIE
from app.config import Settings
from app.database import AsyncSessionLocal
from app.main import create_app
from app.models.activity_log import ActivityLog
from app.models.support_cases import (
    SupportCase,
    SupportCaseMember,
    SupportCaseRequest,
    SupportLogRead,
    SupportOperatorGrant,
)
from app.models.support_identity import (
    SupportAuthEvent,
    SupportCredential,
    SupportEmailOtp,
    SupportOperator,
    SupportSession,
)
from app.services.email_service import EmailDeliveryError
from app.services.support_identity import SUPPORT_HOST, SUPPORT_ORIGIN
from app.utils.security import utc_now
from tests.test_auth import isolated_engine_pool as isolated_engine_pool
from tests.test_auth import skip_if_database_unavailable

API = "/api/v1/support"


def encoded(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(app_env="test", support_portal_enabled=True)
    monkeypatch.setattr("app.api.v1.support.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.support_identity.get_settings", lambda: settings)


async def seed_operator() -> tuple[UUID, bytes, ec.EllipticCurvePrivateKey]:
    operator_id = uuid4()
    private_key = ec.generate_private_key(ec.SECP256R1())
    credential_id = uuid4().bytes
    key = private_key.public_key().public_numbers()
    async with AsyncSessionLocal() as session:
        session.add(
            SupportOperator(
                id=operator_id, display_label="Synthetic", status="active", grant_epoch=1
            )
        )
        await session.flush()
        session.add(
            SupportCredential(
                id=uuid4(),
                operator_id=operator_id,
                credential_hash=sha256(credential_id).hexdigest(),
                public_key=cbor2.dumps(
                    {1: 2, 3: -7, -1: 1, -2: key.x.to_bytes(32), -3: key.y.to_bytes(32)}
                ),
                sign_count=0,
            )
        )
        await session.commit()
    return operator_id, credential_id, private_key


def sign(
    options: dict,
    operator_id: UUID,
    credential_id: bytes,
    key: ec.EllipticCurvePrivateKey,
    *,
    origin: str = SUPPORT_ORIGIN,
    rp_id: str = SUPPORT_HOST,
    flags: int = 5,
    counter: int = 1,
) -> dict:
    client = json.dumps(
        {"type": "webauthn.get", "origin": origin, "challenge": options["public_key"]["challenge"]}
    ).encode()
    auth = sha256(rp_id.encode()).digest() + bytes([flags]) + counter.to_bytes(4)
    signature = key.sign(auth + sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    return {
        "challenge_id": options["challenge_id"],
        "credential": {
            "id": encoded(credential_id),
            "rawId": encoded(credential_id),
            "type": "public-key",
            "response": {
                "authenticatorData": encoded(auth),
                "clientDataJSON": encoded(client),
                "signature": encoded(signature),
                "userHandle": encoded(operator_id.bytes),
            },
        },
    }


def client(*, base_url: str = SUPPORT_ORIGIN) -> httpx.AsyncClient:
    address = uuid4().hex
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_app(), client=(f"2001:db8::{address[:4]}:{address[4:8]}", 12345)
        ),
        base_url=base_url,
        headers={"Origin": SUPPORT_ORIGIN},
    )


async def options(session: httpx.AsyncClient, operator_id: UUID) -> dict:
    response = await session.post(f"{API}/auth/options", json={"operator_id": str(operator_id)})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["public_key"]["userVerification"] == "required"
    return response.json()


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_passkey_replay_cookie_realm_and_csrf() -> None:
    await skip_if_database_unavailable()
    operator, credential, key = await seed_operator()
    async with (
        client() as first,
        client() as second,
        client(base_url="https://portal.garrisons.lk") as business,
    ):
        assert (await business.get(f"{API}/me")).status_code == 404
        assert (await first.get(f"{API}/me")).status_code == 401
        assert (
            await first.post(
                f"{API}/auth/options",
                json={"operator_id": str(operator)},
                headers={"Origin": "https://portal.garrisons.lk"},
            )
        ).status_code == 403
        info = await options(first, operator)
        proof = sign(info, operator, credential, key)
        attempts = await asyncio.gather(
            first.post(f"{API}/auth/verify", json=proof),
            second.post(f"{API}/auth/verify", json=proof),
        )
        assert sorted(response.status_code for response in attempts) == [200, 401]
        winner = first if attempts[0].is_success else second
        response = next(response for response in attempts if response.is_success)
        assert set(response.json()) == {"operator_id", "expires_at"}
        cookie = next(
            h for h in response.headers.get_list("set-cookie") if h.startswith(SESSION_COOKIE + "=")
        )
        assert all(
            flag in cookie.lower() for flag in ("httponly", "secure", "samesite=strict", "path=/")
        )
        assert "domain=" not in cookie.lower()
        secret = winner.cookies[SESSION_COOKIE]
        assert secret not in response.text
        assert (await winner.get(f"{API}/me")).json()["operator_id"] == str(operator)
        assert (await winner.get("/api/v1/auth/me")).status_code == 401
        assert (await winner.post(f"{API}/auth/logout")).status_code == 403
        assert (
            await winner.post(
                f"{API}/auth/logout", headers={"X-Support-CSRF": winner.cookies[CSRF_COOKIE]}
            )
        ).status_code == 204
        assert (
            await winner.get(f"{API}/me", headers={"Cookie": f"{SESSION_COOKIE}={secret}"})
        ).status_code == 401
    async with AsyncSessionLocal() as session:
        acts = list(
            await session.scalars(
                select(SupportAuthEvent.action)
                .where(SupportAuthEvent.operator_id == operator)
                .order_by(SupportAuthEvent.occurred_at)
            )
        )
        assert acts == ["login", "logout"]
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SupportSession)
                .where(SupportSession.operator_id == operator)
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_passkeys_reject_wrong_origin_rp_and_verification_then_enforce_idle() -> None:
    await skip_if_database_unavailable()
    operator, credential, key = await seed_operator()
    async with client() as browser:
        for malformed in (
            {"origin": "https://portal.garrisons.lk"},
            {"rp_id": "garrisons.lk"},
            {"flags": 1},
            {"flags": 0x0D},
        ):
            info = await options(browser, operator)
            assert (
                await browser.post(
                    f"{API}/auth/verify", json=sign(info, operator, credential, key, **malformed)
                )
            ).status_code == 401
            assert (
                await browser.post(f"{API}/auth/verify", json=sign(info, operator, credential, key))
            ).status_code == 401
        info = await options(browser, operator)
        assert (
            await browser.post(f"{API}/auth/verify", json=sign(info, operator, credential, key))
        ).status_code == 200
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SupportSession)
                .where(SupportSession.operator_id == operator)
                .values(last_seen_at=utc_now() - timedelta(minutes=16))
            )
            await session.commit()
        assert (await browser.get(f"{API}/me")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_case_log_reads_check_live_scope_and_commit_redacted_audit() -> None:
    await skip_if_database_unavailable()
    operator, credential, key = await seed_operator()
    case_id = uuid4()
    request_id = uuid4().hex
    marker = "synthetic-confidential-payload"
    now = utc_now()
    query = {
        "request_id": request_id,
        "started_at": (now - timedelta(minutes=1)).isoformat(),
        "ended_at": (now + timedelta(minutes=1)).isoformat(),
    }
    async with AsyncSessionLocal() as session:
        session.add(SupportCase(id=case_id, status="open"))
        session.add(
            ActivityLog(
                request_id=request_id,
                action="http.request",
                entity_type="request",
                http_method="GET",
                status_code=200,
                comments=marker,
            )
        )
        await session.flush()
        session.add(SupportCaseMember(case_id=case_id, operator_id=operator))
        session.add(SupportCaseRequest(case_id=case_id, request_id=request_id))
        await session.commit()
    route = f"{API}/cases/{case_id}/logs"
    async with client() as browser:
        assert (await browser.get(route, params=query)).status_code == 401
        info = await options(browser, operator)
        assert (
            await browser.post(f"{API}/auth/verify", json=sign(info, operator, credential, key))
        ).status_code == 200
        assert (await browser.get(route, params=query)).status_code == 403
        async with AsyncSessionLocal() as session:
            session.add(SupportOperatorGrant(operator_id=operator, capability="logs.runtime"))
            await session.commit()
        assert (
            await browser.get(route, params={**query, "request_id": uuid4().hex})
        ).status_code == 404
        result = await browser.get(route, params=query)
        assert result.status_code == 200 and marker not in result.text
        assert result.json()["events"][0]["status_code"] == 200
        async with AsyncSessionLocal() as session:
            evidence = await session.scalar(
                select(SupportLogRead).where(SupportLogRead.operator_id == operator)
            )
            assert (
                evidence and evidence.event_count == 1 and evidence.source_request_id == request_id
            )
            assert evidence.request_id == result.headers["x-request-id"]
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    delete(SupportLogRead).where(SupportLogRead.id == evidence.id)
                )
            await session.rollback()
            session.add_all(
                [
                    SupportLogRead(
                        id=uuid4(),
                        operator_id=operator,
                        case_id=case_id,
                        request_id=uuid4().hex,
                        source_request_id=request_id,
                        started_at=now - timedelta(minutes=1),
                        ended_at=now,
                        requested_limit=25,
                        event_count=0,
                        occurred_at=utc_now(),
                    )
                    for _ in range(18)
                ]
            )
            await session.commit()
        reads = await asyncio.gather(
            browser.get(route, params=query), browser.get(route, params=query)
        )
        assert sorted(read.status_code for read in reads) == [200, 429]
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(SupportCaseMember).where(
                    SupportCaseMember.case_id == case_id, SupportCaseMember.operator_id == operator
                )
            )
            await session.commit()
        assert (await browser.get(route, params=query)).status_code == 404


@pytest.mark.asyncio
async def test_support_portal_is_inactive_in_production_even_when_flagged(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.v1.support.get_settings",
        lambda: Settings(app_env="production", support_portal_enabled=True),
    )
    async with client() as browser:
        response = await browser.get(f"{API}/me")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_production_support_accepts_only_configured_proxy_peer(monkeypatch) -> None:
    peer = "192.0.2.10"
    monkeypatch.setattr(
        "app.api.v1.support.get_settings",
        lambda: Settings(
            app_env="production", support_portal_enabled=True, support_ingress_peer=ip_address(peer)
        ),
    )
    forwarded = {"X-Forwarded-For": peer, "X-Real-IP": peer, "X-Forwarded-Host": SUPPORT_HOST}
    transport = httpx.ASGITransport(app=create_app(), client=("192.0.2.11", 40000))
    async with httpx.AsyncClient(transport=transport, base_url=SUPPORT_ORIGIN) as untrusted:
        assert (await untrusted.get(f"{API}/me", headers=forwarded)).status_code == 404

    transport = httpx.ASGITransport(app=create_app(), client=(peer, 40000))
    async with httpx.AsyncClient(transport=transport, base_url=SUPPORT_ORIGIN) as trusted:
        assert (await trusted.get(f"{API}/me", headers={"Host": "garrisons.lk"})).status_code == 404
        result = await trusted.get(f"{API}/me")
        assert result.status_code == 401
        assert result.headers["cache-control"] == "no-store"
        payload = {"operator_id": str(uuid4())}
        missing = await trusted.post(f"{API}/auth/options", json=payload)
        assert missing.status_code == 403
        foreign = await trusted.post(
            f"{API}/auth/options", json=payload, headers={"Origin": "https://garrisons.lk"}
        )
        assert foreign.status_code == 403


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_operator_epoch_change_denies_pending_challenge_and_session() -> None:
    await skip_if_database_unavailable()
    operator, credential, key = await seed_operator()
    async with client() as browser:
        info = await options(browser, operator)
        assert (
            await browser.post(f"{API}/auth/verify", json=sign(info, operator, credential, key))
        ).status_code == 200
        stale = await options(browser, operator)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SupportOperator).where(SupportOperator.id == operator).values(grant_epoch=2)
            )
            await session.commit()
        assert (await browser.get(f"{API}/me")).status_code == 401
        assert (
            await browser.post(
                f"{API}/auth/verify", json=sign(stale, operator, credential, key, counter=2)
            )
        ).status_code == 401


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_cli_handoff_requires_browser_passkey_and_never_returns_cli_credentials() -> None:
    await skip_if_database_unavailable()
    operator, credential, key = await seed_operator()
    token, csrf, pairing = token_urlsafe(32), token_urlsafe(32), token_hex(6)
    details = {
        "operator_id": str(operator),
        "token_hash": sha256(token.encode()).hexdigest(),
        "csrf_hash": sha256(csrf.encode()).hexdigest(),
        "code_hash": sha256(pairing.encode()).hexdigest(),
    }
    async with client() as terminal, client() as browser:
        cookies = {"Cookie": f"{SESSION_COOKIE}={token}; {CSRF_COOKIE}={csrf}"}
        assert (await terminal.get(f"{API}/me", headers=cookies)).status_code == 401
        start = await terminal.post(f"{API}/auth/cli/start", json=details)
        assert start.status_code == 200 and set(start.json()) == {"challenge_id"}
        assert "set-cookie" not in start.headers
        invalid = await browser.post(
            f"{API}/auth/cli/options", json={**start.json(), "pairing_code": "0" * 12}
        )
        assert invalid.status_code == 401
        proof = await browser.post(
            f"{API}/auth/cli/options", json={**start.json(), "pairing_code": pairing}
        )
        assert proof.status_code == 200, proof.text
        assertion = sign(proof.json(), operator, credential, key)
        wrong_realm = await browser.post(f"{API}/auth/verify", json=assertion)
        assert wrong_realm.status_code == 401
        route = f"{API}/auth/cli/verify"
        payload = {**assertion, "pairing_code": pairing}
        approved = await asyncio.gather(
            browser.post(route, json=payload), browser.post(route, json=payload)
        )
        assert sorted(response.status_code for response in approved) == [204, 401]
        assert all("set-cookie" not in response.headers for response in approved)
        assert (await browser.get(f"{API}/me")).status_code == 401
        profile = await terminal.get(f"{API}/me", headers=cookies)
        assert profile.status_code == 200
        assert profile.json()["operator_id"] == str(operator)
        denied = await terminal.post(f"{API}/auth/logout", headers=cookies)
        assert denied.status_code == 403
        signed_out = await terminal.post(
            f"{API}/auth/logout", headers={**cookies, "X-Support-CSRF": csrf}
        )
        assert signed_out.status_code == 204
        assert (await terminal.get(f"{API}/me", headers=cookies)).status_code == 401


def mock_support_email(
    monkeypatch: pytest.MonkeyPatch, operator: UUID, *, accepted: bool = True
) -> list[str]:
    mailbox = "synthetic-support@example.com"
    settings = Settings(
        app_env="test",
        support_email_otp_key=SecretStr("synthetic-test-key-for-support-email"),
        support_email_otp_recipients={operator: mailbox},
    )
    monkeypatch.setattr("app.services.support_identity.get_settings", lambda: settings)
    codes: list[str] = []

    def send(_sender: object, *, recipients: list[str], subject: str, body: str) -> int:
        assert recipients == [mailbox] and "Super Admin" in subject
        if not accepted:
            raise EmailDeliveryError("Synthetic transport failure")
        code = body.splitlines()[0].rsplit(" ", 1)[-1]
        assert len(code) == 6 and code.isascii() and code.isdigit()
        codes.append(code)
        return 1

    monkeypatch.setattr("app.services.support_identity.EmailService.send", send)
    return codes


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_email_code_completes_browser_sign_in_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    operator, credential, key = await seed_operator()
    codes = mock_support_email(monkeypatch, operator)
    async with client() as browser, client() as retry:
        info = await options(browser, operator)
        proof = sign(info, operator, credential, key)
        pending = await browser.post(f"{API}/auth/verify", json=proof)
        assert pending.status_code == 200 and len(codes) == 1
        assert "set-cookie" not in pending.headers
        assert set(pending.json()) == {"otp_reference"}
        assert (await browser.get(f"{API}/me")).status_code == 401
        assert (await browser.post(f"{API}/auth/verify", json=proof)).status_code == 401
        wrong = "000000" if codes[0] != "000000" else "999999"
        endpoint = f"{API}/auth/verify-otp"
        base = pending.json()
        assert (await browser.post(endpoint, json={**base, "otp": wrong})).status_code == 401
        results = await asyncio.gather(
            browser.post(endpoint, json={**base, "otp": codes[0]}),
            retry.post(endpoint, json={**base, "otp": codes[0]}),
        )
        assert sorted(result.status_code for result in results) == [200, 401]
        winner = browser if results[0].is_success else retry
        assert (await winner.get(f"{API}/me")).json()["operator_id"] == str(operator)


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
@pytest.mark.parametrize("invalid", ["attempt_limit", "expired", "epoch_changed"])
async def test_email_code_rechecks_expiry_attempts_and_operator_epoch(
    monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    await skip_if_database_unavailable()
    operator, credential, key = await seed_operator()
    codes = mock_support_email(monkeypatch, operator)
    async with client() as browser:
        info = await options(browser, operator)
        pending = await browser.post(
            f"{API}/auth/verify", json=sign(info, operator, credential, key)
        )
        assert pending.status_code == 200 and len(codes) == 1
        endpoint = f"{API}/auth/verify-otp"
        base = pending.json()
        if invalid == "attempt_limit":
            wrong = "000000" if codes[0] != "000000" else "999999"
            for _ in range(5):
                response = await browser.post(endpoint, json={**base, "otp": wrong})
                assert response.status_code == 401
        else:
            async with AsyncSessionLocal() as db:
                if invalid == "expired":
                    record = await db.get(SupportEmailOtp, UUID(base["otp_reference"]))
                    assert record is not None
                    record.expires_at = utc_now() - timedelta(seconds=1)
                else:
                    actor = await db.get(SupportOperator, operator)
                    assert actor is not None
                    actor.grant_epoch += 1
                await db.commit()
        denied = await browser.post(endpoint, json={**base, "otp": codes[0]})
        assert denied.status_code == 401 and "set-cookie" not in denied.headers


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
@pytest.mark.parametrize("missing_binding", [True, False])
async def test_email_code_fails_closed_for_missing_binding_or_unaccepted_delivery(
    monkeypatch: pytest.MonkeyPatch, missing_binding: bool
) -> None:
    await skip_if_database_unavailable()
    operator, credential, key = await seed_operator()
    codes = mock_support_email(
        monkeypatch, uuid4() if missing_binding else operator, accepted=False
    )
    async with client() as browser:
        info = await options(browser, operator)
        response = await browser.post(
            f"{API}/auth/verify", json=sign(info, operator, credential, key)
        )
        assert response.status_code == (401 if missing_binding else 503)
        assert "otp_reference" not in response.json() and "set-cookie" not in response.headers
        assert (await browser.get(f"{API}/me")).status_code == 401
        assert not codes


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_email_code_is_bound_to_cli_pairing(monkeypatch: pytest.MonkeyPatch) -> None:
    await skip_if_database_unavailable()
    operator, credential, key = await seed_operator()
    codes = mock_support_email(monkeypatch, operator)
    token, csrf, pairing = token_urlsafe(32), token_urlsafe(32), token_hex(6)
    async with client() as terminal, client() as browser:
        cookies = {"Cookie": f"{SESSION_COOKIE}={token}; {CSRF_COOKIE}={csrf}"}
        start = await terminal.post(
            f"{API}/auth/cli/start",
            json={
                "operator_id": str(operator),
                "token_hash": sha256(token.encode()).hexdigest(),
                "csrf_hash": sha256(csrf.encode()).hexdigest(),
                "code_hash": sha256(pairing.encode()).hexdigest(),
            },
        )
        proof = await browser.post(
            f"{API}/auth/cli/options", json={**start.json(), "pairing_code": pairing}
        )
        pending = await browser.post(
            f"{API}/auth/cli/verify",
            json={**sign(proof.json(), operator, credential, key), "pairing_code": pairing},
        )
        assert pending.status_code == 202 and len(codes) == 1
        assert "set-cookie" not in pending.headers
        assert (await terminal.get(f"{API}/me", headers=cookies)).status_code == 401
        endpoint = f"{API}/auth/verify-otp"
        base = {**pending.json(), "otp": codes[0]}
        assert (await browser.post(endpoint, json=base)).status_code == 401
        confirmed = await browser.post(endpoint, json={**base, "pairing_code": pairing})
        assert confirmed.status_code == 204 and "set-cookie" not in confirmed.headers
        assert (await browser.get(f"{API}/me")).status_code == 401
        assert (await terminal.get(f"{API}/me", headers=cookies)).status_code == 200
