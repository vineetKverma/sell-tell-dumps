# SellNTell: the story plan for the new architecture

Every story still needed to reach the design in `architecture-proposal-suresh.md`,
in the order they can be picked up: the ones already in Jira (epic AIML-2904)
and the ones still to create. This replaces the pick order in
`architecture-stories.md`.

"NEW" means the story is not in Jira yet. The S-nn numbers match
`architecture-stories.md` so the two documents can be read side by side.

## 1. Assumptions the plan is built on

Each open question from the proposal is settled here by the option the
proposal recommends. If one turns out wrong, only the story named next to it
changes.

| # | Assumption | Changes if wrong |
|---|---|---|
| A1 | **The caller is a backend service, not reps' devices.** It calls us with a Google ID token and is on the Cloud Run invoker list. It passes the rep id in `POST /sessions`; we trust it because only that service can call us. | S-06, S-11, AIML-3048 |
| A2 | **The client sends `account_id` (required) and `event_id` (optional: a visit may have no Salesforce event yet) in `POST /sessions`.** Both are opaque strings; we don't look them up in Salesforce. | S-06 |
| A3 | **The disposition code stays: one per discussed topic, picked by `extract()` and checked against the rep's words** (AIML-3004). Proposal change 4 (derive the code from the fields, or drop it) is replaced by this. | S-08 |
| A4 | **The managed log sink replaces the BigQuery analytics plugin.** S-13 checks this on dev before deleting the plugin. | S-13 |
| A5 | **The business sends the Campaign Topics export each quarter; we upload it with one command.** | S-08 |
| A6 | **We keep our own copy of every record** through a BigQuery subscription, with no code of ours in between. | S-10b |
| A7 | **Transcripts are kept 30 days** (sessions, logs, BigQuery), set as one Terraform variable. No raw audio is kept from production. | S-10b, S-15, S-18 |
| A8 | **Live audio is not screened by Model Armor; the transcript is.** | S-09 |
| A9 | **`extract()` runs on the global endpoint and Live runs in `us-central1`** (approved). | S-15 |
| A10 | **One Cloud Run instance**, so the in-process one-connection lock holds. | S-15 |

## 2. What was confusing, and how it's settled

| What | Settled as |
|---|---|
| `extract()` loads the field catalog and campaign registry from a folder only the eval passes; the app has no source for them | S-08 gives the app a source, and is placed before AIML-3116 |
| The catalog and the registry each have two loaders (`app/extraction/`, `evals/dataset/`) | S-08: one loader each, used by the app and the eval |
| AIML-3012 (`interpret()`) is in test, but the flow it plugs into doesn't exist | 3012 = the classifier and its labelled set; AIML-3117 wires it in and owns the no-reply timeout |
| AIML-3013 tests Model Armor and Pub/Sub failures that aren't built yet | 3013 covers `extract()`, `interpret()` and Google clients; S-09 and S-10a each carry their own failure criteria |
| AIML-2820 and AIML-2822 work on the plugin that S-13 removes | Both closed; S-13 carries the check that the log sink replaces the plugin |
| AIML-2962 fixes a browser app that S-14 deletes | Closed; its WebSocket change is in S-11 |
| AIML-2651 duplicates AIML-3013 | Closed |
| AIML-2845 is a bug in `app.js`, which is removed | Closed with S-14 |
| AIML-2697 (FAR demo hardening) was written for the old flow | Closed |
| AIML-2969 sits in this epic but is the MLOps Monitoring Dashboard's service accounts (done) | Out of this plan; SellNTell's own accounts are S-15a |
| S-15 overlaps AIML-3051 (staging and prod) | S-15 is Terraform and the image from `uv.lock`; 3051 applies it to staging and prod |
| AIML-2957 is 2 points in Jira, 3 in `architecture-stories.md`, and there is no CI pipeline | 2 points; it waits for S-15's Cloud Build |
| AIML-3054 counts disposition loss and needless reminders, both problems of the old flow: the Live model paraphrasing a planned label so the exact-match gate asks again (D-17, D-59), and codes lost in its tool calls | Closed. In the new flow topic labels are a schema enum, codes come from `extract()` (AIML-3004 already counts its 99 fallbacks), and the gate goes in AIML-3014. The part that still matters, a question about a topic the rep already discussed, is a counter in S-12 |
| Two versions of the proposal | `architecture-proposal-suresh.md` is the one; `architecture-proposal.md` goes to the archive |
| `sell_n_tell_architecture.md` describes the old design as current | Moves to the archive, titled as the agent being replaced |
| `stories-after-guided-removal.md`, `plan-after-implicit-decision.md`, `PR5-followup-stories.md`, `note-2698-story-points.md` plan for the old flow | Move to `docs/archive/`; none of their stories are in this plan |
| `architecture-stories.md` still shows S-01 as one 8-point story | Gets one line at the top: "Order and current scope: `story-order.md`" |
| `HANDOFF.md` lists AIML-2929 both as open and as merged | Its ticket table points to this document |
| `scripts/` mixes old-flow tests, a committed test output and the plugin's DDL | Removed by S-13 (plugin) and S-14 (the rest) |

