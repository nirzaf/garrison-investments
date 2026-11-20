import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from hmac import compare_digest, digest
from secrets import randbelow, token_bytes, token_urlsafe
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    options_to_json,
    verify_authentication_response,
)
from webauthn.helpers import parse_authentication_credential_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import CredentialDeviceType, UserVerificationRequirement

from app.config import get_settings
from app.models.support_identity import (
    SupportAuthEvent,
    SupportCredential,
    SupportEmailOtp,
    SupportLoginChallenge,
    SupportOperator,
    SupportSession,
)
from app.models.support_registration import SupportBootstrap
from app.services.email_service import EmailDeliveryError, EmailService
from app.utils.exceptions import AppException
from app.utils.security import utc_now

SUPPORT_HOST = "superadmin.garrisons.lk"
SUPPORT_ORIGIN = f"https://{SUPPORT_HOST}"
SUPPORT_SESSION_SECONDS = 3600
_IDLE = timedelta(minutes=15)
_CHALLENGE_LIFETIME = timedelta(minutes=2)
_OTP_LIFETIME = timedelta(minutes=10)
_OTP_ATTEMPTS = 5

AuthenticatedSupport = tuple[SupportOperator, SupportSession, str | None, str | None]


@dataclass(frozen=True)
class PendingSupportOtp:
    reference: UUID


def _otp_destination(operator_id: UUID) -> tuple[bytes, str] | None:
    settings = get_settings()
    key = settings.support_email_otp_key
    mailbox = settings.support_email_otp_recipients.get(operator_id)
    if key is None or not mailbox:
        return None
    secret = key.get_secret_value().strip().encode()
    return (secret, mailbox) if len(secret) >= 32 else None


def _otp_digest(secret: bytes, mailbox: str, reference: UUID, code: str) -> str:
    return digest(
        secret, b"support-email-otp:" + reference.bytes + code.encode() + mailbox.encode(), "sha256"
    ).hex()


def _denied() -> AppException:
    return AppException(
        "Support authentication could not be verified.",
        status_code=401,
        error_code="SUPPORT_AUTH_REQUIRED",
    )


def _digest(value: str | bytes) -> str:
    return sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def support_session_deadline(active: SupportSession) -> datetime:
    return min(active.expires_at, active.last_seen_at + _IDLE)


