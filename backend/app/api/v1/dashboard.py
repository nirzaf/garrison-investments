from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.dashboard import DashboardSummaryResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    current_user: CurrentUser,
    session: DbSession,
) -> DashboardSummaryResponse:
    return await DashboardService(session).summary(current_user)
