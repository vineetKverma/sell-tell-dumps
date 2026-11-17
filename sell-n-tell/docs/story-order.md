# SellNTell: the story plan for the new architecture

Every story still needed to reach the design in `architecture-proposal-suresh.md`,
in the order they can be picked up, all under epic AIML-2904. This replaces
the pick order in `architecture-stories.md`.

The epic holds the stories from the earlier pilot plan (AIML-2648 to 2663)
next to the new-architecture ones. Where two cover the same work, one is kept
and the other closed; where an older story is still open and fits a planned
one, it is reused with new text instead of creating another ticket.

## 1. Assumptions the plan is built on

Each open question from the proposal is settled by the option the proposal
recommends. If one turns out wrong, only the story named next to it changes.

| # | Assumption | Changes if wrong |
|---|---|---|
| A1 | **The caller is a backend service, not reps' devices.** It calls us with a Google ID token and is on the Cloud Run invoker list. It passes the rep id in `POST /api/sessions`; we trust it because only that service can call us. | AIML-3196, 2650, 2962, 3048 |
| A2 | **The client sends `account_id` (required) and `event_id` (optional: a visit may have no Salesforce event yet).** Both are opaque strings; we don't look them up in Salesforce. | AIML-3196 |
| A3 | **The disposition code stays: one per discussed topic, picked by `extract()` and checked against the rep's words** (AIML-3004). Proposal change 4 is replaced by this. | AIML-3195 |
| A4 | **The managed log sink replaces the BigQuery analytics plugin.** AIML-3198 checks this on dev before deleting the plugin. | AIML-3198 |
| A5 | **The business sends the Campaign Topics export each quarter; we upload it with one command.** | AIML-3195 |
| A6 | **We keep our own copy of every record** through a BigQuery subscription, with no code of ours in between. | AIML-2655 |
| A7 | **Transcripts are kept 30 days** (sessions, logs, BigQuery), set as one Terraform variable. No raw audio is kept from production. | AIML-2655, S-18 |
| A8 | **Live audio is not screened by Model Armor; the transcript is.** | AIML-3197 |
| A9 | **`extract()` runs on the global endpoint and Live runs in `us-central1`** (approved). | AIML-2655 |
| A10 | **One Cloud Run instance**, so the in-process one-connection lock holds. | AIML-3150, 2655, 2657 |
| A11 | **We don't write to Salesforce.** The record goes to Pub/Sub; the consumer team writes it to Salesforce. | AIML-2649 |

## 2. What can be closed or merged

Doing one story well removes the need for another. Each row says which
story absorbs the work.

| Close | Absorbed by | Why |
|---|---|---|
| AIML-2648 Real config registry integration | AIML-3195 | 3195 replaces the hard-coded config with versioned reference data, which is this story |
| AIML-2652 Observability: structured logging, tracing | AIML-3198 | Same scope; 3198 is the newer text and gains a structured-log criterion |
| AIML-2656 Deploy to staging + smoke test | AIML-3051 | 3051 builds staging and prod and runs the smoke check on each |
| AIML-2659 End-to-end integration testing (app ↔ backend) | AIML-3048 | 3048's QA run is the consumer's client against our service end to end |
| AIML-3037 Python 3.11+ | AIML-2654 | The base image changes in the same story that rebuilds the image; the `pyproject.toml` change rides along (made with uv on the dev machine) |
| AIML-2820, 2821, 2822 BigQuery analytics plugin | AIML-3198 | 3198 removes the plugin; its latency, warm-up and table setup stop mattering |
| AIML-2651 Error handling and resilience | AIML-3013 | Same scope, older text |
| AIML-2845 No-speech turns suppress agent speech | AIML-2962 | A browser-only bug; 2962 removes the browser app |
| AIML-2697 FAR demo hardening | — | Written for the old flow; nothing in the new plan needs it |

