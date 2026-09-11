"""Import notes_workflow without pulling in the ADK agent.

``voice_notes_agent/__init__.py`` constructs the agent at import time, which
needs ADK, Vertex config and a model name. The gates under test are plain
functions over in-process state and need none of that, so the module is
registered under a private package name and imported normally -- which lets
its ``from .schemas import ...`` resolve on its own, with no manual ordering.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

_PKG_DIR = Path(__file__).resolve().parents[1] / "app" / "voice_notes_agent"

if "_vna" not in sys.modules:
    _pkg = types.ModuleType("_vna")
    _pkg.__path__ = [str(_PKG_DIR)]
    sys.modules["_vna"] = _pkg

wf = importlib.import_module("_vna.notes_workflow")


@pytest.fixture(autouse=True)
def clean_store():
    """Each test starts from an empty staging store."""
    wf._STAGED_NOTES.clear()
    yield
    wf._STAGED_NOTES.clear()


@pytest.fixture
def workflow():
    return wf


def topic(name: str, code: int = 8, summary: str = "s") -> dict:
    return {
        "topic": name,
        "disposition_code": code,
        "executive_summary": summary,
        "discussed": True,
    }


def payload(topics: list[dict], summary: str = "Visit summary.") -> dict:
    return {
        "event_type": "Meeting",
        "executive_summary": summary,
        "raw_transcript_backup": "transcript",
        "topics": topics,
    }
