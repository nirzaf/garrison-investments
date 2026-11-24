import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, check_database, engine
from app.models.inventory import (
    InventoryItem,
    InventoryLocationStock,
    MaterialRequest,
    MaterialRequestLine,
    StorageLocation,
)
from app.models.project import Project
from scripts.report_inventory_reservation_drift import report_drift
from scripts.report_legacy_site_workflows import report as report_legacy_site_workflows

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def inventory_ids() -> AsyncIterator[tuple[UUID, UUID, UUID]]:
    await engine.dispose()
    if not await check_database():
        pytest.skip("database is not available")

    code = uuid4().hex[:10]
    project = Project(
        id=uuid4(),
        name="Reservation report project",
        code=f"IR-{code}",
        scope_of_work="Reservation report test",
        target_end_date=date.today(),
    )
    item = InventoryItem(
        id=uuid4(),
        name="Reservation report item",
        category="Civil",
        item_type="consumable",
        unit="Nos",
    )
    location = StorageLocation(
        id=uuid4(),
        name="Reservation report warehouse",
        code=f"IR-{code}",
        location_type="warehouse",
    )
    async with AsyncSessionLocal.begin() as session:
        session.add_all([project, item, location])
    try:
        yield project.id, item.id, location.id
    finally:
        async with AsyncSessionLocal.begin() as session:
            await session.execute(delete(Project).where(Project.id == project.id))
            await session.execute(delete(StorageLocation).where(StorageLocation.id == location.id))
            await session.execute(delete(InventoryItem).where(InventoryItem.id == item.id))
        await engine.dispose()


async def reserve(
    session: AsyncSession,
    project_id: UUID,
    item_id: UUID,
    location_id: UUID | None,
    reserved: int,
    *,
    issued: int = 0,
    status: str = "partially_reserved",
) -> MaterialRequestLine:
    request = MaterialRequest(
        id=uuid4(),
        request_number=f"IR-{uuid4().hex[:10]}",
        project_id=project_id,
        from_location_id=location_id,
        status=status,
    )
    session.add(request)
    await session.flush()
    line = MaterialRequestLine(
        id=uuid4(),
        request_id=request.id,
        item_id=item_id,
        quantity=Decimal(10),
        reserved_quantity=Decimal(reserved),
        issued_quantity=Decimal(issued),
    )
    session.add(line)
    return line


@pytest.mark.parametrize("stock_state", ["missing", "deleted", "no_source", "active"])
async def test_reservation_report_checks_active_stock(
    inventory_ids: tuple[UUID, UUID, UUID],
    capsys: pytest.CaptureFixture[str],
    stock_state: str,
) -> None:
    project_id, item_id, location_id = inventory_ids
    source_id = None if stock_state == "no_source" else location_id
    async with AsyncSessionLocal.begin() as session:
        if stock_state in {"active", "deleted", "no_source"}:
            session.add(
                InventoryLocationStock(
                    item_id=item_id,
                    location_id=location_id,
                    on_hand_qty=Decimal(20),
                    reserved_qty=Decimal(0 if stock_state == "no_source" else 2),
                    deleted_at=datetime.now(UTC) if stock_state == "deleted" else None,
                )
            )
        line = await reserve(session, project_id, item_id, source_id, 2)

    await report_drift()
    records = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
    matches = [row for row in records if row.get("line_id") == str(line.id)]
    if stock_state == "active":
        assert matches == []
    else:
        assert matches == [
            {
                "finding": "open_reservation_without_stock",
                "request_id": str(line.request_id),
                "line_id": str(line.id),
                "item_id": str(item_id),
                "location_id": str(source_id) if source_id is not None else None,
                "reserved_quantity": "2.000",
                "remaining_quantity": "10.000",
            }
        ]


async def test_reservation_report_checks_each_lines_remaining_quantity(
    inventory_ids: tuple[UUID, UUID, UUID], capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, item_id, location_id = inventory_ids
    async with AsyncSessionLocal.begin() as session:
        session.add(
            InventoryLocationStock(
                item_id=item_id,
                location_id=location_id,
                on_hand_qty=Decimal(20),
                reserved_qty=Decimal(8),
            )
        )
        excess = await reserve(
            session, project_id, item_id, location_id, 7, issued=6, status="partially_issued"
        )
        slack = await reserve(session, project_id, item_id, location_id, 1)

    await report_drift()
    records = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
    matches = [row for row in records if row.get("item_id") == str(item_id)]
    # Both reservations total 8 while remaining demand totals 14. The balanced stock
    # and aggregate remaining demand cannot explain away the first line's excess.
    assert matches == [
        {
            "finding": "open_reservation_over_remaining",
            "request_id": str(excess.request_id),
            "line_id": str(excess.id),
            "item_id": str(item_id),
            "location_id": str(location_id),
            "reserved_quantity": "7.000",
            "remaining_quantity": "4.000",
        }
    ]
    async with AsyncSessionLocal() as session:
        stored_excess = await session.get(MaterialRequestLine, excess.id)
        stored_slack = await session.get(MaterialRequestLine, slack.id)
        assert stored_excess is not None and stored_excess.reserved_quantity == Decimal(7)
        assert stored_slack is not None and stored_slack.reserved_quantity == Decimal(1)


async def test_legacy_site_report_preserves_request_accounting(
    inventory_ids: tuple[UUID, UUID, UUID],
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_id, item_id, location_id = inventory_ids
    async with AsyncSessionLocal.begin() as session:
        line = await reserve(session, project_id, item_id, location_id, 3, issued=2)
        line_id, request_id = line.id, line.request_id

    statement = select(
        MaterialRequestLine.quantity,
        MaterialRequestLine.reserved_quantity,
        MaterialRequestLine.issued_quantity,
    ).where(MaterialRequestLine.id == line_id)
    async with AsyncSessionLocal() as session:
        before = (await session.execute(statement)).one()
    await report_legacy_site_workflows()
    rows = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
    finding = next(row for row in rows if row["id"] == str(request_id))
    assert finding["disposition"] == "requires_reservation_release"
    assert Decimal(finding["issued_quantity"]) == Decimal(2)
    async with AsyncSessionLocal() as session:
        assert (await session.execute(statement)).one() == before
