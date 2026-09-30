# SellNTell — session handoff

Resume with no prior context. Read this first — it says where things stand and
what to do next. Then `AIML-2702-pivot.md` for the current two stories, and
`change-log.md` for older history.

---

## ✅ START HERE — the eval work (AIML-2898 → AIML-2702)

AIML-2751 (remove the guided flow) is **merged** into `development`
(`85b108c`). The work now is measuring the agent: a golden dataset
(AIML-2898) and the harness that scores the agent against it (AIML-2702).
Both follow Suresh's direction: capture everything on the must-capture sheet
(`must-capture-fields.xlsx`, 65 fields, P1–P3) and report accuracy by
priority.

### AIML-2898 — golden dataset v1: in review with Suresh

**Branch `feature/AIML-2898-golden-dataset`** (off `development`), pushed.
Holds the data only, in `evals/v1/`:

| File | What it is |
|---|---|
| `golden_v1.jsonl` | 90 real FAR notes, 15 per vertical, with the expected answers |
| `golden_v1.evalset.json` | the same 90 as ADK EvalCases — what the harness reads |
| `golden_v1.manifest.json` | counts and which models built it |
| `finalize_v1_summary.md` | counts only |
| `universal_fields.csv`, `vertical_fields.csv` | the 65 fields with priority, from the must-capture sheet |

**The set contains customer notes and contact names — internal only.**

How it was built: notes sampled per vertical across outcome strata (order,
quote, no contact, multi-topic, short, plan restatement). Each note labelled
by two independent builds with the models' roles swapped
(gemini-3.8-flash / gemini-3.1-pro-preview, global endpoint), a judge settling
disagreements. 96.5% agreement; the 67 contested answers are marked in each
record's `contested` list and are not scored. U-03 is derived from the topic
answers, never labelled. "Not stated" is `null`; an event type of `null` means
the note gives no clue. The files were built as "v1.1" (topic descriptions
cleaned, every answer identical to the first build) and renamed to v1 on the
branch.

The curation pipeline (`evals/dataset/`) is **not** in the repo — only the
data is. Suresh's review copy is `golden_v1.1_review.xlsx` (Read me / Records /
Fields tabs).

**Suresh's answers so far:**

1. Campaign type — keep it as a placeholder (`standard_sales`). It is not in
   the source data, and the agent ignores it anyway. Closed.
2. The top-up set — he asked what it means; a plain explanation was sent. No
   decision yet. The work below is going ahead so the reply can carry results.

### The top-up set — in progress on the dev machine

33 of the 54 vertical fields (16 of them P1) never appear in the 90 notes, so
for those the eval can only check that the agent does not invent them. The
fields are rare, not absent: the sheet's Evidence Base tab counts hundreds to
thousands of matching notes in the full export (e.g. HL-01 procurement channel
731, MH-01 turns 6,918). Fifteen notes per vertical just missed them.

The top-up picks notes per missing field, labels them the same two-build way,
and keeps only notes where both builds agree the field is stated. A keyword
hit is only a candidate: MH-02 matches "HVAC" in 22% of notes, but a note has
to say *repair or replace* to state the field.

Pieces (local, committed, covered by the offline tests):

- `evals/dataset/sample_topup.py` — one keyword pattern per missing field,
  up to 6 candidates each from that field's own vertical, v1 notes skipped,
  ids prefixed `T-`.
- `build.py --sampler topup` — same pipeline, new sampler.
- `finalize.py --keep-target-stated 3` — keeps at most 3 confirmed notes per
  field and reports which fields no real note confirmed.

**State:** build A has drafted all 197 candidates with both models; one note
(`T-MH-040`) failed in model B (the reply came back as a list, not an object).
Re-run the same build command **without** `--fresh` — it retries only the
failed note — then build B with the roles swapped, then:

```powershell
uv run python -m evals.dataset.finalize --a topup_a --b topup_b --version topup_v1 --keep-target-stated 3
uv run python -m evals.dataset.export_adk --version topup_v1
```

Bring back `sample_topup_a_summary.md` and `finalize_topup_v1_summary.md`
(counts only). Next: tell Suresh which fields now have real examples, which
have none, and propose short written dictations for the rest. If `T-MH-040`
fails again, make `draft_labels.py` unwrap a one-element list.

### AIML-2702 — eval harness: built, first trial not yet run

**Branch `feature/AIML-2702-eval-harness`**, cut from the AIML-2898 branch
(it needs `evals/v1/`). Code in `evals/agent_eval/`:

