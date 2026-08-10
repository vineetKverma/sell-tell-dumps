# AIML-2698 — Reproduction Log

Evidence for **Close Implicit/Guided Agent Gaps (Disposition + State Correctness)**.
Satisfies AC#1 ("Repro scripts for the log failures above").

Every experiment below runs against the **REST layer only** — no microphone, no
Gemini, no Vertex AI, no BigQuery. The failures are in application logic, not in
the model, so they reproduce deterministically and cost nothing to run.

---

## Test environment

| Setting | Value | Why |
|---|---|---|
| Branch | `feature/AIML-2698-disposition-state-correctness` | cut from `feature/AIML-2130-guided-flow` @ `3ecd956` |
| Server | `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` | |
| `VOICE_NOTES_BQ_ENABLED` | `false` | BigQuery writes disabled — keeps logs clean, removes an external dependency |
| AI / Vertex | **not used** | every experiment hits REST endpoints directly |
| Store | in-memory (`mock_db.py`) | resets on server restart |

> Because the store is in-memory, restarting the server clears all staged and
> committed records. Re-run the experiments after any restart.

### Reference: campaign rules

Retrieved from `GET /api/v1/config/agent-schema?campaign_type=...`

| Campaign | Allowed event types | Allowed disposition codes |
|---|---|---|
| `standard_sales` | Meeting, On-site visit, Phone Call | 1–10 (all) |
| `renewals` | Phone Call, Meeting | 2, 3, 5, 8, 9 |
| `enterprise_field` | Meeting, On-site visit | 1, 2, 4, 5, 8 |

Disposition registry (standard_sales): 1 Create Opportunity · 2 Order Placed ·
3 No current need – revisit · 4 Contracted to buy from competitor · 5 Buying
from preferred vendor already · 6 Not a product/service they use · 7 Does not
meet brand guidelines · 8 Pricing concerns · 9 Recently discussed ·
10 Customer recently purchased related item(s)

---

## Experiment 1 — Commit succeeds with an uncovered planned topic

**Ticket AC:** #3 — *"Commit never succeeds without a valid stage + full
planned-topic coverage"*

**Hypothesis:** `missing_topics` is computed and reported but never enforced, so
a record can be committed while a planned topic has no outcome.

### Steps

```powershell
# Stage a record that covers only 1 of 2 planned topics ("Pricing" omitted).
$body = @{
  event_type = "On-site visit"
  executive_summary = "Visited Acme. Renewal on track; pricing pushback."
  raw_transcript_backup = "Just left Acme..."
  topics = @(
    @{ topic = "Contract / agreement renewal"; disposition_code = 3; executive_summary = "Wants to re-sign."; discussed = $true }
  )
  planned_topics = @("Contract / agreement renewal", "Pricing")
} | ConvertTo-Json -Depth 5

$stage = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/notes/stage" -Body $body -ContentType "application/json"
$stage | ConvertTo-Json -Depth 5

# Commit it anyway.
$commit = @{ session_id = $stage.session_id; confirmed = $true; agent_mode = "implicit"; campaign_type = "standard_sales" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/notes/commit" -Body $commit -ContentType "application/json"

Invoke-RestMethod "http://localhost:8000/api/v1/notes/committed" | ConvertTo-Json -Depth 5
```

### Result — **FAILS (bug confirmed)**

Staging correctly detects the gap:

```json
{
  "session_id": "04038b1c-98ef-4db0-8534-e433a5089b6a",
  "confirmation_text": "... you'd planned to cover Pricing, but I didn't hear an outcome on that topic. What happened with Pricing? ...",
  "missing_topics": ["Pricing"],
  "all_topics_covered": false
}
```

Commit accepts it regardless:

```
status   crm_record_id    closing_statement
success  CRM-B598122C53   Saved successfully. Have a great day!
```

And the committed CRM record carries the incompleteness as stored data:

```json
{
  "crm_record_id": "CRM-B598122C53",
  "planned_topics": ["Contract / agreement renewal", "Pricing"],
  "missing_topics": ["Pricing"],
  "committed_at": "2026-08-09T12:39:43.397172+00:00"
}
```

### Analysis

`mock_db.commit_notes` calls `compute_missing_topics` and writes the result onto
the committed record, but never branches on it. No layer treats it as a gate:

