import csv
import posixpath
import re
import zipfile
from datetime import date
from decimal import Decimal
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree

from sqlalchemy import String, any_, literal, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models.boq_item import BoqItem
from app.models.document import Document
from app.models.idempotency_record import IdempotencyRecord
from app.models.import_batch import ImportBatch
from app.models.inventory import InventoryItem, InventoryMovement, StorageLocation
from app.models.project import Project
from app.models.supplier import Supplier
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.imports import ImportErrorItem, ImportPreviewResponse, ImportRunResponse
from app.schemas.inventory import MovementCreateRequest
from app.services.audit_service import AuditService
from app.services.idempotency import resolve_or_reserve
from app.services.inventory_service import InventoryService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_DOCUMENTS_MANAGE,
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_PROJECTS_MANAGE,
    PERMISSION_SUPPLIERS_MANAGE,
    PERMISSION_USERS_MANAGE,
    can_assign_user_role,
    ensure_permission,
    validate_role,
)
from app.utils.security import hash_password, validate_password_policy

XLSX_NAMESPACE = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
XLSX_RELATIONSHIP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_XLSX_ENTRIES = 1_000
MAX_XLSX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_XLSX_COLUMNS = 16_384
MAX_XLSX_CELLS = 1_000_000
IMPORT_SUBMISSION_ROUTE = "imports.submit"

TEMPLATE_COLUMNS = {
    "users": [
        "email",
        "full_name",
        "role",
        "employee_code",
        "phone",
        "designation",
        "temporary_password",
    ],
    "projects": [
        "code",
        "name",
        "location",
        "scope_of_work",
        "status",
        "budget_amount",
        "start_date",
        "target_end_date",
        "client_name",
        "contract_number",
    ],
    "suppliers": [
        "name",
        "category",
        "rating",
        "payment_terms",
        "contact_person",
        "phone",
        "email",
        "address",
        "tax_registration_number",
        "tds_certificate_number",
        "tds_expiry_date",
        "compliance_status",
    ],
    "materials": [
        "name",
        "item_code",
        "category",
        "item_type",
        "unit",
        "minimum_stock",
        "reorder_level",
        "unit_cost",
        "supplier_name",
    ],
    "documents": ["title", "document_type", "project_code", "revision", "description", "file_name"],
    "boq": [
        "project_code",
        "item_code",
        "description",
        "discipline",
        "phase",
        "unit",
        "planned_quantity",
        "unit_rate",
    ],
    "opening_stock": ["item_code", "location_code", "quantity", "notes"],
}


class ImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    def template_path(self, template_type: str, actor: User) -> Path:
        self._ensure_template(template_type)
        self.ensure_template_access(actor, template_type)
        return (
            Path(__file__).resolve().parents[3]
            / "docs"
            / "import_templates"
            / f"{template_type}.csv"
        )

    async def preview(
        self, template_type: str, content: bytes, actor: User
    ) -> ImportPreviewResponse:
        # Preview is read-only. A row lock held until request teardown can block the
        # separate request-audit transaction on the users foreign key. The actual
        # import path repeats this check under a lock before it writes anything.
        actor = await self._lock_and_validate_actor(actor, lock=False)
        self.ensure_template_access(actor, template_type)
        rows = self._parse(template_type, content)
        errors = await self._validate_for_import(template_type, rows, actor)
        return ImportPreviewResponse(
            template_type=template_type,
            row_count=len(rows),
            errors=errors,
            valid=not errors,
        )

    async def run_import(
        self,
        *,
        template_type: str,
        file_name: str,
        content: bytes,
        actor: User,
        batch_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> ImportRunResponse:
        # User imports and interactive account changes share the same lock as
        # the one-time role cutover. Acquire it before locking the actor row so
        # all user-writing paths use the same lock order.
        if template_type == "users":
            await UserRepository(self.session).lock_access_management()
        actor = await self._lock_and_validate_actor(actor)
        self.ensure_template_access(actor, template_type)
        submission = None
        if batch_id is None:
            submission = await self._reserve_submission(
                template_type, file_name, content, actor.id, idempotency_key
            )
            if submission is not None and submission.resource_id is not None:
                replay = await self._get_submitted_batch(submission.resource_id)
                # Release the actor row lock before request-audit middleware writes
                # its separate event with a foreign key to this user.
                await self.session.commit()
                return self._batch_response(replay)
            batch = ImportBatch(
                template_type=template_type,
                file_name=file_name,
                created_by=actor.id,
            )
        else:
            # The completed marker and imported rows commit together. A second
            # delivery waits here until it can see the first delivery's result.
            existing_batch = await self.session.get(ImportBatch, batch_id, with_for_update=True)
            if existing_batch is None or existing_batch.deleted_at is not None:
                raise NotFoundException("Import batch")
            if (
                existing_batch.created_by != actor.id
                or existing_batch.template_type != template_type
            ):
                raise NotFoundException("Import batch")
            batch = existing_batch
            if batch.status == "completed":
                await self.session.commit()
                return self._batch_response(batch)
        rows = self._parse(template_type, content)
        errors = await self._validate_for_import(template_type, rows, actor)
        batch.status = "failed" if errors else "completed"
        batch.row_count = len(rows)
        batch.error_count = len(errors)
        batch.summary = {"errors": [error.model_dump() for error in errors]}
        if batch_id is None:
            self.session.add(batch)
        await self.session.flush()
        try:
            if not errors:
                created = await self._import_rows(template_type, rows, actor, batch.id)
                batch.summary = {"created": created, "skipped": len(rows) - created}
            await self.audit.record(
                action="imports.run",
                user_id=actor.id,
                entity_type="import_batches",
                entity_id=batch.id,
                new_values={
                    "template_type": template_type,
                    "row_count": len(rows),
                    "error_count": len(errors),
                },
            )
            if submission is not None:
                submission.resource_type = "import_batch"
                submission.resource_id = batch.id
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return self._batch_response(batch)

    async def queue_import(
        self,
        *,
        template_type: str,
        file_name: str,
        content: bytes,
        actor: User,
        idempotency_key: str | None,
    ) -> ImportRunResponse:
        actor = await self._lock_and_validate_actor(actor)
        self.ensure_template_access(actor, template_type)
        self._ensure_template(template_type)
        submission = await self._reserve_submission(
            template_type, file_name, content, actor.id, idempotency_key
        )
        if submission is not None and submission.resource_id is not None:
            replay = await self._get_submitted_batch(submission.resource_id)
            await self.session.commit()
            return self._batch_response(replay)
        batch = ImportBatch(
            template_type=template_type,
            file_name=file_name,
            created_by=actor.id,
            status="queued",
            row_count=0,
            error_count=0,
            summary={},
        )
        self.session.add(batch)
        await self.session.flush()
        if submission is not None:
            submission.resource_type = "import_batch"
            submission.resource_id = batch.id
        await self.session.commit()
        return self._batch_response(batch)

    async def _reserve_submission(
        self,
        template_type: str,
        file_name: str,
        content: bytes,
        user_id: UUID,
        key: str | None,
    ) -> IdempotencyRecord | None:
        if key is None:
            return None
        fingerprint = sha256(
            f"{template_type}\0{file_name}\0{sha256(content).hexdigest()}".encode()
        ).hexdigest()
        await resolve_or_reserve(
            self.session, key=key, user_id=user_id, route=IMPORT_SUBMISSION_ROUTE
        )
        record = await self.session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.key == key,
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.route == IMPORT_SUBMISSION_ROUTE,
            )
        )
        assert record is not None
        if record.resource_id is None:
            record.request_fingerprint = fingerprint
        elif record.request_fingerprint != fingerprint:
            raise AppException(
                "This import key was used for a different file or template.",
                status_code=409,
                error_code="IMPORT_REPLAY_CONFLICT",
            )
        return record

    async def _get_submitted_batch(self, batch_id: UUID) -> ImportBatch:
        batch = await self.session.get(ImportBatch, batch_id)
        if batch is None or batch.deleted_at is not None:
            raise NotFoundException("Import batch")
        return batch

    @staticmethod
    def _batch_response(batch: ImportBatch) -> ImportRunResponse:
        return ImportRunResponse(
            batch_id=batch.id,
            template_type=batch.template_type,
            file_name=batch.file_name,
            status=batch.status,
            row_count=batch.row_count,
            error_count=batch.error_count,
            summary=batch.summary or {},
        )

    async def _import_rows(
        self,
        template_type: str,
        rows: list[dict[str, str]],
        actor: User,
        batch_id: UUID,
    ) -> int:
        if template_type == "users":
            return await self._import_users(rows, actor)
        if template_type == "projects":
            return await self._import_projects(rows, actor)
        if template_type == "suppliers":
            return await self._import_suppliers(rows)
        if template_type == "materials":
            return await self._import_materials(rows)
        if template_type == "documents":
            return await self._import_documents(rows, actor)
        if template_type == "boq":
            return await self._import_boq(rows)
        if template_type == "opening_stock":
            return await self._import_opening_stock(rows, actor, batch_id)
        raise AppException("Unknown import template.", status_code=404, error_code="IMPORT_UNKNOWN")

    async def _import_users(self, rows: list[dict[str, str]], actor: User) -> int:
        created = 0
        for row in rows:
            role = validate_role(row["role"])
            if not can_assign_user_role(actor.role, role):
                raise AppException(
                    "Your role cannot assign one or more requested user roles.",
                    status_code=403,
                    error_code="USER_ROLE_ASSIGNMENT_FORBIDDEN",
                )
            email = row["email"].strip().lower()
            existing = await self.session.scalar(
                select(User).where(User.email == email, User.deleted_at.is_(None))
            )
            if existing:
                continue
            self.session.add(
                User(
                    email=email,
                    full_name=row["full_name"].strip(),
                    role=role,
                    employee_code=row["employee_code"].strip(),
                    phone=row["phone"].strip(),
                    designation=row.get("designation") or None,
                    password_hash=hash_password(row["temporary_password"]),
                    must_change_password=True,
                )
            )
            created += 1
        return created

    async def _import_projects(self, rows: list[dict[str, str]], actor: User) -> int:
        created = 0
        for row in rows:
            code = row["code"].strip()
            existing = await self.session.scalar(
                select(Project).where(Project.code == code, Project.deleted_at.is_(None))
            )
            if existing:
                continue
            self.session.add(
                Project(
                    code=code,
                    name=row["name"].strip(),
                    location=row.get("location") or None,
                    description=row.get("scope_of_work") or None,
                    scope_of_work=row["scope_of_work"],
                    status=row["status"],
                    budget_amount=Decimal(row["budget_amount"]),
                    start_date=date.fromisoformat(row["start_date"]),
                    target_end_date=date.fromisoformat(row["target_end_date"]),
                    client_name=row.get("client_name") or None,
                    contract_number=row.get("contract_number") or None,
                    created_by=actor.id,
                )
            )
            created += 1
        return created

    async def _import_suppliers(self, rows: list[dict[str, str]]) -> int:
        created = 0
        for row in rows:
            existing = await self.session.scalar(
                select(Supplier).where(
                    Supplier.tax_registration_number == row["tax_registration_number"],
                    Supplier.deleted_at.is_(None),
                )
            )
            if existing:
                continue
            self.session.add(
                Supplier(
                    name=row["name"],
                    category=row["category"],
                    rating=row["rating"],
                    payment_terms=row["payment_terms"],
                    contact_person=row["contact_person"],
                    phone=row["phone"],
                    email=row["email"],
                    address=row["address"],
                    tax_registration_number=row["tax_registration_number"],
                    tds_certificate_number=row.get("tds_certificate_number") or None,
                    tds_expiry_date=(
                        date.fromisoformat(row["tds_expiry_date"])
                        if row.get("tds_expiry_date")
                        else None
                    ),
                    compliance_status=row["compliance_status"],
                )
            )
            created += 1
        return created

    async def _import_materials(self, rows: list[dict[str, str]]) -> int:
        created = 0
        for row in rows:
            item_code = row["item_code"].strip()
            existing = await self.session.scalar(
                select(InventoryItem).where(
                    InventoryItem.item_code == item_code,
                    InventoryItem.deleted_at.is_(None),
                )
            )
            if existing:
                continue
            supplier = await self.session.scalar(
                select(Supplier).where(
                    Supplier.name == row["supplier_name"],
                    Supplier.deleted_at.is_(None),
                )
            )
            if not supplier:
                continue
            self.session.add(
                InventoryItem(
                    name=row["name"],
                    item_code=item_code,
                    category=row["category"],
                    item_type=row["item_type"],
                    unit=row["unit"],
                    minimum_stock=Decimal(row["minimum_stock"]),
                    reorder_level=Decimal(row["reorder_level"]),
                    unit_cost=Decimal(row["unit_cost"]),
                    supplier_id=supplier.id,
                )
            )
            created += 1
        return created

    async def _import_documents(self, rows: list[dict[str, str]], actor: User) -> int:
        created = 0
        for row in rows:
            project = await self.session.scalar(
                select(Project).where(
                    Project.code == row["project_code"],
                    Project.deleted_at.is_(None),
                )
            )
            if not project:
                continue
            existing = await self.session.scalar(
                select(Document).where(
                    Document.title == row["title"],
                    Document.project_id == project.id,
                    Document.deleted_at.is_(None),
                )
            )
            if existing:
                continue
            self.session.add(
                Document(
                    title=row["title"],
                    document_type=row["document_type"],
                    project_id=project.id,
                    status="pending_approval",
                    active_version=None,
                    metadata_json={
                        "revision": row["revision"],
                        "description": row.get("description"),
                        "file_name": row.get("file_name"),
                    },
                    uploaded_by=actor.id,
                )
            )
            created += 1
        return created

    async def _import_boq(self, rows: list[dict[str, str]]) -> int:
        created = 0
        for row in rows:
            project = await self.session.scalar(
                select(Project).where(
                    Project.code == row["project_code"],
                    Project.deleted_at.is_(None),
                )
            )
            if not project:
                continue
            item_code = row["item_code"].strip()
            existing = await self.session.scalar(
                select(BoqItem).where(
                    BoqItem.project_id == project.id,
                    BoqItem.item_code == item_code,
                    BoqItem.deleted_at.is_(None),
                )
            )
            if existing:
                continue
            planned_quantity = Decimal(row["planned_quantity"])
            unit_rate = Decimal(row["unit_rate"])
            self.session.add(
                BoqItem(
                    project_id=project.id,
                    item_code=item_code,
                    description=row["description"],
                    discipline=row.get("discipline") or None,
                    phase=row.get("phase") or None,
                    unit=row["unit"],
                    planned_quantity=planned_quantity,
                    unit_rate=unit_rate,
                    planned_amount=planned_quantity * unit_rate,
                )
            )
            created += 1
        return created

    async def _import_opening_stock(
        self, rows: list[dict[str, str]], actor: User, batch_id: UUID
    ) -> int:
        created = 0
        inventory = InventoryService(self.session)
        # run_import holds the batch lock through commit, so the recorded rows
        # cannot change between this read and applying the remaining rows.
        applied_rows = set(
            await self.session.scalars(
                select(InventoryMovement.import_row_index).where(
                    InventoryMovement.import_batch_id == batch_id
                )
            )
        )
        for row_index, row in enumerate(rows):
            if row_index in applied_rows:
                continue
            item = await self.session.scalar(
                select(InventoryItem).where(
                    InventoryItem.item_code == row["item_code"],
                    InventoryItem.deleted_at.is_(None),
                )
            )
            location = await self.session.scalar(
                select(StorageLocation).where(
                    StorageLocation.code == row["location_code"],
                    StorageLocation.deleted_at.is_(None),
                )
            )
            if not item or not location:
                continue
            await inventory.create_movement(
                MovementCreateRequest(
                    item_id=item.id,
                    movement_type="receive",
                    quantity=Decimal(row["quantity"]),
                    to_location_id=location.id,
                    notes=row.get("notes") or "Opening stock import",
                ),
                actor,
                commit=False,
                import_row=(batch_id, row_index),
            )
            created += 1
        return created

    def _parse(self, template_type: str, content: bytes) -> list[dict[str, str]]:
        self._ensure_template(template_type)
        if content.startswith(b"PK"):
            return self._parse_xlsx(content)
        text = content.decode("utf-8-sig")
        return list(csv.DictReader(StringIO(text)))

    def _parse_xlsx(self, content: bytes) -> list[dict[str, str]]:
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > MAX_XLSX_ENTRIES
                    or sum(entry.file_size for entry in entries) > MAX_XLSX_EXPANDED_BYTES
                ):
                    raise self._xlsx_too_large()
                shared_strings: list[str] = []
                if "xl/sharedStrings.xml" in archive.namelist():
                    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                    shared_strings = [
                        "".join(text.text or "" for text in item.iterfind(".//x:t", XLSX_NAMESPACE))
                        for item in root.iterfind("x:si", XLSX_NAMESPACE)
                    ]

                sheet_name = self._xlsx_sheet_path(archive)
                root = ElementTree.fromstring(archive.read(sheet_name))
                table: list[list[str]] = []
                cells_read = 0
                for row in root.iterfind(".//x:sheetData/x:row", XLSX_NAMESPACE):
                    values: list[str] = []
                    for cell in row.iterfind("x:c", XLSX_NAMESPACE):
                        column_index = self._xlsx_column_index(cell.attrib.get("r", ""))
                        if column_index >= MAX_XLSX_COLUMNS:
                            raise self._xlsx_too_large()
                        values.extend([""] * max(0, column_index - len(values)))
                        values.append(self._xlsx_cell_value(cell, shared_strings))
                    cells_read += max(1, len(values))
                    if cells_read > MAX_XLSX_CELLS:
                        raise self._xlsx_too_large()
                    table.append(values)
        except (
            zipfile.BadZipFile,
            ElementTree.ParseError,
            NotImplementedError,
            RuntimeError,
        ) as exc:
            raise AppException(
                "The spreadsheet could not be read.",
                status_code=422,
                error_code="IMPORT_INVALID_XLSX",
            ) from exc
        if not table:
            return []
        headers = table[0]
        return [
            {header: row[index] if index < len(row) else "" for index, header in enumerate(headers)}
            for row in table[1:]
        ]

    @staticmethod
    def _xlsx_too_large() -> AppException:
        return AppException(
            "The spreadsheet exceeds the import size limit.",
            status_code=413,
            error_code="IMPORT_FILE_TOO_LARGE",
        )

    @staticmethod
    def _xlsx_sheet_path(archive: zipfile.ZipFile) -> str:
        names = set(archive.namelist())
        workbook_path = "xl/workbook.xml"
        relationships_path = "xl/_rels/workbook.xml.rels"
        if workbook_path not in names and relationships_path not in names:
            # Preserve support for older template archives with only a worksheet.
            if "xl/worksheets/sheet1.xml" in names:
                return "xl/worksheets/sheet1.xml"
        elif workbook_path in names and relationships_path in names:
            workbook = ElementTree.fromstring(archive.read(workbook_path))
            relationships = ElementTree.fromstring(archive.read(relationships_path))
            targets = {
                relationship.get("Id"): relationship.get("Target", "")
                for relationship in relationships
                if relationship.get("TargetMode") != "External"
                and relationship.get("Type", "").endswith("/worksheet")
            }
            for sheet in workbook.iterfind("x:sheets/x:sheet", XLSX_NAMESPACE):
                target = targets.get(sheet.get(f"{{{XLSX_RELATIONSHIP_NS}}}id"))
                if not target:
                    continue
                path = posixpath.normpath(
                    target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target)
                )
                if path.startswith("xl/") and path in names:
                    return path
                break
        raise AppException(
            "The spreadsheet has no readable worksheet.",
            status_code=422,
            error_code="IMPORT_SHEET_NOT_FOUND",
        )

    @staticmethod
    def _xlsx_cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
        if cell.get("t") == "inlineStr":
            return "".join(text.text or "" for text in cell.iterfind(".//x:t", XLSX_NAMESPACE))
        value = cell.findtext("x:v", default="", namespaces=XLSX_NAMESPACE)
        if cell.get("t") != "s" or not value:
            return value
        try:
            index = int(value)
            if 0 <= index < len(shared_strings):
                return shared_strings[index]
        except ValueError:
            pass
        raise AppException(
            "The spreadsheet contains an invalid shared string reference.",
            status_code=422,
            error_code="IMPORT_SHARED_STRING_INVALID",
        )

    def _xlsx_column_index(self, cell_reference: str) -> int:
        match = re.match(r"([A-Z]+)", cell_reference)
        if not match:
            return 0
        index = 0
        for character in match.group(1):
            index = index * 26 + ord(character) - ord("A") + 1
            if index > MAX_XLSX_COLUMNS:
                return MAX_XLSX_COLUMNS
        return index - 1

    async def _validate_for_import(
        self, template_type: str, rows: list[dict[str, str]], actor: User
    ) -> list[ImportErrorItem]:
        errors = self._validate_rows(template_type, rows)
        if template_type == "users":
            for index, row in enumerate(rows, start=2):
                if not row.get("role"):
                    continue
                try:
                    role = validate_role(row["role"])
                except AppException:
                    continue
                if not can_assign_user_role(actor.role, role):
                    errors.append(
                        ImportErrorItem(
                            row=index,
                            field="role",
                            message="Your role cannot assign this role.",
                        )
                    )
        return errors or await self._validate_references(template_type, rows)

    @staticmethod
    def ensure_template_access(actor: User, template_type: str) -> None:
        permission_by_template = {
            "users": PERMISSION_USERS_MANAGE,
            "suppliers": PERMISSION_SUPPLIERS_MANAGE,
            "materials": PERMISSION_INVENTORY_MANAGE,
            "opening_stock": PERMISSION_INVENTORY_MANAGE,
            "documents": PERMISSION_DOCUMENTS_MANAGE,
            "projects": PERMISSION_PROJECTS_MANAGE,
            "boq": PERMISSION_PROJECTS_MANAGE,
        }
        permission = permission_by_template.get(template_type)
        if permission is None:
            raise AppException(
                "Unknown import template.", status_code=404, error_code="IMPORT_UNKNOWN"
            )
        ensure_permission(actor, permission)
        # New project and priced BOQ imports require company resource and financial scope.
        # The source permission matrix does not grant financial reads to project managers.
        if template_type in {"projects", "boq"} and actor.role not in COMPANY_RESOURCE_ROLES:
            raise AppException(
                "Project and priced BOQ imports are restricted to directors.",
                status_code=403,
                error_code="IMPORT_SCOPE_FORBIDDEN",
            )

    async def _lock_and_validate_actor(self, actor: User, *, lock: bool = True) -> User:
        query = select(User).where(User.id == actor.id, User.deleted_at.is_(None))
        if lock:
            query = query.with_for_update()
        current_actor = await self.session.scalar(query.execution_options(populate_existing=True))
        if (
            current_actor is None
            or not current_actor.is_active
            or current_actor.access_revision != actor.access_revision
        ):
            raise AppException(
                "Import access changed. Reload your session before continuing.",
                status_code=403,
                error_code="IMPORT_ACTOR_ACCESS_REVOKED",
            )
        return current_actor

    def _validate_rows(
        self, template_type: str, rows: list[dict[str, str]]
    ) -> list[ImportErrorItem]:
        required = TEMPLATE_COLUMNS[template_type]
        errors: list[ImportErrorItem] = []
        for column in required:
            if not rows or column not in rows[0]:
                errors.append(
                    ImportErrorItem(row=1, field=column, message="Required column missing.")
                )
        for index, row in enumerate(rows, start=2):
            for column in required:
                if column not in row or row[column] in {None, ""}:
                    if column in {"tds_certificate_number", "tds_expiry_date", "notes"}:
                        continue
                    errors.append(
                        ImportErrorItem(row=index, field=column, message="Value is required.")
                    )
            if template_type == "users":
                for field, validate in (
                    ("role", validate_role),
                    ("temporary_password", validate_password_policy),
                ):
                    if not row.get(field):
                        continue
                    try:
                        validate(row[field])
                    except AppException as error:
                        messages = [item["message"] for item in error.errors] or [error.message]
                        errors.extend(
                            ImportErrorItem(row=index, field=field, message=message)
                            for message in messages
                        )
            if template_type == "opening_stock" and row.get("quantity"):
                try:
                    if Decimal(row["quantity"]) <= 0:
                        raise ValueError
                except Exception:
                    errors.append(
                        ImportErrorItem(
                            row=index, field="quantity", message="Must be positive number."
                        )
                    )
            for field in {
                "budget_amount",
                "minimum_stock",
                "reorder_level",
                "unit_cost",
                "planned_quantity",
                "unit_rate",
            }.intersection(required):
                if row.get(field):
                    try:
                        Decimal(row[field])
                    except Exception:
                        errors.append(
                            ImportErrorItem(row=index, field=field, message="Must be a number.")
                        )
            for field in {"start_date", "target_end_date", "tds_expiry_date"}.intersection(
                required
            ):
                if row.get(field):
                    try:
                        date.fromisoformat(row[field])
                    except Exception:
                        errors.append(
                            ImportErrorItem(
                                row=index,
                                field=field,
                                message="Must be an ISO date in YYYY-MM-DD format.",
                            )
                        )
        return errors

    async def _validate_references(
        self, template_type: str, rows: list[dict[str, str]]
    ) -> list[ImportErrorItem]:
        references: dict[
            str,
            list[
                tuple[
                    str,
                    InstrumentedAttribute[str] | InstrumentedAttribute[str | None],
                    InstrumentedAttribute,
                ]
            ],
        ] = {
            "materials": [("supplier_name", Supplier.name, Supplier.deleted_at)],
            "documents": [("project_code", Project.code, Project.deleted_at)],
            "boq": [("project_code", Project.code, Project.deleted_at)],
            "opening_stock": [
                ("item_code", InventoryItem.item_code, InventoryItem.deleted_at),
                ("location_code", StorageLocation.code, StorageLocation.deleted_at),
            ],
        }
        errors: list[ImportErrorItem] = []
        for field, column, deleted_at in references.get(template_type, []):
            # ANY keeps this lookup bounded to one bind parameter per reference.
            values = sorted({row[field] for row in rows})
            existing = set(
                await self.session.scalars(
                    select(column).where(
                        column == any_(literal(values, type_=ARRAY(String))),
                        deleted_at.is_(None),
                    )
                )
            )
            errors.extend(
                ImportErrorItem(row=index, field=field, message="Referenced record not found.")
                for index, row in enumerate(rows, start=2)
                if row[field] not in existing
            )
        return errors

    def _ensure_template(self, template_type: str) -> None:
        if template_type not in TEMPLATE_COLUMNS:
            raise AppException(
                "Unknown import template.", status_code=404, error_code="IMPORT_UNKNOWN"
            )
