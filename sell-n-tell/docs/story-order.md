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
| A1 | **The caller is a backend service, not reps' devices.** It calls us with a Google ID token and is on the Cloud Run invoker list. It passes the rep id in `POST /api/sessions`; we trust it because only that service can call us. | S-06, S-11, AIML-3048 |
| A2 | **The client sends `account_id` (required) and `event_id` (optional: a visit may have no Salesforce event yet) in `POST /api/sessions`.** Both are opaque strings; we don't look them up in Salesforce. | S-06 |
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
| 2 | NEW S-06 `POST /api/sessions` inputs | 5 | | 3011 |
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

Each story below is written to be pasted into Jira as it stands: title,
points, description, dependencies and acceptance criteria. "A1"–"A10" refer
to the assumptions in §1.

---

### S-08 · Reference data versioned in Cloud Storage · 5 pts

**Wave 1 · Depends on:** nothing · **Unblocks:** AIML-3116, S-07

**Description**

`extract()` needs four pieces of reference data: the campaign registry
(titles and short descriptions), the must-capture field catalog (11 universal
fields plus 9 per vertical), the event-type rules, and the disposition
registry (`dispositions.yaml`, kept since AIML-3004). Today the app has no
runtime source for the first two: `catalog.load_catalog(folder)` and
`campaigns.load_registry(path)` read files that only the eval passes in from
its own git-ignored folders. So `extract()` cannot run inside the deployed
service. The catalog and the registry also each have a second loader in
`evals/dataset/`, which can drift from the app's.

This story moves all four into a versioned Cloud Storage bucket per
environment, with one loader per file that the app and the eval share. The
app loads them at startup and keeps them in memory. Each saved record and
each eval report names the versions it used, so a score can always be tied
to the data behind it. New campaign topics arrive every quarter (A5); a
new version is uploaded with one command and needs no code change or new
image.

Out of scope: editing the content of the registry or the catalog.

**Acceptance criteria**

1. The bucket holds the four files under a version, plus a small manifest
   naming the current version of each.
2. At startup the app loads all four through the manifest. A missing,
   unreadable or malformed file stops startup with an error naming the file.
3. There is one loader per file, used by both the app and the eval; the
   duplicates in `evals/dataset/` are removed.
4. One command validates a new file and uploads it as the next version;
   a file that fails validation is not uploaded.
5. The app picks up a new version on its next start, with the same image.
6. Every saved record and every eval report carries the four version ids.
7. Unit tests cover loading, a malformed file, and the version ids on the
   record.

---

### S-15a · SellNTell service accounts · 3 pts

**Wave 1 · Depends on:** nothing · **Unblocks:** S-15, AIML-2957

**Description**

The service runs today with broad default credentials, and CI has no
identity of its own. This story creates two dedicated accounts, set up and
tested in NP first, then repeated in prod: a runtime account the Cloud Run
service runs as, and a CI account Cloud Build runs as. Each gets only what it
uses. The runtime account must not be able to read the eval bucket (it holds
customer notes); the CI account must not be able to touch production data.

**Acceptance criteria**

1. A runtime account exists in NP with only: Vertex AI user, Agent Engine
   session access, Pub/Sub publisher on `visit-records`, Model Armor user,
   read on the reference-data bucket, and log and trace writer.
2. A CI account exists in NP with read on the eval bucket, Artifact Registry
   writer, and the right to deploy the service; nothing else on data.
3. The Cloud Run service runs as the runtime account; the Compute Engine
   default account is no longer used.
4. No key files are created; both accounts are used directly by Cloud Run
   and Cloud Build.
5. The deployer has `iam.serviceAccountUser` on these two accounts only.
6. The same accounts and grants exist in prod.
7. The grants are written down in the repo, next to the Terraform that
   S-15 adds.

---

### S-06 · `POST /api/sessions` takes the inputs the record needs · 5 pts

**Wave 2 · Depends on:** AIML-3011 · **Unblocks:** S-07, S-10a

**Description**

Today a session is created with planned topic titles and a campaign type,
and the rep's id comes from the WebSocket path, chosen by the client. The
consumer cannot attach a saved record to anything in Salesforce, because the
only id on it is our `session_id`. And `extract()` cannot load the right 9
vertical fields, because the vertical is not an input.

This story changes the session's inputs to what the record needs:
`account_id` (required), `event_id` (optional, a visit may not have a
Salesforce event yet; A2), `vertical`, `rep_id` from the calling service
(A1), and planned topics as a JSON list where each entry is a registry id or,
for a topic not in the registry, a title. All of it is kept in session
state, so a restart keeps it. The session loads the universal fields plus
that vertical's 9 from the reference data. Campaign type is no longer an
input.