- `tools.py :: commit_visit_notes` — checks staged session + turn guards only
- `main.py :: commit_notes` — passes straight through
- `mock_db.py :: commit_notes` — computes, stores, commits

The only thing discouraging a premature save is prompt text
(`instruction_for_model`: *"Do NOT save yet"*), which is model-dependent and
therefore not a guarantee.

---

## Experiment 2 — Campaign rules are not enforced

**Ticket AC:** #2 — *"100% valid disposition codes on golden scripts for both
modes (no invented codes)"*

**Hypothesis:** validation uses the global registry rather than the active
campaign's, so a campaign-illegal event type and disposition code are accepted.

### Steps

```powershell
# renewals allows only event types [Phone Call, Meeting] and codes [2,3,5,8,9].
# This payload violates BOTH: "On-site visit" and code 1.
$bad = @{
  event_type = "On-site visit"
  executive_summary = "Renewals call with Acme."
  raw_transcript_backup = "They're interested, wants a quote..."
  topics = @(
    @{ topic = "Contract / agreement renewal"; disposition_code = 1; executive_summary = "Wants a quote."; discussed = $true }
  )
  planned_topics = @("Contract / agreement renewal")
} | ConvertTo-Json -Depth 5

$s2 = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/notes/stage?campaign_type=renewals" -Body $bad -ContentType "application/json"
$s2 | ConvertTo-Json -Depth 5
```

### Result — **FAILS (bug confirmed)**

```json
{
  "session_id": "4032cae1-9391-481f-93e9-14a324d620e4",
  "confirmation_text": "Got it. Here's my summary: Renewals call with Acme. I've staged an On-site visit covering Contract / agreement renewal marked as create opportunity. Should I save this, or do you want to change something?",
  "missing_topics": [],
  "all_topics_covered": true
}
```

Both illegal values were accepted, and the confirmation text reads the illegal
disposition back to the rep as though it were valid — the "silent wrong code"
failure named in the ticket.

### Analysis — root cause

**The staging endpoint does not know which campaign it is staging for.**

`POST /api/v1/notes/stage` accepts no `campaign_type` parameter
(`main.py :: stage_notes` takes only the payload and `previous_session_id`), so
the `?campaign_type=renewals` above was silently ignored by FastAPI. With no
campaign in scope, both validators fall back to global lists:

| Check | Location | Validates against | Should validate against |
|---|---|---|---|
| event type | `main.py:212` | `mock_db.VALID_EVENT_TYPES` (all 3) | campaign's `allowed_event_types` |
| disposition code | `tools.py:32` | `VALID_DISPOSITION_CODES` (all 10, resolved at import) | campaign's `disposition_registry` |

The campaign config is injected into the model's **prompt** but never used to
**validate** the model's output. The fix requires threading `campaign_type`
through to the staging endpoint before either check can be made campaign-aware.

---

## Experiment 3 — `turn_guard` state is never reset *(not yet reproduced)*

**Ticket rows:** Guided — *"Tools blocked on 'no new reply'"*

Found by code reading; needs a live WebSocket session to demonstrate, so it is
not yet covered by a REST-only repro.

`turn_guard` keeps four module-level dicts keyed by `session_id`
(`_TURN_COUNTS`, `_BASELINES`, `_AWAITING_READBACK`, `_NUDGE_SENT`). Nothing
clears them — the WebSocket teardown in `main.py` closes only the
`LiveRequestQueue`. Because sessions are reused by `session_id`, a reconnect
inherits the previous connection's guard state, so a commit can be blocked by a
readback owed on an earlier connection.

**Proposed repro:** connect with a fixed `session_id`, stage notes, disconnect
before the readback completes, reconnect with the same `session_id`, and attempt
a commit. Expect `commit_visit_notes BLOCKED: confirmation_not_read`.

---

## Verification after fix

Re-ran both experiments against the fixed build. `Invoke-RestMethod` throws on
4xx, so the calls are wrapped in `try/catch` to read the status and body.

### Experiment 1 re-run — **now blocked**

Staging is unchanged (`missing_topics: ["Pricing"]`, `all_topics_covered:
false`); the commit is refused:

```
BLOCKED as expected -> 409
{"detail":"Planned topics still have no outcome: Pricing",
 "error":"incomplete_coverage","missing_topics":["Pricing"]}
```

