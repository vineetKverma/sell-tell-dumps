# PR #5 review — Suresh's findings

`[AIML-2698] Disposition + state correctness, merged with development`
`feature/AIML-2698-on-2130` → `development` · **Changes requested**, 2026-08-19

25 comments. Grouped by whether they block the merge. Line references are his.

---

## A. Correctness — fix before merge

### A1. BigQuery backend commit is broken *and* bypasses the coverage gate
`main.py` — commit endpoint

`db.commit_notes(session_id, confirmed, agent_mode=…, campaign_type=…, ws_user_id=…, ws_session_id=…)`
is now called unconditionally, but `bigquery_db.commit_notes(session_id, confirmed)`
has no matching params — **every commit under `BIGQUERY_ENABLED=true` raises
`TypeError`**.

Worse, even with the signature fixed: `bigquery_db.commit_notes` never calls
`compute_missing_topics` and never raises `IncompleteCoverageError`. It builds
and inserts a row unconditionally on the `confirmed=True` branch. Since the
downstream Salesforce sync is driven by this API's response payload rather than
by BigQuery, **that defeats the entire coverage gate this PR adds, for that
backend.**

> This is the most serious finding. The headline feature of the ticket is
> silently absent on one of two backends.

### A2. Race on `_S_COMMIT_RESULT` → two CRM records for one visit
`tools_guided.py` ~L405

ADK's Live flow can dispatch multiple function calls from one turn concurrently
(`asyncio.gather`). Two invocations can both read `prior` as unset before either
finishes `await httpx.post(...)` and writes the result at ~L572 — each mints a
new `session_id` via `/notes/stage` and commits independently.

Needs an **atomic claim** on `_S_COMMIT_RESULT`, not get-then-set.

> Same failure mode as the orphan bug fixed in AIML-2703, by a different route.
> Our supersede gate does not catch it: these are two independent stage calls,
> neither superseding the other.

### A3. Stale commit result reused across back-to-back dictations
`tools_guided.py` ~L572

`_S_COMMIT_RESULT` is never cleared when a rep starts a new dictation in the
same app session. The client keeps the WebSocket open between dictations to
avoid Vertex's cold-start handshake, and `finishSession()` / `resetForNewDictation()`
never call `closeWebsocketIntentionally()` + `newSessionId()` the way the
campaign-change, agent-mode-change and reconnect paths do (`app.js` ~L623-625,
~L681-682, ~L773).

**Net effect: the rep's second visit of a shift hits the idempotency check, gets
back the previous visit's commit result, and the agent says "saved" while
nothing was staged.**

His recommended fix: close the socket and rotate `sessionId` in `finishSession()`
right after a confirmed commit — a fresh `session_id` makes this state empty by
construction, with no server-side reset needed.

### A4. `/api/v1/notes/confirm` downgrades 409 to a generic 500
`main.py` — `confirm_notes_endpoint2`

Wraps its `db.commit_notes(...)` in `except KeyError`, then a catch-all
`except Exception as e: return 500`. `IncompleteCoverageError` subclasses
`Exception`, so an incomplete record hitting this endpoint returns
`{"error": "Internal server error"}` instead of the structured **409 +
`missing_topics`** contract every other commit path now returns.

### A5. Idempotency safety claim doesn't hold
`mock_db.py` ~L822

The comment says `committed=True` implies the coverage gate already passed —
true — but the cached-success branch **can never be reached for a real retry**:
`del _STAGED_NOTES[session_id]` (~L846) removes the record in the same call that
sets `committed=True`. A genuine retry with the same `session_id` finds no
record and gets `KeyError`/404 instead of the cached response.

Either the delete or the cache branch is wrong. The comment describes behaviour
that cannot occur.

### A6. Resampler never flushes its tail buffer
`audio-recorder.js` ~L120

`emit()` batches ~20 ms of samples in `out` before sending, but nothing flushes
the partial buffer when the mic stops — **the last syllable of every dictation
is silently dropped.** Needs a `flush()` called from `stopMicrophone`.

> Ours, introduced with the resampler. Real user-visible data loss.

### A7. `crypto.randomUUID()` requires a secure context
`app.js` L23, L25