Out of scope: checking the CRM ids against Salesforce.

**Acceptance criteria**

1. The request takes `account_id`, `event_id` (optional), `vertical`,
   `rep_id` and `planned_topics: [{id} | {title}]`; the response is the
   `session_id`.
2. `vertical` must be MH, HS, HL, IS, TR or IN, with consumer mapped to MH.
   An unknown vertical, an unknown topic id or a missing `account_id` gets a
   typed 4xx error.
3. A topic title containing commas arrives intact (test with a real one).
4. `campaign_type` is gone from the request and the code; the `user_id` in
   the WebSocket path is ignored in favour of the session's `rep_id`.
5. The inputs are in session state and survive a restart (test).
6. The saved record carries `account_id`, `event_id`, `rep_id` and
   `vertical`.
7. The eval harness and the browser client create sessions with the new
   request.

---

### S-09 · Model Armor: screen the transcript, de-identify the record · 5 pts

**Wave 3 · Depends on:** AIML-3116 · **Unblocks:** S-10a

**Description**

The dictation is untrusted input to a model, and healthcare visit notes can
name patients or residents. Two Model Armor steps go into the flow. Before
`extract()`, the transcript is screened (prompt injection, malicious
content); a blocked transcript is not extracted and the rep is told. Before
the record is published, it is de-identified: business contact names (field
U-01) stay, because the consumer needs them; patient or resident identity is
removed. Live audio is not screened, only its transcript (A8). Model Armor
failures follow the AIML-3013 pattern.

**Acceptance criteria**

1. Screening and de-identify templates exist per environment, and the
   de-identify rule (what stays, what goes) is written down.
2. Every transcript is screened before `extract()`; a blocked one stops
   extraction with a typed error and the fixed spoken line.
3. Every record is de-identified before publish. Test notes with patient or
   resident names come out without them; business contact names are kept.
4. Model Armor unreachable: one retry with backoff, then a typed error and
   the fixed line; the transcript stays in session state.
5. A record that was not screened and de-identified is never published
   (test).
6. The added latency per session is measured and reported.

---

### S-13 · Tracing, logging and cost per session; analytics plugin removed · 5 pts

**Wave 3 · Depends on:** AIML-3116 · **Replaces:** AIML-2820, AIML-2822

**Description**

Session telemetry today comes from ADK's BigQuery analytics plugin
(`app/analytics.py`), which is off by default because it added about 40 s to
every connect. The new flow adds model calls of its own (`extract()`,
`interpret()`), so we need to see a whole session end to end and know what
each one costs. This story turns on Cloud Trace through ADK's tracing, Cloud
Logging and Error Reporting, and adds a log sink to BigQuery with token usage
and cost per session. Once it is checked on dev that the sink carries what
the plugin did (A4), the plugin and its DDL are removed.

**Acceptance criteria**

1. One trace shows a whole session: each Live turn, each `extract()` and
   `interpret()` call, Model Armor, and the publish.
2. Each model call logs its tokens and cost; a BigQuery view gives tokens
   and cost per session and per day.
3. Errors appear in Error Reporting with the session id.
4. Checked on dev and written down: the sink carries every field the plugin
   gave that we use.
5. `app/analytics.py`, its wiring in `main.py`, its dependencies and
   `scripts/bigquery_*` are removed; `config.py` stays for the silence
   watchdog.
6. The latency the new model calls add is measured against today's flow.
7. No transcript text is logged in full (log its length only).

---

### S-07 · Topic ids and one topic-status field · 3 pts

**Wave 3 · Depends on:** S-06, S-08

**Description**

A planned topic should keep its registry id from the session to the saved
record, so the consumer can match it without comparing titles, and its
status should be one field instead of being inferred from several. A topic
in the registry is sent to `extract()` with its description; a topic not in
the registry is kept by its title (about a third of real topic mentions).

**Acceptance criteria**

1. Each planned topic carries its registry id, or its title when it has
   none, from the session through `extract()` to the record.
2. Each topic's status is one field: `unaddressed`, `skipped` or
   `discussed`.
3. The record has exactly one entry per planned topic.
4. A topic is matched by id or exact title only, never by substring.
5. The `extract()` eval on the golden set scores no worse than before the
   change.

---

### S-05 · Spike: decide end of dictation in our code · 5 pts

**Wave 3 · Depends on:** AIML-3116

**Description**

In the new flow, Live calls `dictation_done()` when the rep has finished.
Sometimes it answers with an empty turn instead (1–3 notes per 90-case run,
more when the prompt wording changes), and the silence watchdog has to
recover. This spike tries starting extraction from our code when Live's turn
ends, and measures whether it is more reliable. Time-boxed; the outcome is a
recommendation, not production code.

