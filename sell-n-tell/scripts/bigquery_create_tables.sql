-- Run these in the BigQuery console's Query editor (paste, then Run).
-- Adjust the project/dataset prefix if yours differs from what's in app/.env
-- (VOICE_NOTES_BQ_DATASET=voice_notes_poc, GOOGLE_CLOUD_PROJECT=prj-hds-np-data).

CREATE TABLE `prj-hds-np-data.voice_notes_poc.implicit_flow_calls`
(
  crm_record_id STRING NOT NULL OPTIONS(description="Mock CRM record id generated on commit (CRM-XXXXXXXXXX)."),
  ws_user_id STRING OPTIONS(description="ADK/WebSocket user_id for the session."),
  ws_session_id STRING OPTIONS(description="ADK/WebSocket session_id -- the conversation-level id (browser-generated)."),
  staged_session_id STRING OPTIONS(description="mock_db's own internal staged-record uuid (stage -> commit correlation)."),
  agent_mode STRING NOT NULL OPTIONS(description="'implicit' or 'guided'."),
  campaign_type STRING,
  event_type STRING NOT NULL OPTIONS(description="Meeting | On-site visit | Phone Call"),
  executive_summary STRING OPTIONS(description="Overall 1-2 sentence call summary."),
  raw_transcript_backup STRING,
  planned_topics ARRAY<STRING> OPTIONS(description="Pre-call planned topic labels the rep selected."),
  missing_topics ARRAY<STRING> OPTIONS(description="Planned topics that ended up with no recorded outcome at commit time."),
  topics ARRAY<STRUCT<
    topic STRING,
    disposition_code INT64,
    disposition_label STRING,
    executive_summary STRING,
    discussed BOOL,
    needs_manual_review BOOL
  >> OPTIONS(description="One entry per discussed/planned topic."),
  correction_count INT64 OPTIONS(description="How many times the record was re-staged/corrected before commit."),
  staged_at TIMESTAMP,
  committed_at TIMESTAMP NOT NULL,
  environment STRING OPTIONS(description="e.g. 'local_dev' -- distinguishes demo-local data from future real deployments.")
)
OPTIONS(
  description="Implicit (Mega-Payload) flow: one row per committed call."
);

CREATE TABLE `prj-hds-np-data.voice_notes_poc.guided_flow_calls`
(
  crm_record_id STRING NOT NULL OPTIONS(description="Mock CRM record id generated on commit (CRM-XXXXXXXXXX)."),
  ws_user_id STRING OPTIONS(description="ADK/WebSocket user_id for the session."),
  ws_session_id STRING OPTIONS(description="ADK/WebSocket session_id -- the conversation-level id (browser-generated)."),
  staged_session_id STRING OPTIONS(description="mock_db's own internal staged-record uuid (stage -> commit correlation)."),
  agent_mode STRING NOT NULL OPTIONS(description="'implicit' or 'guided'."),
  campaign_type STRING,
  event_type STRING NOT NULL OPTIONS(description="Meeting | On-site visit | Phone Call"),
  executive_summary STRING OPTIONS(description="Overall 1-2 sentence call summary."),
  raw_transcript_backup STRING,
  planned_topics ARRAY<STRING> OPTIONS(description="Pre-call planned topic labels the rep selected."),
  missing_topics ARRAY<STRING> OPTIONS(description="Planned topics that ended up with no recorded outcome at commit time."),
  topics ARRAY<STRUCT<
    topic STRING,
    disposition_code INT64,
    disposition_label STRING,
    executive_summary STRING,
    discussed BOOL,
    needs_manual_review BOOL
  >> OPTIONS(description="One entry per discussed/planned topic. needs_manual_review=true after 3 failed confirm attempts."),
  correction_count INT64 OPTIONS(description="How many times the record was re-staged/corrected before commit."),
  staged_at TIMESTAMP,
  committed_at TIMESTAMP NOT NULL,
  environment STRING OPTIONS(description="e.g. 'local_dev' -- distinguishes demo-local data from future real deployments.")
)
OPTIONS(
  description="Guided (explicit turn-by-turn) flow: one row per committed call."
);
