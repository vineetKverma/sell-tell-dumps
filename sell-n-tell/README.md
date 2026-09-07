# Agentic AI Voice Notes Logger

A dynamic, agentic voice-dictation app for field sales reps, built on **Google
ADK** + the **Gemini Live API** (bidirectional audio streaming) and **FastAPI**.

A rep speaks unstructured notes about a customer visit. The app detects when
they stop talking (VAD), extracts a single structured CRM record via one Gemini
function call, reads back a spoken confirmation, and commits to the CRM on
verbal approval.

```text
[User speaks notes] -> [VAD silence stop-trigger] -> [single Mega-Payload tool call]
   -> [spoken confirmation] -> ["Save" / "Change …"] -> [commit to CRM] -> [end]
```

## How the spec maps to the code

| Spec step | Implementation |
|-----------|----------------|
| **1. Dynamic session init & open voice capture** | `before_agent_callback` in `app/voice_notes_agent/agent.py` fetches the campaign-specific schema/instructions from `GET /api/v1/config/agent-schema` and injects them into the system prompt. No trigger words required. |
| **2. VAD stop-trigger (silence)** | Audio streams continuously and the model's automatic VAD (`RealtimeInputConfig.automatic_activity_detection.silence_duration_ms` in `app/main.py`) finalizes each spoken turn after the silence threshold. The browser shows a live silence countdown and gates the mic while the agent speaks, then re-opens it for the rep's response. **Note:** the spec asks for 2.5–3.0s, but the Live API caps `silence_duration_ms` at **2000ms**, so the value is clamped to that maximum. |
| **3. Single-function extraction (temp 0.1 / top_p 0.8)** | `generate_content_config` on the agent enforces determinism; the prompt forces a single `stage_visit_notes` "Mega-Payload" tool call before any freeform text. The payload carries an overall `event_type` plus a `topics` list — one entry per discussion topic, **each with its own `disposition_code` and `executive_summary`**. |
| **4. Implicit confirmation + generative playback** | The `stage_visit_notes` tool POSTs to `/api/v1/notes/stage`, which builds the confirmation string; the native-audio model speaks it back (AUDIO modality). |
| **5. Branching (save vs. correction)** | "Save" → `commit_visit_notes` → `POST /api/v1/notes/commit`. A correction → re-call `stage_visit_notes` with the updated payload and re-confirm. |

The ADK tools call the REST API over HTTP (true to the spec); the REST API is
backed by an in-memory mock config DB + CRM store in
`app/voice_notes_agent/mock_db.py`.

## API spec endpoints

- `GET  /api/v1/config/agent-schema?campaign_type=...` — dynamic agent config
- `POST /api/v1/notes/stage` — stage extracted `StagedVisitPayload`
- `POST /api/v1/notes/commit` — commit a staged payload to the CRM
- `GET  /api/v1/notes/committed` — (debug) inspect committed records

Try a different `campaign_type` (`standard_sales`, `enterprise_field`,
`renewals`) to see different allowed event types and disposition registries
injected dynamically.

## Run it locally

```bash
uv sync                       # or: pip install -e .
# Configure app/.env (GCP project/location for Vertex AI, or an API key).
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000, pick a campaign, press the mic, and dictate. The
mic auto-stops on a pause; review the staged record, then say **"Save"** (or
**"Change the event type to a phone call"**).

> A **native-audio** Gemini Live model (`gemini-live-2.5-flash-native-audio`) is
> required for spoken confirmation playback. With a half-cascade model the app
> falls back to text replies.

## Cloud Deployment

The service is fully packaged via `Dockerfile` to deploy seamlessly to Google Cloud Run. 

```bash
gcloud run deploy sell-n-tell \
  --source . \
  --region us-east1 \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=your-project,GOOGLE_CLOUD_LOCATION=us-east1,VOICE_NOTES_API_BASE=http://localhost:8080,VOICE_NOTES_AGENT_MODEL=gemini-live-2.5-flash-native-audio"
```
*(See `DEPLOYMENT.md` for a deeper architectural breakdown of Cloud Run vs Vertex AI Agent Engine.)*

## Project layout

```text
app/
  main.py                       FastAPI: REST spec + WebSocket bridge + static
  .env                          Model / GCP / VAD / API-base config
  voice_notes_agent/
    agent.py                    Dynamic agent (config injection + instruction provider)
    tools.py                    stage_visit_notes / commit_visit_notes (HTTP -> REST)
    mock_db.py                  Mock config registry + CRM store
  static/                       Frontend (UI + audio worklets + client VAD + Service Worker)
Dockerfile                      Cloud Run container definition