**Acceptance criteria**

1. A prototype behind a flag starts extraction from our code at the end of
   Live's turn.
2. Both approaches run on the full harness; empty turns, missed
   dictations and time to the read-back are reported for each.
3. A written recommendation, with the numbers, says which to keep and
   whether the silence watchdog can go.
4. The decision goes in the decisions log.

---

### S-10a · Publish the saved record to Pub/Sub · 5 pts

**Wave 4 · Depends on:** AIML-3117, S-06, S-09 · **Unblocks:** S-10b, S-11

**Description**

A saved record today exists only in session state; nothing is produced that
the consumer can read. On save, the record goes to two places: a `saved`
event to the client over the WebSocket, so the rep hears it is done, and a
message on the Pub/Sub topic `visit-records`, so the consumer gets it
durably, with Pub/Sub's own retries. The topic has a schema generated from
`schemas.py`, which is the contract with the consumer. A message can be
delivered more than once, so the consumer dedupes on `session_id`.

**Acceptance criteria**

1. One message per saved session, with the CRM keys, the record, and the
   reference-data versions.
2. The Pub/Sub schema is generated from `schemas.py` by a command, and the
   topic rejects a malformed message (test).
3. The client gets `saved` only after the publish succeeds.
4. Publish fails: one retry with backoff, then a typed error and the fixed
   spoken line; the record stays in session state.
5. The contract states that the consumer dedupes on `session_id`.
6. An integration test publishes a record and reads it back from a test
   subscription.

---

### S-10b · Our BigQuery copy and the dead-letter topic · 3 pts

**Wave 4 · Depends on:** S-10a

**Description**

We keep our own copy of every record (A6) for debugging, audit and growing
the eval set, without writing any code for it: a BigQuery subscription on
`visit-records` writes each message to a table. Messages that cannot be
delivered go to a dead-letter topic with an alert, so none is lost silently.

**Acceptance criteria**

1. A BigQuery subscription writes every message on `visit-records` to a
   table, with no code of ours in the path.
2. A dead-letter topic receives messages that fail delivery, and an alert
   fires when one arrives.
3. The table's retention is set from the one retention variable (A7).
4. A test record appears in the table after a publish.

---

### S-11 · Client contract and typed WebSocket events · 5 pts

**Wave 5 · Depends on:** S-10a · **Replaces:** AIML-2962

**Description**

The client will be built by another team, and today it would have to read
raw ADK events, including `instruction_for_model` text meant only for the
model. Our browser app also does things nobody has written down: half-duplex
mic, barge-in, dropping audio when the uplink falls behind, closing the
socket after a save. This story replaces the raw events with a small typed
set and writes the contract document the other team builds against. It also
takes over the WebSocket part of AIML-2962: the socket takes only ids in its
path.

**Acceptance criteria**

1. The server sends only these events, each with a JSON schema: `ready`,
   `transcript`, `agent_text`, `record_preview`, `saved`, `error`.
2. `instruction_for_model` and raw ADK events never reach the client (test).
3. The WebSocket takes only ids in its path; the `planned_topics` query
   parameter is gone.
4. An unknown session, or a session that belongs to another rep, gets a
   typed error and a clean close, not a dropped socket.
5. Error codes are typed (`session_busy`, `not_found`, `save_failed`, …),
   each with retry advice.
6. The contract document covers: auth (A1), session creation, audio format
   up and down, half-duplex and barge-in, the uplink drop rule, keep-alive,
   the time limit, every event, end of session, and every error code.
7. The other team confirms they can build a client from the document alone.

---

### S-15 · Terraform and the image from `uv.lock` · 5 pts

**Wave 5 · Depends on:** S-15a, AIML-3037, S-09, S-10a · **Unblocks:** AIML-3051, AIML-2957, S-17

**Description**

Environments are built by hand today, and the Dockerfile installs with
`pip install .`, which ignores `uv.lock`, so the image can carry versions
nobody tested. This story writes the service and everything it uses as
Terraform: Cloud Run (one instance, A10; 60-minute timeout), Artifact
Registry, the Pub/Sub topic and subscriptions, BigQuery, the reference-data
bucket and the Model Armor templates, using S-15a's accounts. Cloud Build
builds the image from `uv.lock`. Vertex only: Live in `us-central1`,
`extract()` on the global endpoint (A9). AIML-3051 then applies it to staging
and prod.

**Acceptance criteria**

