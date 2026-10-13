"""The non-blocking session writer tries a rate-limited append once more.

main.py writes session events itself, off the request path, so it has to
repeat what ADK's own writer does on an HTTP 429. The helper is loaded from
its file: importing the package builds the agent.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
_spec = importlib.util.spec_from_file_location("_rate_limit", APP / "voice_notes_agent" / "rate_limit.py")
rate_limit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rate_limit)


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


def _call(*outcomes):
    """A call that raises or returns each outcome in turn; ``.count`` is how often it ran."""
    left = list(outcomes)

    async def call():
        call.count += 1
        result = left.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
    call.count = 0
    return call


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(rate_limit, "RETRY_AFTER_S", 0)


def test_a_rate_limited_append_is_tried_once_more():
    call = _call(ApiError(429), "stored")
    assert asyncio.run(rate_limit.once_more_on_429(call)) == "stored" and call.count == 2


def test_only_once_and_only_for_a_rate_limit():
    twice = _call(ApiError(429), ApiError(429), "never reached")
    with pytest.raises(ApiError):
        asyncio.run(rate_limit.once_more_on_429(twice))
    assert twice.count == 2
    for other in (ApiError(500), ApiError(403), ValueError("bad payload")):
        call = _call(other, "never reached")
        with pytest.raises(type(other)):
            asyncio.run(rate_limit.once_more_on_429(call))
        assert call.count == 1


def test_the_session_writer_uses_it():
    assert "await once_more_on_429(lambda: api_client.agent_engines.sessions.events.append(" in (
        APP / "main.py").read_text(encoding="utf-8")
