"""Regression tests for inventory reservation accounting (C4), the adjustment
floor (M5), and price masking that must not mutate ORM state (X1).

Follows the per-module harness convention used by ``tests/test_inventory.py``.
"""

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.approval import Approval
from app.models.inventory import (
    InventoryItem,
    InventoryLocationStock,
    InventoryMovement,
    MaterialRequest,
    MaterialRequestLine,
    StorageLocation,
)
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.inventory import LocationCreateRequest, MaterialQuantityCommand
from app.services.approval_service import ApprovalService
from app.services.email_service import EmailDeliveryError
from app.services.inventory_service import InventoryService
from app.tasks.email import _send_email_notification
from app.utils.exceptions import AppException
from app.utils.security import hash_password, utc_now
from tests.concurrency_helpers import SessionOperation, error_codes, race_sessions, status_counts

pytestmark = pytest.mark.asyncio

ZERO = Decimal("0")


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


async def create_user(role: str, password: str = "Start123!") -> tuple[User, str]:
    user = User(
        email=f"acct-{role}-{uuid4().hex}@example.com",
        full_name=f"{role} Accounting User",
        role=role,
        employee_code=f"ACC-{uuid4().hex[:8]}",
        phone="+97455550555",
        designation=role.replace("_", " ").title(),
        password_hash=hash_password(password),
        must_change_password=False,
    )
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(user)
        await session.commit()
        await session.refresh(user)
    return user, password


async def create_project(pm: User, engineer: User) -> Project:
    async with AsyncSessionLocal() as session:
        project = Project(
            name=f"Accounting Test {uuid4().hex[:6]}",
            code=f"ACC-{uuid4().hex[:6]}",
            location="Doha",
            description="Accounting test project",
            scope_of_work="Accounting test scope",
            status="active",
            budget_amount=Decimal("100000.00"),
            start_date=date.today(),
            target_end_date=date.today(),
            client_name="Test Client",
            contract_number=f"C-{uuid4().hex[:6]}",
            progress_percentage=Decimal("10.00"),
            created_by=pm.id,
        )
        session.add(project)
        await session.flush()
        session.add_all(
            [
                ProjectMember(
                    project_id=project.id, user_id=pm.id, role_in_project="Project Manager"
                ),
                ProjectMember(
                    project_id=project.id, user_id=engineer.id, role_in_project="Engineer"
                ),
            ]
        )
        await session.commit()
        await session.refresh(project)
        return project


@dataclass
class Fixture:
    store: User
    engineer: User
    project: Project
    location: StorageLocation
    item: InventoryItem
    request: MaterialRequest


async def seed(
    *,
    on_hand: Decimal,
    quantity: Decimal,
    status: str = "approved",
    issued: Decimal = ZERO,
    line_reserved: Decimal = ZERO,
    stock_reserved: Decimal = ZERO,
) -> Fixture:
    """Build an item, a stock row and a material request in a known state.

    ``status``/``issued``/``line_reserved`` allow legacy or mid-lifecycle states to be
    reproduced exactly, which is what the accounting invariants must tolerate.
    """
    store, _ = await create_user("store_keeper")
    engineer, _ = await create_user("civil_engineer")
    pm, _ = await create_user("project_manager")
    project = await create_project(pm, engineer)

    async with AsyncSessionLocal() as session:
        location = StorageLocation(
            name=f"Accounting Warehouse {uuid4().hex[:6]}",
            code=f"AW-{uuid4().hex[:6]}",
            location_type="warehouse",
            address="Industrial Area",
        )
        item = InventoryItem(
            name="Accounting Cement",
            item_code=f"ACEM-{uuid4().hex[:6]}",
            category="Civil",
            item_type="consumable",
            unit="Nos",
            minimum_stock=Decimal("1"),
            reorder_level=Decimal("1"),
            unit_cost=Decimal("12.50"),
        )
        session.add_all([location, item])
        await session.flush()

        stock = InventoryLocationStock(
            item_id=item.id,
            location_id=location.id,
            on_hand_qty=on_hand,
            reserved_qty=stock_reserved,
        )
        request = MaterialRequest(
            request_number=f"MR-{uuid4().hex[:10]}",
            project_id=project.id,
            requester_id=engineer.id,
            from_location_id=location.id,
            status=status,
            total_estimated_cost=Decimal("0"),
        )
        session.add_all([stock, request])
        await session.flush()

        line = MaterialRequestLine(
            request_id=request.id,
            item_id=item.id,
            quantity=quantity,
            reserved_quantity=line_reserved,
            issued_quantity=issued,
            unit_cost=Decimal("12.50"),
        )
        session.add(line)
        await session.commit()
        for obj in (location, item, request):
            await session.refresh(obj)
        return Fixture(store, engineer, project, location, item, request)


