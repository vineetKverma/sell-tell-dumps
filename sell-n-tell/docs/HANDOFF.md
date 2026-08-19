# SellNTell — session handoff

Resume with no prior context. Read this, then `PR5-review-findings.md` (the
current work queue), `change-log.md` (what we changed and why), and
`AIML-2698-gap-findings.md` (the 18-gap analysis).

---

## ✅ START HERE — PR #5 is open with changes requested

**Branch: `feature/AIML-2698-on-2130`** → `development`, PR
[#5](https://bitbucket.org/fm_ebiz/sell-n-tell/pull-requests/5), tip `e67fc9c`.
Working tree clean, everything pushed.

`development` has been merged into the branch; the four conflicts
(`main.py`, `app.js`, `mock_db.py`, plus a silently-dropped `db_interface`
import) are resolved and verified.

**Suresh reviewed it on 2026-08-19 and requested changes — 25 comments.**
They are catalogued in **`docs/PR5-review-findings.md`**, grouped:

| Group | Count | Action |
|---|---|---|
| **A — correctness** | 10 | **Fix in this PR.** A1–A3 and A6 are data loss or wrong data. |
| **B — design / duplication** | 11 | Raise one follow-up ticket. B1 first. |
| **C — cosmetic** | 4 | Formatter pass. |
| **D — positive** | 1 | No action. |

### The work queue, in order

1. **A1 — BigQuery backend is broken and bypasses every gate.** Highest
   priority. `bigquery_db.commit_notes(session_id, confirmed)` takes none of the
   kwargs `main.py` now passes, so **every commit under `BIGQUERY_ENABLED=true`
   raises `TypeError`**. And it never calls `compute_missing_topics`, never
   checks `superseded_by`, and has no idempotency guard — so the coverage gate
   (AIML-2698) *and* the supersede gate (AIML-2703) are both absent on that
   backend, and a retry mints a duplicate CRM record. Since Salesforce syncs
   from this API's response, not from BigQuery, the headline guarantees of two
   tickets are silently untrue there.
   **Fix shape:** have `bigquery_db.commit_notes` delegate all gating to
   `mock_db.commit_notes` and only own the BigQuery insert.
2. **A2, A3 — duplicate CRM records in guided**, by two routes neither the 2703
   fix nor the idempotency guard catches. A2 is a check-then-act race on
   `_S_COMMIT_RESULT`; A3 is that same key never being cleared between
   dictations, so the rep's *second* visit of a shift gets told "saved" while
   nothing was staged.
3. **A6, A7 — defects we introduced in this PR.** A6: the resampler never
   flushes its tail buffer, so the last syllable of every dictation is dropped.
   A7: `crypto.randomUUID()` throws at module load on plain HTTP, breaking the
   whole frontend. Neither showed up in testing because we only ever ran on
   `localhost`, which counts as a secure context.
4. **A4, A5, A8, A9, A10** — contract violations. See the findings doc.
5. **B** — one follow-up ticket. Lead with **B1**: the stale `CRMStore` Protocol
   is *why* A1 was invisible to type-checking.

### Also still open

- **Tell Sainitheesh** about the rebase, that his `c6860bd` closed one of our
  documented gaps (Gap 18), and that our Gap 6 fix touches his guided flow.
- **F7** — `_topic_matches` uses substring containment, so an inflected label
  ("Appliance Contract Renewal" vs planned "Appliances") reports the topic
  uncovered and can produce two rows for one discussion. Open; demo mitigation
  is phrasing discipline.
- **Invented skip reasons** — the agent still writes "due to time constraints"
  when the rep gave no reason, despite a prompt rule naming that exact phrase.
  Needs a server-side fix; prompt text has been measured not to work.

---

## 1. Ticket status

| Ticket | Title | Status |
|---|---|---|
| **AIML-2698** | Disposition + State Correctness | **Closed.** Delivered in PR #5 |
| **AIML-2705** | Disposition Quality Guardrails | **Closed.** ACs 1/2/5 delivered; AC4 took its "documents residual risk" clause; AC3 met with 3 cases |
| **AIML-2703** | Correction & Re-stage Reliability | **Done, in PR #5.** Orphan bug reproduced, fixed, regression-tested |
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
  else `mock_db`. Exposes it as `db`. **Its `CRMStore` Protocol is stale (B1).**
- `bigquery_db.py` — delegates config/staging to `mock_db`, owns only the
  committed sink. **Currently missing every guard (A1).**
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
# on the VDI, from the repo root (copy tools/export-repo-md.ps1 there first)
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

1. `index.html` loads `app.js?v=N`. **Bump N** when you change the file — the
   browser caches by full URL, so a new file at the same URL is invisible.
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
**`guided/ambiguous_disposition` is intermittent (~2 in 3)** — it exercises the
deliberately confusing 3-strikes path. Re-run before calling a failure a
regression.

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
| `PR5-review-findings.md` | **the current work queue** — 25 review comments, triaged |
| `change-log.md` | every change, why, verification status |
| `AIML-2698-gap-findings.md` | 18 gaps, repro method, priorities |
| `AIML-2698-experiments.md` | reproductions, findings F1–F5, the 9-case REST suite |
| `demo-golden-path.md` | scripted demo scenarios per mode and campaign |
| `demo-runbook-failure-modes.md` | failure modes & recovery for the demo driver |
| `far-notes-dataset-analysis.md` | real FAR notes: what they break |
| `status-updates.md` | ticket portfolio + day-by-day log |
| `note-disposition-registry-gap.md` | draft to the lead re the registry |
