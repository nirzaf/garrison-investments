"""Lightweight Redis heartbeat markers for Celery worker observability."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime

import redis as sync_redis
import redis.asyncio as async_redis

from app.config import Settings, get_settings
from app.utils.security import utc_now

WORKER_HEARTBEAT_PREFIX = "garrison:celery:worker_heartbeat:"
WORKER_HEARTBEAT_TTL_SECONDS = 180
_SAFE_HOST_RE = re.compile(r"[^a-zA-Z0-9_.:@-]")


def _worker_key(hostname: str | None) -> str:
    cleaned = _SAFE_HOST_RE.sub("_", (hostname or "unknown").strip())[:120] or "unknown"
    return f"{WORKER_HEARTBEAT_PREFIX}{cleaned}"


def task_hostname(task: object) -> str | None:
    """Safely inspect Celery worker hostname without touching an unbound request stack."""
    stack = getattr(task, "request_stack", None)
    top = getattr(stack, "top", None)
    return getattr(top, "hostname", None)


def record_worker_heartbeat(hostname: str | None, *, settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    try:
        client = sync_redis.from_url(
            cfg.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        try:
            payload = json.dumps({"observed_at": utc_now().isoformat()}, separators=(",", ":"))
            client.set(_worker_key(hostname), payload, ex=WORKER_HEARTBEAT_TTL_SECONDS)
        finally:
            client.close()
    except Exception:
        # Heartbeat emission must never interrupt task execution.
        return


def clear_worker_heartbeat(hostname: str | None, *, settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    try:
        client = sync_redis.from_url(
            cfg.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        try:
            client.delete(_worker_key(hostname))
        finally:
            client.close()
    except Exception:
        return


async def read_worker_heartbeats(
    settings: Settings, now: datetime
) -> tuple[str, int | None, int]:
    """Return (worker_status, freshest_age_seconds, active_worker_count)."""
    try:
        async with asyncio.timeout(1.5):
            async with async_redis.from_url(
                settings.redis_url, socket_connect_timeout=1, socket_timeout=1
            ) as conn:
                keys = [
                    key
                    async for key in conn.scan_iter(match=f"{WORKER_HEARTBEAT_PREFIX}*", count=50)
                ]
                if not keys:
                    return "unknown", None, 0
                raw_values = await conn.mget(keys)
    except TimeoutError:
        return "unknown", None, 0
    except Exception:
        return "unavailable", None, 0

    ages: list[int] = []
    for raw in raw_values:
        if not raw:
            continue
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
            observed = datetime.fromisoformat(str(data["observed_at"]))
            if observed.tzinfo is None:
                continue
            ages.append(max(0, int((now - observed).total_seconds())))
        except Exception:
            continue
    if not ages:
        return "unknown", None, 0
    freshest = min(ages)
    if freshest > WORKER_HEARTBEAT_TTL_SECONDS:
        return "unknown", freshest, 0
    active = sum(1 for age in ages if age <= WORKER_HEARTBEAT_TTL_SECONDS)
    return "operational", freshest, active