async def read_stock(item_id: UUID, location_id: UUID) -> InventoryLocationStock:
    async with AsyncSessionLocal() as session:
        stock = await session.scalar(
            select(InventoryLocationStock).where(
                InventoryLocationStock.item_id == item_id,
                InventoryLocationStock.location_id == location_id,
            )
        )
        assert stock is not None
        return stock


async def read_line(request_id: UUID) -> MaterialRequestLine:
    async with AsyncSessionLocal() as session:
        line = await session.scalar(
            select(MaterialRequestLine).where(MaterialRequestLine.request_id == request_id)
        )
        assert line is not None
        return line


async def read_unit_cost(item_id: UUID) -> Decimal | None:
    async with AsyncSessionLocal() as session:
        return await session.scalar(
            select(InventoryItem.unit_cost).where(InventoryItem.id == item_id)
        )


async def race_with_parent_lock[T, U](
    parent: Select[UUID], first: SessionOperation[T], second: SessionOperation[U]
) -> list[object]:
    """Pin the commit order and verify the contender actually waits in PostgreSQL."""
    parent_locked = asyncio.Event()
    contender_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def run_first(session: AsyncSession) -> T:
        assert await session.scalar(parent.with_for_update()) is not None
        holder_pid = await session.scalar(select(func.pg_backend_pid()))
        assert isinstance(holder_pid, int)
        parent_locked.set()
        pid = await contender_pid
        async with asyncio.timeout(10):
            while holder_pid not in (
                await session.scalar(select(func.pg_blocking_pids(pid))) or []
            ):
                await asyncio.sleep(0.01)
        return await first(session)

    async def run_second(session: AsyncSession) -> U:
        await parent_locked.wait()
        pid = await session.scalar(select(func.pg_backend_pid()))
        assert isinstance(pid, int)
        contender_pid.set_result(pid)
        return await second(session)

    return await race_sessions(run_first, run_second)


async def seed_actionable_approval(fixture: Fixture, approver: User, *, overdue: bool) -> UUID:
    now = utc_now()
    async with AsyncSessionLocal() as session:
        approval = Approval(
            request_type="material_request",
            request_id=fixture.request.id,
            project_id=fixture.project.id,
            submitter_id=fixture.engineer.id,
            approver_id=approver.id,
            escalation_user_id=approver.id,
            title="Stores request",
            status="pending",
            submitted_at=now - timedelta(days=3) if overdue else now,
            due_at=now - timedelta(days=2) if overdue else now + timedelta(days=2),
        )
        session.add(approval)
        await session.commit()
        return approval.id


async def assert_cancelled_without_stock_effect(fixture: Fixture, *, decisions: int) -> None:
    request_id = fixture.request.id
    async with AsyncSessionLocal() as session:
        request = await session.get_one(MaterialRequest, request_id)
        assert request.status == "cancelled"
        assert request.revision == fixture.request.revision + decisions
        assert not await session.scalar(
            select(InventoryMovement.id).where(InventoryMovement.item_id == fixture.item.id)
        )
    stock = await read_stock(fixture.item.id, fixture.location.id)
    line = await read_line(request_id)
    assert (stock.on_hand_qty, stock.reserved_qty) == (Decimal("10"), Decimal("2"))
    assert (line.reserved_quantity, line.issued_quantity) == (ZERO, ZERO)


