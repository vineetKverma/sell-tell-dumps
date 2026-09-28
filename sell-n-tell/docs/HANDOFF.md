# SellNTell — session handoff

Resume with no prior context. Read this first — it says what to do next and
why. Then `plan-after-implicit-decision.md` for the current piece of work, and
`change-log.md` for what changed and why.

---

## ✅ START HERE — PR #6 is answered and waiting on re-review

Current as of 2026-09-17. `development` was re-architected by AIML-2750 in
August — `mock_db.py`, `db_interface.py`, `bigquery_db.py` and
`bigquery_sink.py` are gone, replaced by `notes_workflow.py`, `schemas.py` and
`resources/*.yaml`. Sections 3 and 5 below still describe the old shape; the
warnings there say so.

### Where this stands

**PR #6 (AIML-2751, remove the guided flow) is open with every review comment
addressed.** Nothing is outstanding on our side except Suresh's reply.

Three rounds of review, all answered:

1. **First round (3 comments)** — resolved. The confusing diff was because the
   branch was cut before AIML-2750 merged; it was rebuilt on the new
   `development`.
2. **Second round (6 comments)** — resolved, pushed as `617faf8`.
3. **Third round (1 comment)** — pytest was declared as an
   `[project.optional-dependencies]` extra, which `uv run` does not install, so
   the documented `uv run pytest tests/ -q` failed with "program not found".
   Moved to `[dependency-groups] dev`, which `uv run` installs by default.
   Verified after a `uv sync` so it is not leaning on a stale `.venv`.

**One thread is deliberately still open** — the `session_id` one. Leave it until
he replies; it is where we confirmed his diagnosis and changed what the tests
claim.

### The finding worth carrying forward

Suresh caught that the AIML-2703 supersede gate **cannot fire in the live
flow**. `tools.py` passes `session_id=tool_context.session.id` on every
`stage_notes` call, so `previous_session_id != session_id` in
`notes_workflow.stage_notes` is always false, `superseded_by` is never set, and
a correction overwrites `_STAGED_NOTES[session_id]` in place.

So what actually delivers AIML-2703's guarantee in production is the
**single-draft invariant** — one visit only ever has one committable record —
not the gate. The gate is defence for a caller that is not `tools.py`.

`tests/test_notes_workflow_gates.py` now asserts both, split explicitly:

- `TestLiveCallPattern` — same `session_id`, as `tools.py` does. Asserts one
  draft, no `superseded_by`, correction lands in place, one commit, retry
  replays, coverage gate blocks then releases.
- `TestSupersedeGate` — distinct ids. The gate fires here.

**Open question raised with Suresh, not yet answered:** if nothing but
`tools.py` will ever call `notes_workflow`, the supersede gate is unreachable
code — the same "dead code that reads as live" shape this whole PR cleaned up.
Worth a decision either way.

### Testing — what exists now

```powershell
uv run pytest tests/ -q      # 8 tests, no server, no credentials
```

That is the only deterministic coverage in the repo. It needs no running app
because `tests/conftest.py` imports `notes_workflow` under a private package
name, bypassing `voice_notes_agent/__init__.py` (which builds the ADK agent).

For the model-level check, with the server running (no `--reload`):

```powershell
uv run python scripts/ws_smoke_test.py      # no positional argument
```

**Reading the transcript is the only verification.** The `/api/v1` layer is
gone — `main.py` serves only `/healthz`, `/` and the WebSocket — so there is no
`notes/committed` endpoint to count. Each scenario should reach a
`TOOL_RESP=commit_visit_notes -> {'status': 'success'` before the next begins.
Capture it and count:

```powershell
uv run python scripts/ws_smoke_test.py *> smoke.log
(Select-String smoke.log -Pattern "scenario complete").Count       # expect 7
(Select-String smoke.log -Pattern "'status': 'success'").Count     # expect >= 7
Select-String smoke.log -Pattern "no_confirmation_heard|BLOCKED|'status': 'error'"
```

Last full run: 7/7 committed, no errors. Delete `smoke.log`, do not commit it.

### Next, once PR #6 merges

From `stories-after-guided-removal.md`, adjusted — AIML-2750 delivered Story 6,
and Story 3 is likely moot now there is one store:

1. **Story 1** — consolidate campaign rules, *before* vertical-market context
   adds a second config dimension. **Re-check its scope first**: the rewrite
   moved the registry into YAML and may have closed part of it.
