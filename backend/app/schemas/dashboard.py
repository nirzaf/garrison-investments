from pydantic import BaseModel


class DashboardSummaryResponse(BaseModel):
    active_projects: int
    pending_reports: int
    approved_reports: int
    pending_documents: int
    unread_notifications: int
    recent_activity: list[str]