@pytest.mark.parametrize("cancel_first", [True, False], ids=["cancel-first", "approve-first"])
async def test_cancel_and_approval_serialize(cancel_first: bool) -> None:
    await skip_if_database_unavailable()
    fixture = await seed(
        on_hand=Decimal("10"),
        quantity=Decimal("4"),
        status="requested",
        stock_reserved=Decimal("2"),
    )
    approver, _ = await create_user("operation_manager")
    approval_id = await seed_actionable_approval(fixture, approver, overdue=False)
    request_id = fixture.request.id

    async def cancel(session: AsyncSession) -> str:
        return (await InventoryService(session).cancel_request(request_id, fixture.engineer)).status

    async def approve(session: AsyncSession) -> str:
        return (await ApprovalService(session).approve(approval_id, approver, None)).status

    parent = select(MaterialRequest.id).where(MaterialRequest.id == request_id)
    operations = (cancel, approve) if cancel_first else (approve, cancel)
    results = await race_with_parent_lock(parent, *operations)
    if cancel_first:
        assert results[0] == "cancelled", results
        assert status_counts(results) == {"cancelled": 1, 409: 1}, results
        assert error_codes(results) == ["APPROVAL_FINAL"]
    else:
        assert results == ["approved", "cancelled"], results

    async with AsyncSessionLocal() as session:
        approval = await session.get_one(Approval, approval_id)
        assert approval.status == ("cancelled" if cancel_first else "approved")
        assert approval.decided_at is not None
        titles = await session.scalars(
            select(Notification.title).where(Notification.reference_id == approval_id)
        )
        assert titles.all() == ([] if cancel_first else ["Approval completed"])
    await assert_cancelled_without_stock_effect(fixture, decisions=1 if cancel_first else 2)


@pytest.mark.parametrize("cancel_first", [True, False], ids=["cancel-first", "reminder-first"])
async def test_cancel_and_overdue_reminder_serialize(cancel_first: bool) -> None:
    await skip_if_database_unavailable()
    fixture = await seed(
        on_hand=Decimal("10"),
        quantity=Decimal("4"),
        status="requested",
        stock_reserved=Decimal("2"),
    )
    approver, _ = await create_user("operation_manager")
    approval_id = await seed_actionable_approval(fixture, approver, overdue=True)
    request_id = fixture.request.id

    async def cancel(session: AsyncSession) -> str:
        return (await InventoryService(session).cancel_request(request_id, fixture.engineer)).status

    async def remind(session: AsyncSession) -> str:
        await ApprovalService(session).send_reminders_and_escalations()
        return "processed"

    parent = select(MaterialRequest.id).where(MaterialRequest.id == request_id)
    operations = (cancel, remind) if cancel_first else (remind, cancel)
    results = await race_with_parent_lock(parent, *operations)
    assert results == (["cancelled", "processed"] if cancel_first else ["processed", "cancelled"])

    async with AsyncSessionLocal() as session:
        approval = await session.get_one(Approval, approval_id)
        assert approval.status == "cancelled" and approval.decided_at is not None
        if cancel_first:
            assert approval.reminded_at is None and approval.escalated_at is None
        else:
            assert approval.reminded_at is not None and approval.escalated_at is not None
            assert approval.reminded_at <= approval.decided_at
            assert approval.escalated_at <= approval.decided_at
        titles = await session.scalars(
            select(Notification.title).where(Notification.reference_id == approval_id)
        )
        assert sorted(titles) == (
            [] if cancel_first else ["Approval escalated", "Approval reminder"]
        )
    await assert_cancelled_without_stock_effect(fixture, decisions=1)