No CRM record is written, and the staged record stays usable so the agent can
collect the missing outcome and re-stage.

### Experiment 2 re-run — **now rejected**

`campaign_type` now travels in the request body (the earlier query-string
attempt was silently ignored because the endpoint had no such parameter):

```
REJECTED as expected -> 422
{"detail":"event_type 'On-site visit' is not allowed for the 'renewals'
  campaign; choose one of: Phone Call, Meeting; disposition_code 1 on topic
  'Contract / agreement renewal' is not in the 'renewals' registry; allowed
  codes are: 2, 3, 5, 8, 9",
 "campaign_type":"renewals",
 "allowed_event_types":["Phone Call","Meeting"],
 "allowed_disposition_codes":[2,3,5,8,9]}
```

Both violations are reported in a single response, along with the legal values,
so `tools.py` can hand the model a concrete re-map instruction rather than a
bare failure.

### What changed

| File | Change |
|---|---|
| `mock_db.py` | `validate_against_campaign()`; `IncompleteCoverageError`; `stage_notes` records `campaign_type`; `commit_notes` raises before marking the record committed |
| `main.py` | `StagedVisitPayload.campaign_type`; staging validates per campaign → `422`; commit → `409` on incomplete coverage |
| `tools.py` | sends `campaign_type`; validates codes against the session's campaign registry (`_allowed_codes`) rather than the global list; converts `422`/`409` into spoken re-ask instructions |

Enforcement deliberately lives in the **REST layer**, not in the ADK tools:
the tools reach the API over HTTP, so implicit, guided, and hybrid modes all
inherit the same gate from one implementation.

### Regression suite (REST layer)

Six cases, all passing after the fix. The first two are the bugs; the rest
prove the gates do not block legitimate records. Run as one PowerShell block
against a running server — see `scripts/` for the intended permanent home.

| Case | Payload | Expected | Result |
|---|---|---|---|
| A | planned topic with no outcome → commit | `409 incomplete_coverage` | PASS |
| B | `renewals` + `On-site visit` + code `1` → stage | `422` naming both violations | PASS |
| C1 | all planned topics covered → commit | `200` + `crm_record_id` | PASS |
| C2 | `renewals` + `Phone Call` + code `8` → stage | `200` | PASS |
| C3 | topic with `discussed=false`, no code → commit | `200` (deliberate skip is a valid outcome) | PASS |
| C4 | `discussed=true`, no code, `needs_manual_review=true` → commit | `200` (escape hatch preserved) | PASS |

C4 exists because the first version of `validate_against_campaign` rejected
"discussed but no disposition_code" unconditionally, which would have broken
guided mode's 3-attempt escape hatch: the rep would have heard "temporary
problem saving, try again" every time instead of the topic being flagged for a
human. The validator now honours `needs_manual_review`.

**Scope limit:** these exercise the REST layer, where all enforcement lives.
They do **not** exercise guided mode's conversational state machine
(`capture_dictation` → `choose_post_dictation_action` → `set_event_type` →
`record_topic_disposition` → `commit_guided_notes`), which needs a live
WebSocket session or an extended `ws_smoke_test.py`.

## Live session results (implicit mode)

Real WebSocket sessions against Vertex AI with native audio. Campaign
`standard_sales`, planned topics *Contract / agreement renewal* and
*Pricing & promotions*.

### L1 — happy path: **PASS**

Dictated both topics. The model emitted a single `stage_visit_notes` call,
copied both planned-topic labels verbatim (so coverage matched), spoke the
confirmation, waited for a reply, and committed on "Save" — `CRM-BF661C5CA6`.
No `BLOCKED:` lines; native audio throughout.

### L2 — coverage gate live: **PASS**

Dictated only the renewal, leaving *Pricing & promotions* uncovered.

1. Readback asked for the missing outcome instead of offering to save.
2. Said "Save it" anyway → `commit_visit_notes` returned the `409`, and the
   agent spoke: *"I still need an outcome for Pricing & promotions before I
   can save. What happened with that topic?"* — recovered cleanly, no loop,
   no silence, no error text read aloud.
3. Answered "I didn't get to the pricing" → re-staged with the topic as
   `discussed=false` and the call summary updated.
4. "Save" → committed as `CRM-20E3FED366`.

