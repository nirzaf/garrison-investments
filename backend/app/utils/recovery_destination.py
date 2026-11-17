"""Proof of control of a business account's current email address."""

from datetime import datetime
from hmac import compare_digest, digest
from uuid import UUID

from app.config import Settings


def _key(settings: Settings) -> bytes | None:
    configured = settings.support_recovery_key
    if configured is None:
        return None
    key = configured.get_secret_value().encode("utf-8")
    return key if len(key) >= 32 else None


def recovery_destination_digest(settings: Settings, user_id: UUID, email: str) -> str | None:
    key = _key(settings)
    value = b"garrison:recovery-destination:v1\x00" + user_id.bytes + email.strip().encode("utf-8")
    return digest(key, value, "sha256").hex() if key is not None else None


def support_recovery_otp(settings: Settings, challenge_id: UUID) -> str | None:
    key = _key(settings)
    if key is None:
        return None
    value = digest(key, b"garrison:recovery-otp:v1\x00" + challenge_id.bytes, "sha256")
    return f"{int.from_bytes(value, 'big') % 1_000_000:06d}"


def support_recovery_otp_digest(settings: Settings, challenge_id: UUID, otp: str) -> str | None:
    key = _key(settings)
    value = b"garrison:recovery-otp-check:v1\x00" + challenge_id.bytes + otp.encode("utf-8")
    return digest(key, value, "sha256").hex() if key is not None else None


def verified_recovery_destination(
    settings: Settings,
    user_id: UUID,
    email: str,
    stored_digest: str | None,
    verified_at: datetime | None,
) -> str | None:
    """Return the opaque current destination binding, if proved by business sign-in."""
    current = recovery_destination_digest(settings, user_id, email)
    if (
        verified_at is not None
        and stored_digest is not None
        and current is not None
        and compare_digest(current, stored_digest)
    ):
        return current
    return None