2. **Event type interpretation** — Jeremy's first refinement.
   `plan-after-implicit-decision.md` §2 has the root cause (event types carry no
   mapping cues while disposition codes do). **Re-verify against
   `resources/dispositions.yaml`** — that analysis predates the rewrite.
3. **AIML-2702 + AIML-2733** — eval harness and golden set. These gate the
   vertical-market work.
4. **Vertical market context** — Jeremy's second refinement.

**All six follow-up stories need re-checking against the new structure** before
anyone picks one up. They were written against `mock_db.py`, which no longer
exists.

### Open, not ticketed

- **F7** — `_topic_matches` uses substring containment, so an inflected label
  ("Appliance Contract Renewal" vs planned "Appliances") reports the topic
  uncovered and can produce two rows for one discussion.
- **Invented skip reasons** — the agent still writes "due to time constraints"
  when the rep gave no reason. Prompt wording was measured over six runs and
  made no difference; needs a server-side fix.
- **Registry content gap** — no code expresses "renewal agreed", "quote created"
  or "no contact made"; roughly a quarter of real visits.
  `note-disposition-registry-gap.md`.
- **Vestigial BigQuery DDL** — `scripts/bigquery_create_tables.sql` and
  `bigquery_schema.json` still define a `guided_flow_calls` table and an
  `agent_mode` column, but `bigquery_sink.py` was deleted, so nothing writes to
  them. Loose end from AIML-2750.
- **The sync tool never deletes.** `tools/import-repo-md.ps1` only writes files,
  so anything removed upstream survives locally and has to be deleted by hand.

### Three traps that have each cost time

1. **Run `python tools/fix_mojibake.py --write` after every import.** The
   importer decodes UTF-8 as the Windows ANSI codepage and mangles every emoji
   and box-drawing character. `.gitignore` is in its target list now too.
2. **Bump the asset version in two places.** `index.html` *and* `app.js`'s two
   module imports, and they must match. Currently `v=10`.
3. **Verify a documented command exactly as written, in a clean environment.**
   Three separate findings in this project came from state left lying around —
   `crypto.randomUUID` passing on `localhost` but blanking on a LAN IP, a smoke
   count that looked right until a restart zeroed it, and pytest "working"
   because a stale `.venv` already had it. `uv sync` before `uv run` when
   proving a dependency change.

### Guided is preserved

Tag `archive/guided-flow` on `9433908`, pushed, verified to contain both files:

```powershell
git checkout archive/guided-flow -- app/voice_notes_agent/tools_guided.py
```

---

## 1. Ticket status

| Ticket | Title | Status |
|---|---|---|
| **AIML-2751** | Remove the guided flow | **PR #6 open, all review comments answered.** Waiting on Suresh's re-review — see START HERE |
| **AIML-2845** | No-speech turns leave the agent's recovery message suppressed | **Backlog.** Raised from PR #6 review; `suppressAgentSpeech` is only lifted by a tool call, and the no-speech path has none |
| **AIML-2750** | CRM backend decision (Dharun) | **Closed, merged as PR #7 `6ffd86f`.** Delivered as a full re-architecture: `mock_db`/`db_interface`/`bigquery_db`/`bigquery_sink` deleted, `notes_workflow.py` + `schemas.py` + YAML resources added |
| **AIML-2698** | Disposition + State Correctness | **Closed.** Delivered in PR #5 |
| **AIML-2705** | Disposition Quality Guardrails | **Closed.** ACs 1/2/5 delivered; AC4 took its "documents residual risk" clause; AC3 met with 3 cases |
| **AIML-2703** | Correction & Re-stage Reliability | **Closed.** Coverage is now `tests/test_notes_workflow_gates.py` (8 tests). Note the supersede gate cannot fire in the live flow — the single-draft invariant is what delivers the guarantee; see START HERE |
| **AIML-2702** | Eval Harness (faithfulness / factualness / contextualness) | Not started. Q3-S3 |
| **AIML-2697** | FAR Demo Hardening: Mode UX + Demo Script | Partly in flight — the audio fixes are tagged to it |
| **AIML-2651** | Error Handling & Resilience | Not started. No retry/backoff anywhere; timeouts hardcoded |
| **AIML-2704** | ? | Unknown — a branch exists, not in any plan we've seen |

---

## 2. What this project is

