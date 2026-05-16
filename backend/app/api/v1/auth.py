from typing import Annotated

from fastapi import APIRouter, Cookie, Response

from app.api.dependencies import CurrentUser, DbSession, RequestMetadata
from app.config import get_settings
from app.models.user import User
from app.schemas.auth import (
    AuthUserResponse,
    LoginChallengeResponse,
    LoginRequest,
    MessageResponse,
    PasswordChangeRequest,
    PasswordResetChallengeResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshResponse,
    TokenResponse,
    VerifyOtpRequest,
)
from app.services.auth_service import AuthService
from app.utils.exceptions import AppException
from app.utils.permissions import permissions_for_role

router = APIRouter(prefix="/auth", tags=["Authentication"])
REFRESH_COOKIE_NAME = "refresh_token"


def _set_refresh_cookie(response: Response, token: str, max_age: int) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.app_env.lower() not in {"development", "test", "local"},
        samesite="strict",
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/v1/auth")


def _auth_user_response(user: User) -> AuthUserResponse:
    data = AuthUserResponse.model_validate(user)
    data.permissions = permissions_for_role(user.role)
    return data


@router.post("/login", response_model=LoginChallengeResponse)
async def login(
    payload: LoginRequest,
    session: DbSession,
    meta: RequestMetadata,
) -> LoginChallengeResponse:
    result = await AuthService(session).login(payload.email, payload.password, meta)
    expires_in = int((result.challenge.expires_at - result.challenge.created_at).total_seconds())
    return LoginChallengeResponse(
        challenge_id=result.challenge.id,
        expires_at=result.challenge.expires_at,
        expires_in_seconds=expires_in,
        dev_otp=result.otp,
    )


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(
    payload: VerifyOtpRequest,
    response: Response,
    session: DbSession,
    meta: RequestMetadata,
) -> TokenResponse:
    result = await AuthService(session).verify_otp(payload.challenge_id, payload.otp, meta)
    _set_refresh_cookie(response, result.refresh_token, result.refresh_expires_in_seconds)
    return TokenResponse(
        access_token=result.access_token,
        expires_in_seconds=result.access_expires_in_seconds,
        user=_auth_user_response(result.user),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    response: Response,
    session: DbSession,
    meta: RequestMetadata,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> RefreshResponse:
    if not refresh_token:
        raise AppException(
            "Refresh session is missing.",
            status_code=401,
            error_code="REFRESH_TOKEN_MISSING",
        )
    result = await AuthService(session).refresh(refresh_token, meta)
    _set_refresh_cookie(response, result.refresh_token, result.refresh_expires_in_seconds)
    return RefreshResponse(
        access_token=result.access_token,
        expires_in_seconds=result.access_expires_in_seconds,
        user=_auth_user_response(result.user),
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    session: DbSession,
    meta: RequestMetadata,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> MessageResponse:
    await AuthService(session).logout(refresh_token, meta)
    _clear_refresh_cookie(response)
    return MessageResponse(message="Signed out.")


@router.get("/me", response_model=AuthUserResponse)
async def me(current_user: CurrentUser) -> AuthUserResponse:
    return _auth_user_response(current_user)


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    payload: PasswordChangeRequest,
    current_user: CurrentUser,
    session: DbSession,
    meta: RequestMetadata,
) -> MessageResponse:
    await AuthService(session).change_password(
        current_user,
        payload.current_password,
        payload.new_password,
        meta,
    )
    return MessageResponse(message="Password updated.")


@router.post("/password-reset/request", response_model=PasswordResetChallengeResponse)
async def request_password_reset(
    payload: PasswordResetRequest,
    session: DbSession,
    meta: RequestMetadata,
) -> PasswordResetChallengeResponse:
    result = await AuthService(session).request_password_reset(payload.email, meta)
    message = "If the account exists, a password reset code has been sent."
    if not result:
        return PasswordResetChallengeResponse(message=message)
    expires_in = int((result.challenge.expires_at - result.challenge.created_at).total_seconds())
    return PasswordResetChallengeResponse(
        challenge_id=result.challenge.id,
        expires_at=result.challenge.expires_at,
        expires_in_seconds=expires_in,
        dev_otp=result.otp,
        message=message,
    )


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    session: DbSession,
    meta: RequestMetadata,
) -> MessageResponse:
    await AuthService(session).confirm_password_reset(
        payload.challenge_id,
        payload.otp,
        payload.new_password,
        meta,
    )
    return MessageResponse(message="Password reset complete.")
