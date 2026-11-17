import asyncio

import pytest
from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models.support_cases import SupportOperatorGrant
from app.models.support_health import SupportHealthEvent
from app.models.support_identity import SupportSession
from app.utils.security import utc_now
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_custody import login
from tests.test_support_identity import API, client
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_health_is_bounded_redacted_and_rechecks_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    in_probe = asyncio.Event()
    finish = asyncio.Event()
    controlled = False

    async def database() -> bool:
        if controlled:
            in_probe.set()
            await finish.wait()
        return True

    async def cache(_: object) -> bool:
        raise RuntimeError("synthetic-secret-shaped-string")

    monkeypatch.setattr("app.services.support_health.check_database", database)
    monkeypatch.setattr("app.services.support_health._ping_redis", cache)
    monkeypatch.setattr("app.services.support_health._check_bucket", lambda _: False)
    async with client() as actor, client() as ordinary:
        operator, _, _ = await login(actor, custodian=False)
        await login(ordinary, custodian=False)
        async with AsyncSessionLocal() as session:
            session.add(SupportOperatorGrant(operator_id=operator, capability="health.read"))
            await session.commit()

        assert (await ordinary.get(f"{API}/health")).status_code == 403
        response = await actor.get(f"{API}/health")
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {
            "database": "operational",
            "redis": "unavailable",
            "object_storage": "unavailable",
            "observed_at": response.json()["observed_at"],
        }
        controlled = True
        pending = asyncio.create_task(actor.get(f"{API}/health"))
        await asyncio.wait_for(in_probe.wait(), timeout=1.5)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SupportSession)
                .where(SupportSession.operator_id == operator)
                .values(revoked_at=utc_now())
            )
            await session.commit()
        finish.set()
        assert (await pending).status_code == 401
        async with AsyncSessionLocal() as session:
            audit = await session.scalars(
                select(SupportHealthEvent.action)
                .where(SupportHealthEvent.operator_id == operator)
                .order_by(SupportHealthEvent.occurred_at)
            )
            assert list(audit) == ["requested", "returned", "requested"]
