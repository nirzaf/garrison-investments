import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.boq_item import BoqItem
from app.models.document import Document
from app.models.import_batch import ImportBatch
from app.models.inventory import InventoryItem, StorageLocation
from app.models.project import Project
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.imports import ImportErrorItem, ImportPreviewResponse, ImportRunResponse
from app.schemas.inventory import MovementCreateRequest
from app.services.audit_service import AuditService
from app.services.inventory_service import InventoryService
from app.utils.exceptions import AppException
from app.utils.permissions import validate_role
from app.utils.security import hash_password, validate_password_policy

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

    def template_path(self, template_type: str) -> Path:
        self._ensure_template(template_type)
        return (
            Path(__file__).resolve().parents[3]
            / "docs"
            / "import_templates"
            / f"{template_type}.csv"
        )

    async def preview(self, template_type: str, content: bytes) -> ImportPreviewResponse:
        rows = self._parse(template_type, content)
        errors = self._validate_rows(template_type, rows)
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
    ) -> ImportRunResponse:
        rows = self._parse(template_type, content)
        errors = self._validate_rows(template_type, rows)
        batch = ImportBatch(
            template_type=template_type,
            file_name=file_name,
            status="failed" if errors else "completed",
            created_by=actor.id,
            row_count=len(rows),
            error_count=len(errors),
            summary={"errors": [error.model_dump() for error in errors]},
        )
        self.session.add(batch)
        await self.session.flush()
        created = 0
        try:
            if not errors:
                created = await self._import_rows(template_type, rows, actor)
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
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return ImportRunResponse(
            batch_id=batch.id,
            template_type=template_type,
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
    ) -> int:
        if template_type == "users":
            return await self._import_users(rows)
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
            return await self._import_opening_stock(rows, actor)
        raise AppException("Unknown import template.", status_code=404, error_code="IMPORT_UNKNOWN")

    async def _import_users(self, rows: list[dict[str, str]]) -> int:
        created = 0
        for row in rows:
            email = row["email"].strip().lower()
            existing = await self.session.scalar(
                select(User).where(User.email == email, User.deleted_at.is_(None))
            )
            if existing:
                continue
            validate_password_policy(row["temporary_password"])
            self.session.add(
                User(
                    email=email,
                    full_name=row["full_name"].strip(),
                    role=validate_role(row["role"]),
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

    async def _import_opening_stock(self, rows: list[dict[str, str]], actor: User) -> int:
        created = 0
        inventory = InventoryService(self.session)
        for row in rows:
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
            )
            created += 1
        return created

    def _parse(self, template_type: str, content: bytes) -> list[dict[str, str]]:
        self._ensure_template(template_type)
        text = content.decode("utf-8-sig")
        return list(csv.DictReader(StringIO(text)))

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

    def _ensure_template(self, template_type: str) -> None:
        if template_type not in TEMPLATE_COLUMNS:
            raise AppException(
                "Unknown import template.", status_code=404, error_code="IMPORT_UNKNOWN"
            )
