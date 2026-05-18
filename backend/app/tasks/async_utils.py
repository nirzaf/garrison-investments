import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from app.database import engine

T = TypeVar("T")


async def _run_with_fresh_pool(awaitable: Awaitable[T]) -> T:
    await engine.dispose()
    try:
        return await awaitable
    finally:
        await engine.dispose()


def run_async_task(awaitable: Awaitable[T]) -> T:
    return asyncio.run(_run_with_fresh_pool(awaitable))
