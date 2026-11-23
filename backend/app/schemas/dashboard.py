from pydantic import BaseModel


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