class SupportIdentity:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def is_single_owner(self, operator_id: UUID) -> bool:
        if get_settings().support_custody_mode != "single_owner":
            return False
        bootstrap = await self.session.get(SupportBootstrap, 1)
        return (
            bootstrap is not None
            and bootstrap.custody_mode == "single_owner"
            and bootstrap.activated_at is not None
            and bootstrap.first_id == operator_id
        )

    async def _otp_destination(self, operator_id: UUID) -> tuple[bytes, str] | None:
        settings = get_settings()
        bootstrap = await self.session.get(SupportBootstrap, 1)
        single_owner = bootstrap is not None and bootstrap.custody_mode == "single_owner"
        if single_owner != (settings.support_custody_mode == "single_owner"):
            return None
        if single_owner and (
            bootstrap is None
            or bootstrap.activated_at is None
            or bootstrap.first_id != operator_id
            or set(settings.support_email_otp_recipients) != {operator_id}
        ):
            return None
        return _otp_destination(operator_id)

    def _record(self, operator_id: UUID, request_id: str, action: str, now: datetime) -> None:
        self.session.add(
            SupportAuthEvent(
                id=uuid4(),
                operator_id=operator_id,
                request_id=request_id,
                action=action,
                occurred_at=now,
            )
        )

    async def options(
        self, operator_id: UUID, *, cli_binding: tuple[str, str, str] | None = None
    ) -> tuple[UUID, str]:
        operator = await self.session.get(SupportOperator, operator_id, with_for_update=True)
        now = utc_now()
        challenge_id, challenge = uuid4(), token_bytes(32)
        cli_token_hash, cli_csrf_hash, cli_code_hash = cli_binding or (None, None, None)
        if operator is not None and operator.status == "active":
            recent = await self.session.scalar(
                select(func.count())
                .select_from(SupportLoginChallenge)
                .where(
                    SupportLoginChallenge.operator_id == operator_id,
                    SupportLoginChallenge.created_at > now - _CHALLENGE_LIFETIME,
                )
            )
            # Unknown, suspended, or throttled operators receive the same shaped
            # options. Only an eligible operator's challenge is persisted.
            if recent is not None and recent < 5:
                self.session.add(
                    SupportLoginChallenge(
                        id=challenge_id,
                        operator_id=operator_id,
                        challenge=challenge,
                        grant_epoch=operator.grant_epoch,
                        created_at=now,
                        expires_at=now + _CHALLENGE_LIFETIME,
                        cli_token_hash=cli_token_hash,
                        cli_csrf_hash=cli_csrf_hash,
                        cli_code_hash=cli_code_hash,
                    )
                )
        await self.session.commit()
        return challenge_id, self._public_key_options(challenge)

    @staticmethod
    def _public_key_options(challenge: bytes) -> str:
        options = generate_authentication_options(
            rp_id=SUPPORT_HOST,
            challenge=challenge,
            timeout=120_000,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return options_to_json(options)

    async def cli_options(self, challenge_id: UUID, code: str) -> str:
        binding = await self.session.get(SupportLoginChallenge, challenge_id)
        if (
            binding is None
            or binding.expires_at <= utc_now()
            or binding.consumed_at is not None
            or not self._matches_cli_code(binding, code)
        ):
            raise _denied()
        return self._public_key_options(binding.challenge)

    @staticmethod
    def _matches_cli_code(challenge: SupportLoginChallenge, code: str | None) -> bool:
        if challenge.cli_code_hash is None:
            return code is None
        return code is not None and compare_digest(challenge.cli_code_hash, _digest(code))

    async def verify(
        self, challenge_id: UUID, assertion: dict[str, object], request_id: str,
        *, cli_code: str | None = None,
    ) -> AuthenticatedSupport | PendingSupportOtp:
        operator_id = await self.session.scalar(
            select(SupportLoginChallenge.operator_id).where(
                SupportLoginChallenge.id == challenge_id
            )
        )
        if operator_id is None:
            raise _denied()
        operator = await self.session.get(SupportOperator, operator_id, with_for_update=True)
        challenge = await self.session.get(
            SupportLoginChallenge, challenge_id, with_for_update=True
        )
        now = utc_now()
        if (
            operator is None
            or operator.status != "active"
            or challenge is None
            or challenge.expires_at <= now
            or challenge.consumed_at is not None
            or challenge.grant_epoch != operator.grant_epoch
            or not self._matches_cli_code(challenge, cli_code)
        ):
            raise _denied()
        challenge.consumed_at = now
        try:
            await self.verify_assertion(operator_id, challenge.challenge, assertion)
        except (WebAuthnException, AppException, ValueError) as exc:
            self._record(operator_id, request_id, "login_denied", now)
            await self.session.commit()
            raise _denied() from exc

        settings = get_settings()
        if settings.app_env != "test" or settings.support_email_otp_key is not None:
            return await self._send_otp(operator_id, challenge.id, request_id, now)
        return await self._activate(operator, challenge, request_id, now)

    async def request_email_otp(self, operator_id: UUID, request_id: str) -> PendingSupportOtp:
        settings = get_settings()
        if not settings.support_email_otp_only_login:
            raise _denied()
        operator = await self.session.get(SupportOperator, operator_id, with_for_update=True)
        now = utc_now()
        if operator is None or operator.status != "active":
            raise _denied()
        recent = await self.session.scalar(
            select(func.count())
            .select_from(SupportLoginChallenge)
            .where(
                SupportLoginChallenge.operator_id == operator_id,
                SupportLoginChallenge.created_at > now - _CHALLENGE_LIFETIME,
            )
        )
        if recent is None or recent >= 5:
            self._record(operator_id, request_id, "login_denied", now)
            await self.session.commit()
            raise _denied()
        challenge_id = uuid4()
        self.session.add(
            SupportLoginChallenge(
                id=challenge_id,
                operator_id=operator_id,
                challenge=token_bytes(32),
                grant_epoch=operator.grant_epoch,
                created_at=now,
                expires_at=now + _CHALLENGE_LIFETIME,
                consumed_at=now,
            )
        )
        await self.session.flush()
        return await self._send_otp(operator_id, challenge_id, request_id, now)

    async def _send_otp(
        self, operator_id: UUID, challenge_id: UUID, request_id: str, now: datetime
    ) -> PendingSupportOtp:
        destination = await self._otp_destination(operator_id)
        if destination is None:
            self._record(operator_id, request_id, "login_denied", now)
            await self.session.commit()
            raise _denied()
        secret, mailbox = destination
        reference = uuid4()
        code = f"{randbelow(1_000_000):06d}"
        otp = SupportEmailOtp(
            id=reference,
            login_challenge_id=challenge_id,
            code_digest=_otp_digest(secret, mailbox, reference, code),
            expires_at=now + _OTP_LIFETIME,
            attempts=0,
        )
        self.session.add(otp)
        await self.session.commit()
        try:
            accepted = await asyncio.to_thread(
                EmailService().send,
                recipients=[mailbox],
                subject="Garrisons Super Admin sign-in code",
                body=f"Your Super Admin sign-in code is: {code}\n\n"
                "This code expires in 10 minutes.",
            )
            if accepted != 1:
                raise EmailDeliveryError("Verification email was not accepted.")
        except EmailDeliveryError:
            self._record(operator_id, request_id, "login_denied", utc_now())
            await self.session.commit()
            raise AppException(
                "Verification email is unavailable. Start a new sign-in and try again.",
                status_code=503,
                error_code="EMAIL_DELIVERY_UNAVAILABLE",
            ) from None
        otp.accepted_at = utc_now()
        await self.session.commit()
        return PendingSupportOtp(reference)

    async def verify_otp(
        self, reference: UUID, code: str, request_id: str, *, cli_code: str | None
    ) -> AuthenticatedSupport:
        binding = (
            await self.session.execute(
                select(SupportLoginChallenge.operator_id, SupportLoginChallenge.id)
                .join(SupportEmailOtp)
                .where(SupportEmailOtp.id == reference)
            )
        ).one_or_none()
        if binding is None:
            raise _denied()
        operator_id, challenge_id = binding
        operator = await self.session.get(SupportOperator, operator_id, with_for_update=True)
        challenge = await self.session.get(
            SupportLoginChallenge, challenge_id, with_for_update=True
        )
        otp = await self.session.get(SupportEmailOtp, reference, with_for_update=True)
        now = utc_now()
        destination = await self._otp_destination(operator_id)
        if (
            operator is None
            or operator.status != "active"
            or challenge is None
            or challenge.consumed_at is None
            or challenge.grant_epoch != operator.grant_epoch
            or not self._matches_cli_code(challenge, cli_code)
            or otp is None
            or otp.accepted_at is None
            or otp.used_at is not None
            or otp.expires_at <= now
            or otp.attempts >= _OTP_ATTEMPTS
            or destination is None
        ):
            raise _denied()
        secret, mailbox = destination
        if not compare_digest(otp.code_digest, _otp_digest(secret, mailbox, reference, code)):
            otp.attempts += 1
            self._record(operator_id, request_id, "login_denied", now)
            await self.session.commit()
            raise _denied()
        otp.used_at = now
        return await self._activate(operator, challenge, request_id, now)

    async def _activate(
        self,
        operator: SupportOperator,
        challenge: SupportLoginChallenge,
        request_id: str,
        now: datetime,
    ) -> AuthenticatedSupport:
        token = csrf = None
        token_hash, csrf_hash = challenge.cli_token_hash, challenge.cli_csrf_hash
        if token_hash is None or csrf_hash is None:
            token, csrf = token_urlsafe(32), token_urlsafe(32)
            token_hash, csrf_hash = _digest(token), _digest(csrf)
        active = SupportSession(
            id=uuid4(),
            operator_id=operator.id,
            token_hash=token_hash,
            csrf_hash=csrf_hash,
            grant_epoch=operator.grant_epoch,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=SUPPORT_SESSION_SECONDS),
        )
        self.session.add(active)
        self._record(operator.id, request_id, "login", now)
        await self.session.commit()
        return operator, active, token, csrf

    async def verify_assertion(
        self, operator_id: UUID, challenge: bytes, assertion: dict[str, object]
    ) -> None:
        credential = parse_authentication_credential_json(assertion)
        if credential.response.user_handle != operator_id.bytes:
            raise _denied()
        client_data = json.loads(credential.response.client_data_json)
        if not isinstance(client_data, dict) or client_data.get("crossOrigin", False) is not False:
            raise _denied()
        stored = await self.session.scalar(
            select(SupportCredential)
            .where(
                SupportCredential.operator_id == operator_id,
                SupportCredential.credential_hash == _digest(credential.raw_id),
                SupportCredential.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if stored is None:
            raise _denied()
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=SUPPORT_HOST,
            expected_origin=SUPPORT_ORIGIN,
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
            require_user_verification=True,
        )
        if verified.credential_device_type != CredentialDeviceType.SINGLE_DEVICE:
            raise _denied()
        stored.sign_count = verified.new_sign_count

    async def current(self, token: str | None) -> tuple[SupportOperator, SupportSession]:
        if not token or len(token) != 43:
            raise _denied()
        token_hash = _digest(token)
        operator_id = await self.session.scalar(
            select(SupportSession.operator_id).where(SupportSession.token_hash == token_hash)
        )
        if operator_id is None:
            raise _denied()
        operator = await self.session.get(SupportOperator, operator_id, with_for_update=True)
        active = await self.session.scalar(
            select(SupportSession).where(SupportSession.token_hash == token_hash).with_for_update()
        )
        now = utc_now()
        if (
            operator is None
            or operator.status != "active"
            or active is None
            or active.revoked_at is not None
            or support_session_deadline(active) <= now
            or active.grant_epoch != operator.grant_epoch
        ):
            raise _denied()
        return operator, active

    async def logout(self, token: str | None, csrf: str | None, request_id: str) -> None:
        operator, active = await self.current(token)
        if not csrf or len(csrf) != 43 or not compare_digest(active.csrf_hash, _digest(csrf)):
            raise AppException(
                "Support request could not be verified.",
                status_code=403,
                error_code="SUPPORT_CSRF_INVALID",
            )
        now = utc_now()
        active.revoked_at = now
        self._record(operator.id, request_id, "logout", now)
        await self.session.commit()
