# scripts

branch: `feature/AIML-2751-remove-guided`  commit: `6ffd86f`  files: 4

<!-- FILE: scripts/bigquery_create_tables.sql -->
````sql
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
````
<!-- END: scripts/bigquery_create_tables.sql -->

<!-- FILE: scripts/bigquery_schema.json -->
````json
[
  { "name": "crm_record_id", "type": "STRING", "mode": "REQUIRED", "description": "Mock CRM record id generated on commit (CRM-XXXXXXXXXX)." },
  { "name": "ws_user_id", "type": "STRING", "mode": "NULLABLE", "description": "ADK/WebSocket user_id for the session." },
  { "name": "ws_session_id", "type": "STRING", "mode": "NULLABLE", "description": "ADK/WebSocket session_id -- the conversation-level id (browser-generated)." },
  { "name": "staged_session_id", "type": "STRING", "mode": "NULLABLE", "description": "mock_db's own internal staged-record uuid (stage -> commit correlation)." },
  { "name": "agent_mode", "type": "STRING", "mode": "REQUIRED", "description": "'implicit' or 'guided'. Redundant with which table this row is in, kept for safety if tables are ever unioned." },
  { "name": "campaign_type", "type": "STRING", "mode": "NULLABLE" },
  { "name": "event_type", "type": "STRING", "mode": "REQUIRED", "description": "Meeting | On-site visit | Phone Call" },
  { "name": "executive_summary", "type": "STRING", "mode": "NULLABLE", "description": "Overall 1-2 sentence call summary." },
  { "name": "raw_transcript_backup", "type": "STRING", "mode": "NULLABLE" },
  { "name": "planned_topics", "type": "STRING", "mode": "REPEATED", "description": "Pre-call planned topic labels the rep selected." },
  { "name": "missing_topics", "type": "STRING", "mode": "REPEATED", "description": "Planned topics that ended up with no recorded outcome at commit time." },
  {
    "name": "topics",
    "type": "RECORD",
    "mode": "REPEATED",
    "fields": [
      { "name": "topic", "type": "STRING", "mode": "NULLABLE" },
      { "name": "disposition_code", "type": "INTEGER", "mode": "NULLABLE" },
      { "name": "disposition_label", "type": "STRING", "mode": "NULLABLE" },
      { "name": "executive_summary", "type": "STRING", "mode": "NULLABLE" },
      { "name": "discussed", "type": "BOOLEAN", "mode": "NULLABLE" },
      { "name": "needs_manual_review", "type": "BOOLEAN", "mode": "NULLABLE", "description": "Guided flow: true if 3 disposition-confirm attempts failed." }
    ]
  },
  { "name": "correction_count", "type": "INTEGER", "mode": "NULLABLE", "description": "How many times the record was re-staged/corrected before commit." },
  { "name": "staged_at", "type": "TIMESTAMP", "mode": "NULLABLE" },
  { "name": "committed_at", "type": "TIMESTAMP", "mode": "REQUIRED" },
  { "name": "environment", "type": "STRING", "mode": "NULLABLE", "description": "e.g. 'local_dev' -- distinguishes demo-local data from future real deployments." }
]
````
<!-- END: scripts/bigquery_schema.json -->