An **agentic voice-dictation app for field sales reps (FARs)**. The rep speaks
unstructured notes after a visit; the agent extracts a **structured CRM record**
(event type + one entry per planned topic, each with a disposition code and
summary), reads it back, and commits on verbal approval.

**Why it's an agent:** a transcript is useless to a CRM. The task is *constrained
extraction* — mapping free speech onto a fixed registry of outcome codes,
hands-free, with no screen. Verification is a spoken readback and a verbal yes.

**Scope reality:** Confluence describes a phone-call product (CarPlay, podcast
pre-call briefing). What exists is a **browser mic app** with a mock CRM, an
optional BigQuery backend, and a BigQuery analytics sink.

---

## 3. Architecture

Rewritten 2026-09-07 against the post-AIML-2750 code, after the re-import.

```
browser mic (16 kHz Int16 PCM, 20 ms chunks)
   │  WS /ws/{user_id}/{session_id}?planned_topics=&campaign_type=
   ▼
FastAPI upstream_task ──> ADK LiveRequestQueue ──> Gemini Live (Vertex, native audio)
                                                        │
                          downstream_task <── events ───┘
                                ├─ function_call → tools.py → notes_workflow (in-process)
                                └─ audio chunks  → WS → browser playback
```

**The HTTP loopback is gone, and so is the REST layer.** `tools.py` calls
`notes_workflow` directly, in-process. `main.py` serves exactly two routes,
`/healthz` and `/`. This inverts the old rule: enforcement no longer "belongs
in the REST layer", it lives in `notes_workflow` — and, critically, **gaps no
longer reproduce with plain HTTP calls**, which is what broke every REST-based
test this project had. See the testing warning in START HERE.

`agent_mode` is gone entirely — not a WS parameter, not on the record, not a
Runner key. One agent, one `Runner`. `planned_topics` is live and seeds the
prompt's coverage-reminder block; `campaign_type` is accepted and logged but
**inert** — `main.py`'s `websocket_endpoint` docstring says so explicitly, and
`notes_workflow.validate_payload()` never reads it.

**The layer, as it now is:**

- `notes_workflow.py` (678 lines) — staging, the correction/supersede chain,
  the coverage gate, commit and its idempotency replay. In-memory
  `_STAGED_NOTES` only; nothing survives a restart, and there is **no
  `list_committed`** — a committed record is just
  `_STAGED_NOTES[sid]["committed"] = True`.
- `schemas.py` — the Pydantic payloads pulled out of the old `mock_db`.
- `resources/dispositions.yaml` — one universal disposition registry. No
  per-campaign variants any more.
- `resources/behavioral_rules.yaml` — the agent's static prompt text. Now the
  single source, since `agent_guided.py`'s prompt is gone.
- Durable audit is ADK's `BigQueryAgentAnalyticsPlugin` on the Runner, not
  hand-rolled writes. **The two-BigQuery-flags problem is resolved** —
  `BIGQUERY_ENABLED` and `VOICE_NOTES_BQ_ENABLED` are both gone, replaced by
  the single `BQ_ANALYTICS_ENABLED` (default `false`), with
  `BQ_ANALYTICS_DATASET_ID` / `_TABLE_ID` / `_LOCATION` beside it. Open
  decision #5 below is closed.
- `config.py` — now **dead**. It defines `API_BASE` for the HTTP loopback that
  no longer exists, and nothing imports it. Safe to delete; left alone because
  it is outside AIML-2751.

**Modes.** `implicit` is the only flow: `agent.py` + `tools.py`, 2 tools
(`stage_visit_notes`, `commit_visit_notes`), ~2 rep turns. `guided` is
retired (AIML-2751) and recoverable from the tag `archive/guided-flow`. A
hybrid exists on `feature/AIML-2686` — not ours.

On identical input the two modes produced **identical dispositions**; they
differed only in how much the rep was asked, which is why guided went.

---

## 4. Environment

Repo lives on a separate machine (`C:\Personal Storage\developer\sell-n-tell`);
a reconstructed copy for reading/editing is at
`c:\Personal Storage\poc\sellNtell\sell-n-tell`.

**Syncing the local copy** — do this before any analysis, or you will reason
about files that don't exist:

```powershell
# on the app machine, from the repo root (copy tools/export-repo-md.ps1 there first)
.\export-repo-md.ps1
# copy export\ back, then locally:
.\tools\import-repo-md.ps1 -In .\export -Dest .\sell-n-tell
```

**Run:**

