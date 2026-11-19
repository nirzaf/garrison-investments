"""Local-only crash journal around trusted maintenance functions, not host enrollment.

Host installation must supply statically reviewed functions; no source-defined shell,
plugins, or self-asserted receipts are accepted here. Existing host lock is mandatory.
An existing marker always refuses re-entry, including after success. It is an execution
journal, NOT evidence that containment or migration completed. No automatic reset exists.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path


class DurableAttempt:
    def __init__(self, directory: Path, identity: dict, *, owner_uid: int = 0):
        for parent in (directory.parent.parent, directory.parent, directory):
            mode = parent.lstat()
            if (
                not stat.S_ISDIR(mode.st_mode)
                or mode.st_uid != owner_uid
                or mode.st_mode & 0o022
            ):
                raise ValueError("Journal parents must be protected and operator owned")
        self.dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.fd = -1
        try:
            self.fd = os.open(
                "forward097.attempt",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=self.dirfd,
            )
            os.fsync(self.dirfd)
            self.append("attempt_started", identity)
        except BaseException:
            self.close()
            raise

    def append(self, event: str, details: dict | None = None) -> None:
        # Only phase identifiers and release identity belong here, never command output,
        # exception text, personal data, credential values or fabricated approval claims.
        data = (
            json.dumps({"event": event, "details": details or {}}, sort_keys=True)
            + "\n"
        ).encode()
        offset = 0
        while offset < len(data):
            offset += os.write(self.fd, data[offset:])
        os.fsync(self.fd)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
        if self.dirfd >= 0:
            os.close(self.dirfd)
            self.dirfd = -1


PHASES = (
    "verify_exact_release",
    "establish_and_verify_ingress_block",
    "stop_and_drain_writers",
    "verify_no_writer_sessions",
    "verify_source093_and_data",
    "verify_exact_release",
    "consume_exact_permit",
    "migrate097",
    "verify_schema097",
    "start_backend_and_guarded_nginx_only",
    "verify_read_only_smoke",
    "start_and_verify_workers",
    "reopen_business_ingress",
    "record_completed_release",
)


def exercise_trusted_adapter(
    journal: DurableAttempt, functions: dict[str, Callable[[], None]]
) -> None:
    """Non-privileged test seam; caller supplies installed trusted boundaries, not CI data.

    Durable intent precedes each callback. Interrupted intent is never auto-resumed.
    Even a failed containment operation remains explicitly unknown, not 'safe'.
    """
    if set(functions) != set(PHASES) | {"stop_and_preserve_failure"}:
        raise ValueError("Exact trusted boundary set required")
    try:
        for phase in PHASES:
            journal.append("phase_started", {"phase": phase})
            functions[phase]()
            journal.append("phase_completed", {"phase": phase})
        journal.append("attempt_completed")
    except BaseException as original:
        # Failures writing evidence also attempt containment; no downgrade fallback.
        try:
            functions["stop_and_preserve_failure"]()
        except BaseException as containment:  # noqa: BLE001 - re-raised with original failure
            try:
                journal.append("containment_unknown")
            finally:
                raise BaseExceptionGroup(
                    "Release failed; containment also failed", [original, containment]
                )
        journal.append("attempt_failed_containment_callback_completed")
        raise