## 3. The order

A story starts when everything in "Needs" is done. Stories in the same wave
can run in parallel.

| Wave | Story | Pts | Owner | Needs |
|---|---|---|---|---|
| 0 | AIML-3152 `extract()` follow-up | 5 | Vineet (in dev) | — |
| 1 | AIML-3011 Dialogue steps in session state | 3 | Vineet | — |
| 1 | NEW S-08 Reference data in Cloud Storage | 5 | | — |
| 1 | AIML-3012 `interpret()` | 5 | Dharun (in test) | — |
| 1 | AIML-3013 Failure handling, non-blocking Google clients | 5 | Dharun | — |
| 1 | AIML-3037 Python 3.11+ | 2 | Vineet | — |
| 1 | NEW S-15a SellNTell service accounts | 3 | | — |
| 2 | AIML-3116 Live agent with one tool, `extract()` in the flow | 3 | Vineet | 3011, S-08, 3152 |
| 2 | NEW S-06 `POST /sessions` inputs | 5 | | 3011 |
| 3 | AIML-3117 Save gate, corrections, harness conversations | 3 | Vineet | 3116, 3012 |
| 3 | NEW S-09 Model Armor | 5 | | 3116 |
| 3 | NEW S-13 Tracing, logging, cost; plugin removed | 5 | | 3116 |
| 3 | NEW S-07 Topic ids, one status field | 3 | | S-06, S-08 |
| 3 | NEW S-05 Spike: end of dictation in our code | 5 | | 3116 |
| 4 | AIML-3014 Retire the model-driven save machinery | 3 | Dharun | 3117 |
| 4 | NEW S-10a Publish to Pub/Sub | 5 | | 3117, S-06, S-09 |
| 4 | NEW S-10b BigQuery copy and dead-letter topic | 3 | | S-10a |
| 5 | NEW S-11 Client contract and typed events | 5 | | S-10a |
| 5 | NEW S-15 Terraform and the image from `uv.lock` | 5 | | S-15a, 3037, S-09, S-10a |
| 6 | NEW S-12 Harness on typed events | 5 | | S-11 |
| 6 | AIML-3048 External exposure and QA | 3 | Sainitheesh | S-11 |
| 6 | AIML-3051 Staging and prod | 5 | Sainitheesh | S-15 |
| 7 | NEW S-16 Own Agent Engine per environment | 3 | | 3051, the engine team |
| 7 | AIML-2957 Golden-data tests in CI | 2 | Vineet | S-15 |
| 7 | NEW S-14 Remove the frontend and retired code | 3 | | S-11, S-12, 3014 |
| 8 | NEW S-17 Release gate | 3 | | S-12, S-15, 2957 |
| Later | NEW S-18a Collect spoken recordings | 3 | | — (consent first) |
| Later | NEW S-18b Audio eval scorecard | 5 | | S-12, S-18a |

**Longest chain of dependent stories:** 3152 → (3011 + S-08) → 3116 → 3117 →
S-10a → S-11 → S-12 → S-17.

**Totals:** 11 stories in Jira (39 points) stay; 17 to create (71 points);
close AIML-2820, 2822, 2962, 3054, 2651, 2845, 2697. AIML-2969 is done and
belongs to the MLOps dashboard, not this plan.

## 4. Stories already in Jira

### AIML-3152 `extract()` follow-up: evidence by sentence number (5) · wave 0

The model cites sentence numbers and our code copies the words; topic,
event-type and quote rules follow the business's four answers; answer key v1.5.

