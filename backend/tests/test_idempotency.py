"""Idempotency-key regression tests for the offline sync replay path (C1).

The offline photo queue retries ``POST /reports`` after a dropped connection. Without a
key the retry creates a second draft report; with a key it must return the first one.
"""

from __future__ import annotations

from io import BytesIO
from uuid import UUID, uuid4

import pytest
from PIL import Image
from sqlalchemy import func, select, update

from app.database import AsyncSessionLocal, engine
from app.models.daily_report import DailyReport
from app.models.idempotency_record import IdempotencyRecord
from app.models.photo import Photo
from app.models.project_member import ProjectMember
from app.models.user import User
from app.schemas.daily_reports import DailyReportCreateRequest
from app.services.report_service import ReportService
from app.utils.security import utc_now
from tests.concurrency_helpers import race_sessions, require_database
from tests.test_daily_reports import create_test_client, report_payload, setup_project_team
from tests.test_daily_reports import create_user as create_report_user
from tests.test_daily_reports import login_for_token as report_login

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _count_reports(project_id: str) -> int:
    async with AsyncSessionLocal() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(DailyReport)
                .where(
                    DailyReport.project_id == UUID(project_id),
                    DailyReport.deleted_at.is_(None),
                )
            )
            or 0
        )


async def test_same_key_twice_creates_one_report() -> None:
    await require_database()
    key = f"offline-{uuid4().hex}"
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        headers = {
            "Authorization": f"Bearer {setup['engineer_token']}",
            "Idempotency-Key": key,
        }
        first = await client.post(
            "/api/v1/reports", json=report_payload(setup["project_id"]), headers=headers
        )
        second = await client.post(
            "/api/v1/reports", json=report_payload(setup["project_id"]), headers=headers
        )

        assert first.status_code == 201
        assert second.status_code == 201, "a replay must still look like success to the client"
        assert first.json()["id"] == second.json()["id"]

    assert await _count_reports(setup["project_id"]) == 1


async def test_concurrent_same_key_creates_one_report() -> None:
    await require_database()
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        engineer = (
            await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
    engineer_id = UUID(engineer["id"])
    payload = DailyReportCreateRequest(**report_payload(setup["project_id"]))
    key = f"offline-{uuid4().hex}"

    async def create(session):
        actor = await session.get(User, engineer_id)
        assert actor is not None
        report = await ReportService(session).create_report(
            payload, actor, idempotency_key=key
        )
        return report.id

    results = await race_sessions(create, create, create)

    assert all(isinstance(result, UUID) for result in results), f"race failed: {results}"
    assert len({str(result) for result in results}) == 1, "concurrent replays created twins"
    assert await _count_reports(setup["project_id"]) == 1

    async with AsyncSessionLocal() as session:
        records = (
            await session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.key == key)
            )
        ).all()
        assert len(records) == 1
        assert records[0].resource_id == results[0]
        assert records[0].resource_type == "daily_report"


async def test_distinct_keys_create_distinct_reports() -> None:
    await require_database()
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        ids = []
        for _ in range(2):
            response = await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"]),
                headers={
                    "Authorization": f"Bearer {setup['engineer_token']}",
                    "Idempotency-Key": f"offline-{uuid4().hex}",
                },
            )
            assert response.status_code == 201
            ids.append(response.json()["id"])
        assert ids[0] != ids[1]

    assert await _count_reports(setup["project_id"]) == 2


async def test_key_is_scoped_to_the_user() -> None:
    await require_database()
    key = f"offline-{uuid4().hex}"
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        # The operation manager is not an engineer, so use a second engineer on the project.
        email, password = await create_report_user("civil_engineer")
        token = await report_login(client, email, password)
        second = (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        ).json()
        await client.post(
            f"/api/v1/projects/{setup['project_id']}/members",
            json={"user_id": second["id"], "role_in_project": "civil_engineer"},
            headers={"Authorization": f"Bearer {setup['op_token']}"},
        )
        first = await client.post(
            "/api/v1/reports",
            json=report_payload(setup["project_id"]),
            headers={
                "Authorization": f"Bearer {setup['engineer_token']}",
                "Idempotency-Key": key,
            },
        )
        other = await client.post(
            "/api/v1/reports",
            json=report_payload(setup["project_id"]),
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        )
        assert first.status_code == 201
        assert other.status_code == 201
        assert first.json()["id"] != other.json()["id"]

    assert await _count_reports(setup["project_id"]) == 2


async def test_oversized_key_is_rejected() -> None:
    await require_database()
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        response = await client.post(
            "/api/v1/reports",
            json=report_payload(setup["project_id"]),
            headers={
                "Authorization": f"Bearer {setup['engineer_token']}",
                "Idempotency-Key": "k" * 201,
            },
        )
        assert response.status_code == 422
        assert response.json()["error_code"] == "IDEMPOTENCY_KEY_TOO_LONG"

    assert await _count_reports(setup["project_id"]) == 0


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color=(120, 140, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_photo_upload_replay_returns_the_same_photo() -> None:
    await require_database()
    key = f"photo-{uuid4().hex}"
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        headers = {
            "Authorization": f"Bearer {setup['engineer_token']}",
            "Idempotency-Key": key,
        }
        png = _png_bytes()
        first = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report["id"], "kind": "photo"},
            files={"files": ("site.png", png, "image/png")},
            headers=headers,
        )
        second = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report["id"], "kind": "photo"},
            files={"files": ("site.png", png, "image/png")},
            headers=headers,
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()[0]["id"] == second.json()[0]["id"]

    async with AsyncSessionLocal() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(Photo)
            .where(Photo.entity_id == UUID(report["id"]), Photo.deleted_at.is_(None))
        )
        assert total == 1


async def test_photo_replay_checks_current_project_membership() -> None:
    await require_database()
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        headers = {
            "Authorization": f"Bearer {setup['engineer_token']}",
            "Idempotency-Key": f"photo-{uuid4().hex}",
        }
        actor = await client.get("/api/v1/auth/me", headers=headers)
        project_id = UUID(setup["project_id"])
        user_id = UUID(actor.json()["id"])
        data = {"entity_type": "project", "entity_id": str(project_id), "kind": "photo"}
        files = {"files": ("site.png", _png_bytes(), "image/png")}

        first = await client.post("/api/v1/photos/upload", data=data, files=files, headers=headers)
        assert first.status_code == 201, first.text
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(ProjectMember)
                .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
                .values(deleted_at=utc_now())
            )
            await session.commit()

        replay = await client.post("/api/v1/photos/upload", data=data, files=files, headers=headers)
        assert replay.status_code == 403, replay.text
