"""One-use forward093→097 permit validation; does not issue permits or deploy."""

from __future__ import annotations

import json
import os
import re
import stat
import time
from pathlib import Path


def _private_directory(path: Path, owner: int) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
        raise ValueError("Permit parent must be a protected operator-owned directory")


def validate_permit(
    raw: bytes,
    *,
    sha: str,
    ci_run: int,
    ci_attempt: int,
    deploy_run: int,
    attempt: int,
    entrypoint_sha256: str,
    now: int,
) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate permit key")
            result[key] = value
        return result

    data = json.loads(raw, object_pairs_hook=unique)
    fields = {
        "mode",
        "sha",
        "ci_run",
        "ci_attempt",
        "deploy_run",
        "attempt",
        "entrypoint_sha256",
        "source",
        "target",
        "not_before",
        "expires",
    }
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("Unexpected permit fields")
    if not re.fullmatch(r"[a-f0-9]{40}", sha) or not re.fullmatch(
        r"[a-f0-9]{64}", entrypoint_sha256
    ):
        raise ValueError("Invalid exact release identity")
    for key in (
        "ci_run",
        "ci_attempt",
        "deploy_run",
        "attempt",
        "not_before",
        "expires",
    ):
        if type(data[key]) is not int or data[key] <= 0:
            raise ValueError("Invalid permit integer")
    expected = {
        "mode": "forward-only-093-to-097",
        "sha": sha,
        "ci_run": ci_run,
        "ci_attempt": ci_attempt,
        "deploy_run": deploy_run,
        "attempt": attempt,
        "entrypoint_sha256": entrypoint_sha256,
        "source": "202605310093",
        "target": "202605310097",
    }

    if any(data[k] != value for k, value in expected.items()):
        raise ValueError("Permit does not match exact invocation")
    if not (
        data["not_before"] <= now < data["expires"]
        and 0 < data["expires"] - data["not_before"] <= 1800
    ):
        raise ValueError("Permit window invalid or expired")
    return data


def consume_permit(directory: Path, *, owner_uid: int = 0, **identity) -> dict:
    # Called under the existing host deployment lock. Neither runner nor source
    # archive controls these directories. The marker is never overwritten.
    for path in (directory.parent.parent, directory.parent, directory):
        _private_directory(path, owner_uid)
    dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(
            "forward097.permit",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=dirfd,
        )
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != owner_uid
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                raise ValueError(
                    "Permit file must be private, regular and operator-owned"
                )
            with os.fdopen(fd, "rb", closefd=False) as file:
                raw = file.read(8193)
            if len(raw) > 8192:
                raise ValueError("Permit too large")
            result = validate_permit(raw, now=int(time.time()), **identity)
            # Link creates a non-overwriting durable consumed identity atomically.
            os.link(
                "forward097.permit",
                "forward097.used",
                src_dir_fd=dirfd,
                dst_dir_fd=dirfd,
                follow_symlinks=False,
            )
            os.fsync(dirfd)
            os.unlink("forward097.permit", dir_fd=dirfd)
            os.fsync(dirfd)
            return result
        finally:
            os.close(fd)
    finally:
        os.close(dirfd)
