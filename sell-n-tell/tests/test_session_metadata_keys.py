"""The non-blocking session writer must use ADK's own custom-metadata keys.

main.py copies two private constants from ADK's VertexAiSessionService (it
writes events itself, off the request path). If the names differ, compaction
and usage data are stored under keys ADK's get_session never reads back. Both
files are read as text: importing main.py builds the app, and importing ADK's
session service needs the Vertex packages.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"
KEYS = ("_COMPACTION_CUSTOM_METADATA_KEY", "_USAGE_METADATA_CUSTOM_METADATA_KEY")


def _constants(text: str) -> dict[str, str]:
    return {k: v for k, v in re.findall(r"^(_\w+_CUSTOM_METADATA_KEY)\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)}


def _adk_session_service_source() -> str:
    spec = importlib.util.find_spec("google.adk.sessions")
    if spec is None or not spec.submodule_search_locations:
        pytest.skip("google-adk not installed")
    path = Path(next(iter(spec.submodule_search_locations))) / "vertex_ai_session_service.py"
    if not path.exists():
        # ADK is installed but the file moved: fail, so CI notices the guard
        # can no longer check anything (a skip would hide it).
        pytest.fail(f"ADK is installed but {path.name} is not where this guard reads it: {path}")
    return path.read_text(encoding="utf-8")


def test_main_uses_adks_custom_metadata_keys():
    adk = _constants(_adk_session_service_source())
    ours = _constants(MAIN.read_text(encoding="utf-8"))
    for key in KEYS:
        assert key in adk, f"ADK no longer defines {key}"
        assert ours.get(key) == adk[key], f"{key}: main.py {ours.get(key)!r} vs ADK {adk[key]!r}"
