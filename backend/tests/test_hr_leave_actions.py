"""LM-12 actor projections use only disposable synthetic leave records."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, or_, select, update

from app.api.v1.hr import _leave_request_list_response, _leave_request_response
from app.database import AsyncSessionLocal, check_database, engine
from app.models.hr import HrEmployee, HrLeaveLedger, HrLeaveRequest, HrLeaveType
from app.models.notification import Notification
from app.models.user import User
from app.schemas.hr import (
    LeaveRequestDecisionRequest,
    LeaveRequestDecisionState,
    LeaveRouteRefreshRequest,
    SupervisorLeaveDecisionRequest,
)
from app.services.hr_workforce_service import HrWorkforceService
from app.utils.exceptions import AppException
from app.utils.permissions import PERMISSION_HR_LEAVE_APPROVE, roles_with_permission
from app.utils.time import business_today
from tests.password_fixtures import hash_fixture_password
from tests.test_hr import _auth, _client, _login


@pytest.fixture(autouse=True)
async def isolated_pool():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def leave_graph():
    if not await check_database():
        pytest.skip("database is not available")
    async with AsyncSessionLocal() as session:

        def user(role, name):
            return User(
                id=uuid4(),
                email=f"lm12-{uuid4().hex}@example.com",
                role=role,
                full_name=f"Synthetic {name}",
                is_active=True,
                must_change_password=False,
                password_hash=hash_fixture_password("Synthetic-LM12-Password!"),
            )

        hr = user("hr_manager", "HR reviewer")
        manager = user("group_project_manager", "Supervisor")
        worker = user("quantity_surveyor", "Employee")
        former = user("group_project_manager", "Former supervisor")
        technical = user("super_admin", "Technical actor")
        session.add_all([hr, manager, worker, former, technical])
        await session.flush()
        manager_employee = HrEmployee(
            id=uuid4(),
            user_id=manager.id,
            employee_code=f"LM12-{uuid4().hex[:8]}",
            first_name="Synthetic",
            last_name="Manager",
            full_name="Synthetic Manager",
            employment_status="active",
        )
        employee = HrEmployee(
            id=uuid4(),
            user_id=worker.id,
            employee_code=f"LM12-{uuid4().hex[:8]}",
            first_name="Synthetic",
            last_name="Employee",
            full_name="Synthetic Employee",
            employment_status="active",
            manager_employee_id=manager_employee.id,
        )
        leave_type = HrLeaveType(
            id=uuid4(),
            code=f"LM12-{uuid4().hex[:10]}",
            name="Synthetic private category",
            is_paid=False,
            is_active=True,
            policy_required=False,
        )
        session.add_all([manager_employee, employee, leave_type])
        await session.flush()
        day = business_today() + timedelta(days=10)
        request = HrLeaveRequest(
            id=uuid4(),
            employee_id=employee.id,
            leave_type_id=leave_type.id,
            start_date=day,
            end_date=day,
            days_requested=Decimal("1.00"),
            scheduled_work_dates=[day],
            reason="Synthetic private reason",
            status="submitted",
            requested_by_id=worker.id,
            record_revision=1,
            approval_route="supervisor",
            assigned_supervisor_user_id=manager.id,
        )
        session.add(request)
        await session.flush()
        yield session, hr, manager, worker, former, technical, employee, request
        await session.rollback()

        # A few API-path cases commit to make records visible to a separate
        # request session. Remove only this fixture's synthetic rows afterward.
        user_ids = select(User.id).where(User.email.like("lm12-%@example.com"))
        employee_ids = select(HrEmployee.id).where(HrEmployee.employee_code.like("LM12-%"))
        request_ids = select(HrLeaveRequest.id).where(
            or_(
                HrLeaveRequest.employee_id.in_(employee_ids),
                HrLeaveRequest.requested_by_id.in_(user_ids),
            )
        )
        await session.execute(
            delete(Notification).where(
                or_(Notification.user_id.in_(user_ids), Notification.reference_id.in_(request_ids))
            )
        )
        await session.execute(
            delete(HrLeaveLedger).where(
                or_(HrLeaveLedger.employee_id.in_(employee_ids),
                    HrLeaveLedger.reference_request_id.in_(request_ids))
            )
        )
        await session.execute(delete(HrLeaveRequest).where(HrLeaveRequest.id.in_(request_ids)))
        await session.execute(
            update(HrEmployee)
            .where(HrEmployee.id.in_(employee_ids))
            .values(manager_employee_id=None)
        )
        await session.execute(delete(HrEmployee).where(HrEmployee.id.in_(employee_ids)))
        await session.execute(delete(HrLeaveType).where(HrLeaveType.code.like("LM12-%")))
        await session.execute(
            update(User)
            .where(User.id.in_(user_ids))
            .values(is_active=False, deleted_at=datetime.now(UTC))
        )
        await session.commit()


async def test_final_reversal_is_advertised_only_to_independent_hr(leave_graph):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    request.status = "approved"
    request.decided_by_id = manager.id
    request.decided_at = datetime.now(UTC)
    session.add(
        HrLeaveLedger(
            employee_id=employee.id,
            leave_type_id=request.leave_type_id,
            leave_year=request.start_date.year,
            entry_type="taken",
            days_delta=Decimal("-1.00"),
            reference_request_id=request.id,
            actor_user_id=manager.id,
            reason="Synthetic approved leave debit",
        )
    )
    await session.flush()
    await session.refresh(request)
    for actor in (hr, manager, worker, former, technical):
        detail = await _leave_request_response(session, request, actor)
        page = await _leave_request_list_response(session, [request], 1, actor)
        assert detail.allowed_actions == page.items[0].allowed_actions
        assert detail.allowed_actions == (["cancel"] if actor is hr else [])
        assert detail.route_status == "final"


async def test_hr_route_name_is_scoped_and_projection_matches_current_route(leave_graph):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    detail = await _leave_request_response(session, request, hr)
    assert detail.current_reviewer_name == manager.full_name
    assert "approve" not in detail.allowed_actions
    for actor in (worker, former, technical):
        result = await _leave_request_response(session, request, actor)
        assert result.current_reviewer_name is None
        assert "approve" not in result.allowed_actions
    request.assigned_supervisor_user_id = former.id
    await session.flush()
    await session.refresh(request)
    detail = await _leave_request_response(session, request, hr)
    assert detail.route_status == "refresh_required"
    assert detail.current_reviewer_name is None
    assert detail.allowed_actions == ["refresh_route"]


@pytest.mark.parametrize("fallback", [False, True])
async def test_scoped_endpoints_final_actor_and_private_self_result(leave_graph, fallback):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    request.requires_manager_recommendation = True
    # A historic advisory is retained, but is never required for final leave decisions.
    request.manager_recommendation = "support"
    await session.commit()
    async with _client() as client:
        headers = {}
        for actor in (hr, manager, worker, former):
            headers[actor.id] = _auth(await _login(client, actor.email, "Synthetic-LM12-Password!"))
        company = "/api/v1/hr/leave/requests"
        own = "/api/v1/hr/me/leave-requests"
        queue = "/api/v1/hr/me/leave-reviews"
        state_path = f"{company}/{request.id}/decision"
        page = await client.get(
            company, headers=headers[hr.id], params={"employee_id": str(employee.id)}
        )
        assert page.status_code == 200
        assert "no-store" in page.headers["cache-control"]
        projection = page.json()["items"][0]
        assert projection["current_reviewer_name"] == manager.full_name
        assert projection["allowed_actions"] == ["refresh_route", "route_to_hr_fallback"]
        assert (await client.get(company, headers=headers[worker.id])).status_code == 403
        assert (await client.get(state_path, headers=headers[manager.id])).status_code == 403
        denied = await client.post(
            state_path,
            headers=headers[hr.id],
            json={
                "decision": "approved",
                "expected_revision": 1,
            },
        )
        assert denied.status_code == 403
        assert denied.json()["error_code"] == "LEAVE_SUPERVISOR_DECISION_REQUIRED"
        reviews = await client.get(queue, headers=headers[manager.id])
        assert reviews.status_code == 200
        assert "no-store" in reviews.headers["cache-control"]
        review = next(row for row in reviews.json()["items"] if row["id"] == str(request.id))
        assert set(review) == {
            "id",
            "employee_name",
            "start_date",
            "end_date",
            "chargeable_units",
            "is_half_day",
            "status",
            "record_revision",
            "allowed_actions",
            "route_status",
        }
        assert review["allowed_actions"] == ["approve", "reject"]
        assert (await client.get(queue, headers=headers[worker.id])).json()["items"] == []
        # An unlinked former supervisor has no self-service HR access.
        assert (await client.get(queue, headers=headers[former.id])).status_code == 404
        revision = 1
        if fallback:
            receipt = await client.post(
                f"{company}/{request.id}/fallback",
                headers=headers[hr.id],
                json={
                    "expected_revision": 1,
                    "reason_code": "manager_temporarily_unavailable",
                    "reason": "Synthetic temporary unavailability",
                    "until": business_today().isoformat(),
                },
            )
            assert receipt.status_code == 200, receipt.text
            assert "no-store" in receipt.headers["cache-control"]
            assert receipt.json()["route_status"] == "pending_hr"
            assert {"approve", "reject", "restore_supervisor"} <= set(
                receipt.json()["allowed_actions"]
            )
            revision = receipt.json()["record_revision"]
            assert (await client.get(queue, headers=headers[manager.id])).json()["items"] == []
            stale = await client.post(
                f"{queue}/{request.id}/decision",
                headers=headers[manager.id],
                json={
                    "decision": "rejected",
                    "expected_revision": revision,
                    "notes": "Synthetic stale",
                },
            )
            assert stale.status_code == 409
            assert stale.json()["error_code"] == "LEAVE_ROUTE_CHANGED"
        final_path = state_path if fallback else f"{queue}/{request.id}/decision"
        final_actor = hr if fallback else manager
        malformed = await client.post(
            final_path,
            headers=headers[final_actor.id],
            json={
                "decision": "rejected",
                "expected_revision": revision,
                "notes": "   ",
            },
        )
        assert malformed.status_code == 422
        result = await client.post(
            final_path,
            headers=headers[final_actor.id],
            json={
                "decision": "rejected",
                "expected_revision": revision,
                "notes": "Synthetic final reason",
            },
        )
        assert result.status_code == 200, result.text
        assert "no-store" in result.headers["cache-control"]
        state = await client.get(state_path, headers=headers[hr.id])
        assert state.json()["decided_by_id"] == str(final_actor.id)
        assert state.json()["decided_by_name"] == final_actor.full_name
        assert state.json()["decided_at"]
        assert state.json()["allowed_actions"] == []
        assert state.json()["route_status"] == "final"
        assert state.json()["manager_recommendation"] == "support"
        own_result = await client.get(own, headers=headers[worker.id])
        assert "no-store" in own_result.headers["cache-control"]
        own_row = next(row for row in own_result.json()["items"] if row["id"] == str(request.id))
        assert own_row["status"] == "rejected"
        assert own_row["decided_at"] == state.json()["decided_at"]
        assert own_row["decision_notes"] == "Synthetic final reason"
        assert own_row["decided_by_name"] is None
        assert own_row["current_reviewer_name"] is None
        assert own_row["allowed_actions"] == []


async def test_own_cancellation_requires_current_revision_and_conceals_other_employee(leave_graph):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    await session.commit()
    async with _client() as client:
        worker_headers = _auth(await _login(client, worker.email, "Synthetic-LM12-Password!"))
        other_headers = _auth(await _login(client, former.email, "Synthetic-LM12-Password!"))
        path = f"/api/v1/hr/me/leave-requests/{request.id}/cancel"
        assert (
            await client.post(path, headers=other_headers, json={"expected_revision": 1})
        ).status_code == 404
        stale = await client.post(path, headers=worker_headers, json={"expected_revision": 2})
        assert stale.status_code == 409
        assert stale.json()["error_code"] == "REVISION_CONFLICT"
        invalid = await client.post(path, headers=worker_headers, json={"expected_revision": 0})
        assert invalid.status_code == 422
        saved = await client.post(path, headers=worker_headers)
        assert saved.status_code == 200
        assert "no-store" in saved.headers["cache-control"]
        assert saved.json()["status"] == "cancelled"
        assert saved.json()["record_revision"] == 2
        assert saved.json()["allowed_actions"] == []


async def test_stale_route_denials_filter_and_refresh(leave_graph):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    service = HrWorkforceService(session)
    manager.is_active = False
    await session.flush()
    page, total = await service.list_leave_requests(
        employee_id=employee.id, needs_attention=True, limit=1
    )
    assert total == 1 and [row.id for row in page] == [request.id]
    projected = await _leave_request_response(session, request, hr)
    assert projected.route_status == "refresh_required"
    assert projected.allowed_actions == ["refresh_route"]
    for actor in (manager, former, technical, worker):
        projected = await _leave_request_response(session, request, actor)
        assert "approve" not in projected.allowed_actions
        assert "reject" not in projected.allowed_actions
    # Service denial is checked under the existing write locks, independently of the UI.
    with pytest.raises(AppException) as stale:
        await service.decide_supervisor_leave_request(
            request.id,
            SupervisorLeaveDecisionRequest(
                decision="rejected",
                notes="Synthetic stale route",
                expected_revision=1,
            ),
            manager,
        )
    assert stale.value.status_code == 409
    assert stale.value.error_code == "LEAVE_ROUTE_CHANGED"
    with pytest.raises(AppException) as forbidden:
        await service.decide_leave_request(
            request.id,
            LeaveRequestDecisionRequest(
                decision="rejected",
                notes="Synthetic forbidden",
                expected_revision=1,
            ),
            technical,
        )
    assert forbidden.value.status_code == 403
    assert request.status == "submitted" and request.record_revision == 1


async def test_historical_date_reconciliation_is_an_additive_projection(leave_graph):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    request.status = "approved"
    request.decided_by_id = manager.id
    request.decided_at = datetime.now(UTC)
    request.start_date = business_today().replace(day=1)
    request.end_date = request.start_date + timedelta(days=40)
    request.scheduled_work_dates = None
    await session.flush()
    await session.refresh(request)
    result = await _leave_request_response(session, request, hr)
    assert result.reconciliation_status == "required"
    assert result.decided_by_name == manager.full_name


def test_decision_state_legacy_consumers_need_no_new_fields():
    state = LeaveRequestDecisionState(
        id=uuid4(),
        status="submitted",
        record_revision=1,
        manager_recommendation=None,
        decided_by_id=None,
    )
    assert state.allowed_actions == []
    assert state.current_reviewer_name is None
    assert state.decided_at is None


async def test_legacy_draft_submission_and_cancellation_keep_optional_revisions(
    leave_graph, monkeypatch: pytest.MonkeyPatch
):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    request.status = "draft"
    await session.flush()
    service = HrWorkforceService(session)
    monkeypatch.setattr(
        service,
        "_validate_leave_request",
        AsyncMock(return_value=(request.days_requested, [request.start_date])),
    )
    monkeypatch.setattr(service, "_ensure_no_leave_overlap", AsyncMock())
    monkeypatch.setattr(
        service,
        "_resolve_leave_route",
        AsyncMock(return_value=("supervisor", manager.id, None, None)),
    )
    monkeypatch.setattr(service, "_notify_leave_event", AsyncMock())
    monkeypatch.setattr(service.audit, "record", AsyncMock())

    submitted = await service.decide_leave_request(
        request.id, LeaveRequestDecisionRequest(decision="submitted"), hr,
    )
    assert submitted.status == "submitted" and submitted.record_revision == 2

    submitted.status = "draft"
    cancelled = await service.decide_leave_request(
        request.id,
        LeaveRequestDecisionRequest(decision="cancelled"),
        worker,
        own_request=True,
    )
    assert cancelled.status == "cancelled" and cancelled.record_revision == 3


async def test_final_decision_still_requires_revision(leave_graph):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    with pytest.raises(AppException) as missing:
        await HrWorkforceService(session).decide_leave_request(
            request.id,
            LeaveRequestDecisionRequest(decision="rejected", notes="Synthetic rejection"),
            hr,
        )
    assert missing.value.status_code == 409
    assert missing.value.error_code == "REVISION_REQUIRED"
    assert request.status == "submitted" and request.record_revision == 1


async def test_former_and_incoming_supervisor_cannot_decide_until_route_refreshed(leave_graph):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    replacement = HrEmployee(
        id=uuid4(),
        user_id=former.id,
        employee_code=f"LM12-{uuid4().hex[:8]}",
        first_name="Synthetic",
        last_name="Replacement",
        full_name="Synthetic Replacement",
        employment_status="active",
    )
    session.add(replacement)
    await session.flush()
    employee.manager_employee_id = replacement.id
    await session.flush()
    service = HrWorkforceService(session)
    for actor in (manager, former):
        queue = await service.list_supervisor_leave_reviews(actor, offset=0, limit=25)
        assert queue.items == []
        with pytest.raises(AppException) as denied:
            await service.decide_supervisor_leave_request(
                request.id,
                SupervisorLeaveDecisionRequest(
                    decision="rejected",
                    notes="Synthetic stale route",
                    expected_revision=1,
                ),
                actor,
            )
        assert denied.value.status_code == 409
        assert denied.value.error_code == "LEAVE_ROUTE_CHANGED"
    assert request.status == "submitted" and request.record_revision == 1
    refreshed = await service.refresh_leave_route(
        request.id,
        LeaveRouteRefreshRequest(expected_revision=1),
        hr,
    )
    assert refreshed.record_revision == 2
    projection = await _leave_request_response(session, refreshed, hr)
    assert projection.current_reviewer_name == former.full_name
    assert projection.route_status == "pending_supervisor"
    assert "approve" not in projection.allowed_actions
    assert (await service.list_supervisor_leave_reviews(manager, offset=0, limit=25)).items == []
    incoming = await service.list_supervisor_leave_reviews(former, offset=0, limit=25)
    assert [row.id for row in incoming.items] == [request.id]
    result = await service.decide_supervisor_leave_request(
        request.id,
        SupervisorLeaveDecisionRequest(
            decision="rejected",
            notes="Synthetic current route",
            expected_revision=2,
        ),
        former,
    )
    assert result.route_status == "final" and result.allowed_actions == []


async def test_expired_fallback_and_unstaffed_setup_need_attention(leave_graph):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    service = HrWorkforceService(session)
    request.approval_route = "hr_fallback"
    request.fallback_reason_code = "manager_temporarily_unavailable"
    request.fallback_reason = "Synthetic temporary unavailability"
    request.fallback_recorded_by_id = hr.id
    request.fallback_recorded_at = datetime.now(UTC)
    request.fallback_until = business_today() - timedelta(days=1)
    await session.flush()
    await session.refresh(request)
    projection = await _leave_request_response(session, request, hr)
    assert projection.route_status == "refresh_required"
    assert projection.allowed_actions == ["refresh_route"]
    with pytest.raises(AppException) as expired:
        await service.decide_leave_request(
            request.id,
            LeaveRequestDecisionRequest(
                decision="rejected",
                notes="Synthetic expired route",
                expected_revision=1,
            ),
            hr,
        )
    assert expired.value.status_code == 409
    assert expired.value.error_code == "LEAVE_ROUTE_CHANGED"
    # A missing independent HR approver is a setup state, never an implicit approval.
    employee.manager_employee_id = None
    request.assigned_supervisor_user_id = None
    request.fallback_reason_code = "manager_missing"
    request.fallback_reason = "No valid direct supervisor is assigned."
    request.fallback_until = None
    await session.execute(
        update(User)
        .where(User.role.in_(roles_with_permission(PERMISSION_HR_LEAVE_APPROVE)))
        .values(is_active=False)
    )
    await session.flush()
    await session.refresh(request)
    own = await _leave_request_response(session, request, worker)
    assert own.setup_error_code == "LEAVE_APPROVER_NOT_CONFIGURED"
    assert own.route_status == "approver_not_configured"
    assert own.allowed_actions == ["cancel"]
    page, total = await service.list_leave_requests(employee_id=employee.id, needs_attention=True)
    assert total == 1 and [row.id for row in page] == [request.id]


async def test_attention_filter_applies_before_pagination_in_bounded_batches(leave_graph):
    session, hr, manager, worker, former, technical, employee, request = leave_graph
    for _ in range(102):
        session.add(
            HrLeaveRequest(
                id=uuid4(),
                employee_id=employee.id,
                leave_type_id=request.leave_type_id,
                start_date=request.start_date,
                end_date=request.end_date,
                days_requested=Decimal("1.00"),
                status="submitted",
                requested_by_id=worker.id,
                approval_route="supervisor",
                assigned_supervisor_user_id=former.id,
            )
        )
    await session.flush()
    service = HrWorkforceService(session)
    page, total = await service.list_leave_requests(
        employee_id=employee.id,
        needs_attention=True,
        offset=100,
        limit=2,
    )
    assert total == 102 and len(page) == 2
    assert request.id not in {row.id for row in page}
    expected = list(
        await session.scalars(
            select(HrLeaveRequest.id)
            .where(
                HrLeaveRequest.employee_id == employee.id,
                HrLeaveRequest.assigned_supervisor_user_id == former.id,
            )
            .order_by(HrLeaveRequest.created_at.desc(), HrLeaveRequest.id.desc())
            .offset(100)
            .limit(2)
        )
    )
    assert [row.id for row in page] == expected

    all_matches, all_total = await service.list_leave_requests(
        employee_id=employee.id,
        needs_attention=True,
    )
    assert all_total == 102 and len(all_matches) == 102


async def test_invalid_selected_dates_return_no_requestable_leave_types(leave_graph):
    session, _, _, _, _, _, employee, _ = leave_graph
    service = HrWorkforceService(session)
    rows, total = await service.list_requestable_leave_types(
        employee,
        business_today() + timedelta(days=2),
        business_today() + timedelta(days=1),
    )
    assert rows == [] and total == 0

    rows, total = await service.list_requestable_leave_types(
        employee,
        business_today().replace(month=1, day=1),
        business_today().replace(month=1, day=1) + timedelta(days=366),
    )
    assert rows == [] and total == 0
