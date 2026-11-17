import asyncio
from uuid import UUID, uuid4

import cbor2
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from app.api.v1.support import CSRF_COOKIE
from app.database import AsyncSessionLocal
from app.models.support_cases import SupportOperatorGrant
from app.models.support_custody import SupportCustodyEvent
from app.models.support_identity import SupportCredential, SupportOperator, SupportSession
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_identity import API, client, options, seed_operator, sign
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool

CUSTODY = f"{API}/custody/suspensions"


async def seed_custody_operator(
    *,
    custodian: bool = True,
) -> tuple[UUID, bytes, ec.EllipticCurvePrivateKey]:
    operator, credential, key = await seed_operator()
    if custodian:
        async with AsyncSessionLocal() as session:
            key2 = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
            session.add(
                SupportCredential(
                    id=uuid4(),
                    operator_id=operator,
                    credential_hash=uuid4().hex * 2,
                    public_key=cbor2.dumps(
                        {1: 2, 3: -7, -1: 1, -2: key2.x.to_bytes(32), -3: key2.y.to_bytes(32)}
                    ),
                    sign_count=0,
                )
            )
            session.add(SupportOperatorGrant(operator_id=operator, capability="operator.manage"))
            await session.commit()
    return operator, credential, key


async def login(
    browser: httpx.AsyncClient, *, custodian: bool = True
) -> tuple[UUID, bytes, ec.EllipticCurvePrivateKey]:
    operator, credential, key = await seed_custody_operator(custodian=custodian)
    proof = sign(await options(browser, operator), operator, credential, key)
    assert (await browser.post(f"{API}/auth/verify", json=proof)).status_code == 200
    csrf = browser.cookies.get(CSRF_COOKIE)
    assert csrf
    browser.headers["x-support-csrf"] = csrf
    return operator, credential, key


async def propose(browser: httpx.AsyncClient, target: UUID) -> str:
    response = await browser.post(CUSTODY, json={"target_id": str(target)})
    assert response.status_code == 201, response.text
    return response.json()["suspension_id"]


