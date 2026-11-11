"""Shared helpers for concurrency regression tests.

Every race in this suite must be a real ``asyncio.gather`` over **separate**
``AsyncSessionLocal()`` sessions — sequential calls cannot expose lost updates,
double consumption, or duplicate inserts.

Typical use::

    from tests.concurrency_helpers import race_sessions, require_database, status_counts

    async def test_double_approve_consumes_stock_once() -> None:
        await require_database()
        ...
        results = await race_sessions(approve, approve)
        assert status_counts(results) == {200: 1, 409: 1}

``status_counts`` normalizes each outcome to an HTTP status when the operation
raised :class:`AppException` or returned an ``httpx.Response``, so assertions can
be written against status codes rather than exception plumbing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, check_database, engine
from app.utils.exceptions import AppException

#: Operations receive a dedicated session; the return value is the test's outcome.
type SessionOperation[T] = Callable[[AsyncSession], Awaitable[T]]

DEFAULT_RACE_TIMEOUT_SECONDS = 30.0


async def require_database() -> None:
    """Skip the calling test when PostgreSQL is unreachable."""
    if not await check_database():
        pytest.skip("database is not available")


@pytest.fixture
async def isolated_engine_pool():
    """Give each test a clean connection pool (same pattern as the existing modules)."""
    await engine.dispose()
    yield
    await engine.dispose()


def outcome_key(result: Any) -> Any:
    """Reduce a race outcome to a comparable, hashable key."""
    if isinstance(result, AppException):
        return result.status_code
    status_code = getattr(result, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    if isinstance(result, BaseException):
        return type(result).__name__
    return result


def status_counts(results: Sequence[Any]) -> dict[Any, int]:
    """Count race outcomes by status code (or exception type / raw value)."""
    counts: dict[Any, int] = {}
    for result in results:
        key = outcome_key(result)
        counts[key] = counts.get(key, 0) + 1
    return counts


def error_codes(results: Sequence[Any]) -> list[str]:
    """Collect ``AppException.error_code`` values from a race, in completion order."""
    return [result.error_code for result in results if isinstance(result, AppException)]


async def race[T](*coros: Awaitable[T]) -> list[Any]:
    """Run awaitables concurrently, capturing failures instead of aborting the race.

    Each awaitable is responsible for its own session; prefer :func:`race_sessions`
    when the operations only need a session.
    """
    return await asyncio.gather(*coros, return_exceptions=True)


async def race_sessions[T](
    *operations: SessionOperation[T],
    timeout: float = DEFAULT_RACE_TIMEOUT_SECONDS,
) -> list[Any]:
    """Run one operation per fresh session, released simultaneously.

    A barrier holds every participant until all sessions are open, which makes the
    window for a genuine collision as wide as possible. Exceptions are returned as
    values so the caller can assert on the exact success/failure split.
    """
    if not operations:
        return []

    barrier = asyncio.Barrier(len(operations))

    async def run(operation: SessionOperation[T]) -> Any:
        async with AsyncSessionLocal() as session:
            await barrier.wait()
            try:
                return await operation(session)
            except Exception:
                await session.rollback()
                raise

    try:
        return await asyncio.wait_for(
            asyncio.gather(*(run(operation) for operation in operations), return_exceptions=True),
            timeout=timeout,
        )
    except TimeoutError as exc:
        raise AssertionError(
            f"race did not settle within {timeout}s — a participant is probably blocked "
            "on a lock held by another participant that never reached the barrier"
        ) from exc