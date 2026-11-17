import json
from collections.abc import AsyncGenerator
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.database import engine, get_db
from app.main import create_app
from app.models.base import Base
from app.models.support_cases import SupportOperatorGrant
from app.models.support_custody import SupportCustodyAction
from app.models.support_identity import (
    SupportAuthEvent,
    SupportCredential,
    SupportLoginChallenge,
    SupportOperator,
    SupportSession,
)
from app.models.support_registration import (
    SupportBootstrap,
    SupportBootstrapEvent,
    SupportRegistration,
)
from app.services.support_bootstrap import issue_first_custodian_invitations
from app.services.support_identity import SUPPORT_ORIGIN
from scripts import bootstrap_support
from scripts.bootstrap_support import (
    CustodyApproval,
    approved_otp_bindings,
    read_approval,
    verify_otp_config,
    write_otp_config,
)
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_identity import API, options, sign
from tests.test_support_identity import enabled as enabled
from tests.test_support_registration import REGISTRATION, attestation, registration_options


def test_offline_approval_requires_exact_digest_private_file_and_independent_people(
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    data = {
        "version": 1,
        "purpose": "initial_support_custody",
        "preparer_reference": str(uuid4()),
        "reviewer_reference": str(uuid4()),
        "custodians": [
            {"person_reference": str(uuid4()), "mailbox": f"operator-{index}@example.com"}
            for index in range(2)
        ],
    }
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    digest = SecretStr(sha256(path.read_bytes()).hexdigest())
    assert read_approval(path, digest)[0].custodians[0].mailbox == "operator-0@example.com"
    with pytest.raises(ValueError, match="digest did not match"):
        read_approval(path, SecretStr("a" * 64))
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        read_approval(path, digest)
    path.chmod(0o600)
    path.write_text(json.dumps({**data, "reviewer_reference": data["preparer_reference"]}))
    with pytest.raises(ValueError, match="record is invalid"):
        read_approval(path, SecretStr(sha256(path.read_bytes()).hexdigest()))


@pytest.mark.asyncio
@pytest.mark.usefixtures("enabled")
async def test_both_first_custodians_stay_pending_until_all_devices_are_enrolled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    schema = "bootstrap_test_" + uuid4().hex
    isolated = create_async_engine(
        engine.url, connect_args={"server_settings": {"search_path": schema}}
    )
    sessions = async_sessionmaker(isolated, expire_on_commit=False)
    tables = [
        Base.metadata.tables[model.__tablename__]
        for model in (
            SupportOperator,
            SupportCredential,
            SupportLoginChallenge,
            SupportSession,
            SupportAuthEvent,
            SupportOperatorGrant,
            SupportCustodyAction,
            SupportRegistration,
            SupportBootstrap,
            SupportBootstrapEvent,
        )
    ]
    try:
        async with isolated.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(
                lambda sync: Base.metadata.create_all(sync, tables=tables, checkfirst=False)
            )

        async def fresh_session() -> AsyncGenerator[AsyncSession, None]:
            async with sessions() as db:
                yield db

        app = create_app()
        app.dependency_overrides[get_db] = fresh_session
        monkeypatch.setattr(bootstrap_support, "AsyncSessionLocal", sessions)
        approval = CustodyApproval.model_validate({
            "version": 1, "purpose": "initial_support_custody",
            "preparer_reference": uuid4(), "reviewer_reference": uuid4(),
            "custodians": [
                {"person_reference": uuid4(), "mailbox": "operator'$first@example.com"},
                {"person_reference": uuid4(), "mailbox": "second@example.com"},
            ],
        })
        with pytest.raises(ValueError, match="does not match the issued registry"):
            await approved_otp_bindings(approval, "a" * 64)
        async with sessions() as db:
            invited = await issue_first_custodian_invitations(
                db, approval_digest="a" * 64, reissue=False
            )
            await db.commit()
        first, second = invited
        with pytest.raises(ValueError, match="does not match the issued registry"):
            await approved_otp_bindings(approval, "b" * 64)
        bindings = await approved_otp_bindings(approval, "a" * 64)
        assert bindings == {first: "operator'$first@example.com", second: "second@example.com"}
        tmp_path.chmod(0o700)
        config = tmp_path / "otp-bindings.env"
        write_otp_config(config, bindings)
        assert config.stat().st_mode & 0o777 == 0o600
        text_value = config.read_text()
        assert all(token not in text_value for tokens in invited.values() for token in tokens)
        assert "SUPPORT_EMAIL_OTP_KEY" not in text_value and r"\u0024" in text_value
        env = dotenv_values(config)
        monkeypatch.setenv(
            "SUPPORT_EMAIL_OTP_RECIPIENTS", env["SUPPORT_EMAIL_OTP_RECIPIENTS"] or ""
        )
        monkeypatch.setenv("SUPPORT_EMAIL_OTP_KEY", "synthetic-activation-key-at-least-32-bytes")
        monkeypatch.setattr(bootstrap_support, "get_settings", lambda: Settings(app_env="test"))
        verify_otp_config(bindings)
        with pytest.raises(ValueError, match="do not match the approved custodians"):
            verify_otp_config({first: bindings[second], second: bindings[first]})
        with pytest.raises(FileExistsError):
            write_otp_config(config, bindings)
        monkeypatch.delenv("SUPPORT_EMAIL_OTP_KEY")
        monkeypatch.delenv("SUPPORT_EMAIL_OTP_RECIPIENTS")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=SUPPORT_ORIGIN,
            headers={"Origin": SUPPORT_ORIGIN},
        ) as browser:

            async def register(invitation: str, key: ec.EllipticCurvePrivateKey, credential: bytes):
                challenge = await registration_options(browser, invitation)
                return await browser.post(
                    f"{REGISTRATION}/verify",
                    json={
                        "invitation": invitation,
                        "credential": attestation(challenge, credential, key),
                    },
                )

            key, credential = ec.generate_private_key(ec.SECP256R1()), uuid4().bytes
            first_device = await register(invited[first][0], key, credential)
            assert first_device.json() == {"activated": False}
            async with sessions() as db:
                replaced = await issue_first_custodian_invitations(
                    db, approval_digest="a" * 64, reissue=True
                )
                await db.commit()
            assert [len(tokens) for tokens in replaced.values()] == [1, 2]
            for old_token in (*invited[first], *invited[second]):
                expired = await browser.post(
                    f"{REGISTRATION}/options", json={"invitation": old_token}
                )
                assert expired.status_code == 403
            expired_status = await browser.post(
                f"{REGISTRATION}/status", json={"invitation": invited[second][0]},
            )
            assert expired_status.status_code == 403
            duplicate = await register(replaced[second][0], key, uuid4().bytes)
            assert duplicate.status_code == 403
            next_key = ec.generate_private_key(ec.SECP256R1())
            response = await register(replaced[first][0], next_key, uuid4().bytes)
            assert response.json() == {"activated": False, "awaiting_other_custodian": True}
            status = await browser.post(
                f"{REGISTRATION}/status", json={"invitation": replaced[first][0]},
            )
            assert status.json() == {"operator_id": str(first), "state": "registered"}
            premature = await options(browser, first)
            result = await browser.post(
                f"{API}/auth/verify", json=sign(premature, first, credential, key)
            )
            assert result.status_code == 401
            for index, invitation in enumerate(replaced[second]):
                result = await register(
                    invitation, ec.generate_private_key(ec.SECP256R1()), uuid4().bytes
                )
                assert result.json() == {"activated": index == 1}
            status = await browser.post(
                f"{REGISTRATION}/status", json={"invitation": replaced[first][0]},
            )
            assert status.json() == {"operator_id": str(first), "state": "activated"}
            ready = await options(browser, first)
            signed_in = await browser.post(
                f"{API}/auth/verify", json=sign(ready, first, credential, key)
            )
            assert signed_in.status_code == 200
            async with sessions() as db:
                grants = (await db.scalars(select(SupportOperatorGrant))).all()
                assert {(row.operator_id, row.capability) for row in grants} == {
                    (first, "operator.manage"),
                    (second, "operator.manage"),
                }
                events = list(await db.scalars(select(SupportBootstrapEvent.action)))
                assert events.count("activated") == 2
                assert events.count("passkey_added") == 4
                with pytest.raises(ValueError, match="has completed"):
                    await issue_first_custodian_invitations(
                        db, approval_digest="a" * 64, reissue=True
                    )
    finally:
        await isolated.dispose()
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
