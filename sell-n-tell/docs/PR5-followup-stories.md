# PR #5 — Section B follow-up stories

11 design/duplication comments from Suresh's review of PR #5. None block the
merge; all are debt the review made visible.

**Recommendation: four stories, plus one item done in PR #5 itself.**

The grouping is by *cause*, not by file — three of these are the same defect
(one rule expressed in several places) showing up in different layers, and
splitting them per-file would mean three half-fixes that still leave the
sources of truth divergent.

| Story | Covers | Size |
|---|---|---|
| 1. Single source of truth for campaign rules and error shaping | B2, B3, B4, B5, B10 | L |
| 2. Disposition registry and topic-state model | B6, B7, B8 | M |
| 3. Storage backend contract | B1 | S |
| 4. Session-state eviction | B11 | S |
| *(done in PR #5)* | B9 | XS |

---

## Story 1 — Single source of truth for campaign rules and error shaping

**Covers B2, B3, B4, B5, B10.**

### Context

"What is legal for this campaign" is currently implemented three independent
times — `tools.py::_allowed_codes`, `tools_guided.py::_campaign_rules`, and the
server's own `mock_db.validate_against_campaign` — and they do not read the same
data. The tool layers read a cached copy of the config out of ADK session state;
the server does a fresh lookup. A rule change applied to one and not the others
produces different rejection behaviour between implicit mode, guided mode, and
the REST 422, with nothing to flag the divergence.

The same shape repeats in how *rejections* are turned back into instructions for
the model. Both tool modules independently parse the 409 coverage-gate body and
build near-identical refusal dicts (B3), and both independently shape an
`instruction_for_model` from the 422 body's
`problems`/`allowed_event_types`/`allowed_disposition_codes` (B4). A field
rename in `main.py` requires updating both in lockstep, with no failing test if
one is missed.

B5 is the quiet one and arguably the most dangerous. The state keys the tool
layers read (`agent_config`, `campaign_type`) are hardcoded string literals in
two files, duplicating constants `agent.py` already defines. There is a genuine
circular-import reason not to import from `agent.py` — but `db_interface.py`
already demonstrates the pattern for a small shared leaf module. If a key is
renamed and one copy is missed, `tool_context.state.get(...)` returns `None`,
validation silently falls back to the *unrestricted global registry*, and
nothing is logged. That is a campaign-rule bypass that looks like normal
operation.

B10 is the client-side member of the same family: `app.js`'s commit-response
handling funnels three tool names into one conditional, then early-return status
checks, then a `!resp.crm_record_id` refusal path, then unconditional success
rendering. A fourth tool name or a new refusal status added later falls through
to "success" silently. Suresh's suggestion — `isMidFlowContinue(resp)` /
`isRefusal(resp)` helpers — makes it read as guard clauses. It belongs here
because it is the same question ("how is a refusal recognised?") answered in a
fourth place.

### Why it's worth doing

The server already went this way during PR #5: both commit endpoints now share
one `_commit_failure_response` helper, because the drift between them *was* the
A4 defect. This story applies the same treatment to the tool and client layers
before they drift the same way.

### Scope

- One shared source for campaign allow-lists, consumed by implicit, guided and
  the server validator
- One shared 409 and 422 response-shaping path for the tool layers
- Shared state-key constants in a leaf module, no circular import
- `isMidFlowContinue` / `isRefusal` guard clauses in `app.js`

### Out of scope

Changing any campaign rule, disposition code or error contract. This is
consolidation only — behaviour before and after should be identical, which is
also how it should be tested.

---

## Story 2 — Disposition registry and topic-state model

**Covers B6, B7, B8.**

### Context

Three related problems in `mock_db`'s domain model.

**B6 — `needs_manual_review` is set in three places.** `tools.py`,
`tools_guided.py` and `mock_db` each set the flag through their own checks, then
`mock_db` sets it again unconditionally for code 99. The pattern is
monotonic-OR, so the tool-layer computations are redundant work — and the
surrounding comment in `mock_db` openly admits it does not fully trust them,
which is why it re-sets the flag anyway. A check that does not trust an upstream
check belongs upstream, not duplicated. Make `mock_db` the single source of
truth and let the tool layers just null the code.

**B7 — code 99 is spliced in but excluded from the registries it's spliced
into.** `_NOT_COVERED_RULE` is deliberately kept out of
`_FULL_DISPOSITION_REGISTRY` and each campaign's `disposition_registry`, then
added back only in `get_agent_config` and `_DISPOSITION_BY_CODE`. The trap is
the combination: code 99 remains globally *valid* via
`VALID_DISPOSITION_CODES`, so nothing rejects it — it simply has no label or
keywords anywhere that iterates the registry for metadata. Valid-but-invisible
is worse than absent, because absent would fail loudly.

**B8 — `allow_skips` is an ad hoc boolean, not a state model.** It is derived
per call site, then threaded through `compute_missing_topics`,
`build_confirmation_text` and `commit_notes`. It already needed one bespoke
exemption for guided mode to avoid a deadlock — visible today as
`previous is not None or agent_mode == "guided"`, which needed a five-line
comment to justify. A third calling pattern means a third clause in that
expression plus re-checking four functions for consistency. Suresh's suggestion
is a topic-status enum — *unaddressed / skipped-unconfirmed / skipped-confirmed
/ discussed* — which makes new caller semantics a matter of state rather than a
shared boolean's truth table.

### Why it's worth doing

B8 in particular is load-bearing: the coverage gate (AIML-2698) and the
confirmation text both read `allow_skips`, so its truth table is what decides
whether a record can be committed. That is too much weight for a boolean that is
re-derived at each call site.

### Scope

- `mock_db` as the single writer of `needs_manual_review`
- Code 99 present in the registries it is currently spliced around, or a single
  accessor that guarantees it
- Topic-status enum replacing `allow_skips` across all four consumers

### Note

Behaviour-affecting. Needs the REST coverage-gate cases and both smoke suites
re-run, not just a review.

---

## Story 3 — Storage backend contract

**Covers B1.**

### Context

`db_interface.CRMStore` exists to keep `mock_db` and `bigquery_db` in sync. It
did not: it declared `stage_notes` without `campaign_type`/`agent_mode` and
`commit_notes` without the kwargs `main.py` passes. **That is why the BigQuery
signature mismatch (A1) reached review** — the Protocol meant to catch it
documented the wrong contract, so type-checking had nothing to complain about.

The signatures were corrected in PR #5 as part of the A1 fix, because shipping
that fix without them would have left the same hole open. What remains is the
structural half: the Protocol declares `self` on its methods, but the things
that have to satisfy it are *modules*, not instances. A module never structurally
matches such a Protocol, so it was never enforcing anything even when the
signatures were right.

### Why it's worth doing

Small, but it is the guard that stops A1 from happening again. Two backends and
no enforced contract between them is exactly the setup that produced a commit
path with three missing gates.

### Scope

- Make `CRMStore` actually satisfiable by the module objects `get_db()` returns
  (drop `self`, or switch to a small adapter class)
- Wire it into whatever type-checking runs in CI, so a mismatch fails a build
  rather than a review

### Note

Worth doing first, or at least before Story 1, since Story 1 moves shared code
between these same layers.

---

## Story 4 — Session-state eviction

**Covers B11.**

### Context

Several module-level dicts accumulate one entry per session and are never
cleaned up: `turn_guard`'s `_TURN_COUNTS`, `_BASELINES`, `_AWAITING_READBACK`
and `_NUDGE_SENT`, plus `mock_db._STAGED_NOTES`, and now
`tools_guided._COMMIT_LOCKS`. A long-running process grows indefinitely.

Suresh flagged this as non-blocking, and predicted it would matter more once
session-id-per-dictation landed. It did land (A3), so it does. Two changes in
PR #5 push more state through these dicts:

- **A3** rotates `session_id` after every commit, so a shift now produces many
  more distinct sessions than it used to.
- **A5** *keeps* committed records in `_STAGED_NOTES` rather than deleting them.
  The delete was what made the idempotent-retry branch unreachable, so it had to
  go — but it means the store now retains one entry per committed visit.

So the cleanup hook must reap **committed** entries specifically, not only
abandoned ones. Reinstating the old delete is not an option; it would restore
the A5 defect.

### Scope

- A cleanup hook on WebSocket disconnect covering all six dicts
- Committed `_STAGED_NOTES` entries reaped on a TTL or at disconnect, not at
  commit
- A retention window long enough that a genuine client retry still finds its
  record

---

## Done in PR #5 — B9

**Guided-flow state machine split across three files.**

`agent.py`'s prompt tells the model to call `commit_guided_notes`;
`record_topic_disposition` now commits inline instead, working around a
documented model-behaviour gap (the model ends its turn rather than making the
second call). A future prompt change around the commit step would be silently
short-circuited, since the tool has already run before the model gets a turn.

Suresh asked for a cross-reference comment naming the real commit trigger.
That is a comment, not a refactor, and the person it protects is whoever next
edits that prompt — so it belongs in the PR that created the situation rather
than a follow-up.

---

## Suggested sequencing

1. **Story 3** (contract) — small, and it is the guard for everything else
2. **Story 1** (deduplication) — largest, benefits from 3 being in place
3. **Story 2** (domain model) — behaviour-affecting, wants a quiet window
4. **Story 4** (eviction) — independent, can run in parallel with any of them
