"""One more try after an HTTP 429, as ADK's own session writer does
(VertexAiSessionService.append_event: one retry, one second later)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
RETRY_AFTER_S = 1.0


async def once_more_on_429(call: Callable[[], Awaitable[T]]) -> T:
    """Await ``call()``; if it fails with a rate limit (``code == 429``), wait
    and call it once more. Any other error, or a second 429, is raised."""
    try:
        return await call()
    except Exception as exc:
        if getattr(exc, "code", None) != 429:
            raise
    await asyncio.sleep(RETRY_AFTER_S)
    return await call()
