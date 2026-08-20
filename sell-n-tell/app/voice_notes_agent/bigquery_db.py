import os
import logging
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


def _insert_row(record: dict[str, Any]) -> None:
    """Write one committed record to the configured BigQuery table."""
    dataset_id = os.getenv("BIGQUERY_DATASET")
    table_id = os.getenv("BIGQUERY_TABLE")

    row_to_insert = {
        "crm_record_id": record["crm_record_id"],
        "session_id": record.get("staged_session_id"),
        "event_type": record.get("event_type"),
        "executive_summary": record.get("executive_summary"),
        "raw_transcript_backup": record.get("raw_transcript_backup"),
        "topics": record.get("topics", []),
        "planned_topics": record.get("planned_topics", []),
        "committed_at": record.get("committed_at"),
    }

    try:
        client = bigquery.Client()
        table_ref = f"{client.project}.{dataset_id}.{table_id}"
        errors = client.insert_rows_json(table_ref, [row_to_insert])
        if errors:
            logger.error("Failed to insert rows into BigQuery: %s", errors)
            raise RuntimeError(f"BigQuery insert failed: {errors}")

        logger.info(
            "Successfully committed record %s to BigQuery table %s",
            record["crm_record_id"],
            table_ref,
        )
    except Exception as e:
        # The mock_db commit above already succeeded and already deleted the
        # staged record, so this raise surfaces a *partial* commit: the CRM
        # record exists in the API response (which is what Salesforce syncs
        # from) but has no BigQuery row. Logged with the id so the row can be
        # reconciled; failing loudly beats silently dropping the sink write.
        logger.error(
            "BigQuery commit error for crm_record_id=%s: %s",
            record["crm_record_id"],
            e,
        )
        raise


def commit_notes(
    session_id: str,
    confirmed: bool,
    agent_mode: str = "implicit",
    campaign_type: str | None = None,
    ws_user_id: str | None = None,
    ws_session_id: str | None = None,
) -> dict[str, Any]:
    """Commit a staged payload, writing the committed row to BigQuery.

    Every gate lives in ``mock_db.commit_notes`` and is inherited by delegating
    to it rather than re-implemented here: the missing-record 404, the
    AIML-2703 supersede check, the AIML-2698 coverage gate, and the idempotent
    retry branch. This function owns only the BigQuery insert.

    Signature must track ``mock_db.commit_notes`` -- ``main.py`` calls whichever
    backend ``db_interface.get_db()`` returned with the same kwargs. See the
    ``CRMStore`` Protocol in ``db_interface.py``.
    """
    if confirmed:
        # Validated before delegating: mock_db.commit_notes mints the CRM
        # record and drops the staged one, so discovering a missing table here
        # afterwards would leave a commit that can never be re-tried.
        if not os.getenv("BIGQUERY_DATASET") or not os.getenv("BIGQUERY_TABLE"):
            logger.error(
                "BigQuery is enabled but BIGQUERY_DATASET or BIGQUERY_TABLE is missing."
            )
            raise ValueError("BigQuery configuration missing.")

    result = mock_db.commit_notes(
        session_id,
        confirmed,
        agent_mode=agent_mode,
        campaign_type=campaign_type,
        ws_user_id=ws_user_id,
        ws_session_id=ws_session_id,
    )

    # No ``_record`` means no new CRM record was created -- the commit was
    # cancelled (confirmed=False), or it was an idempotent retry replaying an
    # earlier result. Either way there is nothing to insert; inserting anyway
    # is exactly the duplicate row the idempotency guard exists to prevent.
    record = result.get("_record")
    if record is not None:
        _insert_row(record)

    return result


def list_committed() -> list[dict[str, Any]]:
    """Return committed records. For this stub, we return the local cache."""
    return mock_db.list_committed()