| Planned story | Reuses | Why |
|---|---|---|
| S-15a service accounts | AIML-2650 Auth & secrets hardening | Same concern: the identities the service and CI run as, and who may call us |
| S-10a publish the record | AIML-2649 Real Salesforce/CRM integration | Our part of reaching Salesforce is publishing to Pub/Sub (A11) |
| S-10b BigQuery copy, S-15 Terraform | AIML-2655 IaC provisioning (Terraform) | The BigQuery copy and dead-letter topic are infrastructure only, no code |
| S-15 image from `uv.lock` and Cloud Build | AIML-2654 Dockerize + CI/CD pipeline | Same scope |
| S-11 client contract, S-14 frontend removal | AIML-2962 Web UI and WebSocket follow the contract | Once events are typed, the browser app breaks; removing it in the same story avoids fixing it only to delete it |
| S-12 harness on typed events | AIML-3054 Scorecard counters | Its counters only matter on the new flow; the harness move is where they get built |
| S-16 own Agent Engine | AIML-3051 Staging and prod | Each environment's engine id is part of building the environment |
| S-17 release gate | AIML-2957 Golden-data tests in CI | The eval in CI and the gate on its verdict are one pipeline step |
| The rest of S-14 (old-flow scripts) | AIML-3014 | They test the machinery 3014 removes |

**Result:** 1 story left to create now (S-05) and one later (S-18), instead
of 12. 11 tickets closed.

### Doing these first shrinks later work

- **AIML-3150 (one instance on dev) now.** It closes the lock gap on dev
  today, and AIML-2655 only has to write the same setting into Terraform.
- **AIML-3195 before AIML-3116.** `extract()` reads its catalog and campaign
  registry from a folder that only the eval supplies; the running app has no
  source for them, so 3116 can't run `extract()` without 3195.
- **AIML-3013's token-refresh part now.** It fixes the dev failure where a
  slow token refresh drops the live stream, and every later story inherits it.
- **AIML-2650 early.** AIML-2655, 2654 and 2957 all need its accounts.

## 3. The order

A story starts when everything in "Needs" is done. Stories in the same wave
can run in parallel. **Text** says what to do in Jira: *keep* (as written),
*rewrite* (paste the text in §4), *create*.

| Wave | Story | Pts | Owner | Needs | Text |
|---|---|---|---|---|---|
| 0 | AIML-3152 `extract()` follow-up | 5 | Vineet | — | keep |
| 1 | AIML-3011 Dialogue steps in session state | 3 | Vineet | — | keep |
| 1 | AIML-3195 Reference data in Cloud Storage | 5 | | — | keep (+1 criterion) |
| 1 | AIML-3012 `interpret()` | 5 | Dharun | — | rewrite |
| 1 | AIML-3013 Failure handling, non-blocking Google clients | 5 | Dharun | — | rewrite |
| 1 | AIML-2650 Service accounts and caller auth | 3 | Dharun | — | rewrite |
| 1 | AIML-3150 Dev WebSocket service: one instance | 3 | Sainitheesh | — | keep |
| 1 | AIML-2654 Image from `uv.lock` on Python 3.11, Cloud Build | 5 | Sainitheesh | — | rewrite |
| 2 | AIML-3116 Live agent with one tool, `extract()` in the flow | 3 | Vineet | 3011, 3195, 3152 | keep |
| 2 | AIML-3196 `POST /api/sessions` inputs | 5 | | 3011 | keep |
| 3 | AIML-3117 Save gate, corrections, harness conversations | 3 | Vineet | 3116, 3012 | rewrite |
| 3 | AIML-3197 Model Armor | 5 | | 3116 | keep |
| 3 | AIML-3198 Tracing, logging, cost; plugin removed | 5 | | 3116 | keep (+1 criterion) |
| 3 | AIML-3199 Topic ids, one status field | 3 | | 3196, 3195 | keep |
| 3 | NEW S-05 Spike: end of dictation in our code | 5 | | 3116 | create |
| 4 | AIML-3014 Retire the model-driven save machinery | 3 | Dharun | 3117 | rewrite |
| 4 | AIML-2649 Publish the saved record to Pub/Sub | 5 | | 3117, 3196, 3197 | rewrite |
| 4 | AIML-2655 Terraform for the service and its resources | 5 | Sainitheesh | 2650, 2654, 3197, 2649 | rewrite |
| 5 | AIML-2962 Client contract, typed events, browser app removed | 5 | Vineet | 2649 | rewrite |
| 6 | AIML-3054 Eval harness on typed events and session inputs | 5 | Vineet | 2962 | rewrite |
| 6 | AIML-3048 External exposure and end-to-end QA | 3 | Sainitheesh | 2962, 2650 | rewrite |
| 6 | AIML-3051 Staging and prod, each with its own Agent Engine | 5 | Sainitheesh | 2655 | rewrite |
| 7 | AIML-2957 Eval in CI and the release gate | 5 | Vineet | 3054, 2654 | rewrite |
| 7 | AIML-2657 Load and latency test | 2 | | 3051 | rewrite |
| 8 | AIML-2662 Security and compliance review | 3 | | 3197, 2650, 3051 | rewrite |
| 8 | AIML-2661 UAT and business sign-off | 3 | | 3048, 3051 | rewrite |
| 9 | AIML-2660 Field pilot | 3 | | 2661, 2662, 2957 | rewrite |
| 10 | AIML-2663 Production rollout | 3 | | 2660 | rewrite |
| Later | NEW S-18 Audio eval on real recordings | 8 | | 3054; consent | create later |