| File | Role |
|---|---|
| `cases.py` | loads the eval set and field priorities; refuses anything but the full 90 cases for a baseline |
| `drive.py` | runs one case against the **running app** through its own contract: `POST /api/sessions`, then the WebSocket with text turns — the same path as `scripts/ws_smoke_test.py` |
| `score.py` | pure scoring of the last `stage_visit_notes` call against the key |
| `judge.py` | summary faithfulness, the only metric with model calls (`--judge`) |
| `run.py` | the command: runs, scores, writes the scorecard |

The rep's side is scripted: the note as the dictation; "I didn't get to that"
when the agent reminds about a planned topic; then "Yes, that's right. Save
it." The reminder decision mirrors `notes_workflow.compute_missing_topics`
(substring match; skips count only after the first staging call), so the rep
answers exactly when the app asks.

Scored: event type, topic status (discussed / not / duplicate rows, off-plan
rows reported), disposition code, faithfulness, and per must-capture field
recall / precision / fabrication / value accuracy, rolled up per vertical and
per priority. Contested items are skipped; a field with no stated example
reports n/a, not 0. `--repeat N` gives run-to-run variance, `--rescore`
re-scores a saved run, `--evalset` points at another set (the top-up).
Output goes to `evals/runs/<name>/`, which is git-ignored — it quotes notes.

**The agent captures no must-capture fields today** (no `must_capture`
argument on `stage_visit_notes`), so the first baseline shows fields as "Not
captured". That is the gap the vertical build closes; the same harness then
measures it unchanged.

**Next:** start the app, then

```powershell
uv run python -m evals.agent_eval.run --name trial --cases HL-001,MH-001,IS-001
```

Check the transcript in `evals/runs/trial/run1.jsonl` — did the scripted
conversation reach a commit? — before spending about an hour per repeat on the
full 90. Then `--name baseline --repeat 3 --judge`.

The story text in `AIML-2702-pivot.md` matches what was built (drives the app
over its API rather than ADK's Runner in-process; AC4 requires the full
90-case set). The Jira description still needs the same update.

### Open, not ticketed

- **F7** — `compute_missing_topics` matches by substring containment, so an
  inflected label ("Appliance Contract Renewal" vs planned "Appliances") can
  leave a topic "uncovered" and produce two rows for one discussion. The
  harness reports duplicate and off-plan rows, so it will measure this.
- **Invented skip reasons** — the agent still writes "due to time constraints"
  when the rep gave no reason. Prompt wording made no difference over six runs;
  needs a server-side fix. The faithfulness judge will measure it.
- **Registry content gap** — no code expresses "renewal agreed", "quote
  created" or "no contact made"; roughly a quarter of real visits.
  `note-disposition-registry-gap.md`. The must-capture fields U-02 (contact
  outcome) and U-04 (commercial outcome) cover the same ground.
- **Supersede gate unreachable in the live flow** — `tools.py` passes the same
  `session_id` on every stage, so the AIML-2703 gate never fires; the
  single-draft invariant is what delivers the guarantee.
  `tests/test_notes_workflow_gates.py` tests both, split into
  `TestLiveCallPattern` and `TestSupersedeGate`. Whether to keep the gate is
  still an open question with Suresh.
- **Vestigial BigQuery DDL** — `scripts/bigquery_create_tables.sql` and
  `bigquery_schema.json` still define `guided_flow_calls` and `agent_mode`;
  nothing writes them.
- **The sync tool never deletes.** `tools/import-repo-md.ps1` only writes
  files, so anything removed upstream survives locally and has to be deleted
  by hand.

### Guided is preserved

Tag `archive/guided-flow` on `9433908`:

```powershell
git checkout archive/guided-flow -- app/voice_notes_agent/tools_guided.py
```

---

## 1. Ticket status

