import pytest

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


async def test_report_submission_and_decision_create_notifications() -> None:
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
        submitted = (
            await client.post(
                f"/api/v1/reports/{report['id']}/submit",
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()

        manager_count = await client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        manager_notifications = await client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert manager_count.status_code == 200
        assert manager_count.json()["unread_count"] >= 1
        first_notification = manager_notifications.json()["items"][0]

        read_response = await client.patch(
            f"/api/v1/notifications/{first_notification['id']}/read",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        approve_response = await client.post(
            f"/api/v1/reports/{submitted['id']}/approve",
            json={"comments": "Approved"},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        engineer_count = await client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert read_response.status_code == 200
        assert read_response.json()["is_read"] is True
        assert approve_response.status_code == 200
        assert engineer_count.json()["unread_count"] >= 1
