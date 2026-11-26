from pydantic import BaseModel, ConfigDict, Field


class BirthdayItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    day: int = Field(ge=1, le=31)
    month: int = Field(ge=1, le=12)


class BirthdayPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BirthdayItem]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class AnniversaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    day: int = Field(ge=1, le=31)
    month: int = Field(ge=1, le=12)
    completed_years: int = Field(ge=1)


class AnniversaryPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AnniversaryItem]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class SiteOperationsSummary(BaseModel):
    confirmed_progress: int
    progress_awaiting_review: int
    material_requests_awaiting_review: int
    registrations_awaiting_review: int
    confirmed_registrations: int
    confirmed_present_today: int


class DashboardSummaryResponse(BaseModel):
    active_projects: int
    pending_reports: int
    approved_reports: int
    pending_documents: int
    unread_notifications: int
    recent_activity: list[str]
    site_operations: SiteOperationsSummary | None = None
