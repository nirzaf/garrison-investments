from __future__ import annotations

import os
import stat
from pathlib import Path

_MAX_SECRET_BYTES = 64 * 1024


def read_private_secret_file(path: str, *, setting_name: str) -> str:
    """Read an owner-only secret file without following symlinks.

    Error messages intentionally omit paths and contents so configuration
    failures cannot disclose credentials.
    """
    candidate = Path(path)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{setting_name}_FILE must be an absolute private file path.")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError:
        raise ValueError(f"{setting_name}_FILE must identify a private regular file.") from None

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError(f"{setting_name}_FILE must identify an owner-only regular file.")
        if metadata.st_size > _MAX_SECRET_BYTES:
            raise ValueError(f"{setting_name}_FILE exceeds the allowed size.")
        with os.fdopen(descriptor, "rb", closefd=False) as secret_file:
            raw = secret_file.read(_MAX_SECRET_BYTES + 1)
    finally:
        os.close(descriptor)

    if len(raw) > _MAX_SECRET_BYTES:
        raise ValueError(f"{setting_name}_FILE exceeds the allowed size.")
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{setting_name}_FILE must contain UTF-8 text.") from None
    if value.endswith("\n"):
        value = value[:-1]
        if value.endswith("\r"):
            value = value[:-1]
    if not value.strip():
        raise ValueError(f"{setting_name}_FILE must not be empty.")
    if any(character in value for character in "\r\n\x00"):
        raise ValueError(f"{setting_name}_FILE must contain one line of text.")
    return value
