from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.dashboard import (
    AnniversaryPageResponse,
    BirthdayPageResponse,
    DashboardSummaryResponse,
)
from app.services.dashboard_service import DashboardService
from app.utils.exceptions import PermissionDeniedException
from app.utils.permissions import BUSINESS_ROLES

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    current_user: CurrentUser,
    session: DbSession,
) -> DashboardSummaryResponse:
    return await DashboardService(session).summary(current_user)


def _require_business_user(current_user: CurrentUser) -> None:
    if current_user.role not in BUSINESS_ROLES:
        raise PermissionDeniedException("view employee celebrations")


@router.get("/birthdays", response_model=BirthdayPageResponse)
async def upcoming_birthdays(
    current_user: CurrentUser,
    session: DbSession,
    response: Response,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> BirthdayPageResponse:
    _require_business_user(current_user)
    response.headers["Cache-Control"] = "private, no-store"
    return await DashboardService(session).upcoming_birthdays(offset=offset, limit=limit)


@router.get("/anniversaries", response_model=AnniversaryPageResponse)
async def upcoming_anniversaries(
    current_user: CurrentUser,
    session: DbSession,
    response: Response,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AnniversaryPageResponse:
    _require_business_user(current_user)
    response.headers["Cache-Control"] = "private, no-store"
    return await DashboardService(session).upcoming_anniversaries(offset=offset, limit=limit)