This is AC#1's "clear agent recovery" and AC#3's coverage gate demonstrated in
a live conversation, not just at the REST layer.

## Findings from live runs (not yet fixed)

### F1 — Frontend reports success on a blocked commit *(regression, ours)*

During L2 step 2, with nothing saved, the UI showed **"Saved to CRM. Session
complete."** and flipped the record badge to **committed**, directly
contradicting what the agent said aloud.

`commit_visit_notes` now has three outcomes (`success` / `blocked` / `error`);
the frontend appears to treat any tool result as success, which was safe only
while commit could not fail cleanly. A viewer sees a CRM confirmation for a
record that does not exist. Fix belongs in `app/static/js/app.js`: branch on
`status`, keep the record `staged` when blocked, and surface `missing_topics`.

Related: the panel kept showing the **previous** session's `crm_record_id`
next to a `staged` badge — staged records have no CRM id, so it should clear
on each new stage.

### F2 — Disposition mapping is inconsistent for the same outcome

The same real-world outcome ("customer agreed to re-sign for another year")
mapped to different codes across runs:

| Run | Code assigned | Reads in the CRM as |
|---|---|---|
| L1 | 5 — Buying from preferred vendor already | customer is committed to *another* supplier (lost) |
| L2 | 2 — Order Placed | closed the sale (won) |

Both are valid `standard_sales` codes, so AC#2 ("100% valid disposition codes")
passes either way — but they mean opposite things to a manager reading the
record. Code 5's `mapping_keywords` ("preferred vendor", "happy with current
supplier") genuinely match the rep's *words*, so the model matched phrasing
rather than outcome.

Root cause is structural, not a model defect: **every code in the registry is a
reason a sale did or did not advance, and there is no "renewal agreed"
outcome.** Lowering temperature will not fix it — the registry has no correct
answer to select. Options: add a renewal-positive disposition, or require
confirm-or-clarify when two codes compete (the ticket's "confirm-or-clarify,
never silent wrong code"). Needs a product decision, not just code.

**Note the distinction for the ticket: validity and correctness are different
problems. We fixed validity. Consistency remains open.**

### Still outstanding

- `turn_guard` reset on WebSocket teardown (Experiment 3, not yet reproduced).
- Fold the six REST cases above into `scripts/ws_smoke_test.py`, and add the
  conversational cases it cannot cover: malformed args, premature commit,
  skip-topic, correction path.
- Guided mode's tool-level fixes are verified only indirectly (through the REST
  layer). The state machine itself still needs a live-session run.
- Readback omits skipped topics: with `discussed=false`, `confirmation_text`
  lists only discussed topics, so the rep confirms a save without hearing that
  the topic was recorded as skipped. Not introduced by this work; likely
  AIML-2697 (FAR-facing copy) rather than this ticket.

## Status summary

| # | Issue | AC | Status |
|---|---|---|---|
| 1 | Commit ignores uncovered planned topics | #3 | Reproduced → **fixed, verified (409)** |
| 2 | Campaign event types / disposition codes unenforced | #2 | Reproduced → **fixed, verified (422)** — implicit + guided |
| 3 | `turn_guard` state leaks across connections | — | Code-read only, not yet fixed |

### Already fixed on this branch (ticket rows now stale)

The ticket's first three "known gaps" appear to be addressed already at
`3ecd956` and should be re-verified rather than re-fixed:

- **Splintered `topics`** — `tools.py :: _normalize_topics` coerces strings and
  partial objects, drops out-of-registry codes, and returns a re-ask instead of
  raising (an exception inside a tool tears down the live stream).
- **Commit with no staged session** — rejected in `tools.py :: commit_visit_notes`.
- **"Tools blocked on no new reply"** — was a defect *in the guard itself*: an
  earlier version stored counters in ADK session state and always read a stale
  baseline, permanently blocking commits. Rewritten to process-local dicts
  (see the `turn_guard` module docstring).

### Open question

Branch `feature/AIML-2686` ("Added hybrid (partial guidance) flow") forks from
the same commit as this branch and adds a **third** mode. Neither AIML-2698 nor
AIML-2697 accounts for it. Confirm with the project lead whether fixes should be
based on `AIML-2686` instead, and whether hybrid is a third selectable demo mode.
