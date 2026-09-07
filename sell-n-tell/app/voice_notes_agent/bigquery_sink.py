"""Best-effort BigQuery sink for committed call records.

Writes one row per committed call to a table keyed by ``agent_mode``
("implicit" -> ``VOICE_NOTES_BQ_TABLE_IMPLICIT``, "guided" ->
``VOICE_NOTES_BQ_TABLE_GUIDED``) so the two flows can be compared side by
side for the demo.

The guided flow itself was removed in AIML-2751, so nothing writes to the
guided table any more. The mapping stays: the rows already there are the
historical comparison data the mode decision was made on.

This must NEVER take down a live call or the commit REST response: every
failure path (missing config, unreachable BigQuery, bad schema) is caught and
logged, never raised. Table creation is manual (BigQuery console); this
module only inserts rows into tables that already exist.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

_ENABLED = os.getenv("VOICE_NOTES_BQ_ENABLED", "true").strip().lower() not in (
    "false",
    "0",
    "",
)
_PROJECT = os.getenv("VOICE_NOTES_BQ_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
_DATASET = os.getenv("VOICE_NOTES_BQ_DATASET", "voice_notes_poc")
_ENVIRONMENT = os.getenv("VOICE_NOTES_ENVIRONMENT", "local_dev")
_TABLES = {
    "implicit": os.getenv("VOICE_NOTES_BQ_TABLE_IMPLICIT", "implicit_flow_calls"),
    "guided": os.getenv("VOICE_NOTES_BQ_TABLE_GUIDED", "guided_flow_calls"),
}


@lru_cache(maxsize=1)
def _client():
    from google.cloud import bigquery  # local import: optional dep at runtime

    return bigquery.Client(project=_PROJECT)


def _disposition_label(code: int | None, disposition_config: dict | None) -> str | None:
    if code is None or not disposition_config:
        return None
    for rule in disposition_config.get("disposition_registry", []):
        if rule.get("code") == code:
            return rule.get("label")
    return None


def _build_row(
    record: dict[str, Any], disposition_config: dict | None
) -> dict[str, Any]:
    return {
        "crm_record_id": record.get("crm_record_id"),
        "ws_user_id": record.get("ws_user_id"),
        "ws_session_id": record.get("ws_session_id"),
        "staged_session_id": record.get("staged_session_id"),
        "agent_mode": record.get("agent_mode") or "implicit",
        "campaign_type": record.get("campaign_type"),
        "event_type": record.get("event_type"),
        "executive_summary": record.get("executive_summary"),
        "raw_transcript_backup": record.get("raw_transcript_backup"),
        "planned_topics": list(record.get("planned_topics") or []),
        "missing_topics": list(record.get("missing_topics") or []),
        "topics": [
            {
                "topic": t.get("topic"),
                "disposition_code": t.get("disposition_code"),
                "disposition_label": _disposition_label(
                    t.get("disposition_code"), disposition_config
                ),
                "executive_summary": t.get("executive_summary"),
                "discussed": t.get("discussed"),
                "needs_manual_review": t.get("needs_manual_review", False),
            }
            for t in (record.get("topics") or [])
        ],
        "correction_count": record.get("correction_count", 0),
        "staged_at": record.get("staged_at"),
        "committed_at": record.get("committed_at"),
        "environment": _ENVIRONMENT,
    }


def insert_call_record(
    record: dict[str, Any], disposition_config: dict | None = None
) -> None:
    """Insert one committed call record into the table for its agent_mode.

    Synchronous/blocking (the ``google-cloud-bigquery`` client has no native
    asyncio support) -- callers on the event loop should run this via
    ``asyncio.to_thread``.
    """
    if not _ENABLED:
        logger.debug("BigQuery sink disabled (VOICE_NOTES_BQ_ENABLED=false)")
        return

    agent_mode = record.get("agent_mode") or "implicit"
    table_name = _TABLES.get(agent_mode)
    crm_record_id = record.get("crm_record_id")
    if not table_name or not _PROJECT:
        logger.warning(
            "BigQuery sink skipped for crm_record_id=%s: agent_mode=%s "
            "project=%s table=%s (check VOICE_NOTES_BQ_PROJECT / "
            "GOOGLE_CLOUD_PROJECT)",
            crm_record_id,
            agent_mode,
            _PROJECT,
            table_name,
        )
        return

    table_ref = f"{_PROJECT}.{_DATASET}.{table_name}"
    try:
        row = _build_row(record, disposition_config)
        errors = _client().insert_rows_json(table_ref, [row])
    except Exception:  # noqa: BLE001 - must never break the commit flow
        logger.exception(
            "BigQuery insert failed for crm_record_id=%s table=%s",
            crm_record_id,
            table_ref,
        )
        return

    if errors:
        logger.error(
            "BigQuery insert returned errors for crm_record_id=%s table=%s: %s",
            crm_record_id,
            table_ref,
            errors,
        )
    else:
        logger.info(
            "BigQuery insert OK crm_record_id=%s table=%s", crm_record_id, table_ref
        )
