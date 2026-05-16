from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.daily_report import (
    DailyReport,
    DailyReportApprovalHistory,
    ReportEquipment,
    ReportManpower,
    ReportMaterialConsumption,
)


class DailyReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, report: DailyReport) -> DailyReport:
        self.session.add(report)
        await self.session.flush()
        return report

    async def get_by_id(self, report_id: UUID) -> DailyReport | None:
        result = await self.session.execute(
            self._with_children().where(
                DailyReport.id == report_id,
                DailyReport.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_reports(
        self,
        *,
        project_id: UUID | None,
        project_ids: list[UUID] | None,
        engineer_id: UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DailyReport], int]:
        query: Select = self._with_children().where(DailyReport.deleted_at.is_(None))
        if project_id:
            query = query.where(DailyReport.project_id == project_id)
        elif project_ids is not None:
            query = query.where(DailyReport.project_id.in_(project_ids))
        if engineer_id:
            query = query.where(DailyReport.engineer_id == engineer_id)
        if status:
            query = query.where(DailyReport.status == status)
        total = await self.session.scalar(
            select(func.count()).select_from(query.with_only_columns(DailyReport.id).subquery())
        )
        result = await self.session.execute(
            query.order_by(DailyReport.report_date.desc(), DailyReport.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().unique().all()), int(total or 0)

    async def next_report_sequence(self, project_id: UUID, report_date: object) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(DailyReport)
            .where(
                DailyReport.project_id == project_id,
                DailyReport.report_date == report_date,
                DailyReport.report_number.is_not(None),
                DailyReport.deleted_at.is_(None),
            )
        )
        return int(total or 0) + 1

    async def replace_children(
        self,
        report: DailyReport,
        *,
        manpower_entries: list[ReportManpower],
        equipment_entries: list[ReportEquipment],
        material_consumption: list[ReportMaterialConsumption],
    ) -> None:
        await self.session.execute(
            delete(ReportManpower).where(ReportManpower.report_id == report.id)
        )
        await self.session.execute(
            delete(ReportEquipment).where(ReportEquipment.report_id == report.id)
        )
        await self.session.execute(
            delete(ReportMaterialConsumption).where(
                ReportMaterialConsumption.report_id == report.id
            )
        )
        for entry in [*manpower_entries, *equipment_entries, *material_consumption]:
            self.session.add(entry)
        await self.session.flush()

    async def add_history(self, history: DailyReportApprovalHistory) -> DailyReportApprovalHistory:
        self.session.add(history)
        await self.session.flush()
        return history

    def _with_children(self) -> Select:
        return select(DailyReport).options(
            selectinload(DailyReport.manpower_entries),
            selectinload(DailyReport.equipment_entries),
            selectinload(DailyReport.material_consumption),
            selectinload(DailyReport.approval_history),
        )