On a plain-HTTP internal/LAN deployment — plausible for an internal sales tool
without a local TLS cert — `crypto.randomUUID` does not exist and **throws at
module load, breaking the entire frontend before anything else runs.**

Needs a fallback, or written confirmation this is only ever served over HTTPS.

> Ours. We chose this to fix ID collisions; it trades one failure for a worse one
> if the deployment isn't HTTPS.

### A8. Two sources of truth for `campaign_type` at commit
`main.py` ~L340

Reads `body.campaign_type` (client-supplied at commit time) to build the BigQuery
sink config, instead of `record["campaign_type"]` (`mock_db.py` ~L734 — the value
the record was actually staged and validated under). If a client sends a
different value at commit vs. stage, the CRM write silently uses the wrong
campaign's disposition registry.

Fix: always read `record["campaign_type"]`.

### A9. Whitespace-only text bypasses `turn_guard` but still reaches the model
`main.py` ~L768

`turn_guard.record_user_turn(session_id)` is gated on `text.strip()`, but
`live_request_queue.send_content(content)` runs unconditionally. A
non-empty-but-blank message is processed by the model as a real turn, yet every
`turn_guard`-gated tool afterwards reports `no_reply_heard` for a turn that
genuinely happened.

### A10. Unguarded read-modify-write on guided topic state
`tools_guided.py` ~L317

`results = …; results.append(…); state[…] = results`, and the equivalent
`pending` pattern below. Same concurrency exposure as A2 — if two topics are
dispositioned in one concurrent batch, one call's read can be stale relative to
the other's write, silently dropping a topic result or resurrecting an
already-removed pending topic.

---

## B. Design and duplication — follow-up ticket

### B1. `CRMStore` Protocol is stale
`db_interface.py`

Still declares `stage_notes(...)` without `campaign_type`/`agent_mode`, and
`commit_notes(self, session_id, confirmed)` without the kwargs `main.py` now
passes. **This is why A1's signature mismatch wasn't caught by type-checking** —
the Protocol meant to keep `mock_db`/`bigquery_db` in sync documents the wrong
contract.

### B2. Campaign-rule allow-lists computed three independent ways
`tools.py` ~L44 · `tools_guided.py` ~L45 · `mock_db.validate_against_campaign` ~L452

Three implementations of "what's legal for this campaign", reading different data
(cached session-state config vs. fresh server lookup). A rule change applied to
one and not the others produces inconsistent rejection behaviour between
implicit, guided and the server's 422.

### B3. Duplicated 409 coverage-gate handling
`tools.py` ~L462 · `tools_guided.py` ~L520-527 — both parse the 409 body and build
near-identical refusal dicts independently.

### B4. Duplicated 422 rejection-message shaping
`tools.py` ~L264 · `tools_guided.py::commit_guided_notes` ~L482 — both shape an
`instruction_for_model` from `main.py`'s 422 body. A field rename in `main.py`
requires updating both in lockstep.

### B5. Hardcoded state-key literals instead of shared constants
`tools.py` ~L37-40 · `tools_guided.py` ~L41-42

`agent.py` already defines `STATE_AGENT_CONFIG` / `STATE_CAMPAIGN_TYPE`. There's
a real circular-import reason not to import from `agent.py`, but `db_interface.py`
already shows the pattern for a small shared leaf module. **If a key is renamed
and one copy is missed, `tool_context.state.get(...)` silently returns `None` and
validation falls back to the unrestricted global registry, with nothing logged.**

### B6. `needs_manual_review` set redundantly in three places
`mock_db.py` ~L708 · `tools.py::_normalize_topics` · `tools_guided.py::record_topic_disposition` ~L323

Each sets the flag via its own checks, then `mock_db` sets it again
unconditionally for code 99. The pattern is monotonic-OR, so the tool-layer
computations are redundant work that the surrounding comment admits it doesn't
fully trust. Make `mock_db` the single source of truth and let the tool layers
just null the code.

### B7. Code 99 spliced in but excluded from the registries it's spliced into
`mock_db.py` ~L428

