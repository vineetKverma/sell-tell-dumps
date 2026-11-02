"""Tests for BigQuery Agent Analytics Plugin configuration and lifespan pre-warming (AIML-2823).

Constructs the plugin via factory and verifies pre-warm/shutdown lifecycles
without importing app.main or requiring live GCP credentials.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.adk.plugins.bigquery_agent_analytics_plugin import (
    _SCHEMA_VERSION,
    _SCHEMA_VERSION_LABEL_KEY,
    _get_events_schema,
)

from app.analytics import (
    build_bigquery_analytics_plugin,
    get_analytics_status,
    prewarm_analytics_plugins,
    shutdown_analytics_plugins,
)

_BIGQUERY_TYPE_MAP = {
    "INT64": "INTEGER",
    "BOOL": "BOOLEAN",
    "STRUCT": "RECORD",
}


def _split_top_level(text: str, delimiter: str = ",") -> list[str]:
    """Split text by delimiter, ignoring delimiters inside angle brackets or parentheses."""
    parts = []
    current = []
    angle_depth = 0
    paren_depth = 0
    for char in text:
        if char == "<":
            angle_depth += 1
            current.append(char)
        elif char == ">":
            angle_depth -= 1
            current.append(char)
        elif char == "(":
            paren_depth += 1
            current.append(char)
        elif char == ")":
            paren_depth -= 1
            current.append(char)
        elif char == delimiter and angle_depth == 0 and paren_depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)
    last = "".join(current).strip()
    if last:
        parts.append(last)
    return parts


def _parse_ddl_column(col_str: str) -> dict[str, Any]:
    """Parse DDL column definition into (name, type, mode, fields)."""
    # Strip OPTIONS(...)
    col_str = re.sub(r"\s+OPTIONS\s*\(.*?\)$", "", col_str, flags=re.DOTALL).strip()

    match = re.match(r"^([a-z_0-9]+)\s+(.+)$", col_str, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Cannot parse column: {col_str}")
    name, type_expr = match.group(1), match.group(2).strip()

    mode = "NULLABLE"
    if " NOT NULL" in type_expr:
        mode = "REQUIRED"
        type_expr = re.sub(r"\s+NOT NULL\b", "", type_expr).strip()

    if type_expr.startswith("ARRAY<") and type_expr.endswith(">"):
        mode = "REPEATED"
        inner_type = type_expr[len("ARRAY<") : -1].strip()
    else:
        inner_type = type_expr

    fields = []
    if inner_type.startswith("STRUCT<") and inner_type.endswith(">"):
        field_type = "RECORD"
        struct_body = inner_type[len("STRUCT<") : -1].strip()
        for sub_str in _split_top_level(struct_body, ","):
            fields.append(_parse_ddl_column(sub_str))
    else:
        field_type = _BIGQUERY_TYPE_MAP.get(inner_type.upper(), inner_type.upper())

    return {
        "name": name,
        "type": field_type,
        "mode": mode,
        "fields": fields,
    }


def _schema_field_to_dict(sf) -> dict[str, Any]:
    """Convert ADK SchemaField to normalized dict for comparison."""
    subfields = [_schema_field_to_dict(f) for f in sf.fields] if sf.fields else []
    return {
        "name": sf.name,
        "type": sf.field_type.upper(),
        "mode": sf.mode.upper(),
        "fields": subfields,
    }


@pytest.fixture(autouse=True)
def reset_analytics_status():
    """Reset module-global _ANALYTICS_STATUS before and after each test."""
    from app import analytics

    initial = {
        "configured": False,
        "enabled": False,
        "prewarmed": False,
        "error_code": None,
        "table_id": None,
        "error": None,
    }
    analytics._ANALYTICS_STATUS.clear()
    analytics._ANALYTICS_STATUS.update(initial)
    yield
    analytics._ANALYTICS_STATUS.clear()
    analytics._ANALYTICS_STATUS.update(initial)


def test_build_bigquery_analytics_plugin_valid():
    """Verify plugin instantiation sets create_views=False and correct dataset/table configuration."""
    plugin = build_bigquery_analytics_plugin(
        project_id="test-project",
        dataset_id="voice_notes_poc",
        table_id="agent_events",
        location="US",
        credentials=MagicMock(),
    )

    assert plugin is not None
    assert hasattr(plugin, "config")
    assert plugin.config.create_views is False
    assert plugin.dataset_id == "voice_notes_poc"
    assert plugin.project_id == "test-project"
    assert plugin.table_id == "agent_events"
    assert plugin.location == "US"


def test_build_bigquery_analytics_plugin_missing_project_returns_none(caplog):
    """Verify missing project_id disables plugin and logs warning."""
    with caplog.at_level(logging.WARNING):
        plugin = build_bigquery_analytics_plugin(
            project_id=None,
            dataset_id="voice_notes_poc",
        )
    assert plugin is None
    assert "GOOGLE_CLOUD_PROJECT not set" in caplog.text


def test_build_bigquery_analytics_plugin_missing_dataset_returns_none(caplog):
    """Verify missing dataset_id disables plugin and logs warning (no silent code fallback)."""
    with caplog.at_level(logging.WARNING):
        plugin = build_bigquery_analytics_plugin(
            project_id="test-project",
            dataset_id=None,
        )
    assert plugin is None
    assert "BQ_ANALYTICS_DATASET_ID is not set" in caplog.text


def test_build_bigquery_analytics_plugin_warns_when_credentials_none(caplog):
    """Verify warning is logged when credentials are None (falling back to google.auth.default)."""
    with caplog.at_level(logging.WARNING):
        plugin = build_bigquery_analytics_plugin(
            project_id="test-project",
            dataset_id="voice_notes_poc",
            credentials=None,
        )
    assert plugin is not None
    assert "Pre-warmed live_client credentials not found" in caplog.text


def test_bigquery_ddl_matches_adk_schema():
    """Verify scripts/bigquery_create_tables.sql matches ADK's expected schema, types, modes, and version label.

    Prevents schema drift where missing columns or type/mode mismatches cause ADK's
    auto_schema_upgrade to attempt in-place DDL updates or raise schema incompatibility errors.
    Validates top-level and nested STRUCT fields, mapping INT64 -> INTEGER, BOOL -> BOOLEAN,
    NOT NULL -> REQUIRED, and ARRAY<...> -> REPEATED.
    """
    sql_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "scripts"
        / "bigquery_create_tables.sql"
    )
    assert sql_path.exists(), f"DDL script not found at {sql_path}"
    content = sql_path.read_text(encoding="utf-8")

    # Locate the agent_events table definition
    assert "agent_events" in content
    table_part = content.split("agent_events`")[1]
    partition_idx = (
        table_part.find(")\nPARTITION")
        if ")\nPARTITION" in table_part
        else table_part.find(")\r\nPARTITION")
    )
    columns_block = table_part[table_part.find("(") + 1 : partition_idx].strip()

    col_defs = _split_top_level(columns_block, ",")
    parsed_ddl = [_parse_ddl_column(c) for c in col_defs]

    expected_schema = [_schema_field_to_dict(sf) for sf in _get_events_schema()]

    assert parsed_ddl == expected_schema, (
        f"DDL schema in bigquery_create_tables.sql does not match ADK schema.\n"
        f"DDL: {parsed_ddl}\nADK: {expected_schema}"
    )

    # Verify the schema version label matches ADK's current schema version
    expected_label = f'("{_SCHEMA_VERSION_LABEL_KEY}", "{_SCHEMA_VERSION}")'
    assert expected_label in content, (
        f"Expected label {expected_label} not found in bigquery_create_tables.sql"
    )


def test_bigquery_ddl_schema_validation_catches_type_and_mode_mismatches():
    """Verify that _parse_ddl_column strictly detects type and mode incompatibilities."""
    # Type mismatch: STRING instead of JSON
    col_str = 'content STRING OPTIONS(description="Event payload")'
    parsed = _parse_ddl_column(col_str)
    assert parsed["type"] == "STRING"
    assert parsed["mode"] == "NULLABLE"

    # Mode mismatch: missing NOT NULL makes mode NULLABLE instead of REQUIRED
    col_str = 'timestamp TIMESTAMP OPTIONS(description="Time of event")'
    parsed = _parse_ddl_column(col_str)
    assert parsed["mode"] == "NULLABLE"

    # Nested type mismatch in STRUCT
    col_str = (
        "content_parts ARRAY<STRUCT<mime_type STRING, part_index STRING>>"
    )
    parsed = _parse_ddl_column(col_str)
    assert parsed["mode"] == "REPEATED"
    assert parsed["fields"][1]["name"] == "part_index"
    assert parsed["fields"][1]["type"] == "STRING"  # Expected INTEGER/INT64


@pytest.mark.asyncio
async def test_prewarm_analytics_plugins_success():
    """Verify successful pre-warm awaits _ensure_started, verifies table access with timeout, and sets enabled."""
    mock_plugin = MagicMock()
    mock_plugin._started = False
    mock_plugin.full_table_id = "test-project.voice_notes_poc.agent_events"
    mock_plugin.client = MagicMock()

    async def fake_ensure_started():
        mock_plugin._started = True

    mock_plugin._ensure_started = AsyncMock(side_effect=fake_ensure_started)
    mock_plugin.config = MagicMock()
    mock_plugin.config.enabled = True

    await prewarm_analytics_plugins([mock_plugin])

    mock_plugin._ensure_started.assert_awaited_once()
    mock_plugin.client.get_table.assert_called_once()
    call_args = mock_plugin.client.get_table.call_args
    assert call_args.args[0] == "test-project.voice_notes_poc.agent_events"
    assert call_args.kwargs["timeout"] == 10.0
    assert call_args.kwargs["retry"]._timeout == 10.0
    assert mock_plugin.config.enabled is True
    status = get_analytics_status()
    assert status["prewarmed"] is True
    assert status["enabled"] is True
    assert status["error_code"] is None


@pytest.mark.asyncio
async def test_prewarm_analytics_plugins_table_check_failure_disables_plugin(caplog):
    """Verify table access failure after _started=True disables plugin and logs ERROR with TABLE_CHECK_FAILED.

    Acts as defense-in-depth: the explicit get_table check in prewarm_analytics_plugins
    verifies table access and disables the plugin if BigQuery rejects the check.
    """
    mock_plugin = MagicMock()
    mock_plugin._started = False
    mock_plugin.full_table_id = "test-project.voice_notes_poc.agent_events"
    mock_plugin.client = MagicMock()
    mock_plugin.client.get_table.side_effect = RuntimeError("404 Not Found: Table agent_events")

    async def fake_ensure_started():
        mock_plugin._started = True

    mock_plugin._ensure_started = AsyncMock(side_effect=fake_ensure_started)
    mock_plugin.config = MagicMock()
    mock_plugin.config.enabled = True

    with caplog.at_level(logging.ERROR):
        await prewarm_analytics_plugins([mock_plugin])

    mock_plugin.client.get_table.assert_called_once()
    call_args = mock_plugin.client.get_table.call_args
    assert call_args.args[0] == "test-project.voice_notes_poc.agent_events"
    assert call_args.kwargs["timeout"] == 10.0
    assert call_args.kwargs["retry"]._timeout == 10.0
    assert mock_plugin.config.enabled is False
    assert (
        "BigQuery analytics table verification failed for table 'test-project.voice_notes_poc.agent_events'"
        in caplog.text
    )
    status = get_analytics_status()
    assert status["prewarmed"] is False
    assert status["enabled"] is False
    assert status["error_code"] == "TABLE_CHECK_FAILED"


@pytest.mark.asyncio
async def test_prewarm_analytics_plugins_adk_startup_failure_disables_plugin(caplog):
    """Verify ADK startup failure (_started=False, _startup_error set) disables plugin and logs ERROR."""
    mock_plugin = MagicMock()
    mock_plugin._started = False
    mock_plugin._startup_error = RuntimeError("BigQuery table not accessible")
    mock_plugin._ensure_started = AsyncMock()  # ADK catches exceptions and does not raise
    mock_plugin.config = MagicMock()
    mock_plugin.config.enabled = True

    with caplog.at_level(logging.ERROR):
        await prewarm_analytics_plugins([mock_plugin])

    mock_plugin._ensure_started.assert_awaited_once()
    assert mock_plugin.config.enabled is False
    assert "pre-warming failed: BigQuery table not accessible; disabling plugin" in caplog.text
    status = get_analytics_status()
    assert status["prewarmed"] is False
    assert status["enabled"] is False
    assert status["error_code"] == "PREWARM_FAILED"


@pytest.mark.asyncio
async def test_prewarm_analytics_plugins_timeout_disables_plugin(caplog):
    """Verify pre-warm timeout stops waiting, disables plugin, and logs ERROR so live turns do not stall."""
    mock_plugin = MagicMock()
    mock_plugin._started = False

    async def slow_ensure_started():
        await asyncio.sleep(1.0)
        mock_plugin._started = True

    mock_plugin._ensure_started = AsyncMock(side_effect=slow_ensure_started)
    mock_plugin.config = MagicMock()
    mock_plugin.config.enabled = True

    with caplog.at_level(logging.ERROR):
        await prewarm_analytics_plugins([mock_plugin], timeout=0.01)

    assert mock_plugin.config.enabled is False
    assert "timed out after 0.0s; disabling plugin" in caplog.text
    status = get_analytics_status()
    assert status["prewarmed"] is False
    assert status["enabled"] is False
    assert status["error_code"] == "PREWARM_TIMEOUT"


@pytest.mark.asyncio
async def test_prewarm_analytics_plugins_unexpected_exception_disables_plugin(caplog):
    """Verify unexpected exception during pre-warm disables plugin without crashing."""
    mock_plugin = MagicMock()
    mock_plugin._started = False
    mock_plugin._ensure_started = AsyncMock(side_effect=RuntimeError("Unexpected error"))
    mock_plugin.config = MagicMock()
    mock_plugin.config.enabled = True

    with caplog.at_level(logging.ERROR):
        await prewarm_analytics_plugins([mock_plugin])

    assert mock_plugin.config.enabled is False
    assert "pre-warming failed: Unexpected error; disabling plugin." in caplog.text
    status = get_analytics_status()
    assert status["prewarmed"] is False
    assert status["enabled"] is False
    assert status["error_code"] == "PREWARM_FAILED"


@pytest.mark.asyncio
async def test_shutdown_analytics_plugins_success():
    """Verify shutdown flushes pending audit records."""
    mock_plugin = MagicMock()
    mock_plugin.shutdown = AsyncMock()

    await shutdown_analytics_plugins([mock_plugin])

    mock_plugin.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_analytics_plugins_tolerates_exception(caplog):
    """Verify shutdown error is caught and logged without crashing server exit."""
    mock_plugin = MagicMock()
    mock_plugin.shutdown = AsyncMock(side_effect=RuntimeError("Flush timeout"))

    with caplog.at_level(logging.WARNING):
        await shutdown_analytics_plugins([mock_plugin])

    mock_plugin.shutdown.assert_awaited_once()
    assert "Error shutting down BigQuery analytics plugin" in caplog.text


@pytest.mark.asyncio
async def test_shutdown_analytics_plugins_timeout_logs_warning(caplog):
    """Verify shutdown times out gracefully with warning if plugin.shutdown hangs."""
    mock_plugin = MagicMock()

    async def hanging_shutdown():
        await asyncio.sleep(1.0)

    mock_plugin.shutdown = AsyncMock(side_effect=hanging_shutdown)

    with caplog.at_level(logging.WARNING):
        await shutdown_analytics_plugins([mock_plugin], timeout=0.01)

    assert "Timed out flushing BigQuery analytics plugin queue after 0.0s on shutdown" in caplog.text


def test_get_analytics_status_sanitized_keys():
    """Verify get_analytics_status exposes only safe booleans and error_code, never table_id or raw error."""
    from app import analytics

    analytics._ANALYTICS_STATUS["table_id"] = "secret-prj.voice_notes_poc.agent_events"
    analytics._ANALYTICS_STATUS["error"] = "google.api_core.exceptions.Forbidden: 403 IAM permission denied"

    status = get_analytics_status()
    assert isinstance(status, dict)
    assert set(status.keys()) == {"configured", "enabled", "prewarmed", "error_code"}
    assert "table_id" not in status
    assert "error" not in status
    assert "secret-prj" not in str(status)


def test_build_bigquery_analytics_plugin_missing_project_sets_error_code():
    """Verify missing project_id records MISSING_PROJECT error_code."""
    plugin = build_bigquery_analytics_plugin(
        project_id=None,
        dataset_id="voice_notes_poc",
    )
    assert plugin is None
    status = get_analytics_status()
    assert status["configured"] is False
    assert status["enabled"] is False
    assert status["error_code"] == "MISSING_PROJECT"


def test_build_bigquery_analytics_plugin_missing_dataset_sets_error_code():
    """Verify missing dataset_id records MISSING_DATASET error_code."""
    plugin = build_bigquery_analytics_plugin(
        project_id="test-project",
        dataset_id=None,
    )
    assert plugin is None
    status = get_analytics_status()
    assert status["configured"] is False
    assert status["enabled"] is False
    assert status["error_code"] == "MISSING_DATASET"
