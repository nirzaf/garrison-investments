import asyncio
from decimal import Decimal
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, check_database, engine
from app.models.import_batch import ImportBatch
from app.models.inventory import (
    InventoryItem,
    InventoryLocationStock,
    InventoryMovement,
    StorageLocation,
)
from app.models.project import Project
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.import_service import ImportService
from app.tasks.imports import _run_import_async
from app.utils.exceptions import AppException
from app.utils.security import hash_password

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


async def create_admin(password: str = "Start123!") -> User:
    user = User(
        email=f"import-admin-{uuid4().hex}@example.com",
        full_name="Import Admin",
        role="admin",
        employee_code=f"IMP-{uuid4().hex[:8]}",
        phone="+97455551111",
        designation="Admin",
        password_hash=hash_password(password),
        must_change_password=False,
    )
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(user)
        await session.commit()
        await session.refresh(user)
    return user


def csv_bytes(header: str, row: str) -> bytes:
    return f"{header}\n{row}\n".encode()


def xlsx_bytes(headers: list[str], row: list[str]) -> bytes:
    shared_values = headers + row
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared_values)
        + "</sst>"
    )
    header_cells = "".join(
        f'<c r="{chr(65 + index)}1" t="s"><v>{index}</v></c>' for index, _ in enumerate(headers)
    )
    row_cells = "".join(
        f'<c r="{chr(65 + index)}2" t="s"><v>{len(headers) + index}</v></c>'
        for index, _ in enumerate(row)
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="1">{header_cells}</row><row r="2">{row_cells}</row></sheetData>'
        "</worksheet>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


async def test_import_parser_accepts_xlsx_files() -> None:
    service = ImportService.__new__(ImportService)
    rows = service._parse(
        "opening_stock",
        xlsx_bytes(
            ["item_code", "location_code", "quantity", "notes"],
            ["CEM-001", "WH-001", "5", "Opening balance"],
        ),
    )

    assert rows == [
        {
            "item_code": "CEM-001",
            "location_code": "WH-001",
            "quantity": "5",
            "notes": "Opening balance",
        }
    ]


async def test_xlsx_preview_follows_the_workbook_worksheet_relationship() -> None:
    workbook_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    document_rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    original = xlsx_bytes(
        ["item_code", "location_code", "quantity", "notes"],
        ["CEM-001", "WH-001", "5", "Opening balance"],
    )
    renamed = BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(renamed, "w") as target:
        target.writestr("xl/sharedStrings.xml", source.read("xl/sharedStrings.xml"))
        target.writestr("xl/worksheets/opening.xml", source.read("xl/worksheets/sheet1.xml"))
        target.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{workbook_ns}" xmlns:r="{document_rel_ns}">'
            '<sheets><sheet name="Opening stock" sheetId="1" r:id="rId7"/></sheets></workbook>',
        )
        target.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{package_rel_ns}">'
            f'<Relationship Id="rId7" Type="{document_rel_ns}/worksheet" '
            'Target="worksheets/opening.xml"/></Relationships>',
        )

    rows = ImportService.__new__(ImportService)._parse("opening_stock", renamed.getvalue())
    assert len(rows) == 1
    assert rows[0]["item_code"] == "CEM-001"


async def test_xlsx_preview_rejects_missing_shared_string() -> None:
    original = xlsx_bytes(["quantity"], ["5"])
    malformed = BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(malformed, "w") as target:
        target.writestr("xl/sharedStrings.xml", source.read("xl/sharedStrings.xml"))
        sheet = source.read("xl/worksheets/sheet1.xml").replace(b"<v>1</v>", b"<v>9</v>")
        target.writestr("xl/worksheets/sheet1.xml", sheet)

    with pytest.raises(AppException) as error:
        await ImportService.__new__(ImportService).preview("opening_stock", malformed.getvalue())
    assert error.value.status_code == 422
    assert error.value.error_code == "IMPORT_SHARED_STRING_INVALID"


async def test_xlsx_preview_enforces_expanded_size_limit(monkeypatch) -> None:
    monkeypatch.setattr("app.services.import_service.MAX_XLSX_EXPANDED_BYTES", 1)
    with pytest.raises(AppException) as error:
        await ImportService.__new__(ImportService).preview(
            "opening_stock", xlsx_bytes(["quantity"], ["5"])
        )
    assert error.value.status_code == 413


