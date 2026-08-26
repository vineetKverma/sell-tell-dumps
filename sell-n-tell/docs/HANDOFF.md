# SellNTell — session handoff

Resume with no prior context. Read this first — it says what to do next and
why. Then `plan-after-implicit-decision.md` for the current piece of work, and
`change-log.md` for what changed and why.

---

## ✅ START HERE — AIML-2751, remove the guided flow

Everything below is current as of 2026-08-26. No other document is needed to
begin; the rest of this file is background.

### Where things stand

- **PR #5 is merged into `development`** (merge commit `9433908`). Its review is
  fully answered — 10 correctness fixes verified, cosmetics done, remaining
  findings scoped into six follow-up stories.
- **The FAR research group chose the implicit model** (Jeremy, 2026-08-18), so
  guided mode is out of scope.
- **Guided is preserved at git tag `archive/guided-flow`**, pushed to origin,
  verified to sit on `9433908` with both guided files in its tree. Recover any
  file with:
  `git checkout archive/guided-flow -- app/voice_notes_agent/tools_guided.py`
- **Branch `feature/AIML-2751-remove-guided` is created** from `development`.
  Nothing has been deleted yet.

**Ticket: AIML-2751 — "Remove the guided flow".** 3 points, Sprint
AIML-2026-Q3-S3, In Development, parent AIML-1537.

### The task

Delete the guided flow. Below is every file that references it — the grep has
already been done, so this list is complete.

**1. Delete outright**

```
app/voice_notes_agent/tools_guided.py     (660 lines)
app/voice_notes_agent/agent_guided.py     (261 lines)
```

**2. `app/main.py`**

- the `from .voice_notes_agent import agent_guided` import (has a `# noqa: E402`)
- the `"guided": Runner(agent=agent_guided, session_service=session_service)`
  entry in the runners dict, and the `agent_mode == "guided"` selection around it
- `"commit_guided_notes"` in the `_READBACK_OWED_TOOLS` set
- the guided-specific wording in the "agent is responding" banner text
- a comment referencing "guided Stage 1 not calling capture_dictation" — keep or
  reword, it documents a real model behaviour

**3. `app/voice_notes_agent/mock_db.py`**

- **~L741** — the whole point of the story:
  `allow_skips = previous is not None or agent_mode == "guided"`
  becomes `allow_skips = previous is not None`, and the five-line comment above
  it explaining the guided exemption goes with it
- comments referring to `tools_guided.record_topic_disposition` and "guided
  deadlocks" — reword, do not silently drop (see *Rescue the lessons* below)
- `agent_mode` stays as a parameter and on the committed record; only the
  guided *branching* goes

**4. `app/static/index.html`**

- the `<option value="guided">Guided (explicit script)</option>` line, and
  probably the whole Solution selector if implicit is the only mode left

**5. `app/static/js/app.js`**

- `agentModeSelect` and its change listener
- `guidedPayload` and everything that builds it (`resetGuidedPayload`, the
  `capture_dictation` / `set_event_type` / `record_topic_disposition` handlers
  that populate it)
- `commit_guided_notes` and `record_topic_disposition` from the tool-name
  conditionals at ~L1017 and ~L1066 — this collapses three names to one, which
  is most of the "hard to extend" review finding
- the `agentMode === "guided"` banner-text branch
- **bump the version** in `index.html` and in `app.js`'s module imports
  (currently `v=9`, both must match)

**6. `scripts/ws_smoke_test.py`**

- `GUIDED_SCENARIOS`, `PLANNED_TOPICS_GUIDED`
- the `guided` choice in the argparse `agent_mode` argument
- the docstring usage examples and the long comment about
  `commit_guided_notes now`

**7. Leave alone**

- `app/voice_notes_agent/bigquery_sink.py` — it writes to
  `implicit_flow_calls` / `guided_flow_calls` tables keyed by `agent_mode`. That
  is historical comparison data. Keep the table mapping.

### Rescue the lessons first

`tools_guided.py` and `agent_guided.py` carry explanations that exist nowhere
else. Move these into `docs/change-log.md` (or `mock_db.py` comments) **before**
deleting the files:

