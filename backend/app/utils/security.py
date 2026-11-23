import re
import secrets
from datetime import UTC, datetime, timedelta
from functools import cache
from hashlib import sha256
from typing import Any
from uuid import UUID

import bcrypt
import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import InvalidTokenError

from app.config import Settings, get_settings
from app.utils.exceptions import AppException, ErrorDetail

_DISPOSABLE_JWT_ENVS = frozenset({"development", "test", "local"})


def utc_now() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    if "\x00" in password:
        raise ValueError("Passwords cannot contain null characters")
    # Existing Passlib bcrypt hashes use at most the first 72 UTF-8 bytes.
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash or "\x00" in password:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


def hash_secret(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def validate_password_policy(password: str) -> None:
    errors: list[ErrorDetail] = []
    checks = [
        (len(password) >= 8, "Password must be at least 8 characters."),
        (bool(re.search(r"[A-Z]", password)), "Password must include an uppercase letter."),
        (bool(re.search(r"[a-z]", password)), "Password must include a lowercase letter."),
        (bool(re.search(r"\d", password)), "Password must include a number."),
        (bool(re.search(r"[^A-Za-z0-9]", password)), "Password must include a symbol."),
    ]
    for passed, message in checks:
        if not passed:
            errors.append(ErrorDetail(field="new_password", message=message))
    if errors:
        raise AppException(
            "Password does not meet policy.",
            status_code=422,
            error_code="PASSWORD_POLICY_FAILED",
            errors=errors,
        )


def _load_jwt_key(path: str | None, label: str) -> str:
    if not path:
        raise RuntimeError(f"{label} must be set when using configured JWT signing keys.")
    try:
        with open(path, encoding="utf-8") as stream:
            pem = stream.read()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"{label} points to a missing or unreadable JWT key.") from exc
    if not pem.strip():
        raise RuntimeError(f"{label} points to an empty JWT key.")
    return pem


def _uses_ephemeral_jwt_keys(settings: Settings) -> bool:
    return (
        settings.app_env.lower() in _DISPOSABLE_JWT_ENVS
        and not settings.jwt_private_key_path
        and not settings.jwt_public_key_path
    )


@cache
def _ephemeral_jwt_key_pair() -> tuple[str, str]:
    # Only used in disposable single-process environments. Never shared or persisted.
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii"),
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii"),
    )


def _jwt_private_key() -> str:
    settings = get_settings()
    if _uses_ephemeral_jwt_keys(settings):
        return _ephemeral_jwt_key_pair()[0]
    return _load_jwt_key(settings.jwt_private_key_path, "JWT_PRIVATE_KEY_PATH")


def _jwt_public_key() -> str:
    settings = get_settings()
    if _uses_ephemeral_jwt_keys(settings):
        return _ephemeral_jwt_key_pair()[1]
    return _load_jwt_key(settings.jwt_public_key_path, "JWT_PUBLIC_KEY_PATH")


def validate_signing_keys() -> None:
    """Require an RSA key pair; only disposable environments may generate one."""
    private_pem = _jwt_private_key()
    public_pem = _jwt_public_key()
    try:
        private = serialization.load_pem_private_key(private_pem.encode("utf-8"), password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise RuntimeError("JWT_PRIVATE_KEY_PATH is not a valid PEM key.") from exc
    try:
        public = serialization.load_pem_public_key(public_pem.encode("utf-8"))
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise RuntimeError("JWT_PUBLIC_KEY_PATH is not a valid PEM key.") from exc
    if not isinstance(private, rsa.RSAPrivateKey) or not isinstance(public, rsa.RSAPublicKey):
        raise RuntimeError("JWT signing keys must be RSA keys.")
    if private.public_key().public_numbers() != public.public_numbers():
        raise RuntimeError("JWT public and private keys do not match.")


def create_access_token(
    user_id: UUID,
    role: str,
    *,
    access_revision: int = 0,
    auth_session_id: UUID | None = None,
    session_expires_at: datetime | None = None,
    token_type: str = "access",
) -> tuple[str, datetime]:
    settings = get_settings()
    expires_at = utc_now() + timedelta(minutes=settings.access_token_expire_minutes)
    if session_expires_at is not None:
        expires_at = min(expires_at, session_expires_at)
    payload = {
        "sub": str(user_id),
        "role": role,
        "access_revision": access_revision,
        "type": token_type,
        "exp": expires_at,
        "iat": utc_now(),
    }
    if auth_session_id is not None:
        payload["sid"] = str(auth_session_id)
    return jwt.encode(payload, _jwt_private_key(), algorithm=settings.jwt_algorithm), expires_at


def decode_access_token(token: str, *, token_type: str = "access") -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            _jwt_public_key(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except InvalidTokenError as exc:
        raise AppException(
            "Invalid or expired session.",
            status_code=401,
            error_code="INVALID_TOKEN",
        ) from exc
    if payload.get("type") != token_type or not payload.get("sub"):
        raise AppException("Invalid session token.", status_code=401, error_code="INVALID_TOKEN")
    return payload
