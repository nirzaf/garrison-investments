"""Proof of control of a business account's current email address."""

from datetime import datetime
from hmac import compare_digest, digest
from urllib.parse import urlsplit
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


def normalized_business_https_origin(
    raw: str | None, *, support_host: str = "superadmin.garrisons.lk"
) -> str | None:
    try:
        url = urlsplit((raw or "").strip().rstrip("/"))
    except ValueError:
        return None
    if (
        url.scheme != "https"
        or url.hostname is None
        or url.hostname == support_host
        or "*" in url.netloc
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path != ""
    ):
        return None
    return f"https://{url.netloc}"


def recovery_portal_origin(
    settings: Settings, *, support_host: str = "superadmin.garrisons.lk"
) -> str | None:
    """Return the validated business portal HTTPS origin when support recovery is active."""
    if not settings.support_portal_enabled:
        return None
    origin = normalized_business_https_origin(
        settings.normalized_frontend_base_url, support_host=support_host
    )
    if origin is None:
        return None
    if settings.app_env.strip().lower() == "test":
        return origin
    if not settings.support_recovery_delivery_enabled or _key(settings) is None:
        return None
    allowed = {
        parsed
        for item in settings.support_recovery_allowed_origins.split(",")
        if (parsed := normalized_business_https_origin(item, support_host=support_host))
        is not None
    }
    return origin if origin in allowed else None


def is_recovery_issuance_enabled(
    settings: Settings, *, support_host: str = "superadmin.garrisons.lk"
) -> bool:
    if not settings.support_portal_enabled:
        return False
    if settings.app_env.strip().lower() == "test":
        return True
    return recovery_portal_origin(settings, support_host=support_host) is not None
