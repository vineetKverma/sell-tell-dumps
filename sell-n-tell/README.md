# SellNTell — Agentic Voice Notes Logger

A voice-dictation app for field sales reps (FARs). The rep speaks unstructured
notes after a customer visit; an agent extracts a **structured CRM record** —
event type, plus one entry per discussion topic with a disposition code and
summary — reads it back aloud, and commits it on verbal approval.

**Why an agent and not a transcriber.** A transcript is useless to a CRM. The
task is *constrained extraction*: mapping free speech onto a fixed registry of
outcome codes, hands-free, with no screen. Verification is a spoken readback and
a verbal yes.

---

## Architecture

```
browser mic (16 kHz Int16 PCM, 20 ms chunks)
   │  WS /ws/{user_id}/{session_id}?campaign_type=&planned_topics=&agent_mode=
   ▼
FastAPI  upstream_task ──> ADK LiveRequestQueue ──> Gemini Live (Vertex, native audio)
                                                          │
                            downstream_task <── events ────┘
                                  ├─ function_call → tools.py → HTTP POST → own REST API → store
                                  └─ audio chunks  → WS → browser playback
```

**The agent tools never touch the datastore.** They HTTP-call the app's own
`/api/v1` endpoints. Two consequences worth knowing:

1. **All enforcement belongs in the REST layer.** Every agent mode inherits it
   for free — there is no way for a mode to bypass a rule by being written
   differently.
2. **Every gap is reproducible with plain HTTP calls** — no microphone, no
   model, no Vertex dependency, fully deterministic.

---

## The two modes

Selected per session via the `agent_mode` query parameter. One `Runner` each.

| | `implicit` | `guided` |
|---|---|---|
| Files | `agent.py`, `tools.py` | `agent_guided.py`, `tools_guided.py` |
| Tools | 2 | 5 |
| Rep turns | ~2 | ~8 |
| Shape | one "Mega-Payload" `stage_visit_notes` call | explicit turn-by-turn script |
| Confirms each field? | no | yes |

Measured on identical input, both modes produce **identical dispositions**. They
differ only in how much the rep is asked.

A third `hybrid` mode exists on `feature/AIML-2686` and is not part of this
codebase.

---

## Campaigns and disposition codes

Each campaign declares its own legal event types and disposition codes. The
config is injected into the agent's prompt *and* enforced server-side — a prompt
only asks.

| Campaign | Event types | Disposition codes |
|---|---|---|
| `standard_sales` | Meeting, On-site visit, Phone Call | 1–10 |
| `enterprise_field` | Meeting, On-site visit | 1, 2, 4, 5, 8 |
| `renewals` | Phone Call, Meeting | 2, 3, 5, 8, 9 |

Codes 1–10 are business outcomes (Create Opportunity, Order Placed, No current
need, Contracted to competitor, Preferred vendor already, …).

**Code 99 — "Outcome not covered, needs manual review" — is appended to every
campaign.** It exists because filling a structured field is an argmax over the
allowed values: there is always a "best" option, even when every option is
wrong. Without an explicit "none of these" the model returns a confidently wrong
code. Measured: a `renewals` call where the customer requested a quote returned
code 2 ("Order Placed") or 3 ("No current need") at random across six runs —
opposite meanings, both false. With 99 available it selects 99, and controls
confirm it never wins when a real code fits.

---

## Enforcement

These fail loudly rather than producing bad CRM data:

| Guard | Behaviour |
|---|---|
| Planned-topic coverage | Commit refused (`409`) until every planned topic has an outcome or an explicit rep-stated skip |
| Campaign rules | Event types and codes validated against the active campaign (`422`); illegal values rejected and re-asked |
| Real confirmation | Commit refused unless a genuine rep reply arrived *after* the readback — the agent cannot answer its own question and save |
| Skip provenance | A topic can only be marked "not discussed" after the rep was asked |
| Frontend truthfulness | The UI shows "Saved to CRM" only when a CRM record id actually exists |

A refusal is the system working correctly.

---

## Running it

```powershell
uv sync
gcloud auth application-default login
gcloud config set project prj-hds-np-data

uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open <http://localhost:8000>.

**Don't use `--reload` for a demo.** A file save restarts the process, which
drops every live WebSocket and wipes both the session store and staged records.

**Hard-refresh (Ctrl+Shift+R) after any `app.js` change** — it's a cached ES
module.

### Configuration — `app/.env`

| Variable | Notes |
|---|---|
| `GOOGLE_GENAI_USE_VERTEXAI` | `TRUE` for Vertex |
| `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` | e.g. `prj-hds-np-data` / `us-east1` |
| `VOICE_NOTES_AGENT_MODEL` | **must be a native-audio model** or spoken playback silently disables itself |
| `VOICE_NOTES_VAD_SILENCE_MS` | silence before the server VAD finalizes a turn (default 2500) |
| `BIGQUERY_ENABLED` | selects `bigquery_db` over `mock_db` in `db_interface` |
| `VOICE_NOTES_BQ_ENABLED` | *separate* flag read by `bigquery_sink` — see Known issues |

`.env` is gitignored; `app/.env.example` is the template.

---

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/config/agent-schema?campaign_type=` | per-campaign rules injected into the prompt |
| `GET /api/v1/config/planned-topics` | catalog of selectable pre-call topics |
| `POST /api/v1/notes/stage` | stage an extracted payload, return confirmation text |
| `POST /api/v1/notes/commit` | commit a staged payload to the CRM |
| `GET /api/v1/notes/committed` | inspect committed records (debug) |
| `GET /api/v1/client-config` | runtime knobs for the browser |
| `WS /ws/{user_id}/{session_id}` | bidirectional audio ↔ agent |

