"""Local preparation for an independently enrolled maintenance ingress guard.

Does not install/reload configuration. Only static/readiness GET/HEAD probes pass;
all business and authentication APIs are blocked, including GET requests.
"""

from __future__ import annotations

import re

GUARD = """
    # FORWARD097_MAINTENANCE_GUARD: never enable Super Admin or business APIs here.
    if ($request_method !~ ^(GET|HEAD)$) { return 503; }
    if ($uri !~ "^(/|/login|/sw\\.js|/assets/[A-Za-z0-9_.-]+|/health/readiness)$") { return 503; }
"""


def guarded_config(original: str) -> str:
    if "FORWARD097_MAINTENANCE_GUARD" in original:
        raise ValueError("Maintenance guard already present")
    # Deliberately require reviewed standard server block syntax; no guessing.
    guarded, count = re.subn(r"(?m)^(\s*server\s*\{)\s*$", lambda m: m.group(1) + GUARD, original)
    if count == 0:
        raise ValueError("No supported server blocks")
    return guarded


def verify_drained(running_services: set[str], client_sessions: int) -> None:
    # All other writers must be explicitly inventoried rather than ignored.
    allowed = {
        "postgres",
        "redis",
        "minio",
        "grafana",
        "loki",
        "alloy",
        "grafana_db_init",
        "loki_minio_init",
    }
    if running_services - allowed or type(client_sessions) is not int or client_sessions != 0:
        raise ValueError("Ingress/application/unknown writers or database client sessions remain")
