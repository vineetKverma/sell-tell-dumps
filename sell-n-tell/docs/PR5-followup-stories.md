# PR #5 — follow-up stories

Design and duplication findings from Suresh's review of
[PR #5](https://bitbucket.org/fm_ebiz/sell-n-tell/pull-requests/5), 2026-08-19.
None blocked the merge.

**Parent epic:** AIML-1537 (EPP-84 Post Call Automation)

| # | Story | Points |
|---|---|---|
| 1 | Single source of truth for campaign rules and error shaping | 8 |
| 2 | Disposition registry and topic-state model | 5 |
| 3 | Enforce the storage backend contract | 2 |
| 4 | Session-state eviction | 3 |

Total 18, sized against AIML-2698 (3). Order: **3 → 1 → 2 → 4**.

---

# Story 1 — Single source of truth for campaign rules and error shaping

**Points: 8**

## Description

The same rule is written in several places, and they can drift apart.

**Campaign rules — 3 copies.** `tools.py::_allowed_codes` (~L44) and
`tools_guided.py::_campaign_rules` (~L45) read a cached config from session
state. `mock_db.validate_against_campaign` (~L474) does a fresh lookup. Change a
rule in one and implicit mode, guided mode and the REST 422 start disagreeing,
with nothing to flag it.

**Error shaping — 2 copies each.** Both tool modules parse the 409 body and
build their own refusal dict (`tools.py` ~L462, `tools_guided.py` ~L520-527),
and both shape their own 422 message (`tools.py` ~L264, `tools_guided.py` ~L482).
A field rename in `main.py` needs both updated, and nothing fails if one is
missed.

**State keys — 2 copies, and this one is the risk.** `agent_config` and
`campaign_type` are hardcoded strings in two files, duplicating constants
`agent.py` already defines. If a key is renamed and one copy is missed,
`state.get(...)` returns `None`, validation falls back to the **unrestricted
global registry**, and nothing is logged. A campaign-rule bypass that looks
normal.

**Client — the 4th place.** `app.js` ~L1077 funnels three tool names into one
conditional, then status checks, then a refusal path, then unconditional
success rendering. A new tool name or refusal status falls through to "success".

The server already fixed its half in PR #5 — both commit endpoints now share one
error-shaping helper, because the drift between them was a real bug (an
incomplete record got a generic 500 instead of the 409 + `missing_topics`
contract). This does the same for the tool and client layers.

Consolidation only — no rule, code or contract should change.

## Acceptance criteria

1. Adding a disposition code to a campaign means editing one place; implicit,
   guided and the REST 422 all reflect it.
2. A renamed state key cannot silently fall back to the global registry — it
   either can't be missed, or it logs a warning.
3. One code path per status produces the 409 and 422 refusal messages.
4. `app.js` does not render success for an unknown tool name or refusal status.
5. Both smoke suites and the 9-case REST suite behave identically to before.

---

# Story 2 — Disposition registry and topic-state model

**Points: 5**

## Description

Three related problems in `mock_db`.

**`needs_manual_review` is set in three places** — `tools.py`,
`tools_guided.py` (~L323) and `mock_db` (~L708). Each has its own checks, then
`mock_db` sets it again anyway for code 99. Its comment admits it doesn't fully
trust the others, which is why. Make `mock_db` the only writer.

**Code 99 is valid but invisible.** `_NOT_COVERED_RULE` (~L238) is kept out of
`_FULL_DISPOSITION_REGISTRY` and each campaign's registry, then added back only
in two read sites (~L428). It stays valid via `VALID_DISPOSITION_CODES`, so
nothing rejects it — it just has no label or keywords for anything iterating the
registry. Absent would fail loudly; this doesn't.

**`allow_skips` should be a state, not a boolean.** Derived per call site
(~L741), then threaded through `compute_missing_topics`,
`build_confirmation_text` and `commit_notes`. It already needed a carve-out for
guided mode (`previous is not None or agent_mode == "guided"`) with a five-line
comment to justify it. A third caller means a third clause plus re-checking four
functions. Replace with a topic-status enum: unaddressed / skipped-unconfirmed /
skipped-confirmed / discussed.

`allow_skips` is load-bearing — the AIML-2698 coverage gate reads it, so it
decides whether a record can commit at all. The carve-out exists because getting
it wrong once deadlocked the guided flow (seen live 2026-08-11).

This story changes behaviour, unlike the other three. Needs both smoke suites
and the REST coverage cases re-run.

## Acceptance criteria

1. `needs_manual_review` is set in one module only; tool layers just null the
   code.
2. Iterating any disposition registry includes code 99 with its label and
   keywords.
3. `allow_skips` is gone; all four consumers read a topic status.
4. A new calling pattern can be added without editing a shared boolean.
5. Guided mode doesn't deadlock on a rep-confirmed skip.
6. Both smoke suites and the REST coverage cases pass.

---

# Story 3 — Enforce the storage backend contract

**Points: 2**

## Description

`db_interface.CRMStore` is meant to keep `mock_db` and `bigquery_db` in sync. It
wasn't — it declared the old signatures for both `stage_notes` and
`commit_notes`.

That's why the BigQuery mismatch reached review: the Protocol documented the
wrong contract, so type-checking had nothing to complain about. The finding
turned out to be a commit path missing three gates (AIML-2698 coverage,
AIML-2703 supersede, and idempotency), with every commit under
`BIGQUERY_ENABLED=true` raising `TypeError`.

The signatures were fixed in PR #5. What's left is structural: `CRMStore`
declares `self` on its methods, but the things that must satisfy it are
**modules**, not instances — so it never enforced anything even when the
signatures were right. Fix by dropping `self` or adding a thin adapter class,
then wire it into CI.

Small, but it's the guard that stops this recurring.

## Acceptance criteria

1. Removing a kwarg from `bigquery_db.commit_notes` fails type-checking.
2. That check runs in CI, not just locally.

---

# Story 4 — Session-state eviction

**Points: 3**

## Description

Six module-level dicts grow by one entry per session and are never cleaned up:
`turn_guard._TURN_COUNTS`, `_BASELINES`, `_AWAITING_READBACK`, `_NUDGE_SENT`,
`mock_db._STAGED_NOTES` and `tools_guided._COMMIT_LOCKS`.

Flagged as non-blocking, with the prediction it would matter more once
session-id-per-dictation landed. It landed. Two PR #5 changes make it worse:
`session_id` now rotates after every commit (many more sessions per shift), and
committed records are now **kept** in `_STAGED_NOTES` rather than deleted —
the delete was what made the idempotent-retry branch unreachable, so a real
retry got a 404 instead of the cached result.

**Don't reinstate the delete at commit time** — that brings the 404 back. Reap
committed entries on WebSocket disconnect or a TTL, with a window long enough
that a genuine retry still finds its record.

## Acceptance criteria

1. After N connect/disconnect cycles, none of the six dicts has grown with N.
2. A commit retry inside the retention window still replays the original
   `crm_record_id`.
3. The AIML-2703 supersede gate still fires for a draft not yet evicted.

---

# Delivered in PR #5

The review also asked for a comment naming the guided flow's real commit
trigger — Stage 5 of the prompt says to call `commit_guided_notes`, but
`record_topic_disposition` commits inline, so a future prompt change there would
be silently ignored. That's a comment, not a refactor, so it shipped in PR #5.