- Golden runs on key v1.5 recorded in the decisions log (done: D-82).
- The agent's quote cue limited to a quote given for that topic, with three
  full agent runs inside the baseline's limit (D-83).
- The agent baseline re-exported on key v1.5.
- PR approved and merged.

### AIML-3011 Dialogue steps kept in session state (3) · wave 1

The step machine (LISTENING → EXTRACTING → ASKING_ABOUT_TOPIC → READING_BACK
→ WAITING_FOR_YES → SAVING → DONE), stored in Agent Engine session state. Not
used by the live flow yet.

- Every allowed step change is in one table; any other change raises.
- Step and draft are written to session state on every change.
- After a restart the session resumes at the same step with the same draft
  (test).
- Unit tests cover each step change.

### AIML-3012 `interpret()`: classify the rep's reply after a read-back (5) · wave 1

A text Gemini call with a fixed schema: confirm, correction, skip or unclear.
Built and scored on its own; AIML-3117 wires it into the steps.

- A labelled set of at least 100 replies (yes, "yeah", "save it", "yes but
  change X", noise, empty) is in the eval.
- False-confirm rate is the gating metric, with its target written down
  before tuning.
- An empty or noise transcript is "unclear", never "confirm" (test).
- One command scores it, in the harness's scorecard format.

### AIML-3013 Failure handling and non-blocking Google clients (5) · wave 1

`extract()` and `interpret()` fail: one retry with backoff, then a typed error
and a fixed spoken line ("couldn't save, your notes are kept"). Google clients
are built and authenticated at startup.

- A test per failing call: one retry, then the typed error and the line.
- Transcript and draft stay in session state after a failure.
- Token refresh never blocks the event loop (shown in a trace).
- No Google client is created on a request path.

### AIML-3037 Move the runtime to Python 3.11+ (2) · wave 1

- `requires-python` is `>=3.11`, changed with uv on the dev machine.
- The Dockerfile's base image is 3.11 or later.
- All tests and one quick harness run pass on the new runtime.

### AIML-3116 Live agent with one tool, `extract()` in the flow (3) · wave 2

Live keeps the voice and gets one tool, `dictation_done()`, with no
arguments. Our code runs `extract()` on the transcript, builds the read-back
and the topic question, and moves the steps.

- The Live agent has exactly one tool.
- Extraction rules are gone from the Live prompt; `behavioral_rules.yaml`
  keeps conversation behaviour only.
- An unmentioned planned topic triggers one question, driven by topic status.
- The silence watchdog reads the current step instead of `turn_guard`; a
  check-in while a topic question is pending repeats the question.
- A happy-path conversation passes in the harness in text mode.

### AIML-3117 Save gate, corrections and harness conversations (3) · wave 3

`interpret()` wired into WAITING_FOR_YES. Saving happens only from there,
on a reply after the latest read-back.

- A correction runs `extract()` again and forces a new read-back.
- No reply within the timeout: one reminder, then the notes stay unsaved and
  the rep is told.
- The gate tests from `test_notes_workflow_gates.py` pass against the steps.
- Harness conversations pass: happy path, skipped topic, correction, no reply.

### AIML-3014 Retire the model-driven save machinery (3) · wave 4

Remove `turn_guard.py`, the commit and read-back watchdogs,
`stage_visit_notes` / `commit_visit_notes`, `_normalize_topics`, the in-memory
store and its prune task, and the supersede gate.

- The removed modules and tools are gone, and nothing imports them.
- Business rules still in use move next to the steps, with their tests.
- A full harness run passes against the committed baseline.

### AIML-3048 Sell 'n Tell external exposure and QA (3) · wave 6

The calling service reaches us through the load balancer, authenticated with
an ID token (A1).

- Only the calling service's account is on the invoker list.
- A QA run from outside our project creates a session, dictates, and gets
  `saved` over the WebSocket.
- An unauthenticated or unknown caller gets 401/403, never a session.

### AIML-3051 Sell 'n Tell staging and prod (5) · wave 6

- Staging and prod built from S-15's Terraform, one apply each.
- Each has its own bucket, topic, Model Armor templates and service account.
- A deploy to staging runs the quick eval before it is promoted to prod.

### AIML-2957 Golden-data tests in CI (2) · wave 7

- CI fetches the key version named in the README; no data test skips.
- Bucket access is read-only, for CI's service account (S-15a) only.

## 5. Stories to create

### S-08 Reference data versioned in Cloud Storage (5) · wave 1

The campaign registry with descriptions, the field catalog, the event-type
rules and `dispositions.yaml` live in a versioned bucket and load at startup.

- The app loads all four from the bucket; a missing or malformed file stops
  startup with a clear error.
- One loader per file, used by both the app and the eval.
- A new quarterly export is uploaded with one command and loads without a
  deploy (A5).
- Each record and each eval report names the versions used.

### S-15a SellNTell service accounts (3) · wave 1

One least-privilege runtime account for the service and one for CI, set up
in NP first, then the same in prod.

- The runtime account has only what the service uses: Vertex AI, Agent
  Engine, Pub/Sub publisher, Model Armor, reading the reference-data bucket,
  and writing logs and traces.
- The CI account reads the eval bucket and nothing else in data.
- No key files; Cloud Run and Cloud Build run as the accounts directly.
- The Compute Engine default account is no longer used by the service.

### S-06 `POST /sessions` takes the inputs the record needs (5) · wave 2

`account_id`, optional `event_id` (A2), `vertical`, planned topics as a JSON
list (registry id or title), and the rep id from the calling service (A1).

- `vertical` must be MH, HS, HL, IS, TR or IN (consumer → MH); an unknown
  vertical or topic id gets a typed error.
- Titles with commas arrive intact.
- Campaign type is no longer an input; the path's `user_id` is ignored.
- The session loads the universal fields plus the vertical's 9.
- The CRM keys are kept in session state and carried on the saved record.

### S-09 Model Armor: screen the transcript, de-identify the record (5) · wave 3

- The transcript is screened before `extract()`; a blocked transcript gets a
  typed error and the fixed line.
- The record is de-identified before publish: business contact names kept,
  patient or resident identity removed (test notes for both).
- Templates per environment, with the rule written down.
- Model Armor down: one retry, then the error; an unscreened record is never
  published (test).

### S-13 Tracing, logging and cost per session; plugin removed (5) · wave 3

- One Cloud Trace shows a whole session, each model call and the publish.
- A log sink to BigQuery, with a view of tokens and cost per session and day.
- Checked on dev: the sink carries everything the plugin did (A4).
- `app/analytics.py`, its wiring in `main.py` and `scripts/bigquery_*` are
  removed; `config.py` stays for the watchdog.
- The added latency of the extra model calls is measured against today.

### S-07 Topic ids and one topic-status field (3) · wave 3

- Planned topics carry their registry id from the session to the record.
- Status is one field: unaddressed, skipped or discussed.
- Exactly one entry per planned topic; matching by id or exact title, never
  substring (`_topic_matches` goes).
- The `extract()` eval confirms the score is unchanged.

### S-05 Spike: decide end of dictation in our code (5) · wave 3

Live sometimes answers with an empty turn instead of calling the tool. Try
starting extraction from our code when Live's turn ends.

- A prototype behind a flag, measured on the full harness.
- Empty-turn count and latency for both approaches.
- A written recommendation, including whether the silence watchdog can go.

### S-10a Publish the saved record to Pub/Sub (5) · wave 4

- On save, a `saved` event to the client and one message on `visit-records`
  with the CRM keys, the record and the reference versions.
- The Pub/Sub schema is generated from `schemas.py` and rejects a malformed
  record.
- The contract says the consumer dedupes on `session_id`.
- Publish fails: one retry, then a typed error and the fixed line; the draft
  stays in session state.

### S-10b Our BigQuery copy and the dead-letter topic (3) · wave 4

- A BigQuery subscription receives every record, with no code of ours (A6).
- A dead-letter topic catches failed deliveries, with an alert.
- Retention set from the one Terraform variable (A7).

### S-11 Client contract and typed WebSocket events (5) · wave 5

- The server sends only typed events (`ready`, `transcript`, `agent_text`,
  `record_preview`, `saved`, `error`), each with a schema;
  `instruction_for_model` and raw ADK events never reach the client.
- The WebSocket takes only ids in its path; the `planned_topics` query
  parameter is gone.
- An unknown or another rep's session gets a typed error, not a dropped
  socket.
- The contract document covers auth (A1), session, audio (half-duplex,
  barge-in, the uplink drop rule), keep-alive, events, end of session and
  error codes.
- The other team confirms they can build from it.

### S-15 Terraform and the image from `uv.lock` (5) · wave 5

Terraform for Cloud Run (one instance, 60-minute timeout), Artifact Registry,
Pub/Sub, BigQuery, Cloud Storage and Model Armor templates, using S-15a's
accounts. Cloud Build builds the image.

- `terraform apply` builds an environment from nothing.
- The image installs from `uv.lock` (today `pip install .`).
- `GOOGLE_API_KEY` and `GOOGLE_GENAI_USE_VERTEXAI` are gone; Live in
  `us-central1`, `extract()` global (A9).
- Live API quotas checked against the expected number of reps.

### S-12 Eval harness on typed events and session inputs (5) · wave 6

- `evals/agent_eval` drives the new session inputs and reads typed events,
  with the same metrics and verdicts.
- A new counter: questions asked about a planned topic the rep had already
  discussed (replaces AIML-3054).
- "The agent never replied" is counted apart from a wrong answer.
- `extract()` scoring stays in the same check.
- A baseline re-exported on the new flow and committed.

### S-16 Our own Agent Engine per environment (3) · wave 7

- Each environment has its own engine, its id from configuration.
- Sessions are created, resumed and read back on it (integration test).

### S-14 Remove the frontend and retired code; rewrite the README (3) · wave 7

- `app/static/`, the `/` and `/api/config` routes, and `demo_assets/` are
  gone.
- The scripts for the old flow are gone: `ws_smoke_test.py`,
  `test_pr_review_fixes.py`, `test_aiml_2743_session_lifecycle.py`,
  `smoke_test_output.txt`.
- The tests pass, and the README describes the service as it is.

### S-17 Release gate: block a release when the eval drops (3) · wave 8

- Cloud Build runs the quick eval on every change and the full one before a
  release; REGRESSION or INVALID blocks it.
- A deliberately broken prompt fails the gate in a test pipeline.
- The scorecard is attached to the build; golden data never enters the image
  or logs.

### S-18a Collect spoken recordings for the audio eval (3) · later

- At least 30 real spoken visit notes (noise, accents, clipped speech,
  product names), with consent.
- Stored outside the repo with agreed retention, labelled with the same key
  format.

### S-18b Audio eval scorecard (5) · later

- The recordings run through Live's transcription and the full flow, scored
  with the same metrics.
- An audio scorecard alongside the text one, run before each release.
- A report on transcription errors and their effect on the record.

## 6. Housekeeping (not a story)

- Move to `docs/archive/`: `architecture-proposal.md`,
  `stories-after-guided-removal.md`, `plan-after-implicit-decision.md`,
  `PR5-followup-stories.md`, `note-2698-story-points.md`, and
  `sell_n_tell_architecture.md` (retitled as the agent being replaced).
- One line at the top of `architecture-stories.md` and in `HANDOFF.md`'s
  ticket table: "Order and current scope: `story-order.md`".
- In Jira: close AIML-2820, 2822, 2962, 3054, 2651, 2845, 2697; create the 17
  NEW stories; apply the scope changes to AIML-3012, 3013 and 3117 as written
  in §4.

## 7. Jira numbers for the new stories

Filled in once created; every "NEW S-nn" above is then replaced by its number.

| Plan id | Title | Jira |
|---|---|---|
| S-08 | Reference data versioned in Cloud Storage | |
| S-15a | SellNTell service accounts | |
| S-06 | `POST /sessions` takes the inputs the record needs | |
| S-09 | Model Armor: screen the transcript, de-identify the record | |
| S-13 | Tracing, logging and cost per session; plugin removed | |
| S-07 | Topic ids and one topic-status field | |
| S-05 | Spike: decide end of dictation in our code | |
| S-10a | Publish the saved record to Pub/Sub | |
| S-10b | Our BigQuery copy and the dead-letter topic | |
| S-11 | Client contract and typed WebSocket events | |
| S-15 | Terraform and the image from `uv.lock` | |
| S-12 | Eval harness on typed events and session inputs | |
| S-16 | Our own Agent Engine per environment | |
| S-14 | Remove the frontend and retired code; rewrite the README | |
| S-17 | Release gate: block a release when the eval drops | |
| S-18a | Collect spoken recordings for the audio eval | |
| S-18b | Audio eval scorecard | |
