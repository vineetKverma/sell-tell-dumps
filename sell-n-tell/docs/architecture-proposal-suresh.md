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

**The 20 fields are optional.** Reps state few of them in any one call: in
the must-capture sheet's own evidence, a quantified count appears in about
1-2% of notes and par levels in under 1%. So every field is an optional slot:
filled only when the rep states it, otherwise empty. Requiring a field makes
the model invent a value (measured earlier: a required summary on a skipped
topic produced "due to time constraints").

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
code, derive anything that is a business rule, and deliver the record to the
client and the consumer.

```
client app ──POST /sessions (CRM ids, vertical, topics)──► Cloud Run (ADK)
client app ──audio (WebSocket, typed events)────────────► │ ◄──► Gemini Live: hears + speaks
                                                          │ transcript
                                                          ▼
                                           our code: dialogue steps (state kept in the session)
                                             ├─ Model Armor → screen the transcript
                                             ├─ extract()   → Gemini text call, JSON schema; prompt holds the
                                             │                universal fields + the account's vertical only
                                             ├─ derive      → event type check, disposition (rules, not the model)
                                             ├─ interpret() → Gemini text call: is the reply a yes, a correction, unclear?
                                             ├─ Model Armor → de-identify the record
                                             └─ save        ├─► WebSocket: "saved" event to the client app
                                                            └─► Pub/Sub "visit-records"
                                                                  ├─► third-party service
                                                                  └─► BigQuery (our copy)
reference data (Cloud Storage, versioned): campaign topics + descriptions, field catalog, rules
session capture: Agent Engine sessions · Cloud Logging/Trace · log sink → BigQuery
```

**The dialogue steps** (the state is stored in the session, so a restart
resumes):

```
LISTENING → EXTRACTING → (planned topic not mentioned?) → ASKING_ABOUT_TOPIC → EXTRACTING
                       → READING_BACK → WAITING_FOR_YES
WAITING_FOR_YES, on the rep's next reply:
   yes ("yes", "yeah", "save it")  → SAVING → DONE
   correction ("change the date")  → EXTRACTING → read back what changed
   unclear or noise                → ask again
   no reply                        → remind, then keep the notes unsaved
```

Saving is reachable only from WAITING_FOR_YES, and only through a reply that
arrives after the latest readback; a correction always forces a new readback.
That is what `turn_guard` checks today, now enforced by the flow itself.

## 3. Changes and reasons