async def test_cancelled_material_approval_suppresses_queued_and_retried_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    fixture = await seed(on_hand=Decimal("10"), quantity=Decimal("4"), status="requested")
    approver, _ = await create_user("operation_manager")
    approval_id = await seed_actionable_approval(fixture, approver, overdue=True)
    monkeypatch.setattr("app.tasks.email.send_email_notification.delay", lambda _id: None)
    attempts: list[str] = []

    def reject_delivery(self: object, *, recipients: list[str], subject: str, body: str) -> int:
        assert recipients == [approver.email]
        attempts.append(subject)
        return 0

    monkeypatch.setattr("app.tasks.email.EmailService.send", reject_delivery)
    async with AsyncSessionLocal() as session:
        await ApprovalService(session).send_reminders_and_escalations()
        notifications = await session.scalars(
            select(Notification).where(Notification.reference_id == approval_id)
        )
        deliveries = {notification.title: str(notification.id) for notification in notifications}
    assert deliveries.keys() == {"Approval reminder", "Approval escalated"}

    with pytest.raises(EmailDeliveryError):
        await _send_email_notification(deliveries["Approval reminder"])
    assert attempts == ["Approval reminder"]
    async with AsyncSessionLocal() as session:
        await InventoryService(session).cancel_request(fixture.request.id, fixture.engineer)

    for notification_id in deliveries.values():
        assert await _send_email_notification(notification_id) == "notification email skipped"
    assert attempts == ["Approval reminder"]
    async with AsyncSessionLocal() as session:
        email_statuses = await session.scalars(
            select(Notification.email_status).where(Notification.reference_id == approval_id)
        )
        assert email_statuses.all() == ["skipped", "skipped"]


async def test_cancelled_request_cannot_be_revived_by_an_open_approval() -> None:
    await skip_if_database_unavailable()
    fixture = await seed(on_hand=Decimal("10"), quantity=Decimal("4"), status="requested")
    approver, _ = await create_user("operation_manager")
    async with AsyncSessionLocal() as session:
        approval = Approval(
            request_type="material_request",
            request_id=fixture.request.id,
            project_id=fixture.project.id,
            submitter_id=fixture.engineer.id,
            approver_id=approver.id,
            escalation_user_id=approver.id,
            title="Stores request",
            status="delegated",
            submitted_at=utc_now(),
            due_at=utc_now() - timedelta(days=2),
        )
        session.add(approval)
        await session.commit()
        approval_id = approval.id

    async with AsyncSessionLocal() as session:
        service = InventoryService(session)
        assert (
            await service.cancel_request(fixture.request.id, fixture.engineer)
        ).status == "cancelled"
        assert (
            await service.cancel_request(fixture.request.id, fixture.engineer)
        ).status == "cancelled"
    async with AsyncSessionLocal() as session:
        cancelled_approval = await session.get(Approval, approval_id)
        assert cancelled_approval is not None and cancelled_approval.status == "cancelled"
        with pytest.raises(AppException, match="Approval is already final"):
            await ApprovalService(session).approve(approval_id, approver, None)
        await session.rollback()
        await ApprovalService(session).send_reminders_and_escalations()
        await session.refresh(cancelled_approval)
        assert cancelled_approval.status == "cancelled"
        assert cancelled_approval.reminded_at is None and cancelled_approval.escalated_at is None


async def test_selected_quantities_preserve_reservation_balances_and_replay() -> None:
    await skip_if_database_unavailable()
    fixture = await seed(on_hand=Decimal("12"), quantity=Decimal("10"))
    line = await read_line(fixture.request.id)
    request_id = fixture.request.id
    keys = [str(uuid4()) for _ in range(4)]
    steps: list[tuple[Literal["reserve", "issue"], str]] = [
        ("reserve", "4"),
        ("issue", "3"),
        ("reserve", "6"),
        ("issue", "7"),
    ]
    first = None
    for revision, ((action, quantity), key) in enumerate(zip(steps, keys, strict=True), start=1):
        command = MaterialQuantityCommand.model_validate(
            {
                "expected_revision": revision,
                "lines": [{"line_id": line.id, "quantity": quantity}],
            }
        )
        async with AsyncSessionLocal() as session:
            result = await InventoryService(session).fulfill_quantities(
                request_id,
                fixture.store,
                command,
                action=action,
                key=key,
            )
        assert result.revision == revision + 1
        if revision == 1:
            first = result
        if revision == 4:
            assert result.status == "issued"
            assert result.lines[0].issued_quantity == Decimal("10")
            assert result.lines[0].reserved_quantity == 0

    command = MaterialQuantityCommand.model_validate(
        {
            "expected_revision": 1,
            "lines": [{"line_id": line.id, "quantity": "4.000"}],
        }
    )
    async with AsyncSessionLocal() as session:
        replay = await InventoryService(session).fulfill_quantities(
            request_id,
            fixture.store,
            command,
            action="reserve",
            key=keys[0],
        )
        assert replay == first
    command.lines[0].quantity = Decimal("5")
    async with AsyncSessionLocal() as session:
        with pytest.raises(AppException, match="used for different quantities"):
            await InventoryService(session).fulfill_quantities(
                request_id,
                fixture.store,
                command,
                action="reserve",
                key=keys[0],
            )
    balance = await read_stock(fixture.item.id, fixture.location.id)
    assert balance.on_hand_qty == Decimal("2")
    assert balance.reserved_qty == 0


