"""Batch 7 §7.1.2 — the reservation repair migration must restore derived balances.

C4 left ``reserved_quantity`` holding the full line quantity even after part of it
was issued, and left reservations behind on issued/cancelled requests. The repair
recomputes those derived columns and only then validates the stock balance checks.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.database import AsyncSessionLocal, check_database, engine
from app.models.inventory import (
    InventoryItem,
    InventoryLocationStock,
    InventoryMovement,
    MaterialRequest,
    MaterialRequestLine,
    StorageLocation,
)
from app.models.project import Project
from app.models.user import User
from app.repositories.user_repository import UserRepository
from tests.password_fixtures import hash_fixture_password

pytestmark = pytest.mark.asyncio

TABLE = "inventory_location_stock"
ON_HAND_CHECK = "ck_inventory_location_stock_on_hand_nonnegative"
RESERVED_CHECK = "ck_inventory_location_stock_reserved_nonnegative"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "202605300003_repair_inventory_reservations.py"
)


def load_migration() -> ModuleType:
    """Alembic version files are loaded by path, not imported as a package."""
    spec = spec_from_file_location("repair_inventory_reservations", MIGRATION_PATH)
    assert spec and spec.loader, f"{MIGRATION_PATH.name} has not been written yet"
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class LegacyDrift:
    stock_id: UUID
    negative_id: UUID
    lines: dict[str, UUID]


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


async def seed_legacy_drift() -> LegacyDrift:
    """Recreate the pre-repair state, including balances the guards now forbid."""
    suffix = uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        actor = User(
            email=f"repair-{suffix}@example.com",
            full_name="Repair Site Supervisor",
            role="site_supervisor",
            employee_code=f"REP-{suffix}",
            phone="+97455550555",
            designation="Site Supervisor",
            password_hash=hash_fixture_password("Start123!"),
            must_change_password=False,
        )
        await UserRepository(session).add(actor)
        project = Project(
            name=f"Repair Project {suffix}",
            code=f"REP-{suffix}",
            location="Doha",
            description="Reservation repair project",
            scope_of_work="Reservation repair scope",
            status="active",
            budget_amount=Decimal("100000.00"),
            start_date=date.today(),
            target_end_date=date.today(),
            client_name="Repair Client",
            contract_number=f"C-{suffix}",
            progress_percentage=Decimal("10.00"),
            created_by=actor.id,
        )
        item = InventoryItem(
            name=f"Repair Item {suffix}",
            item_code=f"ITEM-{suffix}",
            category="Civil",
            item_type="material",
            unit="Nos",
        )
        location = StorageLocation(
            name=f"Repair Location {suffix}",
            code=f"LOC-{suffix}",
            location_type="warehouse",
        )
        # uq_inventory_stock_item_location forbids a second row for the same pair.
        spare = StorageLocation(
            name=f"Repair Spare {suffix}",
            code=f"SPARE-{suffix}",
            location_type="warehouse",
        )
        session.add_all([project, item, location, spare])
        await session.flush()

        # Historical rows predate the balance guards, so drop them to seed the damage.
        await session.execute(
            text(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {ON_HAND_CHECK}")
        )
        await session.execute(
            text(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {RESERVED_CHECK}")
        )

        stock = InventoryLocationStock(
            item_id=item.id,
            location_id=location.id,
            on_hand_qty=Decimal("100.000"),
            # Drifted: 50 (partially issued) + 10 (cancelled) + 15 (issued) instead of 30 + 5.
            reserved_qty=Decimal("75.000"),
        )
        negative = InventoryLocationStock(
            item_id=item.id,
            location_id=spare.id,
            on_hand_qty=Decimal("10.000"),
            reserved_qty=Decimal("-4.000"),
        )
        session.add_all([stock, negative])
        await session.flush()
        stock_id, negative_id = stock.id, negative.id

        requests: dict[str, UUID] = {}
        for status, quantity, issued, reserved in (
            ("partially_issued", "50.000", "20.000", "50.000"),
            ("cancelled", "10.000", "0.000", "10.000"),
            ("issued", "15.000", "15.000", "15.000"),
        ):
            request = MaterialRequest(
                request_number=f"MR-{status}-{suffix}",
                project_id=project.id,
                requester_id=actor.id,
                from_location_id=location.id,
                status=status,
            )
            session.add(request)
            await session.flush()
            line = MaterialRequestLine(
                request_id=request.id,
                item_id=item.id,
                quantity=Decimal(quantity),
                issued_quantity=Decimal(issued),
                reserved_quantity=Decimal(reserved),
            )
            session.add(line)
            await session.flush()
            requests[status] = line.id

        # A manual reserve is a real claim on stock that no request line describes.
        session.add(
            InventoryMovement(
                item_id=item.id,
                movement_type="reserve",
                quantity=Decimal("5.000"),
                from_location_id=location.id,
                project_id=project.id,
                handled_by=actor.id,
            )
        )
        # A negative reserve is how the pool went below zero historically: the recomputed
        # sum itself is negative here, so only the outer clamp can bring it back to zero.
        session.add(
            InventoryMovement(
                item_id=item.id,
                movement_type="reserve",
                quantity=Decimal("-4.000"),
                from_location_id=spare.id,
                project_id=project.id,
                handled_by=actor.id,
            )
        )
        await session.commit()

    return LegacyDrift(stock_id=stock_id, negative_id=negative_id, lines=requests)


async def restore_not_valid_checks() -> None:
    """Leave the schema exactly as 202605300002 does: guards present, unvalidated."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                f"ALTER TABLE {TABLE} ADD CONSTRAINT {ON_HAND_CHECK} "
                "CHECK (on_hand_qty >= 0) NOT VALID"
            )
        )
        await session.execute(
            text(
                f"ALTER TABLE {TABLE} ADD CONSTRAINT {RESERVED_CHECK} "
                "CHECK (reserved_qty >= 0) NOT VALID"
            )
        )
        await session.commit()


