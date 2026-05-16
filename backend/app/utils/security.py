import re
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.utils.exceptions import AppException, ErrorDetail

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_dev_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_dev_private_pem = _dev_private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")
_dev_public_pem = _dev_private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode("utf-8")


def utc_now() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return password_context.verify(password, password_hash)


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


def _read_key_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return None


def _jwt_private_key() -> str:
    settings = get_settings()
    return _read_key_file(settings.jwt_private_key_path) or _dev_private_pem


def _jwt_public_key() -> str:
    settings = get_settings()
    return _read_key_file(settings.jwt_public_key_path) or _dev_public_pem


def create_access_token(user_id: UUID, role: str) -> tuple[str, datetime]:
    settings = get_settings()
    expires_at = utc_now() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "exp": expires_at,
        "iat": utc_now(),
    }
    return jwt.encode(payload, _jwt_private_key(), algorithm=settings.jwt_algorithm), expires_at


def decode_access_token(token: str) -> dict[str, str]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, _jwt_public_key(), algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise AppException(
            "Invalid or expired session.",
            status_code=401,
            error_code="INVALID_TOKEN",
        ) from exc
    if payload.get("type") != "access" or not payload.get("sub"):
        raise AppException("Invalid session token.", status_code=401, error_code="INVALID_TOKEN")
    return payload