async def test_issue_consumes_the_line_reservation() -> None:
    """C4: after issuing, reserved_quantity must mean 'reserved but not yet issued'."""
    await skip_if_database_unavailable()
    fx = await seed(on_hand=Decimal("5"), quantity=Decimal("5"))

    async with AsyncSessionLocal() as session:
        await InventoryService(session).reserve_request(fx.request.id, fx.store)

    stock = await read_stock(fx.item.id, fx.location.id)
    line = await read_line(fx.request.id)
    assert (stock.on_hand_qty, stock.reserved_qty) == (Decimal("5"), Decimal("5"))
    assert (line.reserved_quantity, line.issued_quantity) == (Decimal("5"), ZERO)

    async with AsyncSessionLocal() as session:
        await InventoryService(session).issue_request(fx.request.id, fx.store)

    stock = await read_stock(fx.item.id, fx.location.id)
    line = await read_line(fx.request.id)
    assert (stock.on_hand_qty, stock.reserved_qty) == (ZERO, ZERO)
    assert line.issued_quantity == Decimal("5")
    assert line.reserved_quantity == ZERO, "issuing must consume the line reservation"


async def test_concurrent_issue_cannot_over_issue() -> None:
    """C4: a real gather race — exactly one issue wins, stock is consumed once."""
    await skip_if_database_unavailable()
    fx = await seed(on_hand=Decimal("5"), quantity=Decimal("5"))

    async with AsyncSessionLocal() as session:
        await InventoryService(session).reserve_request(fx.request.id, fx.store)

    async def issue(session: AsyncSession) -> int:
        try:
            await InventoryService(session).issue_request(fx.request.id, fx.store)
            return 200
        except AppException as exc:
            return exc.status_code

    results = await race_sessions(*([issue] * 5))
    assert status_counts(results) == {200: 1, 409: 4}, results

    stock = await read_stock(fx.item.id, fx.location.id)
    line = await read_line(fx.request.id)
    assert (stock.on_hand_qty, stock.reserved_qty) == (ZERO, ZERO)
    assert line.issued_quantity == Decimal("5")
    assert line.reserved_quantity == ZERO


async def test_issue_cannot_consume_more_than_physically_on_hand() -> None:
    await skip_if_database_unavailable()
    fx = await seed(
        on_hand=Decimal("2"),
        quantity=Decimal("5"),
        status="reserved",
        line_reserved=Decimal("5"),
        stock_reserved=Decimal("5"),
    )

    async with AsyncSessionLocal() as session:
        request = await InventoryService(session).issue_request(fx.request.id, fx.store)
        assert request.status == "partially_issued"

    stock = await read_stock(fx.item.id, fx.location.id)
    line = await read_line(fx.request.id)
    assert (stock.on_hand_qty, stock.reserved_qty) == (Decimal("2"), Decimal("5"))
    assert (line.issued_quantity, line.reserved_quantity) == (ZERO, Decimal("5"))


