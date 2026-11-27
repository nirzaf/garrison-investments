import asyncio
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, engine
from app.models.hr import HrEmployee, HrLeaveRequest, HrLeaveType
from app.models.notification import Notification
from app.models.task_outbox import TaskOutbox, notification_email_outbox_dedupe_key
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.notification_service import NotificationService
from app.tasks.email import _send_email_notification, send_email_notification
from app.tasks.maintenance import _cleanup_old_notifications
from app.tasks.outbox import _dispatch_notification_email_outbox
from app.utils.security import utc_now
from app.utils.time import business_today
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


def _record_fake_email(calls: list[dict[str, object]], **message: object) -> int:
    calls.append(message)
    return 1


class _FakeNotificationEmailSession:
    def __init__(self, state: SimpleNamespace) -> None:
        self.state = state

    async def __aenter__(self) -> "_FakeNotificationEmailSession":
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def scalar(self, statement):
        description = statement.column_descriptions[0]
        entity = description["entity"]
        name = description["name"]
        if entity is TaskOutbox:
            return self.state.outbox
        if entity is Notification:
            return self.state.notification
        if entity is User:
            return self.state.user
        if entity is HrLeaveRequest:
            return self.state.request
        if entity is HrEmployee:
            if name == "HrEmployee":
                return self.state.employee
            if name == "manager_employee_id":
                return self.state.manager_employee_id
            if name == "user_id":
                return self.state.manager_user_id or self.state.employee.user_id
        raise AssertionError(f"Unexpected scalar query for {entity}.{name}")

    async def scalars(self, _statement):
        return list(self.state.filtered_user_ids)

    async def execute(self, _statement):
        return SimpleNamespace(all=lambda: [])

    async def commit(self) -> None:
        return None


def _leave_email_state(
    *,
    event: str = "submitted",
    request_status: str = "submitted",
    route: str = "supervisor",
    user_role: str = "group_project_manager",
    user_active: bool = True,
) -> SimpleNamespace:
    user_id = uuid4()
    employee_user_id = uuid4()
    manager_user_id = user_id if route == "supervisor" else uuid4()
    manager_employee_id = uuid4() if route == "supervisor" else None
    employee_id = uuid4()
    request_id = uuid4()
    revision = 2
    reason_code = "manager_missing" if route == "hr_fallback" else None
    reason = "No valid direct supervisor is assigned." if reason_code else None
    user = SimpleNamespace(
        id=user_id,
        email="synthetic-recipient@example.invalid",
        role=user_role,
        is_active=user_active,
        deleted_at=None,
    )
    employee = SimpleNamespace(
        id=employee_id,
        user_id=employee_user_id,
        manager_employee_id=manager_employee_id,
        deleted_at=None,
        employment_status="active",
    )
    request = SimpleNamespace(
        id=request_id,
        employee_id=employee_id,
        requested_by_id=uuid4(),
        status=request_status,
        record_revision=revision,
        approval_route=route,
        assigned_supervisor_user_id=manager_user_id if route == "supervisor" else None,
        fallback_reason_code=reason_code,
        fallback_reason=reason,
        fallback_until=None,
    )
    notification = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        reference_type="hr_leave_request",
        reference_id=request_id,
        event_code=event,
        event_revision=revision,
        email_status="queued",
        muted=False,
        superseded_at=None,
        title="Leave request approved",
        body=(
            "A leave request has a new status. Sign in to review it.\n\n"
            "Open leave workspace: https://portal.example.com/me/hr"
        ),
    )
    route_result = (
        ("supervisor", manager_user_id, None, None)
        if route == "supervisor"
        else ("hr_fallback", None, reason_code, reason)
    )
    return SimpleNamespace(
        user=user,
        employee=employee,
        manager_employee_id=manager_employee_id,
        manager_user_id=manager_user_id if manager_employee_id is not None else None,
        request=request,
        notification=notification,
        outbox=SimpleNamespace(status="dispatched", lease_until=None),
        current_route=route_result,
        eligible_hr_ids=[user_id],
        filtered_user_ids=[user_id],
    )