<!-- FILE: scripts/smoke_test_output.txt -->
````text
(voice-notes-logger) PS C:\Users\5000240\sellNtell_dev\sell-n-tell> uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
INFO:     Will watch for changes in these directories: ['C:\\Users\\5000240\\sellNtell_dev\\sell-n-tell']
2026-09-01 01:55:09,242 - google_adk.google.adk.plugins.plugin_manager - INFO - Plugin 'bigquery_agent_analytics' registered.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [28336] using WatchFiles
2026-09-01 01:55:16,116 - google_adk.google.adk.plugins.plugin_manager - INFO - Plugin 'bigquery_agent_analytics' registered.
INFO:     Started server process [14548]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     127.0.0.1:64938 - "GET / HTTP/1.1" 200 OK
INFO:     127.0.0.1:64938 - "GET /static/css/style.css?v=3 HTTP/1.1" 200 OK
INFO:     127.0.0.1:64938 - "GET /static/js/app.js?v=9 HTTP/1.1" 200 OK
INFO:     127.0.0.1:64938 - "GET /static/js/audio-player.js?v=9 HTTP/1.1" 200 OK
INFO:     127.0.0.1:60000 - "GET /static/js/audio-recorder.js?v=9 HTTP/1.1" 200 OK
INFO:     127.0.0.1:60000 - "GET /api/v1/client-config HTTP/1.1" 404 Not Found
INFO:     127.0.0.1:61731 - "GET /static/js/pcm-player-processor.js HTTP/1.1" 200 OK
INFO:     127.0.0.1:61731 - "GET /static/js/pcm-recorder-processor.js HTTP/1.1" 200 OK
INFO:     127.0.0.1:57723 - "WebSocket /ws/rep-23ee446d-57d8-48ea-b565-6dc2af503ada/sess-8049e227-1443-4905-8554-1ce8432a7ed8?planned_topics=Hardware&agent_mode=implicit&campaign_type=standard_sales" [accepted]
2026-09-01 01:55:45,961 - app.main - INFO - WS connect user_id=rep-23ee446d-57d8-48ea-b565-6dc2af503ada session_id=sess-8049e227-1443-4905-8554-1ce8432a7ed8 planned=['Hardware']
INFO:     connection open
2026-09-01 01:55:46,947 - app.main - INFO - Upstream audio: 50 chunks, 32000 bytes total
2026-09-01 01:55:47,955 - app.main - INFO - Upstream audio: 100 chunks, 64000 bytes total
2026-09-01 01:55:48,950 - app.main - INFO - Upstream audio: 150 chunks, 96000 bytes total
2026-09-01 01:55:49,939 - app.main - INFO - Upstream audio: 200 chunks, 128000 bytes total
2026-09-01 01:55:50,954 - app.main - INFO - Upstream audio: 250 chunks, 160000 bytes total
2026-09-01 01:55:51,950 - app.main - INFO - Upstream audio: 300 chunks, 192000 bytes total
2026-09-01 01:55:52,946 - app.main - INFO - Upstream audio: 350 chunks, 224000 bytes total
2026-09-01 01:55:53,954 - app.main - INFO - Upstream audio: 400 chunks, 256000 bytes total
2026-09-01 01:55:54,950 - app.main - INFO - Upstream audio: 450 chunks, 288000 bytes total
2026-09-01 01:55:55,948 - app.main - INFO - Upstream audio: 500 chunks, 320000 bytes total
2026-09-01 01:55:56,957 - app.main - INFO - Upstream audio: 550 chunks, 352000 bytes total
2026-09-01 01:55:57,951 - app.main - INFO - Upstream audio: 600 chunks, 384000 bytes total
2026-09-01 01:55:58,946 - app.main - INFO - Upstream audio: 650 chunks, 416000 bytes total
2026-09-01 01:55:59,954 - app.main - INFO - Upstream audio: 700 chunks, 448000 bytes total
2026-09-01 01:56:00,953 - app.main - INFO - Upstream audio: 750 chunks, 480000 bytes total
2026-09-01 01:56:01,946 - app.main - INFO - Upstream audio: 800 chunks, 512000 bytes total
2026-09-01 01:56:02,954 - app.main - INFO - Upstream audio: 850 chunks, 544000 bytes total
2026-09-01 01:56:03,950 - app.main - INFO - Upstream audio: 900 chunks, 576000 bytes total
2026-09-01 01:56:04,946 - app.main - INFO - Upstream audio: 950 chunks, 608000 bytes total
2026-09-01 01:56:05,955 - app.main - INFO - Upstream audio: 1000 chunks, 640000 bytes total
2026-09-01 01:56:06,954 - app.main - INFO - Upstream audio: 1050 chunks, 672000 bytes total
2026-09-01 01:56:07,938 - app.main - INFO - Upstream audio: 1100 chunks, 704000 bytes total
2026-09-01 01:56:08,954 - app.main - INFO - Upstream audio: 1150 chunks, 736000 bytes total
2026-09-01 01:56:09,956 - app.main - INFO - Upstream audio: 1200 chunks, 768000 bytes total
2026-09-01 01:56:10,947 - app.main - INFO - Upstream audio: 1250 chunks, 800000 bytes total
2026-09-01 01:56:11,958 - app.main - INFO - Upstream audio: 1300 chunks, 832000 bytes total
2026-09-01 01:56:12,950 - app.main - INFO - Upstream audio: 1350 chunks, 864000 bytes total
2026-09-01 01:56:13,946 - app.main - INFO - Upstream audio: 1400 chunks, 896000 bytes total
2026-09-01 01:56:14,957 - app.main - INFO - Upstream audio: 1450 chunks, 928000 bytes total
2026-09-01 01:56:15,951 - app.main - INFO - Upstream audio: 1500 chunks, 960000 bytes total
2026-09-01 01:56:16,947 - app.main - INFO - Upstream audio: 1550 chunks, 992000 bytes total
2026-09-01 01:56:17,955 - app.main - INFO - Upstream audio: 1600 chunks, 1024000 bytes total
2026-09-01 01:56:18,952 - app.main - INFO - Upstream audio: 1650 chunks, 1056000 bytes total
2026-09-01 01:56:19,946 - app.main - INFO - Upstream audio: 1700 chunks, 1088000 bytes total
2026-09-01 01:56:20,957 - app.main - INFO - Upstream audio: 1750 chunks, 1120000 bytes total
2026-09-01 01:56:21,950 - app.main - INFO - Upstream audio: 1800 chunks, 1152000 bytes total
2026-09-01 01:56:22,941 - app.main - INFO - Upstream audio: 1850 chunks, 1184000 bytes total
2026-09-01 01:56:23,957 - app.main - INFO - Upstream audio: 1900 chunks, 1216000 bytes total
C:\Users\5000240\sellNtell_dev\sell-n-tell\.venv\Lib\site-packages\google\adk\tools\function_tool.py:95: UserWarning: [EXPERIMENTAL] feature FeatureName.JSON_SCHEMA_FOR_FUNC_DECL is enabled.
  build_function_declaration(
2026-09-01 01:56:24,134 - google_adk.google.adk.flows.llm_flows.base_llm_flow - INFO - Establishing live connection for agent: voice_notes_logger
2026-09-01 01:56:24,134 - google_genai._api_client - INFO - The project/location from the environment variables will take precedence over the API key from the environment variables.
2026-09-01 01:56:25,358 - google_adk.google.adk.models.google_llm - INFO - Trying to connect to live model: gemini-live-2.5-flash-native-audio with api backend: GoogleLLMVariant.VERTEX_AI
2026-09-01 01:56:25,358 - google_genai._api_client - INFO - The project/location from the environment variables will take precedence over the API key from the environment variables.
2026-09-01 01:56:30,940 - app.main - INFO - Upstream audio: 1950 chunks, 1248000 bytes total
2026-09-01 01:56:30,942 - app.main - INFO - Upstream audio: 2000 chunks, 1280000 bytes total
2026-09-01 01:56:30,945 - app.main - INFO - Upstream audio: 2050 chunks, 1312000 bytes total
2026-09-01 01:56:30,948 - app.main - INFO - Upstream audio: 2100 chunks, 1344000 bytes total
2026-09-01 01:56:30,950 - app.main - INFO - Upstream audio: 2150 chunks, 1376000 bytes total
2026-09-01 01:56:30,952 - app.main - INFO - Upstream audio: 2200 chunks, 1408000 bytes total
2026-09-01 01:56:30,956 - app.main - INFO - Upstream audio: 2250 chunks, 1440000 bytes total
2026-09-01 01:56:31,946 - app.main - INFO - Upstream audio: 2300 chunks, 1472000 bytes total
2026-09-01 01:56:32,954 - app.main - INFO - Upstream audio: 2350 chunks, 1504000 bytes total
2026-09-01 01:56:33,950 - app.main - INFO - Upstream audio: 2400 chunks, 1536000 bytes total
2026-09-01 01:56:34,947 - app.main - INFO - Upstream audio: 2450 chunks, 1568000 bytes total
2026-09-01 01:56:35,955 - app.main - INFO - Upstream audio: 2500 chunks, 1600000 bytes total
2026-09-01 01:56:36,952 - app.main - INFO - Upstream audio: 2550 chunks, 1632000 bytes total
2026-09-01 01:56:37,946 - app.main - INFO - Upstream audio: 2600 chunks, 1664000 bytes total
2026-09-01 01:56:38,957 - app.main - INFO - Upstream audio: 2650 chunks, 1696000 bytes total
2026-09-01 01:56:39,952 - app.main - INFO - Upstream audio: 2700 chunks, 1728000 bytes total
2026-09-01 01:56:40,947 - app.main - INFO - Upstream audio: 2750 chunks, 1760000 bytes total
2026-09-01 01:56:41,956 - app.main - INFO - Upstream audio: 2800 chunks, 1792000 bytes total
2026-09-01 01:56:42,950 - app.main - INFO - Upstream audio: 2850 chunks, 1824000 bytes total
2026-09-01 01:56:43,946 - app.main - INFO - Upstream audio: 2900 chunks, 1856000 bytes total
2026-09-01 01:56:44,954 - app.main - INFO - Upstream audio: 2950 chunks, 1888000 bytes total
2026-09-01 01:56:45,821 - app.main - INFO - DOWNSTREAM EVENT | author=user | INPUT_TX text='I had an onsite visit with the customer today. We discussed about the hardware requirements for their upcoming project. They have requested for a pricing quotes and sample products. That concludes my notes.' finished=False
2026-09-01 01:56:45,824 - app.main - INFO - DOWNSTREAM EVENT | author=user | INPUT_TX text='I had an onsite visit with the customer today. We discussed about the hardware requirements for their upcoming project. They have requested for a pricing quotes and sample products. That concludes my notes.' finished=True
2026-09-01 01:56:45,950 - app.main - INFO - Upstream audio: 3000 chunks, 1920000 bytes total
2026-09-01 01:56:46,937 - app.main - INFO - Upstream audio: 3050 chunks, 1952000 bytes total
2026-09-01 01:56:47,017 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text="I've staged" finished=False
2026-09-01 01:56:47,182 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11114b)
2026-09-01 01:56:47,475 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:47,488 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' an' finished=False
2026-09-01 01:56:47,827 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(15360b)
2026-09-01 01:56:47,842 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' on-site' finished=False
2026-09-01 01:56:47,846 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:47,851 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' visit' finished=False
2026-09-01 01:56:48,069 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(15360b)
2026-09-01 01:56:48,122 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' where you' finished=False
2026-09-01 01:56:48,133 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,156 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,165 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' discussed' finished=False
2026-09-01 01:56:48,212 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,295 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,306 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' hardware,' finished=False
2026-09-01 01:56:48,340 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,402 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:48,406 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' creating' finished=False
2026-09-01 01:56:48,437 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,451 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,455 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' a new' finished=False
2026-09-01 01:56:48,478 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,482 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' opportunity.' finished=False
2026-09-01 01:56:48,514 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,521 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,546 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:48,550 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' Does that' finished=False
2026-09-01 01:56:48,565 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,585 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:48,590 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' sound' finished=False
2026-09-01 01:56:48,604 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,607 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' correct?' finished=False
2026-09-01 01:56:48,623 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,638 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,657 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:48,664 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text="I've staged an on-site visit where you discussed hardware, creating a new opportunity. Does that sound correct?" finished=True
2026-09-01 01:56:48,666 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger
2026-09-01 01:56:48,668 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | TOOL_CALL=stage_visit_notes
2026-09-01 01:56:48,704 - voice_notes_agent.tools - INFO - stage_visit_notes tool invoked: {'event_type': 'On-site visit', 'executive_summary': 'The customer requested pricing and samples for an upcoming hardware project. I will create an opportunity to track this request.', 'raw_transcript_backup': 'I had an on-site visit with the customer today. We discussed about their hardware requirements for their upcoming project. They have requested for pricing quotes and sample products. That concludes my notes.', 'topics': [{'topic': 'Hardware', 'disposition_code': 1, 'executive_summary': 'The customer expressed interest in hardware for a new project and requested pricing and samples.', 'discussed': True, 'needs_manual_review': False}]}
2026-09-01 01:56:48,704 - voice_notes_agent.notes_workflow - INFO - Staged notes session_id=sess-8049e227-1443-4905-8554-1ce8432a7ed8 event_type=On-site visit topics=1 missing=0 (correction=False, correction_count=0)
2026-09-01 01:56:48,727 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | TOOL_RESP=stage_visit_notes
2026-09-01 01:56:48,733 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | TURN_COMPLETE
2026-09-01 01:56:48,737 - google_adk.google.adk.flows.llm_flows.base_llm_flow - INFO - Update session resumption handle: new_handle='a856c8c5-34ef-432c-bfba-655c4f3fe4be' resumable=True last_consumed_client_message_index=None.
2026-09-01 01:56:48,739 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger
2026-09-01 01:56:49,185 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text='' finished=True
2026-09-01 01:56:49,187 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger
2026-09-01 01:56:49,187 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | TURN_COMPLETE
2026-09-01 01:56:49,192 - google_adk.google.adk.flows.llm_flows.base_llm_flow - INFO - Update session resumption handle: new_handle='5ebd4e4c-7733-4e5c-a1c9-97173a12b5e5' resumable=True last_consumed_client_message_index=None.
2026-09-01 01:56:49,194 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger
2026-09-01 01:56:49,646 - app.main - INFO - Upstream audio: 3100 chunks, 1983870 bytes total
2026-09-01 01:56:49,958 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text='Got it.' finished=False
2026-09-01 01:56:49,995 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11114b)
2026-09-01 01:56:50,055 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:50,114 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=" Here's" finished=False
2026-09-01 01:56:50,126 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(13440b)
2026-09-01 01:56:50,154 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' my summary:' finished=False
2026-09-01 01:56:50,224 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(15360b)
2026-09-01 01:56:50,294 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(13440b)
2026-09-01 01:56:50,307 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' The customer' finished=False
2026-09-01 01:56:50,307 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
INFO:     127.0.0.1:59286 - "GET /favicon.ico HTTP/1.1" 404 Not Found
2026-09-01 01:56:50,363 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:50,450 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:50,454 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' requested' finished=False
2026-09-01 01:56:50,474 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:50,524 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:50,554 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' pricing' finished=False
2026-09-01 01:56:50,595 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:50,621 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:50,635 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' and samples' finished=False
2026-09-01 01:56:50,699 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:50,726 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:50,770 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' for an' finished=False
2026-09-01 01:56:50,774 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:50,832 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' upcoming' finished=False
2026-09-01 01:56:50,840 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:50,894 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:50,934 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' hardware' finished=False
2026-09-01 01:56:50,942 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,026 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,026 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' project.' finished=False
2026-09-01 01:56:51,074 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:51,158 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:51,158 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' I will' finished=False
2026-09-01 01:56:51,172 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,262 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,266 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' create' finished=False
2026-09-01 01:56:51,294 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,326 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' an opportunity' finished=False
2026-09-01 01:56:51,345 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,446 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,458 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,483 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' to track' finished=False
2026-09-01 01:56:51,500 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,582 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,588 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' this request.' finished=False
2026-09-01 01:56:51,618 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:51,674 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:51,722 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,746 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=" I've staged" finished=False
2026-09-01 01:56:51,774 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:51,839 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:51,890 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' an On-site' finished=False
2026-09-01 01:56:51,902 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:51,968 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:52,018 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' visit' finished=False
2026-09-01 01:56:52,025 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,106 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,114 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' covering' finished=False
2026-09-01 01:56:52,150 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:52,168 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' Hardware' finished=False
2026-09-01 01:56:52,198 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,243 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,268 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' marked' finished=False
2026-09-01 01:56:52,310 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:52,326 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' as create' finished=False
2026-09-01 01:56:52,371 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(13440b)
2026-09-01 01:56:52,422 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' opportunity.' finished=False
2026-09-01 01:56:52,430 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,516 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,568 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,596 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' Should' finished=False
2026-09-01 01:56:52,659 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:52,731 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:52,738 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' I save' finished=False
2026-09-01 01:56:52,778 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,804 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' this,' finished=False
2026-09-01 01:56:52,826 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,868 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' or do' finished=False
2026-09-01 01:56:52,876 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,924 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:52,927 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' you want' finished=False
2026-09-01 01:56:52,966 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' to change' finished=False
2026-09-01 01:56:52,971 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:53,023 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:53,026 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text=' something?' finished=False
2026-09-01 01:56:53,071 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(9600b)
2026-09-01 01:56:53,130 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(11520b)
2026-09-01 01:56:53,188 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | OUTPUT_TX text="Got it. Here's my summary: The customer requested pricing and samples for an upcoming hardware project. I will create an opportunity to track this request. I've staged an On-site visit covering Hardware marked as create opportunity. Should I save this, or do you want to change something?" finished=True
2026-09-01 01:56:53,200 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | AUDIO(7680b)
2026-09-01 01:56:53,210 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger
2026-09-01 01:56:53,212 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger | TURN_COMPLETE
2026-09-01 01:56:53,216 - google_adk.google.adk.flows.llm_flows.base_llm_flow - INFO - Update session resumption handle: new_handle='3803eb34-684f-4b3b-b2e8-6e36ea28c5fe' resumable=True last_consumed_client_message_index=None.
2026-09-01 01:56:53,216 - app.main - INFO - DOWNSTREAM EVENT | author=voice_notes_logger
2026-09-01 01:56:53,883 - app.main - INFO - Upstream audio: 3150 chunks, 2015742 bytes total
2026-09-01 01:56:54,878 - app.main - INFO - Upstream audio: 3200 chunks, 2047742 bytes total
2026-09-01 01:56:55,877 - app.main - INFO - Upstream audio: 3250 chunks, 2079742 bytes total
2026-09-01 01:56:56,883 - app.main - INFO - Upstream audio: 3300 chunks, 2111742 bytes total
2026-09-01 01:56:57,879 - app.main - INFO - Upstream audio: 3350 chunks, 2143742 bytes total
2026-09-01 01:56:58,874 - app.main - INFO - Upstream audio: 3400 chunks, 2175742 bytes total
2026-09-01 01:56:59,883 - app.main - INFO - Upstream audio: 3450 chunks, 2207742 bytes total
2026-09-01 01:57:00,879 - app.main - INFO - Upstream audio: 3500 chunks, 2239742 bytes total
2026-09-01 01:57:01,875 - app.main - INFO - Upstream audio: 3550 chunks, 2271742 bytes total
2026-09-01 01:57:02,880 - app.main - INFO - Upstream audio: 3600 chunks, 2303742 bytes total
2026-09-01 01:57:03,878 - app.main - INFO - Upstream audio: 3650 chunks, 2335742 bytes total
2026-09-01 01:57:04,875 - app.main - INFO - Upstream audio: 3700 chunks, 2367742 bytes total
2026-09-01 01:57:05,884 - app.main - INFO - Upstream audio: 3750 chunks, 2399742 bytes total
2026-09-01 01:57:06,879 - app.main - INFO - Upstream audio: 3800 chunks, 2431742 bytes total
2026-09-01 01:57:07,875 - app.main - INFO - Upstream audio: 3850 chunks, 2463742 bytes total
2026-09-01 01:57:08,883 - app.main - INFO - Upstream audio: 3900 chunks, 2495742 bytes total
2026-09-01 01:57:09,878 - app.main - INFO - Upstream audio: 3950 chunks, 2527742 bytes total
2026-09-01 01:57:10,875 - app.main - INFO - Upstream audio: 4000 chunks, 2559742 bytes total
2026-09-01 01:57:11,882 - app.main - INFO - Upstream audio: 4050 chunks, 2591742 bytes total
2026-09-01 01:57:12,878 - app.main - INFO - Upstream audio: 4100 chunks, 2623742 bytes total
2026-09-01 01:57:13,875 - app.main - INFO - Upstream audio: 4150 chunks, 2655742 bytes total
2026-09-01 01:57:14,883 - app.main - INFO - Upstream audio: 4200 chunks, 2687742 bytes total
2026-09-01 01:57:15,879 - app.main - INFO - Upstream audio: 4250 chunks, 2719742 bytes total
2026-09-01 01:57:16,877 - app.main - INFO - Upstream audio: 4300 chunks, 2751742 bytes total
2026-09-01 01:57:17,883 - app.main - INFO - Upstream audio: 4350 chunks, 2783742 bytes total
2026-09-01 01:57:18,879 - app.main - INFO - Upstream audio: 4400 chunks, 2815742 bytes total
2026-09-01 01:57:19,876 - app.main - INFO - Upstream audio: 4450 chunks, 2847742 bytes total
2026-09-01 01:57:20,883 - app.main - INFO - Upstream audio: 4500 chunks, 2879742 bytes total
2026-09-01 01:57:21,880 - app.main - INFO - Upstream audio: 4550 chunks, 2911742 bytes total
2026-09-01 01:57:22,875 - app.main - INFO - Upstream audio: 4600 chunks, 2943742 bytes total
2026-09-01 01:57:23,884 - app.main - INFO - Upstream audio: 4650 chunks, 2975742 bytes total
2026-09-01 01:57:24,879 - app.main - INFO - Upstream audio: 4700 chunks, 3007742 bytes total
2026-09-01 01:57:25,875 - app.main - INFO - Upstream audio: 4750 chunks, 3039742 bytes total
2026-09-01 01:57:26,882 - app.main - INFO - Upstream audio: 4800 chunks, 3071742 bytes total
2026-09-01 01:57:27,875 - app.main - INFO - Upstream audio: 4850 chunks, 3103742 bytes total
2026-09-01 01:57:28,874 - app.main - INFO - Upstream audio: 4900 chunks, 3135742 bytes total
2026-09-01 01:57:29,883 - app.main - INFO - Upstream audio: 4950 chunks, 3167742 bytes total
2026-09-01 01:57:30,879 - app.main - INFO - Upstream audio: 5000 chunks, 3199742 bytes total
2026-09-01 01:57:31,875 - app.main - INFO - Upstream audio: 5050 chunks, 3231742 bytes total
2026-09-01 01:57:32,883 - app.main - INFO - Upstream audio: 5100 chunks, 3263742 bytes total
2026-09-01 01:57:33,879 - app.main - INFO - Upstream audio: 5150 chunks, 3295742 bytes total
2026-09-01 01:57:34,875 - app.main - INFO - Upstream audio: 5200 chunks, 3327742 bytes total
2026-09-01 01:57:35,883 - app.main - INFO - Upstream audio: 5250 chunks, 3359742 bytes total
2026-09-01 01:57:36,875 - app.main - INFO - Upstream audio: 5300 chunks, 3391742 bytes total
2026-09-01 01:57:37,876 - app.main - INFO - Upstream audio: 5350 chunks, 3423742 bytes total
2026-09-01 01:57:38,884 - app.main - INFO - Upstream audio: 5400 chunks, 3455742 bytes total
2026-09-01 01:57:39,878 - app.main - INFO - Upstream audio: 5450 chunks, 3487742 bytes total
2026-09-01 01:57:40,875 - app.main - INFO - Upstream audio: 5500 chunks, 3519742 bytes total
2026-09-01 01:57:41,882 - app.main - INFO - Upstream audio: 5550 chunks, 3551742 bytes total
2026-09-01 01:57:42,879 - app.main - INFO - Upstream audio: 5600 chunks, 3583742 bytes total
2026-09-01 01:57:43,875 - app.main - INFO - Upstream audio: 5650 chunks, 3615742 bytes total
2026-09-01 01:57:44,883 - app.main - INFO - Upstream audio: 5700 chunks, 3647742 bytes total
2026-09-01 01:57:45,879 - app.main - INFO - Upstream audio: 5750 chunks, 3679742 bytes total
2026-09-01 01:57:46,874 - app.main - INFO - Upstream audio: 5800 chunks, 3711742 bytes total
2026-09-01 01:57:47,883 - app.main - INFO - Upstream audio: 5850 chunks, 3743742 bytes total
2026-09-01 01:57:48,879 - app.main - INFO - Upstream audio: 5900 chunks, 3775742 bytes total
2026-09-01 01:57:49,874 - app.main - INFO - Upstream audio: 5950 chunks, 3807742 bytes total
2026-09-01 01:57:50,887 - app.main - INFO - Upstream audio: 6000 chunks, 3839742 bytes total
2026-09-01 01:57:51,879 - app.main - INFO - Upstream audio: 6050 chunks, 3871742 bytes total
2026-09-01 01:57:52,877 - app.main - INFO - Upstream audio: 6100 chunks, 3903742 bytes total
2026-09-01 01:57:53,883 - app.main - INFO - Upstream audio: 6150 chunks, 3935742 bytes total
2026-09-01 01:57:54,879 - app.main - INFO - Upstream audio: 6200 chunks, 3967742 bytes total
2026-09-01 01:57:55,875 - app.main - INFO - Upstream audio: 6250 chunks, 3999742 bytes total
2026-09-01 01:57:56,883 - app.main - INFO - Upstream audio: 6300 chunks, 4031742 bytes total
2026-09-01 01:57:57,879 - app.main - INFO - Upstream audio: 6350 chunks, 4063742 bytes total
2026-09-01 01:57:58,875 - app.main - INFO - Upstream audio: 6400 chunks, 4095742 bytes total
2026-09-01 01:57:59,883 - app.main - INFO - Upstream audio: 6450 chunks, 4127742 bytes total
2026-09-01 01:58:00,878 - app.main - INFO - Upstream audio: 6500 chunks, 4159742 bytes total
2026-09-01 01:58:01,875 - app.main - INFO - Upstream audio: 6550 chunks, 4191742 bytes total
2026-09-01 01:58:02,047 - google_adk.google.adk.flows.llm_flows.base_llm_flow - ERROR - APIError in live flow: 1011 None. Input data processing failed. This is likely due to the client sending data too fast. Please review your flow control mecha
2026-09-01 01:58:02,047 - app.main - ERROR - Streaming error: 1011 None. Input data processing failed. This is likely due to the client sending data too fast. Please review your flow control mecha
````
<!-- END: scripts/smoke_test_output.txt -->

