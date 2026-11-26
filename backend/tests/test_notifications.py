import asyncio
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal, engine
from app.models.notification import Notification
from app.models.task_outbox import TaskOutbox, notification_email_outbox_dedupe_key
from app.repositories.user_repository import UserRepository
from app.services.notification_service import NotificationService
from app.tasks.email import _send_email_notification, send_email_notification
from app.tasks.maintenance import _cleanup_old_notifications
from app.tasks.outbox import _dispatch_notification_email_outbox
from app.utils.security import utc_now
from tests.test_daily_reports import (
    create_test_client,
    create_user,
    login_for_token,
    report_payload_without_materials,
    setup_project_team,
    skip_if_database_unavailable,
)


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def prioritize_notification_outbox(notification_id: UUID) -> None:
    """Isolate this synthetic row from unrelated notifications left by other tests."""
    await prioritize_notification_outboxes({notification_id})


async def prioritize_notification_outboxes(notification_ids: set[UUID]) -> None:
    """Isolate a small set of synthetic rows while preserving their dispatch order."""
    dedupe_keys = {notification_email_outbox_dedupe_key(item_id) for item_id in notification_ids}
    async with AsyncSessionLocal() as session:
        older_entries = list(
            await session.scalars(
                select(TaskOutbox)
                .where(
                    TaskOutbox.task_name == "send_email_notification",
                    TaskOutbox.status == "pending",
                    TaskOutbox.dedupe_key.not_in(dedupe_keys),
                )
                .with_for_update()
            )
        )
        for older_entry in older_entries:
            older_entry.status = "completed"
            older_entry.lease_until = None
            if older_entry.args_json:
                try:
                    older_notification_id = UUID(str(older_entry.args_json[0]))
                except (ValueError, TypeError):
                    continue
                older_notification = await session.get(Notification, older_notification_id)
                if older_notification is not None and older_notification.email_status == "queued":
                    older_notification.email_status = "skipped"
        entries = list(
            await session.scalars(
                select(TaskOutbox)
                .where(TaskOutbox.dedupe_key.in_(dedupe_keys))
                .order_by(TaskOutbox.created_at, TaskOutbox.id)
                .with_for_update()
            )
        )
        assert len(entries) == len(dedupe_keys)
        for index, selected in enumerate(entries):
            selected.created_at = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=index)
        await session.commit()


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
                json=report_payload_without_materials(
                    setup["project_id"], setup["supervisor_update_id"]
                ),
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
            first_notification["body"] == f"{submitted['report_number']} is ready for approval.\n\n"
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
@pytest.mark.parametrize("accepted", [0, 1])
async def test_notification_email_status_reflects_provider_acceptance(
    monkeypatch, accepted
) -> None:
    await skip_if_database_unavailable()
    user_email, _ = await create_user("group_project_manager")

    monkeypatch.setattr("app.tasks.outbox.celery_app.send_task", lambda *_args, **_kwargs: None)

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

    await prioritize_notification_outbox(notification.id)
    assert await _dispatch_notification_email_outbox() >= 1
    async with AsyncSessionLocal() as session:
        dispatched = await session.scalar(
            select(TaskOutbox).where(
                TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(notification.id)
            )
        )
        assert dispatched is not None and dispatched.status == "dispatched"

    sent_payload: dict[str, object] = {}
    send_calls = 0

    def fake_send(self, *, recipients: list[str], subject: str, body: str) -> int:
        nonlocal send_calls
        send_calls += 1
        sent_payload["recipients"] = recipients
        sent_payload["subject"] = subject
        sent_payload["body"] = body
        return accepted

    monkeypatch.setattr("app.tasks.email.EmailService.send", fake_send)

    if accepted:
        result = await _send_email_notification(str(notification.id))
        assert result == "notification email sent to 1 recipient"
        assert await _send_email_notification(str(notification.id)) == (
            "notification email is not eligible for delivery"
        )
        assert send_calls == 1
    else:
        result = await _send_email_notification(str(notification.id))
        assert result == "notification email delivery outcome requires review"
    assert sent_payload["recipients"] == [user_email]
    assert sent_payload["subject"] == "Approval required"

    async with AsyncSessionLocal() as session:
        refreshed = await session.scalar(
            select(Notification).where(Notification.id == notification.id)
        )
        outbox = await session.scalar(
            select(TaskOutbox).where(
                TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(notification.id)
            )
        )
        assert refreshed is not None
        assert refreshed.email_status == ("sent" if accepted else "unknown")
        assert outbox is not None
        assert outbox.status == ("completed" if accepted else "manual_review")


