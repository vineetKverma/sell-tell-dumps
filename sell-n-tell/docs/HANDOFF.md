# SellNTell — session handoff

Resume with no prior context. Read this first — it says what to do next and
why. Then `plan-after-implicit-decision.md` for the current piece of work, and
`change-log.md` for what changed and why.

---

## ✅ START HERE — AIML-2751, rebuilt on a rewritten `development`

Current as of 2026-09-07. Read this whole section before touching anything —
`development` is not the codebase this file described a week ago.

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

### The remaining work

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

### To resume with the assistant

The local copy at `c:\Personal Storage\poc\sellNtell\sell-n-tell` is still the
**old** structure and cannot be used to edit the new files. A fresh export is
already sitting in `c:\Personal Storage\poc\sellNtell\_export` (10 markdown
files). Import it first:

```powershell
cd "c:\Personal Storage\poc\sellNtell"
.\tools\import-repo-md.ps1 -In .\_export -Dest .\sell-n-tell
python tools\fix_mojibake.py --write
```

The second line is not optional — the import decodes UTF-8 as the Windows ANSI
codepage and mangles every emoji and box-drawing character. `.gitignore` is now
in its target list too.

**Note the import never deletes.** Files removed upstream (`mock_db.py`,
`db_interface.py`, `bigquery_db.py`, `bigquery_sink.py`) will still be sitting
in the local copy after importing, and must be deleted by hand or they will
mislead. Same trap that left the guided files behind on the app machine.

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
uv run python scripts/ws_smoke_test.py implicit
```

Then one browser dictation end to end, hard-reloaded, producing one CRM record.
Note the smoke harness prints a transcript, not a pass/fail — count the
committed records:

```powershell
$r = (Invoke-RestMethod -Uri "http://localhost:8000/api/v1/notes/committed").records
"TOTAL: $($r.Count)"
$r | Group-Object ws_session_id | Where-Object Count -gt 1   # must print nothing
```

The record store resets on restart, so note the baseline first. The scenario
count and the harness itself changed in the rewrite — check what
`ws_smoke_test.py` actually defines now rather than assuming seven.

**`scripts/test_correction_reliability.py` is gone.** It was 16 assertions
covering the supersede gate, retry idempotency and correction chains, and passed
on 2026-08-21 — only a stale `.pyc` remains in `scripts/__pycache__/`. Check
whether it survived on the app machine; if not it is worth rewriting, because
the smoke suite would still pass with the supersede gate deleted.

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
| **AIML-2751** | Remove the guided flow | **PR #6 open, changes requested.** Branch reset onto the rewritten `development`; work to redo — see START HERE |
| **AIML-2750** | CRM backend decision (Dharun) | **Closed, merged as PR #7 `6ffd86f`.** Delivered as a full re-architecture: `mock_db`/`db_interface`/`bigquery_db`/`bigquery_sink` deleted, `notes_workflow.py` + `schemas.py` + YAML resources added |
| **AIML-2698** | Disposition + State Correctness | **Closed.** Delivered in PR #5 |
| **AIML-2705** | Disposition Quality Guardrails | **Closed.** ACs 1/2/5 delivered; AC4 took its "documents residual risk" clause; AC3 met with 3 cases |
| **AIML-2703** | Correction & Re-stage Reliability | **Closed.** All 5 ACs met. Supersede-gate coverage is `scripts/repro_orphan_restage.py` (exit 0 = gate holds), *not* the `test_correction_reliability.py` this table used to name — that script does not exist |
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

> ⚠️ **Stale below this line.** This section describes the pre-AIML-2750
> structure — `mock_db.py`, `db_interface.py`, `bigquery_db.py` and
> `bigquery_sink.py` no longer exist. The storage and config layer is now
> `notes_workflow.py` + `schemas.py` + `resources/*.yaml`. The WS/ADK/Live flow
> at the top is still accurate. Rewrite this section once the local copy is
> re-imported from `_export`.

```
browser mic (16 kHz Int16 PCM, 20 ms chunks)
   │  WS /ws/{user_id}/{session_id}?campaign_type=&planned_topics=&agent_mode=
   ▼
FastAPI upstream_task ──> ADK LiveRequestQueue ──> Gemini Live (Vertex, native audio)
                                                        │
                          downstream_task <── events ───┘
                                ├─ function_call → tools.py → HTTP POST → own REST API → db
                                └─ audio chunks  → WS → browser playback
```

**The tools never touch the store.** They HTTP-call the app's own `/api/v1`
endpoints, so **all enforcement belongs in the REST layer** — implicit, guided
and hybrid inherit it for free. It's also why gaps reproduce with plain HTTP
calls, no mic and no model.

**Storage indirection (new, from `development`):**

- `db_interface.py` — `get_db()` returns `bigquery_db` when `BIGQUERY_ENABLED=true`,
  else `mock_db`. Exposes it as `db`. `CRMStore`'s signatures are now correct;
  the rest of B1 (it declares `self` on methods a *module* has to satisfy)
  stands.
- `bigquery_db.py` — delegates config/staging **and all commit gating** to
  `mock_db`, owns only the BigQuery insert (A1 fix). Gates are inherited by
  delegation; don't re-implement one here.
- `config.py` — just `API_BASE`.
- **Two BigQuery flags:** `db_interface` reads `BIGQUERY_ENABLED`,
  `bigquery_sink` reads `VOICE_NOTES_BQ_ENABLED`. One feature, two switches.

**Modes** (`agent_mode`, one `Runner` each):
- `implicit` — `agent.py` + `tools.py`, 2 tools, ~2 rep turns. **The only mode.**
- `guided` — 5 tools, ~8 turns. Removed in AIML-2751; recoverable from the tag
  `archive/guided-flow`.
- hybrid exists on `feature/AIML-2686` — not ours

On identical input the two modes produced **identical dispositions**; they
differed only in how much the rep was asked, which is why guided went.
`agent_mode` survives the removal as a parameter, on the committed record, and
as the BigQuery sink's table key.

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
PCM noise. Watch for `commit_visit_notes BLOCKED:`, `Staging rejected for
campaign_type=`, `Commit BLOCKED for session_id=`.

---

## 5. Tests

> ⚠️ **Partly stale.** `ws_smoke_test.py` changed in the rewrite (guided
> scenarios removed, `agent_mode` no longer sent) — check what it defines now
> rather than trusting the counts below.

**Conversational harness** (no mic, real WebSocket, text turns):

```powershell
uv run python scripts/ws_smoke_test.py implicit   # 7 scenarios
uv run python scripts/ws_smoke_test.py implicit --scenario clean_save
```

Bar: every scenario commits, one CRM record each, no duplicates.

**One scenario is intermittent — re-run before calling a failure a regression:**

- `correction_summary` — on 2026-08-21 it missed once in a full run and
  committed on its own re-run, no code change in between. Model
  non-determinism, same family as Gap 6/F5 (see `change-log.md`, Batch N).

The committed-record count is in-memory, so **a server restart resets it to 0**.
Always note the baseline before reading a count as a failure.

**Counting the result is the real check**, not the transcript — the harness
prints a live log and no pass/fail summary:

```powershell
$r = (Invoke-RestMethod -Uri "http://localhost:8000/api/v1/notes/committed").records
"TOTAL: $($r.Count)"                                    # expect 7
$r | Group-Object agent_mode | Select-Object Name, Count # implicit 7
$r | Group-Object ws_session_id | Where-Object Count -gt 1   # must print nothing
```

The third line is the duplicate check: each scenario opens its own
`ws_session_id`, so any group above 1 is two CRM records for one visit.

**No automated coverage for the AIML-2703 supersede gate.** A repro script was
written to prove the orphan bug (stage → correct → commit the *old* id, expect
409) and deliberately **not kept in the repo** — it existed to diagnose, and the
bug is fixed. Worth knowing: the smoke suite exercises the correction path but
never tries to commit a superseded draft, so if that gate regressed, all six
implicit scenarios would still pass. Fold an assertion into the REST suite if
the gate is ever in question.

**REST suite** — 9 cases, ~15 min, no mic or model. Paste-able block in
`AIML-2698-experiments.md`. Covers the coverage gate (409), campaign rules
(422), happy path, skip-after-reminder, manual review, self-skip rejection.

Harness gap: it **hardcodes `campaign_type=standard_sales`**, so none of the
`enterprise_field` golden-path scenarios are covered. Adding `--campaign` is
step one for AIML-2702.

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
4. **Two flag shapes** — guided uses null code + `needs_manual_review`, implicit
   uses code 99. Unify (this is what's left of AIML-2705's scope).
5. **Two BigQuery env flags** — `BIGQUERY_ENABLED` vs `VOICE_NOTES_BQ_ENABLED`.

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