**Longest chain:** 3152 → (3011 + 3195) → 3116 → 3117 → 2649 → 2962 → 3054 →
2957 → 2660 → 2663.

**Totals:** 28 stories, 113 points, plus S-18 later. Of these, 27 are
already in Jira; 1 to create now.

## 4. The stories

Text for every story marked *rewrite* or *create*, ready to paste; the
*keep* stories are listed with their criteria for reference. Older stories
(AIML-2648 to 2663) are rewritten from their titles; check nothing in their
current Jira text is lost.

---

### AIML-3152 · `extract()` follow-up: evidence by sentence number · 5 pts · keep

**Wave 0**

The model cites sentence numbers and our code copies the words; topic,
event-type and quote rules follow the business's four answers; answer key
v1.5.

**Acceptance criteria**
1. Golden runs on key v1.5 recorded in the decisions log (done: D-82).
2. The agent's quote cue limited to a quote given for that topic, with three
   full agent runs inside the baseline's limit (D-83).
3. The agent baseline re-exported on key v1.5.
4. PR approved and merged.

---

### AIML-3011 · Dialogue steps kept in session state · 3 pts · keep

**Wave 1 · Needs:** nothing · **Unblocks:** 3116, 3196

The step machine (LISTENING → EXTRACTING → ASKING_ABOUT_TOPIC →
READING_BACK → WAITING_FOR_YES → SAVING → DONE), stored in Agent Engine
session state. Not used by the live flow yet.

**Acceptance criteria**
1. Every allowed step change is in one table; any other change raises.
2. Step and draft are written to session state on every change.
3. After a restart the session resumes at the same step with the same draft
   (test).
4. Unit tests cover each step change.

---

### AIML-3195 · Reference data versioned in Cloud Storage · 5 pts · keep, add one criterion

**Wave 1 · Needs:** nothing · **Unblocks:** 3116, 3199 · **Closes:** 2648

`extract()` needs the campaign registry, the field catalog, the event-type
rules and the disposition registry. The app has no runtime source for the
first two today; they are read from folders only the eval passes in. This
moves all four into a versioned bucket, with one loader each shared by the
app and the eval, and replaces the hard-coded config AIML-2648 was raised
for.

**Acceptance criteria** (as created, plus 8)
1. The bucket holds the four files under a version, plus a manifest naming
   the current version of each.
2. At startup the app loads all four through the manifest; a missing,
   unreadable or malformed file stops startup with an error naming the file.
3. One loader per file, used by both the app and the eval; the duplicates in
   `evals/dataset/` are removed.
4. One command validates a new file and uploads it as the next version.
5. The app picks up a new version on its next start, with the same image.
6. Every saved record and eval report carries the four version ids.
7. Unit tests cover loading, a malformed file, and the version ids.
8. **New:** no hard-coded event types, codes or campaign rules are left in
   the app; all of them come from the reference data.

---