<!-- FILE: scripts/ws_smoke_test.py -->
````python
"""Manual dev smoke-test client for the voice-notes WebSocket, text-mode.

Drives a scripted conversation through /ws/{user}/{session} using TEXT turns
(bypassing the mic/audio pipeline entirely). The native-audio model still
replies with audio, but `output_audio_transcription` is enabled server side,
so we can read back what it *said* as text.

Per the contract-simplification pass: the guided flow is retired (no more
`agent_mode` argument -- there is only one flow now).

`campaign_type` IS sent on the connection query string (business decision:
keep it flowing end-to-end for forward-compatibility) but is NOT processed
by the backend -- see main.py's websocket_endpoint docstring. It has no
effect on this test's scenarios or assertions; it's included only so the
smoke test continues to exercise the full, real connection contract the
frontend uses.

Usage:
    uv run python scripts/ws_smoke_test.py
    uv run python scripts/ws_smoke_test.py --scenario missing_topic

Requires the app to already be running locally (uvicorn app.main:app).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.parse
import uuid

import websockets

BASE_WS_URL = "ws://localhost:8000/ws"
RAW_MODE = False

# campaign_type is sent but inert on the backend (see module docstring).
# Kept as a plain constant, not a CLI flag, since there is currently nothing
# server-side to vary it against -- add a --campaign-type flag if/when
# notes_workflow.validate_payload() starts reading it.
DEFAULT_CAMPAIGN_TYPE = "standard_sales"

# ---------------------------------------------------------------------------
# Scripted turns per scenario. Each turn is one simulated "rep speaks" event.
# (Guided-flow scenarios removed -- that flow is retired.)
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, list[str]] = {
    "clean_save": [
        "I met with the customer on site today. We discussed pricing and "
        "they said it was too expensive for their budget right now. End of "
        "notes.",
        "Save it.",
    ],
    "correction": [
        "Had a phone call about pricing concerns, budget is tight. Done.",
        "Actually change that to a meeting.",
        "Save.",
    ],
    # AIML-2703 AC#3. The correction shapes the ticket names, one per scenario,
    # because they exercise different paths through stage_notes: `correction`
    # above changes a top-level field (event_type), and the three below change a
    # topic's disposition, restate the summary, and add a topic that was never
    # staged.
    #
    # None of these can exercise the supersede gate -- the model always commits
    # the record it just staged, never the one it replaced. That gate is covered
    # by scripts/test_correction_reliability.py.
    "correction_summary": [
        "Met on site to talk about pricing. They said it was too expensive. "
        "End of notes.",
        "That summary isn't right -- say they're reviewing it with their "
        "finance team before deciding.",
        "Save it.",
    ],
    "correction_disposition": [
        "Met on site and went through pricing. They placed an order for it. "
        "End of notes.",
        "That's wrong -- they didn't order anything, the price was too high "
        "for their budget.",
        "Save it.",
    ],
    "correction_add_topic": [
        "Met on site, we went through pricing and they said it was too "
        "expensive. End of notes.",
        "I also covered the contract renewal and they placed an order for it.",
        "Save it.",
    ],
    "missing_topic": [
        "Talked about pricing, they said it's too expensive.",
        "We didn't get to the contract renewal, ran out of time.",
        "Save it.",
    ],
    "multi_topic": [
        "Met on site. Discussed pricing -- too expensive for them right "
        "now. Also talked about a contract renewal, they already placed an "
        "order for it.",
        "Save.",
    ],
}

PLANNED_TOPICS: dict[str, str] = {
    "clean_save": "Pricing discussion",
    "correction": "Pricing discussion",
    "correction_summary": "Pricing discussion",
    "correction_disposition": "Pricing discussion",
    # Contract renewal is planned but deliberately not mentioned on the first
    # pass -- the correction turn is what adds it, so this also proves the
    # coverage gate releases once a re-stage supplies the missing topic.
    "correction_add_topic": "Pricing discussion,Contract renewal",
    "missing_topic": "Pricing discussion,Contract renewal",
    "multi_topic": "Pricing discussion,Contract renewal",
}


def _summarize_event(evt: dict) -> str | None:
    bits = []
    author = evt.get("author", "?")
    if evt.get("inputTranscription", {}).get("text"):
        bits.append(f"IN_TX={evt['inputTranscription']['text']!r}")
    if evt.get("outputTranscription", {}).get("text"):
        bits.append(f"OUT_TX={evt['outputTranscription']['text']!r}")
    content = evt.get("content") or {}
    for part in content.get("parts", []) or []:
        if part.get("functionCall"):
            fc = part["functionCall"]
            bits.append(f"TOOL_CALL={fc.get('name')}({fc.get('args')})")
        elif part.get("functionResponse"):
            fr = part["functionResponse"]
            bits.append(f"TOOL_RESP={fr.get('name')} -> {fr.get('response')}")
        elif part.get("text"):
            bits.append(f"TEXT={part['text'][:200]!r}")
    if evt.get("interrupted"):
        bits.append("INTERRUPTED")
    if evt.get("turnComplete"):
        bits.append("TURN_COMPLETE")
    if not bits:
        return None
    return f"[{author}] " + " | ".join(bits)


# How long the agent must stay silent AFTER a turn_complete before we accept
# that it has finished and send the next scripted turn.
QUIET_PERIOD_S = 3.0
# After the LAST scripted turn the agent often still owes trailing work --
# e.g. speaking the closing_statement after commit_visit_notes returns, which
# needs another beat (and may need main.py's auto-continue nudge to land).
# Closing the socket at the normal quiet period cuts that off and the
# scenario ends with no commit for reasons that have nothing to do with the
# code under test.
FINAL_QUIET_PERIOD_S = 15.0
# Absolute cap on how long one scripted turn may take.
TURN_TIMEOUT_S = 60.0


async def _drain_until_agent_settles(
    ws, quiet_period: float = QUIET_PERIOD_S
) -> None:
    """Read events until the agent has genuinely finished its response.

    A single agent response emits MULTIPLE ``turnComplete`` events -- one after
    a tool call returns, another after it finishes speaking, and so on. Breaking
    on the first one sends the next scripted turn while the agent is still
    working, so the "rep" ends up answering a question that has not been asked
    yet. That desynchronisation is not cosmetic: it makes the model answer its
    own questions, which turn_guard then (correctly) blocks, which leaves
    required state unset, which makes the final commit fail. One race,
    four layers of fallout, and none of it reproducible against a real rep.

    So instead of stopping at the first turn_complete, we keep reading until
    the agent has been silent for QUIET_PERIOD_S after at least one
    turn_complete.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + TURN_TIMEOUT_S
    saw_turn_complete = False

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            print("(turn timeout -- moving on)")
            return
        # Before the first turn_complete, wait as long as the overall cap
        # allows. After it, a short silence means the agent is done.
        wait_for = min(quiet_period, remaining) if saw_turn_complete else remaining
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=wait_for)
        except asyncio.TimeoutError:
            if saw_turn_complete:
                return  # agent has gone quiet -- safe to send the next turn
            print("(no response from agent -- moving on)")
            return

        evt = json.loads(raw)
        if RAW_MODE:
            print("RAW:", json.dumps(evt))
        summary = _summarize_event(evt)
        if summary:
            print(summary)
        if evt.get("turnComplete"):
            saw_turn_complete = True


