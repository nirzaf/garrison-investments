import asyncio
import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.tasks.imports import ImportTask, _run_import_async
from app.utils.exceptions import AppException
from app.utils.permissions import ROLE_MANAGING_DIRECTOR
from tests.password_fixtures import hash_fixture_password

pytestmark = pytest.mark.asyncio
RETIRED_ROLE_KEYS = json.loads(
    Path(__file__).with_name("business_role_matrix.json").read_text()
)["retired_roles"]


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
        full_name="Import Director",
        role="managing_director",
        employee_code=f"IMP-{uuid4().hex[:8]}",
        phone="+97455551111",
        designation="Managing Director",
        password_hash=hash_fixture_password(password),
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
        ImportService.__new__(ImportService)._parse("opening_stock", malformed.getvalue())
    assert error.value.status_code == 422
    assert error.value.error_code == "IMPORT_SHARED_STRING_INVALID"


async def test_xlsx_preview_enforces_expanded_size_limit(monkeypatch) -> None:
    monkeypatch.setattr("app.services.import_service.MAX_XLSX_EXPANDED_BYTES", 1)
    with pytest.raises(AppException) as error:
        ImportService.__new__(ImportService)._parse(
            "opening_stock", xlsx_bytes(["quantity"], ["5"])
        )
    assert error.value.status_code == 413


async def test_import_template_permissions_follow_the_domain_matrix() -> None:
    ImportService.ensure_template_access(User(role="mep_project_manager"), "suppliers")
    ImportService.ensure_template_access(User(role="managing_director"), "projects")
    ImportService.ensure_template_access(User(role="managing_director"), "users")

    for role, template in (
        ("group_project_manager", "suppliers"),
        ("mep_project_manager", "projects"),
        ("hr_manager", "users"),
        ("hr_manager", "materials"),
        ("hr_manager", "documents"),
        ("hr_manager", "boq"),
        ("hr_executive_reader", "users"),
        ("hr_executive_reader", "documents"),
    ):
        with pytest.raises(AppException) as error:
            ImportService.ensure_template_access(User(role=role), template)
        assert error.value.status_code == 403


async def test_hr_manager_user_import_cannot_assign_protected_director_roles(monkeypatch) -> None:
    service = ImportService.__new__(ImportService)
    monkeypatch.setattr(service, "_validate_rows", lambda _template, _rows: [])

    errors = await service._validate_for_import(
        "users",
        [{"role": "managing_director"}, {"role": "hr_manager"}],
        User(role="hr_manager"),
    )

    assert [(error.row, error.field) for error in errors] == [(2, "role"), (3, "role")]


async def test_director_user_import_accepts_hr_executive_reader_as_a_target() -> None:
    service = ImportService.__new__(ImportService)
    row = {
        "email": "reader@example.com",
        "full_name": "Synthetic Directory Reader",
        "role": "hr_executive_reader",
        "employee_code": "SYNTHETIC-READER",
        "phone": "+94770000019",
        "designation": "HR Executive",
        "temporary_password": "Start123!",
    }
    assert await service._validate_for_import("users", [row], User(role="managing_director")) == []


@pytest.mark.parametrize("retired_role", [*RETIRED_ROLE_KEYS, "hr_executive"])
async def test_user_import_rejects_each_retired_role_target(retired_role: str) -> None:
    service = ImportService.__new__(ImportService)
    row = {
        "email": "candidate@example.com",
        "full_name": "Role Import Candidate",
        "role": retired_role,
        "employee_code": "ROLE-IMPORT",
        "phone": "+97455550000",
        "designation": "Candidate",
        "temporary_password": "Start123!",
    }

    errors = await service._validate_for_import("users", [row], User(role="managing_director"))

    assert any(error.row == 2 and error.field == "role" for error in errors)