async def action_options(browser: httpx.AsyncClient, route: str, target: UUID) -> dict:
    response = await browser.post(f"{route}/options")
    assert response.status_code == 200, response.text
    assert response.json()["target_id"] == str(target)
    return response.json()


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_review_bound_proofs_and_concurrent_custodian_suspensions() -> None:
    await skip_if_database_unavailable()
    async with client() as first, client() as second, client() as third, client() as ordinary:
        a = await login(first)
        b = await login(second)
        c = await login(third)
        d = await login(ordinary, custodian=False)
        assert (await ordinary.post(CUSTODY, json={"target_id": str(a[0])})).status_code == 403
        assert (await first.post(CUSTODY, json={"target_id": str(a[0])})).status_code == 403
        assert (
            await first.post(
                CUSTODY, json={"target_id": str(c[0])}, headers={"x-support-csrf": "wrong"}
            )
        ).status_code == 403

        suspend_c = f"{CUSTODY}/{await propose(first, c[0])}"
        suspend_b = f"{CUSTODY}/{await propose(first, b[0])}"
        assert (await first.post(f"{suspend_c}/review/options")).status_code == 403
        assert (await third.post(f"{suspend_c}/review/options")).status_code == 403
        assert (await first.post(f"{suspend_c}/execute/options")).status_code == 409

        info = await action_options(second, f"{suspend_c}/review", c[0])
        invalid = sign(info, *b, flags=1, counter=2)
        assert (await second.post(f"{suspend_c}/review", json=invalid)).status_code == 403
        valid = sign(info, *b, counter=2)
        assert (await second.post(f"{suspend_c}/review", json=valid)).status_code == 409
        assert (await second.post(f"{API}/auth/verify", json=valid)).status_code == 401
        info = await action_options(second, f"{suspend_c}/review", c[0])
        assert (
            await second.post(f"{suspend_c}/review", json=sign(info, *b, counter=2))
        ).status_code == 204

        info = await action_options(third, f"{suspend_b}/review", b[0])
        assert (
            await third.post(f"{suspend_b}/review", json=sign(info, *c, counter=2))
        ).status_code == 204

        proof_c = sign(await action_options(first, f"{suspend_c}/execute", c[0]), *a, counter=2)
        proof_b = sign(await action_options(first, f"{suspend_b}/execute", b[0]), *a, counter=3)
        assert (await first.post(f"{suspend_b}/execute", json=proof_c)).status_code == 409

        async with client() as other_session:
            renewal = sign(await options(other_session, a[0]), *a, counter=2)
            assert (await other_session.post(f"{API}/auth/verify", json=renewal)).status_code == 200
            csrf = other_session.cookies.get(CSRF_COOKIE)
            assert csrf
            other_session.headers["x-support-csrf"] = csrf
            assert (
                await other_session.post(f"{suspend_c}/execute", json=proof_c)
            ).status_code == 409
        proof_c = sign(await action_options(first, f"{suspend_c}/execute", c[0]), *a, counter=3)
        result_c, result_b = await asyncio.gather(
            first.post(f"{suspend_c}/execute", json=proof_c),
            first.post(f"{suspend_b}/execute", json=proof_b),
        )
        assert sorted((result_c.status_code, result_b.status_code)) == [204, 409]
        name, browser, target, proof = (
            (suspend_c, third, c[0], proof_c)
            if result_c.status_code == 204
            else (suspend_b, second, b[0], proof_b)
        )
        assert (await first.post(f"{name}/execute", json=proof)).status_code == 409
        assert (await browser.get(f"{API}/me")).status_code == 401
        assert (await ordinary.get(f"{API}/me")).json()["operator_id"] == str(d[0])

        async with AsyncSessionLocal() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(SupportOperator)
                    .where(
                        SupportOperator.id.in_((a[0], b[0], c[0])),
                        SupportOperator.status == "active",
                    )
                )
                == 2
            )
            for model in (SupportCredential, SupportSession):
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.operator_id == target, model.revoked_at.is_(None))
                    )
                    == 0
                )
            custody_action_id = UUID(name.rsplit("/", 1)[1])
            result = await session.scalars(
                select(SupportCustodyEvent.action).where(
                    SupportCustodyEvent.custody_action_id == custody_action_id
                )
            )
            assert {"proposed", "reviewed", "executed"} <= set(result)
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    update(SupportCustodyEvent)
                    .where(SupportCustodyEvent.custody_action_id == custody_action_id)
                    .values(action="proposed")
                )


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_reviewed_grant_changes_revoke_sessions_without_replacing_passkeys() -> None:
    await skip_if_database_unavailable()
    grants = f"{API}/custody/grant-changes"
    async with client() as maker, client() as reviewer, client() as target:
        a = await login(maker)
        b = await login(reviewer)
        c = await login(target, custodian=False)
        payload = {"target_id": str(c[0]), "capability": "cases.manage", "enable": True}
        assert (
            await maker.post(grants, json={**payload, "capability": "operator.manage"})
        ).status_code == 422
        assert (
            await maker.post(grants, json={**payload, "target_id": str(a[0])})
        ).status_code == 403
        for index, enable in enumerate((True, False), start=2):
            draft = await maker.post(grants, json={**payload, "enable": enable})
            assert draft.status_code == 201, draft.text
            change_id = draft.json()["grant_change_id"]
            path = f"{grants}/{change_id}"
            assert (await maker.post(f"{path}/review/options")).status_code == 403
            assert (await target.post(f"{path}/review/options")).status_code == 403
            assert (await reviewer.post(f"{CUSTODY}/{change_id}/review/options")).status_code == 409
            review = await reviewer.post(f"{path}/review/options")
            assert review.status_code == 200, review.text
            info = review.json()
            assert (info["target_id"], info["capability"], info["enable"]) == (
                str(c[0]),
                "cases.manage",
                enable,
            )
            assert (
                await reviewer.post(f"{path}/review", json=sign(info, *b, counter=index))
            ).status_code == 204
            assert (await reviewer.post(f"{path}/execute/options")).status_code == 403
            execution = await maker.post(f"{path}/execute/options")
            assert execution.status_code == 200, execution.text
            proof = sign(execution.json(), *a, counter=index)
            assert (await maker.post(f"{path}/execute", json=proof)).status_code == 204
            assert (await maker.post(f"{path}/execute", json=proof)).status_code == 409
            assert (await target.get(f"{API}/me")).status_code == 401
            fresh = sign(await options(target, c[0]), *c, counter=index)
            assert (await target.post(f"{API}/auth/verify", json=fresh)).status_code == 200
            profile = (await target.get(f"{API}/me")).json()
            assert profile["capabilities"] == (["cases.manage"] if enable else [])
            assert (await target.get(f"{API}/cases")).status_code == (200 if enable else 403)
