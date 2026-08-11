# SellNTell — session handoff

Resume with no prior context. Read this, then `AIML-2698-gap-findings.md` (the
current deliverable), `change-log.md` (what we changed and why), and
`far-notes-dataset-analysis.md` (real FAR data).

---

## ⚠️ START HERE — the lead has pushed changes we don't have

`feature/AIML-2130-guided-flow` tip is **`c6860bd`** (pushed 2026-08-11, visible
in the Bitbucket/web UI):

> `[AIML-2130] Fixed both implicit and guided flow disposition fields and now
> has latest working solution which was used for demo with leadership`

Our branch is based on `3ecd956` (2026-07-29), so `c6860bd` is one commit we do
not have. **It probably overlaps our disposition work directly** — campaign-scoped
codes, code 99, the coverage gate.

**The local clone does not fetch it.** `git fetch origin --prune` followed by
`git rev-parse --short origin/feature/AIML-2130-guided-flow` still prints
`3ecd956` even though the web UI shows `c6860bd`. Diagnose before trusting any
local ref — a stale remote-tracking ref already produced one wrong "his branch
never moved" conclusion on 2026-08-11:

```powershell
git remote -v
git config --get-all remote.origin.fetch
git ls-remote origin "refs/heads/feature/AIML-2130-guided-flow"   # asks the server directly
```

Once it fetches, assess with `tools/compare-trees.ps1` (three-way: baseline vs
his vs ours).

**Decided 2026-08-11:** if the changes overlap, **rebase our 2698 fixes on top of
his branch** — his is what leadership saw, so it is the demo-credible base.

---

## 1. Current situation (as of 2026-08-11)

**AIML-2698 has been re-scoped by the lead.** It is now **discovery and
reproduction only** — document the gaps, close the ticket, raise a new one for
the fixes. Do not present our fixes as part of 2698.

> "Do some testing with different examples and see what all gaps are there,
> there is a demo on next Monday Aug 17th with Field Account Representatives
> here in the office, let's try to make it more matured solution if possible by
> Thursday, we can connect daily... Just document in this ticket and add details
> in the ticket or confluence link and can close and create a new ticket."

- **Demo: Monday 17 Aug**, with FARs, in the office.
- **Target maturity: Thursday 13 Aug.**
- **Daily check-ins** with Sainitheesh, Vineet, Dharun.

**Deliverable produced:** `docs/AIML-2698-gap-findings.md` — 18 gaps, 15
reproduced with method and evidence, 3 not reproduced with reasons, priority
ranked against the demo, plus questions for the business.

**Complication:** we already implemented and verified fixes for most gaps on
`feature/AIML-2698-disposition-state-correctness` (pushed). Those commits now
need a home — new ticket, cherry-pick, or PR. Unresolved.

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
pre-call briefing). What exists is a **browser mic app** with a **mock CRM** and
a BigQuery sink. No telephony, no Salesforce, no playback direction.

---

## 3. Architecture

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

**The tools never touch the store.** They HTTP-call the app's own `/api/v1`
endpoints, so **all enforcement belongs in the REST layer** — implicit, guided
and hybrid inherit it for free. This is also why gaps can be reproduced with
plain HTTP calls, no mic and no model.

**Load-bearing ideas:** dynamic per-session campaign config injected into the
prompt; implicit's single "Mega-Payload" `stage_visit_notes` call; planned-topic
coverage checking; and defence-in-depth against the model (`temperature=0.1`,
`ProactivityConfig`, `turn_guard`, auto-continue nudges).

**Modes** (`agent_mode` param, one `Runner` each):
- `implicit` — `agent.py` + `tools.py`, 2 tools, ~2 rep turns, decides silently
- `guided` — `agent_guided.py` + `tools_guided.py`, 5 tools, ~8 turns, confirms
  each field
- hybrid exists on `feature/AIML-2686` — not ours

Measured on identical input, both modes produced **identical dispositions**;
they differ in how much the rep is asked.

---

## 4. People, branches, tickets

- **Sainitheesh Erra** — lead. **Suresh Thiagarajan** — original POC author.
- **Dharun** — junior engineer. **Sasidharan** — infra.
- **Jeremy Daniell** — business contact; supplied the product categories and the
  real FAR notes.

