"""Concurrency proofs for report decisions (H1), numbering (M14) and payments (H4).

Every race here is a real ``asyncio.gather`` over **separate** sessions released by a
barrier — sequential calls would pass even without the row locks, so they prove nothing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, engine
from app.models.daily_report import DailyReport
from app.models.finance import Invoice, Payment
from app.models.inventory import InventoryLocationStock, InventoryMovement
from app.models.user import User
from app.schemas.daily_reports import DailyReportUpdateRequest
from app.schemas.finance import PaymentCreateRequest
from app.services.finance_service import FinanceService
from app.services.report_service import ReportService
from app.utils.exceptions import AppException
from tests.concurrency_helpers import error_codes, race_sessions, require_database, status_counts
from tests.test_daily_reports import (
    create_test_client,
    report_payload,
    setup_project_team,
    setup_report_consumption_stock,
)
from tests.test_daily_reports import create_user as create_report_user
from tests.test_daily_reports import login_for_token as report_login
from tests.test_finance import add_invoice, create_project_and_supplier
from tests.test_finance import create_user as create_finance_user

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _submitted_report_with_stock() -> tuple[UUID, UUID, UUID, UUID]:
    """Create + submit a report that consumes 12 m3 from a location holding 20."""
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        stock = await setup_report_consumption_stock(
            client, setup["project_id"], setup["op_token"]
        )
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        submitted = await client.post(
            f"/api/v1/reports/{report['id']}/submit",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        assert submitted.status_code == 200
        manager = (
            await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {setup['manager_token']}"},
            )
        ).json()
    return (
        UUID(report["id"]),
        UUID(manager["id"]),
        UUID(stock["item_id"]),
        UUID(stock["location_id"]),
    )


async def test_double_approve_consumes_stock_once() -> None:
    await require_database()
    report_id, manager_id, item_id, location_id = await _submitted_report_with_stock()

    async def approve(session):
        actor = await session.get(User, manager_id)
        assert actor is not None
        report = await ReportService(session).approve_report(
            report_id, actor, comments="Target covered.", target_covered=True
        )
        return report.status

    results = await race_sessions(approve, approve, approve)

    assert status_counts(results) == {"approved": 1, 409: 2}
    assert error_codes(results) == ["DAILY_REPORT_NOT_SUBMITTED"] * 2

    async with AsyncSessionLocal() as session:
        movements = (
            await session.scalars(
                select(InventoryMovement).where(
                    InventoryMovement.reference_id == report_id,
                    InventoryMovement.movement_type == "consume",
                    InventoryMovement.deleted_at.is_(None),
                )
            )
        ).all()
        assert len(movements) == 1, "approval consumed material more than once"
        assert str(movements[0].quantity) == "12.000"

        stock = await session.scalar(
            select(InventoryLocationStock).where(
                InventoryLocationStock.item_id == item_id,
                InventoryLocationStock.location_id == location_id,
            )
        )
        assert stock is not None
        assert stock.on_hand_qty == Decimal("8.000")

        report = await session.get(DailyReport, report_id)
        assert report is not None
        assert report.status == "approved"


async def test_concurrent_submits_keep_distinct_report_numbers() -> None:
    """Two engineers, same project + date: numbering must not collide (M14)."""
    await require_database()
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        second_email, second_password = await create_report_user("quantity_surveyor")
        second_token = await report_login(client, second_email, second_password)
        second = (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {second_token}"})
        ).json()
        member = await client.post(
            f"/api/v1/projects/{setup['project_id']}/members",
            json={"user_id": second["id"], "role_in_project": "quantity_surveyor"},
            headers={"Authorization": f"Bearer {setup['op_token']}"},
        )
        assert member.status_code in {200, 201}

        # No supervisor update links: this race is about numbering only.
        payloads = [
            report_payload(setup["project_id"]),
            report_payload(setup["project_id"]),
        ]
        tokens = [setup["engineer_token"], second_token]
        report_ids = []
        for payload, token in zip(payloads, tokens, strict=True):
            created = await client.post(
                "/api/v1/reports",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert created.status_code == 201
            report_ids.append(UUID(created.json()["id"]))

    def submit(index: int):
        async def operation(session):
            actor_id = await session.scalar(
                select(DailyReport.engineer_id).where(DailyReport.id == report_ids[index])
            )
            actor = await session.get(User, actor_id)
            assert actor is not None
            report = await ReportService(session).submit_report(report_ids[index], actor)
            return report.report_number

        return operation

    results = await race_sessions(submit(0), submit(1))

    numbers = [result for result in results if isinstance(result, str)]
    assert len(numbers) == 2, f"expected two successful submits, got {status_counts(results)}"
    assert len(set(numbers)) == 2, f"duplicate report numbers issued: {numbers}"
    assert all(number.startswith(f"{setup['project_code']}-DR-") for number in numbers)
    assert sorted(number.rsplit("-", 1)[1] for number in numbers) == ["001", "002"]

    async with AsyncSessionLocal() as session:
        stored = [
            number
            for number in (
                await session.scalars(
                    select(DailyReport.report_number).where(DailyReport.id.in_(report_ids))
                )
            ).all()
            if number is not None
        ]
        assert sorted(stored) == sorted(numbers)


async def test_number_collision_returns_409_and_keeps_existing_numbers() -> None:
    """A legacy gap in the per-day series must surface as 409, never a raw IntegrityError.

    ``report_number`` already carries a global partial unique index, so COUNT+1 can
    collide with a pre-existing number when the series has holes.
    """
    await require_database()
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        headers = {"Authorization": f"Bearer {setup['engineer_token']}"}
        first = (
            await client.post(
                "/api/v1/reports", json=report_payload(setup["project_id"]), headers=headers
            )
        ).json()
        submitted = await client.post(f"/api/v1/reports/{first['id']}/submit", headers=headers)
        assert submitted.status_code == 200
        existing_number = submitted.json()["report_number"]

        pending = (
            await client.post(
                "/api/v1/reports", json=report_payload(setup["project_id"]), headers=headers
            )
        ).json()
        collision = (
            await client.post(
                "/api/v1/reports", json=report_payload(setup["project_id"]), headers=headers
            )
        ).json()
        engineer = (await client.get("/api/v1/auth/me", headers=headers)).json()

    # Leave a hole at -002 so the next COUNT+1 lands on the number we plant at -003.
    prefix, _, sequence = existing_number.rpartition("-")
    planted_number = f"{prefix}-{int(sequence) + 2:03d}"
    async with AsyncSessionLocal() as session:
        legacy = await session.get(DailyReport, UUID(pending["id"]))
        assert legacy is not None
        legacy.report_number = planted_number
        await session.commit()

    async with AsyncSessionLocal() as session:
        actor = await session.get(User, UUID(engineer["id"]))
        assert actor is not None
        with pytest.raises(AppException) as excinfo:
            await ReportService(session).submit_report(UUID(collision["id"]), actor)
        assert excinfo.value.status_code == 409
        assert excinfo.value.error_code == "DAILY_REPORT_NUMBER_CONFLICT"

    async with AsyncSessionLocal() as session:
        untouched = await session.get(DailyReport, UUID(first["id"]))
        assert untouched is not None
        assert untouched.report_number == existing_number
        rolled_back = await session.get(DailyReport, UUID(collision["id"]))
        assert rolled_back is not None
        assert rolled_back.report_number is None
        assert rolled_back.status == "draft"


async def _approved_invoice(total: str = "315.00") -> tuple[UUID, UUID]:
    """Seed an approved invoice for verifying the read-only finance boundary."""
    admin, _ = await create_finance_user("managing_director")
    project, supplier = await create_project_and_supplier(admin)
    invoice = await add_invoice(project, Decimal(total), status="approved", supplier_id=supplier.id)
    return invoice.id, admin.id


def _payment(amount: str) -> PaymentCreateRequest:
    return PaymentCreateRequest(
        payment_date=date.today(), amount=Decimal(amount), method="bank_transfer"
    )


async def test_concurrent_payment_attempts_are_denied_without_financial_write_permission() -> None:
    await require_database()
    invoice_id, accounts_id = await _approved_invoice("315.00")

    async def pay(session):
        actor = await session.get(User, accounts_id)
        assert actor is not None
        invoice = await FinanceService(session).create_payment(
            invoice_id, _payment("315.00"), actor
        )
        return invoice.payment_status

    results = await race_sessions(pay, pay, pay)

    assert status_counts(results) == {403: 3}
    assert error_codes(results) == ["FINANCE_WRITE_FORBIDDEN"] * 3

    async with AsyncSessionLocal() as session:
        paid = await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.invoice_id == invoice_id, Payment.deleted_at.is_(None)
            )
        )
        invoice = await session.get(Invoice, invoice_id)
        assert invoice is not None
        assert Decimal(paid or 0) == Decimal("0.00")
        assert invoice.payment_status == "unpaid"
        count = await session.scalar(
            select(func.count()).select_from(Payment).where(Payment.invoice_id == invoice_id)
        )
        assert count == 0


async def test_payment_amount_variants_are_denied_without_financial_write_permission() -> None:
    await require_database()
    invoice_id, accounts_id = await _approved_invoice("200.00")

    async with AsyncSessionLocal() as session:
        actor = await session.get(User, accounts_id)
        assert actor is not None
        service = FinanceService(session)
        for amount in ("50.00", "150.01", "150.00", "0.01"):
            with pytest.raises(AppException) as excinfo:
                await service.create_payment(invoice_id, _payment(amount), actor)
            assert excinfo.value.status_code == 403
            assert excinfo.value.error_code == "FINANCE_WRITE_FORBIDDEN"

    async with AsyncSessionLocal() as session:
        assert await session.scalar(
            select(func.count()).select_from(Payment).where(Payment.invoice_id == invoice_id)
        ) == 0


async def test_concurrent_draft_edits_from_one_revision_have_one_winner() -> None:
    await require_database()
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        headers = {"Authorization": f"Bearer {setup['engineer_token']}"}
        payload = report_payload(setup["project_id"])
        created = await client.post("/api/v1/reports", json=payload, headers=headers)
        assert created.status_code == 201
        report = created.json()
        actor = (await client.get("/api/v1/auth/me", headers=headers)).json()

    report_id = UUID(report["id"])
    actor_id = UUID(actor["id"])

    expected_revision = 1

    async def edit(session):
        user = await session.get(User, actor_id)
        assert user is not None
        updated = await ReportService(session).update_report(
            report_id,
            DailyReportUpdateRequest.model_validate(
                {**payload, "expected_revision": expected_revision, "work_completed": "Latest edit"}
            ),
            user,
        )
        return updated.revision

    results = await race_sessions(edit, edit)
    assert status_counts(results) == {2: 1, 409: 1}
    assert error_codes(results) == ["DAILY_REPORT_REVISION_CONFLICT"]

    expected_revision = 2

    async def submit(session):
        user = await session.get(User, actor_id)
        assert user is not None
        submitted = await ReportService(session).submit_report(report_id, user)
        return submitted.status

    transition = await race_sessions(edit, submit)
    observed = status_counts(transition)
    assert observed in ({"submitted": 1, 3: 1}, {"submitted": 1, 409: 1})
    async with AsyncSessionLocal() as session:
        persisted = await session.get(DailyReport, report_id)
        assert persisted is not None
        assert persisted.status == "submitted"
        assert persisted.revision == (4 if 3 in observed else 3)