@pytest.mark.parametrize("retired_role", RETIRED_ROLE_KEYS)
async def test_import_worker_rejects_each_retired_actor_before_processing(
    retired_role: str,
) -> None:
    await skip_if_database_unavailable()
    suffix = uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        actor = User(
            email=f"retired-import-{suffix}@example.com",
            full_name="Retired Import Actor",
            role=retired_role,
            employee_code=f"OLD-{suffix}",
            password_hash="synthetic-password-hash",
            must_change_password=False,
        )
        session.add(actor)
        await session.flush()
        batch = ImportBatch(
            template_type="users",
            file_name="users.csv",
            status="queued",
            created_by=actor.id,
        )
        session.add(batch)
        await session.commit()
        actor_id = actor.id
        batch_id = batch.id

    result = await _run_import_async(
        template_type="users",
        file_name="users.csv",
        content=csv_bytes(
            "email,full_name,role,employee_code,phone,designation,temporary_password",
            f"new-{suffix}@example.com,New User,quantity_surveyor,NEW-{suffix},"
            "+97455550000,Engineer,Start123!",
        ),
        actor_id=str(actor_id),
        batch_id=str(batch_id),
    )

    assert result == "import stopped: INVALID_ROLE"
    async with AsyncSessionLocal() as session:
        failed_batch = await session.get(ImportBatch, batch_id)
        assert failed_batch is not None
        assert failed_batch.status == "failed"
        assert failed_batch.summary == {"error_code": "INVALID_ROLE"}
        created_user = await session.scalar(
            select(User).where(User.email == f"new-{suffix}@example.com")
        )
        assert created_user is None


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
            preview = await service.preview(template, content, actor)
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
        assert failed_batch.status == "processing"

    # A retryable attempt remains processing; Celery's terminal failure hook is
    # responsible for marking the batch failed after its retry budget is exhausted.
    await asyncio.to_thread(
        ImportTask().on_failure,
        RuntimeError("storage temporarily unavailable"),
        "task-id",
        (),
        {"batch_id": str(batch_id)},
        None,
    )

    async with AsyncSessionLocal() as session:
        failed_batch = await session.get(ImportBatch, batch_id)
        assert failed_batch is not None
        assert failed_batch.status == "failed"
        assert failed_batch.summary == {"error_code": "IMPORT_EXECUTION_FAILED"}


async def test_opening_stock_row_replay_never_adds_stock_twice() -> None:
    """H8: a redelivered batch must skip rows it already applied, not re-receive them."""
    await skip_if_database_unavailable()
    actor = await create_admin()
    suffix = uuid4().hex[:8]
    key = str(uuid4())
    content = csv_bytes(
        "item_code,location_code,quantity,notes",
        f"ITEM-{suffix},LOC-{suffix},8,Opening balance",
    )
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
        session.add_all([item, location])
        await session.commit()
        item_id = item.id
        location_id = location.id
        queued = await ImportService(session).queue_import(
            template_type="opening_stock",
            file_name="opening_stock.csv",
            content=content,
            actor=actor,
            idempotency_key=key,
        )
        assert queued.status == "queued"
        batch_id = queued.batch_id
    async with AsyncSessionLocal() as session:
        replay = await ImportService(session).queue_import(
            template_type="opening_stock",
            file_name="opening_stock.csv",
            content=content,
            actor=actor,
            idempotency_key=key,
        )
        assert replay == queued

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
    async with AsyncSessionLocal() as session:
        replay = await ImportService(session).run_import(
            template_type="opening_stock",
            file_name="opening_stock.csv",
            content=content,
            actor=actor,
            idempotency_key=key,
        )
        assert replay.batch_id == batch_id
        assert replay.status == "completed"

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


