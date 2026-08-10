# SellNTell — session handoff

Everything needed to resume with no prior context. Read this, then
`change-log.md` (what changed and why) and `AIML-2698-experiments.md`
(evidence + runnable tests).

**State as of last session: AIML-2698 is code-complete and verified. Next up is
AIML-2703 (Sprint S2), then AIML-2702 (S3).**

---

## 1. What this project is

An **agentic voice-dictation app for field sales reps (FARs)**. A rep finishes a
customer visit, speaks unstructured notes, and the agent extracts a **structured
CRM record** — event type, plus one entry per planned topic with a disposition
(outcome) code and a summary — reads it back, and commits on verbal approval.

**Business problem:** a FAR does 5–10 visits/day and spends 5–10 min per visit
typing into Salesforce, or defers to the evening and forgets. Target saving:
45 min–1.5 hr/day.

**Why it's an agent, not a form:** a transcript is useless to a CRM. The task is
*constrained extraction* — mapping free speech onto a fixed registry of outcome
codes, hands-free, with no screen. The rep is driving, so the only verification
is reading it back and getting a verbal yes.

**Scope reality check:** Confluence describes a phone-call product (CarPlay, plus
a podcast-style pre-call briefing). What exists is a **browser mic app** with a
**mock CRM** and a BigQuery sink. No telephony, no Salesforce, no playback
direction. Don't let anyone conflate the two.

---

## 2. Architecture

```
browser mic (16kHz Int16 PCM)
   │  WS /ws/{user_id}/{session_id}?campaign_type=&planned_topics=&agent_mode=
   ▼
FastAPI upstream_task ──> ADK LiveRequestQueue ──> Gemini Live (Vertex, native audio)
                                                        │
                          downstream_task <── events ───┘
                                ├─ function_call → tools.py → HTTP POST → own REST API → mock_db
                                └─ audio chunks  → WS → browser playback
```

**The tools never touch the database.** `tools.py` HTTP-calls
`localhost:8000/api/v1/...` — the server calling itself. Deliberate: validation,
logging and state live in one place, so voice and plain REST behave identically.
**All enforcement belongs in the REST layer**, where implicit, guided and any
future hybrid inherit it for free.

**Four load-bearing ideas**

1. **Dynamic config per session.** `before_agent_callback` → `load_campaign_config`
   fetches `/api/v1/config/agent-schema` and stashes the campaign's allowed event
   types + disposition registry in state; `voice_notes_instruction()` rebuilds the
   system prompt every turn from it.
2. **The Mega-Payload.** Implicit stays silent through dictation, then emits
   exactly one `stage_visit_notes` call with the whole record.
3. **Planned-topic coverage.** `compute_missing_topics` compares planned topics to
   what was extracted; gaps turn the confirmation into a reminder.
4. **Defence in depth against the model.** `temperature=0.1`, `ProactivityConfig`,
   `turn_guard` (code-level backstop against committing without a real reply), and
   auto-continue nudges for the opposite failure (silence owing a readback).

**Two modes**, via the `agent_mode` query param, one `Runner` each:
- `implicit` — `agent.py` + `tools.py`, single mega-payload
- `guided` — `agent_guided.py` + `tools_guided.py`, 5-tool state machine
  (`capture_dictation` → `choose_post_dictation_action` → `set_event_type` →
  `record_topic_disposition` → `commit_guided_notes`)

A third **hybrid** mode exists on `feature/AIML-2686` — not ours.

---

## 3. People and branches

- **Sainitheesh Erra** — project lead. **Suresh Thiagarajan** — original POC author.
- **Dharun** — junior engineer. **Sasidharan** — infra.

| Branch | What |
|---|---|
| `feature/AIML-2130-guided-flow` | lead's branch, tip `3ecd956` — **our base** |
| `feature/AIML-2686` | hybrid flow — not ours |
| `feature/AIML-2698-disposition-state-correctness` | **ours**, pushed |

Upstream was deliberately unset then re-pointed at our own remote branch, so a
bare `git push` can't reach the lead's branch.

---

## 4. Tickets (epic AIML-1537 SellNTell - V1)

