from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials

from app.api.dependencies import DbSession, RequestMetadata, bearer_scheme
from app.config import get_settings
from app.schemas.auth import LoginRequest, VerifyOtpRequest
from app.schemas.super_admin import SuperAdminChallenge, SuperAdminOverview, SuperAdminToken
from app.services.auth_service import AuthService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.security import utc_now

PORTAL_HOST = "superadmin.garrisons.lk"


def require_portal_host(request: Request, response: Response) -> None:
    settings = get_settings()
    # The temporary OTP implementation uses business identity records.
    # Keep it confined to synthetic tests until separate operator auth exists.
    if (
        settings.app_env != "test"
        or not settings.super_admin_enabled
        or settings.support_portal_enabled
        or request.headers.get("host") != PORTAL_HOST
    ):
        raise NotFoundException("Super Admin portal")
    if request.method == "POST" and request.headers.get("origin") != f"https://{PORTAL_HOST}":
        raise AppException("Request origin is not allowed.", status_code=403)
    response.headers["Cache-Control"] = "no-store"


def portal_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    if not credentials:
        raise AppException("Authentication required.", status_code=401, error_code="AUTH_REQUIRED")
    return credentials.credentials


PortalToken = Annotated[str, Depends(portal_token)]
router = APIRouter(
    prefix="/super-admin",
    tags=["Super Admin"],
    dependencies=[Depends(require_portal_host)],
)


@router.post("/auth/login", response_model=SuperAdminChallenge)
async def login(
    payload: LoginRequest, session: DbSession, meta: RequestMetadata
) -> SuperAdminChallenge:
    challenge = await AuthService(session).create_technical_login_challenge(
        payload.email, payload.password, meta
    )
    return SuperAdminChallenge(challenge_id=challenge.id, expires_at=challenge.expires_at)


@router.post("/auth/verify-otp", response_model=SuperAdminToken)
async def verify_otp(
    payload: VerifyOtpRequest, session: DbSession, meta: RequestMetadata
) -> SuperAdminToken:
    result = await AuthService(session).verify_technical_login(
        payload.challenge_id, payload.otp, meta
    )
    return SuperAdminToken(access_token=result.access_token, expires_at=result.expires_at)


@router.post("/auth/logout", status_code=204, response_class=Response)
async def logout(
    token: PortalToken, session: DbSession, meta: RequestMetadata, response: Response
) -> Response:
    await AuthService(session).logout_technical_session(token, meta)
    response.status_code = 204
    return response


@router.get("/overview", response_model=SuperAdminOverview)
async def read_overview(token: PortalToken, session: DbSession) -> SuperAdminOverview:
    await AuthService(session).get_technical_session(token)
    return SuperAdminOverview(observed_at=utc_now())
