import asyncio
import json
from time import monotonic

import redis.asyncio as redis
from fastapi import Request

from app.utils.request import get_client_ip


class AuthRateLimiter:
    protected_paths = {
        "/api/v1/auth/login",
        "/api/v1/auth/verify-otp",
        "/api/v1/auth/password-reset/request",
        "/api/v1/auth/password-reset/confirm",
        "/api/v1/super-admin/auth/login",
        "/api/v1/super-admin/auth/verify-otp",
        "/api/v1/support/auth/options",
        "/api/v1/support/auth/verify",
        "/api/v1/support/auth/verify-otp",
        "/api/v1/support/auth/cli/start",
        "/api/v1/support/auth/cli/options",
        "/api/v1/support/auth/cli/verify",
        "/api/v1/support/auth/cli-proof/start",
        "/api/v1/support/auth/cli-proof/options",
        "/api/v1/support/auth/cli-proof/submit",
        "/api/v1/support/auth/cli-proof/take",
        "/api/v1/support/registration/options",
        "/api/v1/support/registration/status",
        "/api/v1/support/registration/verify",
    }

    def __init__(self, *, redis_url: str, window_seconds: int, max_requests: int) -> None:
        self.redis_url = redis_url
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self._redis: redis.Redis | None = None
        self._fallback_buckets: dict[str, list[float]] = {}
        self._fallback_lock = asyncio.Lock()

    def applies_to(self, request: Request) -> bool:
        return request.method.upper() == "POST" and request.url.path in self.protected_paths

    async def check(self, request: Request) -> tuple[bool, int]:
        key = await self._key_for(request)
        count = await self._increment(key)
        remaining = max(self.max_requests - count, 0)
        return count > self.max_requests, remaining

    async def _key_for(self, request: Request) -> str:
        client_id = get_client_ip(request) or "unknown"
        identity = await self._request_identity(request)
        return f"rate-limit:auth:{request.url.path}:{client_id}:{identity}"

    async def _request_identity(self, request: Request) -> str:
        if request.url.path.startswith("/api/v1/support/"):
            return "anonymous"
        try:
            body = await request.body()
        except Exception:
            return "anonymous"

        if not body:
            return "anonymous"

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "anonymous"
        if not isinstance(payload, dict):
            return "anonymous"

        if request.url.path in {
            "/api/v1/auth/login",
            "/api/v1/auth/password-reset/request",
            "/api/v1/super-admin/auth/login",
        }:
            return str(payload.get("email") or "anonymous").strip().lower()
        if request.url.path in {
            "/api/v1/auth/verify-otp",
            "/api/v1/auth/password-reset/confirm",
            "/api/v1/super-admin/auth/verify-otp",
        }:
            return str(payload.get("challenge_id") or "anonymous").strip().lower()
        return "anonymous"

    async def _increment(self, key: str) -> int:
        try:
            if self._redis is None:
                self._redis = redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )

            count = int(await self._redis.incr(key))
            ttl = await self._redis.ttl(key)
            if ttl < 0:
                await self._redis.expire(key, self.window_seconds)
            return count
        except Exception:
            return await self._increment_in_memory(key)

    async def _increment_in_memory(self, key: str) -> int:
        now = monotonic()
        async with self._fallback_lock:
            bucket = [
                timestamp
                for timestamp in self._fallback_buckets.get(key, [])
                if now - timestamp < self.window_seconds
            ]
            bucket.append(now)
            self._fallback_buckets[key] = bucket
            return len(bucket)
