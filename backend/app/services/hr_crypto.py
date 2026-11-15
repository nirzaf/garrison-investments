import zipfile
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.utils.exceptions import AppException

MAX_HR_DOCUMENT_SIZE = 60 * 1024 * 1024
BLOCKED_EXTENSIONS = {".exe", ".sh", ".bat", ".cmd", ".js", ".ps1", ".php", ".py", ".html", ".svg"}
MAGIC_MIME_PREFIXES = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}


def _derive_fernet_key() -> bytes:
    configured = get_settings().hr_encryption_key
    if configured is not None:
        try:
            raw = configured.get_secret_value().encode("ascii")
            Fernet(raw)
            return raw
        except (ValueError, UnicodeError):
            pass
    raise AppException(
        "The HR encryption key is unavailable.",
        status_code=503,
        error_code="HR_ENCRYPTION_UNAVAILABLE",
    )


def encrypt_hr_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    fernet = Fernet(_derive_fernet_key())
    return fernet.encrypt(stripped.encode("utf-8")).decode("ascii")


def decrypt_hr_value(token: str | None) -> str | None:
    if not token:
        return None
    fernet = Fernet(_derive_fernet_key())
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise AppException(
            "The HR record could not be decrypted.",
            status_code=503,
            error_code="HR_DECRYPTION_FAILED",
        ) from None


def mask_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) <= 4:
        return "*" * len(stripped)
    return f"{'*' * (len(stripped) - 4)}{stripped[-4:]}"


def validate_hr_document_file(file_name: str, data: bytes) -> tuple[str, str]:
    suffix = Path(file_name or "document").suffix.lower()
    if suffix in BLOCKED_EXTENSIONS:
        raise AppException("Unsupported file type.", status_code=422, error_code="INVALID_FILE")
    if not data:
        raise AppException("Empty file.", status_code=422, error_code="EMPTY_FILE")
    if len(data) > MAX_HR_DOCUMENT_SIZE:
        raise AppException("File exceeds 60MB limit.", status_code=413, error_code="FILE_TOO_LARGE")

    mime_type: str | None = None
    for candidate_mime, signatures in MAGIC_MIME_PREFIXES.items():
        if any(data.startswith(sig) for sig in signatures):
            mime_type = candidate_mime
            break

    if mime_type is None and suffix == ".docx" and data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                if "word/document.xml" in archive.namelist():
                    mime_type = (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
        except zipfile.BadZipFile:
            mime_type = None

    if mime_type is None:
        raise AppException(
            "File content does not match allowed HR document formats (PDF, PNG, JPEG, DOCX).",
            status_code=422,
            error_code="INVALID_FILE_SIGNATURE",
        )

    checksum = sha256(data).hexdigest()
    return mime_type, checksum
