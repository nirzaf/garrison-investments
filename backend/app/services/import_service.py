import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_batch import ImportBatch
from app.models.inventory import InventoryItem, StorageLocation
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.imports import ImportErrorItem, ImportPreviewResponse, ImportRunResponse
from app.schemas.inventory import MovementCreateRequest
from app.services.audit_service import AuditService
from app.services.inventory_service import InventoryService
from app.utils.exceptions import AppException

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
        if not errors:
            if template_type == "suppliers":
                created = await self._import_suppliers(rows)
            elif template_type == "opening_stock":
                created = await self._import_opening_stock(rows, actor)
            else:
                batch.status = "validated"
            batch.summary = {"created": created}
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
        return ImportRunResponse(
            batch_id=batch.id,
            template_type=template_type,
            status=batch.status,
            row_count=batch.row_count,
            error_count=batch.error_count,
            summary=batch.summary or {},
        )

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
        return errors

    def _ensure_template(self, template_type: str) -> None:
        if template_type not in TEMPLATE_COLUMNS:
            raise AppException(
                "Unknown import template.", status_code=404, error_code="IMPORT_UNKNOWN"
            )
