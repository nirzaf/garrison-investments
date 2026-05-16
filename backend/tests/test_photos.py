from io import BytesIO

import pytest
from PIL import Image

from app.database import engine
from tests.test_daily_reports import (
    create_test_client,
    report_payload,
    setup_project_team,
    skip_if_database_unavailable,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


def jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (20, 20), color=(80, 120, 160)).save(buffer, format="JPEG")
    return buffer.getvalue()


async def test_photo_upload_download_url_and_delete_lock() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        upload_response = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report["id"], "kind": "photo"},
            files={"files": ("site.jpg", jpeg_bytes(), "image/jpeg")},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert upload_response.status_code == 201
        photo = upload_response.json()[0]
        assert photo["thumbnail_path"]

        url_response = await client.get(
            f"/api/v1/photos/{photo['id']}/thumbnail",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert url_response.status_code == 200
        assert "url" in url_response.json()

        await client.post(
            f"/api/v1/reports/{report['id']}/submit",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        delete_response = await client.delete(
            f"/api/v1/photos/{photo['id']}",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert delete_response.status_code == 409


async def test_blocked_file_type_is_rejected() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        response = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report["id"], "kind": "attachment"},
            files={"files": ("run.sh", b"#!/bin/sh\necho bad", "text/x-shellscript")},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert response.status_code == 422
