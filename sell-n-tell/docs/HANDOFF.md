# SellNTell — session handoff

Resume with no prior context. Read this first — it says where things stand and
what to do next. Then `architecture-proposal-suresh.md` for the design we are
moving to, `AIML-2702-baseline.md` for what the agent scores today, and
`evals/README.md` for how to run the eval.

---

## ✅ START HERE

**AIML-2898 (golden dataset) is done and AIML-2702 (eval harness) is in a PR.**
Both close when that PR merges. The next piece of work is the new architecture,
which is waiting on Suresh, and two stories that can start before he answers.

### 1. The open PR: `feature/AIML-2702-eval-harness` → `development`

One PR closes both stories. No application code changes. Contents:

| Path | What it is |
|---|---|
| `evals/v1/` | the golden set: `golden_v1.evalset.json` (90 real FAR notes, 15 per vertical, with expected answers) plus `universal_fields.csv` / `vertical_fields.csv` (the 65 must-capture fields with priority). **Customer notes and names — internal only; to be moved out of the repo later** |
| `evals/agent_eval/` | the regression harness: drives the running app as the client does and scores the saved record |
| `evals/adk_eval/` | the same scores through ADK's own evaluation service (custom metrics + ADK's built-in tool-use judge, live mode) |
| `evals/baselines/golden_v1.json` | the committed baseline: aggregate numbers only |
| `evals/README.md` | how to run both |
| `tests/test_agent_eval_score.py`, `tests/test_agent_eval_regression.py`, `tests/test_adk_eval_metrics.py` | offline scoring tests |