async def test_repair_recomputes_reservations_and_keeps_manual_claims() -> None:
    """The repair floors issued/cancelled lines and preserves non-request reserves."""
    await skip_if_database_unavailable()
    migration = load_migration()
    seeded = await seed_legacy_drift()
    try:
        await restore_not_valid_checks()
        async with AsyncSessionLocal() as session:
            for statement in migration.REPAIR_STATEMENTS:
                await session.execute(text(statement))
            await session.commit()

            lines: dict[UUID, Decimal] = dict(
                (
                    await session.execute(
                        text(
                            "SELECT id, reserved_quantity FROM material_request_lines "
                            "WHERE id = ANY(:ids)"
                        ),
                        {"ids": list(seeded.lines.values())},
                    )
                ).all()
            )
            assert lines[seeded.lines["partially_issued"]] == Decimal("30.000"), (
                "a partially issued line must reserve only the unissued remainder"
            )
            assert lines[seeded.lines["cancelled"]] == Decimal("0.000"), (
                "a cancelled request must hold no reservation"
            )
            assert lines[seeded.lines["issued"]] == Decimal("0.000"), (
                "a fully issued request must hold no reservation"
            )

            balances: dict[UUID, Decimal] = dict(
                (
                    await session.execute(
                        text(
                            "SELECT id, reserved_qty FROM inventory_location_stock "
                            "WHERE id = ANY(:ids)"
                        ),
                        {"ids": [seeded.stock_id, seeded.negative_id]},
                    )
                ).all()
            )
            assert balances[seeded.stock_id] == Decimal("35.000"), (
                "stock must reserve the 30 outstanding request units plus the 5 manual units"
            )
            assert balances[seeded.negative_id] == Decimal("0.000"), (
                "a negative reservation pool must be clamped to zero"
            )
    finally:
        async with AsyncSessionLocal() as session:
            for statement in migration.VALIDATE_STATEMENTS:
                await session.execute(text(statement))
            await session.commit()


async def test_stock_balance_checks_are_validated_after_repair() -> None:
    """§7.1.2 requires enforced checks, not guards that only cover new writes."""
    await skip_if_database_unavailable()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT conname, convalidated FROM pg_constraint "
                    "WHERE conrelid = CAST(:table AS regclass) AND contype = 'c'"
                ),
                {"table": TABLE},
            )
        ).all()
    validated: dict[str, bool] = dict(rows)
    for name in (ON_HAND_CHECK, RESERVED_CHECK):
        assert name in validated, f"{name} is missing from {TABLE}"
        assert validated[name], f"{name} is still NOT VALID; historical rows were never reconciled"