| Ticket | Title | Sprint | Status |
|---|---|---|---|
| **AIML-2698** | Disposition + State Correctness | — | **Complete**, AC#5 pending lead review |
| **AIML-2703** | Correction & Re-stage Reliability (Both Flows) | Q3-**S2** | **Next** |
| **AIML-2702** | Eval Harness: Faithfulness/Factualness/Contextualness | Q3-**S3** | After 2703 |
| **AIML-2697** | FAR Demo Hardening: Mode UX + Demo Script | — | Not started, mostly frontend |

**Build the harness once.** 2698 AC#1/#5, 2703 AC#3 and all of 2702 want the
same artifact — a golden set run through both modes producing a scorecard.
2702's eval harness is the superset; extend `ws_smoke_test.py` in that shape
rather than writing ad-hoc scripts.

**2703 has a head start:** its AC#2 (commit blocked without a valid staged
session + required fields) and much of AC#4 (soft-fail messaging) are already
delivered and verified by the 2698 work. Cite the evidence rather than redoing it.

---

## 5. Environment

Repo lives on a separate machine (`C:\Personal Storage\developer\sell-n-tell`).
A reconstructed copy for reading/editing is at
`c:\Personal Storage\poc\sellNtell\sell-n-tell`.

**Transfer:** `tools/export-repo-md.ps1` (run in the repo, dumps tracked files to
markdown per folder, `-Include` to scope) and `tools/import-repo-md.ps1` (run
locally, rebuilds the tree). Prefer **targeted edits** over whole-file
replacement when sending changes back. Verify sync with marker/line-count
comparison, not hashes (repo is CRLF, local is LF). Don't copy the local
`index.html` back — its emoji are corrupted by an early exporter bug since fixed.

**Run:**

```powershell
cd "C:\Personal Storage\developer\sell-n-tell"
uv sync
gcloud auth application-default login
gcloud config set project prj-hds-np-data
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload 2>&1 | Tee-Object -FilePath "..\live-run.log"
```

**Keep the `2>&1`** — uvicorn logs to stderr, and without it the tee captures
almost nothing. The red PowerShell error-record wrapping is cosmetic.

Then http://localhost:8000. **Hard-refresh (Ctrl+Shift+R) after any `app.js`
change** — cached ES module.

**`app/.env`** (tracked in git; keep local edits out of commits):
`GOOGLE_CLOUD_LOCATION=us-east1` (doc says central; east works),
`VOICE_NOTES_VAD_SILENCE_MS=2000`, `VOICE_NOTES_BQ_ENABLED=false` for local dev
(else every commit logs a traceback). Model must be **native-audio** or playback
degrades to text.

**Debugging:** `_log_event` in `main.py` prints every downstream event without
PCM noise. Watch for `commit_visit_notes BLOCKED:`,
`Staging rejected for campaign_type=`, `Commit BLOCKED for session_id=`.

---

## 6. Tests

**REST regression suite — 9 cases, run after every backend change.** Full
paste-able block in `AIML-2698-experiments.md`:

| Case | Checks |
|---|---|
| A | uncovered topic → commit blocked (409) |
| B | campaign-illegal event type + code → 422 |
| C1 | full coverage → commits |
| C2 | legal `renewals` payload → stages |
| C3a/b/c | gap reported → re-stage accepts skip → commits |
| C4 | `needs_manual_review` with no code → commits |
| C5 | self-skip on first stage does **not** count as coverage |

**Conversational harness** (no mic, drives the real WebSocket with text turns):

```powershell
uv run python scripts/ws_smoke_test.py guided   2>&1 | Tee-Object -FilePath "..\ac5-guided.log"
uv run python scripts/ws_smoke_test.py implicit 2>&1 | Tee-Object -FilePath "..\ac5-implicit.log"
uv run python scripts/ws_smoke_test.py guided --scenario clean_save   # single scenario
```

All 8 scenarios commit correctly except guided `playback_then_save`, which hits
F5. **The harness hardcodes `campaign_type=standard_sales`** — adding a
`--campaign` flag is the natural first step for 2702.

---

## 7. What we changed

Detail in `change-log.md` (7 batches). Summary:

1. **Coverage gate** — commit refused (`409`) when planned topics have no
   outcome. Previously `missing_topics` was computed, stored on the record as a
   field, and committed anyway.
2. **Campaign rules enforced** (`422`), both modes. Root cause: `/notes/stage`
   took no `campaign_type` at all, so both checks fell back to global lists.
