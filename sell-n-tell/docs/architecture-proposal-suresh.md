# SellNTell: architecture proposal

**For:** Suresh (architect) · **Status:** draft for review

## 1. Why change

The must-capture work adds up to 20 fields per call (11 universal plus 9 for
the account's vertical) to the record. Today the whole record is extracted by
the Gemini Live audio model as one tool call, and the same model decides when
to save. The AIML-2702 baseline (90 golden cases, 3 runs) measures what that
gives today:

| Measure | Today | Main cause |
|---|---|---|
| Topic status | 48.7% | 65% of campaigns the rep never mentioned are marked discussed. The prompt says "extract a disposition for EACH planned topic", and the agent sees only campaign titles, no descriptions |
| Event type | 59.7% | Meeting and On-site visit mixed up both ways. The prompt lists the three names with no rules |
| Disposition | 72.2% | Every miss is a forced code where none fits. Code 1's cue words ("interested", "send a quote") contradict the "use 99" guidance |
| Summary faithfulness | 22.0% | Summaries written for campaigns that were not discussed; invented skip reasons |
| Must-capture fields | 0% | Not built; the tool call has no place for them |

Three structural problems sit underneath:

- **Unreliable extraction.** Tool arguments arrive malformed and need repair
  code (`_normalize_topics`). The model invents details. Adding 20 fields to
  the same tool call makes it worse.
- **Unsafe saving.** The model can save without hearing a real "yes", so
  `turn_guard` and three watchdogs (silence, readback, commit) exist to stop
  it.
- **Slow measurement.** Extraction can only be tested through a full live
  conversation: about 1.5 hours per 90-case run (about a minute per case).
  `adk eval` can't run a live model on the test environment's ADK (2.1.0).

Separately, a saved record exists only in the session state and process
memory. Nothing is produced that the consuming service can read.

## 2. Proposal in one picture

Keep Gemini Live for voice. Move extraction and the save decision into our
code, derive anything that is a business rule, and publish the record for the
consumer.

```
client app ──POST /sessions (CRM ids, vertical, topic ids)──► Cloud Run (ADK)
client app ──audio (WebSocket, typed events)───────────────► │ ◄──► Gemini Live: hears + speaks
                                                             │ transcript
                                                             ▼
                                              our code: dialogue steps
                                                ├─ extract()   → Gemini (text, JSON schema)
                                                ├─ interpret() → Gemini (text, JSON schema)
                                                ├─ derive      → event type check, disposition (rules, not the model)
                                                ├─ Model Armor → screen input, de-identify record
                                                └─ save        → Pub/Sub "visit-records"
                                                                    ├─► third-party service
                                                                    └─► BigQuery (our copy)
reference data (Cloud Storage, versioned): campaign topics + descriptions, field catalog, rules
session capture: Agent Engine sessions · Cloud Logging/Trace · log sink → BigQuery
```

## 3. Changes and reasons

| # | Change | Reason |
|---|---|---|
| 1 | **Extraction moves to a text Gemini call** with a fixed JSON schema (`extract`). Live gets one tool, `dictation_done()`, with no arguments | The schema guarantees the record's shape, so the repair code goes. The 20 fields become schema fields, not prompt text. It can be scored on the golden set in minutes, without a live conversation |
| 2 | **Extraction follows written business rules**, in `extract()` and checked by the eval. Approved (Jeremy): a person mentioned → Meeting, otherwise On-site visit (a call → Phone Call); dimensions stored like 4x4 with the rep's unit; in Trades, trucks count like units or properties. Proposed, to confirm (question 14): a planned campaign counts as discussed only when the rep talks about its offer or products | Today's prompt has none of these rules, which explains most of the event-type and topic-status misses. The "discussed" rule is how the golden set is labelled, so it needs sign-off |
| 3 | **Disposition codes stop being a model choice.** The agent captures the facts (U-02 contact outcome, U-04 commercial outcome, U-06 objection and competitor). If a per-topic code is still needed downstream, it is derived from those facts by a small business-owned mapping (e.g. U-04 "order placed" gives 2, U-06 "pricing" gives 8, no match gives 99). Otherwise the codes are dropped | Nothing consumes the codes today, they were not in the approved list, they overlap U-04/U-06, and they lack quote created and no contact. A derived code can't contradict the fields and can't be a forced guess |
| 4 | **Our code decides when to save.** A text Gemini call classifies the rep's reply (`confirm / correction / skip / unclear`). Saving happens only on a clear `confirm` to the current readback. The reminder for unaddressed planned topics stays, now driven by topic status. The dialogue state and the draft are written to the Agent Engine session state, so a restart resumes | "No save without a real yes" holds by design. `turn_guard` and the commit watchdog go, along with the in-memory store and its prune task |
| 5 | **Topics carry ids**, and topic status becomes one field (`unaddressed / skipped / discussed`). The session gives each topic its registry description (a short version, about 300 characters) | Fixes the substring-match bug (two rows for one topic) and gives the model what a campaign is about. Only 243 of 1,960 real topic titles (26% of mentions) are in the registry, and 34 titles contain commas, so ids plus a JSON list are needed |
| 6 | **`POST /sessions` takes the inputs the record needs**: account id, visit or event id, rep id, the account's vertical, and the planned topic ids. Campaign type stays an optional placeholder. The published record carries the CRM keys | The vertical picks the 9 vertical fields, as Suresh assumed (an API input). Without CRM keys the consumer can't attach the record to anything; today it has only our `session_id` |
| 7 | **The saved record is published to Pub/Sub**, with a Pub/Sub schema as the contract (generated from `schemas.py`). The consumer subscribes; a BigQuery subscription keeps our copy | Durable from the moment of save. Built-in retry (7 days) and a dead-letter topic. The rep doesn't wait on a database. A new consumer needs no change on our side |
| 8 | **Model Armor**: screen the transcript before extraction, and de-identify the record before publishing | The dictation is untrusted model input. Healthcare records must never carry patient or resident identity |
| 9 | **Session capture uses managed services**: Agent Engine sessions (already in place), Cloud Trace through ADK's built-in tracing, Cloud Logging, Error Reporting, and a log sink to BigQuery, including token usage and cost per session | Full logs and telemetry with no request-path cost. Replaces the BigQuery analytics plugin, disabled because it added about 40 s to every connect |
| 10 | **The frontend is removed and replaced by a client contract document** (§4) | A client owned by another team calls us. Our browser app does work today that the contract must spell out |
| 11 | **Failure handling is defined.** If extract(), Model Armor or Pub/Sub fails: one retry with backoff, then the rep hears a fixed "couldn't save, your notes are kept" line. The transcript stays in session state for recovery. An unscreened record is never published. Google auth and token refresh never block the event loop | Nothing has retries today (AIML-2651). The eval saw Google token fetches time out and sockets drop on the test environment, so these failures are real, not theoretical |
| 12 | **Reference data is versioned in Cloud Storage**: campaign topics with descriptions, the must-capture field catalog, the event-type rules, and the disposition mapping if kept (from `dispositions.yaml`). Loaded at startup; each record stores the versions used | Extraction needs topic descriptions and the vertical's fields, and the eval must use the same versions. New campaign topics each quarter need no deploy |
| 13 | **The eval is part of the product.** The golden set (`evals/v1`: 90 real notes, 65 real top-up notes for rare fields, 5 synthetic cases kept separate) and the harness (`evals/agent_eval`) gate every release. `extract()` is first scored directly on the transcripts; the end-to-end harness is updated to the new typed events and session inputs (`drive.py` reads today's raw ADK events and `stage_visit_notes` calls, which both go) | Quality drops are caught before deploy. The golden set holds customer notes, so it stays internal with an agreed retention |

## 4. Client contract (what the other team's client must do)

Our browser app does these today, without them being written down. The
contract document has to state each one:

| Topic | What the contract says |
|---|---|
| Auth and identity | The client sends a token. The user_id comes from the verified token, not from the URL path as today, where the client picks it |
| Session | `POST /sessions` with the CRM ids, the vertical and the planned topic ids → `session_id`. One session per dictation. Reconnect rule: a new session, or resume within N seconds |
| Audio | Up: 16 kHz, 16-bit mono PCM, 20 ms chunks. Down: 24 kHz PCM. Mic off while the agent speaks (half-duplex). Barge-in stops playback. Drop audio if the uplink falls more than ~2 s behind |
| Connection | How keep-alive works (the server may be slow to answer pings during a token refresh), and the time limit per session |
| Events | A small typed event set (`ready`, `transcript`, `agent_text`, `record_preview`, `saved`, `error`), not raw ADK events as `main.py` forwards today |
| End of session | The server closes after the closing line and `saved`. That replaces the client-side auto-close timer |
| Errors | Typed error codes (`session_busy`, `not_found`, `save_failed`, …) with retry advice |

## 5. Pending questions

| # | Question | Our recommendation |
|---|---|---|
| 1 | Is the consumer only the third-party service, or do we also keep our own copy of records? | Keep our copy (BigQuery subscription, no code) |
| 2 | Who is the client, and how does it authenticate: a service, or reps' devices? | A service with Cloud Run IAM tokens. Use Identity Platform if reps connect directly |
| 3 | What may the record contain: business contact names (field U-01) but never patient or resident identity? | Yes. Model Armor's de-identify template is written to that rule |
| 4 | Which CRM ids exist at the time of the visit (account, visit or event, rep), and who supplies them, along with the vertical? | The client, in `POST /sessions` |
| 5 | Does Salesforce or reporting need a per-topic disposition code at all? | If yes, derive it from U-02/U-04/U-06 with a business-owned mapping that adds quote created and no contact. If no, drop the codes (change 3) |
| 6 | Can Model Armor screen Gemini Live audio directly? | Not sure. We assume no and screen the transcript. Needs confirming |
| 7 | Which Gemini model for `extract()`? The golden set was labelled with gemini-3.8-flash and gemini-3.1-pro-preview (global only) | A different model or version, or the scores flatter us |
| 8 | Which ADK version do we standardise on? Newer ADK may support live evaluation | Pin one version in `uv.lock`, then re-check live eval support |
| 9 | When do we get our own Agent Engine, and can it act as a lock across instances or host the WebSocket instead of Cloud Run? | Own engine before records are published (with Dharun). Stay on Cloud Run, one instance |
| 10 | What retention for transcripts (sessions, logs, BigQuery) and for the golden set, and do we keep raw audio? | Short retention for transcripts. No raw audio unless needed for debugging |
| 11 | Should our code, not Live, decide when dictation has ended? | Try it once extraction works. It removes the silence watchdog if it works |
| 12 | Who owns reference-data updates (new campaign topics each quarter)? | The business owner of Campaign Topics. We load new versions without a deploy |
| 13 | Which region, given that the 3.x text models are global only, and what margin counts as "better than today" for `extract()`? | Live in `us-central1`; `extract()` on global if a 3.x model wins, else a regional model. Agree the margin before building it |
| 14 | Does a planned campaign count as discussed only when the rep talks about its offer or products? | Yes. It is how the golden set is labelled, and the alternative (any visit counts) makes topic status meaningless |

## 6. Comments

<!-- Name: comment -->

## 7. Decisions

| # | Decision | By |
|---|---|---|
| | | |
