# Stories for the new SellNTell architecture

Every story needed to move from today's agent (Gemini Live extracts the
record and decides when to save) to the proposed design: Live for voice only,
extraction and the save decision in our code, records published for the
consumer. Based on the architecture proposal (§3 changes, §4 client contract,
§5 pending questions). Parent epic: AIML-1537. Points are planning estimates.

## Summary

| Phase | What it delivers | Stories | Points |
|---|---|---|---|
| 0–1 | Fair baseline for today's agent; `extract()` measured; go/no-go | AIML-2898, 2702, 2928, 2929 | done |
| 1b | Settle the extraction shape and the disposition codes | AIML-3003, AIML-3004 | 10 |
| 2 | Our code runs the conversation; old save machinery retired | S-01 – S-05 | 26 |
| 3 | Session inputs, topic ids, reference data, Model Armor, Pub/Sub | S-06 – S-10 | 28 |
| 4 | Client contract, harness on the new events, tracing, frontend removed | S-11 – S-14, AIML-2962 | 20 |
| 5 | Infrastructure, own Agent Engine, release gate, CI on golden data | S-15 – S-17, AIML-2957 | 17 |
| Later | Audio evaluation on real recordings | S-18 | 8 |

22 open stories, 109 points.

## Pick order

| Step | Pick | Why it can start then |
|---|---|---|
| Now | AIML-2962, S-08 | depend on nothing |
| | AIML-3003 | needs AIML-2929 |
| | AIML-3004 | needs AIML-2929 and the business answer on whether codes are needed |
| Next | S-01 | needs AIML-2929 and AIML-3003's decision; Phases 2–4 build on it |
| After S-01, in parallel | S-02, S-03, S-05, S-06, S-09, S-13 | each needs only S-01 |
| Then | S-04 | needs S-01, S-02 |
| | S-07 | needs S-06, S-08 |
| | S-10 | needs S-06, S-09 |
| Then | S-11, S-15 | need S-10 |
| Then | S-12 | needs S-11 |
| | S-16, AIML-2957 | need S-15 |
| Last | S-14 | needs S-11, S-12 |
| | S-17 | needs S-12, S-15, AIML-2957 |
| | S-18 | needs S-12 |

Critical path: AIML-3003 → S-01 → S-06 / S-09 → S-10 → S-11 → S-12.

## Phase 0–1: done

- **AIML-2898 Curate the vertical golden dataset.** 90 real notes (15 per
  vertical), 65 top-up notes, 5 synthetic; answer key v1.4. Kept in
  `gs://sellntell-eval-np`, never in the repo.
- **AIML-2702 Eval harness.** PASS / REGRESSION / INVALID against a committed
  baseline; quick (18 cases) and full (90).
