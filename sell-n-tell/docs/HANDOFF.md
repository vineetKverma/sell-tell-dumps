# SellNTell — session handoff

Resume with no prior context. Read this, then `PR5-review-findings.md` (the
current work queue), `change-log.md` (what we changed and why), and
`AIML-2698-gap-findings.md` (the 18-gap analysis).

---

## ✅ START HERE — PR #5 review is answered

**Branch: `feature/AIML-2698-on-2130`** → `development`, PR
[#5](https://bitbucket.org/fm_ebiz/sell-n-tell/pull-requests/5).

Suresh reviewed it on 2026-08-19 — 25 comments. **All answered.**

| Group | Count | State |
|---|---|---|
| **A — correctness** | 10 | Fixed, tested, replied. 9 resolved; the read-modify-write one left open deliberately |
| **B — design / duplication** | 11 | 1 delivered here; the other 10 are four stories in `PR5-followup-stories.md` |
| **C — cosmetic** | 4 | Done |
| **D — positive** | 1 | No action |

Per-thread status and reply text: `PR5-comment-replies.md`.
Cause → fix → evidence per finding: `PR5-response.md`.
Test method and results: `PR5-test-plan.md`, `PR5-test-results.md`.

### What still needs doing

1. **Post the top-level summary comment and re-request review.** Four replies say
   something the reviewer didn't, and those threads are now collapsed — the
   summary is the only place they stay visible. Text is at the bottom of
   `PR5-comment-replies.md`.
2. **Raise the four follow-up stories** in `PR5-followup-stories.md` (18 points,
   suggested order 3 → 1 → 2 → 4), then swap the real ids into the B replies and
   post them.
3. **Tell Sainitheesh** about the rebase, that his `c6860bd` closed Gap 18, and
   that our Gap 6 fix touches his guided flow.

### Worth carrying forward

Four fixes diverged from what the comment asked — say so rather than being
silently different:

- The BigQuery backend was missing **three** gates (coverage, supersede,
  idempotency), not the one flagged. Fixing it also required correcting the
  `CRMStore` signatures, since a stale Protocol is what let the mismatch pass
  type-checking.
- The resampler flush belongs at the `micActive` transitions; `stopMicrophone`
  is never called by `app.js`. The stranded samples were also being spliced onto
  the *next* turn, not merely dropped.
- `campaign_type` needed fixing inside `mock_db.commit_notes`, not at the
  `main.py` read site — the field it was told to trust was itself populated from
  the caller.
- The guided read-modify-write race cannot occur as described (no `await` in
  that sequence under asyncio). The in-place state mutation underneath it is
  real and is fixed.

Two deliberate trade-offs:

- **Rotating `session_id` per dictation gives up the warm socket.** Measured
  45.6s / 59.2s / 36.6s across three consecutive dictations, so no consistent
  cold-start penalty in practice.
- **Committed records now stay in `_STAGED_NOTES`.** Deleting them was what made
  the idempotent-retry branch unreachable. This makes the session-state eviction
  story more valuable, not less.

Found during testing, not in the review: the planning panel stayed locked after
a save; the `?v=` cache-buster never covered `app.js`'s imported modules; and the
secure-context guard was on the wrong call (`AudioWorklet` fails before
`getUserMedia`). All three fixed.

### Also still open

- **F7** — `_topic_matches` uses substring containment, so an inflected label
  ("Appliance Contract Renewal" vs planned "Appliances") reports the topic
  uncovered and can produce two rows for one discussion.
- **Invented skip reasons** — the agent still writes "due to time constraints"
  when the rep gave no reason, despite a prompt rule naming that exact phrase.
  Needs a server-side fix; prompt text has been measured not to work.

---

## 1. Ticket status

| Ticket | Title | Status |
|---|---|---|
| **AIML-2698** | Disposition + State Correctness | **Closed.** Delivered in PR #5 |
| **AIML-2705** | Disposition Quality Guardrails | **Closed.** ACs 1/2/5 delivered; AC4 took its "documents residual risk" clause; AC3 met with 3 cases |
| **AIML-2703** | Correction & Re-stage Reliability | **Closed.** All 5 ACs met; supersede gate now regression-tested in `scripts/test_correction_reliability.py` |
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
- `implicit` — `agent.py` + `tools.py`, 2 tools, ~2 rep turns
- `guided` — `agent_guided.py` + `tools_guided.py`, 5 tools, ~8 turns
- hybrid exists on `feature/AIML-2686` — not ours

On identical input both modes produce **identical dispositions**; they differ in
how much the rep is asked.

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
   file at the same URL is invisible. Currently `v=7`.

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

**Conversational harness** (no mic, real WebSocket, text turns):

```powershell
uv run python scripts/ws_smoke_test.py implicit   # 6 scenarios
uv run python scripts/ws_smoke_test.py guided     # 4 scenarios
uv run python scripts/ws_smoke_test.py guided --scenario clean_save
```

Bar: every scenario commits, one CRM record each, no duplicates.

**Two guided scenarios are intermittent — re-run before calling a failure a
regression:**

- `ambiguous_disposition` (~2 in 3) — exercises the deliberately confusing
  3-strikes path.
- `rerecord` — observed failing to commit once on 2026-08-19, then passing on an
  immediate re-run with no code change in between. Model non-determinism in the
  guided flow, same family as Gap 6/F5.
- `implicit/correction_summary` — same pattern on 2026-08-21: missed once in a
  full run, committed on its own re-run.

The committed-record count is in-memory, so **a server restart resets it to 0**.
Always note the baseline before reading a count as a failure.

**Counting the result is the real check**, not the transcript — the harness
prints a live log and no pass/fail summary:

```powershell
$r = (Invoke-RestMethod -Uri "http://localhost:8000/api/v1/notes/committed").records
"TOTAL: $($r.Count)"                                    # expect 10
$r | Group-Object agent_mode | Select-Object Name, Count # implicit 6, guided 4
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
| `HANDOFF.md` | this file |
| `PR5-review-findings.md` | 25 review comments, triaged, with the fix for each |
| `PR5-response.md` | cause → fix → evidence per finding, plus the four root-cause themes |
| `PR5-comment-replies.md` | **paste-able inline reply text** for all 25 comments, per section |
| `change-log.md` | every change, why, verification status |
| `AIML-2698-gap-findings.md` | 18 gaps, repro method, priorities |
| `AIML-2698-experiments.md` | reproductions, findings F1–F5, the 9-case REST suite |
| `demo-golden-path.md` | scripted demo scenarios per mode and campaign |
| `demo-runbook-failure-modes.md` | failure modes & recovery for the demo driver |
| `far-notes-dataset-analysis.md` | real FAR notes: what they break |
| `status-updates.md` | ticket portfolio + day-by-day log |
| `note-disposition-registry-gap.md` | draft to the lead re the registry |
