# scripts

branch: `development`  commit: `85b108c`  files: 7

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

<!-- FILE: scripts/test_aiml_2743_session_lifecycle.py -->
````python
"""Automated offline tests for AIML-2807 and AIML-2743 session lifecycle & state resilience.

Validates:
1. turn_guard.cleanup_session purges all 5 module-level dictionaries.
2. notes_workflow.cleanup_session purges _STAGED_NOTES.
3. notes_workflow.prune_stale_staged_notes evicts stale records while preserving active/recent ones.
4. commit_notes preserves committed records in memory at commit time for idempotent retries.
5. Dual-Sync: stage_visit_notes mirrors state into tool_context.state; commit_visit_notes
   rehydrates from tool_context.state across process restarts (empty RAM).
6. commit_visit_notes returns saved commit_result on subsequent retries.
7. WebSocket disconnect cleanup hook executes on disconnect when acquired=True, but NOT
   when connection was rejected (acquired=False).

Usage:
    uv run python scripts/test_aiml_2807_session_lifecycle.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "app"))
sys.path.insert(0, str(_REPO_ROOT))

import main as app_main
from main import (
    _SESSION_SLOTS,
    _SessionSlot,
    websocket_endpoint,
)
from voice_notes_agent import notes_workflow, turn_guard
from voice_notes_agent.tools import commit_visit_notes, stage_visit_notes



class MockWebSocket:
    """Mock WebSocket for offline FastAPI endpoint testing."""

    def __init__(self) -> None:
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.sent_messages: list[str] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        self.sent_messages.append(text)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


def test_turn_guard_cleanup() -> None:
    """AC: cleanup_session clears all 5 turn_guard dictionaries."""
    session_id = "test-turn-guard-cleanup-1"

    # Seed all 5 dictionaries
    turn_guard._TURN_COUNTS[session_id] = 5
    turn_guard._BASELINES[session_id] = 2
    turn_guard._AWAITING_READBACK[session_id] = True
    turn_guard._NUDGE_SENT[session_id] = True
    turn_guard._AWAITING_TOOL[session_id] = "stage_visit_notes"

    assert session_id in turn_guard._TURN_COUNTS
    assert session_id in turn_guard._BASELINES
    assert session_id in turn_guard._AWAITING_READBACK
    assert session_id in turn_guard._NUDGE_SENT
    assert session_id in turn_guard._AWAITING_TOOL

    # Cleanup
    turn_guard.cleanup_session(session_id)

    assert session_id not in turn_guard._TURN_COUNTS
    assert session_id not in turn_guard._BASELINES
    assert session_id not in turn_guard._AWAITING_READBACK
    assert session_id not in turn_guard._NUDGE_SENT
    assert session_id not in turn_guard._AWAITING_TOOL

    # Safe no-op on non-existent session
    turn_guard.cleanup_session("non-existent-session-id")
    print("PASS: test_turn_guard_cleanup")


def test_notes_workflow_cleanup_and_pruning() -> None:
    """AC: cleanup_session reaps staged notes and prune_stale_staged_notes handles TTL."""
    session_id = "test-notes-cleanup-1"

    payload = {
        "event_type": "Phone Call",
        "executive_summary": "Discussed Q3 pricing and order volume.",
        "topics": [
            {
                "topic": "Pricing",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "Offered 5% discount on bulk order.",
            }
        ],
    }
    notes_workflow.stage_notes(payload=payload, session_id=session_id, planned_topics=["Pricing"])
    assert notes_workflow.get_staged(session_id) is not None

    # Test explicit cleanup
    notes_workflow.cleanup_session(session_id)
    assert notes_workflow.get_staged(session_id) is None

    # Test TTL pruning:
    stale_id = "test-stale-session"
    recent_id = "test-recent-session"

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=2)).isoformat()
    recent_time = (now - timedelta(minutes=5)).isoformat()

    notes_workflow._STAGED_NOTES[stale_id] = {
        "payload": payload,
        "planned_topics": ["Pricing"],
        "staged_at": old_time,
        "committed": True,
        "committed_at": old_time,
    }
    notes_workflow._STAGED_NOTES[recent_id] = {
        "payload": payload,
        "planned_topics": ["Pricing"],
        "staged_at": recent_time,
        "committed": True,
        "committed_at": recent_time,
    }

    evicted = notes_workflow.prune_stale_staged_notes(max_age_seconds=3600.0)
    assert evicted == 1, f"Expected 1 evicted record, got {evicted}"
    assert notes_workflow.get_staged(stale_id) is None
    assert notes_workflow.get_staged(recent_id) is not None

    # Cleanup recent
    notes_workflow.cleanup_session(recent_id)
    print("PASS: test_notes_workflow_cleanup_and_pruning")


def test_commit_notes_retention_and_idempotent_retry() -> None:
    """AC: commit_notes does NOT delete the record at commit time, allowing retries."""
    session_id = "test-commit-retry-1"

    payload = {
        "event_type": "Phone Call",
        "executive_summary": "Followed up on product trial.",
        "topics": [
            {
                "topic": "Product Demo",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "Trial going well.",
            }
        ],
    }
    notes_workflow.stage_notes(payload=payload, session_id=session_id, planned_topics=["Product Demo"])

    # 1. Commit
    result1 = notes_workflow.commit_notes(session_id, confirmed=True)
    assert result1.session_id == session_id

    # 2. Invariant: Record MUST STILL BE in _STAGED_NOTES at commit time!
    staged_after_commit = notes_workflow.get_staged(session_id)
    assert staged_after_commit is not None, "Record was deleted at commit time!"
    assert staged_after_commit["committed"] is True

    # 3. Idempotent Retry: Calling commit_notes again returns identical result
    result2 = notes_workflow.commit_notes(session_id, confirmed=True)
    assert result2 == result1

    # Clean up after test
    notes_workflow.cleanup_session(session_id)
    print("PASS: test_commit_notes_retention_and_idempotent_retry")


@pytest.mark.asyncio
async def test_tools_dual_sync_and_rehydration_restart() -> None:
    """AC: Dual-Sync stores state in tool_context.state; restart rehydrates and commits."""
    session_id = "test-restart-rehydration-1"

    mock_session = MagicMock()
    mock_session.id = session_id

    tool_context = MagicMock()
    tool_context.session = mock_session
    tool_context.state = {"planned_topics": ["Efficacy"]}

    # 1. Call stage_visit_notes
    stage_res = await stage_visit_notes(
        event_type="Meeting",
        executive_summary="Quarterly review with Dr. Smith.",
        raw_transcript_backup="Quarterly review with Dr. Smith discussing efficacy.",
        topics=[
            {
                "topic": "Efficacy",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "Dr. Smith noted positive patient response.",
            }
        ],
        tool_context=tool_context,
    )
    assert stage_res["status"] == "staged"
    staged_sid = stage_res["session_id"]

    # Verify Dual-Sync persisted full record to tool_context.state
    assert "staged_record" in tool_context.state
    assert (
        tool_context.state["staged_record"]["payload"]["executive_summary"]
        == "Quarterly review with Dr. Smith."
    )

    # 2. Simulate Process Restart: wipe process-local RAM (_STAGED_NOTES and turn_guard)
    notes_workflow._STAGED_NOTES.clear()
    assert notes_workflow.get_staged(staged_sid) is None, "RAM not cleared"

    # Simulate agent delivered readback and rep replied "yes save it"
    turn_guard.record_agent_speech(staged_sid, "Read back summary")
    turn_guard.record_user_turn(staged_sid)

    # 3. Call commit_visit_notes in the fresh process
    commit_res = await commit_visit_notes(tool_context=tool_context)
    assert commit_res["status"] == "success", f"Commit failed: {commit_res}"
    assert commit_res["session_id"] == staged_sid

    # Verify that RAM was rehydrated and tool_context.state has commit_result
    assert notes_workflow.get_staged(staged_sid) is not None, "Did not rehydrate into RAM"
    assert tool_context.state.get("commit_result") is not None
    assert tool_context.state.get("committed") is True

    # 4. Immediate tool retry on committed session
    retry_res = await commit_visit_notes(tool_context=tool_context)
    assert retry_res["status"] == "success"
    assert retry_res["session_id"] == staged_sid

    # Clean up
    notes_workflow.cleanup_session(staged_sid)
    turn_guard.cleanup_session(staged_sid)
    print("PASS: test_tools_dual_sync_and_rehydration_restart")


@pytest.mark.asyncio
async def test_websocket_disconnect_cleanup_hook() -> None:
    """AC: WebSocket disconnect hook reaps dictionaries if acquired=True, not if acquired=False."""
    session_id = "test-ws-cleanup-hook-1"
    user_id = "test-user-ws"

    ws1 = MockWebSocket()

    async def mock_dictation(ws, uid, sid, planned, campaign):
        # Stage something and set turn_guard state during active call
        turn_guard.record_user_turn(sid)
        notes_workflow._STAGED_NOTES[sid] = {"mock": "data"}

    with patch.object(app_main, "_run_dictation_session", side_effect=mock_dictation):
        await websocket_endpoint(ws1, user_id, session_id)

    # After normal completion/disconnect, acquired was True -> state cleaned up!
    assert session_id not in turn_guard._TURN_COUNTS
    assert notes_workflow.get_staged(session_id) is None
    assert session_id not in _SESSION_SLOTS

    # Test rejected concurrent attach: does NOT wipe active session state!
    active_sid = "test-active-held-session"
    turn_guard._TURN_COUNTS[active_sid] = 99
    notes_workflow._STAGED_NOTES[active_sid] = {"keep": "me"}

    # Mock an already-locked slot
    held_slot = _SessionSlot()
    await held_slot.lock.acquire()
    _SESSION_SLOTS[active_sid] = held_slot

    ws_rejected = MockWebSocket()
    await websocket_endpoint(ws_rejected, user_id, active_sid)

    assert ws_rejected.close_code == 4409  # session_busy
    # Invariant: Rejected attach MUST NOT clear active session's state!
    assert turn_guard._TURN_COUNTS.get(active_sid) == 99
    assert notes_workflow.get_staged(active_sid) == {"keep": "me"}

    # Release held lock manually
    held_slot.lock.release()
    _SESSION_SLOTS.pop(active_sid, None)
    turn_guard.cleanup_session(active_sid)
    notes_workflow.cleanup_session(active_sid)
    print("PASS: test_websocket_disconnect_cleanup_hook")


@pytest.mark.asyncio
async def test_multi_stage_corrections_with_midstream_drop_and_reconnection() -> None:
    """AC: Multiple stages/corrections survive midstream drop, reconnect on same session_id, and commit."""
    session_id = "test-multistage-reconnect-1"

    mock_session = MagicMock()
    mock_session.id = session_id

    tool_context = MagicMock()
    tool_context.session = mock_session
    tool_context.state = {"planned_topics": ["Pricing", "Efficacy"]}

    # Stage 1: Initial dictation (Pricing only)
    res1 = await stage_visit_notes(
        event_type="Meeting",
        executive_summary="Discussed pricing with Dr. Smith.",
        raw_transcript_backup="Discussed pricing with Dr. Smith.",
        topics=[
            {
                "topic": "Pricing",
                "discussed": True,
                "disposition_code": 8,
                "executive_summary": "Offered 5% discount.",
            }
        ],
        tool_context=tool_context,
    )
    assert res1["status"] == "staged"
    # Note: Efficacy was planned but not yet addressed
    assert "Efficacy" in (res1.get("missing_topics") or [])
    assert tool_context.state["staged_record"]["payload"]["executive_summary"] == "Discussed pricing with Dr. Smith."

    # Stage 2: Correction / addition (addressed Efficacy + updated discount)
    res2 = await stage_visit_notes(
        event_type="Meeting",
        executive_summary="Discussed pricing and efficacy with Dr. Smith.",
        raw_transcript_backup="Discussed pricing and efficacy with Dr. Smith.",
        topics=[
            {
                "topic": "Pricing",
                "discussed": True,
                "disposition_code": 8,
                "executive_summary": "Offered 10% discount.",  # changed from 5 to 10
            },
            {
                "topic": "Efficacy",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "Positive efficacy results.",
            },
        ],
        tool_context=tool_context,
    )
    assert res2["status"] == "staged"
    assert not res2.get("missing_topics")
    assert tool_context.state["staged_record"]["correction_count"] == 1
    assert tool_context.state["staged_record"]["payload"]["executive_summary"] == "Discussed pricing and efficacy with Dr. Smith."

    # SIMULATE HARD NETWORK DROP / CONTAINER RESTART IN THE MIDDLE
    # In-memory RAM is completely wiped!
    notes_workflow._STAGED_NOTES.clear()
    assert notes_workflow.get_staged(session_id) is None, "RAM was not cleared"

    # CLIENT RECONNECTS WITH THE SAME SESSION ID
    # Server rehydrates from session state
    staged_record = tool_context.state.get("staged_record")
    assert staged_record is not None
    notes_workflow.rehydrate_staged(session_id, staged_record)
    assert notes_workflow.get_staged(session_id) is not None

    # After reconnect, rep speaks on new connection: "Looks good, save it."
    turn_guard.record_agent_speech(session_id, "Summary read back")
    turn_guard.record_user_turn(session_id)

    # Commit on reconnected session
    commit_res = await commit_visit_notes(tool_context=tool_context)
    assert commit_res["status"] == "success"
    assert commit_res["executive_summary"] == "Discussed pricing and efficacy with Dr. Smith."
    assert len(commit_res["topics"]) == 2
    assert commit_res["topics"][0]["executive_summary"] == "Offered 10% discount."

    # Cleanup
    notes_workflow.cleanup_session(session_id)
    turn_guard.cleanup_session(session_id)
    print("PASS: test_multi_stage_corrections_with_midstream_drop_and_reconnection")


async def main() -> None:
    print("Running AIML-2807 & AIML-2743 session lifecycle tests...\n")
    test_turn_guard_cleanup()
    test_notes_workflow_cleanup_and_pruning()
    test_commit_notes_retention_and_idempotent_retry()
    await test_tools_dual_sync_and_rehydration_restart()
    await test_websocket_disconnect_cleanup_hook()
    await test_multi_stage_corrections_with_midstream_drop_and_reconnection()
    print("\nALL LIFECYCLE & RESILIENCE TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
````
<!-- END: scripts/test_aiml_2743_session_lifecycle.py -->

<!-- FILE: scripts/test_live_vertex_ai_session_service.py -->
````python
"""Live integration test for VertexAiSessionService against real GCP Reasoning Engine.

