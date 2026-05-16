from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report_export import ReportExport


class ReportExportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, export: ReportExport) -> ReportExport:
        self.session.add(export)
        await self.session.flush()
        return export

    async def latest_for_report(self, report_id: UUID) -> ReportExport | None:
        result = await self.session.execute(
            select(ReportExport)
            .where(ReportExport.report_id == report_id, ReportExport.deleted_at.is_(None))
            .order_by(ReportExport.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, export_id: UUID) -> ReportExport | None:
        result = await self.session.execute(
            select(ReportExport).where(
                ReportExport.id == export_id,
                ReportExport.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()