async def run_scenario(scenario: str, turns: list[str], planned_topics: str) -> None:
    user_id = "smoke_tester"
    session_id = f"smoke-{scenario}-{uuid.uuid4().hex[:6]}"
    # campaign_type is sent per the business decision to keep it flowing
    # end-to-end, but the backend stores it as inert session-state metadata
    # only -- see main.py's websocket_endpoint docstring. It does not affect
    # any scenario's assertions here. agent_mode is not sent: guided flow is
    # retired and there is only one flow now.
    query = urllib.parse.urlencode(
        {
            "planned_topics": planned_topics,
            "campaign_type": DEFAULT_CAMPAIGN_TYPE,
        }
    )
    url = f"{BASE_WS_URL}/{user_id}/{session_id}?{query}"
    print(f"\n=== {scenario} ===")
    print(f"connecting: {url}")

    async with websockets.connect(url, max_size=None) as ws:
        for i, turn in enumerate(turns, start=1):
            if i > 1:
                # Small courtesy pause only; the real synchronisation is the
                # quiet-period wait below.
                await asyncio.sleep(0.5)
            print(f"\n--- turn {i}: REP SAYS: {turn!r} ---")
            await ws.send(json.dumps({"type": "text", "text": turn}))
            is_last = i == len(turns)
            await _drain_until_agent_settles(
                ws, FINAL_QUIET_PERIOD_S if is_last else QUIET_PERIOD_S
            )
        print("\n--- scenario complete ---")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=None, help="run just one scenario")
    parser.add_argument(
        "--raw", action="store_true", help="print full raw event JSON"
    )
    args = parser.parse_args()
    global RAW_MODE
    RAW_MODE = args.raw

    names = [args.scenario] if args.scenario else list(SCENARIOS.keys())

    for name in names:
        turns = SCENARIOS[name]
        planned = PLANNED_TOPICS.get(name, "")
        await run_scenario(name, turns, planned)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
````
<!-- END: scripts/ws_smoke_test.py -->

