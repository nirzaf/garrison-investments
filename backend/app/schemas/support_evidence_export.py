from datetime import datetime, timedelta
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.support_request_logs import SupportRequestLogQuery

ExportReason = Literal["incident_review", "audit_review"]
ExportStage = Literal["review", "download"]
MAX_EXPORT_ROWS = 10_000
MAX_EXPORT_BYTES = 10 * 1024 * 1024


class SupportEvidenceFilters(SupportRequestLogQuery):
    max_window: ClassVar[timedelta] = timedelta(days=7)
    limit: int = Field(default=MAX_EXPORT_ROWS, ge=1, le=MAX_EXPORT_ROWS)


class SupportEvidenceExportCreate(BaseModel, extra="forbid"):
    filters: SupportEvidenceFilters
    reason: ExportReason


class SupportEvidenceExportRead(BaseModel):
    authorization_mode: Literal["paired", "single_owner"] = "paired"
    id: UUID
    case_id: UUID
    filters: SupportEvidenceFilters
    reason: ExportReason
    row_count: int
    truncated: bool
    sha256: str
    expires_at: datetime
    approved_at: datetime | None
    downloaded_at: datetime | None