- **AIML-2928 ADK 2.10 upgrade and prompt fixes** (PR #11). Topic status
  48.7% → 75.6%, event type 57.2% → 78.7%, faithfulness 22.0% → 54.9% (key
  v1.4); exact-label topic coverage.
- **AIML-2929 `extract()` as a text call with a fixed schema; go/no-go.**
  gemini-3.8-flash, thinking low, global: topic status 95.6%, event type
  93.4%, 0% campaigns wrongly marked discussed, P1 field recall 79%, USD 2.96
  per 1,000 notes.

## Phase 1b: settle the extraction shape (10 points)

### AIML-3003 Single vs parallel extraction: evaluate and choose (5)

Option A (one `extract()` call) is built and measured in AIML-2929. Build
Option B: parallel calls, each with a focused part of the record (contact
outcome and next step; commercial outcome, blockers and objections; the
account's 9 vertical fields), plus topic status and event type. Score both with
the same model, thinking level and answer key, and keep the better one.

Acceptance criteria:
- Option B runs through the same `evals/extract_eval` runner (same scorer and judge).
- A comparison table from the runs' own files (golden, top-up, synthetic
  separately): topic status, event type, faithfulness, P1 and all-field
  recall, invented-value rate, cost per 1,000 notes, median and p95 latency.
- Option B's records are checked for consistency across calls.
- A written decision with the numbers, agreed with the architect; the losing
  option's code is removed.

Depends on AIML-2929. Proposal change 2, question 9.

### AIML-3004 Business-rule derived dispositions (5)

Disposition codes stop being a model choice. The model captures the facts
(U-02 contact outcome, U-04 commercial outcome, U-06 objection and
competitor); if a per-topic code is still needed downstream, Python derives it
with a business-owned mapping (e.g. U-04 "order placed" → 2, U-06 "pricing" →
8, no match → 99). If no code is needed, the codes are dropped instead.

Acceptance criteria:
- The business answer to "is a per-topic code needed?" is recorded first.
- The mapping lives in reference data (S-08), not in code or the prompt, and
  adds the missing outcomes (quote created, no contact).
- No disposition instructions or cue words remain in any prompt.
- Unit tests cover every mapping row, the 99 fallback, and contradictory facts.
- Disposition is scored on the golden set from the derived code.

Open question: does Salesforce or reporting need a per-topic code at all
(proposal question 3)? Depends on AIML-2929. Proposal change 4.

## Phase 2: our code runs the conversation (26 points)

Done when scripted conversations pass in text mode through the harness.

### S-01 Dialogue steps in our code, with `extract()` in the live flow (8)

Replace the model-driven save flow with dialogue steps kept in the Agent
Engine session state: LISTENING → EXTRACTING → ASKING_ABOUT_TOPIC →
READING_BACK → WAITING_FOR_YES → SAVING → DONE. Live keeps the voice and gets
one tool, `dictation_done()`; our code runs `extract()` on the transcript.
`behavioral_rules.yaml` is cut down to conversation behaviour.

Acceptance criteria:
- Saving is reachable only from WAITING_FOR_YES, through a reply after the
  latest readback; a correction forces a new readback.
- An unmentioned planned topic triggers one question, driven by topic status.
- Step and draft are in session state; a restart resumes.
- Extraction rules are gone from the Live prompt; the Live agent has one tool.
- Scripted conversations (happy path, skipped topic, correction, no reply)
  pass in the harness.

Depends on AIML-2929, AIML-3003. Proposal changes 1, 5.

### S-02 `interpret()`: classify the rep's reply after a readback (5)

A text Gemini call with a fixed schema classifies the reply: confirm,
correction, skip or unclear.

Acceptance criteria:
- A labelled set of at least 100 confirmation replies is added to the eval.
- A false confirm is the gating metric, with a target agreed before building.
- No reply within the timeout: one reminder, then the notes stay unsaved and
  the rep is told.

Depends on S-01. Proposal change 5.

### S-03 Failure handling and non-blocking Google clients (5)

If `extract()`, `interpret()`, Model Armor or Pub/Sub fails: one retry with
backoff, then a typed error and a fixed spoken line. Every Google client is
created and authenticated at startup; token refresh never blocks the event
loop.

Acceptance criteria:
- Each failing dependency has a test: one retry, then the error and the line.
- Transcript and draft stay in session state after a failure.
- An unscreened record is never published (test).
- No auth pause on the event loop, checked in a trace.

Depends on S-01. Proposal change 12. Related AIML-2651.

### S-04 Retire the model-driven save machinery (3)

Remove `turn_guard.py`, the commit watchdog, `stage_visit_notes` /
`commit_visit_notes`, `_normalize_topics`, the in-memory store and its prune
task, and the supersede gate. Keep the business rules and move
`test_notes_workflow_gates.py` with them.

Acceptance criteria:
- Removed modules and tools are gone; nothing imports them.
- The moved gate tests pass against the dialogue steps.
- A full harness run passes against the committed baseline.

Depends on S-01, S-02. Proposal change 5.

### S-05 Spike: decide end of dictation in our code (5)

Live sometimes answers with an empty turn instead of calling the tool
(measured: 1–3 notes per 90-case run, more when prompt wording changes). Try
starting extraction from our code when Live's turn ends.

Acceptance criteria:
- A prototype behind a flag, measured on the full harness.
- Empty-turn count and latency reported for both approaches.
- A written recommendation.

Depends on S-01. Proposal question 16.

## Phase 3: inputs, reference data, privacy, publishing (28 points)

Done when each session produces one de-identified record with CRM keys,
delivered to the client and Pub/Sub, surviving a restart.

### S-06 `POST /sessions` takes the inputs the record needs (5)

Account id, visit or event id, vertical, and planned topics as a JSON list
(registry id, or title when not in the registry). Rep identity from the
verified token. The session loads the universal fields plus the vertical's 9.

Acceptance criteria:
- `vertical` must be MH, HS, HL, IS, TR or IN (consumer → MH); unknown
  vertical or topic id rejected with a typed error.
- Titles with commas arrive intact.
- Rep id from the token; a path-supplied id is ignored.
- Campaign type is no longer an input.
- CRM keys are carried on the saved record.

Open question: which ids should the record carry so the consumer can attach
it (e.g. account id, Salesforce event id), and will the client send them
(question 7)? Depends on S-01. Proposal change 7.

### S-07 Topic ids, registry descriptions, one topic-status field (5)

Topics carry registry ids where they have one; status is one field
(unaddressed, skipped, discussed). Registry topics get their short
description; others are kept by title.

Acceptance criteria:
- Coverage by id or exact title, never substring.
- Exactly one record entry per planned topic.
- `extract()` gets every registry description; the eval confirms the score.

Depends on S-06, S-08. Proposal change 6.

### S-08 Reference data versioned in Cloud Storage (5)

Campaign topics with descriptions, the field catalog, event-type rules and the
disposition mapping (if kept), loaded at startup; each record stores the
versions used.

Acceptance criteria:
- New quarterly topics load without a deploy.
- The eval reads the same versions and names them in its report.
- A missing or malformed file stops startup with a clear error.

Open question: who sends us the new Campaign Topics export each quarter
(question 4)? Depends on nothing. Proposal change 13.

### S-09 Model Armor: screen the transcript, de-identify the record (5)

Screen the transcript before `extract()`; de-identify before publishing.
Business contact names stay; patient or resident identity never leaves.

Acceptance criteria:
- Screening and de-identify templates per environment, rule written down.
- Test notes with patient or resident names come out de-identified; business
  contact names kept.
- A screening failure follows S-03.

Decided: Live audio is not screened (the transcript is). De-identifying our
stored copy can be set up after the first release. Depends on S-01. Proposal
change 9.

### S-10 Publish the saved record to Pub/Sub, with our BigQuery copy (8)

On save: a `saved` event to the client, and the Pub/Sub topic `visit-records`
with a schema generated from `schemas.py`. A BigQuery subscription keeps our
copy; a dead-letter topic catches failures.

Acceptance criteria:
- One message per saved session, with CRM keys, record and reference versions.
- The Pub/Sub schema rejects a malformed record; it is generated from code.
- BigQuery receives every record with no code of ours in the path.
- The contract states the consumer dedupes on `session_id`.

Open question, to confirm: we plan to keep our own copy, kept minimal (a
BigQuery subscription on the topic, no code), for debugging, audit and growing
the eval set (question 5). Depends on S-06, S-09. Proposal change 8.

## Phase 4: client contract, harness, observability (20 points)

Done when the other team can build against the contract alone, and any
session can be traced end to end.

### S-11 Client contract and typed WebSocket events (5)

Typed events (`ready`, `transcript`, `agent_text`, `record_preview`, `saved`,
`error`) and typed error codes replace raw ADK events. The contract document
covers auth, session, audio, keep-alive, events, end of session and errors.

Acceptance criteria:
- The server emits only typed events, each with a documented schema.
- The contract covers what today's browser app does unwritten (half-duplex
  mic, barge-in, uplink drop rule, server-side close after `saved`).
