from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, check_database, engine
from app.models.import_batch import ImportBatch
from app.models.inventory import InventoryItem, StorageLocation
from app.models.project import Project
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.import_service import ImportService
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
        f'<c r="{chr(65 + index)}1" t="s"><v>{index}</v></c>'
        for index, _ in enumerate(headers)
    )
    row_cells = "".join(
        f'<c r="{chr(65 + index)}2" t="s"><v>{len(headers) + index}</v></c>'
        for index, _ in enumerate(row)
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData><row r=\"1\">{header_cells}</row><row r=\"2\">{row_cells}</row></sheetData>"
        "</worksheet>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


async def test_import_preview_accepts_xlsx_files() -> None:
    service = ImportService.__new__(ImportService)
    preview = await service.preview(
        "opening_stock",
        xlsx_bytes(
            ["item_code", "location_code", "quantity", "notes"],
            ["CEM-001", "WH-001", "5", "Opening balance"],
        ),
    )

    assert preview.valid is True
    assert preview.row_count == 1


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
                f"Cement,ITEM-{suffix},Civil,consumable,Nos,5,5,12.5,"
                f"Import Supplier {suffix}",
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
