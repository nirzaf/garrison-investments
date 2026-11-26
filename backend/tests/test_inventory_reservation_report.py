import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, check_database, engine
from app.models.document import Document, DocumentVersion
from app.models.hr import HrAttendanceEntry, HrEmployee
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


async def test_legacy_report_flags_unknown_material_valuation_without_mutating_it(
    inventory_ids: tuple[UUID, UUID, UUID], capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, _, location_id = inventory_ids
    request = MaterialRequest(
        id=uuid4(),
        request_number=f"UV-{uuid4().hex[:10]}",
        project_id=project_id,
        from_location_id=location_id,
        status="requested",
        total_estimated_cost=Decimal("0"),
    )
    async with AsyncSessionLocal.begin() as session:
        session.add_all(
            [
                request,
                MaterialRequestLine(
                    request_id=request.id,
                    item_id=inventory_ids[1],
                    quantity=Decimal("1"),
                    unit_cost=None,
                ),
            ]
        )

    await report_legacy_site_workflows()
    records = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
    finding = next(
        row
        for row in records
        if row.get("finding") == "incomplete_material_valuation"
        and row.get("id") == str(request.id)
    )
    assert finding["approval_stages"] == []
    assert finding["disposition"] == "valuation_review_required"
    async with AsyncSessionLocal() as session:
        stored = await session.get(MaterialRequest, request.id)
        assert stored is not None
        assert stored.total_estimated_cost == Decimal("0")
        assert stored.status == "requested"


async def test_legacy_report_flags_unclassified_document_version_under_operational_parent(
    inventory_ids: tuple[UUID, UUID, UUID], capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, _, _ = inventory_ids
    document_id, version_id = uuid4(), uuid4()
    async with AsyncSessionLocal.begin() as session:
        session.add(
            Document(
                id=document_id,
                title="Synthetic operational delivery note",
                document_type="delivery_note",
                classification="operational",
                project_id=project_id,
                status="active",
                active_version=1,
                metadata_json={},
                versions=[
                    DocumentVersion(
                        id=version_id,
                        version=1,
                        status="active",
                        classification="unclassified",
                        storage_path="synthetic/report-only",
                        original_name="delivery-note.pdf",
                        mime_type="application/pdf",
                        size_bytes=1,
                    )
                ],
            )
        )

    try:
        await report_legacy_site_workflows()
        records = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
        finding = next(
            row
            for row in records
            if row.get("finding") == "unclassified_evidence"
            and row.get("evidence_type") == "document_version"
            and row.get("evidence_id") == str(version_id)
        )
        assert finding["entity_id"] == str(document_id)
        assert finding["project_id"] == str(project_id)
        assert finding["disposition"] == "manual_classification_review"
    finally:
        async with AsyncSessionLocal.begin() as session:
            await session.execute(delete(Document).where(Document.id == document_id))


async def test_legacy_report_flags_unresolved_historical_attendance_evidence(
    inventory_ids: tuple[UUID, UUID, UUID], capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, _, _ = inventory_ids
    employee = HrEmployee(
        id=uuid4(),
        employee_code=f"HIST-{uuid4().hex[:8]}",
        first_name="Synthetic",
        last_name="Worker",
        full_name="Synthetic Worker",
        employment_status="terminated",
        join_date=None,
    )
    entry = HrAttendanceEntry(
        id=uuid4(),
        employee_id=employee.id,
        project_id=project_id,
        work_date=date(2025, 1, 15),
        attendance_status="present",
        status="returned",
        worked_hours=Decimal("8.00"),
        source="site",
    )
    async with AsyncSessionLocal.begin() as session:
        session.add(employee)
        await session.flush()
        session.add(entry)

    try:
        await report_legacy_site_workflows()
        records = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
        finding = next(
            row
            for row in records
            if row.get("finding") == "historical_attendance_eligibility"
            and row.get("id") == str(entry.id)
        )
        assert finding["employee_id"] == str(employee.id)
        assert finding["project_id"] == str(project_id)
        assert finding["reason_code"] == (
            "legacy_employment_start_unresolved,assignment_evidence_missing"
        )
        assert finding["disposition"] == "manual_reconciliation"
        async with AsyncSessionLocal() as session:
            persisted = await session.get(HrAttendanceEntry, entry.id)
            assert persisted is not None
            assert persisted.status == "returned"
            assert persisted.record_revision == 1
    finally:
        async with AsyncSessionLocal.begin() as session:
            await session.delete(entry)
            await session.delete(employee)
