from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal, engine
from app.models.notification import Notification
from app.repositories.user_repository import UserRepository
from app.services.notification_service import NotificationService
from app.tasks.email import _send_email_notification, send_email_notification
from app.tasks.maintenance import _cleanup_old_notifications
from app.utils.security import utc_now
from tests.test_daily_reports import (
    create_test_client,
    create_user,
    report_payload,
    setup_project_team,
    skip_if_database_unavailable,
)


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def frontend_base_url(monkeypatch):
    monkeypatch.setattr(
        "app.utils.links.get_settings",
        lambda: SimpleNamespace(normalized_frontend_base_url="https://portal.example.com"),
    )


@pytest.mark.asyncio
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
        assert (
            first_notification["body"]
            == f"{submitted['report_number']} is ready for approval.\n\n"
            "Open approval: https://portal.example.com/approvals?tab=reports&reportId="
            f"{submitted['id']}"
        )

        read_response = await client.patch(
            f"/api/v1/notifications/{first_notification['id']}/read",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        mute_response = await client.patch(
            f"/api/v1/notifications/{first_notification['id']}/mute",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        unmute_response = await client.patch(
            f"/api/v1/notifications/{first_notification['id']}/unmute",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        approve_response = await client.post(
            f"/api/v1/reports/{submitted['id']}/approve",
            json={"comments": "Approved", "target_covered": True},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        engineer_count = await client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        engineer_notifications = await client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert read_response.status_code == 200
        assert read_response.json()["is_read"] is True
        assert mute_response.status_code == 200
        assert mute_response.json()["muted"] is True
        assert unmute_response.status_code == 200
        assert unmute_response.json()["muted"] is False
        assert approve_response.status_code == 200
        assert engineer_count.json()["unread_count"] >= 1
        assert any(
            item["title"] == "Daily report approved"
            and item["body"]
            == f"{submitted['report_number']} has been approved.\n\n"
            "Open report: https://portal.example.com/reports/daily?reportId="
            f"{submitted['id']}"
            for item in engineer_notifications.json()["items"]
        )


@pytest.mark.asyncio
async def test_notification_email_updates_status_when_delivery_succeeds(monkeypatch) -> None:
    await skip_if_database_unavailable()
    user_email, _ = await create_user("project_manager")

    monkeypatch.setattr("app.tasks.email.send_email_notification.delay", lambda _id: None)

    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_by_email(user_email)
        assert user is not None
        notification = await NotificationService(session).create(
            user_id=user.id,
            title="Approval required",
            body="Please review the latest submission.",
            notification_type="approval",
        )
        await session.commit()

    sent_payload: dict[str, object] = {}

    def fake_send(self, *, recipients: list[str], subject: str, body: str) -> int:
        sent_payload["recipients"] = recipients
        sent_payload["subject"] = subject
        sent_payload["body"] = body
        return len(recipients)

    monkeypatch.setattr("app.tasks.email.EmailService.send", fake_send)

    result = await _send_email_notification(str(notification.id))

    assert result == "notification email sent to 1 recipient"
    assert sent_payload["recipients"] == [user_email]
    assert sent_payload["subject"] == "Approval required"

    async with AsyncSessionLocal() as session:
        refreshed = await session.scalar(
            select(Notification).where(Notification.id == notification.id)
        )
        assert refreshed is not None
        assert refreshed.email_status == "sent"


def test_send_email_notification_requires_notification_id() -> None:
    assert send_email_notification() == "notification id required"


@pytest.mark.asyncio
async def test_cleanup_old_notifications_soft_deletes_stale_items() -> None:
    await skip_if_database_unavailable()
    user_email, _ = await create_user("project_manager")

    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_by_email(user_email)
        assert user is not None
        stale = Notification(
            user_id=user.id,
            title="Old notification",
            body="Stale body",
            notification_type="approval",
            created_at=utc_now() - timedelta(days=91),
        )
        fresh = Notification(
            user_id=user.id,
            title="Fresh notification",
            body="Fresh body",
            notification_type="approval",
            created_at=utc_now(),
        )
        session.add_all([stale, fresh])
        await session.commit()

    result = await _cleanup_old_notifications()

    assert result == "1 notifications cleaned up"

    async with AsyncSessionLocal() as session:
        stale_db = await session.scalar(
            select(Notification).where(Notification.title == "Old notification")
        )
        fresh_db = await session.scalar(
            select(Notification).where(Notification.title == "Fresh notification")
        )
        assert stale_db is not None
        assert stale_db.deleted_at is not None
        assert fresh_db is not None
        assert fresh_db.deleted_at is None
