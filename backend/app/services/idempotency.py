"""Idempotency keys for retried writes.

The offline photo queue replays requests after a dropped connection, so ``POST /reports``
and ``POST /photos/upload`` must be safe to repeat. A key is reserved before the resource
is created and bound to it inside the *same* transaction:

* a retry that arrives after the winner committed reads the winner's ``resource_id``;
* a retry that arrives while the winner is still running blocks on the row lock and then
  reads the winner's ``resource_id`` — it never creates a second resource.

Callers must treat a returned id that differs from the one they just created as "someone
else won": roll the local transaction back and serve the winner's resource.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency_record import IdempotencyRecord
from app.utils.exceptions import AppException

MAX_IDEMPOTENCY_KEY_LENGTH = 200


def validate_key(key: str | None) -> str | None:
    """Normalize an ``Idempotency-Key`` header, rejecting oversized values."""
    if key is None:
        return None
    normalized = key.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise AppException(
            f"Idempotency-Key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters.",
            status_code=422,
            error_code="IDEMPOTENCY_KEY_TOO_LONG",
        )
    return normalized


def _lookup(key: str, user_id: UUID, route: str):
    return select(IdempotencyRecord).where(
        IdempotencyRecord.key == key,
        IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.route == route,
    )


async def resolve_or_reserve(
    session: AsyncSession,
    *,
    key: str,
    user_id: UUID,
    route: str,
) -> UUID | None:
    """Return the resource already bound to ``key``, or reserve the key and return None.

    The reservation is an ``INSERT ... ON CONFLICT DO NOTHING`` followed by a locking
    read, which serialises concurrent callers on the unique constraint without needing
    a separate advisory lock.
    """
    existing = await session.scalar(_lookup(key, user_id, route))
    if existing is not None and existing.resource_id is not None:
        return existing.resource_id

    await session.execute(
        insert(IdempotencyRecord)
        .values(key=key, user_id=user_id, route=route)
        .on_conflict_do_nothing(index_elements=["key", "user_id", "route"])
    )
    record = await session.scalar(
        _lookup(key, user_id, route)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record is None:
        # The conflicting transaction rolled back and our insert was skipped; retry once.
        await session.execute(
            insert(IdempotencyRecord).values(key=key, user_id=user_id, route=route)
        )
        record = await session.scalar(
            _lookup(key, user_id, route)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return record.resource_id if record is not None else None


async def bind(
    session: AsyncSession,
    *,
    key: str,
    user_id: UUID,
    route: str,
    resource_type: str,
    resource_id: UUID,
) -> UUID:
    """Bind ``resource_id`` to the reserved key; return the winner's id.

    Runs in the caller's transaction so the binding commits or rolls back with the
    resource itself. A returned id different from ``resource_id`` means a concurrent
    request won the key and the caller must discard its own resource.
    """
    record = await session.scalar(
        _lookup(key, user_id, route).with_for_update().execution_options(populate_existing=True)
    )
    if record is None:
        try:
            async with session.begin_nested():
                record = IdempotencyRecord(
                    key=key,
                    user_id=user_id,
                    route=route,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
                session.add(record)
                await session.flush()
        except IntegrityError:
            record = await session.scalar(
                _lookup(key, user_id, route)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if record is None:
                raise
    if record.resource_id is not None and record.resource_id != resource_id:
        return record.resource_id
    record.resource_type = resource_type
    record.resource_id = resource_id
    await session.flush()
    return resource_id