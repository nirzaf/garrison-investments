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


async def test_dashboard_summary_counts_pending_reports_and_notifications() -> None:
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
        await client.post(
            f"/api/v1/reports/{report['id']}/submit",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        response = await client.get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert response.status_code == 200
        summary = response.json()
        assert summary["pending_reports"] >= 1
        assert summary["unread_notifications"] >= 1
