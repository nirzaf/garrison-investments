from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.approvals import router as approvals_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.documents import router as documents_router
from app.api.v1.finance import router as finance_router
from app.api.v1.imports import router as imports_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.logs import router as logs_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.photos import router as photos_router
from app.api.v1.projects import router as projects_router
from app.api.v1.reports import router as reports_router
from app.api.v1.supervisor_updates import router as supervisor_updates_router
from app.api.v1.suppliers import router as suppliers_router
from app.api.v1.users import router as users_router
from app.utils.exceptions import AppErrorResponse, ValidationErrorResponse

router = APIRouter(tags=["Root"])


@router.get("/")
async def api_root() -> dict[str, str]:
    return {
        "name": "Construction Internal Portal API",
        "version": "v1",
        "status": "ready",
    }


api_router = APIRouter(
    responses={
        422: {"model": ValidationErrorResponse | AppErrorResponse, "description": "Invalid request"}
    }
)
api_router.include_router(router)
api_router.include_router(analytics_router)
api_router.include_router(approvals_router)
api_router.include_router(auth_router)
api_router.include_router(audit_router)
api_router.include_router(dashboard_router)
api_router.include_router(documents_router)
api_router.include_router(finance_router)
api_router.include_router(imports_router)
api_router.include_router(inventory_router)
api_router.include_router(logs_router)
api_router.include_router(notifications_router)
api_router.include_router(photos_router)
api_router.include_router(projects_router)
api_router.include_router(reports_router)
api_router.include_router(supervisor_updates_router)
api_router.include_router(suppliers_router)
api_router.include_router(users_router)
