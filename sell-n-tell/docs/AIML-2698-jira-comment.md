# Draft comment for AIML-2698

*(paste into the Jira ticket; trim as needed)*

---

Reproduced two of the listed gaps against `feature/AIML-2130-guided-flow`
(`3ecd956`) using REST calls only — no mic, no Gemini, no Vertex, BigQuery
disabled. Both are deterministic and take seconds to run, so they can go
straight into the smoke harness. Full log with copy-pasteable scripts:
`docs/AIML-2698-experiments.md`.

**1. Commit succeeds without full planned-topic coverage (AC#3)**

Staged a record covering 1 of 2 planned topics. Staging correctly returned
`missing_topics: ["Pricing"]`, `all_topics_covered: false`. Commit then
succeeded anyway and returned `CRM-B598122C53`. The committed record stores
`missing_topics: ["Pricing"]` as a field — the system records that the data is
incomplete and saves it regardless.

`compute_missing_topics` is computed at both stage and commit but never gates
anything. The only thing discouraging a premature save today is prompt text
("Do NOT save yet"), which is model-dependent.

**2. Campaign disposition codes and event types are not enforced (AC#2)**

`renewals` allows event types `[Phone Call, Meeting]` and codes `[2,3,5,8,9]`.
Staged a `renewals` payload with `event_type: "On-site visit"` and
`disposition_code: 1` — both illegal, both accepted, `all_topics_covered: true`.
The generated readback then states *"I've staged an On-site visit ... marked as
create opportunity"*, i.e. an invalid code is spoken back to the rep as valid.

Root cause: **`POST /api/v1/notes/stage` takes no `campaign_type`**, so it cannot
look up campaign rules. Both checks fall back to global lists — `event_type`
against `mock_db.VALID_EVENT_TYPES` (all 3) and disposition codes against
`VALID_DISPOSITION_CODES` (all 10, resolved at import time in `tools.py`). The
campaign config is injected into the model's prompt but never used to validate
its output. Fixing this requires threading `campaign_type` through to the
staging endpoint first.

**3. `turn_guard` state is never reset between connections** (code reading, no
repro yet)

The four module-level dicts keyed by `session_id` are never cleared; WS teardown
closes only the `LiveRequestQueue`. Since sessions are reused by `session_id`, a
reconnect inherits stale state and a commit can be blocked by a readback owed on
a previous connection. Likely to show up during repeated demo runs.

**Ticket rows 1–3 appear already fixed on this branch** and should be
re-verified rather than re-implemented:
- splintered `topics` → handled by `tools.py :: _normalize_topics`
- commit with no staged session → rejected in `commit_visit_notes`
- "tools blocked on no new reply" → was a bug *in the guard*; the ADK-session-state
  version always read a stale baseline and blocked every commit. Already rewritten.

**Proposed fix location:** all of #1 and #2 belong in the REST layer
(`main.py` + `mock_db.py`) rather than in the ADK tools. Because the tools call
the API over HTTP, implicit / guided / hybrid all inherit the fix from one place.

**Question for the lead:** `feature/AIML-2686` ("Added hybrid (partial guidance)
flow") branches from the same commit as this work and adds a third mode. Should
these fixes be based on `AIML-2686` instead of `AIML-2130-guided-flow`? And does
hybrid become a third selectable mode in AIML-2697's demo UX?
