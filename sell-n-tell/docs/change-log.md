# Change log

Running record of every change we make, why it was made, and how it was
verified. Append new batches at the bottom; do not rewrite history.

Evidence and reproductions live in `AIML-2698-experiments.md`.

**Status key:** `verified-live` (proven in a real session) ·
`verified-rest` (proven via the REST suite only) · `untested` ·
`mitigation` (reduces but cannot eliminate the problem)

---

## Batch 1 — Coverage gate + campaign rules (implicit)

Ticket: AIML-2698 · Commit: `321d3e3`

| File | Change | Why |
|---|---|---|
| `mock_db.py` | `validate_against_campaign()` | Campaign config was injected into the prompt but never used to validate output |
| `mock_db.py` | `IncompleteCoverageError`; `commit_notes` raises it before marking the record committed | `missing_topics` was computed and stored on the record, never used as a gate |
| `mock_db.py` | `stage_notes` records `campaign_type` | So the commit gate re-checks against the campaign the record was staged under |
| `main.py` | `StagedVisitPayload.campaign_type`; stage → `422`, commit → `409` | The staging endpoint had no `campaign_type` param, so campaign rules could not be enforced |
| `tools.py` | `_allowed_codes()`; sends `campaign_type`; converts `422`/`409` into spoken re-asks | Codes were validated against the global registry, resolved at import |

**Status:** `verified-live` (409 blocked a commit mid-conversation; agent
recovered and asked for the missing topic).

---

## Batch 2 — Guided mode + a regression we introduced

Ticket: AIML-2698 · Commit: pending

| File | Change | Why |
|---|---|---|
| `tools_guided.py` | `_campaign_rules()`; campaign-scoped codes and event types | Same global-registry bug as implicit (lines 25 and 207) |
| `tools_guided.py` | Sends `campaign_type`; handles `422`/`409` explicitly instead of `raise_for_status()` | A rule violation was being reported to the rep as "temporary problem saving, try again" |
| `mock_db.py` | `validate_against_campaign` honours `needs_manual_review` | **Regression from Batch 1:** the new validator rejected `discussed=true` + no code, which is guided's legitimate 3-strikes escape hatch |

**Status:** `verified-rest`. Guided's conversational state machine has **not**
been exercised live.

---

## Batch 3 — Frontend: stop reporting success on a refused commit

Ticket: AIML-2698 (regression from Batch 1) · Commit: pending

| File | Change | Why |
|---|---|---|
| `static/js/app.js` | `handleFunctionResponse` tests `!resp.crm_record_id` instead of `status === "error"` | Commit gained `blocked` and `rejected` outcomes; the UI matched only `error`, so a refused commit fell through and displayed "Saved to CRM. Session complete." for a record that was never written |
| `static/js/app.js` | Refusal path resets the badge to `staged` and logs `missing_topics` | Leaves the rep in the confirm phase so they can answer and retry |
| `static/js/app.js` | `renderPayload` clears `pCrmId` | A staged record was showing the previous session's CRM id |

Testing for a record id rather than enumerating failure statuses means a future
refusal defaults to "not saved" instead of silently claiming success.

**Status:** `verified-live` (banner, badge, CRM id and console log all correct
on a blocked commit).

---

## Batch 4 — Skips must come from the rep, not the model

Ticket: AIML-2698 · Commit: pending · Evidence: F3

| File | Change | Why |
|---|---|---|
| `mock_db.py` | `compute_missing_topics(..., allow_skips)` | Coverage counted a topic as addressed if its label was present, regardless of `discussed`. Presence carries no provenance |
| `mock_db.py` | `stage_notes` sets `allow_skips = previous is not None`; stored on the record for the commit gate | A skip is only trustworthy after the rep was asked — which is exactly what a re-stage represents. Encodes an ordering that previously existed only in prose |
| `mock_db.py` | `DiscussionTopic.executive_summary` now optional | It was required, so a skipped topic *forced* the model to invent a reason |
| `agent.py`, `tools.py` | `discussed=false` only after asking; omit unmentioned topics; leave summary empty if no reason given | Aligns the prompt with the enforced rule and avoids a wasted round trip |

**Status:** `verified-live` (model no longer self-skips; topic summary came back
as "Topic was skipped." with no invention).

---

## Batch 5 — Let the agent say "I don't know"

Ticket: AIML-2698 · Commit: pending · Evidence: F2/F5

| File | Change | Why |
|---|---|---|
| `tools.py` | `_normalize_topics` carries `needs_manual_review` through, and no longer treats "discussed, no code" as an error when it is set | **The flag was unreachable from implicit mode** — the topic dict was rebuilt from scratch and the field silently dropped, so nothing could ever set it |
| `tools.py` | Documents `needs_manual_review` in the `stage_visit_notes` docstring | The model had no way to know the option existed |
| `agent.py` | Prompt: match on the OUTCOME, not on which keywords appear; if no allowed code fits, ask the rep, then flag rather than choose the nearest | Baseline showed the same utterance mapping to codes 2 and 3 — opposite meanings, both wrong |
| `agent.py` | Prompt: never state a skip reason the rep did not give, including in the overall summary | F4b: the invention relocated from the topic summary to the call summary |

**Status:** `untested` · `mitigation`. This converts a silently wrong record
into a flagged one. It does **not** fix the root cause — see the open decision
below.

---

## Open: needs a decision from the project lead

**The `renewals` disposition registry has no code for "customer is interested
and requested a quote."** Measured behaviour, one utterance, four runs:

| Run | Campaign | Code | Correct? |
|---|---|---|---|
| 1 | renewals | 2 — Order Placed | no (nothing was ordered) |
| 2 | renewals | 3 — No current need | no (opposite of run 1) |
| 3 | renewals | 3 — No current need | no |
| 4 (control) | renewals | 8 — Pricing concerns | **yes** |

Run 4 proves the model maps correctly when a correct code exists, so the fault
is the registry, not the agent. In run 1 the free-text summary was accurate
("next step is to prepare and send a formal quote") while the disposition code
said Order Placed — the structured field that feeds reporting was the wrong one.

Options: add code 1 to `renewals`, or add an explicit "outcome does not fit"
code. Either is a product decision.
