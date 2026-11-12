from datetime import date
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from minio import Minio
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.daily_report import DailyReport
from app.models.finance import Invoice, Payment
from app.models.inventory import InventoryItem, InventoryMovement
from app.models.project import Project
from app.models.user import User
from app.schemas.analytics import AnalyticsSummaryResponse, MaterialUsageRow, ProjectAnalyticsRow
from app.services.authorization import accessible_project_ids, ensure_project_access
from app.services.finance_service import FINANCE_ROLES, NON_BILLABLE_INVOICE_STATUSES
from app.utils.exceptions import AppException
from app.utils.permissions import ROLE_ADMIN, ROLE_GENERAL_MANAGER, ROLE_OPERATION_MANAGER

MANAGEMENT_ROLES = {ROLE_ADMIN, ROLE_GENERAL_MANAGER, ROLE_OPERATION_MANAGER}


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    def ensure_management_access(self, actor: User) -> None:
        if actor.role not in MANAGEMENT_ROLES and actor.role not in FINANCE_ROLES:
            raise AppException(
                "Management analytics are restricted.",
                status_code=403,
                error_code="ANALYTICS_FORBIDDEN",
            )

    async def summary(
        self,
        actor: User,
        *,
        project_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        location: str | None = None,
        department: str | None = None,
    ) -> AnalyticsSummaryResponse:
        project_scope = await self._project_scope(actor, project_id)
        self._validate_date_range(date_from, date_to)
        projects = await self._project_rows(project_scope, date_from, date_to, location, department)
        usage = await self._material_rows(project_scope, date_from, date_to, department)
        return AnalyticsSummaryResponse(projects=projects, material_usage=usage)

    async def project_progress_export(
        self,
        actor: User,
        *,
        project_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        location: str | None = None,
        department: str | None = None,
    ) -> bytes:
        project_scope = await self._project_scope(actor, project_id)
        self._validate_date_range(date_from, date_to)
        rows = await self._project_rows(project_scope, date_from, date_to, location, department)
        return build_xlsx(
            "Project Progress",
            [["Project", "Progress %", "Reports", "Invoice Total", "Paid Total"]]
            + [
                [
                    row.project_name,
                    str(row.progress_percentage),
                    str(row.report_count),
                    str(row.invoice_total),
                    str(row.paid_total),
                ]
                for row in rows
            ],
            context=self._filter_context(project_id, date_from, date_to, location, department),
        )

    async def material_usage_export(
        self,
        actor: User,
        *,
        project_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        department: str | None = None,
    ) -> bytes:
        project_scope = await self._project_scope(actor, project_id)
        self._validate_date_range(date_from, date_to)
        rows = await self._material_rows(project_scope, date_from, date_to, department)
        return build_xlsx(
            "Material Usage",
            [["Item", "Issued Quantity", "Consumed Quantity"]]
            + [
                [row.item_name, str(row.issued_quantity), str(row.consumed_quantity)]
                for row in rows
            ],
            context=self._filter_context(
                project_id, date_from, date_to, None, department, material=True
            ),
        )

    async def management_pdf_summary(
        self,
        actor: User,
        *,
        project_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        location: str | None = None,
        department: str | None = None,
    ) -> bytes:
        summary = await self.summary(
            actor,
            project_id=project_id,
            date_from=date_from,
            date_to=date_to,
            location=location,
            department=department,
        )
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = [
            Paragraph("Garrisons Investments - Management Summary", styles["Title"]),
            Spacer(1, 12),
            Paragraph(
                escape_xml(
                    self._filter_context(project_id, date_from, date_to, location, department)
                ),
                styles["BodyText"],
            ),
            Paragraph("Project Progress", styles["Heading2"]),
            Table(
                [["Project", "Progress", "Reports", "Invoiced", "Paid"]]
                + [
                    [
                        row.project_name,
                        f"{row.progress_percentage}%",
                        str(row.report_count),
                        str(row.invoice_total),
                        str(row.paid_total),
                    ]
                    for row in summary.projects
                ]
            ),
            Spacer(1, 12),
            Paragraph("Material Usage", styles["Heading2"]),
            Table(
                [["Item", "Issued", "Consumed"]]
                + [
                    [row.item_name, str(row.issued_quantity), str(row.consumed_quantity)]
                    for row in summary.material_usage
                ]
            ),
        ]
        doc.build(story)
        return buffer.getvalue()

    def upload_export(self, export_type: str, data: bytes, content_type: str) -> str:
        object_key = f"exports/{export_type}/{uuid4().hex}"
        client = self._client()
        if not client.bucket_exists(self.settings.minio_bucket):
            client.make_bucket(self.settings.minio_bucket)
        client.put_object(
            self.settings.minio_bucket,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return object_key

    async def _project_scope(self, actor: User, project_id: UUID | None) -> list[UUID] | None:
        self.ensure_management_access(actor)
        if project_id is not None:
            await ensure_project_access(self.session, project_id, actor)
            return [project_id]
        return await accessible_project_ids(self.session, actor)

    @staticmethod
    def _validate_date_range(date_from: date | None, date_to: date | None) -> None:
        if date_from and date_to and date_from > date_to:
            raise AppException(
                "Choose an end date on or after the start date.",
                status_code=422,
                error_code="INVALID_ANALYTICS_DATE_RANGE",
            )

    @staticmethod
    def _filter_context(
        project_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        location: str | None,
        department: str | None,
        *,
        material: bool = False,
    ) -> str:
        filters = (
            f"Project {project_id or 'all accessible'} | Activity dates {date_from or 'any'} to "
            f"{date_to or 'any'} | Scope or category text {(department or '').strip() or 'any'}"
        )
        if material:
            return f"{filters} | Project location is not applied to material movements."
        return (
            f"{filters} | Project-panel location {(location or '').strip() or 'any'} | "
            "Progress, invoiced and paid totals are cumulative."
        )

    async def _project_rows(
        self,
        project_scope: list[UUID] | None,
        date_from: date | None,
        date_to: date | None,
        location: str | None,
        department: str | None,
    ) -> list[ProjectAnalyticsRow]:
        # Each total is a correlated scalar subquery. Joining reports, invoices and payments
        # into one row set multiplies every row by the others' cardinality, which inflated
        # the sums and forced SUM(DISTINCT) to collapse invoices of equal value into one.
        report_count = select(func.count(DailyReport.id)).where(
            DailyReport.project_id == Project.id,
            DailyReport.deleted_at.is_(None),
        )
        # The date window narrows the report count only; it must never drop the project.
        if date_from:
            report_count = report_count.where(DailyReport.report_date >= date_from)
        if date_to:
            report_count = report_count.where(DailyReport.report_date <= date_to)
        invoice_total = (
            select(func.coalesce(func.sum(Invoice.total_amount), 0))
            .where(
                Invoice.project_id == Project.id,
                Invoice.deleted_at.is_(None),
                Invoice.status.notin_(NON_BILLABLE_INVOICE_STATUSES),
            )
            .scalar_subquery()
        )
        paid_total = (
            select(func.coalesce(func.sum(Payment.amount), 0))
            .select_from(Payment)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(
                Invoice.project_id == Project.id,
                Payment.deleted_at.is_(None),
                Invoice.deleted_at.is_(None),
            )
            .scalar_subquery()
        )
        query = select(
            Project.id,
            Project.name,
            Project.progress_percentage,
            report_count.scalar_subquery(),
            invoice_total,
            paid_total,
        ).where(Project.deleted_at.is_(None))
        if project_scope is not None:
            query = query.where(Project.id.in_(project_scope))
        if location and location.strip():
            query = query.where(func.lower(Project.location).like(f"%{location.strip().lower()}%"))
        if department and department.strip():
            query = query.where(
                func.lower(Project.scope_of_work).like(f"%{department.strip().lower()}%")
            )
        result = await self.session.execute(query.order_by(Project.name.asc()))
        return [
            ProjectAnalyticsRow(
                project_id=row[0],
                project_name=row[1],
                progress_percentage=Decimal(row[2] or 0),
                report_count=int(row[3] or 0),
                invoice_total=Decimal(row[4] or 0),
                paid_total=Decimal(row[5] or 0),
            )
            for row in result.all()
        ]

    async def _material_rows(
        self,
        project_scope: list[UUID] | None,
        date_from: date | None,
        date_to: date | None,
        department: str | None,
    ) -> list[MaterialUsageRow]:
        query = (
            select(
                InventoryItem.id,
                InventoryItem.name,
                func.coalesce(
                    func.sum(InventoryMovement.quantity).filter(
                        InventoryMovement.movement_type == "issue"
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(InventoryMovement.quantity).filter(
                        InventoryMovement.movement_type == "consume"
                    ),
                    0,
                ),
            )
            .outerjoin(InventoryMovement, InventoryMovement.item_id == InventoryItem.id)
            .where(InventoryItem.deleted_at.is_(None))
        )
        if project_scope is not None:
            projects = select(Project.id).where(
                Project.id.in_(project_scope), Project.deleted_at.is_(None)
            )
            query = query.where(InventoryMovement.project_id.in_(projects))
        if date_from or date_to:
            try:
                zone = ZoneInfo(self.settings.business_timezone).key
            except ZoneInfoNotFoundError:
                zone = "UTC"
            movement_day = func.date(func.timezone(zone, InventoryMovement.created_at))
            if date_from:
                query = query.where(movement_day >= date_from)
            if date_to:
                query = query.where(movement_day <= date_to)
        if department and department.strip():
            query = query.where(
                func.lower(InventoryItem.category).like(f"%{department.strip().lower()}%")
            )
        result = await self.session.execute(
            query.group_by(InventoryItem.id).order_by(InventoryItem.name.asc())
        )
        return [
            MaterialUsageRow(
                item_id=row[0],
                item_name=row[1],
                issued_quantity=Decimal(row[2] or 0),
                consumed_quantity=Decimal(row[3] or 0),
            )
            for row in result.all()
        ]

    def _client(self) -> Minio:
        return Minio(
            self.settings.minio_endpoint,
            access_key=self.settings.minio_root_user,
            secret_key=self.settings.minio_root_password,
            secure=self.settings.minio_secure,
        )


def build_xlsx(sheet_name: str, rows: list[list[str]], *, context: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("xl/workbook.xml", workbook_xml(sheet_name))
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml(rows))
        archive.writestr(
            "docProps/custom.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
            'custom-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" '
            'pid="2" name="Filter context">'
            f"<vt:lpwstr>{escape_xml(context)}</vt:lpwstr></property></Properties>",
        )
    return buffer.getvalue()


def workbook_xml(sheet_name: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="{escape_xml(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""


def worksheet_xml(rows: list[list[str]]) -> str:
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{column_letter(col_index)}{row_index}"
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape_xml(value)}</t></is></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>{"".join(row_xml)}</sheetData>
</worksheet>"""


def column_letter(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def escape_xml(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/docProps/custom.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>'
    "</Types>"
)
ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/>'
    '<Relationship Id="rId2" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" '
    'Target="docProps/custom.xml"/>'
    "</Relationships>"
)
WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    'Target="worksheets/sheet1.xml"/>'
    "</Relationships>"
)
