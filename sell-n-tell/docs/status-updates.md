# SellNTell — ticket portfolio & progress log

Epic: **AIML-1537 SellNTell - V1**

---

## Ticket portfolio

| Ticket | Title | Pts | Sprint | Status |
|---|---|---|---|---|
| **AIML-2698** | Close Implicit/Guided Agent Gaps (Disposition + State Correctness) | — | — | **Code complete, verified.** 3 of 5 ACs fully met, 2 partial |
| **AIML-2703** | Correction & Re-stage Reliability (Both Flows) | 3 | Q3-**S2** | Not started — *earliest sprint, do next* |
| **AIML-2702** | Eval Harness: Faithfulness / Factualness / Contextualness | 3 | Q3-**S3** | Not started |
| **AIML-2697** | FAR Demo Hardening: Mode Selection UX + Demo Script | — | — | Not started (mostly frontend) |

### AIML-2698 acceptance criteria

| AC | Status |
|---|---|
| 1. Repro scripts for the logged failures → fixed or blocked with clear agent recovery | ✅ 9 REST cases + live 409/422 recovery verified |
| 2. Smoke: 100% valid disposition codes, both modes, no invented codes | ✅ enforced per campaign — **caveat below** |
| 3. Commit never succeeds without a valid stage + full planned-topic coverage | ✅ verified REST + live |
| 4. Short "known failure modes + agent recovery" note for the FAR demo runbook | ✅ `demo-runbook-failure-modes.md` |
| 5. Lead review of before/after logs from a dual-mode dry run | ✅ 8 scenarios both modes (`ac5-guided.log`, `ac5-implicit.log`) — **pending lead review** |

**Caveat to state explicitly on AC#2:** it asks for *valid* codes. We deliver
that — every code is now guaranteed to be in the active campaign's registry.
But *valid* and *correct* are different properties. A campaign whose registry
lacks a fitting outcome will still produce a legal-but-wrong code; that is now
handled by code 99 rather than a silent guess, but the underlying registry gap
needs a product decision (see `note-disposition-registry-gap.md`).

---

## Progress log

### 2026-08-07 — Context and orientation

- Read the Confluence background, Lucid flow, README and the two tickets;
  established what the product is and where the POC diverges from the pitch
  (browser app + mock CRM, not the phone-call product described in Confluence).
- Cloned the repo, branched `feature/AIML-2698-disposition-state-correctness`
  from `feature/AIML-2130-guided-flow` @ `3ecd956` per the lead's instruction;
  unset upstream so a stray push cannot reach his branch.
- Reviewed all 12 source files. Produced a gap analysis: identified that ticket
  rows 1–3 were already fixed on the branch, and that two of the listed gaps
  (coverage enforcement, campaign-scoped validation) were genuinely open.
- Flagged `feature/AIML-2686` (hybrid flow) as an unaccounted third mode.

### 2026-08-09 — Environment, reproduction, first fixes

- Got the app running locally; verified config endpoints, VAD settings and the
  campaign registries.
- **Reproduced both open gaps at the REST layer, no AI required:**
  - commit succeeded on a record the system knew was incomplete
    (`CRM-B598122C53` stored `missing_topics: ["Pricing"]`)
  - a `renewals` payload was accepted with a forbidden event type and a
    forbidden disposition code
- Root-caused the second: `POST /notes/stage` accepted no `campaign_type`, so
  campaign rules could not be enforced at all; both checks fell back to global
  lists.
- Implemented the coverage gate (`409`) and campaign-scoped validation (`422`)
  in the REST layer so all agent modes inherit them. Built a 6-case regression
  suite. Committed `321d3e3`.
- Extended the same fixes to guided mode, and fixed a regression the new
  validator introduced against guided's manual-review escape hatch.

### 2026-08-10 — Live verification and three further defects

- Ran the first live sessions. Confirmed the coverage gate and agent recovery
  in a real conversation: rep said "Save" with a topic uncovered → `409` →
  agent asked for the missing outcome → rep answered → re-stage → commit.
- **Found and fixed three defects that only appear live:**
  1. The UI reported "Saved to CRM. Session complete." on a *refused* commit —
     a regression from our own change, since the frontend matched only one
     failure status. Now tests for a record id, so unknown outcomes default to
     "not saved".
  2. The model could mark a planned topic `discussed=false` with an invented
     reason, satisfying the coverage check without ever asking the rep. Skips
     now only count on a re-stage.
  3. A campaign registry with no fitting code produced random wrong
     dispositions (six runs of one utterance returned "Order Placed" or "No
     current need" — opposite meanings, both false). Added code 99 "Outcome not
     covered", verified over six runs that it fires only when no real code
     fits.
- Regression suite grown to 9 cases, all passing.
- Produced handoff, change log, evidence log and a sign-off note for the lead.

**Method note:** four of the fixes followed the same pattern — a prompt rule
losing to a structure pointing the other way. One attempt (prompt-only) was
measured before and after and made no difference; it is recorded as a failed
attempt rather than a fix.

---

## What is not done on AIML-2698

- Guided mode has never been exercised live (its fixes are REST-verified only).
  This blocks AC#5 and is the last significant unknown.
- `turn_guard` state is never reset between WebSocket connections — found by
  code reading, never reproduced.
- AC#4 runbook note not yet written.
