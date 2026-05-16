from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ProjectAnalyticsRow(BaseModel):
    project_id: UUID
    project_name: str
    progress_percentage: Decimal
    report_count: int
    invoice_total: Decimal
    paid_total: Decimal


class MaterialUsageRow(BaseModel):
    item_id: UUID
    item_name: str
    issued_quantity: Decimal
    consumed_quantity: Decimal


class AnalyticsSummaryResponse(BaseModel):
    projects: list[ProjectAnalyticsRow]
    material_usage: list[MaterialUsageRow]


class ExportTaskResponse(BaseModel):
    task_id: str
    status: str