---

## Testing

**Conversational harness** — no mic, real WebSocket, scripted text turns:

```powershell
uv run python scripts/ws_smoke_test.py implicit
uv run python scripts/ws_smoke_test.py guided
uv run python scripts/ws_smoke_test.py guided --scenario clean_save
```

Bar: all scenarios reach a commit, one CRM record each, no duplicates.

`ambiguous_disposition` is **intermittent** — it exercises the deliberately
confusing 3-strikes path and passes roughly 2 runs in 3. Re-run before treating
a failure as a regression.

A 9-case REST regression suite (no mic, no model) is documented in
`docs/AIML-2698-experiments.md`.

---

## Layout

```
app/
  main.py                    FastAPI app, REST endpoints, WebSocket bridge
  static/
    index.html
    js/app.js                UI state machine, client VAD, rendering
    js/audio-recorder.js     mic capture, 16 kHz resampling, anti-alias filter
    js/audio-player.js       agent playback
  voice_notes_agent/
    agent.py / tools.py            implicit mode
    agent_guided.py / tools_guided.py  guided mode
    mock_db.py               campaign configs, disposition registry, staging + commit
    db_interface.py          selects mock_db or bigquery_db
    turn_guard.py            blocks tools acting without a genuine new rep reply
    bigquery_sink.py         analytics sink (fire-and-forget)
scripts/ws_smoke_test.py     conversational regression harness
docs/                        change log, gap findings, demo scripts
```

---

## Audio pipeline

`new AudioContext({sampleRate: 16000})` is a **request, not a guarantee** — on
many Windows machines the context returns 44100 or 48000. Forwarding those
samples while telling the Live API they are 16 kHz sends ~3× more audio per
second than real time, and the server kills the socket:

```
APIError: 1011 Input data processing failed. This is likely due to the
client sending data too fast.
```

So `audio-recorder.js` reads the rate the context *actually* got, low-passes
(4th-order Butterworth at 7 kHz — decimating without this folds everything above
8 kHz into the speech band and wrecks consonant detail), then resamples to
16 kHz and batches to 20 ms chunks. Correct behaviour is **32 000 bytes/sec**
upstream; the browser console logs the resampling decision on mic start.

`app.js` additionally drops chunks when `websocket.bufferedAmount` exceeds ~2 s
of audio. There is no catching up on a realtime stream — a backlog delivered
late reads as "too fast" and kills the session.

---

## Known issues

- **Invented skip reasons.** The agent can state a reason the rep never gave
  ("skipped due to time constraints"), despite an explicit prompt rule
  forbidding that exact phrase. Needs a server-side fix; prompt text has been
  measured not to work.
- **Orphaned staged records.** A correction re-stages under a new `session_id`
  and leaves the previous draft in place, uncommitted and still committable.
  Tracked under AIML-2703.
- **Topic-label matching** (`_topic_matches`) uses substring containment, so an
  inflected label ("Appliance Contract Renewal" vs planned "Appliances") reports
  the topic uncovered and can produce a second row for one discussion.
- **Two flag shapes for "no code fits"** — guided uses a null code plus
  `needs_manual_review`; implicit uses code 99. Pending unification.
- **Two BigQuery env vars** — `db_interface` reads `BIGQUERY_ENABLED`,
  `bigquery_sink` reads `VOICE_NOTES_BQ_ENABLED`.
- **Registry gaps** — no code expresses "renewal agreed" or "no contact made"
  on any campaign; a no-contact visit has no valid event type either. Product
  decision, not an engineering one.

---

## Design principle worth knowing before you change anything

**A prompt rule cannot beat a structure pointing the other way.**

Five fixes in this codebase followed that shape and were solved structurally — a
code-level gate, an ordering constraint, an extra enum value. The one prompt-only
attempt was measured over six runs before and after and made no difference. When
the model reliably ignores an instruction, change what the schema or the flow
makes easy, not how emphatically the prompt is worded.

**Corollary:** when a guard fires unexpectedly, instrument before assuming it's
wrong. `turn_guard` looked broken for a day and was correct every time.

---

## Documentation

| File | Contents |
|---|---|
| `docs/HANDOFF.md` | resume with no prior context |
| `docs/change-log.md` | every change, why, and verification status |
| `docs/AIML-2698-gap-findings.md` | 18 gaps, reproduction method, priorities |
| `docs/AIML-2698-experiments.md` | reproductions and the REST suite |
| `docs/demo-golden-path.md` | scripted demo scenarios per mode and campaign |
| `docs/demo-runbook-failure-modes.md` | failure modes and recovery for the demo driver |
| `docs/far-notes-dataset-analysis.md` | analysis of 1000 real FAR notes |