async def test_reserve_only_covers_the_outstanding_quantity() -> None:
    """C4: quantity - reserved - issued, so an already-issued part is never re-reserved."""
    await skip_if_database_unavailable()
    fx = await seed(
        on_hand=Decimal("5"),
        quantity=Decimal("5"),
        status="approved",
        issued=Decimal("3"),
        line_reserved=ZERO,
        stock_reserved=ZERO,
    )

    async with AsyncSessionLocal() as session:
        await InventoryService(session).reserve_request(fx.request.id, fx.store)

    stock = await read_stock(fx.item.id, fx.location.id)
    line = await read_line(fx.request.id)
    assert line.reserved_quantity == Decimal("2"), "must reserve only the outstanding 2 of 5"
    assert stock.reserved_qty == Decimal("2")


async def test_cancel_after_partial_issue_releases_only_the_remainder() -> None:
    """C4: cancelling a partially issued request releases the remainder, not the full line."""
    await skip_if_database_unavailable()
    fx = await seed(
        on_hand=Decimal("2"),
        quantity=Decimal("5"),
        status="partially_issued",
        issued=Decimal("3"),
        line_reserved=Decimal("2"),
        stock_reserved=Decimal("2"),
    )

    async with AsyncSessionLocal() as session:
        await InventoryService(session).cancel_request(fx.request.id, fx.store)

    stock = await read_stock(fx.item.id, fx.location.id)
    line = await read_line(fx.request.id)
    assert stock.reserved_qty == ZERO
    assert stock.on_hand_qty == Decimal("2"), "already-issued stock must not be returned"
    assert line.reserved_quantity == ZERO
    assert line.issued_quantity == Decimal("3")


async def test_cancel_preserves_other_reservations_when_legacy_line_is_overstated() -> None:
    await skip_if_database_unavailable()
    fx = await seed(
        on_hand=Decimal("5"),
        quantity=Decimal("5"),
        status="partially_issued",
        issued=Decimal("3"),
        line_reserved=Decimal("5"),
        stock_reserved=Decimal("5"),
    )

    async with AsyncSessionLocal() as session:
        await InventoryService(session).cancel_request(fx.request.id, fx.store)

    stock = await read_stock(fx.item.id, fx.location.id)
    assert stock.reserved_qty == Decimal("3"), "the other request's reservation must remain"


async def test_concurrent_cancel_releases_the_remainder_exactly_once() -> None:
    """Concurrent cancellation retries succeed with one stock release."""
    await skip_if_database_unavailable()
    fx = await seed(
        on_hand=Decimal("2"),
        quantity=Decimal("5"),
        status="partially_issued",
        issued=Decimal("3"),
        line_reserved=Decimal("2"),
        stock_reserved=Decimal("2"),
    )

    async def cancel(session: AsyncSession) -> int:
        try:
            await InventoryService(session).cancel_request(fx.request.id, fx.store)
            return 200
        except AppException as exc:
            return exc.status_code

    results = await race_sessions(*([cancel] * 5))
    assert status_counts(results) == {200: 5}, results

    stock = await read_stock(fx.item.id, fx.location.id)
    line = await read_line(fx.request.id)
    assert stock.reserved_qty == ZERO, "the remainder must be released exactly once"
    assert stock.on_hand_qty == Decimal("2"), "already-issued stock must not be returned"
    assert line.reserved_quantity == ZERO
    assert line.issued_quantity == Decimal("3")