3. **Frontend stopped lying** — a refused commit showed "Saved to CRM"; it
   matched only `status === "error"` and our new `blocked`/`rejected` fell
   through. Now tests for `crm_record_id`, so unknown outcomes default to
   "not saved".
4. **Skips must come from the rep** — the model could mark a topic
   `discussed=false` with an invented reason and satisfy coverage without
   asking. Skips now count only on a re-stage. `executive_summary` made optional
   so a skip no longer *forces* confabulation.
5. **Code 99 "Outcome not covered"** in every campaign registry, auto-setting
   `needs_manual_review`.
6. **turn_guard counts text turns** — it only counted audio, so every gated tool
   was permanently blocked in text mode and the harness could never get past
   `capture_dictation`.
7. **Harness waits for the agent to fall silent** instead of breaking on the
   first `turnComplete`.

### The transferable lesson

Four fixes followed the same shape: **a prompt rule cannot beat a structure
pointing the other way.** Each was solved by changing the structure — a
code-level gate, an ordering constraint, an extra enum value — not by wording
the instruction more firmly. One attempt (Batch 5) tried prompt-only, was
measured before and after, and made no difference; it's recorded as a failed
attempt rather than a fix.

**Corollary, learned the hard way:** when a guard fires unexpectedly, instrument
before assuming it's wrong. `turn_guard` looked broken for most of a day and was
correct every time — the harness was desynchronised.

---

## 8. Open items

**Defects, not fixed:**
- **F5 — guided intermittently stalls before `commit_guided_notes`.** All topics
  dispositioned, agent says "Got it", then silence; nothing saved. Any further
  utterance unblocks it. Intermittent, so it passes rehearsal and can fail live.
  Recommended fix: commit directly in `record_topic_disposition`'s
  `all_topics_done` branch instead of asking the model for a second call. This
  touches the lead's guided flow — worth a word with him first.
- **`turn_guard` state never reset between connections.** Four module-level
  dicts keyed by `session_id`, never cleared; WS teardown closes only the queue.
  Sessions are reused by id, so a reconnect can inherit stale state. Found by
  code reading, **never reproduced.** Repro: complete a session, reconnect with
  the same `session_id`, attempt a commit.
- **Two flag shapes for the same idea** — guided uses null code +
  `needs_manual_review`; implicit uses code 99. Anything downstream has to
  handle both. Unify.

**Lower priority:** agent paraphrases `confirmation_text` instead of reading it
verbatim; invented skip reasons relocated to the overall summary after we made
the topic field optional (prompt rule added, unverified — can't be fully closed
in code); agent says "Contract **slash** agreement renewal"; readback omits
skipped topics; mic streams continuously (~4MB/session); ADK/OpenTelemetry
`Failed to detach context` traceback on every disconnect (library teardown, no
data impact, documented in the runbook).

**Needs the lead** (`note-disposition-registry-gap.md` is written and ready):
accept code 99 and its spoken label? Add code 1 to `renewals`? **Who consumes
`needs_manual_review`** — nothing downstream reads it today. Is hybrid
(`AIML-2686`) a third demo mode? AIML-2697 assumes two.

---

## 9. Working agreements

- Enforcement goes in the **REST layer**, not the ADK tools, so all modes inherit it.
- **Never silently produce a wrong value** — be right, ask, or flag for review.
  This is the invariant the whole codebase defends.
- Run the 9-case REST suite after every backend change; run the conversational
  harness for anything touching conversation flow.
- Record every change in `change-log.md` with why + verification status. Mark
  failed attempts as failed rather than leaving them looking like fixes.
- Docs in `docs/` are **local-only tracking**, not copied to the repo.
- Commit with explicit paths (`git add <files>`, never `-a`) to keep local
  `.env` edits out.

---

## 10. Document index

| File | Contents |
|---|---|
| `HANDOFF.md` | this file — orientation |
| `change-log.md` | every change, why, verification status |
| `AIML-2698-experiments.md` | reproductions, findings F1–F5, the 9-case REST suite |
| `status-updates.md` | ticket portfolio + day-by-day progress log |
| `demo-runbook-failure-modes.md` | AC#4 deliverable — failure modes & recovery for the demo driver |
| `note-disposition-registry-gap.md` | draft message to the lead re code 99 |
