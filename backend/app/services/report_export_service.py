import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from uuid import UUID

from minio import Minio, S3Error
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.daily_report import DailyReport
from app.models.report_export import ReportExport
from app.models.user import User
from app.repositories.report_export_repository import ReportExportRepository
from app.services.audit_service import AuditService
from app.services.report_service import ReportService
from app.services.storage_service import minio_client
from app.utils.exceptions import AppException
from app.utils.security import utc_now

PDF_CONTENT_TYPE = "application/pdf"


@dataclass(frozen=True)
class ReportPdfData:
    """Plain-data snapshot of a report, safe to render on a worker thread.

    Rendering reads every field it needs up front on the event loop, so the worker never
    touches an ORM instance or the session and cannot trigger a lazy load off-greenlet.
    """

    report_number: str
    status: str
    report_date: str
    day_type: str
    work_location: str
    weather: str
    progress: str
    submitted_at: str
    approved_at: str
    work_completed: str
    next_day_plan: str
    site_visitors: str
    subcontractors: str
    safety_incidents: str
    safety_notes: str
    wir_number: str
    wir_status: str
    inspection_status: str
    delay_notes: str
    manpower: tuple[tuple[str, str, str], ...]
    equipment: tuple[tuple[str, str, str, str], ...]
    materials: tuple[tuple[str, str, str, str], ...]


def report_pdf_data(report: DailyReport) -> ReportPdfData:
    extra = report.extra_fields
    return ReportPdfData(
        report_number=report.report_number or "-",
        status=report.status,
        report_date=report.report_date.isoformat(),
        day_type=str(extra.get("day_type") or "-"),
        work_location=report.work_location,
        weather=str(extra.get("weather_condition") or "-"),
        progress=f"{report.progress_percentage}%",
        submitted_at=report.submitted_at.isoformat() if report.submitted_at else "-",
        approved_at=report.approved_at.isoformat() if report.approved_at else "-",
        work_completed=report.work_completed,
        next_day_plan=report.next_day_plan,
        site_visitors=str(extra.get("site_visitors") or "-"),
        subcontractors=str(extra.get("subcontractors") or "-"),
        safety_incidents=str(report.safety_incidents),
        safety_notes=report.safety_notes or "-",
        wir_number=str(extra.get("wir_number") or "-"),
        wir_status=report.wir_status,
        inspection_status=report.inspection_status,
        delay_notes=report.delay_notes or "-",
        manpower=tuple(
            (entry.trade, str(entry.count), str(entry.overtime_hours))
            for entry in report.manpower_entries
        ),
        equipment=tuple(
            (
                entry.equipment_name,
                str(entry.quantity),
                str(entry.hours_used),
                entry.remarks or "-",
            )
            for entry in report.equipment_entries
        ),
        materials=tuple(
            (entry.material_name, entry.unit, str(entry.quantity), entry.remarks or "-")
            for entry in report.material_consumption
        ),
    )


class ReportExportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.exports = ReportExportRepository(session)
        self.audit = AuditService(session)

    async def generate_pdf_export(
        self, report_id: UUID, actor: User | None = None, *, reuse_existing: bool = False
    ) -> ReportExport:
        report = await ReportService(self.session).get_report_for_export(report_id, for_update=True)
        if report.status != "approved":
            raise AppException(
                "Only approved reports can be exported.",
                status_code=409,
                error_code="REPORT_EXPORT_REQUIRES_APPROVAL",
            )
        if reuse_existing:
            existing = await self.exports.latest_for_report(report.id)
            if existing is not None:
                return existing
        pdf_bytes = await asyncio.to_thread(self.build_pdf, report_pdf_data(report))
        file_name = f"{report.report_number or report.id}.pdf"
        object_key = f"reports/{report.project_id}/{report.id}/{file_name}"
        await asyncio.to_thread(self._upload_pdf, object_key, pdf_bytes)
        export = await self.exports.add(
            ReportExport(
                report_id=report.id,
                generated_by=actor.id if actor else None,
                file_name=file_name,
                object_key=object_key,
                content_type=PDF_CONTENT_TYPE,
                status="ready",
                generated_at=utc_now(),
            )
        )
        await self.audit.record(
            action="report_exports.generated",
            user_id=actor.id if actor else None,
            entity_type="daily_reports",
            entity_id=report.id,
            new_values={
                "object_key": object_key,
                "template": self.settings.report_pdf_template_name,
            },
        )
        await self.session.commit()
        return export

    async def get_or_create_pdf(self, report_id: UUID, actor: User) -> tuple[ReportExport, bytes]:
        report = await ReportService(self.session).get_report(report_id, actor)
        if report.status != "approved":
            raise AppException(
                "Only approved reports can be downloaded as PDF.",
                status_code=409,
                error_code="REPORT_EXPORT_REQUIRES_APPROVAL",
            )
        export = await self.exports.latest_for_report(report.id)
        if not export:
            export = await self.generate_pdf_export(report.id, actor, reuse_existing=True)
        await self.audit.record(
            action="report_exports.downloaded",
            user_id=actor.id,
            entity_type="daily_reports",
            entity_id=report.id,
            new_values={
                "export_id": str(export.id),
                "file_name": export.file_name,
                "object_key": export.object_key,
            },
        )
        await self.session.commit()
        try:
            return export, await asyncio.to_thread(self._download_pdf, export.object_key)
        except S3Error as exc:
            if exc.code not in {"NoSuchKey", "NoSuchBucket"}:
                raise
            export = await self.generate_pdf_export(report.id, actor)
            return export, await asyncio.to_thread(self._download_pdf, export.object_key)

    def build_pdf(self, data: ReportPdfData) -> bytes:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36,
        )
        styles = getSampleStyleSheet()
        story = [
            Paragraph("Garrisons Investments - Daily Site Report", styles["Title"]),
            Paragraph(f"Template: {self.settings.report_pdf_template_name}", styles["Normal"]),
            Spacer(1, 12),
            self._table(
                [
                    ["Report Number", data.report_number],
                    ["Status", data.status],
                    ["Report Date", data.report_date],
                    ["Day Type", data.day_type],
                    ["Work Location", data.work_location],
                    ["Weather", data.weather],
                    ["Progress", data.progress],
                    ["Submitted At", data.submitted_at],
                    ["Approved At", data.approved_at],
                ]
            ),
            Spacer(1, 12),
            Paragraph("Work Completed", styles["Heading2"]),
            Paragraph(data.work_completed, styles["BodyText"]),
            Spacer(1, 8),
            Paragraph("Next-Day Plan", styles["Heading2"]),
            Paragraph(data.next_day_plan, styles["BodyText"]),
            Spacer(1, 8),
            Paragraph("Site Coordination", styles["Heading2"]),
            self._table(
                [
                    ["Site Visitors", data.site_visitors],
                    ["Subcontractors", data.subcontractors],
                ]
            ),
            Spacer(1, 8),
            Paragraph("Safety And Inspections", styles["Heading2"]),
            self._table(
                [
                    ["Safety Incidents", data.safety_incidents],
                    ["Safety Notes", data.safety_notes],
                    ["WIR Number", data.wir_number],
                    ["WIR Status", data.wir_status],
                    ["Inspection Status", data.inspection_status],
                    ["Delay Notes", data.delay_notes],
                ]
            ),
            Spacer(1, 8),
            Paragraph("Manpower", styles["Heading2"]),
            self._table([["Trade", "Count", "Overtime"], *data.manpower]),
            Spacer(1, 8),
            Paragraph("Equipment", styles["Heading2"]),
            self._table([["Equipment", "Qty", "Hours", "Remarks"], *data.equipment]),
            Spacer(1, 8),
            Paragraph("Material Consumption", styles["Heading2"]),
            self._table([["Material", "Unit", "Qty", "Remarks"], *data.materials]),
        ]
        doc.build(story)
        return buffer.getvalue()

    def _table(self, rows: Sequence[Sequence[str]]) -> Table:
        table = Table(rows, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    def _client(self) -> Minio:
        return minio_client(self.settings)

    def _upload_pdf(self, object_key: str, data: bytes) -> None:
        client = self._client()
        if not client.bucket_exists(self.settings.minio_bucket):
            client.make_bucket(self.settings.minio_bucket)
        client.put_object(
            self.settings.minio_bucket,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=PDF_CONTENT_TYPE,
        )

    def _download_pdf(self, object_key: str) -> bytes:
        response = self._client().get_object(self.settings.minio_bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
