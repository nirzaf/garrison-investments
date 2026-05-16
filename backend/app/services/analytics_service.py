from decimal import Decimal
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_report import DailyReport
from app.models.finance import Invoice, Payment
from app.models.inventory import InventoryItem, InventoryMovement
from app.models.project import Project
from app.models.user import User
from app.schemas.analytics import AnalyticsSummaryResponse, MaterialUsageRow, ProjectAnalyticsRow
from app.services.finance_service import FINANCE_ROLES
from app.utils.exceptions import AppException
from app.utils.permissions import ROLE_ADMIN, ROLE_GENERAL_MANAGER, ROLE_OPERATION_MANAGER

MANAGEMENT_ROLES = {ROLE_ADMIN, ROLE_GENERAL_MANAGER, ROLE_OPERATION_MANAGER}


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def ensure_management_access(self, actor: User) -> None:
        if actor.role not in MANAGEMENT_ROLES and actor.role not in FINANCE_ROLES:
            raise AppException(
                "Management analytics are restricted.",
                status_code=403,
                error_code="ANALYTICS_FORBIDDEN",
            )

    async def summary(self, actor: User) -> AnalyticsSummaryResponse:
        self.ensure_management_access(actor)
        projects = await self._project_rows()
        usage = await self._material_rows()
        return AnalyticsSummaryResponse(projects=projects, material_usage=usage)

    async def project_progress_export(self, actor: User) -> bytes:
        rows = await self._project_rows_for_export(actor)
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
        )

    async def material_usage_export(self, actor: User) -> bytes:
        self.ensure_management_access(actor)
        rows = await self._material_rows()
        return build_xlsx(
            "Material Usage",
            [["Item", "Issued Quantity", "Consumed Quantity"]]
            + [
                [row.item_name, str(row.issued_quantity), str(row.consumed_quantity)]
                for row in rows
            ],
        )

    async def _project_rows_for_export(self, actor: User) -> list[ProjectAnalyticsRow]:
        self.ensure_management_access(actor)
        return await self._project_rows()

    async def _project_rows(self) -> list[ProjectAnalyticsRow]:
        result = await self.session.execute(
            select(
                Project.id,
                Project.name,
                Project.progress_percentage,
                func.count(func.distinct(DailyReport.id)),
                func.coalesce(func.sum(func.distinct(Invoice.total_amount)), 0),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .outerjoin(DailyReport, DailyReport.project_id == Project.id)
            .outerjoin(Invoice, Invoice.project_id == Project.id)
            .outerjoin(Payment, Payment.invoice_id == Invoice.id)
            .where(Project.deleted_at.is_(None))
            .group_by(Project.id)
            .order_by(Project.name.asc())
        )
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

    async def _material_rows(self) -> list[MaterialUsageRow]:
        result = await self.session.execute(
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
            .group_by(InventoryItem.id)
            .order_by(InventoryItem.name.asc())
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


def build_xlsx(sheet_name: str, rows: list[list[str]]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("xl/workbook.xml", workbook_xml(sheet_name))
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml(rows))
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
    "</Types>"
)
ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/>'
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