def _patch_fake_leave_workflow(monkeypatch, state: SimpleNamespace) -> None:
    from app.services.hr_workforce_service import HrWorkforceService

    async def current_route(_self, _employee, _submitter_id):
        if isinstance(state.current_route, Exception):
            raise state.current_route
        return state.current_route

    async def eligible_reviewers(_self, _request, *, excluded_ids=None):
        return state.eligible_hr_ids

    monkeypatch.setattr(HrWorkforceService, "_resolve_leave_route", current_route)
    monkeypatch.setattr(HrWorkforceService, "_eligible_hr_leave_approver_ids", eligible_reviewers)


def _patch_fake_email_task(monkeypatch, state: SimpleNamespace, send):
    monkeypatch.setattr(
        "app.tasks.email.AsyncSessionLocal",
        lambda: _FakeNotificationEmailSession(state),
    )

    class FakeEmailService:
        def send(self, *, recipients: list[str], subject: str, body: str) -> int:
            return send(recipients=recipients, subject=subject, body=body)

    monkeypatch.setattr("app.tasks.email.EmailService", FakeEmailService)


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
@pytest.mark.parametrize(
    "case",
    [
        "stale_revision",
        "status_changed",
        "expired_temporary_fallback",
        "returned_supervisor",
        "revoked_hr_role",
        "submitter_is_recipient",
        "hr_submitter_is_recipient",
        "employee_route_unavailable",
    ],
)
async def test_leave_email_worker_skips_stale_or_unauthorized_routes(monkeypatch, case) -> None:
    from app.utils.time import business_today

    state = _leave_email_state()
    if case == "stale_revision":
        state.notification.event_revision -= 1
    elif case == "status_changed":
        state.request.status = "approved"
    elif case == "expired_temporary_fallback":
        state = _leave_email_state(route="hr_fallback", user_role="hr_manager")
        state.request.fallback_reason_code = "manager_temporarily_unavailable"
        state.request.fallback_reason = "Supervisor temporarily unavailable."
        state.request.assigned_supervisor_user_id = uuid4()
        state.request.fallback_until = business_today() - timedelta(days=1)
        state.manager_employee_id = uuid4()
        state.employee.manager_employee_id = state.manager_employee_id
        state.manager_user_id = state.request.assigned_supervisor_user_id
        state.current_route = (
            "supervisor",
            state.request.assigned_supervisor_user_id,
            None,
            None,
        )
    elif case == "returned_supervisor":
        state = _leave_email_state(route="hr_fallback", user_role="hr_manager")
        state.request.fallback_reason_code = "manager_absent"
        state.request.fallback_reason = "The assigned direct supervisor is on approved leave."
        state.manager_employee_id = uuid4()
        state.employee.manager_employee_id = state.manager_employee_id
        state.manager_user_id = uuid4()
        state.current_route = ("supervisor", state.manager_user_id, None, None)
    elif case == "revoked_hr_role":
        state = _leave_email_state(route="hr_fallback", user_role="quantity_surveyor")
    elif case == "submitter_is_recipient":
        state.request.requested_by_id = state.user.id
    elif case == "hr_submitter_is_recipient":
        state = _leave_email_state(route="hr_fallback", user_role="hr_manager")
        state.request.requested_by_id = state.user.id
        state.eligible_hr_ids = []
    elif case == "employee_route_unavailable":
        from app.utils.exceptions import AppException

        state.employee.employment_status = "terminated"
        state.current_route = AppException(
            "Leave can only be routed for a currently employed employee.",
            status_code=409,
        )

    _patch_fake_leave_workflow(monkeypatch, state)
    send_calls: list[dict[str, object]] = []
    _patch_fake_email_task(
        monkeypatch,
        state,
        lambda **message: _record_fake_email(send_calls, **message),
    )

    result = await _send_email_notification(str(state.notification.id))

    assert result == "notification email skipped"
    assert state.notification.email_status == "skipped"
    assert state.outbox.status == "completed"
    assert send_calls == []


