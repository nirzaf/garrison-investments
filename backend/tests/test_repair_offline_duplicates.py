from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal, engine
from app.models.activity_log import ActivityLog
from app.models.daily_report import DailyReport
from app.models.idempotency_record import IdempotencyRecord
from app.models.photo import Photo
from app.schemas.daily_reports import DailyReportResponse
from scripts.repair_offline_duplicates import consolidate_pair
from tests.concurrency_helpers import require_database
from tests.test_daily_reports import create_test_client, report_payload, setup_project_team
from tests.test_idempotency import _png_bytes


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.parametrize(
    "reason",
    [None, "Draft contents differ", "would exceed 5 active photos"],
    ids=["identical", "different", "quota"],
)
async def test_duplicate_repair_compares_line_contents_before_moving_references(
    reason: str | None,
) -> None:
    await require_database()
    key = f"offline-{uuid4().hex}"
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        headers = {"Authorization": f"Bearer {setup['engineer_token']}"}
        payload = report_payload(setup["project_id"], setup["supervisor_update_id"])
        first = await client.post("/api/v1/reports", json=payload, headers=headers)
        assert first.status_code == 201, first.text
        if reason == "Draft contents differ":
            payload["material_consumption"][0]["quantity"] = "13"
        second = await client.post(
            "/api/v1/reports", json=payload, headers={**headers, "Idempotency-Key": key}
        )
        assert second.status_code == 201, second.text
        retained, duplicate = first.json(), second.json()
        keep_id, duplicate_id = UUID(retained["id"]), UUID(duplicate["id"])
        for section in ("manpower_entries", "equipment_entries", "material_consumption"):
            assert retained[section][0]["id"] != duplicate[section][0]["id"]
        uploaded = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": str(duplicate_id), "kind": "photo"},
            files={"files": ("site.png", _png_bytes(), "image/png")},
            headers=headers,
        )
        assert uploaded.status_code == 201, uploaded.text
        photo_id = UUID(uploaded.json()[0]["id"])

        if reason == "would exceed 5 active photos":
            full = await client.post(
                "/api/v1/photos/upload",
                data={"entity_type": "daily_report", "entity_id": str(keep_id), "kind": "photo"},
                files=[
                    ("files", (f"site-{index}.png", _png_bytes(), "image/png"))
                    for index in range(5)
                ],
                headers=headers,
            )
            assert full.status_code == 201, full.text

        async with AsyncSessionLocal() as session:
            if reason:
                with pytest.raises(ValueError, match=reason):
                    await consolidate_pair(session, keep_id, duplicate_id)
            else:
                await consolidate_pair(session, keep_id, duplicate_id)

        async with AsyncSessionLocal() as session:
            report = await session.get(DailyReport, duplicate_id)
            photo = await session.get(Photo, photo_id)
            replay = await session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.key == key)
            )
            event = await session.scalar(
                select(ActivityLog).where(
                    ActivityLog.entity_id == keep_id,
                    ActivityLog.action == "daily_reports.offline_duplicate_consolidated",
                )
            )
            assert report is not None and (report.deleted_at is None) == (reason is not None)
            expected_id = duplicate_id if reason else keep_id
            assert photo is not None and photo.entity_id == expected_id
            assert photo.report_revision == (2 if reason else None)
            assert replay is not None and replay.resource_id == expected_id
            assert (event is None) == (reason is not None)

        if reason is None:
            replayed = await client.post(
                "/api/v1/reports", json=payload, headers={**headers, "Idempotency-Key": key}
            )
            assert replayed.status_code == 201, replayed.text
            assert DailyReportResponse.model_validate(replayed.json()) == (
                DailyReportResponse.model_validate(
                    {**retained, "revision": retained["revision"] + 1}
                )
            )