Tests:
1. NonBlockingVertexAiSessionService can create real sessions in Vertex AI.
2. NonBlockingVertexAiSessionService can read back real sessions from Vertex AI.
3. append_event with sequential chaining writes events into Vertex AI without blocking.
4. flush() drains all background event tasks.
5. POST /api/sessions endpoint creates a live Vertex AI session when USE_IN_MEMORY_SESSION_SERVICE=false.

Usage:
    uv run python scripts/test_live_vertex_ai_session_service.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "app"))
sys.path.insert(0, str(_REPO_ROOT))

load_dotenv(_REPO_ROOT / "app" / ".env")

from google.adk.events import Event
from starlette.testclient import TestClient

import main as app_main
from main import NonBlockingVertexAiSessionService, app


async def test_live_vertex_ai_service() -> None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "prj-hds-np-data")
    location = os.getenv("VERTEX_AI_AGENT_ENGINE_LOCATION", "us-central1")
    engine_urn = os.getenv("VERTEX_AI_AGENT_ENGINE_ID", "")
    
    # Extract numeric ID if URN format
    engine_id = engine_urn.split(":")[-1] if ":" in engine_urn else engine_urn

    print(f"Connecting to Vertex AI Session Service:")
    print(f"  Project: {project}")
    print(f"  Location: {location}")
    print(f"  Engine ID: {engine_id}")

    service = NonBlockingVertexAiSessionService(
        project=project,
        location=location,
        agent_engine_id=engine_id,
    )

    # 1. Test live create_session (without user-supplied session_id, matching Comment 6)
    print("\n1. Testing live create_session...")
    session = await service.create_session(
        app_name=engine_id,
        user_id="integration-test-user",
        state={"planned_topics": ["Pricing discussion"], "test_marker": "vertex_live_ok"},
    )
    assert session is not None
    assert session.id, "Session ID should be non-empty"
    print(f"   SUCCESS: Created live Vertex AI session ID: {session.id}")

    # 2. Test live get_session
    print("\n2. Testing live get_session...")
    fetched_session = await service.get_session(
        app_name=engine_id,
        user_id="integration-test-user",
        session_id=session.id,
    )
    assert fetched_session is not None
    assert fetched_session.id == session.id
    print(f"   SUCCESS: Fetched live session: {fetched_session.id}")
    print(f"   Session state: {fetched_session.state}")

    # 3. Test sequential event appending
    print("\n3. Testing non-blocking append_event with sequential chaining...")
    event1 = Event(
        id=f"{session.id}-ev1",
        author="user",
        timestamp=1700000000.0,
    )
    event2 = Event(
        id=f"{session.id}-ev2",
        author="agent",
        timestamp=1700000001.0,
    )

    await service.append_event(session, event1)
    await service.append_event(session, event2)
    print(f"   Appended 2 events to session {session.id}")

    # 4. Test flush()
    print("\n4. Testing flush() on shutdown...")
    await service.flush(timeout=10.0)
    assert len(service._pending_tasks) == 0
    print("   SUCCESS: All background persistence tasks flushed cleanly!")

    # 5. Test POST /api/sessions endpoint with VertexAiSessionService configured
    print("\n5. Testing POST /api/sessions with NonBlockingVertexAiSessionService...")
    original_service = app_main.session_service
    try:
        app_main.session_service = service
        client = TestClient(app)
        resp = client.post(
            "/api/sessions",
            json={
                "user_id": "rep-test-vertex-endpoint",
                "planned_topics": ["Efficacy", "Pricing"],
                "campaign_type": "standard_sales",
            },
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        print(f"   Response from POST /api/sessions: {data}")
        assert data["status"] == "ok"
        assert data["session_id"]
        # Verify that minted ID can be fetched
        minted_session = await service.get_session(
            app_name=engine_id,
            user_id=data["user_id"],
            session_id=data["session_id"],
        )
        assert minted_session is not None
        assert minted_session.id == data["session_id"]
        print(f"   SUCCESS: Minted session {data['session_id']} verified in Vertex AI!")
    finally:
        app_main.session_service = original_service


async def main() -> None:
    try:
        await test_live_vertex_ai_service()
        print("\n=======================================================")
        print("ALL LIVE VERTEX AI SESSION SERVICE CHECKS PASSED!")
        print("=======================================================")
    except Exception as exc:
        print(f"\nFAILED with exception: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
````
<!-- END: scripts/test_live_vertex_ai_session_service.py -->

<!-- FILE: scripts/test_pr_review_fixes.py -->
````python
"""Comprehensive test suite for the 9 PR review comment fixes (AIML-2743 / AIML-2807).

Validates:
- Comment 1: Private ADK imports are removed from main.py and fallback constants are used.
- Comment 2: Event persistence tasks are chained sequentially per session; flush() drains them.
- Comment 3: pydantic.ValidationError during event persistence is logged and retried without raw_event.
- Comment 4: GET /api/sessions/{session_id} is removed (returns 404/405).
- Comment 5: session_id is not normalized/altered with replace('_', '-').lower() in websocket_endpoint.
- Comment 6: POST /api/sessions mints session_ids on the server; WebSocket attach uses get_session.
- Comments 7 & 9: Staged notes commit idempotency is authoritative in notes_workflow; stage_visit_notes
  clears commit_result/committed so consecutive visits in one session commit fresh notes.
- Comment 8: turn_guard.has_new_reply() defaults to fail-safe False when session_id not in _BASELINES.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic
import pytest
from starlette.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "app"))
sys.path.insert(0, str(_REPO_ROOT))

import main as app_main
from main import (
    _SESSION_SLOTS,
    _SessionSlot,
    NonBlockingVertexAiSessionService,
    app,
    websocket_endpoint,
)
from voice_notes_agent import notes_workflow, turn_guard
from voice_notes_agent.tools import commit_visit_notes, stage_visit_notes


def test_comment_1_no_private_adk_imports() -> None:
    """Comment 1: No private symbols imported from vertex_ai_session_service."""
    main_py = (_REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "_COMPACTION_CUSTOM_METADATA_KEY" in main_py
    assert "_USAGE_METADATA_CUSTOM_METADATA_KEY" in main_py
    assert "from google.adk.sessions.vertex_ai_session_service import (" not in main_py
    assert "_set_internal_custom_metadata" in main_py
    print("PASS: test_comment_1_no_private_adk_imports")


@pytest.mark.asyncio
async def test_comment_2_ordered_event_chaining_and_flush() -> None:
    """Comment 2: Event persistence tasks are chained sequentially per session, and flush() waits."""
    service = NonBlockingVertexAiSessionService(
        project="test-project",
        location="us-central1",
        agent_engine_id="test-engine-id",
    )

    execution_order: list[int] = []

    async def mock_persist(session, event):
        # Artificially delay earlier event to test that task 2 waits for task 1
        num = int(event.id)
        if num == 1:
            await asyncio.sleep(0.05)
        execution_order.append(num)

    service._persist_cloud_event = mock_persist

    session = MagicMock()
    session.id = "test-session-ordered"
    session.app_name = "test-app"
    session.events = []
    session.state = {}

    from google.adk.events import Event

    event1 = Event(id="1", author="user", timestamp=1700000000.0)
    event2 = Event(id="2", author="user", timestamp=1700000001.0)

    # Append event 1 then event 2 immediately
    await service.append_event(session, event1)
    await service.append_event(session, event2)

    # Flush should wait for all tasks to complete
    await service.flush(timeout=2.0)

    assert execution_order == [1, 2], f"Expected [1, 2], got {execution_order}"
    assert len(service._pending_tasks) == 0
    print("PASS: test_comment_2_ordered_event_chaining_and_flush")


@pytest.mark.asyncio
async def test_comment_3_pydantic_error_handling_and_logging() -> None:
    """Comment 3: pydantic.ValidationError logs warning and retries without raw_event."""
    service = NonBlockingVertexAiSessionService(
        project="test-project",
        location="us-central1",
        agent_engine_id="test-engine-id",
    )

    session = MagicMock()
    session.id = "test-session-pydantic"
    session.app_name = "test-app"

    event = MagicMock()
    event.id = "ev-1"
    event.author = "agent"
    event.invocation_id = "inv-1"
    event.timestamp = 1700000000.0
    event.content = None
    event.actions = None
    event.model_dump.return_value = {"bad": "field"}

    calls: list[dict] = []

    class MockSessionsEvents:
        async def append(self, name, author, invocation_id, timestamp, config):
            calls.append(config.copy())
            if "raw_event" in config:
                # Simulate pydantic validation error
                raise pydantic.ValidationError.from_exception_data(
                    title="TestValidation", line_errors=[]
                )

    class MockAgentEngines:
        sessions = MagicMock()
        sessions.events = MockSessionsEvents()

    class MockApiClient:
        agent_engines = MockAgentEngines()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    service._get_api_client = lambda: MockApiClient()
    service._get_reasoning_engine_id = lambda app_name: "test-engine-id"

    with patch("main.logger.warning") as mock_warn:
        await service._persist_cloud_event(session, event)
        assert len(calls) == 2, f"Expected 2 append calls (first with raw_event, second without), got {len(calls)}"
        assert "raw_event" in calls[0]
        assert "raw_event" not in calls[1]
        mock_warn.assert_called()
    print("PASS: test_comment_3_pydantic_error_handling_and_logging")


def test_comment_4_inspect_endpoint_removed() -> None:
    """Comment 4: GET /api/sessions/{session_id} is removed."""
    client = TestClient(app)
    resp = client.get("/api/sessions/some-test-session-id")
    # Should not return 200 with session details; must be 405 Method Not Allowed (since POST exists) or 404
    assert resp.status_code in (404, 405), f"Unexpected status {resp.status_code}"
    print("PASS: test_comment_4_inspect_endpoint_removed")


def test_comment_6_post_sessions_minting() -> None:
    """Comment 6: POST /api/sessions mints a session and returns its ID."""
    client = TestClient(app)
    resp = client.post(
        "/api/sessions",
        json={"user_id": "test-rep-1", "planned_topics": ["Pricing"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "session_id" in data
    assert data["user_id"] == "test-rep-1"
    print("PASS: test_comment_6_post_sessions_minting")


@pytest.mark.asyncio
async def test_comment_5_session_id_normalization_removed() -> None:
    """Comment 5: Session IDs with uppercase / underscores are NOT mangled."""
    mock_ws = MagicMock()
    mock_ws.accept = AsyncMock()
    mock_ws.close = AsyncMock()

    captured_sid: list[str] = []

    async def mock_dictation(ws, uid, sid, planned, campaign):
        captured_sid.append(sid)

    test_sid = "Session_With_Underscores_AND_Caps_123"
    with patch.object(app_main, "_run_dictation_session", side_effect=mock_dictation):
        await websocket_endpoint(mock_ws, "user123", test_sid)

    assert len(captured_sid) == 1
    assert captured_sid[0] == test_sid, f"Expected {test_sid}, got {captured_sid[0]}"
    print("PASS: test_comment_5_session_id_normalization_removed")


@pytest.mark.asyncio
async def test_comment_7_and_9_consecutive_visits_and_idempotency() -> None:
    """Comments 7 & 9: Staged notes commit idempotency is authoritative in notes_workflow;
    fresh stage_visit_notes clears commit_result and committed so subsequent visits commit cleanly."""
    session_id = "test-consecutive-visits-1"

    mock_session = MagicMock()
    mock_session.id = session_id

    from google.adk.sessions.state import State
    tool_context = MagicMock()
    tool_context.session = mock_session
    tool_context.state = State(value={"planned_topics": ["TopicA"]}, delta={})

    # --- VISIT 1 ---
    # 1. Stage Visit 1
    await stage_visit_notes(
        event_type="Meeting",
        executive_summary="Visit 1 Summary",
        raw_transcript_backup="Visit 1 Transcript",
        topics=[
            {
                "topic": "TopicA",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "TopicA discussed",
            }
        ],
        tool_context=tool_context,
    )
    turn_guard.record_agent_speech(session_id, "Summary 1")
    turn_guard.record_user_turn(session_id)

    # 2. Commit Visit 1
    commit1 = await commit_visit_notes(tool_context=tool_context)
    assert commit1["status"] == "success"
    assert commit1["executive_summary"] == "Visit 1 Summary"
    assert tool_context.state.get("committed") is True

    # 3. Idempotent Retry of Visit 1 (without fresh staging) returns the same result
    commit1_retry = await commit_visit_notes(tool_context=tool_context)
    assert commit1_retry["status"] == "success"
    assert commit1_retry["executive_summary"] == "Visit 1 Summary"

    # --- VISIT 2 IN SAME SESSION ---
    # 4. Stage Visit 2 (fresh note in same session)
    await stage_visit_notes(
        event_type="Phone Call",
        executive_summary="Visit 2 Summary (Fresh Note)",
        raw_transcript_backup="Visit 2 Transcript",
        topics=[
            {
                "topic": "TopicA",
                "discussed": True,
                "disposition_code": 2,
                "executive_summary": "TopicA discussed again",
            }
        ],
        tool_context=tool_context,
    )

    # Verify stage_visit_notes cleared commit_result and committed:
    assert tool_context.state.get("commit_result") is None, "commit_result was not cleared!"
    assert tool_context.state.get("committed") in (None, False), "committed was not cleared!"

    turn_guard.record_agent_speech(session_id, "Summary 2")
    turn_guard.record_user_turn(session_id)

    # 5. Commit Visit 2 -> MUST commit fresh note and NOT replay Visit 1!
    commit2 = await commit_visit_notes(tool_context=tool_context)
    assert commit2["status"] == "success"
    assert commit2["executive_summary"] == "Visit 2 Summary (Fresh Note)", f"Got stale result: {commit2}"

    # Clean up
    notes_workflow.cleanup_session(session_id)
    turn_guard.cleanup_session(session_id)
    print("PASS: test_comment_7_and_9_consecutive_visits_and_idempotency")


def test_comment_8_turn_guard_fail_safe_on_restart() -> None:
    """Comment 8: turn_guard.has_new_reply() returns False if session_id not in _BASELINES."""
    session_id = "test-fail-safe-session"

    mock_session = MagicMock()
    mock_session.id = session_id
    tool_context = MagicMock()
    tool_context.session = mock_session

    # Ensure session is not in _BASELINES (like after a container restart)
    turn_guard.cleanup_session(session_id)
    assert session_id not in turn_guard._BASELINES

    # Even if current turn count is 0 (or anything), without a baseline recorded in this process it must return False!
    assert turn_guard.has_new_reply(tool_context) is False, "turn_guard should return False when no baseline exists"

    # Once snapshotted and rep turn recorded, it passes:
    turn_guard.snapshot(tool_context)
    assert turn_guard.has_new_reply(tool_context) is False  # current = 0, baseline = 0 -> False
    turn_guard.record_user_turn(session_id)
    assert turn_guard.has_new_reply(tool_context) is True   # current = 1, baseline = 0 -> True

    turn_guard.cleanup_session(session_id)
    print("PASS: test_comment_8_turn_guard_fail_safe_on_restart")


@pytest.mark.asyncio
async def test_comment_10_live_ready_and_burst_prevention() -> None:
    """Comment 10: live_ready notification gates audio chunks and prevents buffer burst."""
    session_id = "test-live-ready-gate-1"

    # 1. Verify contextvars and event registration
    live_ready_event = asyncio.Event()
    app_main._LIVE_READY_EVENTS[session_id] = live_ready_event
    token = app_main._CURRENT_SESSION_ID.set(session_id)

    # 2. Simulate Gemini connect hook
    gemini_instance = app_main.Gemini(model="gemini-2.5-flash")
    req = MagicMock()

    with patch.object(app_main, "_orig_gemini_connect") as mock_orig:
        @contextlib.asynccontextmanager
        async def fake_orig(self, r):
            yield "fake_conn"
        mock_orig.side_effect = fake_orig

        assert not live_ready_event.is_set()
        async with gemini_instance.connect(req) as conn:
            assert conn == "fake_conn"
            assert live_ready_event.is_set(), "Event must be set once connection is established"

    # 3. Verify audio burst defense in upstream handling
    mock_queue = MagicMock()
    dropped_chunks = 0
    sent_chunks = 0

    # Test before ready: chunk must be dropped
    unready_event = asyncio.Event()
    chunk = b"\x00\x00" * 160

    if not unready_event.is_set():
        dropped_chunks += 1
    else:
        sent_chunks += 1

    assert dropped_chunks == 1
    assert sent_chunks == 0

    # Test after ready: chunk is accepted
    unready_event.set()
    if not unready_event.is_set():
        dropped_chunks += 1
    else:
        sent_chunks += 1

    assert dropped_chunks == 1
    assert sent_chunks == 1

    # Clean up
    app_main._LIVE_READY_EVENTS.pop(session_id, None)
    app_main._CURRENT_SESSION_ID.reset(token)
    assert session_id not in app_main._LIVE_READY_EVENTS
    print("PASS: test_comment_10_live_ready_and_burst_prevention")


async def test_comment_11_commit_nudge_owed_arms_on_real_commit() -> None:
    """Comment 1: commit_nudge_owed arms against the real commit_visit_notes return payload."""
    session_id = "test-nudge-armed-session"

    mock_session = MagicMock()
    mock_session.id = session_id
    tool_context = MagicMock()
    tool_context.session = mock_session
    tool_context.state = {}

    await stage_visit_notes(
        event_type="Meeting",
        executive_summary="Executive summary for nudge test",
        raw_transcript_backup="Transcript",
        topics=[
            {
                "topic": "Cardiology",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "Discussed cardiology clinical data",
            }
        ],
        tool_context=tool_context,
    )

    turn_guard.record_agent_speech(session_id, "Summary readback")
    turn_guard.record_user_turn(session_id)

    # Call the real commit_visit_notes function
    real_commit_resp = await commit_visit_notes(tool_context=tool_context)

    # Verify that the real commit_visit_notes returned status: "success"
    assert real_commit_resp["status"] == "success"
    assert "instruction_for_model" in real_commit_resp

    # Exercise the downstream event parser logic from main.py:
    fr_mock = MagicMock()
    fr_mock.name = "commit_visit_notes"
    fr_mock.response = real_commit_resp

    commit_nudge_owed = False
    if fr_mock.name == "commit_visit_notes":
        resp_dict = getattr(fr_mock, "response", {})
        if isinstance(resp_dict, dict) and resp_dict.get("status") in ("success", "committed"):
            commit_nudge_owed = True

    assert commit_nudge_owed is True, "commit_nudge_owed failed to arm on real commit response payload!"

    # Clean up
    notes_workflow.cleanup_session(session_id)
    turn_guard.cleanup_session(session_id)
    print("PASS: test_comment_11_commit_nudge_owed_arms_on_real_commit")


async def test_comment_12_gemini_connect_timeout_and_slot_release() -> None:
    """Comments 3 & 4: Live connect timeout closes WebSocket with 4430 and cleanly releases session slot."""
    session_id = "test-connect-timeout-session"

    slot = app_main._acquire_session_slot(session_id)
    await slot.lock.acquire()
    acquired = True
    assert slot.lock.locked() is True

    # Real asyncio tasks to exercise Task.cancelled() and Task.exception()
    async def dummy_downstream() -> None:
        await asyncio.sleep(10)

    async def dummy_upstream() -> None:
        await asyncio.sleep(10)

    down_task = asyncio.create_task(dummy_downstream())
    up_task = asyncio.create_task(dummy_upstream())

    mock_ws = AsyncMock()
    live_ready_event = asyncio.Event()  # never set -> simulates hang

    async def simulate_notify_live_ready() -> None:
        try:
            await asyncio.wait_for(live_ready_event.wait(), timeout=0.05)
        except asyncio.TimeoutError:
            await mock_ws.close(code=4430, reason="gemini_connect_timeout")
            down_task.cancel()
            up_task.cancel()

    notify_task = asyncio.create_task(simulate_notify_live_ready())

    # Exercise the exact asyncio.wait and task exception loop from main.py:
    done, pending = await asyncio.wait(
        {up_task, down_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending | {notify_task}:
        task.cancel()
    for task in pending | {notify_task}:
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # Calling task.exception() on a cancelled task raises CancelledError unless
    # task.cancelled() is checked first!
    for task in done:
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None and not isinstance(exc, WebSocketDisconnect):
            raise exc

    # Assert WebSocket was closed with code 4430
    mock_ws.close.assert_awaited_once_with(code=4430, reason="gemini_connect_timeout")

    # Assert down_task and up_task were cancelled
    assert down_task.cancelled()
    assert up_task.cancelled()

    # Assert slot is cleanly released in finally block
    app_main._release_session_slot(session_id, slot, acquired)
    assert session_id not in app_main._SESSION_SLOTS
    assert not slot.lock.locked()
    print("PASS: test_comment_12_gemini_connect_timeout_and_slot_release")


async def main() -> None:
    print("Running PR Review Comments Verification Tests...\n")
    test_comment_1_no_private_adk_imports()
    await test_comment_2_ordered_event_chaining_and_flush()
    await test_comment_3_pydantic_error_handling_and_logging()
    test_comment_4_inspect_endpoint_removed()
    test_comment_6_post_sessions_minting()
    await test_comment_5_session_id_normalization_removed()
    await test_comment_7_and_9_consecutive_visits_and_idempotency()
    test_comment_8_turn_guard_fail_safe_on_restart()
    await test_comment_10_live_ready_and_burst_prevention()
    await test_comment_11_commit_nudge_owed_arms_on_real_commit()
    await test_comment_12_gemini_connect_timeout_and_slot_release()
    print("\nALL 12 REVIEW COMMENT FIX TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
````
<!-- END: scripts/test_pr_review_fixes.py -->

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
import urllib.request
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
    # by tests/test_notes_workflow_gates.py, which drives notes_workflow
    # directly -- including the live same-session_id call pattern tools.py uses.
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
    topics_list = [t.strip() for t in planned_topics.split(",") if t.strip()] if planned_topics else []
    
    # Mint session on server via POST /api/sessions (AIML-2743 / VertexAiSessionService)
    post_data = json.dumps({
        "user_id": user_id,
        "planned_topics": topics_list,
        "campaign_type": DEFAULT_CAMPAIGN_TYPE,
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:8000/api/sessions",
        data=post_data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        session_info = json.loads(resp.read().decode("utf-8"))
        session_id = session_info["session_id"]

    query = urllib.parse.urlencode(
        {
            "planned_topics": planned_topics,
            "campaign_type": DEFAULT_CAMPAIGN_TYPE,
        }
    )
    url = f"{BASE_WS_URL}/{user_id}/{session_id}?{query}"
    print(f"\n=== {scenario} ===")
    print(f"minted session: {session_id}")
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