async def test_import_templates_create_records_and_opening_stock_transactionally() -> None:
    await skip_if_database_unavailable()
    actor = await create_admin()
    suffix = uuid4().hex[:6]

    async with AsyncSessionLocal() as session:
        service = ImportService(session)
        supplier = await service.run_import(
            template_type="suppliers",
            file_name="suppliers.csv",
            content=csv_bytes(
                "name,category,rating,payment_terms,contact_person,phone,email,address,"
                "tax_registration_number,tds_certificate_number,tds_expiry_date,"
                "compliance_status",
                f"Import Supplier {suffix},Civil,A,30 days,Contact,+97455550000,"
                f"import-supplier-{suffix}@example.com,Doha,TAX-{suffix},TDS-{suffix},"
                "2027-05-16,compliant",
            ),
            actor=actor,
        )
        project = await service.run_import(
            template_type="projects",
            file_name="projects.csv",
            content=csv_bytes(
                "code,name,location,scope_of_work,status,budget_amount,start_date,"
                "target_end_date,client_name,contract_number",
                f"PRJ-{suffix},Import Project,Doha,Fit out,active,1000,2026-01-01,"
                f"2026-12-31,Client,CON-{suffix}",
            ),
            actor=actor,
        )
        material = await service.run_import(
            template_type="materials",
            file_name="materials.csv",
            content=csv_bytes(
                "name,item_code,category,item_type,unit,minimum_stock,reorder_level,"
                "unit_cost,supplier_name",
                f"Cement,ITEM-{suffix},Civil,consumable,Nos,5,5,12.5,Import Supplier {suffix}",
            ),
            actor=actor,
        )
        boq = await service.run_import(
            template_type="boq",
            file_name="boq.csv",
            content=csv_bytes(
                "project_code,item_code,description,discipline,phase,unit,"
                "planned_quantity,unit_rate",
                f"PRJ-{suffix},BOQ-{suffix},Wall works,Civil,Phase 1,Nos,10,20",
            ),
            actor=actor,
        )
        document = await service.run_import(
            template_type="documents",
            file_name="documents.csv",
            content=csv_bytes(
                "title,document_type,project_code,revision,description,file_name",
                f"Method Statement {suffix},method_statement,PRJ-{suffix},A,Initial,ms.pdf",
            ),
            actor=actor,
        )

        project_row = await session.scalar(select(Project).where(Project.code == f"PRJ-{suffix}"))
        item = await session.scalar(
            select(InventoryItem).where(InventoryItem.item_code == f"ITEM-{suffix}")
        )
        assert project_row is not None
        assert item is not None
        location = StorageLocation(
            name=f"Import Location {suffix}",
            code=f"LOC-{suffix}",
            location_type="warehouse",
        )
        session.add(location)
        await session.commit()

        stock = await service.run_import(
            template_type="opening_stock",
            file_name="opening_stock.csv",
            content=csv_bytes(
                "item_code,location_code,quantity,notes",
                f"ITEM-{suffix},LOC-{suffix},8,Opening balance",
            ),
            actor=actor,
        )

        assert supplier.summary["created"] == 1
        assert project.summary["created"] == 1
        assert material.summary["created"] == 1
        assert boq.summary["created"] == 1
        assert document.summary["created"] == 1
        assert stock.summary["created"] == 1
        assert supplier.file_name == "suppliers.csv"
        assert document.file_name == "documents.csv"
        assert stock.file_name == "opening_stock.csv"

        failed = await service.run_import(
            template_type="opening_stock",
            file_name="bad_opening_stock.csv",
            content=csv_bytes(
                "item_code,location_code,quantity,notes",
                f"ITEM-{suffix},LOC-{suffix},0,Bad balance",
            ),
            actor=actor,
        )
        assert failed.status == "failed"
        assert await session.scalar(select(func.count()).select_from(ImportBatch)) is not None

        batch = ImportBatch(
            template_type="opening_stock",
            file_name="opening_stock.csv",
            status="queued",
            created_by=actor.id,
        )
        session.add(batch)
        await session.commit()
        batch_id = batch.id
        item_id = item.id

    async def deliver() -> str:
        return await _run_import_async(
            template_type="opening_stock",
            file_name="opening_stock.csv",
            content=csv_bytes(
                "item_code,location_code,quantity,notes",
                f"ITEM-{suffix},LOC-{suffix},4,Retried opening stock",
            ),
            actor_id=str(actor.id),
            batch_id=str(batch_id),
        )

    first, second = await asyncio.gather(deliver(), deliver())
    assert first == second
    assert "completed: completed" in first
    async with AsyncSessionLocal() as session:
        movements = await session.scalars(
            select(InventoryMovement).where(InventoryMovement.item_id == item_id)
        )
        assert sorted(movement.quantity for movement in movements) == [4, 8]


