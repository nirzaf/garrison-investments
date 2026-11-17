import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

_SENSITIVE_KEY_PARTS = {
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "csrf",
    "invitation",
    "jwt",
    "otp",
    "pairing_code",
    "passphrase",
    "password",
    "private_key",
    "secret",
    "sealed",
    "set_cookie",
    "token",
    "x_amz_signature",
}
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_URL_CREDENTIAL_PATTERN = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s:]+:[^@\s]+@")
_KEY_VALUE_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(?P<prefix>(?:[a-z0-9]+[_-])*(?:api[_-]?key|auth(?:orization)?|cookie|"
    r"jwt|otp(?:[_-]code)?|pass(?:word)?|passphrase|secret|session|token|"
    r"x[_-]amz[_-](?:credential|signature|security[_-]token))=)[^&\s\"']+"
)
_MAX_REDACTION_DEPTH = 24


@lru_cache(maxsize=512)
def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    value = _BEARER_PATTERN.sub("Bearer [redacted]", value)
    value = _JWT_PATTERN.sub("[redacted-jwt]", value)
    value = _URL_CREDENTIAL_PATTERN.sub(r"\g<scheme>[redacted]@", value)
    return _KEY_VALUE_CREDENTIAL_PATTERN.sub(r"\g<prefix>[redacted]", value)


def redact_payload(value: Any, *, key: object | None = None, depth: int = 0) -> Any:
    if key is not None and _is_sensitive_key(str(key)):
        return "[redacted]"
    if depth >= _MAX_REDACTION_DEPTH:
        return "[redacted-depth-limit]"
    if isinstance(value, Mapping):
        return {
            item_key: redact_payload(item, key=item_key, depth=depth + 1)
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_payload(item, depth=depth + 1) for item in value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "[redacted-binary]"
    if isinstance(value, str):
        return redact_text(value)
    return value