@pytest.mark.asyncio
async def test_notification_email_outbox_is_transactional_and_retries_broker_outage(
    monkeypatch,
) -> None:
    await skip_if_database_unavailable()
    user_email, _ = await create_user("group_project_manager")
    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_by_email(user_email)
        assert user is not None
        user_id = user.id
        rolled_back = await NotificationService(session).create(
            user_id=user_id,
            title="Rollback notice",
            body="Must not dispatch.",
            notification_type="approval",
        )
        rolled_back_id = rolled_back.id
        await session.rollback()
        committed = await NotificationService(session).create(
            user_id=user_id,
            title="Durable notice",
            body="Dispatch is durable.",
            notification_type="approval",
        )
        no_email = await NotificationService(session).create(
            user_id=user_id,
            title="Portal only",
            body="No email requested.",
            notification_type="approval",
            send_email=False,
        )
        await session.commit()
        committed_id = committed.id
        no_email_id = no_email.id

    await prioritize_notification_outbox(committed_id)

    async with AsyncSessionLocal() as session:
        assert await session.get(Notification, rolled_back_id) is None
        assert (
            await session.scalar(
                select(TaskOutbox).where(
                    TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(rolled_back_id)
                )
            )
            is None
        )
        assert (
            await session.scalar(
                select(TaskOutbox).where(
                    TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(no_email_id)
                )
            )
            is None
        )

    def fail_broker(*_args, **_kwargs):
        raise ConnectionError("synthetic broker outage")

    monkeypatch.setattr("app.tasks.outbox.celery_app.send_task", fail_broker)
    assert await _dispatch_notification_email_outbox() == 0
    async with AsyncSessionLocal() as session:
        entry = await session.scalar(
            select(TaskOutbox).where(
                TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(committed_id)
            )
        )
        notice = await session.get(Notification, committed_id)
        assert entry is not None and entry.status == "pending"
        assert entry.attempts == 1
        assert entry.next_attempt_at is not None and entry.lease_until is None
        assert notice is not None and notice.email_status == "queued"


@pytest.mark.asyncio
async def test_concurrent_notification_email_delivery_is_single_claim(monkeypatch) -> None:
    await skip_if_database_unavailable()
    user_email, _ = await create_user("group_project_manager")
    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_by_email(user_email)
        assert user is not None
        notification = await NotificationService(session).create(
            user_id=user.id,
            title="Concurrent notice",
            body="One delivery only.",
            notification_type="approval",
        )
        await session.commit()
        notification_id = notification.id

    await prioritize_notification_outbox(notification_id)
    monkeypatch.setattr("app.tasks.outbox.celery_app.send_task", lambda *_args, **_kwargs: None)
    assert await _dispatch_notification_email_outbox() >= 1
    send_calls: list[str] = []

    def fake_send(self, *, recipients: list[str], subject: str, body: str) -> int:
        time.sleep(0.1)
        send_calls.append(subject)
        return 1

    monkeypatch.setattr("app.tasks.email.EmailService.send", fake_send)
    results = await asyncio.gather(
        _send_email_notification(str(notification_id)),
        _send_email_notification(str(notification_id)),
    )
    assert send_calls == ["Concurrent notice"]
    assert "notification email sent to 1 recipient" in results
    async with AsyncSessionLocal() as session:
        refreshed_notification = await session.get(Notification, notification_id)
        outbox = await session.scalar(
            select(TaskOutbox).where(
                TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(notification_id)
            )
        )
        assert refreshed_notification is not None
        assert refreshed_notification.email_status == "sent"
        assert outbox is not None and outbox.status == "completed"


@pytest.mark.asyncio
async def test_expired_notification_email_claim_requires_reconciliation() -> None:
    await skip_if_database_unavailable()
    user_email, _ = await create_user("group_project_manager")
    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_by_email(user_email)
        assert user is not None
        notification = await NotificationService(session).create(
            user_id=user.id,
            title="Stale delivery",
            body="Synthetic content.",
            notification_type="approval",
        )
        await session.flush()
        entry = await session.scalar(
            select(TaskOutbox).where(
                TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(notification.id)
            )
        )
        assert entry is not None
        entry.status = "processing"
        entry.lease_until = utc_now() - timedelta(minutes=6)
        notification.email_status = "sending"
        notification_id = notification.id
        await session.commit()

    await prioritize_notification_outbox(notification_id)
    await _dispatch_notification_email_outbox()
    async with AsyncSessionLocal() as session:
        refreshed_notification = await session.get(Notification, notification_id)
        entry = await session.scalar(
            select(TaskOutbox).where(
                TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(notification_id)
            )
        )
        assert refreshed_notification is not None
        assert refreshed_notification.email_status == "unknown"
        assert entry is not None and entry.status == "manual_review"


