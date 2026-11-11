import asyncio
from collections.abc import Awaitable

from app.database import engine


async def _run_with_fresh_pool[T](awaitable: Awaitable[T]) -> T:
    await engine.dispose()
    try:
        return await awaitable
    finally:
        await engine.dispose()


def run_async_task[T](awaitable: Awaitable[T]) -> T:
    return asyncio.run(_run_with_fresh_pool(awaitable))