| # | Change | Reason |
|---|---|---|
| 1 | **Extraction moves to a text Gemini call** with a fixed JSON schema (`extract`). Live gets one tool, `dictation_done()`, with no arguments. Every must-capture field is optional in the schema | The schema guarantees the record's shape, so the repair code goes. The 20 fields become schema fields, not prompt text. It can be scored on the golden set in minutes, without a live conversation |
| 2 | **One extraction call or several is decided by the eval.** Option A: one call. Option B: parallel calls, each with a focused part of the record (e.g. contact and next step; commercial outcome, blockers and objections; the 9 vertical fields), plus topic status and event type. Both are scored on the golden set before choosing | Smaller prompts may be more reliable; one call keeps related facts consistent (the commercial outcome, the topic outcomes and the next step describe the same moment). Measuring both settles it |
| 3 | **Extraction follows written business rules**, in `extract()` and checked by the eval. Approved (Jeremy): a business conversation with a customer contact → Meeting; front desk or gatekeeper only, or no conversation → On-site visit (confirmed by Tobi); a call → Phone Call; dimensions stored like 4x4 with the rep's unit; in Trades, trucks count like units or properties. Proposed, to confirm (question 2): a planned campaign counts as discussed only when the rep talks about its offer or products | Today's prompt has none of these rules, which explains most of the event-type and topic-status misses. The "discussed" rule is how the golden set is labelled, so it needs sign-off |
| 4 | **Disposition codes stop being a model choice.** The agent captures the facts (U-02 contact outcome, U-04 commercial outcome, U-06 objection and competitor). If a per-topic code is still needed downstream, it is derived from those facts by a small business-owned mapping (e.g. U-04 "order placed" gives 2, U-06 "pricing" gives 8, no match gives 99). Otherwise the codes are dropped | Nothing consumes the codes today, they were not in the approved list, they overlap U-04/U-06, and they lack quote created and no contact. A derived code can't contradict the fields and can't be a forced guess |
| 5 | **Our code decides when to save,** through the dialogue steps in §2. `interpret()` classifies the rep's reply after the readback: "yeah" or "okay" after "shall I save?" is a yes; noise or an empty transcript is unclear and the agent asks again; "yes, but change X" is a correction. The reminder for unaddressed planned topics stays | "No save without a real yes" holds by design: the model can no longer save, and only a fresh reply to the latest readback can. `turn_guard`, the commit watchdog, the in-memory store and its prune task go. Confirmation replies are added to the eval so this is measured, not assumed |
| 6 | **Topics carry ids where they have one**, and topic status becomes one field (`unaddressed / skipped / discussed`). A topic in the registry gets its description (a short version, about 300 characters); a topic not in the registry is kept by its title | Fixes the substring-match bug (two rows for one topic) and gives the model what a campaign is about. 380 of 1,947 real topic titles (66% of mentions) are in the registry once its names are repaired (the source file's Replace All damage, e.g. "MF" → "MH - MULTIFAMILY"), so a third of topic mentions still have no id or description. 34 titles contain commas, so topics travel as a JSON list |
| 7 | **`POST /sessions` takes the inputs the record needs**: account id, visit or event id, the account's vertical, and the planned topics (registry id, or title when not in the registry). The rep's identity comes from the verified token. `vertical` must be one of MH, HS, HL, IS, TR, IN (consumer accounts map to MH); an unknown vertical or topic id is rejected. The session loads the universal fields plus that vertical's 9, built from the field catalog in reference data. Campaign type is no longer an input. The published record carries the CRM keys | The vertical picks the 9 vertical fields, as you assumed (an API input), and keeps other verticals' fields out of the prompt. Without CRM keys the consumer can't attach the record to anything; today it has only our `session_id` |
| 8 | **The saved record goes to two places at once**: a `saved` event to the client app over the WebSocket, and Pub/Sub, with a Pub/Sub schema as the contract (generated from `schemas.py`). The consumer subscribes; a BigQuery subscription keeps our copy | The rep sees the save immediately. Pub/Sub makes it durable from the moment of save, with built-in retry (7 days) and a dead-letter topic. A new consumer needs no change on our side |
| 9 | **Model Armor**: screen the transcript before extraction, and de-identify the record before publishing | The dictation is untrusted model input. Healthcare records must never carry patient or resident identity |
| 10 | **Session capture uses managed services**: Agent Engine sessions (already in place), Cloud Trace through ADK's built-in tracing, Cloud Logging, Error Reporting, and a log sink to BigQuery, including token usage and cost per session | Full logs and telemetry with no request-path cost. Replaces the BigQuery analytics plugin, disabled because it added about 40 s to every connect |
| 11 | **The frontend is removed and replaced by a client contract document** (§4) | A client owned by another team calls us. Our browser app does work today that the contract must spell out |
| 12 | **Failure handling is defined.** If extract(), Model Armor or Pub/Sub fails: one retry with backoff, then the client gets a typed error and the rep hears a fixed "couldn't save, your notes are kept" line. The transcript stays in session state for recovery. An unscreened record is never published. Google auth and token refresh never block the event loop | Nothing has retries today (AIML-2651). The eval saw Google token fetches time out and sockets drop on the test environment, so these failures are real, not theoretical |
| 13 | **Reference data is versioned in Cloud Storage**: campaign topics with descriptions, the must-capture field catalog, the event-type rules, and the disposition mapping if kept (from `dispositions.yaml`). Loaded at startup; each record stores the versions used | Extraction needs topic descriptions and the vertical's fields, and the eval must use the same versions. New campaign topics each quarter need no deploy |
| 14 | **The eval is part of the product, in two tiers.** Tier 1, every change: text cases on the golden set (`evals/v1`), scoring `extract()` directly and the agent end to end through the harness (`evals/agent_eval`), which is updated to the new typed events and session inputs; ADK's own eval (`evals/adk_eval`) runs the same cases. Tier 2, before a release: the same scoring on real spoken recordings, including noise, accents and clipped speech. Recordings have to be collected first; there are none today | Quality drops are caught before deploy. Text cases can't catch mishearing, so audio needs its own tier. The golden set holds customer notes, so it stays internal with an agreed retention |

## 4. Client contract (what the other team's client must do)

Our browser app does these today, without them being written down. The
contract document has to state each one:

| Topic | What the contract says |
|---|---|
| Auth and identity | The client sends a token. The rep's identity comes from the verified token, not from the URL path as today, where the client picks it |
| Session | `POST /sessions` with `{account_id, visit_id, vertical, planned_topics: [{id} or {title}]}` → `session_id`. One session per dictation. Reconnect rule: a new session, or resume within N seconds |
| Audio | Up: 16 kHz, 16-bit mono PCM, 20 ms chunks. Down: 24 kHz PCM. Mic off while the agent speaks (half-duplex). Barge-in stops playback. Drop audio if the uplink falls more than ~2 s behind |
| Connection | How keep-alive works (the server may be slow to answer pings during a token refresh), and the time limit per session |
| Events | A small typed event set (`ready`, `transcript`, `agent_text`, `record_preview`, `saved`, `error`), not raw ADK events as `main.py` forwards today |
| End of session | The server sends `saved`, speaks the closing line and closes the connection. That replaces the client-side auto-close timer |
| Errors | Typed error codes (`session_busy`, `not_found`, `save_failed`, …) with retry advice |

## 5. Pending questions

### Business and product

| # | Question | Our recommendation |
|---|---|---|
| 1 | Are all 20 must-capture fields optional (empty when not said), with the agent never inventing a value to complete a record? | Yes (§1) |
| 2 | Does a planned campaign count as discussed only when the rep talks about its offer or products? | Yes. It is how the golden set is labelled, and the alternative (any visit counts) makes topic status meaningless |
| 3 | Does Salesforce or reporting need a per-topic disposition code at all? | If yes, derive it from U-02/U-04/U-06 with a business-owned mapping that adds quote created and no contact. If no, drop the codes (change 4) |
| 4 | Who owns reference-data updates (new campaign topics each quarter)? | The business owner of Campaign Topics. We load new versions without a deploy |
| 5 | Is the consumer only the third-party service, or do we also keep our own copy of records? | Keep our copy (BigQuery subscription, no code) |
| 6 | What may the record contain: business contact names (field U-01) but never patient or resident identity? | Yes. Model Armor's de-identify template is written to that rule |
| 7 | Which CRM ids exist at the time of the visit (account, visit or event), and who supplies them, along with the vertical? | The client, in `POST /sessions` |
| 8 | What retention for transcripts (sessions, logs, BigQuery) and for the golden set, and do we keep raw audio? | Short retention for transcripts. No raw audio unless needed for debugging or the audio eval tier |

### Technical

| # | Question | Our recommendation |
|---|---|---|
| 9 | One extraction call, or several in parallel? | Score both on the golden set and keep the better one (change 2) |
| 10 | Who is the client, and how does it authenticate: a service, or reps' devices? | A service with Cloud Run IAM tokens. Use Identity Platform if reps connect directly |
| 11 | Which Gemini model for `extract()`? The golden set was labelled with gemini-3.8-flash and gemini-3.1-pro-preview (global only) | A different model or version, or the scores flatter us |
| 12 | Which region, given that the 3.x text models are global only, and what margin counts as "better than today" for `extract()`? | Live in `us-central1`; `extract()` on global if a 3.x model wins, else a regional model. Agree the margin before building it |
| 13 | Which ADK version do we standardise on? | 2.10, pinned in `uv.lock`. A trial on 2.10 ran ADK's live evaluation on our agent with no app changes; 2.1.0 has none |
| 14 | When do we get our own Agent Engine, and can it act as a lock across instances or host the WebSocket instead of Cloud Run? | Own engine before records are published. Stay on Cloud Run, one instance |
| 15 | Can Model Armor screen Gemini Live audio directly? | Not sure. We assume no and screen the transcript. Needs confirming |
| 16 | Should our code, not Live, decide when dictation has ended? | Try it once extraction works. It removes the silence watchdog if it works |
| 17 | Do the managed log sinks fully replace the BigQuery analytics plugin once deployed? | Expected yes; confirm on Cloud Run before removing the plugin's code |