- The other team confirms they can build from it.

Open question: will a backend service call our endpoint (Cloud Run IAM), or
reps' devices directly (question 10)? Depends on S-01, S-10. Proposal §4,
change 11. Related AIML-2962.

### S-12 Eval harness on the new events and session inputs (5)

Move `evals/agent_eval` from raw ADK events and `stage_visit_notes` calls to
the typed events and new session inputs; keep `extract()` scoring in the same
check.

Acceptance criteria:
- A full run scores end to end from typed events, same metrics and verdicts.
- "The agent never replied" is counted separately from a wrong answer.
- A baseline is re-exported on the new flow and committed.

Depends on S-11. Proposal change 14.

### S-13 Tracing, logging and cost per session (5)

Cloud Trace through ADK, Cloud Logging, Error Reporting, and a log sink to
BigQuery with tokens and cost per session. Remove the BigQuery analytics
plugin, its dependencies and DDL.

Acceptance criteria:
- One trace shows a whole session, including each model call and publish.
- A BigQuery view gives tokens and cost per session and per day.
- Added latency of the extra model calls measured against today.
- The plugin, `scripts/bigquery_*` and `config.py` are gone.

Depends on S-01. Proposal change 10.

### S-14 Remove the frontend and retired code; rewrite the README (3)

Remove `app/static/`, `/`, `/api/config`, `demo_assets/`, and scripts that
test removed code. Rewrite the README.