### AIML-3012 · `interpret()`: classify the rep's reply after a read-back · 5 pts · rewrite

**Wave 1 · Needs:** nothing · **Unblocks:** 3117

**Description**

After the read-back, the rep's reply decides whether the record is saved. A
text Gemini call with a fixed schema classifies it: confirm, correction,
skip or unclear. This story builds and scores the classifier on its own.
Wiring it into the dialogue steps, and the no-reply timeout, belong to
AIML-3117, because the steps don't exist until AIML-3011 and 3116 land.

**Acceptance criteria**
1. A labelled set of at least 100 replies (plain yes, "yeah", "save it",
   "yes but change X", a new fact, noise, empty) is added to the eval.
2. False-confirm rate is the gating metric, with its target written down
   before tuning.
3. An empty or noise transcript is "unclear", never "confirm" (test).
4. One command scores it, in the harness's scorecard format.
5. A correction comes back with the rep's words for the change.

---

### AIML-3013 · Failure handling and non-blocking Google clients · 5 pts · rewrite

**Wave 1 · Needs:** nothing · **Closes:** 2651

**Description**

Nothing retries today. On dev, a token refresh to Google that times out
drops the live stream. This story makes model-call failures predictable and
keeps Google auth off the event loop: `extract()` and `interpret()` get one
retry with backoff, then a typed error and a fixed spoken line ("I couldn't
save, your notes are kept"). Every Google client is created and
authenticated at startup. Model Armor and Pub/Sub carry the same pattern in
their own stories (AIML-3197, 2649).

**Acceptance criteria**
1. A test per failing call: one retry with backoff, then the typed error and
   the spoken line.
2. Transcript and draft stay in session state after a failure.
3. Token refresh never blocks the event loop (shown in a trace).
4. No Google client is created on a request path.
5. A long session on dev survives a token refresh without dropping.

---

### AIML-2650 · Service accounts and caller auth · 3 pts · rewrite

**Wave 1 · Needs:** nothing · **Unblocks:** 2655, 2654, 3048, 2957

**Description**

The service runs with broad default credentials, CI has no identity of its
own, and any caller that reaches the URL can name any rep. This story gives
the service and CI their own least-privilege accounts (NP first, then prod),
limits who may call us to the consumer's service (A1), and keeps every
secret out of the code and the image.

**Acceptance criteria**
1. A runtime account with only: Vertex AI user, Agent Engine session
   access, Pub/Sub publisher on `visit-records`, Model Armor user, read on
   the reference-data bucket, log and trace writer. It cannot read the eval
   bucket.
2. A CI account with read on the eval bucket, Artifact Registry writer and
   the right to deploy the service; nothing else on data.
3. Cloud Run runs as the runtime account; the Compute Engine default
   account is no longer used. No key files anywhere.
4. Only the consumer's service account is on the invoker list.
5. No secret is in the repo, the image or an env file; anything secret
   comes from Secret Manager.
6. The grants are written down next to the Terraform (AIML-2655).

---

### AIML-3150 · Dev WebSocket service: one instance · 3 pts · keep

**Wave 1 · Needs:** nothing

Dev runs up to 5 instances, but the one-connection-per-session lock lives in
one instance's memory, so two connections for one session can land on
different instances. Set min and max instances to 1 (A10). Check the
criteria in Jira match this; AIML-2655 writes the same setting into
Terraform.

---

### AIML-2654 · Image from `uv.lock` on Python 3.11, built by Cloud Build · 5 pts · rewrite

**Wave 1 · Needs:** nothing · **Unblocks:** 2655, 2957 · **Closes:** 3037

**Description**

The Dockerfile uses Python 3.10 and runs `pip install .`, which ignores
`uv.lock`, so the image can carry versions nobody tested. This story moves
the runtime to Python 3.11 (the `pyproject.toml` change made with uv on the
dev machine), installs exactly what `uv.lock` pins, and has Cloud Build
build the image and push it to Artifact Registry on every merge. The same
pipeline later runs the eval (AIML-2957).

**Acceptance criteria**
1. `requires-python` is `>=3.11` and the base image is Python 3.11 or later.
2. The image installs exactly what `uv.lock` pins; `pip install .` is gone.
3. Cloud Build builds and pushes the image on every merge, running as the CI
   account (AIML-2650).
4. All tests pass in the pipeline on the new runtime.
5. `GOOGLE_API_KEY` and `GOOGLE_GENAI_USE_VERTEXAI` handling is removed from
   the code and the config; the app runs on Vertex only.

---

### AIML-3116 · Live agent with one tool, `extract()` in the flow · 3 pts · keep

**Wave 2 · Needs:** 3011, 3195, 3152

Live keeps the voice and gets one tool, `dictation_done()`. Our code runs
`extract()` on the transcript, builds the read-back and the topic question,
and moves the steps.

**Acceptance criteria**
1. The Live agent has exactly one tool.
2. Extraction rules are gone from the Live prompt; `behavioral_rules.yaml`
   keeps conversation behaviour only.
3. An unmentioned planned topic triggers one question, driven by topic
   status.
4. The silence watchdog reads the current step instead of `turn_guard`; a
   check-in while a topic question is pending repeats the question.
5. A happy-path conversation passes in the harness in text mode.

---

### AIML-3196 · `POST /api/sessions` takes the inputs the record needs · 5 pts · keep

**Wave 2 · Needs:** 3011 · **Unblocks:** 3199, 2649

`account_id`, optional `event_id` (A2), `vertical`, `rep_id` from the calling
service (A1), and planned topics as a JSON list (registry id or title), kept
in session state; campaign type is no longer an input.

**Acceptance criteria**
1. The request takes `account_id`, `event_id` (optional), `vertical`,
   `rep_id` and `planned_topics: [{id} | {title}]`; the response is the
   `session_id`.
2. An unknown vertical or topic id, or a missing `account_id`, gets a typed
   4xx error; consumer maps to MH.
3. A topic title with commas arrives intact.
4. `campaign_type` is gone; the WebSocket path's `user_id` is ignored.
5. The inputs survive a restart (test).
6. The saved record carries `account_id`, `event_id`, `rep_id`, `vertical`.
7. The harness and the browser client use the new request.

---

### AIML-3117 · Save gate, corrections and harness conversations · 3 pts · rewrite

**Wave 3 · Needs:** 3116, 3012 · **Unblocks:** 3014, 2649

**Description**

Wires `interpret()` (AIML-3012) into WAITING_FOR_YES, so a save happens
only on a confirming reply that came after the latest read-back. A
correction re-runs `extract()` and forces a new read-back. Takes the
no-reply timeout from AIML-3012, and the gate tests from the code AIML-3014
removes.

**Acceptance criteria**
1. A save is reachable only from WAITING_FOR_YES, on a reply after the
   latest read-back (test).
2. A correction runs `extract()` again and forces a new read-back that says
   what changed.
3. No reply within the timeout: one reminder, then the notes stay unsaved
   and the rep is told.
4. The rules in `test_notes_workflow_gates.py` pass against the steps.
5. Harness conversations pass: happy path, skipped topic, correction, no
   reply.

---

### AIML-3197 · Model Armor: screen the transcript, de-identify the record · 5 pts · keep

**Wave 3 · Needs:** 3116 · **Unblocks:** 2649, 2662

**Acceptance criteria**
1. Screening and de-identify templates per environment; the rule (what
   stays, what goes) written down.
2. Every transcript is screened before `extract()`; a blocked one stops with
   a typed error and the fixed line.
3. Every record is de-identified before publish: patient or resident names
   removed, business contact names kept (test notes for both).
4. Model Armor unreachable: one retry, then the typed error; the transcript
   stays in session state.
5. A record not screened and de-identified is never published (test).
6. The added latency per session is measured.

---

### AIML-3198 · Tracing, logging and cost per session; analytics plugin removed · 5 pts · keep, add one criterion

**Wave 3 · Needs:** 3116 · **Closes:** 2652, 2820, 2821, 2822

**Acceptance criteria** (as created, plus 8)
1. One trace shows a whole session: Live turns, `extract()`, `interpret()`,
   Model Armor and the publish.
2. Each model call logs tokens and cost; a BigQuery view gives them per
   session and per day.
3. Errors appear in Error Reporting with the session id.
4. Checked on dev: the sink carries every plugin field we use (A4).
5. `app/analytics.py`, its wiring, its dependencies and `scripts/bigquery_*`
   are removed; `config.py` stays.
6. The latency of the new model calls is measured against today.
7. No transcript text is logged in full.
8. **New:** every log line is structured JSON with the session id and the
   step.

---

### AIML-3199 · Topic ids and one topic-status field · 3 pts · keep

**Wave 3 · Needs:** 3196, 3195

**Acceptance criteria**
1. Each planned topic carries its registry id, or its title when it has
   none, from the session through `extract()` to the record.
2. Status is one field: `unaddressed`, `skipped` or `discussed`.
3. Exactly one record entry per planned topic.
4. Matched by id or exact title only, never by substring.
5. The `extract()` eval scores no worse than before.

---

### S-05 · Spike: decide end of dictation in our code · 5 pts · create

**Wave 3 · Needs:** 3116

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
2. Both approaches run on the full harness; empty turns, missed dictations
   and time to the read-back are reported for each.
3. A written recommendation, with the numbers, says which to keep and
   whether the silence watchdog can go.
4. The decision goes in the decisions log.

---

### AIML-3014 · Retire the model-driven save machinery · 3 pts · rewrite

**Wave 4 · Needs:** 3117

**Description**

Once the dialogue steps decide when to save, the code that tried to stop the
model from saving wrongly is dead: `turn_guard.py`, the commit and read-back
watchdogs, `stage_visit_notes` / `commit_visit_notes`, `_normalize_topics`,
the in-memory store and its prune task, the supersede gate, and the scripts
that test them.

**Acceptance criteria**
1. The modules and tools above are removed and nothing imports them.
2. The scripts for the old flow are removed: `ws_smoke_test.py`,
   `test_pr_review_fixes.py`, `test_aiml_2743_session_lifecycle.py`,
   `smoke_test_output.txt`.
3. Business rules still in use move next to the steps, with their tests.
4. A full harness run passes against the committed baseline.

---

### AIML-2649 · Publish the saved record to Pub/Sub · 5 pts · rewrite

**Wave 4 · Needs:** 3117, 3196, 3197 · **Unblocks:** 2962, 2655

**Description**

A saved record exists only in session state today; nothing reaches
Salesforce. We don't write to Salesforce ourselves (A11): on save, the
record goes to the client as a `saved` event, and to the Pub/Sub topic
`visit-records`, which the consumer team reads and writes to Salesforce. The
topic's schema, generated from `schemas.py`, is the contract with them.
Delivery can repeat, so the consumer dedupes on `session_id`.

**Acceptance criteria**
1. One message per saved session, with the CRM keys, the de-identified
   record, and the reference-data versions.
2. The Pub/Sub schema is generated from `schemas.py` by one command; the
   topic rejects a malformed message (test).
3. The client gets `saved` only after the publish succeeds.
4. Publish fails: one retry with backoff, then a typed error and the fixed
   line; the record stays in session state.
5. The contract states the consumer dedupes on `session_id`.
6. An integration test publishes a record and reads it back from a test
   subscription.

---

### AIML-2655 · Terraform for the service and its resources · 5 pts · rewrite

**Wave 4 · Needs:** 2650, 2654, 3197, 2649 · **Unblocks:** 3051

**Description**

Environments are built by hand today. This story writes the service and
everything it uses as Terraform, so an environment can be built from an
empty project: Cloud Run (one instance, A10; 60-minute timeout), Artifact
Registry, the `visit-records` topic, our BigQuery copy through a BigQuery
subscription (A6), a dead-letter topic, the reference-data bucket, the Model
Armor templates, and the accounts from AIML-2650. Live in `us-central1`,
`extract()` on the global endpoint (A9).

**Acceptance criteria**
1. `terraform apply` builds a working environment from an empty project.
2. Cloud Run is fixed at one instance with a 60-minute timeout.
3. A BigQuery subscription writes every `visit-records` message to a table,
   with no code of ours in the path.
4. Undeliverable messages go to a dead-letter topic, with an alert.
5. Retention is one variable, used by every store (A7).
6. The README says how to build an environment.

---

### AIML-2962 · Client contract, typed events, browser app removed · 5 pts · rewrite

**Wave 5 · Needs:** 2649 · **Closes:** 2845

**Description**

The client will be built by another team. Today it would have to read raw
ADK events, including `instruction_for_model` text meant only for the
model, and our browser app does things nobody has written down (half-duplex
mic, barge-in, dropping audio when the uplink falls behind, closing after a
save). This story replaces raw events with a small typed set, writes the
contract the other team builds against, and removes our browser app: once
events are typed it would break, and fixing it only to delete it is wasted
work.

**Acceptance criteria**
1. The server sends only `ready`, `transcript`, `agent_text`,
   `record_preview`, `saved` and `error`, each with a JSON schema.
2. `instruction_for_model` and raw ADK events never reach the client (test).
3. The WebSocket takes only ids in its path; `planned_topics` is gone from
   it.
4. An unknown session, or another rep's, gets a typed error and a clean
   close, not a dropped socket.
5. The contract document covers auth (A1), session creation, audio up and
   down, half-duplex and barge-in, the uplink drop rule, keep-alive, the
   time limit, every event, end of session and every error code.
6. `app/static/`, `demo_assets/`, and the `/` and `/api/config` routes are
   removed; the README describes the service as it is.
7. The other team confirms they can build a client from the contract alone.

---

### AIML-3054 · Eval harness on typed events and session inputs · 5 pts · rewrite

**Wave 6 · Needs:** 2962 · **Unblocks:** 2957, S-18

**Description**

The agent harness drives today's app: it creates sessions with topic titles
and a campaign type, reads raw ADK events, and scores the last
`stage_visit_notes` call. All three go away. This story moves the harness to
the new session inputs and typed events, keeps the metrics and verdicts, and
adds the counter this ticket was raised for in the form that still matters
in the new flow. Its original counters (disposition loss, reminders caused
by a paraphrased label) measure problems of the old flow that 3116 and 3014
remove.

**Acceptance criteria**
1. A full run creates sessions with the new inputs and scores end to end
   from typed events.
2. The scorecard has the same metrics and verdicts as today.
3. A new counter: questions asked about a planned topic the rep had
   already discussed.
4. "The agent never replied" is counted apart from a wrong answer.
5. `extract()` scoring runs in the same check.
6. A baseline is exported on the new flow and committed.

---

### AIML-3048 · External exposure and end-to-end QA · 3 pts · rewrite

**Wave 6 · Needs:** 2962, 2650 · **Closes:** 2659

**Description**

The consumer's service reaches us through the load balancer with a Google
ID token (A1). This story opens that path and proves the whole chain works
from outside our project: their client creates a session, streams a
dictation, gets `saved`, and the record arrives on Pub/Sub.

**Acceptance criteria**
1. The consumer's service reaches us through the load balancer; only its
   account is accepted.
2. An unauthenticated or unknown caller gets 401/403, never a session.
3. A QA run from the consumer's client: session, dictation, correction,
   `saved`, and the record on Pub/Sub.
4. Every error code in the contract is triggered once and handled by the
   client.

---

### AIML-3051 · Staging and prod, each with its own Agent Engine · 5 pts · rewrite

**Wave 6 · Needs:** 2655, the team that provides the engines · **Closes:** 2656

**Description**

Builds staging and prod from AIML-2655's Terraform. Each environment gets
its own Agent Engine instance (sessions today use a borrowed one), its own
bucket, topic and Model Armor templates. A deploy goes to staging first and
is smoke-tested before it reaches prod.

**Acceptance criteria**
1. Staging and prod built with one `terraform apply` each.
2. Each has its own Agent Engine, id from configuration; the app fails at
   startup if it is missing or wrong.
3. Sessions are created, resumed and read back on each engine (integration
   test).
4. A smoke test (session, one dictation, `saved`, record on Pub/Sub) runs
   after every deploy to staging, and a failure stops promotion to prod.

---

### AIML-2957 · Eval in CI and the release gate · 5 pts · rewrite

**Wave 7 · Needs:** 3054, 2654

**Description**

The eval only protects quality if a drop stops a release. Cloud Build
(AIML-2654) runs the quick eval on every change and the full eval before a
release; REGRESSION or INVALID blocks it. Golden data is customer notes, so
it is fetched at build time and never kept in the image, logs or artifacts.

**Acceptance criteria**
1. CI fetches the key version named in the README; no data test skips.
2. Bucket access is read-only, for the CI account only.
3. The quick eval runs on every change; the full eval runs before a release.
4. REGRESSION or INVALID fails the build; a deliberately broken prompt fails
   it in a test pipeline.
5. The scorecard is attached to the build.
6. Golden data is absent from the image, logs and artifacts (checked).

---

### AIML-2657 · Load and latency test · 2 pts · rewrite

**Wave 7 · Needs:** 3051

**Description**

One instance (A10) must carry the expected number of reps at once, and the
new flow adds model calls the rep waits on. This measures both on staging
with synthetic dictations, never golden data.

**Acceptance criteria**
1. Live API and Gemini quotas are checked against the expected number of
   reps; the figure is written down.
2. A test runs the expected peak of concurrent sessions on one instance;
   none fails or drops.
3. Time from end of dictation to the read-back, and from "yes" to `saved`,
   reported at p50 and p95.
4. If one instance can't carry the peak, a written proposal for what
   changes.

---

### AIML-2662 · Security and compliance review · 3 pts · rewrite

**Wave 8 · Needs:** 3197, 2650, 3051

**Acceptance criteria**
1. Review covers: caller auth, account grants, secrets, de-identification
   rule and its test results, retention (A7), and what is logged.
2. Every finding is fixed or accepted in writing by its owner.
3. Sign-off recorded before the pilot.

---

### AIML-2661 · UAT and business sign-off · 3 pts · rewrite

**Wave 8 · Needs:** 3048, 3051

**Acceptance criteria**
1. Business users run agreed scripted visits on staging through the
   consumer's client.
2. The records they see in Salesforce match what they said; misses are
   logged and triaged.
3. Business sign-off recorded, naming any accepted gaps.

---

### AIML-2660 · Field pilot with a subset of reps · 3 pts · rewrite

**Wave 9 · Needs:** 2661, 2662, 2957

**Acceptance criteria**
1. A named group of reps uses it on real visits in prod for an agreed
   period.
2. Daily figures from the cost view and the logs: sessions, saves, errors,
   time to save, cost.
3. Reps' feedback and the records' review by the business collected.
4. A go/no-go for rollout, with the numbers.

---

### AIML-2663 · Production rollout · 3 pts · rewrite

**Wave 10 · Needs:** 2660

**Acceptance criteria**
1. Rollout in agreed phases, each with a check of errors and saves before
   the next.
2. A rollback path tested on staging.
3. An on-call runbook: alerts, dead-letter topic, failed saves.

---

### S-18 · Audio eval on real spoken recordings · 8 pts · create later

**Later · Needs:** 3054; consent agreed

**Description**

Text cases cannot catch mishearing. Collect real spoken visit notes (noise,
accents, clipped speech, product names) with consent, run them through
Live's transcription and the full flow, and score them like the text eval.
Can be split into "collect" (3) and "score" (5) when planned.

**Acceptance criteria**
1. At least 30 recordings across every vertical, with written consent, a key
   in the golden format, stored outside the repo with agreed retention.
2. One command runs them through the full flow and scores them.
3. An audio scorecard alongside the text one, run before each release.
4. A report on transcription errors and their effect on the record.

## 5. Housekeeping (not a story)

- Move to `docs/archive/`: `architecture-proposal.md`,
  `stories-after-guided-removal.md`, `plan-after-implicit-decision.md`,
  `PR5-followup-stories.md`, `note-2698-story-points.md`, and
  `sell_n_tell_architecture.md` (retitled as the agent being replaced).
- One line at the top of `architecture-stories.md` and in `HANDOFF.md`'s
  ticket table: "Order and current scope: `story-order.md`".