- **Gap 6 / F5** — asked to make a second tool call when it has nothing left to
  say, the model ends its turn instead. Record complete, nothing saved, no
  signal. This is why the last disposition commits inline. Currently in the
  `_GUIDED_SCRIPT` header comment and at the inline commit in
  `record_topic_disposition`.
- **The `allow_skips` deadlock** (observed live 2026-08-11) — guided asks about
  a topic, the rep says they skipped it, the first staging call reports that
  same topic as uncovered, the commit 409s, and the agent asks again. Currently
  in the `mock_db.stage_notes` comment you are about to delete.
- **The 3-strikes disposition path** — after three failed confirm attempts,
  record `needs_manual_review` rather than guess a code.
- **Two flag shapes for manual review** — guided used a null code plus
  `needs_manual_review`; implicit uses code 99.

A tag preserves the code, but nobody goes looking in an archive tag for a lesson
they do not know exists.

### Testing

The local copy at `c:\Personal Storage\poc\sellNtell\sell-n-tell` is for
reading and editing only. Changes must be carried to the app machine
(`C:\Personal Storage\developer\sell-n-tell`) before anything can run — see
§4 for the export/import round trip, and run
`python tools/fix_mojibake.py --check` after importing.

On the app machine, with the server up (`uv run uvicorn app.main:app --host
0.0.0.0 --port 8000`, **no `--reload`**):

```powershell
uv run python scripts/ws_smoke_test.py implicit          # 7 scenarios
uv run python scripts/test_correction_reliability.py     # expect 16/16
```

Then one browser dictation end to end at `http://localhost:8000`, hard-reloaded,
producing exactly one CRM record.

Counting the committed records is the real check — the smoke harness prints a
transcript and no pass/fail summary:

```powershell
$r = (Invoke-RestMethod -Uri "http://localhost:8000/api/v1/notes/committed").records
"TOTAL: $($r.Count)"
$r | Group-Object ws_session_id | Where-Object Count -gt 1   # must print nothing
```

**`implicit/correction_summary` is intermittent** — it missed once on
2026-08-21 and passed on an immediate re-run with no code change. Re-run a single
scenario with `--scenario correction_summary` before calling it a regression.
The record store is in-memory, so **a restart resets the count to 0** — note the
baseline before reading a count as a failure.

### Acceptance criteria (from the ticket)

1. No file references `tools_guided` or `agent_guided`.
2. `allow_skips` has no `agent_mode` term.
3. The implicit smoke suite passes with the same scenario count as before (7).
4. `scripts/test_correction_reliability.py` passes unchanged.
5. A dictation completes end to end in the browser and produces one CRM record.

### Then

Raise the PR into `development`. Put the archive-tag recovery command in the PR
description — the tag is only useful if it is findable.

### After AIML-2751

Order from `stories-after-guided-removal.md` (the six follow-up stories,
re-scoped from 33 to 20 points now that guided is going):

1. **Decide where CRM records actually live** — today no configuration persists
   a committed record across a restart. May delete the storage-contract story.
2. **Consolidate campaign rules** — before vertical-market context adds a second
   config dimension.
3. **Event type interpretation** — Jeremy's first refinement.
   `plan-after-implicit-decision.md` §2 has the root cause: event types carry no
   mapping keywords while disposition codes do.
4. **AIML-2702 + AIML-2733** — eval harness and golden set. These gate the
   vertical-market work.
5. **Vertical market context** — Jeremy's second refinement.

### Still open, not ticketed

- **F7** — `_topic_matches` uses substring containment, so an inflected label
  ("Appliance Contract Renewal" vs planned "Appliances") reports the topic
  uncovered and can produce two rows for one discussion.
- **Invented skip reasons** — the agent still writes "due to time constraints"
  when the rep gave no reason. Prompt wording was measured over six runs and made
  no difference; needs a server-side fix.
- **Registry content gap** — no code expresses "renewal agreed", "quote created"
  or "no contact made"; roughly a quarter of real visits. Product decision, in
  `note-disposition-registry-gap.md`.
- **Tell Sainitheesh** about the rebase and that his `c6860bd` closed Gap 18.

---

## 1. Ticket status

| Ticket | Title | Status |
|---|---|---|
| **AIML-2751** | Remove the guided flow | **In development.** Branch `feature/AIML-2751-remove-guided` cut, nothing deleted yet — see START HERE |
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
