# SellNTell — session handoff

Resume with no prior context. Read this first — it says what to do next and
why. Then `plan-after-implicit-decision.md` for the current piece of work, and
`change-log.md` for what changed and why.

---

## ✅ START HERE — AIML-2751 code is done; it needs pushing and testing

Current as of 2026-09-07. Read this whole section before touching anything —
`development` is not the codebase this file described a week ago.

### Where this stands right now

The local copy has been re-imported from `_export` and the AIML-2751 work is
**committed locally as `3d0229f`** (the WIP that preceded it is `a3051f8`).
What was done, against the sections below:

- **Steps 1–4 are all done.** Both guided files deleted; the four modules
  AIML-2750 removed upstream (`mock_db.py`, `db_interface.py`,
  `bigquery_db.py`, `bigquery_sink.py`) deleted too, since the importer never
  deletes and they had survived the import; `app.js` stripped; the asset
  version bumped 9 → 10 in `index.html` **and** in `app.js`'s two module
  imports; `.gitignore` split and given its trailing newline.
- **Fewer comments needed changing than step 3 predicted.** `main.py`,
  `tools.py`, `agent.py` and `ws_smoke_test.py` already read "retired" after
  the rewrite. Only `notes_workflow.py` and `behavioral_rules.yaml` still said
  "being retired separately". `schemas.py`'s `needs_manual_review` description
  was also updated to explain why a guided-only field survives.
- **One extra deletion in `app.js`** worth knowing about at review time: the
  early return on `resp.status === "next_topic" || resp.error ===
  "no_reply_heard"` went too. Neither value is emitted anywhere any more —
  both were `tools_guided`'s. `tools.py`'s turn-guard refusal is
  `no_confirmation_heard`, which the normal refusal path already handles.

**Still to do:** push, reply on PR #6, and run the tests — but read
"Testing is more broken than this file says" first, because the commands in
§5 no longer work.

### ⚠️ Testing is more broken than this file says

**The entire `/api/v1` REST layer is gone.** `main.py` now serves exactly two
routes, `/healthz` and `/`. The tools call `notes_workflow` in-process; there
is no HTTP hop and no REST surface at all. Three things in this file depend on
that layer and are now dead:

1. **`Invoke-RestMethod .../api/v1/notes/committed`** — the "count the result
   is the real check" step in §5 and in the Testing section below. There is no
   such endpoint, and `notes_workflow` has no `list_committed` at all.
   Committed records live only as `_STAGED_NOTES[session_id]["committed"] =
   True` in process memory. **There is currently no way to verify a smoke run
   other than reading the transcript.** Restoring a count means either a small
   read-only debug endpoint or querying the BigQuery audit table the ADK
   plugin writes.
2. **`scripts/repro_orphan_restage.py`** — the supersede-gate coverage the
   AIML-2703 row below names. It drives `http://localhost:8000/api/v1`, so it
   cannot run. It is also local-only (not in the export manifest, so not on
   the branch). AIML-2703's supersede gate now has **no** executable coverage
   of any kind.
3. **The 9-case REST suite** in `AIML-2698-experiments.md` — same cause.

Also: **`ws_smoke_test.py` takes no positional argument now.** The documented
`uv run python scripts/ws_smoke_test.py implicit` fails on argparse. It is
just `uv run python scripts/ws_smoke_test.py`, optionally `--scenario NAME`
or `--raw`. Seven scenarios survive: `clean_save`, `correction`,
`correction_summary`, `correction_disposition`, `correction_add_topic`,
`missing_topic`, `multi_topic`.

None of this is AIML-2751's doing — it all landed with AIML-2750 — but it
means the project currently has no automated verification of anything. Worth
raising alongside the scope point for Sai below.

**Verified still intact** in `notes_workflow.commit_notes` after the import:
the idempotency replay, the supersede gate (`SupersededRecordError`), and the
coverage gate (`IncompleteCoverageError`), in that order, with the ordering
comments from PR #5 carried over. `python -m compileall app scripts` is clean
and `node --check app/static/js/app.js` passes.

### What happened

