"""One more try after an HTTP 429, as ADK's own session writer does
(VertexAiSessionService.append_event: one retry, one second later)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

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
        # Logged so production shows how often this happens: the wait sits in
        # the session's ordered write chain, so it delays every event behind
        # it, and on disconnect the flush window is short.
        logger.warning(
            "Rate-limited (HTTP 429); retrying once in %.1f s: %s",
            RETRY_AFTER_S,
            exc,
        )
    await asyncio.sleep(RETRY_AFTER_S)
    return await call()
