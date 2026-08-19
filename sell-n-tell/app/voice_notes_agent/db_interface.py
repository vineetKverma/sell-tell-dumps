import os
from typing import Any, Protocol

# We re-export the shared schemas from mock_db so that downstream consumers
# (main.py, tools.py) don't have to import mock_db directly.
from .mock_db import (
    DiscussionTopic,
    DispositionCode,
    VALID_DISPOSITION_CODES,
    VALID_CAMPAIGN_TYPES,
    VALID_EVENT_TYPES,
)

class CRMStore(Protocol):
    VALID_CAMPAIGN_TYPES: set[str]
    VALID_EVENT_TYPES: list[str]
    
    def get_agent_config(self, campaign_type: str | None) -> dict[str, Any]: ...
    def get_planned_topic_catalog(self) -> list[dict[str, str]]: ...
    def stage_notes(self, payload: dict[str, Any], previous_session_id: str | None = None, planned_topics: list[str] | None = None, session_id: str | None = None) -> dict[str, Any]: ...
    def commit_notes(self, session_id: str, confirmed: bool) -> dict[str, str]: ...
    def list_committed(self) -> list[dict[str, Any]]: ...

def get_db() -> CRMStore:
    if os.getenv("BIGQUERY_ENABLED", "false").lower() == "true":
        from . import bigquery_db
        return bigquery_db
    else:
        from . import mock_db
        return mock_db

db: CRMStore = get_db()
