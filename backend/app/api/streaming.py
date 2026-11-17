from collections.abc import AsyncIterable, Awaitable, Callable

from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send


class ManagedEventStream(StreamingResponse):
    def __init__(
        self, content: AsyncIterable[str], release: Callable[[], Awaitable[None]]
    ) -> None:
        super().__init__(
            content, media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
        )
        self._release = release

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A disconnect can interrupt the response between iterator reads.
            await self._release()