async def test_negative_adjustment_cannot_consume_reserved_stock() -> None:
    """M5: an adjustment may not push on_hand below reserved."""
    await skip_if_database_unavailable()
    fx = await seed(
        on_hand=Decimal("5"),
        quantity=Decimal("1"),
        stock_reserved=Decimal("3"),
    )
    async with create_test_client() as client:
        token = await login_for_token(client, fx.store, "Start123!")
        response = await client.post(
            "/api/v1/inventory/movements",
            json={
                "item_id": str(fx.item.id),
                "movement_type": "adjustment",
                "quantity": "-3",
                "to_location_id": str(fx.location.id),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 409
    assert response.json()["error_code"] == "INSUFFICIENT_STOCK"

    stock = await read_stock(fx.item.id, fx.location.id)
    assert (stock.on_hand_qty, stock.reserved_qty) == (Decimal("5"), Decimal("3"))


async def test_negative_adjustment_down_to_reserved_succeeds() -> None:
    """M5: the floor is reserved_qty, not zero — shrinking to exactly reserved is allowed."""
    await skip_if_database_unavailable()
    fx = await seed(
        on_hand=Decimal("5"),
        quantity=Decimal("1"),
        stock_reserved=Decimal("3"),
    )
    payload = {
        "item_id": str(fx.item.id),
        "movement_type": "adjustment",
        "quantity": "-2",
        "to_location_id": str(fx.location.id),
    }
    async with create_test_client() as client:
        token = await login_for_token(client, fx.store, "Start123!")
        headers = {"Authorization": f"Bearer {token}"}
        invalid = await client.post(
            "/api/v1/inventory/movements",
            json={**payload, "movement_type": "receive"},
            headers=headers,
        )
        assert invalid.status_code == 422
        response = await client.post("/api/v1/inventory/movements", json=payload, headers=headers)
        assert response.status_code == 201

    stock = await read_stock(fx.item.id, fx.location.id)
    assert (stock.on_hand_qty, stock.reserved_qty) == (Decimal("3"), Decimal("3"))


async def test_price_masking_never_wipes_persisted_unit_cost() -> None:
    """X1: reading items in a session that later commits must not null out prices."""
    await skip_if_database_unavailable()
    fx = await seed(on_hand=Decimal("5"), quantity=Decimal("1"))
    assert await read_unit_cost(fx.item.id) == Decimal("12.50")

    async with AsyncSessionLocal() as session:
        service = InventoryService(session)
        # A non-price role reads the catalogue, then the same session performs a write.
        listed = await service.list_items()
        assert any(candidate.id == fx.item.id for candidate in listed)
        fetched = await service.get_item(fx.item.id)
        assert fetched.unit_cost == Decimal("12.50"), "the service must not mutate prices"
        await service.create_location(
            LocationCreateRequest(
                name=f"Post-read Yard {uuid4().hex[:6]}",
                code=f"PY-{uuid4().hex[:6]}",
                location_type="warehouse",
            ),
            fx.store,
        )

    assert await read_unit_cost(fx.item.id) == Decimal("12.50"), (
        "a read followed by a commit in the same session wiped unit_cost"
    )


def create_test_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver"
    )


async def login_for_token(client: httpx.AsyncClient, user: User, password: str) -> str:
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": password}
    )
    challenge = login.json()
    verify = await client.post(
        "/api/v1/auth/verify-otp",
        json={
            "challenge_id": challenge["challenge_id"],
            "otp": challenge.get("dev_otp") or "123456",
        },
    )
    return str(verify.json()["access_token"])


async def test_item_responses_mask_price_by_role() -> None:
    """X1: masking belongs to the response, and the database keeps the real price."""
    await skip_if_database_unavailable()
    fx = await seed(on_hand=Decimal("5"), quantity=Decimal("1"))
    store, store_password = await create_user("store_keeper")
    admin, admin_password = await create_user("admin")

    async with create_test_client() as client:
        store_token = await login_for_token(client, store, store_password)
        admin_token = await login_for_token(client, admin, admin_password)

        masked = await client.get(
            "/api/v1/inventory/items", headers={"Authorization": f"Bearer {store_token}"}
        )
        assert masked.status_code == 200
        row = next(item for item in masked.json() if item["id"] == str(fx.item.id))
        assert row["unit_cost"] is None

        visible = await client.get(
            f"/api/v1/inventory/items/{fx.item.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert visible.status_code == 200
        assert visible.json()["unit_cost"] == "12.50"

        masked_detail = await client.get(
            f"/api/v1/inventory/items/{fx.item.id}",
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert masked_detail.status_code == 200
        assert masked_detail.json()["unit_cost"] is None

    assert await read_unit_cost(fx.item.id) == Decimal("12.50")
