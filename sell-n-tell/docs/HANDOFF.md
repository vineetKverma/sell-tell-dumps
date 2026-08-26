# SellNTell — session handoff

Resume with no prior context. Read this first — it says what to do next and
why. Then `plan-after-implicit-decision.md` for the current piece of work, and
`change-log.md` for what changed and why.

---

## ✅ START HERE — next task is removing the guided flow

**PR #5 is merged into `development`.** The review is fully answered: all 10
correctness findings fixed and verified, cosmetics done, and the remaining
design findings scoped into six follow-up stories.

The FAR research group has chosen **the implicit model** (Jeremy, 2026-08-18),
so guided mode is out of scope. Removing it is the next piece of work, and it
makes several of the follow-up stories smaller — do it before them, not after.

### The plan

1. **Pull `development`** and tag the current tip *before* deleting anything —
   that tag is how guided comes back if it is ever needed. See
   "Preserving guided" below.
2. **Branch from `development`**:
   `feature/AIML-2751-remove-guided`
3. **Delete guided** — scope and acceptance criteria are in
   `plan-after-implicit-decision.md` §5 (AIML-2751).
4. **Test** — implicit smoke suite, the correction suite, and one browser
   dictation end to end.
5. **Raise the PR** into `development`.

### Preserving guided so it can come back

**Use an annotated git tag, not a branch and not a feature flag.**

Before the removal branch is cut, from an up-to-date `development`:

```powershell
git checkout development
git pull
git tag -a archive/guided-flow -m "Last commit containing the guided flow (tools_guided.py, agent_guided.py). Removed because the FAR research group selected the implicit model, 2026-08-18. See docs/plan-after-implicit-decision.md."
git push origin archive/guided-flow
```

Recovering a file later is then one command:

```powershell
git checkout archive/guided-flow -- app/voice_notes_agent/tools_guided.py
```

**Why a tag rather than the alternatives:**

- *A long-lived branch* looks maintained. Someone will eventually merge
  `development` into it, or wonder why it is behind.
- *Keeping the files behind a flag* is exactly what `bigquery_db.py` was: dead
  code that read as a working alternative, shipped with three missing gates, and
  cost a review cycle to find. Do not repeat it.
- *A tag* costs nothing, cannot drift, and is unambiguous about being an
  archive.

**What is actually worth preserving is not the code.** If guided ever returns it
will be rewritten against whatever the code looks like then. What must not be
lost is what building it taught us, and that lives in docs, not in
`tools_guided.py`:

- **Gap 6 / F5** — asked to make a second tool call when it has nothing left to
  say, the model ends its turn instead. The record is complete and nothing is
  saved, with no signal. This is why the last disposition commits inline.
- **The `allow_skips` deadlock** (observed live 2026-08-11) — guided asks about
  a topic, the rep says they skipped it, and the first staging call then reports
  that same topic as uncovered, so the commit 409s and the agent asks again.
- **The 3-strikes disposition path** — after three failed confirm attempts,
  record `needs_manual_review` rather than guessing a code.
- **Two flag shapes for manual review** — guided used a null code plus
  `needs_manual_review`; implicit uses code 99. Worth knowing if a second flow
  is ever added.

These are already written down in `change-log.md`, `AIML-2698-gap-findings.md`
and the comments in `mock_db.py`. Check they survive the deletion — the ones
living in `tools_guided.py` comments will not.

### After guided is removed

Suggested order, from `stories-after-guided-removal.md`:

1. **Story 6** — decide where CRM records actually live. May delete Story 3.
2. **Story 1** — consolidate campaign rules, *before* vertical-market context
   adds a second config dimension.
3. **Event type interpretation** — Jeremy's first refinement. Small and
   directly asked for. See `plan-after-implicit-decision.md` §2.
4. **AIML-2702 + AIML-2733** — eval harness and golden set. These gate the
   vertical-market work, since "recognises vertical-specific patterns" cannot be
   checked by the smoke suite.
5. **Vertical market context** — Jeremy's second refinement.
6. Stories 2, 4, 5 as capacity allows.

### Still open, not yet ticketed

- **F7** — `_topic_matches` uses substring containment, so an inflected label
  ("Appliance Contract Renewal" vs planned "Appliances") reports the topic
  uncovered and can produce two rows for one discussion.
- **Invented skip reasons** — the agent still writes "due to time constraints"
  when the rep gave no reason. Prompt wording was measured over six runs and
  made no difference; needs a server-side fix.
- **Registry content gap** — no code expresses "renewal agreed", "quote
  created", or "no contact made"; roughly a quarter of real visits. Product
  decision, in `note-disposition-registry-gap.md`.
- **Tell Sainitheesh** about the rebase, that his `c6860bd` closed Gap 18, and
  that our Gap 6 fix touches the guided flow — now moot if guided is deleted,
  but the rebase note still stands.

### Documents from the review round

| File | What it is |
|---|---|
| `PR5-comment-replies.md` | all 28 review comments, matched to their thread, with reply text |
| `PR5-response.md` | cause → fix → evidence per finding |
| `PR5-test-plan.md` / `PR5-test-results.md` | how it was tested and what passed |
| `architecture-notes.md` | why so much surfaced late; what the Live API does vs what we built; what BigQuery is actually for |
| `plan-after-implicit-decision.md` | the guided-removal story, Jeremy's two requirements, and further candidate stories |
| `stories-after-guided-removal.md` | the six follow-up stories, re-scoped |

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
