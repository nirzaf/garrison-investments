"""Fixed root-installed permit consumer; invoked only by reviewed host entrypoint."""

import hashlib
import os
import stat
import sys
import time
from pathlib import Path

from forward_release_contract import consume_permit, validate_permit

if os.geteuid() != 0 or len(sys.argv) != 9:
    raise SystemExit("Root entrypoint invocation required")
mode, state, sha, ci_run, ci_attempt, deploy_run, attempt, entrypoint_hash = sys.argv[1:]
if mode not in ("validate", "consume"):
    raise SystemExit("Unknown permit operation")
if state != "/opt/garrison-portal/deploy":
    raise SystemExit("Unexpected protected state directory")
actual = hashlib.sha256(Path("/usr/local/sbin/garrison-deploy").read_bytes()).hexdigest()
if actual != entrypoint_hash:
    raise SystemExit("Entrypoint changed")
identity = dict(
    sha=sha,
    ci_run=int(ci_run),
    ci_attempt=int(ci_attempt),
    deploy_run=int(deploy_run),
    attempt=int(attempt),
    entrypoint_sha256=actual,
)
if mode == "consume":
    consume_permit(Path(state), **identity)
else:
    fd = os.open(str(Path(state) / "forward097.permit"), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise SystemExit("Permit is not private/root owned")
        raw = os.read(fd, 8193)
        if len(raw) > 8192:
            raise SystemExit("Permit too large")
        validate_permit(raw, now=int(time.time()), **identity)
    finally:
        os.close(fd)