| Ticket | Title | Status |
|---|---|---|
| **AIML-2898** | Curate the vertical golden dataset | **In review with Suresh.** v1 on `feature/AIML-2898-golden-dataset`; top-up set being built |
| **AIML-2702** | Eval harness (rewritten for ADK-native evaluation) | **Built, not yet run on the dev machine.** `feature/AIML-2702-eval-harness` |
| **AIML-2751** | Remove the guided flow | **Merged** into `development` |
| **AIML-2741** | — | Marked not needed |
| **AIML-2845** | No-speech turns leave the agent's recovery message suppressed | **Backlog.** `suppressAgentSpeech` is only lifted by a tool call, and the no-speech path has none |
| **AIML-2750** | CRM backend decision | **Closed**, merged as PR #7 — the re-architecture to `notes_workflow.py` + `schemas.py` + YAML resources |
| **AIML-2698** | Disposition + State Correctness | **Closed** (PR #5) |
| **AIML-2705** | Disposition Quality Guardrails | **Closed** |
| **AIML-2703** | Correction & Re-stage Reliability | **Closed.** Covered by `tests/test_notes_workflow_gates.py` |
| **AIML-2697** | FAR Demo Hardening | Partly in flight |
| **AIML-2651** | Error Handling & Resilience | Not started |

---

## 2. What this project is

An **agentic voice-dictation app for field sales reps (FARs)**. The rep speaks
unstructured notes after a visit; the agent extracts a **structured CRM record**
(event type + one entry per planned topic, each with a disposition code and
summary), reads it back, and commits on verbal approval.

**Why it's an agent:** a transcript is useless to a CRM. The task is
*constrained extraction* — mapping free speech onto a fixed registry of
outcome codes, hands-free, with no screen.

**Where it is going:** the must-capture sheet asks the agent to also extract
up to 20 fields per call (11 universal + 9 for the account's vertical), when
present — the agent does not ask for missing ones. Topic name, description,
vertical and campaign type are assumed to arrive as API inputs. Not built yet;
the harness above is what will measure it.

---

## 3. Architecture

Checked against `development` at `85b108c`.

```
browser mic (16 kHz Int16 PCM, 20 ms chunks)
   │  POST /api/sessions {user_id, planned_topics, campaign_type}  -> session_id
   │  WS /ws/{user_id}/{session_id}?planned_topics=&campaign_type=
   ▼
FastAPI upstream_task ──> ADK LiveRequestQueue ──> Gemini Live (Vertex, native audio)
                                                        │
                          downstream_task <── events ───┘
                                ├─ function_call → tools.py → notes_workflow (in-process)
                                └─ audio chunks  → WS → browser playback
```

**Routes:** `/healthz`, `/api/config`, `/api/sessions`, `/` and the WebSocket.
There is still no endpoint that lists committed records.

**Sessions** are created by `POST /api/sessions` (AIML-2743) and stored in a
`VertexAiSessionService` (a non-blocking subclass in `main.py`), because that
service mints its own ids and rejects client-supplied ones. `planned_topics`
arrive there as a **list**, which is what seeds the prompt — the WebSocket's
`planned_topics` query string is now only logged. `campaign_type` is stored
but **inert**.

**Live credentials** are pre-warmed once at import
(`voice_notes_agent/live_credentials.py`) and refreshed in the background.
The comment above `live_client` in `agent.py` explains why this must happen
there, not in `main.py`.

**The layer:**

- `notes_workflow.py` — staging, corrections, the coverage gate
  (`compute_missing_topics`), commit and its idempotent replay. In-memory
  `_STAGED_NOTES` only; nothing survives a restart.
- `schemas.py` — the Pydantic payloads (`DiscussionTopic` etc.).
- `resources/dispositions.yaml` — one universal disposition registry (codes
  1–10, 99).
- `resources/behavioral_rules.yaml` — the agent's static prompt text.
- `tools.py` — `stage_visit_notes(event_type, executive_summary,
  raw_transcript_backup, topics)` and `commit_visit_notes`. The agent's whole
  CRM record is the arguments of the last stage call — which is why the
  harness scores tool-call arguments.
- Durable audit is ADK's BigQuery analytics plugin behind
  `BQ_ANALYTICS_ENABLED` (default `false`).
- `config.py` — dead (`API_BASE` for a loopback that no longer exists);
  nothing imports it.

One agent, one Runner, one flow (implicit); guided is retired.

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

**Do not use `--reload` for a demo** — a file save restarts the process and
drops every live WebSocket and every staged record.

**`app/.env` is untracked** (`.env.example` is the template). Needs a
**native-audio** model or spoken playback silently disables itself.

### Frontend caching — read this before editing `app.js`

`index.html` loads `app.js?v=16`; `app.js` imports `audio-player.js?v=10` and
`audio-recorder.js?v=10`. The browser caches by full URL, so bump the version
of whichever file you change. The two numbers are currently out of step,
contrary to the comment in `app.js` that asks for them to match — harmless,
but decide which convention to keep. `main.py` also sends
`Cache-Control: no-store` for `/static`; keep both.

Symptom to recognise: the file on disk is correct, fetching the plain URL
returns the correct content, and the browser still runs old code.

**Debugging:** `_log_event` in `main.py` prints every downstream event without
PCM noise. Watch for `commit_visit_notes BLOCKED:` (turn_guard),
`Staging rejected by validation:`, and `Commit BLOCKED for session_id=`.

---

## 5. Tests

**Offline, deterministic** — no server, no model, no credentials:

```powershell
uv run pytest tests/ -q
```

- `tests/test_notes_workflow_gates.py` (8 tests) — the staging/commit gates,
  on `development`. `tests/conftest.py` imports `notes_workflow` under a
  private package name so the ADK agent is never built.
- `tests/test_agent_eval_score.py` (28 tests) — the AIML-2702 scoring, on
  the harness branch. Adds the repo root to `sys.path` itself; no
  `pyproject.toml` change.
- `tests/test_dataset_*.py` — the curation pipeline; local only, like the
  pipeline.

**Model-level** — the eval harness (AIML-2702) above is the scored check.
`scripts/ws_smoke_test.py` still works for a quick look (7 scenarios, mints a
session via `POST /api/sessions` first); its only output is the transcript.
`correction_summary` is intermittent — re-run before calling a failure a
regression.

---

## 6. Lessons worth keeping

**A prompt rule cannot beat a structure pointing the other way.** Five fixes
were solved structurally; the one prompt-only attempt was measured over six
runs and made no difference.

**A required field is a place to invent.** A required summary on a skipped
topic produced "due to time constraints". Every must-capture field must allow
"not stated", and the harness counts filling one as fabrication.

**Never trust a count you didn't measure.** The golden set's agreement rate,
the per-field counts and the test totals in this file were all measured, not
copied — several first guesses were wrong (the Campaign Topics export is
Windows-1252, not UTF-8; a fourth Replace-All substitution, "gov", was found
late).

**Verify a documented command exactly as written, in a clean environment.**
Stale state has fooled this project three times (`crypto.randomUUID` on
localhost, a smoke count zeroed by a restart, pytest "working" from a stale
`.venv`).

**When a guard fires unexpectedly, instrument before assuming it's wrong.**
`turn_guard` looked broken for a day and was correct every time.

---

## 7. Open decisions

1. **Top-up set** — worth adding before the vertical build? Results pending
   (see START HERE).
2. **Vertical build** — making the agent capture the must-capture fields is
   not ticketed yet. The harness is ready to measure it.
3. **Registry content** — "no contact", "quote created", "renewal agreed" have
   no code; U-02/U-04 overlap. Which is authoritative?
4. **`needs_manual_review`** — nothing sets or reads it now that guided is
   gone, but the coverage gate still honours it. Delete it or use it.
5. **Supersede gate** — keep as defence, or delete as unreachable?

---

## 8. Document index

| File | Contents |
|---|---|
| `HANDOFF.md` | this file — start here |
| `AIML-2702-pivot.md` | **current work**: the AIML-2898 and AIML-2702 story text as built |
| `plan-after-implicit-decision.md` | the plan after choosing implicit: remove guided, then Jeremy's two requirements |
| `stories-after-guided-removal.md` | the six follow-up stories, re-scoped |
| `architecture-notes.md` | Live API vs our layers; what BigQuery is for |
| `change-log.md` | every change, why, verification status |
| `status-updates.md` | ticket portfolio + day-by-day log |
| `far-notes-dataset-analysis.md` | real FAR notes: what they break |
| `note-disposition-registry-gap.md` | draft to the lead re the registry |
| `AIML-2698-gap-findings.md` | 18 gaps, repro method, priorities |
| `AIML-2698-experiments.md` | reproductions and findings F1-F5 (its REST suite no longer runs) |
| `AIML-2698-jira-comment.md` | draft Jira comment for AIML-2698 |
| `note-2698-story-points.md` | draft message: AIML-2698 story points 3 → 5 |
| `PR5-review-findings.md` | triage of the 25 PR #5 comments |
| `PR5-comment-replies.md` | every PR #5 review comment, matched to its thread, with reply text |
| `PR5-response.md` | cause → fix → evidence per PR #5 finding |
| `PR5-followup-stories.md` | follow-up stories from the PR #5 review |
| `PR5-test-plan.md` / `PR5-test-results.md` | how PR #5 was tested, and what passed |
| `demo-golden-path.md` | demo script (written when both flows existed) |
| `demo-runbook-failure-modes.md` | demo runbook: known failure modes and agent recovery |
