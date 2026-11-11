import re
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings
from app.utils.exceptions import AppException, ErrorDetail

_dev_private_pem = """-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQDAthkEzasri5OW
a54Xb1kAFDuvacVLfpwrBFMVVIj1l/lsSvp4fHi0vx+ZKvhWBGZDb+/lx8fiErZK
xsFsjrDybqnxUOnaWo/xzllzhlb9ddJcjfkz7x6EPjO5oJX2NTda8fY0u2YBqCfo
DCZMIUQPhfy1bKxZlnb5LHQVTJDSzSUEje5xNEmx2K79kyO+0RWxHhAtVVmmKp+4
NDTiIivYbThIS/NIPRC9Yny8tGqFpk8CjJ85AXsdjAIuEwIXQvxv3Pijf2Xves6x
waS49FbGXdTsurhMlYrTolSDzLbj7dKqaOL6DGdphBEmpRuY0KZoLgTgAdndjufY
RAq2oFBpAgMBAAECggEAEasweIsF2GB79+TmkgX8vj/cqAzV0MHrPhtvpatCQmg8
b2QhelYJOCM02bWBnttY5/J1p5btWeo2yfzWo6YijZu9W5l8U2+NtpEhjPDCfYsl
riQ7NrqEDQJp+ilBzpja+izokrWi2OCKxiEFCuJa6+RwQs8Tr0QXJOnhO8mxFo6d
SY08uxwSsSV/nA0HNRQQks70lBbCvhnounQ0SViJqNU22rIrr/zXsUGtFQ0167sQ
gVKw6LH1ta04RU5BIkqPcQZg3zpoQYbhreouBZqBAC8eHV0DIlXx18/iH8Qzgskh
rUgjDbCbvUZ/Ysp21BLaBQUTUddFRMlneiierPl6vQKBgQDkIssm4mb7zZAQxQ9y
G3CDXPtkU8v8/XoySndRf06lPafSAqCG7Y9NqiP7WcgHpTP4YmKUn4gaXVjsvfns
5H0zmyfHMKkH3o19FjQGsA1tW7MZIWzAwNwiy6BSrVUa9QU3f4c04z1XsR3U0Kk3
O+uce8SCyBkNNGqUBoCy8YOaVQKBgQDYP6u9XweCsNHmdx2tTy3YLG1BXlTDX6tP
v/I4B0mKRiny6d3O3tY1FKfc1odqJ2pvk0zJQnh6BSW4BAUVIeoKrC1f0a85pxds
sQVvQ6RTvSpipR1l3babsGHI7trokZaE+WeCBadTNfoOT4knJ46JdHnwZmz5sPaP
FGG7dedZxQKBgHQrM3+NchtuxZmEfyT/y/9Ybbrc4NbmzD6npLKfPRDvoHFUXSHX
/kzyAniPc0hRW3Fzx/cedVPXjNygsI9smkSZEVxg7vHO5gV4NO3i4DN7qmt1lcdh
bbdaMT1ofhnIAuwLyHGp9SaeTi58Qm6Z2JRKgfqGohsTQeI2nXqBeR4xAoGAaCZi
RJacO2mF7oW4GVxlLBRZmn4gPOi6zXIY6rs3xAz+7yuL1LKmYHJOVqJMHehV7t72
wIfvFnWcMQBeokrvOayrPdbzmcTMF2E6yNe/MUWOQGxduE4MQPe2YNwJOrHD2M91
9r1aVU1N3c6Ys+7tS255vDrYiXmdhlO+rlae0jECgYAxFCG0WCn07TbZakx8fEhu
9n5rRxnK/zo5VJv9V3GqFRH69nShtzKhFRCoG3ecJyYv+0mP/MF5YIk4FTdhpL2R
5FnAC0zJzd/9rl9gfI/BRcqe1ZcuuMs2AEjuyYmHiZ4Jy+s7VK6b0S0C1We/1x5v
EVNElSGB90F/tPpCCtBl9Q==
-----END PRIVATE KEY-----
"""
_dev_public_pem = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwLYZBM2rK4uTlmueF29Z
ABQ7r2nFS36cKwRTFVSI9Zf5bEr6eHx4tL8fmSr4VgRmQ2/v5cfH4hK2SsbBbI6w
8m6p8VDp2lqP8c5Zc4ZW/XXSXI35M+8ehD4zuaCV9jU3WvH2NLtmAagn6AwmTCFE
D4X8tWysWZZ2+Sx0FUyQ0s0lBI3ucTRJsdiu/ZMjvtEVsR4QLVVZpiqfuDQ04iIr
2G04SEvzSD0QvWJ8vLRqhaZPAoyfOQF7HYwCLhMCF0L8b9z4o39l73rOscGkuPRW
xl3U7Lq4TJWK06JUg8y24+3Sqmji+gxnaYQRJqUbmNCmaC4E4AHZ3Y7n2EQKtqBQ
aQIDAQAB
-----END PUBLIC KEY-----
"""


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