`_NOT_COVERED_RULE` (~L238) is deliberately kept out of
`_FULL_DISPOSITION_REGISTRY` and each campaign's `disposition_registry`, and only
added back in `get_agent_config` and `_DISPOSITION_BY_CODE`. Future code reading
`_CAMPAIGN_CONFIGS[...]["disposition_registry"]` directly, or iterating
`_FULL_DISPOSITION_REGISTRY` for metadata, silently misses 99's label and
keywords — while it stays globally "valid" via `VALID_DISPOSITION_CODES`.

### B8. `allow_skips` is an ad hoc boolean, not a state model
`mock_db.py` ~L728

Derived per call site, then threaded through `compute_missing_topics`,
`build_confirmation_text` and `commit_notes`. It already needed one bespoke
exemption for guided to avoid deadlocking; a third calling pattern needs another
carve-out in the same expression, checked across four functions to stay
consistent.

Suggested: a topic-status enum — *unaddressed / skipped-unconfirmed /
skipped-confirmed / discussed* — making new caller semantics a matter of state
rather than a shared boolean's truth table.

### B9. Guided commit trigger is split across three files
`tools_guided.py` ~L408

`agent.py`'s prompt tells the model to call `commit_guided_notes`;
`record_topic_disposition` now commits inline instead, working around a
documented model-behaviour gap. A future prompt change around the commit step
(e.g. asking for spoken confirmation first) would be **silently short-circuited**,
since the tool already ran before the model gets a turn. Wants a cross-reference
comment naming the real commit trigger.

### B10. Commit-response conditional is hard to extend
`app.js` ~L1010-1023

Three tool names funnel into one `if`, then early-return status checks, then the
`!resp.crm_record_id` refusal path, then unconditional rendering. **A fourth tool
name or a new refusal status added later would silently fall through to "success"
rendering.** Suggested: `isMidFlowContinue(resp)` / `isRefusal(resp)` helpers so
it reads as guard clauses.

> Note this is the exact bug class Batch 3 fixed once already.

### B11. Session state is never evicted — slow memory leak
`turn_guard.py` — `_TURN_COUNTS`, `_BASELINES`, `_AWAITING_READBACK`, `_NUDGE_SENT`;
`mock_db._STAGED_NOTES` has the same shape.

No session's entries are ever cleaned up, so a long-running process accumulates
them indefinitely. More relevant once the session-id-per-dictation change (A3) is
in, since that creates many more distinct sessions per shift. Wants a cleanup
hook on WS disconnect. Not blocking.

---

## C. Cosmetic

- **C1.** `mock_db.py` — stray extra blank line vs. the file's two-blank-line
  convention between top-level defs.
- **C2.** `tools_guided.py` — indentation not run through the project formatter
  (args past continuation width, dangling close paren). Will trip a lint gate.
- **C3.** `main.py` ~L275 — redundant `get_agent_config()` on the rejection path;
  `validate_against_campaign` already builds it internally. Consider returning
  `(problems, config)`.
- **C4.** `audio-recorder.js` — resampler closure state (`cursor`, `prevSample`,
  `out`, `outLen`) would be more testable as a small class. Not a defect.

---

## D. Positive

`app.js` ~L1206 — removing the `audioRingBuffer.push/shift` pattern:

> *"that was an O(n) array shift on up to 1250 elements running every ~8ms, and
> the backpressure-drop approach here is a clean, genuine improvement."*

---

## Suggested response

**Fix in this PR (A1–A10)** — all are correctness. A1, A2, A3 and A6 are
user-visible data loss or wrong data; the rest are contract violations that make
the guarantees this ticket claims untrue in some path.

**Raise a follow-up ticket for B** — B1 first, since a correct Protocol is what
would have caught A1 automatically. B2–B5 are one theme: campaign rules and
error shaping duplicated across implicit/guided/server, which is the same
"three sources of truth" risk in four places.

**C is a formatter pass.**

Two of his findings (A6, A7) are defects we introduced in this PR, and both are
real. A6 drops the last word of every dictation; A7 breaks the whole frontend on
plain HTTP. Neither would have surfaced in our testing because we only ever ran
over `localhost`, which counts as a secure context.
