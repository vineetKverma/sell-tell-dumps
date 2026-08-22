# PR #5 — follow-up stories

Findings from Suresh's review of
[PR #5](https://bitbucket.org/fm_ebiz/sell-n-tell/pull-requests/5), 2026-08-19.
None blocked the merge.

**Parent epic:** AIML-1537 (EPP-84 Post Call Automation)

| # | Story | Points |
|---|---|---|
| 1 | Single source of truth for campaign rules and error shaping | 8 |
| 2 | Disposition registry and topic-state model | 5 |
| 3 | Enforce the storage backend contract | 2 |
| 4 | Session-state durability and eviction | 8 |
| 5 | Defined reconnect behaviour for the WebSocket endpoint | 5 |
| 6 | Durable CRM storage and BigQuery flag naming | 5 |

Total 33, sized against AIML-2698 (3).

Stories 4-6 come from a later round of review comments and are platform
concerns rather than code tidy-ups. **Story 6 should be decided before Story 3**
— if `bigquery_db` is dropped, the contract Story 3 enforces may not need to
exist.

Order: **6 → 3 → 1 → 2**, with 4 and 5 runnable in parallel.

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

# Story 4 — Session-state durability and eviction

**Points: 8**

## Description

**Nothing survives a restart.** Session state lives entirely in one process's
memory via `InMemorySessionService` (the `KNOWN LIMITATION` comment in
`main.py`), so a restart or redeploy drops every session. The recommendation is
to migrate to `VertexAISessionService` so state survives restarts and scales
past a single process.

**One constraint to carry into the work:** `turn_guard`'s counters were
deliberately moved *out* of ADK session state, because `ToolContext.state` does
not observe mutations made to the `Session` object from `main.py`'s downstream
loop — every commit read a stale baseline and was permanently blocked. So
`VertexAISessionService` fixes ADK session state but **not** `turn_guard`'s
dicts, `mock_db._STAGED_NOTES`, or `tools_guided._COMMIT_LOCKS`, none of which
are ADK state. Migration and eviction are complementary, not alternatives.

**Nothing is evicted either.** Six module-level dicts grow by one entry per
session and are never cleaned up:
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

1. Session state survives a server restart.
2. After N connect/disconnect cycles, none of the six dicts has grown with N.
3. A commit retry inside the retention window still replays the original
   `crm_record_id`.
4. The AIML-2703 supersede gate still fires for a draft not yet evicted.
5. `turn_guard` still reads a live counter, not a stale baseline — the failure
   that moved it out of ADK state in the first place.

---

# Story 5 — Defined reconnect behaviour for the WebSocket endpoint

**Points: 5**

## Description

The REST layer already has a solid contract for intermittent connectivity: a
caller can retry `stage` or `commit` after a dropped connection and either lands
on the idempotent `committed=True` branch or gets a structured
`IncompleteCoverageError` / `SupersededRecordError` to act on.

`/ws/{user_id}/{session_id}` is where the gap is. `websocket_endpoint` does
`get_session(...)` falling back to `create_session(...)`, so the data model
supports resuming by reusing a `session_id` — but nothing tracks which ids
currently have a **live** connection. Each connection builds its own
`LiveRequestQueue()` and calls `runner.run_live(...)` independently. If a second
connection attaches with the same `session_id` before the first one's teardown
has finished, both drive the same underlying Live API session concurrently —
which is exactly the `APIError 1000` the reconnect-backoff comment names.

There is no in-flight registry, no rejection of a second attach, and no
wait-for-prior-teardown. The only thing preventing it today is that the
reference client always mints a brand-new `session_id` on reconnect — a
client-side dodge, not a service guarantee. Any other client that reconnects
with the same id after a blip hits the race.

**PR #5 increased the reliance on that dodge**: fixing the stale commit result
means the client now rotates `session_id` after every commit, so it mints new
ids more often than before, making the race even less likely to surface locally.

This compounds with Story 4: a backend restart is itself a connectivity
interruption from any client's perspective, and today it loses everything
regardless of how good the WS-level reconnect protocol is. With both fixed, the
live channel's job during an interruption becomes getting the client back to a
point where it can rely on the REST layer's already-solid retry contract.

## Acceptance criteria

1. The service tracks live connections per `session_id`.
2. A second attach for an id that is still active either waits for the prior
   connection's teardown, or is rejected with an explicit documented signal
   (e.g. "session busy, retry after Xms") — not an opaque upstream
   `APIError 1000`.
3. The behaviour is published as part of the API contract, so a consumer knows
   whether reconnecting with the same `session_id` is supported.
4. A client that reconnects with the same `session_id` after a dropped
   connection reaches a working state without minting a new id.

---

# Story 6 — Durable CRM storage and BigQuery flag naming

**Points: 5**

## Description

**There is currently no configuration under which a committed CRM record
durably persists.** With `BIGQUERY_ENABLED=false` — the default, and not
documented in `.env.example` at all — `db_interface.get_db()` selects `mock_db`,
whose `_STAGED_NOTES` / `_COMMITTED_NOTES` are plain in-process Python
structures. A restart drops every "committed" record.

**Two similarly-named flags do different things.** `VOICE_NOTES_BQ_ENABLED`
(default `true`) drives `bigquery_sink.insert_call_record`, which runs
unconditionally in the commit handler regardless of which `CRMStore` is active.
That is what actually populates BigQuery rows today — an analytics side-log of
the payload, not the CRM record itself. So BigQuery rows appear even with
`BIGQUERY_ENABLED=false`, which reads as though the CRM backend is BigQuery when
it is still `mock_db` in memory.

Two ways to resolve it:

- **(a)** Make BigQuery the actual backing `CRMStore` when
  `BIGQUERY_ENABLED=true` — its own staging, commit and read, no shadow copy —
  and keep `bigquery_sink` purely as the separate analytics log it already is.
- **(b)** Drop `bigquery_db.py`'s pretense of being an independent `CRMStore`,
  rely on `bigquery_sink` for BigQuery visibility, and document `mock_db` as the
  only "CRM" until a real backend exists.

PR #5 made (b) cheap: `bigquery_db.commit_notes` now delegates the entire commit
— coverage gate, supersede check, idempotency — to `mock_db` and owns only the
insert. It was doing none of that before, which is what made it look like an
independent backend while silently bypassing every gate. It is now unambiguously
an insert wrapper.

**Decide this before Story 3.** If `bigquery_db` goes away, the contract that
story enforces may not need to exist.

## Acceptance criteria

1. A decision is recorded on (a) vs (b), with the reasoning.
2. The two flags no longer read as the same switch — renamed, merged, or clearly
   documented as CRM backend vs analytics log.
3. `.env.example` documents whichever flags remain.
4. It is unambiguous from configuration alone whether a committed record
   survives a restart.

---

# Delivered in PR #5

The review also asked for a comment naming the guided flow's real commit
trigger — Stage 5 of the prompt says to call `commit_guided_notes`, but
`record_topic_disposition` commits inline, so a future prompt change there would
be silently ignored. That's a comment, not a refactor, so it shipped in PR #5.