```powershell
uv sync
gcloud auth application-default login
gcloud config set project prj-hds-np-data
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Do not use `--reload` for a demo** — a file save restarts the process, drops
every live WebSocket, and wipes the session store and staged records.

**`app/.env` is untracked now** (`.env.example` is the template). Needs a
**native-audio** model or spoken playback silently disables itself.

### Frontend caching — read this before editing `app.js`

This cost an hour. Three mechanisms were half-wired at once:

1. `index.html` loads `app.js?v=N`, **and `app.js` now imports
   `audio-player.js?v=N` / `audio-recorder.js?v=N`**. **Bump N in both files**
   when you change any of the three — the browser caches by full URL, so a new
   file at the same URL is invisible. Currently `v=10` (bumped from 9 by
   AIML-2751).

   The imports were versioned on 2026-08-20 after the app machine served `app.js` fresh
   (200, 65 kB) and `audio-recorder.js` from disk cache (0 B) in the same page
   load, despite the `no-store` middleware below. The version query had only
   ever covered `app.js`, so a change to an imported module could be invisible
   while `app.js` was demonstrably current.
2. A **service worker** (`sw.js`) was cache-first with no revalidation. It had
   already been unregistered in `app.js` but the file was left in the repo, and
   an installed copy kept serving stale assets. **Deleted.** Note that deleting
   the file does not uninstall a worker already running in someone's browser.
3. `main.py` now sends `Cache-Control: no-store` for `/static`, which makes the
   version query redundant. Keep both.

Symptom to recognise: the file on disk is correct, `Invoke-WebRequest` of the
plain URL returns the correct content, and the browser still runs old code.

**Debugging:** `_log_event` in `main.py` prints every downstream event without
PCM noise. The strings to watch for, verified against the current code:
`commit_visit_notes BLOCKED:` (turn_guard, two variants — `real
confirmation_text was never…` and `no new rep reply since staging…`),
`Staging rejected by validation:` (was `Staging rejected for campaign_type=`;
campaign rules are gone with campaign_type), and `Commit BLOCKED for
session_id=` (superseded, and incomplete coverage).

---

## 5. Tests

Rechecked 2026-09-07 against the post-AIML-2750 code.

**Conversational harness** (no mic, real WebSocket, text turns). This is the
**only** working test in the project:

```powershell
uv run python scripts/ws_smoke_test.py                       # 7 scenarios
uv run python scripts/ws_smoke_test.py --scenario clean_save
```

No positional mode argument any more. The seven scenarios are `clean_save`,
`correction`, `correction_summary`, `correction_disposition`,
`correction_add_topic`, `missing_topic`, `multi_topic`.

Bar: every scenario commits, one CRM record each, no duplicates.

**One scenario is intermittent — re-run before calling a failure a regression:**

- `correction_summary` — on 2026-08-21 it missed once in a full run and
  committed on its own re-run, no code change in between. Model
  non-determinism, same family as Gap 6/F5 (see `change-log.md`, Batch N).

🔴 **There is no longer a way to count the result.** This section used to say
"counting the result is the real check, not the transcript", via
`Invoke-RestMethod .../api/v1/notes/committed`. AIML-2750 deleted the whole
`/api/v1` layer — `main.py` serves only `/healthz` and `/` — and
`notes_workflow` has no `list_committed`. Committed records exist only as
`_STAGED_NOTES[sid]["committed"] = True` in process memory. **Reading the
transcript is now the only check available**, which is a real regression in
verifiability, not a documentation gap.

Restoring it is cheap and is the first thing to do before trusting any smoke
run again: a read-only `GET /healthz`-style debug route over `_STAGED_NOTES`,
or a query against the BigQuery table the ADK analytics plugin writes when
`BQ_ANALYTICS_ENABLED=true`. The duplicate check that mattered — group by
`ws_session_id`, expect no group above 1, since each scenario opens its own —
needs whichever of those lands first.

**One scenario is intermittent — re-run before calling a failure a
regression:** `correction_summary` (see above).

🔴 **The REST suite is gone too.** The 9-case block in
`AIML-2698-experiments.md` (coverage gate 409, campaign rules 422, happy path,
skip-after-reminder, manual review, self-skip rejection) drove `/api/v1` and
cannot run. Note two of those cases are also now meaningless on their own
terms: campaign rules no longer exist, and there is one universal disposition
registry.

🔴 **The AIML-2703 supersede gate has no coverage at all.**
`scripts/repro_orphan_restage.py` — local-only, never on the branch — was the
stand-in named in §1, and it is a `/api/v1` client. The gate itself is
verified present in `notes_workflow.commit_notes`, above the coverage gate,
raising `SupersededRecordError`. But the smoke suite exercises the correction
path without ever trying to commit a superseded draft, so **all seven
scenarios would still pass with that gate deleted.** The fix is now easier
than it was: call `notes_workflow.stage_notes` / `commit_notes` directly
in-process — stage, re-stage with `previous_session_id`, commit the *old* id,
expect `SupersededRecordError`. No server, no mic, no model.

Old harness gap, now moot: it hardcoded `campaign_type=standard_sales`, so no
`enterprise_field` scenarios were covered. `campaign_type` is inert now, so
adding `--campaign` buys nothing until `validate_payload()` reads it again.
AIML-2702's step one is no longer that flag — it is rebuilding an assertable
harness at all.

---

## 6. Lessons worth keeping

**A prompt rule cannot beat a structure pointing the other way.** Five fixes
followed that shape and were solved structurally — a code-level gate, an
ordering constraint, an extra enum value. The one prompt-only attempt was
measured over six runs before and after and made no difference.

**When a guard fires unexpectedly, instrument before assuming it's wrong.**
`turn_guard` looked broken for a day and was correct every time.

**A stale Protocol is worse than no Protocol.** `CRMStore` documented the old
signatures, so a real mismatch (A1) passed type-checking silently. It was
noticed during the merge and deferred — that deferral is what let A1 ship.

**Settle "his branch moved" with `git ls-remote`, not `git rev-parse`** — the
latter reads a cache. `tools/compare-trees.ps1` does a three-way tree diff.

**We only ever tested on `localhost`.** That's a secure context and a single
user, which is exactly why A7 (`crypto.randomUUID` on plain HTTP) and the
concurrency races (A2, A10) were invisible.

---

## 7. Open decisions for the lead

1. **Registry content.** No code expresses "renewal agreed", "quote created" on
   campaigns lacking code 1, or "no contact made" (~25% of real visits between
   them). A no-contact visit has no valid event type either. Product decision.
2. **Who consumes `needs_manual_review`?** Nothing downstream reads it.
3. **Is coverage a blocker or a prompt?** With category topics, most visits will
   trigger reminders — 67% of real notes name no product category at all.
4. **Two flag shapes** — guided used null code + `needs_manual_review`,
   implicit uses code 99. Still open, and now odder: with guided retired
   nothing *sets* `needs_manual_review`, but `schemas.py` still declares it and
   `notes_workflow`'s coverage gate still honours it as a legitimate reason for
   a topic to carry no code. So it is a live branch with no producer. Either
   delete it or make implicit use it. (What's left of AIML-2705's scope.)
5. ~~**Two BigQuery env flags**~~ — **closed by AIML-2750.** `BIGQUERY_ENABLED`
   and `VOICE_NOTES_BQ_ENABLED` are both gone; there is one flag,
   `BQ_ANALYTICS_ENABLED`.
6. **Restore verifiability** — new, and the most urgent of these. The project
   has no assertable test of any kind since the `/api/v1` layer was deleted.
   See §5. Not really a product decision, but it needs someone to own it.

---

## 8. Document index

| File | Contents |
|---|---|
| `HANDOFF.md` | this file — start here |
| `plan-after-implicit-decision.md` | **current work**: remove guided, then Jeremy's two requirements |
| `stories-after-guided-removal.md` | the six follow-up stories, re-scoped |
| `architecture-notes.md` | why the review found so much; Live API vs our layers; what BigQuery is for |
| `PR5-comment-replies.md` | every review comment, matched to its thread, with reply text |
| `PR5-response.md` | cause → fix → evidence per finding |
| `PR5-review-findings.md` | the original triage of the 25 comments |
| `PR5-test-plan.md` / `PR5-test-results.md` | how PR #5 was tested, and what passed |
| `change-log.md` | every change, why, verification status |
| `AIML-2698-gap-findings.md` | 18 gaps, repro method, priorities |
| `AIML-2698-experiments.md` | reproductions, findings F1-F5, the 9-case REST suite |
| `far-notes-dataset-analysis.md` | real FAR notes: what they break |
| `status-updates.md` | ticket portfolio + day-by-day log |
| `note-disposition-registry-gap.md` | draft to the lead re the registry |