@pytest.mark.asyncio
async def test_independent_hr_can_receive_pending_leave_email(monkeypatch) -> None:
    state = _leave_email_state(route="hr_fallback", user_role="hr_manager")
    state.eligible_hr_ids = [state.user.id]
    send_calls: list[dict[str, object]] = []
    _patch_fake_leave_workflow(monkeypatch, state)
    _patch_fake_email_task(
        monkeypatch,
        state,
        lambda **message: _record_fake_email(send_calls, **message),
    )

    result = await _send_email_notification(str(state.notification.id))

    assert result == "notification email sent to 1 recipient"
    assert state.notification.email_status == "sent"
    assert state.outbox.status == "completed"
    assert len(send_calls) == 1


@pytest.mark.asyncio
async def test_current_supervisor_can_receive_pending_leave_email(monkeypatch) -> None:
    state = _leave_email_state()
    send_calls: list[dict[str, object]] = []
    _patch_fake_leave_workflow(monkeypatch, state)
    _patch_fake_email_task(
        monkeypatch,
        state,
        lambda **message: _record_fake_email(send_calls, **message),
    )

    result = await _send_email_notification(str(state.notification.id))

    assert result == "notification email sent to 1 recipient"
    assert state.notification.email_status == "sent"
    assert state.outbox.status == "completed"
    assert len(send_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("recipient", ["employee", "hr"])
async def test_leave_email_worker_skips_disabled_employee_or_hr(monkeypatch, recipient) -> None:
    if recipient == "employee":
        state = _leave_email_state(
            event="approved",
            request_status="approved",
            route="none",
            user_role="quantity_surveyor",
            user_active=False,
        )
        state.user.id = state.employee.user_id
        state.notification.user_id = state.user.id
    else:
        state = _leave_email_state(route="hr_fallback", user_role="hr_manager", user_active=False)

    send_calls: list[dict[str, object]] = []
    _patch_fake_email_task(
        monkeypatch,
        state,
        lambda **message: _record_fake_email(send_calls, **message),
    )

    result = await _send_email_notification(str(state.notification.id))

    assert result == "notification email skipped"
    assert state.notification.email_status == "skipped"
    assert state.outbox.status == "completed"
    assert send_calls == []


@pytest.mark.asyncio
async def test_muted_leave_email_is_skipped_without_transport(monkeypatch) -> None:
    state = _leave_email_state()
    state.notification.muted = True
    send_calls: list[dict[str, object]] = []
    _patch_fake_email_task(
        monkeypatch,
        state,
        lambda **message: _record_fake_email(send_calls, **message),
    )

    result = await _send_email_notification(str(state.notification.id))

    assert result == "notification email skipped"
    assert state.notification.email_status == "skipped"
    assert state.outbox.status == "completed"
    assert send_calls == []


@pytest.mark.asyncio
async def test_already_sent_leave_email_is_preserved_after_expired_claim(monkeypatch) -> None:
    state = _leave_email_state(
        event="approved",
        request_status="approved",
        route="none",
        user_role="quantity_surveyor",
    )
    state.user.id = state.employee.user_id
    state.notification.user_id = state.user.id
    state.notification.email_status = "sent"
    state.outbox.status = "processing"
    state.outbox.lease_until = utc_now() - timedelta(minutes=6)
    send_calls: list[dict[str, object]] = []
    _patch_fake_email_task(
        monkeypatch,
        state,
        lambda **message: _record_fake_email(send_calls, **message),
    )

    result = await _send_email_notification(str(state.notification.id))

    assert result == "notification email already sent"
    assert state.notification.email_status == "sent"
    assert state.outbox.status == "completed"
    assert send_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("recipient", ["employee", "submitter", "hr", "supervisor"])
async def test_valid_terminal_leave_email_sends_once_with_generic_content(
    monkeypatch, recipient
) -> None:
    state = _leave_email_state(
        event="approved",
        request_status="approved",
        route="none",
        user_role="quantity_surveyor",
    )
    if recipient == "employee":
        state.user.id = state.employee.user_id
        state.notification.user_id = state.user.id
    elif recipient == "submitter":
        state.request.requested_by_id = state.user.id
    elif recipient == "hr":
        state.user.role = "hr_manager"
    else:
        state.employee.manager_employee_id = uuid4()
        state.manager_employee_id = state.employee.manager_employee_id
        state.manager_user_id = state.user.id
        state.request.assigned_supervisor_user_id = state.user.id
    sent: list[dict[str, object]] = []
    _patch_fake_email_task(
        monkeypatch,
        state,
        lambda **message: _record_fake_email(sent, **message),
    )

    result = await _send_email_notification(str(state.notification.id))
    replay = await _send_email_notification(str(state.notification.id))

    assert result == "notification email sent to 1 recipient"
    assert replay == "notification email is not eligible for delivery"
    assert state.notification.email_status == "sent"
    assert state.outbox.status == "completed"
    assert sent == [
        {
            "recipients": ["synthetic-recipient@example.invalid"],
            "subject": "Leave request approved",
            "body": (
                "A leave request has a new status. Sign in to review it.\n\n"
                "Open leave workspace: https://portal.example.com/me/hr"
            ),
        }
    ]


@pytest.mark.asyncio
async def test_ambiguous_leave_email_transport_failure_requires_review(monkeypatch) -> None:
    from app.services.email_service import EmailDeliveryError

    state = _leave_email_state(
        event="approved",
        request_status="approved",
        route="none",
        user_role="quantity_surveyor",
    )
    state.user.id = state.employee.user_id
    state.notification.user_id = state.user.id
    calls = 0

    def fail_transport(**_message) -> int:
        nonlocal calls
        calls += 1
        raise EmailDeliveryError("synthetic transport failure")

    _patch_fake_email_task(monkeypatch, state, fail_transport)

    result = await _send_email_notification(str(state.notification.id))
    replay = await _send_email_notification(str(state.notification.id))

    assert result == "notification email delivery outcome requires review"
    assert replay == "notification email is not eligible for delivery"
    assert state.notification.email_status == "unknown"
    assert state.outbox.status == "manual_review"
    assert calls == 1


@pytest.mark.asyncio
async def test_pending_leave_notification_rejects_stale_recipient_route(monkeypatch) -> None:
    from app.services.hr_workforce_service import HrWorkforceService

    state = _leave_email_state(event="rerouted")
    stale_supervisor_id = state.request.assigned_supervisor_user_id
    state.current_route = ("supervisor", uuid4(), None, None)
    state.filtered_user_ids = [stale_supervisor_id]
    _patch_fake_leave_workflow(monkeypatch, state)
    service = HrWorkforceService(cast(AsyncSession, _FakeNotificationEmailSession(state)))

    recipients = await service._leave_notification_users(state.request, "rerouted")

    assert recipients == []


@pytest.mark.asyncio
async def test_stale_pending_route_does_not_audit_missing_hr_reviewer(monkeypatch) -> None:
    from app.services.hr_workforce_service import HrWorkforceService

    state = _leave_email_state(event="rerouted", route="hr_fallback", user_role="hr_manager")
    state.request.fallback_reason_code = "manager_absent"
    state.request.fallback_reason = "The assigned direct supervisor is on approved leave."
    state.manager_employee_id = uuid4()
    state.employee.manager_employee_id = state.manager_employee_id
    state.manager_user_id = uuid4()
    state.current_route = ("supervisor", state.manager_user_id, None, None)
    state.filtered_user_ids = []
    state.eligible_hr_ids = [state.user.id]
    _patch_fake_leave_workflow(monkeypatch, state)

    class FakeAudit:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def record(self, **values) -> None:
            self.calls.append(values)

    service = HrWorkforceService(cast(AsyncSession, _FakeNotificationEmailSession(state)))
    audit = FakeAudit()
    cast(Any, service).audit = audit
    await service._notify_leave_event(state.request, "rerouted", uuid4())

    assert audit.calls == []


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
async def test_notification_email_dispatch_exhaustion_exposes_failed_status(
    monkeypatch,
) -> None:
    await skip_if_database_unavailable()
    from app.schemas.notifications import NotificationResponse
    from app.tasks.outbox import MAX_NOTIFICATION_EMAIL_ATTEMPTS

    user_email, _ = await create_user("group_project_manager")
    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_by_email(user_email)
        assert user is not None
        notification = await NotificationService(session).create(
            user_id=user.id,
            title="Synthetic delivery status",
            body="No transport should be dispatched after exhaustion.",
            notification_type="approval",
        )
        outbox = await session.scalar(
            select(TaskOutbox).where(
                TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(notification.id)
            )
        )
        assert outbox is not None
        outbox.attempts = MAX_NOTIFICATION_EMAIL_ATTEMPTS
        await session.commit()

    await prioritize_notification_outbox(notification.id)
    monkeypatch.setattr(
        "app.tasks.outbox.celery_app.send_task",
        lambda *_args, **_kwargs: pytest.fail("exhausted dispatch must not contact the broker"),
    )
    assert await _dispatch_notification_email_outbox() == 0

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(Notification, notification.id)
        entry = await session.scalar(
            select(TaskOutbox).where(
                TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(notification.id)
            )
        )
        assert refreshed is not None and entry is not None
        assert refreshed.email_status == "failed"
        assert NotificationResponse.model_validate(refreshed).email_status == "failed"
        assert entry.status == "failed"


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


@pytest.mark.asyncio
async def test_live_leave_actionability_query_is_scoped_and_minimal() -> None:
    from app.repositories.notification_repository import NotificationRepository

    class QueryCapture:
        statement: Any = None

        async def scalars(self, statement):
            self.statement = statement
            return []

        async def scalar(self, statement):
            self.statement = statement
            return 0

    user = cast(
        User,
        SimpleNamespace(id=uuid4(), role="group_project_manager", is_active=True, deleted_at=None),
    )
    capture = QueryCapture()
    repository = NotificationRepository(cast(AsyncSession, capture))
    notification_id = uuid4()

    assert await repository.actionable_leave_notification_ids({notification_id}, user) == set()
    scoped_query = str(capture.statement.compile(dialect=postgresql.dialect()))
    assert "notifications.id IN" in scoped_query
    assert "notifications.user_id" in scoped_query
    assert "hr_leave_requests.reason " not in scoped_query

    assert await repository.unread_count(user) == 0
    unread_query = str(capture.statement.compile(dialect=postgresql.dialect()))
    assert "count(*)" in unread_query.lower()
    assert "notifications.user_id" in unread_query
    assert "hr_leave_requests.reason " not in unread_query


@pytest.mark.asyncio
async def test_leave_notification_reads_recheck_live_routes_without_revision_changes() -> None:
    await skip_if_database_unavailable()
    manager_email, manager_password = await create_user("group_project_manager")
    replacement_email, replacement_password = await create_user("group_project_manager")
    hr_email, hr_password = await create_user("hr_manager")
    subject_email, _ = await create_user("quantity_surveyor")
    second_subject_email, _ = await create_user("quantity_surveyor")
    submitter_email, _ = await create_user("quantity_surveyor")

    async with AsyncSessionLocal() as session:
        users = {
            email: await UserRepository(session).get_by_email(email)
            for email in (
                manager_email,
                replacement_email,
                hr_email,
                subject_email,
                second_subject_email,
                submitter_email,
            )
        }

        def required_user(email: str) -> User:
            user = users[email]
            assert user is not None
            return user

        manager_user = required_user(manager_email)
        replacement_user = required_user(replacement_email)
        hr_user = required_user(hr_email)
        subject_user = required_user(subject_email)
        second_subject_user = required_user(second_subject_email)
        submitter = required_user(submitter_email)

        def employee(user: User, label: str) -> HrEmployee:
            suffix = uuid4().hex[:12]
            return HrEmployee(
                id=uuid4(),
                user_id=user.id,
                employee_code=f"NT03-{suffix}",
                first_name="Synthetic",
                last_name=label,
                full_name=f"Synthetic {label}",
                employment_status="active",
            )

        manager_employee = employee(manager_user, "Manager")
        replacement_employee = employee(replacement_user, "Replacement")
        subject_employee = employee(subject_user, "Subject")
        second_subject_employee = employee(second_subject_user, "FallbackSubject")
        subject_employee.manager_employee_id = manager_employee.id
        leave_type = HrLeaveType(
            id=uuid4(),
            code=f"NT03-{uuid4().hex[:12]}",
            name="Synthetic notification route leave",
            is_paid=True,
            is_active=True,
            policy_required=False,
        )
        session.add_all(
            [
                manager_employee,
                replacement_employee,
                subject_employee,
                second_subject_employee,
                leave_type,
            ]
        )
        await session.flush()

        revision = 4
        today = business_today()
        supervisor_request = HrLeaveRequest(
            id=uuid4(),
            employee_id=subject_employee.id,
            leave_type_id=leave_type.id,
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=10),
            days_requested=Decimal("1.00"),
            reason="Synthetic private leave detail",
            status="submitted",
            requested_by_id=submitter.id,
            record_revision=revision,
            approval_route="supervisor",
            assigned_supervisor_user_id=manager_user.id,
        )
        fallback_request = HrLeaveRequest(
            id=uuid4(),
            employee_id=second_subject_employee.id,
            leave_type_id=leave_type.id,
            start_date=today + timedelta(days=12),
            end_date=today + timedelta(days=12),
            days_requested=Decimal("1.00"),
            reason="Another synthetic private detail",
            status="submitted",
            requested_by_id=submitter.id,
            record_revision=revision,
            approval_route="hr_fallback",
            fallback_reason_code="manager_missing",
            fallback_reason="No valid direct supervisor is assigned.",
            fallback_recorded_by_id=submitter.id,
            fallback_recorded_at=utc_now(),
        )
        supervisor_notice = Notification(
            id=uuid4(),
            user_id=manager_user.id,
            title="Leave request submitted",
            body=(
                "A leave request has a new status. Sign in to review it.\n\n"
                "Open leave workspace: https://portal.example.com/hr"
            ),
            notification_type="hr",
            reference_type="hr_leave_request",
            reference_id=supervisor_request.id,
            event_code="submitted",
            event_revision=revision,
            email_status="sent",
        )
        fallback_notice = Notification(
            id=uuid4(),
            user_id=hr_user.id,
            title="Leave request ready for review",
            body="Synthetic generic HR notification.",
            notification_type="hr",
            reference_type="hr_leave_request",
            reference_id=fallback_request.id,
            event_code="rerouted",
            event_revision=revision,
            email_status="sent",
        )
        ordinary_notice = Notification(
            id=uuid4(),
            user_id=manager_user.id,
            title="Inventory update",
            body="Synthetic inventory notification.",
            notification_type="inventory",
        )
        session.add_all(
            [
                supervisor_request,
                fallback_request,
                supervisor_notice,
                fallback_notice,
                ordinary_notice,
            ]
        )
        await session.commit()

        supervisor_notice_id = supervisor_notice.id
        fallback_notice_id = fallback_notice.id
        supervisor_request_id = supervisor_request.id
        fallback_request_id = fallback_request.id
        ordinary_notice_id = ordinary_notice.id
        replacement_user_id = replacement_user.id

    async with create_test_client() as client:
        manager_token = await login_for_token(client, manager_email, manager_password)
        hr_token = await login_for_token(client, hr_email, hr_password)
        manager_headers = {"Authorization": f"Bearer {manager_token}"}
        hr_headers = {"Authorization": f"Bearer {hr_token}"}

        manager_before = await client.get("/api/v1/notifications", headers=manager_headers)
        manager_count_before = await client.get(
            "/api/v1/notifications/unread-count", headers=manager_headers
        )
        hr_before = await client.get("/api/v1/notifications", headers=hr_headers)
        hr_count_before = await client.get("/api/v1/notifications/unread-count", headers=hr_headers)
        assert manager_before.status_code == hr_before.status_code == 200
        assert manager_count_before.json()["unread_count"] == 2
        assert hr_count_before.json()["unread_count"] == 1
        manager_item_before = next(
            item
            for item in manager_before.json()["items"]
            if item["id"] == str(supervisor_notice_id)
        )
        hr_item_before = next(
            item for item in hr_before.json()["items"] if item["id"] == str(fallback_notice_id)
        )
        assert manager_item_before["is_actionable"] is True
        assert hr_item_before["is_actionable"] is True

        async with AsyncSessionLocal() as session:
            replacement = await session.get(HrEmployee, replacement_employee.id)
            subject = await session.get(HrEmployee, subject_employee.id)
            fallback_subject = await session.get(HrEmployee, second_subject_employee.id)
            assert replacement is not None and subject is not None and fallback_subject is not None
            subject.manager_employee_id = replacement.id
            fallback_subject.manager_employee_id = replacement.id
            await session.commit()

        manager_after = await client.get("/api/v1/notifications", headers=manager_headers)
        manager_count_after = await client.get(
            "/api/v1/notifications/unread-count", headers=manager_headers
        )
        hr_after = await client.get("/api/v1/notifications", headers=hr_headers)
        hr_count_after = await client.get("/api/v1/notifications/unread-count", headers=hr_headers)
        assert manager_after.status_code == hr_after.status_code == 200
        assert manager_count_after.json()["unread_count"] == 1
        assert hr_count_after.json()["unread_count"] == 0
        manager_item_after = next(
            item
            for item in manager_after.json()["items"]
            if item["id"] == str(supervisor_notice_id)
        )
        hr_item_after = next(
            item for item in hr_after.json()["items"] if item["id"] == str(fallback_notice_id)
        )
        assert manager_item_after["is_actionable"] is False
        assert hr_item_after["is_actionable"] is False
        assert manager_item_after["body"].endswith(
            "Open leave workspace: https://portal.example.com/hr"
        )
        assert manager_item_after["superseded_at"] is None
        assert manager_item_after["is_read"] is False and manager_item_after["muted"] is False
        assert "Synthetic private leave detail" not in manager_after.text

        replacement_token = await login_for_token(client, replacement_email, replacement_password)
        replacement_headers = {"Authorization": f"Bearer {replacement_token}"}
        async with AsyncSessionLocal() as session:
            from app.services.hr_workforce_service import HrWorkforceService

            request = await session.get(HrLeaveRequest, supervisor_request_id)
            assert request is not None
            request.approval_route = "supervisor"
            request.assigned_supervisor_user_id = replacement_user_id
            request.fallback_reason_code = None
            request.fallback_reason = None
            request.fallback_recorded_by_id = None
            request.fallback_recorded_at = None
            request.fallback_until = None
            request.record_revision += 1
            await HrWorkforceService(session)._notify_leave_event(request, "rerouted", submitter.id)
            await session.commit()
            current_notice = await session.scalar(
                select(Notification).where(
                    Notification.reference_type == "hr_leave_request",
                    Notification.reference_id == supervisor_request_id,
                    Notification.event_code == "rerouted",
                    Notification.event_revision == request.record_revision,
                    Notification.user_id == replacement_user_id,
                )
            )
            assert current_notice is not None
            current_notice_id = current_notice.id

        replacement_after = await client.get("/api/v1/notifications", headers=replacement_headers)
        replacement_count = await client.get(
            "/api/v1/notifications/unread-count", headers=replacement_headers
        )
        assert replacement_after.status_code == 200
        assert replacement_count.json()["unread_count"] == 1
        current_item = next(
            item
            for item in replacement_after.json()["items"]
            if item["id"] == str(current_notice_id)
        )
        assert current_item["is_actionable"] is True

    async with AsyncSessionLocal() as session:
        supervisor_saved = await session.get(Notification, supervisor_notice_id)
        fallback_saved = await session.get(Notification, fallback_notice_id)
        ordinary_saved = await session.get(Notification, ordinary_notice_id)
        current_saved = await session.get(Notification, current_notice_id)
        supervisor_request_saved = await session.get(HrLeaveRequest, supervisor_request_id)
        fallback_request_saved = await session.get(HrLeaveRequest, fallback_request_id)
        assert supervisor_saved is not None and fallback_saved is not None
        assert current_saved is not None
        assert ordinary_saved is not None
        assert supervisor_request_saved is not None and fallback_request_saved is not None
        assert supervisor_saved.superseded_at is not None and fallback_saved.superseded_at is None
        assert supervisor_saved.email_status == fallback_saved.email_status == "sent"
        assert supervisor_saved.is_read is False and fallback_saved.is_read is False
        assert current_saved.email_status == "queued" and current_saved.is_read is False
        assert current_saved.superseded_at is None
        pending_mail = await session.scalar(
            select(TaskOutbox).where(
                TaskOutbox.dedupe_key == notification_email_outbox_dedupe_key(current_notice_id)
            )
        )
        assert pending_mail is not None and pending_mail.status == "pending"
        assert supervisor_request_saved.record_revision == revision + 1
        assert fallback_request_saved.record_revision == revision
        assert ordinary_saved.is_read is False and ordinary_saved.muted is False