| Branch | State |
|---|---|
| `feature/AIML-2130-guided-flow` | lead's — **moved 2026-08-10, see START HERE** |
| `feature/AIML-2686` | hybrid flow — not ours |
| `feature/AIML-2698-disposition-state-correctness` | ours, based on `3ecd956`, pushed |

| Ticket | Title | Sprint | Status |
|---|---|---|---|
| **AIML-2698** | Disposition + State Correctness | — | **Discovery complete** — findings doc written; close it |
| **AIML-2703** | Correction & Re-stage Reliability | Q3-**S2** | Next |
| **AIML-2702** | Eval Harness (faithfulness/factualness/contextualness) | Q3-**S3** | After 2703 |
| **AIML-2697** | FAR Demo Hardening: Mode UX + Demo Script | — | Demo-relevant, not started |

**Build the harness once.** 2698 AC#1/#5, 2703 AC#3 and all of 2702 want the
same artifact. 2702's eval harness is the superset — extend `ws_smoke_test.py`
in that shape.

**2703 has a head start:** its "commit blocked without a valid staged session +
required fields" and much of its soft-fail messaging are already satisfied by
our work.

---

## 5. Environment

Repo is on a separate machine (`C:\Personal Storage\developer\sell-n-tell`); a
reconstructed copy for reading/editing is at
`c:\Personal Storage\poc\sellNtell\sell-n-tell`.

**Transfer:** `tools/export-repo-md.ps1` (in the repo, dumps tracked files to
markdown per folder, `-Include` to scope) and `tools/import-repo-md.ps1`
(locally, rebuilds the tree). Prefer **targeted edits** over whole-file
replacement going back. Verify sync by marker/line-count comparison, not hashes
(repo CRLF, local LF). Don't copy the local `index.html` back — emoji corrupted
by an early exporter bug, since fixed.

**Run:**

```powershell
uv sync
gcloud auth application-default login
gcloud config set project prj-hds-np-data
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload 2>&1 | Tee-Object -FilePath "..\live-run.log"
```

**Keep the `2>&1`** — uvicorn logs to stderr; without it the tee captures almost
nothing. Red PowerShell error-record wrapping is cosmetic.

**Hard-refresh (Ctrl+Shift+R) after any `app.js` change** — cached ES module.

**`app/.env`** (tracked; keep local edits out of commits): `us-east1` works
though the doc says central; `VOICE_NOTES_VAD_SILENCE_MS=2000`;
`VOICE_NOTES_BQ_ENABLED=false` locally. Model must be **native-audio**.

**Debugging:** `_log_event` in `main.py` prints every downstream event without
PCM noise. Watch `commit_visit_notes BLOCKED:`, `Staging rejected for
campaign_type=`, `Commit BLOCKED for session_id=`.

---

## 6. Tests

**REST suite — 9 cases, ~15 min, no mic or model.** Full paste-able block in
`AIML-2698-experiments.md`. Covers: coverage gate (409), campaign rules (422),
happy path, legal renewals payload, skip-after-reminder, manual review, and
self-skip rejection. **Run this against the lead's new branch first** — it will
show exactly which gaps he fixed.

**Conversational harness** (no mic, real WebSocket, text turns):

```powershell
uv run python scripts/ws_smoke_test.py guided   2>&1 | Tee-Object -FilePath "..\ac5-guided.log"
uv run python scripts/ws_smoke_test.py implicit 2>&1 | Tee-Object -FilePath "..\ac5-implicit.log"
uv run python scripts/ws_smoke_test.py guided --scenario clean_save
```

Two fixes were needed to make it work at all (see Gap 7): `turn_guard` counted
only spoken turns so text input was permanently blocked, and the harness broke
on the first `turnComplete` and sent turns mid-response. **It hardcodes
`campaign_type=standard_sales`** — adding `--campaign` is step one for 2702.

---

## 7. Key findings (detail in `AIML-2698-gap-findings.md`)

**18 gaps.** Highest demo risk:

1. **Gap 6** — Guided intermittently stalls before saving. All topics answered,
   agent goes quiet, nothing saved. Any utterance unblocks it. *Intermittent, so
   it passes rehearsal and can fail live.*
2. **Gap 5** — Dispositions wrong and non-deterministic when no code fits. Same
   utterance returned codes 5, 2 and 1 across sessions. **Root cause is the
   registry, not the model** — proven by a control where a fitting code exists
   and is chosen correctly every time.