async def test_preview_and_run_reject_invalid_user_fields_and_missing_references() -> None:
    await skip_if_database_unavailable()
    actor = await create_admin()
    cases = [
        (
            "users",
            csv_bytes(
                "email,full_name,role,employee_code,phone,designation,temporary_password",
                "preview-user@example.com,Preview User,unknown,PREVIEW,+97455550000,Engineer,short",
            ),
            {"role", "temporary_password"},
        ),
        (
            "opening_stock",
            csv_bytes("item_code,location_code,quantity,notes", "MISSING,MISSING,4,Opening stock"),
            {"item_code", "location_code"},
        ),
    ]
    async with AsyncSessionLocal() as session:
        service = ImportService(session)
        for template, content, fields in cases:
            preview = await service.preview(template, content)
            assert not preview.valid
            assert {error.field for error in preview.errors} == fields
            result = await service.run_import(
                template_type=template, file_name="invalid.csv", content=content, actor=actor
            )
            assert result.status == "failed"
            assert result.summary["errors"] == [error.model_dump() for error in preview.errors]


async def test_async_import_marks_existing_batch_failed_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    actor = await create_admin()
    async with AsyncSessionLocal() as session:
        batch = ImportBatch(
            template_type="materials",
            file_name="materials.csv",
            status="queued",
            created_by=actor.id,
        )
        session.add(batch)
        await session.commit()
        await session.refresh(batch)
        batch_id = batch.id

    async def raise_unexpected_import_error(self, **kwargs):
        del self, kwargs
        raise RuntimeError("storage temporarily unavailable")

    monkeypatch.setattr(
        "app.services.import_service.ImportService.run_import",
        raise_unexpected_import_error,
    )

    with pytest.raises(RuntimeError, match="storage temporarily unavailable"):
        await _run_import_async(
            template_type="materials",
            file_name="materials.csv",
            content=b"name,item_code\n",
            actor_id=str(actor.id),
            batch_id=str(batch_id),
        )

    async with AsyncSessionLocal() as session:
        failed_batch = await session.get(ImportBatch, batch_id)
        assert failed_batch is not None
        assert failed_batch.status == "failed"
        assert failed_batch.summary == {"error": "storage temporarily unavailable"}


async def test_opening_stock_row_replay_never_adds_stock_twice() -> None:
    """H8: a redelivered batch must skip rows it already applied, not re-receive them."""
    await skip_if_database_unavailable()
    actor = await create_admin()
    suffix = uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        item = InventoryItem(
            name=f"Replay Item {suffix}",
            item_code=f"ITEM-{suffix}",
            category="Civil",
            item_type="material",
            unit="Nos",
        )
        location = StorageLocation(
            name=f"Replay Location {suffix}",
            code=f"LOC-{suffix}",
            location_type="warehouse",
        )
        batch = ImportBatch(
            template_type="opening_stock",
            file_name="opening_stock.csv",
            status="queued",
            created_by=actor.id,
        )
        session.add_all([item, location, batch])
        await session.commit()
        item_id = item.id
        location_id = location.id
        batch_id = batch.id

    content = csv_bytes(
        "item_code,location_code,quantity,notes",
        f"ITEM-{suffix},LOC-{suffix},8,Opening balance",
    )

    async def deliver() -> dict:
        async with AsyncSessionLocal() as session:
            result = await ImportService(session).run_import(
                template_type="opening_stock",
                file_name="opening_stock.csv",
                content=content,
                actor=actor,
                batch_id=batch_id,
            )
            return result.summary

    assert (await deliver())["created"] == 1

    # The worker was lost after the rows became durable but before the completed marker
    # was seen by the redelivery, so the batch looks runnable again.
    async with AsyncSessionLocal() as session:
        reopened = await session.get(ImportBatch, batch_id)
        assert reopened is not None
        reopened.status = "queued"
        await session.commit()

    assert (await deliver())["created"] == 0

    async with AsyncSessionLocal() as session:
        stock = await session.scalar(
            select(InventoryLocationStock).where(
                InventoryLocationStock.item_id == item_id,
                InventoryLocationStock.location_id == location_id,
            )
        )
        assert stock is not None
        assert stock.on_hand_qty == Decimal("8.000")
        movements = (
            await session.scalars(
                select(InventoryMovement).where(InventoryMovement.item_id == item_id)
            )
        ).all()
        assert len(movements) == 1
        assert movements[0].import_batch_id == batch_id
        assert movements[0].import_row_index == 0
