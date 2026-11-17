import json
from hashlib import sha256
from uuid import UUID, uuid4

import cbor2
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.support_custody import SupportCustodyEvent
from app.models.support_identity import SupportOperator
from app.services.support_identity import SUPPORT_HOST, SUPPORT_ORIGIN
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_custody import CUSTODY, action_options, login, propose
from tests.test_support_identity import API, client, encoded, options, sign
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool

REGISTRATION = f"{API}/registration"
PROPOSALS = f"{API}/custody/registrations"


def attestation(
    challenge: str,
    credential: bytes,
    key: ec.EllipticCurvePrivateKey,
    *,
    flags: int = 0x45,
) -> dict:
    points = key.public_key().public_numbers()
    public = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: points.x.to_bytes(32), -3: points.y.to_bytes(32)})
    auth = (
        sha256(SUPPORT_HOST.encode()).digest()
        + bytes([flags])
        + bytes(20)
        + len(credential).to_bytes(2)
        + credential
        + public
    )
    attested = cbor2.dumps({"fmt": "none", "authData": auth, "attStmt": {}})
    client_data = json.dumps(
        {"type": "webauthn.create", "origin": SUPPORT_ORIGIN, "challenge": challenge}
    ).encode()
    return {
        "id": encoded(credential),
        "rawId": encoded(credential),
        "type": "public-key",
        "response": {
            "attestationObject": encoded(attested),
            "clientDataJSON": encoded(client_data),
        },
    }


async def registration_options(browser: httpx.AsyncClient, invitation: str) -> str:
    response = await browser.post(f"{REGISTRATION}/options", json={"invitation": invitation})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    creation = response.json()["public_key"]
    assert creation["authenticatorSelection"]["userVerification"] == "required"
    assert creation["authenticatorSelection"]["residentKey"] == "required"
    return creation["challenge"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_two_passkeys_after_review_and_recovery_invalidates_old_credentials() -> None:
    await skip_if_database_unavailable()
    target = uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            SupportOperator(id=target, display_label="Synthetic", status="pending", grant_epoch=1)
        )
        await session.commit()

    async with client() as maker, client() as reviewer, client() as applicant:
        a = await login(maker)
        b = await login(reviewer)
        previous: tuple[bytes, ec.EllipticCurvePrivateKey] | None = None
        for index, kind in ((2, "enroll"), (4, "recover")):
            request = await maker.post(PROPOSALS, json={"target_id": str(target), "kind": kind})
            assert request.status_code == 201, request.text
            proposal_id = request.json()["proposal_id"]
            path = f"{PROPOSALS}/{kind}/{proposal_id}"
            alternate = "recover" if kind == "enroll" else "enroll"
            assert (
                await reviewer.post(f"{PROPOSALS}/{alternate}/{proposal_id}/review/options")
            ).status_code == 409
            assert (await maker.post(f"{path}/review/options")).status_code == 403
            assert (await maker.post(f"{path}/execute/options")).status_code == 409
            rf = await action_options(reviewer, f"{path}/review", target)
            reviewed = await reviewer.post(f"{path}/review", json=sign(rf, *b, counter=index))
            assert reviewed.json() == {"invitations": None}
            ef = await action_options(maker, f"{path}/execute", target)
            execution = sign(ef, *a, counter=index)
            result = await maker.post(f"{path}/execute", json=execution)
            assert result.status_code == 200, result.text
            first, second = result.json()["invitations"]
            assert (await maker.post(f"{path}/execute", json=execution)).status_code == 409
            status = await applicant.post(f"{REGISTRATION}/status", json={"invitation": first})
            assert status.json() == {"operator_id": str(target), "state": "pending"}
            assert "set-cookie" not in status.headers
            assert status.headers["cache-control"] == "no-store"

            key1, key2 = (ec.generate_private_key(ec.SECP256R1()) for _ in range(2))
            cred1, cred2 = uuid4().bytes, uuid4().bytes
            challenge = await registration_options(applicant, first)
            if kind == "enroll":
                backed_up = attestation(challenge, cred1, key1, flags=0x4D)
                assert (
                    await applicant.post(
                        f"{REGISTRATION}/verify",
                        json={
                            "invitation": first,
                            "credential": backed_up,
                        },
                    )
                ).status_code == 403
                challenge = await registration_options(applicant, first)
            registration = {"invitation": first, "credential": attestation(challenge, cred1, key1)}
            accepted = await applicant.post(f"{REGISTRATION}/verify", json=registration)
            assert accepted.json() == {"activated": False}
            status = await applicant.post(f"{REGISTRATION}/status", json={"invitation": first})
            assert status.json() == {"operator_id": str(target), "state": "registered"}
            assert (
                await applicant.post(f"{REGISTRATION}/verify", json=registration)
            ).status_code == 403
            premature = sign(await options(applicant, target), target, cred1, key1)
            assert (await applicant.post(f"{API}/auth/verify", json=premature)).status_code == 401

            challenge2 = await registration_options(applicant, second)
            duplicate_key = attestation(challenge2, cred2, key1)
            assert (
                await applicant.post(
                    f"{REGISTRATION}/verify",
                    json={
                        "invitation": second,
                        "credential": duplicate_key,
                    },
                )
            ).status_code == 403
            challenge2 = await registration_options(applicant, second)
            accepted = await applicant.post(
                f"{REGISTRATION}/verify",
                json={
                    "invitation": second,
                    "credential": attestation(challenge2, cred2, key2),
                },
            )
            assert accepted.json() == {"activated": True}
            status = await applicant.post(f"{REGISTRATION}/status", json={"invitation": first})
            assert status.json() == {"operator_id": str(target), "state": "activated"}
            if kind == "recover":
                assert previous is not None
                obsolete = sign(await options(applicant, target), target, *previous, counter=2)
                assert (
                    await applicant.post(f"{API}/auth/verify", json=obsolete)
                ).status_code == 401
            previous = cred1, key1
            fresh = sign(await options(applicant, target), target, cred1, key1)
            assert (await applicant.post(f"{API}/auth/verify", json=fresh)).status_code == 200

            async with AsyncSessionLocal() as session:
                history = await session.scalars(
                    select(SupportCustodyEvent.action).where(
                        SupportCustodyEvent.custody_action_id == UUID(proposal_id)
                    )
                )
                assert {"reviewed", "executed", "passkey_added", "operator_activated"} <= set(
                    history
                )
            if kind == "enroll":
                suspension = f"{CUSTODY}/{await propose(maker, target)}"
                rf = await action_options(reviewer, f"{suspension}/review", target)
                assert (
                    await reviewer.post(f"{suspension}/review", json=sign(rf, *b, counter=3))
                ).status_code == 204
                ef = await action_options(maker, f"{suspension}/execute", target)
                assert (
                    await maker.post(f"{suspension}/execute", json=sign(ef, *a, counter=3))
                ).status_code == 204
                assert (await applicant.get(f"{API}/me")).status_code == 401
                stale = await applicant.post(f"{REGISTRATION}/status", json={"invitation": first})
                assert stale.status_code == 403