@pytest.mark.asyncio
async def test_user_import_takes_shared_access_lock_before_actor_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    actor = User(
        id=uuid4(),
        email="role-lock@example.test",
        full_name="Role Lock Test",
        role=ROLE_MANAGING_DIRECTOR,
        employee_code="ROLE-LOCK",
        phone="+97455550000",
        password_hash="synthetic-hash",
    )
    actor.access_revision = 1
    batch_id = uuid4()

    async def access_lock(_: UserRepository) -> None:
        events.append("access-lock")

    async def actor_lock(_: User) -> User:
        events.append("actor-row-lock")
        return actor

    async def reserve(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(resource_id=batch_id)

    async def get_batch(_: UUID) -> object:
        return object()

    async def commit() -> None:
        events.append("transaction-commit")

    service = ImportService(cast(AsyncSession, SimpleNamespace(commit=commit)))

    monkeypatch.setattr(UserRepository, "lock_access_management", access_lock)
    monkeypatch.setattr(service, "_lock_and_validate_actor", actor_lock)
    monkeypatch.setattr(service, "_reserve_submission", reserve)
    monkeypatch.setattr(service, "_get_submitted_batch", get_batch)
    monkeypatch.setattr(service, "_batch_response", lambda batch: batch)

    await service.run_import(
        template_type="users",
        file_name="users.csv",
        content=b"synthetic",
        actor=actor,
        idempotency_key="safe-test-key",
    )

    assert events == ["access-lock", "actor-row-lock", "transaction-commit"]


async def test_async_import_outbox_recovers_after_prepublish_crash_and_deduplicates_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    from datetime import timedelta

    import httpx

    from app.main import app
    from app.models.activity_log import ActivityLog
    from app.models.auth import AuthSession
    from app.models.task_outbox import TaskOutbox
    from app.services.import_service import import_outbox_dedupe_key
    from app.tasks import outbox as outbox_module
    from app.tasks.outbox import _dispatch_task_outbox
    from app.utils.security import create_access_token, utc_now

    actor = await create_admin()
    suffix = uuid4().hex[:8]
    auth_session_id = uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            AuthSession(
                id=auth_session_id,
                user_id=actor.id,
                expires_at=utc_now() + timedelta(hours=1),
            )
        )
        item = InventoryItem(
            name=f"Outbox Item {suffix}",
            item_code=f"ITEM-OBX-{suffix}",
            category="Civil",
            item_type="material",
            unit="Nos",
        )
        location = StorageLocation(
            name=f"Outbox Loc {suffix}",
            code=f"LOC-OBX-{suffix}",
            location_type="warehouse",
        )
        session.add_all([item, location])
        await session.commit()
        item_id, location_id = item.id, location.id

    csv_payload = csv_bytes(
        "item_code,location_code,quantity,notes",
        f"ITEM-OBX-{suffix},LOC-OBX-{suffix},6.5,Sensitive-Marker-{suffix}",
    )

    # Simulate broker outage during initial API request -> durable outbox remains pending.
    def fail_broker(*_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr("app.tasks.outbox.celery_app.send_task", fail_broker)
    token, _ = create_access_token(actor.id, actor.role, auth_session_id=auth_session_id)
    key = str(uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/api/v1/imports/opening_stock/run-async",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
            files={"file": ("opening_stock.csv", csv_payload, "text/csv")},
        )
    assert resp.status_code == 202, resp.text
    queued = resp.json()
    assert queued["status"] == "queued"
    batch_id = UUID(queued["batch_id"])
    dedupe_key = import_outbox_dedupe_key(batch_id)

    async with AsyncSessionLocal() as session:
        entry = await session.scalar(select(TaskOutbox).where(TaskOutbox.dedupe_key == dedupe_key))
        assert entry is not None
        assert entry.status == "pending"
        assert entry.attempts == 1
        assert f"Sensitive-Marker-{suffix}" not in json.dumps(entry.kwargs_json)
        logs = (
            await session.scalars(
                select(ActivityLog).where(ActivityLog.entity_id == batch_id)
            )
        ).all()
        assert all(f"Sensitive-Marker-{suffix}" not in repr(log.new_values) for log in logs)

    # Broker recovers -> outbox dispatcher publishes without requiring client retry.
    published: list[dict[str, Any]] = []

    def capture_send_task(
        name: str,
        *,
        args: list[Any],
        kwargs: dict[str, Any],
        task_id: str,
        queue: str,
        **_opts: Any,
    ) -> None:
        published.append(
            {"name": name, "args": args, "kwargs": kwargs, "task_id": task_id, "queue": queue}
        )

    monkeypatch.setattr("app.tasks.outbox.celery_app.send_task", capture_send_task)
    async with AsyncSessionLocal() as guard:
        await guard.execute(
            select(TaskOutbox.id).where(TaskOutbox.dedupe_key != dedupe_key).with_for_update()
        )
        assert await _dispatch_task_outbox() == 1
    assert len(published) == 1
    assert published[0]["name"] == "run_import_async"
    assert published[0]["queue"] == "maintenance"
    assert published[0]["task_id"] == f"import-batch-{batch_id}"
    assert "content_ciphertext" not in published[0]["kwargs"]
    assert f"Sensitive-Marker-{suffix}" not in json.dumps(published[0]["kwargs"])

    # Worker loads encrypted payload from TaskOutbox; duplicate delivery executes only once.
    first_result, second_result = await asyncio.gather(
        _run_import_async(**published[0]["kwargs"]),
        _run_import_async(**published[0]["kwargs"]),
    )
    assert "completed: completed" in first_result
    assert "completed: completed" in second_result

    async with AsyncSessionLocal() as session:
        completed_batch = await session.get(ImportBatch, batch_id)
        completed_outbox = await session.scalar(
            select(TaskOutbox).where(TaskOutbox.dedupe_key == dedupe_key)
        )
        stock = await session.scalar(
            select(InventoryLocationStock).where(
                InventoryLocationStock.item_id == item_id,
                InventoryLocationStock.location_id == location_id,
            )
        )
        assert completed_batch is not None and completed_batch.status == "completed"
        assert completed_outbox is not None and completed_outbox.status == "completed"
        assert "content_ciphertext" not in completed_outbox.kwargs_json
        assert stock is not None and stock.on_hand_qty == Decimal("6.500")

        # Duplicate redelivery after ciphertext scrub also returns cleanly without failure.
        third_result = await _run_import_async(**published[0]["kwargs"])
        assert "completed: completed" in third_result

        # Exhausted outbox entry marks a stranded queued batch as failed.
        exhausted_id = uuid4()
        exhausted_key = import_outbox_dedupe_key(exhausted_id)
        session.add(
            ImportBatch(
                id=exhausted_id,
                template_type="opening_stock",
                file_name="exhausted.csv",
                status="queued",
                created_by=actor.id,
            )
        )
        session.add(
            TaskOutbox(
                dedupe_key=exhausted_key,
                task_name="run_import_async",
                args_json=[str(exhausted_id), str(actor.id)],
                kwargs_json={
                    "template_type": "opening_stock",
                    "file_name": "exhausted.csv",
                    "content_sha256": "0" * 64,
                    "content_ciphertext": "invalid",
                },
                status="pending",
                attempts=outbox_module.MAX_OUTBOX_ATTEMPTS,
            )
        )
        await session.commit()

    async with AsyncSessionLocal() as guard:
        await guard.execute(
            select(TaskOutbox.id).where(TaskOutbox.dedupe_key != exhausted_key).with_for_update()
        )
        assert await _dispatch_task_outbox() == 0
    async with AsyncSessionLocal() as session:
        exhausted_batch = await session.get(ImportBatch, exhausted_id)
        assert exhausted_batch is not None and exhausted_batch.status == "failed"
        assert exhausted_batch.summary == {"error_code": "IMPORT_DISPATCH_FAILED"}


async def test_import_payload_encryption_keyring_rotation_and_tamper_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zlib

    from pydantic import SecretStr

    from app.config import Settings
    from app.services import import_service
    from app.services.import_service import (
        InvalidToken,
        _legacy_import_outbox_fernet,
        decrypt_import_payload,
        encrypt_import_payload_with_key_id,
        parse_import_payload_key_id,
    )

    primary_key = "dedicated-import-outbox-key-alpha-001"
    previous_keys: str | None = None
    hr_key = "hr-secret-initial"
    backup_key = "backup-secret-initial"
    minio_key = "minio-secret-initial"

    def fake_settings() -> Settings:
        return Settings(
            app_env="test",
            import_outbox_encryption_key=SecretStr(primary_key),
            import_outbox_previous_encryption_keys=(
                SecretStr(previous_keys) if previous_keys is not None else None
            ),
            hr_encryption_key=SecretStr(hr_key),
            backup_encryption_password=backup_key,
            minio_root_password=minio_key,
        )

    monkeypatch.setattr(import_service, "get_settings", fake_settings)

    payload = b"email,full_name\nsynthetic.user@example.test,Synthetic User\n"
    token_v1, key_id_v1 = encrypt_import_payload_with_key_id(payload)
    assert token_v1.startswith(f"v2:{key_id_v1}:")
    assert parse_import_payload_key_id(token_v1) == key_id_v1
    assert "synthetic.user@example.test" not in token_v1
    assert primary_key not in token_v1

    # Rotating unrelated HR, backup, and MinIO secrets does not affect import payload decryption.
    hr_key = "hr-secret-rotated"
    backup_key = "backup-secret-rotated"
    minio_key = "minio-secret-rotated"
    assert decrypt_import_payload(token_v1, expected_key_id=key_id_v1) == payload

    # Approved key rotation: promote key B and retain key A in previous keys.
    previous_keys = primary_key
    primary_key = "dedicated-import-outbox-key-beta-002"
    assert decrypt_import_payload(token_v1, expected_key_id=key_id_v1) == payload
    token_v2, key_id_v2 = encrypt_import_payload_with_key_id(payload)
    assert key_id_v2 != key_id_v1
    assert decrypt_import_payload(token_v2, expected_key_id=key_id_v2) == payload

    # Mismatched expected_key_id or tampered ciphertext fails closed.
    with pytest.raises(InvalidToken):
        decrypt_import_payload(token_v1, expected_key_id=key_id_v2)
    with pytest.raises(InvalidToken):
        decrypt_import_payload(token_v1[:-4] + "AAAA", expected_key_id=key_id_v1)

    # Once key A is truly retired (removed from previous keys), old ciphertext fails closed.
    previous_keys = None
    with pytest.raises(InvalidToken):
        decrypt_import_payload(token_v1, expected_key_id=key_id_v1)
    assert decrypt_import_payload(token_v2, expected_key_id=key_id_v2) == payload

    # Legacy unversioned pre-upgrade tokens remain readable during upgrade transition.
    legacy_token = (
        _legacy_import_outbox_fernet(hr_key).encrypt(zlib.compress(payload)).decode("ascii")
    )
    assert decrypt_import_payload(legacy_token) == payload
    with pytest.raises(InvalidToken):
        decrypt_import_payload(legacy_token, expected_key_id=key_id_v2)


@pytest.mark.asyncio
async def test_queued_import_survives_key_rotation_and_fails_closed_when_key_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    from pydantic import SecretStr

    from app.config import Settings
    from app.models.task_outbox import TaskOutbox
    from app.services import import_service
    from app.services.import_service import import_outbox_dedupe_key
    from app.tasks import outbox as outbox_module
    from app.tasks.outbox import _dispatch_task_outbox

    state: dict[str, str | None] = {
        "primary": "rotation-drill-key-one-0001",
        "previous": None,
    }

    def fake_settings() -> Settings:
        return Settings(
            app_env="test",
            import_outbox_encryption_key=SecretStr(state["primary"] or ""),
            import_outbox_previous_encryption_keys=(
                SecretStr(state["previous"]) if state["previous"] else None
            ),
        )

    monkeypatch.setattr(import_service, "get_settings", fake_settings)

    actor = await create_admin()
    suffix = uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        item = InventoryItem(
            name=f"Rotation Item {suffix}",
            item_code=f"ROT-{suffix}",
            category="Civil",
            item_type="material",
            unit="Nos",
        )
        location = StorageLocation(
            name=f"Rotation Yard {suffix}",
            code=f"RYD-{suffix}",
            location_type="warehouse",
        )
        session.add_all([item, location])
        await session.commit()
        item_id, location_id = item.id, location.id

        content = csv_bytes(
            "item_code,location_code,quantity,notes",
            f"ROT-{suffix},RYD-{suffix},4.25,Queued before rotation",
        )
        queued = await ImportService(session).queue_import(
            template_type="opening_stock",
            file_name="rotation.csv",
            content=content,
            actor=actor,
            idempotency_key=str(uuid4()),
        )
        batch_id = queued.batch_id
        dedupe_key = import_outbox_dedupe_key(batch_id)

        retired_queued = await ImportService(session).queue_import(
            template_type="opening_stock",
            file_name="retired.csv",
            content=content,
            actor=actor,
            idempotency_key=str(uuid4()),
        )
        retired_batch_id = retired_queued.batch_id
        retired_dedupe_key = import_outbox_dedupe_key(retired_batch_id)

    # Rotate key while both batches are queued; keep old key in previous list for first batch.
    state["previous"] = state["primary"]
    state["primary"] = "rotation-drill-key-two-0002"

    dispatched_kwargs: list[dict[str, Any]] = []

    def fake_send_task(task_name: str, *, args, kwargs, task_id, queue, retry) -> None:
        del task_name, args, task_id, queue, retry
        dispatched_kwargs.append(dict(kwargs))

    monkeypatch.setattr(outbox_module.celery_app, "send_task", fake_send_task)

    async with AsyncSessionLocal() as guard:
        await guard.execute(
            select(TaskOutbox.id).where(TaskOutbox.dedupe_key != dedupe_key).with_for_update()
        )
        assert await _dispatch_task_outbox() == 1

    assert len(dispatched_kwargs) == 1
    assert "content_ciphertext" not in dispatched_kwargs[0]
    result = await _run_import_async(**dispatched_kwargs[0])
    assert "completed: completed" in result

    async with AsyncSessionLocal() as session:
        stock = await session.scalar(
            select(InventoryLocationStock).where(
                InventoryLocationStock.item_id == item_id,
                InventoryLocationStock.location_id == location_id,
            )
        )
        outbox_row = await session.scalar(
            select(TaskOutbox).where(TaskOutbox.dedupe_key == dedupe_key)
        )
        assert stock is not None and stock.on_hand_qty == Decimal("4.250")
        assert outbox_row is not None and outbox_row.status == "completed"
        assert "content_ciphertext" not in outbox_row.kwargs_json
        assert isinstance(outbox_row.kwargs_json.get("content_key_id"), str)

    # Retire the old key completely; the second pending batch fails closed and scrubs ciphertext.
    state["previous"] = None
    async with AsyncSessionLocal() as guard:
        await guard.execute(
            select(TaskOutbox.id)
            .where(TaskOutbox.dedupe_key != retired_dedupe_key)
            .with_for_update()
        )
        assert await _dispatch_task_outbox() == 0

    async with AsyncSessionLocal() as session:
        failed_batch = await session.get(ImportBatch, retired_batch_id)
        failed_outbox = await session.scalar(
            select(TaskOutbox).where(TaskOutbox.dedupe_key == retired_dedupe_key)
        )
        assert failed_batch is not None and failed_batch.status == "failed"
        assert failed_batch.summary == {"error_code": "IMPORT_DISPATCH_FAILED"}
        assert failed_outbox is not None and failed_outbox.status == "failed"
        assert "content_ciphertext" not in failed_outbox.kwargs_json
