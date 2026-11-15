import asyncio
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.auth import AuthOtpChallenge, AuthRefreshToken
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.email_service import EmailDeliveryError, EmailService
from app.utils.exceptions import AppException
from app.utils.permissions import VALID_ROLES
from app.utils.security import (
    create_access_token,
    decode_access_token,
    generate_otp,
    generate_refresh_token,
    hash_password,
    hash_secret,
    utc_now,
    validate_password_policy,
    verify_password,
)

LOGIN_FAILURE_MESSAGE = "Invalid email, password, or verification code."


@dataclass(frozen=True)
class RequestMeta:
    request_id: str | None = None
    session_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    endpoint: str | None = None
    method: str | None = None


@dataclass(frozen=True)
class OtpChallengeResult:
    challenge: AuthOtpChallenge
    otp: str | None


@dataclass(frozen=True)
class SessionResult:
    user: User
    access_token: str
    access_expires_in_seconds: int
    refresh_token: str
    refresh_expires_in_seconds: int


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.users = UserRepository(session)
        self.auth = AuthRepository(session)
        self.audit = AuditService(session)
        self.email = EmailService()

    async def login(self, email: str, password: str, meta: RequestMeta) -> OtpChallengeResult:
        user = await self.users.get_by_email(email, for_update=True)
        if (
            not user
            or not user.is_active
            or user.role not in VALID_ROLES
            or not verify_password(password, user.password_hash)
        ):
            if user:
                await self._register_failed_login(user, meta)
            raise AppException(LOGIN_FAILURE_MESSAGE, status_code=401, error_code="LOGIN_FAILED")

        now = utc_now()
        if user.locked_until and user.locked_until > now:
            raise AppException(
                "Account is temporarily locked. Try again later.",
                status_code=423,
                error_code="ACCOUNT_LOCKED",
            )

        otp = generate_otp()
        challenge = await self.auth.add_otp_challenge(
            AuthOtpChallenge(
                user_id=user.id,
                purpose="login",
                otp_hash=hash_secret(otp),
                expires_at=now + timedelta(minutes=self.settings.otp_expire_minutes),
            )
        )
        await self.audit.record(
            action="auth.login_otp_created",
            user_id=user.id,
            ip_address=meta.ip_address,
            user_agent=meta.user_agent,
        )
        await self.session.commit()
        await self._send_otp(
            challenge,
            recipient=user.email,
            subject="Your Verification Code",
            body=(
                f"Your verification code is: {otp}\n\n"
                f"This code expires in {self.settings.otp_expire_minutes} minutes."
            ),
        )
        return OtpChallengeResult(
            challenge=challenge,
            otp=otp if self.settings.should_expose_dev_otp else None,
        )

    async def verify_otp(self, challenge_id: UUID, otp: str, meta: RequestMeta) -> SessionResult:
        challenge, user = await self._get_otp_for_update(challenge_id)
        now = utc_now()
        max_attempts = self.settings.auth_failed_attempt_limit
        if not challenge or challenge.attempts >= max_attempts:
            raise AppException(LOGIN_FAILURE_MESSAGE, status_code=401, error_code="OTP_FAILED")

        otp_matches = challenge.otp_hash == hash_secret(otp) or (
            challenge.purpose == "login"
            and self.settings.staging_login_otp_enabled
            and otp == self.settings.staging_login_otp
        )

        if (
            challenge.purpose != "login"
            or challenge.consumed_at is not None
            or challenge.expires_at <= now
            or not otp_matches
        ):
            challenge.attempts += 1
            if challenge.attempts >= max_attempts:
                challenge.consumed_at = now
            await self.session.commit()
            raise AppException(LOGIN_FAILURE_MESSAGE, status_code=401, error_code="OTP_FAILED")

        if not user or not user.is_active or user.role not in VALID_ROLES:
            raise AppException(LOGIN_FAILURE_MESSAGE, status_code=401, error_code="OTP_FAILED")

        challenge.consumed_at = now
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        await self.audit.record(
            action="auth.login_success",
            user_id=user.id,
            ip_address=meta.ip_address,
            user_agent=meta.user_agent,
        )
        result = await self._create_session(user)
        await self.session.commit()
        return result

    async def refresh(self, refresh_token: str, meta: RequestMeta) -> SessionResult:
        token_hash = hash_secret(refresh_token)
        token = await self.auth.get_refresh_token_by_hash(token_hash)
        user = await self.users.get_by_id(token.user_id, for_update=True) if token else None
        if user:
            token = await self.auth.get_refresh_token_by_hash(token_hash, for_update=True)
        now = utc_now()
        if (
            not user
            or not user.is_active
            or user.role not in VALID_ROLES
            or not token
            or token.revoked_at
            or token.expires_at <= now
        ):
            raise AppException(
                "Refresh session is invalid or expired.",
                status_code=401,
                error_code="REFRESH_TOKEN_INVALID",
            )

        token.revoked_at = now
        result = await self._create_session(user)
        await self.audit.record(
            action="auth.refresh",
            user_id=user.id,
            ip_address=meta.ip_address,
            user_agent=meta.user_agent,
        )
        await self.session.commit()
        return result

    async def logout(self, refresh_token: str | None, meta: RequestMeta) -> None:
        if refresh_token:
            token = await self.auth.get_refresh_token_by_hash(hash_secret(refresh_token))
            if token and not token.revoked_at:
                token.revoked_at = utc_now()
                await self.audit.record(
                    action="auth.logout",
                    user_id=token.user_id,
                    ip_address=meta.ip_address,
                    user_agent=meta.user_agent,
                )
                await self.session.commit()

    async def get_user_from_access_token(self, token: str) -> User:
        payload = decode_access_token(token)
        user = await self.users.get_by_id(UUID(payload["sub"]))
        if (
            not user
            or not user.is_active
            or user.role not in VALID_ROLES
            or payload.get("access_revision", 0) != user.access_revision
        ):
            raise AppException(
                "Invalid or expired session.",
                status_code=401,
                error_code="INVALID_TOKEN",
            )
        return user

    async def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
        meta: RequestMeta,
    ) -> None:
        locked_user = await self.users.get_by_id(user.id, for_update=True)
        if (
            not locked_user
            or not locked_user.is_active
            or not verify_password(current_password, locked_user.password_hash)
        ):
            raise AppException(
                "Current password is incorrect.",
                status_code=400,
                error_code="CURRENT_PASSWORD_INCORRECT",
            )
        validate_password_policy(new_password)
        locked_user.password_hash = hash_password(new_password)
        locked_user.must_change_password = False
        await self.auth.revoke_user_authentication(locked_user.id)
        await self.audit.record(
            action="auth.password_changed",
            user_id=user.id,
            ip_address=meta.ip_address,
            user_agent=meta.user_agent,
        )
        await self.session.commit()

    async def request_password_reset(
        self,
        email: str,
        meta: RequestMeta,
    ) -> OtpChallengeResult | None:
        user = await self.users.get_by_email(email, for_update=True)
        if not user or not user.is_active or user.role not in VALID_ROLES:
            return None
        otp = generate_otp()
        challenge = await self.auth.add_otp_challenge(
            AuthOtpChallenge(
                user_id=user.id,
                purpose="password_reset",
                otp_hash=hash_secret(otp),
                expires_at=utc_now() + timedelta(minutes=self.settings.otp_expire_minutes),
            )
        )
        await self.audit.record(
            action="auth.password_reset_otp_created",
            user_id=user.id,
            ip_address=meta.ip_address,
            user_agent=meta.user_agent,
        )
        await self.session.commit()
        await self._send_otp(
            challenge,
            recipient=user.email,
            subject="Password Reset Code",
            body=(
                f"Your password reset code is: {otp}\n\n"
                f"This code expires in {self.settings.otp_expire_minutes} minutes."
            ),
        )
        return OtpChallengeResult(
            challenge=challenge,
            otp=otp if self.settings.should_expose_dev_otp else None,
        )

    async def _send_otp(
        self,
        challenge: AuthOtpChallenge,
        *,
        recipient: str,
        subject: str,
        body: str,
    ) -> None:
        try:
            delivered = await asyncio.to_thread(
                self.email.send, recipients=[recipient], subject=subject, body=body
            )
            if delivered <= 0:
                raise EmailDeliveryError("No recipient accepted the OTP email.")
        except EmailDeliveryError:
            if self.settings.should_expose_dev_otp or (
                challenge.purpose == "login" and self.settings.staging_login_otp_enabled
            ):
                return
            challenge.consumed_at = utc_now()
            await self.session.commit()
            raise AppException(
                "Email delivery is unavailable. Try again shortly.",
                status_code=503,
                error_code="EMAIL_DELIVERY_UNAVAILABLE",
            ) from None

    async def confirm_password_reset(
        self,
        challenge_id: UUID,
        otp: str,
        new_password: str,
        meta: RequestMeta,
    ) -> None:
        validate_password_policy(new_password)
        challenge, user = await self._get_otp_for_update(challenge_id)
        now = utc_now()
        max_attempts = self.settings.auth_failed_attempt_limit
        if not challenge or challenge.attempts >= max_attempts:
            raise AppException(
                "Invalid or expired password reset code.",
                status_code=401,
                error_code="PASSWORD_RESET_FAILED",
            )
        if (
            challenge.purpose != "password_reset"
            or challenge.consumed_at is not None
            or challenge.expires_at <= now
            or challenge.otp_hash != hash_secret(otp)
        ):
            challenge.attempts += 1
            if challenge.attempts >= max_attempts:
                challenge.consumed_at = now
            await self.session.commit()
            raise AppException(
                "Invalid or expired password reset code.",
                status_code=401,
                error_code="PASSWORD_RESET_FAILED",
            )
        if not user or not user.is_active or user.role not in VALID_ROLES:
            raise AppException(
                "Invalid or expired password reset code.",
                status_code=401,
                error_code="PASSWORD_RESET_FAILED",
            )
        challenge.consumed_at = now
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.auth.revoke_user_authentication(user.id)
        await self.audit.record(
            action="auth.password_reset_completed",
            user_id=user.id,
            ip_address=meta.ip_address,
            user_agent=meta.user_agent,
        )
        await self.session.commit()

    async def _get_otp_for_update(
        self, challenge_id: UUID
    ) -> tuple[AuthOtpChallenge | None, User | None]:
        challenge = await self.auth.get_otp_challenge(challenge_id)
        if not challenge:
            return None, None
        user = await self.users.get_by_id(challenge.user_id, for_update=True)
        if not user:
            return None, None
        return await self.auth.get_otp_challenge(challenge_id, for_update=True), user

    async def _register_failed_login(self, user: User, meta: RequestMeta) -> None:
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= self.settings.auth_failed_attempt_limit:
            user.locked_until = utc_now() + timedelta(minutes=self.settings.account_lockout_minutes)
        await self.audit.record(
            action="auth.login_failed",
            user_id=user.id,
            ip_address=meta.ip_address,
            user_agent=meta.user_agent,
        )
        await self.session.commit()

    async def _create_session(self, user: User) -> SessionResult:
        if user.role not in VALID_ROLES:
            raise AppException(
                "Invalid or expired session.", status_code=401, error_code="INVALID_TOKEN"
            )
        access_token, access_expires_at = create_access_token(
            user.id, user.role, access_revision=user.access_revision
        )
        refresh_token = generate_refresh_token()
        refresh_expires_at = utc_now() + timedelta(hours=self.settings.refresh_token_expire_hours)
        await self.auth.add_refresh_token(
            AuthRefreshToken(
                user_id=user.id,
                token_hash=hash_secret(refresh_token),
                expires_at=refresh_expires_at,
            )
        )
        now = utc_now()
        return SessionResult(
            user=user,
            access_token=access_token,
            access_expires_in_seconds=max(0, int((access_expires_at - now).total_seconds())),
            refresh_token=refresh_token,
            refresh_expires_in_seconds=max(0, int((refresh_expires_at - now).total_seconds())),
        )