1. `terraform apply` builds a working environment from an empty project.
2. The image installs exactly what `uv.lock` pins.
3. `GOOGLE_API_KEY` and `GOOGLE_GENAI_USE_VERTEXAI` handling is removed
   from the code and the config.
4. Retention is one variable, used by every store (A7).
5. Live API quotas are checked against the expected number of reps, and
   the figure is written down.
6. The README says how to build an environment.

---

### S-12 · Eval harness on typed events and session inputs · 5 pts

**Wave 6 · Depends on:** S-11 · **Unblocks:** S-14, S-17, S-18b

**Description**

The agent harness (`evals/agent_eval`) drives today's app: it creates a
session with topic titles and a campaign type, reads raw ADK events, and
scores the arguments of the last `stage_visit_notes` call. All three go away
in the new flow. This story moves the harness to the new session inputs and
the typed events, keeps the same metrics and verdicts, and keeps `extract()`
scoring in the same check. It also adds the one counter from AIML-3054 that
still matters.

**Acceptance criteria**

1. A full run creates sessions with the new inputs and scores end to end
   from the typed events.
2. The scorecard has the same metrics and verdicts as today.
3. A new counter: questions asked about a planned topic the rep had
   already discussed.
4. "The agent never replied" is counted apart from a wrong answer.
5. `extract()` scoring runs in the same check.
6. A baseline is exported on the new flow and committed.

---

### S-16 · Our own Agent Engine per environment · 3 pts

**Wave 7 · Depends on:** AIML-3051, the team that provides the engines

**Description**

Sessions are kept today in a borrowed Agent Engine instance. Each
environment needs its own, so that sessions, retention and access are
separate. The engines are provided by another team; this story wires our
configuration to them and proves they work.

**Acceptance criteria**

1. Each environment has its own engine, with its id set in configuration.
2. The app fails at startup with a clear error if the id is missing or
   wrong.
3. An integration test creates, resumes and reads back a session on each
   engine.
4. Session retention matches the retention variable (A7).

---

### S-14 · Remove the frontend and retired code; rewrite the README · 3 pts

**Wave 7 · Depends on:** S-11, S-12, AIML-3014 · **Closes:** AIML-2845

**Description**

Once the other team's client works against the contract, our browser app and
the code that only served it are dead weight. This story removes them and
rewrites the README to describe the service as it is.

**Acceptance criteria**

1. `app/static/`, `demo_assets/`, and the `/` and `/api/config` routes are
   removed.
2. Scripts that test the old flow are removed: `ws_smoke_test.py`,
   `test_pr_review_fixes.py`, `test_aiml_2743_session_lifecycle.py`,
   `smoke_test_output.txt`.
3. Nothing imports what was removed, and all tests pass.
4. The README covers what the service does, how to run it, the contract, the
   eval and the environments, and nothing that was removed.

---

### S-17 · Release gate: block a release when the eval drops · 3 pts

**Wave 8 · Depends on:** S-12, S-15, AIML-2957

**Description**

The eval only protects quality if a drop stops a release. Cloud Build runs
the quick eval on every change and the full eval before a release; a
REGRESSION or INVALID verdict blocks it. Golden data is customer notes, so
it is fetched at build time and never kept in the image, the logs or the
build artifacts.

**Acceptance criteria**

1. The quick eval runs on every change; the full eval runs before a release.
2. A REGRESSION or INVALID verdict fails the build and blocks the release.
3. A deliberately broken prompt fails the gate in a test pipeline.
4. The scorecard is attached to the build.
5. Golden data is fetched at build time and is absent from the image, logs
   and artifacts (checked).

---

### S-18a · Collect spoken recordings for the audio eval · 3 pts

**Later · Depends on:** consent agreed

**Description**

Text cases cannot catch mishearing. The audio eval needs real spoken visit
notes: background noise, accents, clipped speech, product names. None exist
today. This story collects them with consent, labels them in the golden
key's format, and stores them outside the repo with agreed retention. No
raw audio from production is used (A7).

**Acceptance criteria**

1. At least 30 recordings, covering every vertical, with written consent.
2. Each has an answer key in the golden set's format.
3. Stored in the eval bucket, outside the repo, with agreed retention.

---

### S-18b · Audio eval scorecard · 5 pts

**Later · Depends on:** S-12, S-18a

**Description**

Runs the recordings through Live's transcription and the full flow, and
scores the records with the same metrics as the text eval, so the effect of
mishearing on the record is measured.

**Acceptance criteria**

1. One command runs the recordings through the full flow and scores them.
2. An audio scorecard sits alongside the text one, and runs before each
   release.
3. A report on transcription errors and how each affected the record.

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
| S-06 | `POST /api/sessions` takes the inputs the record needs | |
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