**Merge with "Squash".** The branch history still contains data files that the
final commit removed (top-ups, synthetic cases, the review workbook); a squash
merge brings only the final state into `development`. Last full test run on
the branch: 54 passed, 1 skipped (the ADK test module, which skips under the
project's ADK 2.1.0).

**After the merge:** post the closing comments on AIML-2898 and AIML-2702, and
change AIML-2702's AC4 from "seven-scenario seed set" to "the AIML-2898 golden
set (90 cases) runs end to end and produces a recorded baseline".

### 2. The two evals — what they are and how to run them

Both use the same golden set and the same scoring rules (the ADK metrics call
the harness's scorer), so a rule change applies to both.

**Regression harness** — the gate developers run:

```powershell
uv run python -m evals.agent_eval.run quick    # 18 cases (3 per vertical), about 20 minutes
uv run python -m evals.agent_eval.run full     # 90 cases, about 1.5 hours
```

- Starts the app if nothing answers on port 8000, sends each note over the
  WebSocket as text turns, answers the agent's topic reminders ("I didn't get
  to that"), confirms ("Yes, that's right. Save it."), and scores the last
  `stage_visit_notes` call.
- Writes `evals/runs/<mode>-<time>/final_scores.json` with a verdict and exit
  code: **PASS** (0), **REGRESSION** (1, a score worse than the baseline by more
  than 3 × its run-to-run spread, never less than 5 points), **INVALID** (2,
  more than 10% connection errors, no baseline, or the golden set changed).
- Every result records the app commit, the agent and judge models and the
  dataset checksum. Connection errors are retried once, then left out.
- Scoring rules: contested answers are skipped; a note that mentions no
  person is scored as On-site visit (the approved rule: a person → Meeting,
  otherwise On-site visit); dimensions compare as `4x4`; the faithfulness judge
  (gemini-3.8-flash, global) sees the note plus the rep's scripted replies.
- New baseline after an accepted change: run `full` three times, then
  `uv run python -m evals.agent_eval.baseline export <run folders>`.
- `uv run python -m evals.agent_eval.diagnose evals/runs/<name>` breaks the
  misses into expected → got patterns (counts only).

**ADK eval** — the framework to grow into (simulated users, audio later):

```powershell
uv run --with "google-adk[eval]==2.10.0" --with google-cloud-aiplatform python -m evals.adk_eval.run quick
```

- Loads the agent in-process; ADK's `LocalEvalService` drives it in live mode
  **one session at a time** (`AgentEvaluator` always opens 4 at once, which timed
  out on the opening handshake). Failed sessions retry once.
- Needs ADK with live evaluation. The project pins **2.1.0** (`uv.lock`), which
  has custom metrics but no live evaluation — hence `--with` until the ADK upgrade.
- It sends only the note, so after staging the agent tries to save without a
  reply and the app logs `commit_visit_notes BLOCKED: no new rep reply since
  staging` until the live timeout. Expected; the score uses the staged record.
  It is also a live view of the "saves without a yes" problem.
- Two quick runs so far: topic status 55.6% / 50.0%, event type 52.9%,
  disposition 42.9%, ADK rubric judge 74.5%; about 107 model events and 11
  tool calls per case (mostly those blocked save attempts). Not comparable
  decimal-for-decimal with the harness (first staged record, per-case means).

### 3. What the agent scores today (AIML-2702 baseline)

Full set, 90 cases × 3 runs (`AIML-2702-baseline.md`):

| Measure | Score | Main pattern |
|---|---|---|
| Event type | 59.7% | Meeting and On-site visit mixed up both ways; Phone Call chosen with no call |
| Topic status | 48.7% | 65% of campaigns the rep never mentioned marked discussed (190 of 293); discussed ones right 97% |
| Disposition | 72.2% | every miss is a specific code where the key says 99, mostly code 1 |
| Faithfulness | 22.0% | summaries for campaigns not discussed; invented skip reasons |
| Must-capture fields | 0% | not built |

Causes, all in the prompt or code list: `agent.py` and `behavioral_rules.yaml`
say "extract a disposition for EACH planned topic"; the agent sees only
campaign titles; there are no event-type rules; code 1's cue words
("interested", "send a quote") contradict the "use 99" guidance. Quick-set
baseline (18 cases): event type 62.0%, topic status 66.2%, disposition 65.7%
(range 44.4–77.8, so quick mode only catches large disposition drops),
faithfulness 30.2%.

### 4. The dataset (AIML-2898, done)

- 90 real notes, two independent model builds with roles swapped, 96.5%
  agreement; contested answers excluded from scoring.
- Field top-up: 65 more real notes found by searching the full export. Every
  must-capture field now has an example: all universal fields and 52 of 54
  vertical fields from real notes. HS-08 (PTAC population) and HS-09 (shop
  stock gaps) are stated in no note in the export, so they have 5 written
  cases, marked synthetic. 19 vertical fields have a single real example.
- Only the 90-case eval set ships in the PR. The top-up and synthetic sets,
  their summaries and the review workbook Suresh got stay on
  `feature/AIML-2898-golden-dataset`.
- The curation pipeline (`evals/dataset/`) is not in the repo; it lives in the
  local copy and as untracked files on the dev machine.

### 5. Dev-machine workarounds (until fixed on `development`)

- **Agent Engine:** `app/.env` needs `VERTEX_AI_AGENT_ENGINE_ID` (the URN Dharun
  gave, ending `reasoningEngines:2221633612665585664`) and
  `VERTEX_AI_AGENT_ENGINE_LOCATION=us-central1`. It is a borrowed, unused
  engine; sell-n-tell needs its own.
- **Missing dependency:** the session service needs `google-cloud-aiplatform`,
  which `pyproject.toml` does not declare, so a fresh install fails at startup.
  Start the app with `uv run --with google-cloud-aiplatform uvicorn app.main:app --port 8000`.
  The fix is `google-adk[gcp]` (a message to Dharun was drafted; also part of the ADK upgrade).
- **Unreliable connection to Google:** token fetches to `oauth2.googleapis.com`
  time out and sockets drop during long runs. The harness tolerates it (no
  client keepalive, retries, errors excluded and reported); worth raising with
  whoever looks after that machine, because real reps would hit it too.

### 6. The new architecture (waiting on Suresh)

`architecture-proposal-suresh.md` is the version to send him: why change
(the baseline above), the picture, 14 changes, the client contract and
17 questions (business and technical). It includes the useful parts of
Dharun's review. `architecture-proposal.md` is the fuller internal version
(component-by-component kept / removed list, rollout phases, risks); it does
not yet have the review merged in.

The design in short:

- Gemini Live keeps the voice. Extraction moves to a text Gemini call with a
  fixed JSON schema (`extract()`); every must-capture field is optional.
  Whether that is one call or several in parallel is decided by the eval.
- Written business rules (approved event-type rule, `4x4` dimensions, trucks
  count as units in Trades; "discussed only when the rep talks about the
  offer" still to confirm).
- Disposition codes stop being a model choice: derived from U-02 / U-04 / U-06
  by a business-owned mapping, or dropped (nothing consumes them today).
- Our code decides when to save, through **dialogue steps** kept in the session
  (listening → extracting → asking about a missed topic → reading back →
  waiting for a yes → saving). Saving is only reachable from "waiting for a
  yes", by a reply to the latest readback, so `turn_guard` and the commit
  watchdog go. `interpret()` labels the reply yes / correction / unclear.
- `POST /sessions` takes account id, visit id, vertical and planned topics (by
  registry id, or by title — only 26% of real topic mentions are in the
  registry); the rep comes from the token. The record goes to the client as a
  `saved` event and to Pub/Sub (consumer + BigQuery copy). Model Armor, managed
  logging, versioned reference data in Cloud Storage, failure handling.
- The eval in two tiers: text cases on every change, real recordings before a
  release (none collected yet).

**To send Suresh:** the proposal (it also asks whether the disposition codes are needed at all), and the ADK upgrade case — the project's
versions disagree (`uv.lock` 2.1.0, `requirements.txt` 2.5.0, `pyproject.toml`
≥1.32, and the Dockerfile ignores the lockfile); 2.1.0 has no live evaluation;
a trial on 2.10 ran ADK's live eval on our agent with no app changes. Proposal:
2.10 with `google-adk[gcp,eval]`, pinned, `requirements.txt` dropped, Dockerfile
installing from the lockfile.

### 7. The next stories (can start before Suresh answers)

**Story 1 — Fix the agent's prompt for topic mapping, event type and
disposition (3 points).** Remove the "EACH planned topic" wording and add "a
campaign counts as discussed only when the rep talks about its offer or
products" (`agent.py`, `behavioral_rules.yaml`); add the approved event-type
rule; align code 1's cue words with the 99 guidance (`dispositions.yaml`); add
`google-adk[gcp]` to `pyproject.toml`. AC: the three prompt changes are in; a
fresh `uv sync` starts the app; `run full` (×3) beats the baseline on topic
status, event type and disposition by more than the noise, with nothing else
dropping; unit tests pass.

**Story 2 — Text extraction with a fixed schema: the go/no-go (5 points).**
Build `extract()` (dictation text + planned topics with short descriptions +
vertical → one schema-valid record: event type, topic status, the vertical's
20 fields, the facts behind dispositions) and score it directly on the golden
set, without the live app. AC: schema-valid JSON for every case with no repair
step; one command writes a scorecard in the harness format; a model different
from the two that labelled the golden set; spread measured over 3 runs; it
beats the baseline (or Story 1's) on topic status, event type and faithfulness
by the agreed margin and meets agreed field targets — the result decides
whether the rest of the redesign goes ahead.

Also likely: a small **ADK upgrade** story if Suresh agrees.

### Guided is preserved

Tag `archive/guided-flow` on `9433908`:

```powershell
git checkout archive/guided-flow -- app/voice_notes_agent/tools_guided.py
```

---

## 1. Ticket status

| Ticket | Title | Status |
|---|---|---|
| **AIML-2702** | Eval harness | **PR open** (`feature/AIML-2702-eval-harness`). Closes on merge |
| **AIML-2898** | Curate the vertical golden dataset | **Done**; the full set was sent to Suresh for review as `golden_v1_review.xlsx`. Closes with the AIML-2702 PR |
| Story 1 (to create) | Prompt fixes for topic mapping, event type, disposition | Drafted (§7 above) |
| Story 2 (to create) | Text extraction go/no-go | Drafted (§7 above) |
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
up to 20 fields per call (11 universal + 9 for the account's vertical), only
when stated. The new architecture (§6 of START HERE) is how; the eval is how
we know it worked.

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


---

## 5. Tests

**Offline, deterministic** — no server, no model, no credentials:

```powershell
uv run pytest tests/ -q
```

- `tests/test_notes_workflow_gates.py` (8 tests) — the staging/commit gates,
  on `development`. `tests/conftest.py` imports `notes_workflow` under a
  private package name so the ADK agent is never built.
- `tests/test_agent_eval_score.py` (37 tests) — the harness's scoring, on hand-built records.
- `tests/test_agent_eval_regression.py` (9 tests) — quick subset, baseline,
  noise thresholds and the PASS / REGRESSION / INVALID verdicts.
- `tests/test_adk_eval_metrics.py` (7 tests) — the ADK custom metrics and
  config. Skips as a whole under an ADK without live evaluation (2.1.0).
- Tests that read the golden set skip when it is absent.
- `tests/test_dataset_*.py` — the curation pipeline; local only, like the
  pipeline.

**Model-level** — the eval (START HERE §2) is the scored check.
`scripts/ws_smoke_test.py` still works for a quick look (7 scenarios); its only
output is the transcript, and the proposal retires it.

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
late; "two fields with one example" was really 19).

**A framework does not make numbers meaningful — the checks around it do.**
Checked answers, a tested scorer, measured noise, recorded provenance, and
broken runs excluded rather than scored.

**Search for the detail, not the topic word.** Keyword searches for rare
fields ("filters", "competitor") returned thousands of notes that mention the
topic without the fact; patterns requiring the detail (a count, a price) found
the real examples.

**Verify a documented command exactly as written, in a clean environment.**
Stale state has fooled this project three times (`crypto.randomUUID` on
localhost, a smoke count zeroed by a restart, pytest "working" from a stale
`.venv`).

**When a guard fires unexpectedly, instrument before assuming it's wrong.**
`turn_guard` looked broken for a day and was correct every time.

---

## 7. Open decisions

All are also questions in the proposal:

1. **The new architecture** — Suresh's review of `architecture-proposal-suresh.md`.
2. **ADK upgrade** to 2.10, pinned in `uv.lock`.
3. **"Discussed" threshold** — a campaign counts as discussed only when the rep
   talks about its offer or products? The golden set is labelled that way.
4. **Disposition codes** — does anything downstream need a per-topic code? If
   not, drop them; if yes, derive them from U-02 / U-04 / U-06.
5. **Golden data in the repo** — kept for now; move it out later (retention
   and location to agree).
6. **Own Agent Engine** for sell-n-tell (the current one is borrowed).

---

## 8. Document index

| File | Contents |
|---|---|
| `HANDOFF.md` | this file — start here |
| `architecture-proposal-suresh.md` | **next work**: the architecture proposal for Suresh, with the review merged in |
| `architecture-proposal.md` | the fuller internal proposal (kept/removed components, rollout, risks) |
| `AIML-2702-baseline.md` | the eval baseline: scores, patterns, causes, the disposition-code question |
| `AIML-2702-pivot.md` | the AIML-2898 and AIML-2702 story text as built |
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