def test_send_email_notification_requires_notification_id() -> None:
    assert send_email_notification() == "notification id required"


@pytest.mark.asyncio
async def test_cleanup_old_notifications_soft_deletes_stale_items() -> None:
    await skip_if_database_unavailable()
    user_email, _ = await create_user("group_project_manager")

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


@pytest.mark.asyncio
async def test_notification_pagination_unread_parity_and_bulk_read_are_complete() -> None:
    await skip_if_database_unavailable()
    user_email, user_password = await create_user("group_project_manager")
    other_email, _ = await create_user("group_project_manager")

    async with create_test_client() as client:
        token = await login_for_token(client, user_email, user_password)
        headers = {"Authorization": f"Bearer {token}"}
        async with AsyncSessionLocal() as session:
            user = await UserRepository(session).get_by_email(user_email)
            other = await UserRepository(session).get_by_email(other_email)
            assert user is not None and other is not None
            created_at = datetime(2026, 11, 1, tzinfo=UTC)
            read_at = datetime(2026, 10, 31, tzinfo=UTC)
            notification_ids = [uuid4() for _ in range(250)]
            notifications = [
                Notification(
                    id=notification_ids[index],
                    user_id=user.id,
                    title=f"Synthetic notification {index}",
                    body="Synthetic test notification.",
                    notification_type="test",
                    reference_type=("hr_leave_request" if index == 1 else None),
                    event_code=("submitted" if index == 1 else None),
                    event_revision=(1 if index == 1 else None),
                    is_read=False,
                    muted=index == 0,
                    superseded_at=created_at if index == 1 else None,
                    read_at=read_at if index == 2 else None,
                    created_at=created_at,
                )
                for index in range(250)
            ]
            deleted = Notification(
                id=uuid4(),
                user_id=user.id,
                title="Synthetic deleted notification",
                body="Synthetic test notification.",
                notification_type="test",
                is_read=False,
                deleted_at=created_at,
                created_at=created_at,
            )
            other_user = Notification(
                id=uuid4(),
                user_id=other.id,
                title="Other user notification",
                body="Synthetic test notification.",
                notification_type="test",
                is_read=False,
                created_at=created_at,
            )
            deleted_id = deleted.id
            other_notification_id = other_user.id
            session.add_all([*notifications, deleted, other_user])
            await session.commit()

        first_page = await client.get("/api/v1/notifications", headers=headers)
        second_page = await client.get(
            "/api/v1/notifications", params={"limit": 100, "offset": 100}, headers=headers
        )
        final_page = await client.get(
            "/api/v1/notifications", params={"limit": 100, "offset": 200}, headers=headers
        )
        invalid_limit = await client.get(
            "/api/v1/notifications", params={"limit": 101}, headers=headers
        )
        invalid_offset = await client.get(
            "/api/v1/notifications", params={"offset": -1}, headers=headers
        )
        dashboard = await client.get("/api/v1/dashboard/summary", headers=headers)

        assert first_page.status_code == 200
        assert first_page.json()["total"] == 250
        assert len(first_page.json()["items"]) == 100
        assert second_page.status_code == final_page.status_code == 200
        assert len(second_page.json()["items"]) == 100
        assert len(final_page.json()["items"]) == 50
        page_ids = [
            UUID(item["id"])
            for page in (first_page, second_page, final_page)
            for item in page.json()["items"]
        ]
        assert page_ids == sorted(notification_ids, reverse=True)
        assert invalid_limit.status_code == invalid_offset.status_code == 422
        assert dashboard.status_code == 200
        assert dashboard.json()["unread_notifications"] == 248

        updated = await client.post("/api/v1/notifications/mark-all-read", headers=headers)
        repeated = await client.post("/api/v1/notifications/mark-all-read", headers=headers)
        assert updated.status_code == repeated.status_code == 200
        assert updated.json()["updated"] == 250
        assert repeated.json()["updated"] == 0

    async with AsyncSessionLocal() as session:
        preserved = await session.get(Notification, notification_ids[2])
        deleted_after = await session.get(Notification, deleted_id)
        other_after = await session.get(Notification, other_notification_id)
        assert preserved is not None and preserved.is_read is True
        assert preserved.read_at == read_at
        assert deleted_after is not None and deleted_after.is_read is False
        assert other_after is not None and other_after.is_read is False
