import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery

# Reuse mock_db for staging and configuration. BigQuery is only for the committed sink.
from . import mock_db

logger = logging.getLogger(__name__)

VALID_CAMPAIGN_TYPES = mock_db.VALID_CAMPAIGN_TYPES
VALID_EVENT_TYPES = mock_db.VALID_EVENT_TYPES
get_agent_config = mock_db.get_agent_config
get_planned_topic_catalog = mock_db.get_planned_topic_catalog
stage_notes = mock_db.stage_notes

def commit_notes(session_id: str, confirmed: bool) -> dict[str, str]:
    """Commit notes to BigQuery."""
    record = mock_db.get_staged(session_id)
    if record is None:
        raise KeyError(f"No staged notes found for session_id={session_id}")
        
    if not confirmed:
        # Handled by mock_db
        return mock_db.commit_notes(session_id, confirmed)
        
    dataset_id = os.getenv("BIGQUERY_DATASET")
    table_id = os.getenv("BIGQUERY_TABLE")
    
    if not dataset_id or not table_id:
        logger.error("BigQuery is enabled but BIGQUERY_DATASET or BIGQUERY_TABLE is missing.")
        raise ValueError("BigQuery configuration missing.")
        
    crm_record_id = f"CRM-{uuid.uuid4().hex[:10].upper()}"
    committed_at = datetime.now(timezone.utc).isoformat()
    
    payload = record["payload"]
    row_to_insert = {
        "crm_record_id": crm_record_id,
        "session_id": session_id,
        "event_type": payload.get("event_type"),
        "executive_summary": payload.get("executive_summary"),
        "raw_transcript_backup": payload.get("raw_transcript_backup"),
        "topics": payload.get("topics", []),
        "planned_topics": record.get("planned_topics", []),
        "committed_at": committed_at,
    }
    
    try:
        client = bigquery.Client()
        table_ref = f"{client.project}.{dataset_id}.{table_id}"
        errors = client.insert_rows_json(table_ref, [row_to_insert])
        if errors:
            logger.error("Failed to insert rows into BigQuery: %s", errors)
            raise RuntimeError(f"BigQuery insert failed: {errors}")
            
        logger.info("Successfully committed record %s to BigQuery table %s", crm_record_id, table_ref)
    except Exception as e:
        logger.error("BigQuery commit error: %s", e)
        raise
        
    # Clean up staged note
    del mock_db._STAGED_NOTES[session_id]
    
    # Optionally append to mock_db's in-memory list so the UI history still works
    mock_db._COMMITTED_NOTES.append(row_to_insert)

    return {
        "status": "success",
        "crm_record_id": crm_record_id,
        "closing_statement": "Saved successfully. Have a great day!",
    }

def list_committed() -> list[dict[str, Any]]:
    """Return committed records. For this stub, we return the local cache."""
    return mock_db.list_committed()
