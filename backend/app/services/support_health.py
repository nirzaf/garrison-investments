import asyncio
from collections.abc import Awaitable
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import redis.asyncio as redis
from minio import Minio
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from urllib3 import PoolManager, Timeout

from app.config import Settings, get_settings
from app.database import check_database
from app.models.support_cases import SupportOperatorGrant
from app.models.support_health import SupportHealthEvent
from app.models.support_identity import SupportOperator, SupportSession
from app.services.support_identity import SupportIdentity, support_session_deadline
from app.utils.exceptions import AppException, PermissionDeniedException
from app.utils.security import utc_now

Status = Literal["operational", "unavailable", "unknown"]
_CAPABILITY = "health.read"


class SupportHealthRead(BaseModel):
    database: Status
    redis: Status
    object_storage: Status
    observed_at: datetime


async def _observe(probe: Awaitable[bool]) -> Status:
    try:
        return "operational" if await asyncio.wait_for(probe, timeout=2.0) else "unavailable"
    except TimeoutError:
        return "unknown"
    except Exception:
        return "unavailable"


async def _ping_redis(settings: Settings) -> bool:
    async with redis.from_url(
        settings.redis_url, socket_connect_timeout=1, socket_timeout=1
    ) as connection:
        return bool(await connection.ping())


def _check_bucket(settings: Settings) -> bool:
    pool = PoolManager(timeout=Timeout(connect=0.75, read=0.75), retries=False)
    try:
        return Minio(
            settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            secure=settings.minio_secure,
            region="us-east-1",
            http_client=pool,
        ).bucket_exists(settings.minio_bucket)
    finally:
        pool.clear()


async def _eligible(
    session: AsyncSession, token: str | None
) -> tuple[SupportOperator, SupportSession]:
    operator, active = await SupportIdentity(session).current(token)
    grant = await session.get(
        SupportOperatorGrant, (operator.id, _CAPABILITY), with_for_update=True
    )
    if grant is None:
        raise PermissionDeniedException(_CAPABILITY)
    return operator, active


def _audit(session: AsyncSession, operator_id: UUID, action: str, request_id: str) -> None:
    session.add(
        SupportHealthEvent(
            id=uuid4(),
            operator_id=operator_id,
            action=action,
            request_id=request_id,
            occurred_at=utc_now(),
        )
    )


async def read_support_health(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportHealthRead:
    operator, _ = await _eligible(session, token)
    count = await session.scalar(
        select(func.count())
        .select_from(SupportHealthEvent)
        .where(
            SupportHealthEvent.operator_id == operator.id,
            SupportHealthEvent.action == "requested",
            SupportHealthEvent.occurred_at > utc_now() - timedelta(minutes=1),
        )
    )
    if count is not None and count >= 6:
        raise AppException(
            "Wait before checking service health again.",
            status_code=429,
            error_code="SUPPORT_HEALTH_RATE_LIMIT",
        )
    _audit(session, operator.id, "requested", request_id)
    await session.commit()

    # Probe fixed, configured dependencies after releasing the authorization locks.
    settings = get_settings()
    database, cache, storage = await asyncio.gather(
        _observe(check_database()),
        _observe(_ping_redis(settings)),
        _observe(asyncio.to_thread(_check_bucket, settings)),
    )
    session.expire_all()
    operator, active = await _eligible(session, token)
    now = utc_now()
    if support_session_deadline(active) <= now:
        raise AppException(
            "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
        )
    _audit(session, operator.id, "returned", request_id)
    active.last_seen_at = now
    await session.commit()
    return SupportHealthRead(
        database=database, redis=cache, object_storage=storage, observed_at=now
    )