**AIML-2750 (Dharun, PR #7) turned into a full re-architecture and is merged.**
Four commits, 19 files, +2018 / −2421 between `9433908` and `6ffd86f`:

| Deleted | Added |
|---|---|
| `mock_db.py` (954 lines) | `notes_workflow.py` (678) |
| `db_interface.py` | `schemas.py` (125) |
| `bigquery_db.py` | `resources/dispositions.yaml` (137) |
| `bigquery_sink.py` | `resources/behavioral_rules.yaml` (161) |

`main.py`, `agent.py`, `tools.py` and `app.js` were rewritten. The disposition
registry now lives in YAML rather than Python.

**The PR #5 gates survived.** Verified directly against
`origin/development:app/voice_notes_agent/notes_workflow.py` — it contains
`compute_missing_topics`, `IncompleteCoverageError`, `SupersededRecordError`,
the `Commit BLOCKED … superseded by` path, the
`already committed -- returning` idempotency replay, and the
`previous_session_id … is already committed` correction-base guard. Our comments
were carried over verbatim. Nothing to escalate.

**The guided flow was NOT removed** — `tools_guided.py` and `agent_guided.py`
are still on `development` and now import from the deleted `mock_db.py`, so they
are broken dead code on the mainline. AIML-2751 is still needed. This is exactly
what Suresh's third review comment was describing.

### Current branch state — two things were lost

`feature/AIML-2751-remove-guided` was **`git reset --hard origin/development`**,
so it now sits at `6ffd86f` with no local commits. That discarded:

1. **`b5ee250`** — the original guided removal. Obsolete anyway; it edited
   `mock_db.py`, which no longer exists. Recoverable by SHA if ever wanted.
2. **`dce35cb`** — the `.gitignore` fix. **Needs redoing** (see below).

### The work — all done in `3d0229f`

Kept below as the record of what AIML-2751 actually changed.
Much smaller than before — the rewrite already retired guided from the backend.

**1. Delete two files**

```
app/voice_notes_agent/tools_guided.py
app/voice_notes_agent/agent_guided.py
```

**2. Strip guided from `app.js`** — this is the real work, ~15 sites:
`guidedPayload` (declared ~L1034, built ~L1016-1096, read ~L1579),
`resetGuidedPayload()`, `commit_guided_notes` in the tool-name conditionals
(~L1006, ~L1056), and the `record_topic_disposition` handling around ~L1067-1096.
Remember to bump the version in `index.html` **and** in `app.js`'s module
imports — they must match.

**3. Update ~8 comments** that say guided is "being retired separately" to say
it is retired: `main.py` ~L184, `notes_workflow.py` ~L26 / ~L166 / ~L588,
`resources/behavioral_rules.yaml` ~L11-12, `tools.py` ~L6,
`scripts/ws_smoke_test.py` ~L8 / ~L212. (`agent.py`'s docstring already says
"implicit flow only -- guided flow retired".)

**4. Redo the `.gitignore` fix.** `development`'s last line is the concatenated
`app.voice_notes_agentcommitted_notes.json` — `committed_notes.json` was
appended to a file with no trailing newline. Split into two lines **and add a
trailing newline**, which is the actual root cause:

```powershell
$t = [IO.File]::ReadAllText(".gitignore")
if (-not $t.EndsWith("`n")) { [IO.File]::WriteAllText(".gitignore", $t + "`n") }
```

**Nothing to do in `index.html`** — the mode selector is already gone.

### Not ours, but worth raising

`scripts/bigquery_create_tables.sql` and `scripts/bigquery_schema.json` still
define a `guided_flow_calls` table and an `agent_mode` column, but
`bigquery_sink.py` was deleted in the rewrite, so nothing writes to them. Loose
end from AIML-2750.

### To resume with the assistant — ✅ already done

Left here because the next export will need the same steps. The local copy at
`c:\Personal Storage\poc\sellNtell\sell-n-tell` **has been** re-imported from
`c:\Personal Storage\poc\sellNtell\_export` and now matches `6ffd86f` plus the
AIML-2751 changes. The commands were:

```powershell
cd "c:\Personal Storage\poc\sellNtell"
.\tools\import-repo-md.ps1 -In .\_export -Dest .\sell-n-tell
python tools\fix_mojibake.py --write
```

The second line is a safety net, not a fix — `import-repo-md.ps1` now reads
with `-Encoding UTF8` explicitly, so this import produced **no** mojibake and
`fix_mojibake.py` reported everything clean. Keep running it anyway; it is
idempotent and costs nothing. Two gotchas: it must be run **from the repo
root** (`sell-n-tell/`), not the parent — its `TARGETS` are repo-relative and
it silently prints `skip … (not found)` otherwise; and its target list covers
only `.gitignore` and the frontend, so pass the Python/YAML files as arguments
if you want them checked (they were, and were clean).

**Note the import never deletes.** Files removed upstream (`mock_db.py`,
`db_interface.py`, `bigquery_db.py`, `bigquery_sink.py`) were still sitting in
the local copy after importing and had to be deleted by hand — they are gone
as of `3d0229f`. Same trap that left the guided files behind on the app
machine. A quick check after any future import: diff the tree against
`_export/_manifest.md`, which lists every file the branch actually has.

### Then

Commit, push, and reply on PR #6. Suggested reply to the top-level comment:

> Rebuilt this branch on the current `development` now that AIML-2750 is in.
> The earlier diff was reading against a base that had moved, which is why it
> looked like it was reverting your changes. `tools_guided.py` and
> `agent_guided.py` are deleted here, along with the remaining guided handling
> in `app.js`.

The other two review comments (`.gitignore`, `agent_guided.py`) are both
addressed by this work — reply once it is pushed and the file list is visible.

### Testing

With the server running (no `--reload`):

```powershell
uv run python scripts/ws_smoke_test.py                       # all 7 scenarios
uv run python scripts/ws_smoke_test.py --scenario clean_save
```

No positional argument — the `implicit` this file used to pass now fails on
argparse.

Then one browser dictation end to end, hard-reloaded (the asset version is
`v=10` now), producing one CRM record.

**Read the transcript, because there is nothing else to read.** The
`/api/v1/notes/committed` count this section used to prescribe no longer
exists — see "Testing is more broken than this file says" above. Watch the
server log for `Commit BLOCKED for session_id=` and confirm each scenario
reaches a `commit_visit_notes` response with `status: "success"` exactly once.

**`scripts/test_correction_reliability.py` is gone**, and its stand-in
`scripts/repro_orphan_restage.py` cannot run either (it needs the deleted REST
layer). The supersede gate therefore has no executable coverage at all: the
smoke suite would still pass with that gate deleted, because the model always
commits the record it just staged and never the one it replaced. Restoring
coverage means an in-process test calling `notes_workflow.stage_notes` /
`commit_notes` directly — which is now easy, since there is no HTTP hop to
stand up.

### Guided is preserved

Tag `archive/guided-flow` on `9433908`, pushed, verified to contain both files:

```powershell
git checkout archive/guided-flow -- app/voice_notes_agent/tools_guided.py
```

### After AIML-2751

From `stories-after-guided-removal.md`, adjusted — Story 6 is delivered by
AIML-2750 and Story 3 is likely moot now that there is one store:

1. **Story 1** — consolidate campaign rules, *before* vertical-market context
   adds a second config dimension. Re-check its scope first: the rewrite moved
   the registry into YAML and may have closed part of it already.
2. **Event type interpretation** — Jeremy's first refinement. Root cause in
   `plan-after-implicit-decision.md` §2: event types carry no mapping keywords
   while disposition codes do. **Re-verify against `dispositions.yaml`** — the
   rewrite may have changed this.
3. **AIML-2702 + AIML-2733** — eval harness and golden set. These gate the
   vertical-market work.
4. **Vertical market context** — Jeremy's second refinement.

**All six follow-up stories need re-checking against the new structure** before
anyone picks one up. They were written against `mock_db.py`, which is gone.

### Process point for Sai

Our intended order was AIML-2751 before AIML-2750, because removing guided
shrinks the surface everyone else works on. That ordering lived only in our docs
— not in Jira, not as a blocker link, not in either PR description — so there
was no way for it to be honoured. The cost was one obsolete commit, not lost
work.

Separately: AIML-2750 was scoped as "decide where CRM records live" and
delivered a re-architecture of the storage and config layer. Worth agreeing how
scope changes of that size get flagged, since it invalidated a branch in review
and every follow-up story written against the old structure.

---

## 1. Ticket status

| Ticket | Title | Status |
|---|---|---|
| **AIML-2751** | Remove the guided flow | **PR #6 open, changes requested. Code done locally (`3d0229f`), not yet pushed.** Rebuilt on the rewritten `development` — see START HERE |
| **AIML-2750** | CRM backend decision (Dharun) | **Closed, merged as PR #7 `6ffd86f`.** Delivered as a full re-architecture: `mock_db`/`db_interface`/`bigquery_db`/`bigquery_sink` deleted, `notes_workflow.py` + `schemas.py` + YAML resources added |
| **AIML-2698** | Disposition + State Correctness | **Closed.** Delivered in PR #5 |
| **AIML-2705** | Disposition Quality Guardrails | **Closed.** ACs 1/2/5 delivered; AC4 took its "documents residual risk" clause; AC3 met with 3 cases |
| **AIML-2703** | Correction & Re-stage Reliability | **Closed, but now uncovered.** All 5 ACs met in code (the gate is verified present in `notes_workflow.commit_notes`). `scripts/repro_orphan_restage.py`, named here as the coverage, drives the `/api/v1` layer AIML-2750 deleted, so it cannot run — and it is local-only, not on the branch |
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