Acceptance criteria:
- Removed files are gone and tests pass.
- The README describes the service as it is.

Depends on S-11, S-12. Proposal change 11.

### AIML-2962 Web UI and WebSocket follow the session contract (2)

Interim fix while the browser app exists: the WebSocket takes only the ids in
its path, and planned topics come only from `POST /sessions`.

Acceptance criteria:
- The web UI creates the session first and connects with ids only.
- The `planned_topics` query parameter is gone from the WebSocket handler.

Depends on nothing. Superseded later by S-11, S-14.

## Phase 5: infrastructure and release gate (17 points)

Done when a release with an eval drop is blocked automatically.

### S-15 Infrastructure as code and three environments (8)

Terraform for Cloud Run (min/max 1 instance, 60-minute timeout), Artifact
Registry, Pub/Sub, BigQuery, Cloud Storage and Model Armor templates; one
least-privilege service account; dev, test and prod projects. Cloud Build
builds the image from `uv.lock`. Vertex only; Live in `us-central1`,
`extract()` on global if a 3.x model is chosen.

Acceptance criteria:
- `terraform apply` builds an environment from nothing.
- The image installs from `uv.lock` (today it runs `pip install .`).
- `GOOGLE_API_KEY` and `GOOGLE_GENAI_USE_VERTEXAI` are gone.
- Live API quotas checked against the expected number of reps.

Decided: `extract()` runs on the global endpoint (approved). Depends on
S-10. Proposal questions 12, 13.

### S-16 Our own Agent Engine instance per environment (3)

Acceptance criteria:
- Each environment has its own engine, id from configuration.
- Sessions created, resumed and read back on it (integration test).

The engines are provided by another team; this story wires our
configuration to them. Depends on S-15 and that team. Proposal question 14.

### S-17 Release gate: block a release when the eval drops (3)

Cloud Build runs the eval (quick on every change, full before a release);
REGRESSION or INVALID blocks the release.

Acceptance criteria:
- A deliberately broken prompt fails the gate in a test pipeline.
- The scorecard is attached to the build.
- Golden data is fetched at build time, never stored in the image or logs.

Depends on S-12, S-15, AIML-2957. Proposal change 14.

### AIML-2957 Golden-data tests in CI (3)

Acceptance criteria:
- CI fetches the key version named in the README; no data test skips.
- Bucket access is read-only, limited to CI's service account.

Depends on S-15.

## Later: audio evaluation (8 points)

### S-18 Tier 2 eval on real spoken recordings (8)

Collect real spoken visit notes (noise, accents, clipped speech, product
names), run them through Live's transcription and the full flow, and score
them with the same metrics.

Acceptance criteria:
- At least 30 recordings, with consent and agreed retention, outside the repo.
- An audio scorecard alongside the text one, run before each release.
- A report on transcription errors and their effect on the record.

Open question, to confirm: we plan to keep no raw audio from production
(the record comes from the transcript), and to collect the recordings for this
eval separately, with consent (question 8). Depends on S-12. Proposal change
14.