3. **Gaps 1–4** — commit succeeded on knowingly-incomplete records; campaign
   rules unenforced; the model marked topics "not discussed" on the rep's behalf
   with invented reasons.
4. **Gap 18** — Guided leaves the on-screen record card empty. Undercuts guided's
   whole "you can see it confirm each field" pitch if both are demoed.

**Not reproduced:** orphaned staged records after a correction (relevant to
2703); `turn_guard` state leaking across reconnects; and the three failure modes
in the original ticket description, which appear already fixed on the branch.

### The transferable lesson

**A prompt rule cannot beat a structure pointing the other way.** Four fixes
followed that shape and were solved structurally (a code-level gate, an ordering
constraint, an extra enum value). One attempt was prompt-only, measured before
and after over six runs, and made no difference.

**Corollary:** when a guard fires unexpectedly, instrument before assuming it's
wrong. `turn_guard` looked broken for most of a day and was correct every time —
the harness was desynchronised.

---

## 8. Real FAR data (new, 2026-08-11)

`Notes Examples(Sheet1).csv` — 1000 rows from Salesforce, column 1 = pre-call
plan, column 2 = post-meeting notes. Analysis in
`far-notes-dataset-analysis.md`. Headlines:

- **Planned-topic catalog replaced** with Jeremy's 13 product categories
  (Appliances … Tools). Already applied in `mock_db.py`.
- **67% of notes mention no product category at all.** Coverage reminders become
  the common path, not the exception. Only Appliances, HVAC, Pool and Plumbing
  appear with real frequency — **use those for the demo.**
- **Two common outcomes have no disposition code:** quote created/sent (~15% of
  visits) and no contact made (~8%, "Not there", "Office was closed"). A
  no-contact visit has no valid event type either.
- **9% of notes are under 40 characters** ("Junk", "REHAB", "OK for Now") — the
  inputs most likely to force fabrication.
- Reps don't actually plan in categories; real plans are campaign codes and
  follow-ups, heavily abbreviated (FU, EE, BM&S, MRO, PTAC, CAPX).
- **This is the golden set for 2702.** Sample it stratified — especially the 67%
  stratum that names no planned topic, which is completely untested.

---

## 9. Open decisions for the lead

1. ~~**How do our fixes get carried forward**~~ — **decided 2026-08-11: rebase
   our 2698 fixes on top of `feature/AIML-2130-guided-flow`.** His branch is what
   leadership saw, so it is the demo-credible base. Still needs telling him.
2. **Registry design.** No code for "renewal agreed", "quote created", or "no
   contact made". Together that's ~25% of real visits with no correct code.
   Cannot be solved in engineering.
3. **Gap 6 approach** — commit directly at `all_topics_done` rather than asking
   the model for a second call. Touches his guided flow.
4. **Who consumes `needs_manual_review`?** Nothing downstream reads it.
5. **Is coverage a blocker or a prompt?** With category topics, most visits will
   trigger reminders.
6. **Two flag shapes** — guided uses null code + `needs_manual_review`, implicit
   uses code 99. Unify.

---

## 10. Working agreements

- Enforcement goes in the **REST layer**, not the ADK tools.
- **Never silently produce a wrong value** — be right, ask, or flag for review.
- Run the 9-case REST suite after every backend change; run the conversational
  harness for anything touching conversation flow.
- Record changes in `change-log.md` with why + verification status. **Mark failed
  attempts as failed.**
- `docs/` is local-only tracking, not copied to the repo.
- Commit with explicit paths (`git add <files>`, never `-a`) to keep `.env` out.

---

## 11. Document index

| File | Contents |
|---|---|
| `HANDOFF.md` | this file |
| `AIML-2698-gap-findings.md` | **the deliverable** — 18 gaps, repro method, priorities |
| `far-notes-dataset-analysis.md` | real FAR notes: what they break |
| `change-log.md` | every change, why, verification status |
| `AIML-2698-experiments.md` | reproductions, findings F1–F5, the 9-case REST suite |
| `demo-golden-path.md` | **the two scripted demo scenarios** — one per mode, real utterances, expected records |
| `demo-runbook-failure-modes.md` | failure modes & recovery for the demo driver |
| `status-updates.md` | ticket portfolio + day-by-day log |
| `note-disposition-registry-gap.md` | draft to the lead re the registry |
| `note-2698-story-points.md` | draft re 3 → 5 points |
