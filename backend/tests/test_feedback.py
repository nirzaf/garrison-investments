import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.api.dependencies import CurrentUser
from app.database import AsyncSessionLocal
from app.main import create_app
from app.models.activity_log import ActivityLog
from app.models.user import User
from app.utils.security import create_access_token, utc_now
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_custody import login
from tests.test_support_identity import API, client
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("isolated_engine_pool", "enabled")]
SUBMISSION = "/api/v1/feedback"


async def seed_reporter(role: str = "site_supervisor") -> tuple[UUID, dict[str, str]]:
    user_id = uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                email=f"feedback-{user_id}@example.com",
                full_name="Feedback Reporter",
                role=role,
            )
        )
        await session.commit()
    token, _ = create_access_token(user_id, role)
    return user_id, {"Authorization": f"Bearer {token}"}


def report(**kwargs: object) -> dict[str, object]:
    return {
        "submission_id": str(uuid4()),
        "category": "bug",
        "title": "Project list problem",
        "description": "The filtered list did not load.",
        **kwargs,
    }


async def test_feedback_request_projection_and_technical_triage() -> None:
    await skip_if_database_unavailable()
    reporter, headers = await seed_reporter()
    unrelated, _ = await seed_reporter()
    matched, foreign, expired, successful, excluded = [uuid4().hex for _ in range(5)]
    async with AsyncSessionLocal() as db:
        for ref, actor, age, status, path in (
            (matched, reporter, 1, 409, f"/api/v1/projects/{uuid4()}"),
            (foreign, unrelated, 1, 500, "/api/v1/projects"),
            (expired, reporter, 45, 500, "/api/v1/projects"),
            (successful, reporter, 1, 200, "/api/v1/projects"),
            (excluded, reporter, 1, 403, "/api/v1/auth/refresh"),
        ):
            db.add(
                ActivityLog(
                    user_id=actor,
                    action="http.request",
                    entity_type="request",
                    request_id=ref,
                    created_at=utc_now() - timedelta(minutes=age),
                    endpoint=path,
                    http_method="PATCH",
                    status_code=status,
                    comments="private-payload-fixture",
                    ip_address="192.0.2.44",
                    context_payload={"private_note": "private-payload-fixture"},
                )
            )
        await db.commit()
    async with (
        client(base_url="https://portal.garrisons.lk") as portal,
        client() as owner,
        client() as operator,
    ):
        payload = report(
            description="The portal failed. token=synthetic-token https://example.com/?X-Secret=fixture",
            request_ids=[matched, foreign, expired, successful, excluded],
        )
        assert (await portal.post(SUBMISSION, json=payload)).status_code == 401
        response = await portal.post(SUBMISSION, json=payload, headers=headers)
        assert response.status_code == 201, response.text
        assert response.json()["attached_diagnostics"] == 1
        assert set(response.json()) == {"id", "created_at", "attached_diagnostics"}
        feedback_id = response.json()["id"]
        replay = await portal.post(SUBMISSION, json=payload, headers=headers)
        assert replay.json() == response.json()
        invalid = await portal.post(
            SUBMISSION, json={**payload, "category": "other"}, headers=headers
        )
        assert invalid.status_code == 409

        inbox_path = f"{API}/feedback"
        assert (await portal.get(inbox_path, headers=headers)).status_code == 404
        assert (await owner.get(inbox_path, headers=headers)).status_code == 401
        await login(operator, custodian=False)
        assert (await operator.get(inbox_path)).status_code == 403
        owner_id, _, _ = await login(owner)
        inbox = await owner.get(inbox_path, params={"status": "new"})
        assert inbox.status_code == 200, inbox.text
        item = next(row for row in inbox.json()["items"] if row["id"] == feedback_id)
        (summary,) = item["diagnostics"]
        assert set(summary) == {"request_id", "occurred_at", "area", "method", "status_code"}
        assert (summary["request_id"], summary["area"], summary["status_code"]) == (
            matched,
            "projects",
            409,
        )
        assert item["reporter_id"] == str(reporter)
        assert "synthetic-token" not in inbox.text
        assert "X-Secret" not in inbox.text
        assert "private-payload-fixture" not in inbox.text
        assert "192.0.2.44" not in inbox.text
        assert not {foreign, expired, successful, excluded}.intersection(
            row["request_id"] for row in item["diagnostics"]
        )

        status_url = f"{inbox_path}/{feedback_id}/status"
        desired = {"status": "investigating", "expected_revision": 1}
        assert (await operator.patch(status_url, json=desired)).status_code == 403
        assert (
            await owner.patch(status_url, json=desired, headers={"x-support-csrf": "wrong"})
        ).status_code == 403
        changed = await owner.patch(status_url, json=desired)
        assert changed.status_code == 200, changed.text
        assert changed.json()["revision"] == 2
        assert (await owner.patch(status_url, json=desired)).status_code == 409
        persisted = await owner.get(inbox_path, params={"status": "investigating", "limit": 1})
        assert persisted.json()["items"][0]["id"] == feedback_id
        assert persisted.json()["items"][0]["status"] == "investigating"

    async with AsyncSessionLocal() as db:
        events = list(
            await db.scalars(select(ActivityLog).where(ActivityLog.entity_id == UUID(feedback_id)))
        )
    assert {event.action for event in events} == {"feedback.submitted", "feedback.status_changed"}
    assert len(events) == 2
    assert any(
        event.context_payload and event.context_payload.get("operator_id") == str(owner_id)
        for event in events
    )


async def test_rate_limit_serializes_distinct_concurrent_feedback_and_preserves_retry() -> None:
    await skip_if_database_unavailable()
    _, headers = await seed_reporter("quantity_surveyor")
    async with client(base_url="https://portal.garrisons.lk") as portal:
        first = report()
        for payload in [first, *(report() for _ in range(8))]:
            assert (await portal.post(SUBMISSION, json=payload, headers=headers)).status_code == 201

        outcomes = await asyncio.gather(
            *(portal.post(SUBMISSION, json=report(), headers=headers) for _ in range(2))
        )
        assert sorted(response.status_code for response in outcomes) == [201, 429]
        assert (await portal.post(SUBMISSION, json=first, headers=headers)).status_code == 201
        assert (
            await portal.post(SUBMISSION, json=report(request_ids=["invalid"]), headers=headers)
        ).status_code == 422


async def test_unhandled_feedback_diagnostic_has_verified_actor() -> None:
    await skip_if_database_unavailable()
    _, headers = await seed_reporter()
    app = create_app()

    @app.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/feedback-test-error")
    async def fail_after_auth(_: CurrentUser) -> None:
        raise RuntimeError("private exception text")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as portal:
        response = await portal.get(
            "/api/v1/projects/00000000-0000-0000-0000-000000000000/feedback-test-error",
            headers=headers,
        )
        assert response.status_code == 500
        submission = await portal.post(
            SUBMISSION,
            json=report(request_ids=[response.headers["X-Request-ID"]]),
            headers=headers,
        )
        assert submission.status_code == 201, submission.text
        assert submission.json()["attached_diagnostics"] == 1
        assert "private exception text" not in submission.text
