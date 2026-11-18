# SellNTell — session handoff

Resume with no prior context. Read this first — it says where things stand and
what to do next. Then `architecture-proposal-suresh.md` for the design we are
moving to, `AIML-2702-baseline.md` for what the agent scores today, and
`evals/README.md` for how to run the eval.

---

## ✅ START HERE

| Story | State | Next |
|---|---|---|
| **AIML-2898** golden dataset | **Done** (merged with PR #10). Key now v1.4 | — |
| **AIML-2702** eval harness | **Merged** (PR #10, squash, 2026-10-15) | — |
| **AIML-2928** ADK 2.10 + prompt fixes | **Merged** (PR #11, squash, 2026-10-26, `a416029`), approved by Suresh. Baseline = three full runs of the merged code (81.0 / 80.0 / 67.8 / 56.3) | — |
| **AIML-2929** `extract()` go/no-go | **Merged** (PR #13, squash), approved by Suresh. Final head `1fbae31`; results in §6a | — |
| **AIML-3011 / 3116 / 3117** dialogue steps + `extract()` in the live flow | 8-pointer split into three 3-pointers at Bobby's ask (§11) | Pick in order after 2929 merges |
| **AIML-3004** disposition code per discussed topic | **Merged** (PR #17, squash), approved by Suresh. Final head `2aabf50`; run `extract-20261110-230607`: disposition 85.6% (agent 67.8%; 25 against 20 of 30 topics, p = 0.23), over-claimed 0%, no wrong code; details in decisions D-73 to D-77 | Follow-up story after the business answers (material left, a quote, a brand refusal): evidence by sentence number, the topic rule, the key correction |
| **AIML-3152** extract() follow-up | **Ready for PR**, branch `feature/AIML-3152-extract-followup`. Evidence by sentence number; the business answers in `extract()`'s prompt (topic rule, quote rule) and key v1.5 (in the bucket); the agent's quote rule; sentence numbers stripped from the record. Run `extract-20261118-132816` (key v1.5): disposition 80/84 = 95.2%, topic status 99.2%, event type 93.4%, faithfulness 90.0%, over-claimed 0.7%. Agent baseline re-exported on key v1.5. Decisions D-78 to D-84 | Raise the PR; then Suresh's review |
| **Dev deployment** | Tested end to end; 12 gaps posted to the team (§10) | App fixes 2-6 when Suresh confirms; no code changes until then |
| **AIML-3037** Python 3.11+ runtime | Backlog (raised from the PR #11 review) | — |
| **AIML-3054** scorecard counters (disposition loss, needless reminders) | Backlog (raised from the PR #11 review) | — |
| **AIML-2957** golden-data tests in CI | Backlog | — |
| **AIML-2962** web UI + WebSocket follow the session contract | Backlog | UI first, then the `main.py` handler |
| Event-type rule | **Answered** (Tobi, for Jeremy, 2026-10-14): front desk or gatekeeper only is an On-site visit. In key v1.4 and `extract()`. The agent's prompt keeps its earlier rule: every wording tried cost topic status and faithfulness (3 wordings, 6 runs, a control run) | Done |

### 1. Branches

- `origin/development` (`b2266c4`) holds PR #10 (eval harness), PR #11
  (AIML-2928), AIML-2910 and PR #14 AIML-3006 (silence watchdog), AIML-2823
  (BigQuery audit logging; `/healthz` gains an `analytics` key when on) and
  PR #16 (default model `gemini-3.8-live`, set in `voice_notes_agent/agent.py`;
  AIML-2929 moves the name into a new `voice_notes_agent/model.py`, same value).
  Pull `development` before comparing against it.
- `feature/AIML-2929-text-extraction`: development merged in twice; head
  `1fbae31`.
- An automated review of these branches gave several rounds of findings; the
  triage is in `AIML-2929-review-findings.md`.
- Commit hygiene: one short line per commit ("AIML-2929: …"), never review
  rounds or tool names. Five pushed 2929 commits still carry "review round" /
  "PR #13 review" wording; the Squash merge replaces them.
- `pyproject.toml` / `uv.lock` are managed with uv and never hand-edited.
- Stage files by path; never `git add -A`.

### 2. Data — never in the repo

`gs://sellntell-eval-np` (project `prj-hds-np-data`; versioned, 5 versions,
noncurrent expire after 90 days; uniform access; public access prevented):

| Folder | Contents |
|---|---|
| `golden_v1/` | v1.1 as labelled: `golden_v1.evalset.json` (90), `universal_fields.csv`, `vertical_fields.csv` |
| `golden_v1.2/` | + 17 event types → Meeting; manifest lists the ids |
| `golden_v1.3/` | v1.2 + U-02 "spoke with contact" on 21 cases |
| `golden_v1.4/` | **in use**: v1.3 + the front-desk rule (HS-007 → On-site visit; HL-011 contested); checksum `32a1988b…` |
| `topup/` | 65 real notes for field examples (`golden_topup_v1..v3`: 44 + 12 + 9) — key still v1.1 |
| `synthetic/` | 5 written cases (HS-08 / HS-09) — key still v1.1 |
| `reference/` | `campaign_topics.csv` — the campaign registry (titles + descriptions) |
| `review/` | `golden_v1_review.xlsx` sent to Suresh |

```powershell
New-Item -ItemType Directory -Force evals/v1 | Out-Null
gcloud storage cp "gs://sellntell-eval-np/golden_v1.4/*" evals/v1/
gcloud storage cp -r gs://sellntell-eval-np/topup gs://sellntell-eval-np/synthetic gs://sellntell-eval-np/reference evals/
```

The dataset checksum ignores line endings (`cases.dataset_sha256`).
`evals/topup/`, `evals/synthetic/` and `evals/reference/` are git-ignored
from AIML-2929.

### 3. AIML-2928 — merged

ADK 2.10.0 (`google-adk` plus `google-cloud-aiplatform[agent-engines]`, no
`[gcp]` extra; `[eval]` in dev), `requirements.txt` removed, session metadata
keys `_compaction` / `_usage_metadata`, one retry on HTTP 429 (logged).
Prompt rules: a topic is discussed only on its offer or products, codes
include 99, an empty record is refused when nothing was planned. Coverage
needs a planned topic's own label; the read-back says what the rep said; the
gate's limits are never finer than one item.

**The committed baseline**: replaced by AIML-3152 with three full runs on key
v1.5, with the agent's quote rule (full-20261117-175125, -203642, -234544):

| Score | Full | Quick |
|---|---|---|
| Event type | 83.7% | 87.8% |
| Topic status | 92.8% | 93.6% |
| Over-claimed | 7.8% | 9.4% |
| Disposition | 83.5% (80.0-85.2, limit ±9) | 68.5% (not gated: 9 topics) |
| Faithfulness | 77.2% | 92.4% |

The AIML-2928 baseline it replaces (key v1.4): event type 81.0%, topic
status 80.0%, over-claimed 21.3%, disposition 67.8% (63.3-73.3, limit about
±15), faithfulness 56.3%.

**What was tried for the event-type rule (key v1.4):**

| Prompt | Runs | Event type | Topic status | Disposition | Faithfulness |
|---|---|---|---|---|---|
| PR #10 (before 2928) | 3 | 57.2 | 48.7 | 72.2 | 22.0 |
| Earlier 2928 prompt | 3 | 79.1 | 75.4 | 73.3 | 52.6 |
| New event-type wording + after-reminder clause | 3 | 79.8 | 73.9 | 67.8 | 48.5 |
| New wording, no clause | 2 | 81.4 | 70.4 | 70.0 | 47.2 |
| One-line front-desk exception | 1 | 82.6 | 72.3 | 70.0 | 43.2 |

Every version of the business rule in the agent's prompt made it mark
undiscussed campaigns as discussed, so the prompt keeps its earlier rule.
Editing the `planned_topics` instruction, the schema text and the
discussed=false hard rule made the agent answer 8-10 notes per run with an
empty turn, so those stay as measured.

### 4. The evals

| Eval | Command |
|---|---|
| Agent harness (the gate) | `uv run python -m evals.agent_eval.run quick` / `full`; `--rescore <run>` re-scores without the app and writes to `<run>/rescore-<mode>/`, never touching the run's files; `baseline export` takes those folders and refuses a run scored on another key. On 2929 a run also keeps its `app.log` and counts cases where the agent never replied |
| ADK eval | `uv run python -m evals.adk_eval.run quick` |
| `extract()` eval | `uv run python -m evals.extract_eval.run --model gemini-3.8-flash --allow-labelling-model --thinking low [--set golden topup synthetic]`; `--rescore <run>`; `compare <runs…>` prints the report table from the runs' files |
| Misses by pattern | `uv run python -m evals.agent_eval.diagnose <run or scores_<set>.json> [--show-unsupported N]` |

Rules that keep the numbers honest: noisy metrics leave the gate only when
the baseline records them (`--allow-noisy`); a run with >10% failed calls is
INVALID (both harnesses); a labelling model runs only with
`--allow-labelling-model` and is marked; a self-judging run is marked.

### 5. Answer-key decisions (all scripted, versioned, re-score only)

- **Event type** (`evals/dataset/fix_event_types.py`, v1.1 → v1.2): the
  labelling left it blank when the note didn't say HOW contact happened; the
  scorer read blank as "no person → On-site". Rule applied (Jeremy's, as
  written): Phone Call if a call; Meeting if any interaction, named or not;
  otherwise On-site (incl. person unavailable). 17 cases → Meeting: named —
  HL-003 HS-004 IN-013 IS-008 IS-009 IS-012 MH-002 MH-009 TR-012 TR-014;
  unnamed — HL-010 HL-015 HS-003 IN-009 IN-015 MH-006 TR-007. Confirmed by
  the business (2026-10-14), with the front-desk exception applied in v1.4.
- **Contact outcome U-02** (`evals/dataset/fix_contact_outcome.py`, v1.2 →
  v1.3): rule decided from the must-capture sheet (U-02 is P1, "capture on
  every call") — **a field is filled when the note clearly shows it**. Where
  the key shows an interaction and U-02 is blank → "spoke with contact" (21
  cases, each read). The scorer accepts target/alternate against it.
- Both scripts refuse a key they weren't written for or have already been
  applied to. The U-02 script counts only a Meeting as a conversation (a
  Phone Call can end at a voicemail). Top-up and synthetic
  keys are not reviewed (AC2 covers golden only); doing it means the same
  case-by-case read of their blank event types and U-02, then the same two
  scripts.

### 6. AIML-2929 — done (proof in `docs/AIML-2929-model-comparison.md`)

**Chosen:** gemini-3.8-flash, thinking **low**, global endpoint (approved).
`minimal` is rejected by the API for 3.8-flash.

| Golden, v1.3, mean of 3 runs | Agent | **3.8-flash low** | 3.7-flash low |
|---|---|---|---|
| Event type | 80.5% | **93.9%** | 94.2% |
| Topic status | 75.4% | **94.9%** | 93.8% |
| Over-claimed | 27.3% | **0%** | 0% |
| Faithfulness | 52.6% | **93.3%** ¹ | 90.2% |
| P1 / all field recall | 0% | **79.6% / 81.5%** | 80.2% / 82.0% |
| Invented values | — | **1.6%** | 1.7% |
| Median / p95 per note | — | **3.8 s / 8.9 s** | 3.9 s / 7.8 s |
| $ per 1,000 notes (2027) | — | **$2.93 ($5.86)** | $2.97 ($5.93) |

¹ judged by 3.8-flash itself; 3.8-flash also helped label the golden set —
3.7-flash (independent) scoring the same shows the effect is small.
Default thinking: same quality on topics/event type, 3× slower and 2–3×
the cost; 3.8 default has P1 recall 57.1% (fails the proposed ≥ 60%).
2.5-flash (regional): 91.6 / 92.3 / 2.0% over-claimed, $3.90, 8.1 s.

### 6a. AIML-2929 — final PR figures (what the PR description quotes)

**Current:** run `extract-20261104-235607` on `090f8f5`, re-scored on `1fbae31` (same figures; unconfirmed topics
keep their summary); golden key v1.4 (`32a1988b`), 3 runs, gemini-3.8-flash,
thinking low, global endpoint. Event type 95.7, topic status 94.9,
over-claimed 0.0, faithfulness 92.2, P1 / all recall 90.5 / 91.4, invented
1.6, value accuracy P1 / all 80.9 / 78.5, errors 0 of 270, unconfirmed 0.0,
USD 3.02 / 6.04, p50 / p95 3.81 / 9.06 s. Event type moved 90.7 → 95.7 with
no prompt, schema or key change (model-side variation); no topic was
unconfirmed, so the summary change did not touch this run.

Previous (kept for reference): run `extract-20261102-172210` on `3b97f61`,
re-scored with the final scorer (same figures); golden key v1.4, 3 runs,
scores are the mean, cost and time cover the answered calls;
gemini-3.8-flash, thinking low, global endpoint.

| Score | Value |
|---|---|
| Event type | 90.7% |
| Topic status | 95.3% |
| Over-claimed | 0.0% |
| Faithfulness | 90.3% |
| P1 / all field recall | 90.3% / 91.2% |
| Invented values | 1.5% |
| Value accuracy P1 / all | 80.2% / 77.0% (compare's mean over repeats) |
| U-02 | 158/159 under all four rule variants (`tools/u02_variants.py`) |

**Closing steps:** description header becomes "**Results** (run
`extract-20261102-172210` on `3b97f61`, re-scored with the final scorer, same
figures; golden key v1.4, 3 runs, scores are the mean, cost and time cover the
answered calls; gemini-3.8-flash, thinking low, global endpoint):"; post the
replies on the zero-cents nit and the role-at-reception comment, resolve; ask
Suresh; Squash merge as `AIML-2929: text extraction with a fixed schema, and
its eval`.

**Freeze rule:** the U-02 and amount rules are regex over free text and never
converge. New wording edge cases go to a scorer follow-up ticket, reply "Logged
for the scorer follow-up; it changes value accuracy only, not the go/no-go
figures." Only a real `extract()` bug or a go/no-go number change goes in.

**What the late scorer work covered** (in `evals/agent_eval/score.py`):
spoke/talked/met with no-one forms; "contact not available"; a named target
beats a gatekeeper; decision-maker roles at the desk (`_ROLE`, not possessive)
count as the contact; amounts compare after `_same_number` (thousands
separators, trailing zeros, `.0`) with `_within` on word edges. The harness
refuses an app whose `/healthz` shows `analytics` (or cannot be asked) and
starts its own with `BQ_ANALYTICS_ENABLED=false`, because golden notes are
customer notes. `extract()`: evidence (the cited sentences) needs 2 non-filler words, `_unmark`
spaces out `<<<`/`>>>`, notes over 10,000 chars are `error_kind="input"`.

**ACs** (Jira text as rewritten):
1. Schema-valid JSON for every case, no repair; discussed only with a quote;
   unit tests without a model — **met**: 0 errors / 0 dropped labels across
   every golden, top-up and synthetic run; tests cover schema, the evidence
   check (a quote then; sentence numbers since AIML-3152),
   mapping, label enum, usage, invalid runs.
2. Golden event types follow the approved rule before scoring; baseline
   re-scored — **met** (v1.2, v1.3 and v1.4 manifests list every id).
3. One command, scorecard in the harness format, a non-labelling model, 3
   runs — **met** (3.7-flash is the independent measurement).
4. Go/no-go — **met on the proposed targets**; Suresh's agreement comes on
   the PR.

**How it works:** `app/extraction/` — `catalog.py` (19 fields per vertical),
`campaigns.py` (registry repaired: the source file's Replace All damage;
the visit's vertical wins for duplicates; ~300-char descriptions),
`extract.py` (schema with topic labels as an enum of the planned titles,
evidence checked in code → `unconfirmed` (a quote found in the note at
first; since AIML-3152 the model cites sentence numbers and code copies the
words), count field U-10 needs a
number, usage tokens/time recorded, `thinking`).

**Bugs found on the way (and the lesson):** labels came back as "Title:
description" in 47/90 cases and were silently dropped → schema enum + dropped
labels reported; the faithfulness judge was also the model under test →
marked; a 100%-failed run looked like a regression → INVALID rule; the
coverage figure "26%" was counted on damaged names → 66%.

### 7. Messages / tickets outside the code

- Dharun: the token-refresh bug (a refresh to `oauth2.googleapis.com` times
  out and kills the live stream). Team: Docker image from `uv.lock`.
- Suresh: the 26% → 66% correction to the proposal; AIML-2929 approval on
  PR #13; confirm dev-deployment items 1, 2, 5 (rate limit, one connection
  per session, resumption) and 7-9 of the gaps list (§10).
- Team chat (SellNTell updates): dev test results and the 12-gap list posted;
  reply to Sainitheesh on `instruction_for_model` posted.
- Bobby: AIML-3011 split reply (§11).
- Jira: AIML-2929 (ACs + link the report); AIML-2957 and AIML-2962 linked to
  AIML-2702.

### 8. Environment notes

- `app/.env`: `VERTEX_AI_AGENT_ENGINE_ID` (a borrowed engine; our own comes from
  another team) and `VERTEX_AI_AGENT_ENGINE_LOCATION=us-central1`.
- `uv run` re-syncs to the branch's lock (ADK 2.1.0 on 2702, 2.10.0 from
  2928).
- Model access (`evals/dataset/probe_models.py`): every 3.x model is
  **global only** in this project (404 in us-central1 and us-east1);
  2.5-flash/pro work regionally. No 3.7/3.8 Pro.
- Token fetches to Google time out on long runs; the harnesses retry.

### 9. The new architecture

`architecture-proposal-suresh.md` (sent) / `architecture-proposal.md`.
AIML-2929 is its go/no-go for `extract()`. Registry coverage corrected to
66% of real topic mentions (68% multifamily). Suresh's steer on topic
mapping ("confidence, reconfirm when unsure") is in `extract()` as
evidence-checked topics → `unconfirmed`.

### 10. Dev deployment — tested, gaps posted

Sainitheesh deployed `a074174` to the dev environment (Cloud Run
`sellntell-dev`, us-central1, `prj-hds-np-data`, revision
`sellntell-dev-00002-hqt`). Callers need a Google ID token and must be on the
invoker list. The deployed build is older than `origin/development`: no
silence watchdog, no 2928 prompt fixes, no BigQuery logging, old model.

**Service settings:** min/max instances 0/5, concurrency 160, timeout 600 s,
ingress `internal-and-cloud-load-balancing`, `BQ_ANALYTICS_ENABLED=false`,
`VOICE_NOTES_AGENT_MODEL=gemini-live-2.5-flash-native-audio` (pinned, so a
redeploy alone keeps the old model), `VOICE_NOTES_VAD_SILENCE_MS=2000`,
`VOICE_NOTES_RECONNECT_SAME_SESSION=false`.

**How to test it:** only from **Cloud Shell**. On the corporate VPN the DNS
has no record (public DNS has Cloudflare IPs) and the path asks for TLS
renegotiation that Python cannot do; curl works for REST only. Turning the
VPN off is not allowed. `gcloud run services proxy` is refused (ingress is
load-balancer only). Three test scripts, kept outside the repo (synthetic
notes, no customer data), run in Cloud Shell with
`export ID_TOKEN=$(gcloud auth print-identity-token)`: a smoke test (healthz,
session, WS, one turn), typed scenarios (7 scenarios + protocol guards), and a
voice test (Cloud TTS
speech streamed as 16 kHz PCM: transcription, pauses, barge-in, silence,
noise, multi-topic, 3 at once). Each test leaves sessions under
`smoketest`/`demotest`/`voicetest` in Agent Engine (no TTL).

**Measured:** 94% of words heard (91% with noise); agent speaks ~3.5 s after
the rep stops; a visit saves in 12-22 s; waits through a 1.5 s pause; stops
0.2 s after barge-in and applies the correction; saves only on a yes; skipped
planned topic asked; off-plan topic captured; Meeting and Phone Call right;
3/3 parallel visits saved; 4409 on a second connection; 1008 on a bad id.

**Gaps posted to the team** (can't do yet): 1 no silence nudge (old build);
2 pauses over ~2 s end the turn; 3 read-back after a correction doesn't say
the new value (`notes_workflow.py` change list); 4 unknown session or another
`user_id` drops with 1006 (`get_session` raises genai 400 at `main.py` ~1015,
uncaught); 5 `instruction_for_model` and the raw ADK event stream reach the
client; 6 typed text logged in full ("Upstream text"); 7 no session TTL,
resumption on; 8 `user_id` not tied to the caller, no rate limit; 9
one-connection lock is per instance, max 5; 10 model pinned, BigQuery off;
11 no browser access (ID token, ingress) and no VPN DNS; 12 cold start.
Fixable by: redeploy + env (1, 10, plus prompt fixes, CORS, np fallbacks);
small app changes (2-6); after a decision (7-9); deployment/network (11, 12).
Items 3 and 4 are also in current development.

**Sainitheesh's questions** (deployment message): we answered 3, 4, 6 as ours
(log text length only, delete session after commit + short TTL, CORS from
env / strip `instruction_for_model` from the client copy / remove np
fallbacks) and gave suggestions for 1, 2, 5 for Suresh to confirm. His
follow-up on `instruction_for_model`: confirmed the plan — in the downstream
task, copy the event and delete only that key from function responses before
`send_text`; the model keeps the original. The UI reads `confirmation_text`,
`status`, `error`, `missing_topics`, `session_id`, `closing_statement` from
responses and fills the card from the `stage_visit_notes` call args, so a
one-key removal keeps everything it needs. Also told him: missing Agent Engine
ID already fails at startup, project has no np default, we'll add a project
startup check.

**Eval and the demo:** not needed for the demo. The golden set never goes to
the deployed URL (customer notes; no TTL, full logging there). Optional: one
local `agent_eval quick` on the commit before a redeploy. There is no
committed agent baseline file (`evals/baselines/golden_v1.json` absent).

### 11. AIML-3011 split (Bobby asked for 3-point stories)

| Story | Title | Points |
|---|---|---|
| AIML-3011 | Dialogue steps kept in session state (step machine, state in Agent Engine, resume after restart; not used by the live flow yet) | 3 |
| AIML-3116 | Live agent with one tool, `extract()` in the flow (`dictation_done()`, read-back and topic question from our code, `behavioral_rules.yaml` cut down) | 3 |
| AIML-3117 | Save gate, corrections, and harness conversations (save only from WAITING_FOR_YES after the latest read-back; harness scripts: happy, skipped topic, correction, no reply) | 3 |

Order 3011 → 3116 → 3117. 3116 and 3117 had no sprint when created.

### Guided is preserved

Tag `archive/guided-flow` on `9433908`:

```powershell
git checkout archive/guided-flow -- app/voice_notes_agent/tools_guided.py
```

---

## 1. Ticket status

| Ticket | Title | Status |
|---|---|---|
| **AIML-2702** | Eval harness | **Merged** (PR #10) |
| **AIML-2898** | Curate the vertical golden dataset | **Done**; data in `gs://sellntell-eval-np` |
| **AIML-2928** | ADK 2.10 + prompt fixes (5 pts) | **Merged** (PR #11) |
| **AIML-2929** | Text extraction with a fixed schema, go/no-go (5 pts) | **PR #13 open**, READY; closing steps in §6a |
| **AIML-3011 / 3116 / 3117** | Dialogue steps, one-tool live agent, save gate (3 pts each) | Backlog / sprint (§11) |
| **AIML-2957** | Run the golden-data tests in CI | Backlog |
| **AIML-2962** | Web UI and WebSocket follow the session contract | Backlog |
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
when stated. The new architecture (§9 of START HERE) is how; the eval is how
we know it worked.

---

## 3. Architecture

Checked against `development` at `85b108c`; since then development also has
the BigQuery plugin (AIML-2823), the AIML-3006 watchdog changes and the
`gemini-3.8-live` default (§1).

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
  (`compute_missing_topics`), commit and its idempotent replay. The staged
  record lives in `_STAGED_NOTES` and is also copied into ADK session state,
  from which `commit_visit_notes` rehydrates it after a restart.
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
- `config.py` — the silence watchdog's timeout settings (AIML-2910).
- `silence_watchdog.py`, `audio_detector.py` — AIML-2910: check-ins when the
  rep goes quiet, closing an idle session.

One agent, one Runner, one flow (implicit); guided is retired.

---

## 4. Environment

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

`index.html` loads `app.js?v=17`; `app.js` imports `audio-player.js?v=10` and
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

- `tests/test_notes_workflow_gates.py` (16 tests) — the staging/commit gates and read-back,
  on `development`. `tests/conftest.py` imports `notes_workflow` under a
  private package name so the ADK agent is never built.
- `tests/test_agent_eval_score.py` — the harness's scoring, the judge's reply
  handling, reading the record off the socket, the ADK summary units.
- `tests/test_agent_eval_regression.py` — quick subset, baseline export,
  noise limits and `not_gated`, the PASS / REGRESSION / INVALID verdicts, the
  line-ending-safe hash, per-case run log, cut-off lines, session endpoint.
- `tests/test_adk_eval_metrics.py` (7 tests) — the ADK custom metrics and
  config. Skip as a whole under ADK 2.1.0 (the 2702 branch); run from 2928 on.
- `tests/test_prompt_rules.py`, `tests/test_session_metadata_keys.py` — 2928.
- `tests/test_extraction.py` — 2929: catalog, schema, evidence check,
  settling the record, scorer mapping (a stand-in client, no model).
- Every eval test was checked by breaking the code it covers; each break fails
  a test. Most tests that read the golden set skip when it is absent;
  `test_dataset_topup.py` (local only) fails instead.
- Counts: `development` (after PR #11) 126 passed; the AIML-2929 branch 210
  passed; locally about 310 with the local-only dataset tests.
- `tests/test_dataset_*.py` — the curation pipeline; local only, like the
  pipeline.

**Model-level** — the eval (START HERE §4) is the scored check.
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

**Check what a label meant when it was made.** A blank event type meant "how
the contact happened is unknown"; the scorer later read it as "no person".
Half the event-type "misses" after 2928 were that mismatch, not the agent.

**A known repair has to reach every count.** The Campaign Topics damage was
repaired in the dataset code, but the coverage count in the proposal was run
before the repair: 26% instead of 66%.

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
2. **Event-type rule** — settled: confirmed by the business (2026-10-14); in key v1.4 and `extract()`.
3. **AIML-2929 go/no-go numbers** — margin and field targets, to agree with Suresh.
4. **Disposition codes** — does anything downstream need a per-topic code? If
   not, drop them; if yes, derive them from U-02 / U-04 / U-06.
5. **Own Agent Engine** for sell-n-tell (the current one is borrowed).

Settled: ADK 2.10 (AIML-2928); golden data out of the repo, in the bucket;
"discussed" = the rep talks about the campaign's offer or products (Suresh's
steer: reconfirm when unsure — evidence-checked topics in AIML-2929).

---

## 8. Document index

| File | Contents |
|---|---|
| `HANDOFF.md` | this file — start here |
| `architecture-proposal-suresh.md` | **next work**: the architecture proposal for Suresh, with the review merged in |
| `architecture-proposal.md` | the fuller internal proposal (kept/removed components, rollout, risks) |
| `AIML-2702-baseline.md` | the first eval baseline (before 2928): scores, patterns, causes, the disposition-code question |
| `AIML-2702-review-fixes.md` | PR #10 review: rounds 1–2, each comment, fix and reply; the AIML-2957 story text |
| `AIML-2929-model-comparison.md` | **AIML-2929 proof**: quality, cost, latency per model; key versions; the field rule; run folders |
| `AIML-2929-review-findings.md` | every round of automated review findings on the 2928/2929 branches: verdict, fix and status |
| `AIML-2929-results-summary.md` | the AIML-2929 results for Suresh: the go/no-go table and how to verify it |
| `architecture-stories.md` | the 22 stories for the new architecture, with pick order and open questions |
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

### Story list for the new architecture

`docs/architecture-stories.md`: 22 stories, 109 points, by phase with a pick
order; citations match `architecture-proposal-suresh.md`. Sent to Suresh
(2026-10-20) with seven questions: AIML-3003 one call enough, AIML-3004
disposition codes needed, CRM ids on the record, backend or devices calling
us, who sends the quarterly Campaign Topics export, confirm our BigQuery copy,
confirm no raw audio. Decided: `extract()` on global, Model Armor screens the
transcript (not Live audio), Agent Engines come from another team.
