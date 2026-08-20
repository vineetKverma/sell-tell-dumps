# PR #5 — response to review

`[AIML-2698] Disposition + state correctness, merged with development`
`feature/AIML-2698-on-2130` → `development`

Reviewed by Suresh, 2026-08-19, changes requested — 25 comments.
This document answers, per finding: **what caused it**, **what changed**, and
**how it was verified**. Full review text and per-item detail live in
`PR5-review-findings.md`.

---

## Status

| Group | Count | Status |
|---|---|---|
| **A — correctness** | 10 | **All fixed.** The only group blocking merge. |
| **B — design / duplication** | 11 | Follow-up ticket. B1's signatures fixed as part of A1. |
| **C — cosmetic** | 4 | Formatter pass, not yet run. |
| **D — positive** | 1 | No action. |

Verified by three scripts, **49 assertions**, none requiring a mic, model,
BigQuery or a running server.

---

## Root causes, in four themes

Most of the ten correctness findings trace back to four things, and it is more
honest to say so than to present ten unrelated slips.

**1. A second storage backend nobody updated.** The merge from `development`
introduced `db_interface`/`bigquery_db` alongside `mock_db`. This PR then grew
`commit_notes`' signature and added the coverage gate — to `mock_db` only. The
`CRMStore` Protocol that exists to keep the two in sync was already stale, so
type-checking could not catch the mismatch. It was noticed during the merge and
deferred; that deferral is what let **A1** ship. → **A1**, **B1**

**2. We only ever ran on `localhost`.** That is a secure context and a single
user. Two whole classes of defect are invisible there: browser APIs gated on
HTTPS, and anything concurrent. → **A7**, and it is why **A2** went unnoticed

**3. New guards added beside old code, without re-checking the interaction.**
The idempotency guard (**A5**) was added above a pre-existing `del`, so it could
never fire. The commit-result cache (**A3**) was added without asking what
happens on the rep's *second* dictation. Each change was correct in isolation
and wrong in combination. → **A3**, **A5**

**4. A contract added to one endpoint but not its twin.** The 409 +
`missing_topics` contract went onto `/notes/commit`; `/notes/confirm` kept its
catch-all and silently turned the same condition into a 500. → **A4**, and the
same shape in **A8**

The remaining three are ordinary local defects: a batching buffer with no drain
path (**A6**), a guard condition applied to the counter but not the send
(**A9**), and a list mutated in place in session state (**A10**).

---

## A — correctness (all fixed)

### A1 — BigQuery backend broken and bypassing every gate

**Cause.** `main.py` grew kwargs on `db.commit_notes(...)` and gained the
coverage gate; `bigquery_db.commit_notes(session_id, confirmed)` was never
updated. Every commit under `BIGQUERY_ENABLED=true` raised `TypeError`. The
stale `CRMStore` Protocol meant nothing flagged it.

**Worse than reported.** Suresh flagged the coverage gate. `bigquery_db` also
skipped the `superseded_by` check and had no idempotency guard — **three** gates
absent, so AIML-2703's fix was missing on that backend too and a retry minted a
duplicate record.

**Fix.** `bigquery_db.commit_notes` takes the full kwarg set and delegates the
entire commit to `mock_db.commit_notes`, owning only the BigQuery insert. Gates
are inherited, not re-implemented, so the two backends cannot drift again. The
insert is keyed off `_record` being present in the result — absent on a cancel
and on an idempotent replay, exactly when a row must not be written. Dataset and
table are validated *before* delegating, since `mock_db` mints the record and
drops the staged one. Also fixed the signature half of **B1**.

**Verified.** 13 assertions with a stubbed BQ client.

### A2 — race on `_S_COMMIT_RESULT` → two CRM records for one visit

**Cause.** The idempotency check was get-then-set across two awaited HTTP
round-trips. ADK's Live flow can dispatch several function calls from one model
turn concurrently, so both invocations read the key as unset and both committed
— two independent stagings, which neither the supersede gate nor `mock_db`'s
session-keyed idempotency can see.

**Fix.** A per-session `asyncio.Lock` wraps the sequence, with the check
repeated inside it. The commit body moved to `_commit_guided_notes_locked`. The
loser finds the winner's result and replays it.

**Verified.** Reproduced before asserting the fix: the unlocked path yields
**2 CRM records** under `asyncio.gather`; the locked entry point yields **1**,
both callers returning the same id.

### A3 — stale commit result reused across dictations

**Cause.** The client holds the WebSocket open between dictations to skip
Vertex's cold-start handshake, so `session_id` persists — and
`_S_COMMIT_RESULT` was never cleared. The rep's second visit of a shift hit the
idempotency check, got the previous visit's result, and the agent said "saved"
while nothing was staged.

**Fix.** Both sides, deliberately. Client: `finishSession()` closes the socket
and rotates `sessionId`, matching the campaign-change, mode-change and reconnect
paths. Server: `capture_dictation` resets guided state when a dictation arrives
on a session that already committed, and `_reset_guided_state` now clears
`_S_COMMIT_RESULT` (it leaked through the re-record path too). The guarantee
should not depend on one client behaving — `ws_smoke_test.py` reuses sessions.

**Trade-off.** The next dictation now pays the 6–10s cold start again. Silently
losing a visit is worse.

**Verified.** Two dictations on one session produce two distinct records holding
their own topics.

### A4 — `/notes/confirm` downgraded 409 to a generic 500

**Cause.** The structured error contract was added to `/notes/commit` only.
`/notes/confirm` kept a catch-all, and `IncompleteCoverageError` subclasses
`Exception`, so an incomplete record returned "Internal server error" instead of
409 + `missing_topics`.

**Fix.** The mapping moved into one `_commit_failure_response(exc)` helper both
endpoints share — the drift *was* the defect. `/notes/confirm` falls through to
500 only for genuinely unmapped errors. It was also leaking the internal
`_record` key into its response body; now stripped.

**Verified.** All four cases: 409 + `missing_topics`, 409 + `superseded_by`,
404, and an unmapped error left for the 500 path.

### A5 — idempotency guard was unreachable

**Cause.** `del _STAGED_NOTES[session_id]` ran in the same call that set
`committed=True`, so a genuine retry found no record and got a 404. The comment
described behaviour that could not occur.

**Fix.** The delete was the wrong half — the committed record now stays;
`committed=True` retires it as a commit target. One consequence had to be closed
with it: a committed record became findable as a correction base, which would
let a correction supersede a record already in the CRM. `stage_notes` now
refuses that and stages a new record — exactly the old behaviour, when the
lookup simply missed.

**Trade-off.** `_STAGED_NOTES` retains one entry per committed visit. It already
leaked (**B11**); that eviction hook must reap committed entries rather than
reinstate this delete.

**Verified.** Three commits of one `session_id` return the same
`crm_record_id`, leave one committed record, and only the first carries
`_record` — so the sink is not written twice.

### A6 — resampler never flushed its tail buffer

**Cause.** Ours, introduced with the resampler that fixed the sample-rate
problem. `emit()` batches ~20 ms before sending and nothing drained the partial
buffer when streaming stopped.

**Correction to the diagnosis.** The review said to flush from `stopMicrophone`
— but that function is never called by `app.js`. The mic stays open across turns
and streaming is gated by `micActive`, so a flush there would never have fired.

**Also worse than reported.** The stranded samples were not merely lost: they
stayed in the buffer and were **spliced onto the front of the next turn**.

**Fix.** `createResampler` gains `flush()`, returned from
`startAudioRecorderWorklet`. `app.js` gains `stopMicStreaming()` — flush, *then*
clear `micActive`, since the handler drops everything once the gate closes. All
seven stop sites route through it. `flush()` resets state before calling
`onChunk`, because the distortion-teardown path re-enters the handler from
inside it and a reset-after would recurse forever.

**Verified.** Measured at 48 kHz: **14 stale samples** carried into the next
turn before, **1** after (the resampler's deliberate interpolation carry).

### A7 — `crypto.randomUUID()` requires a secure context

**Cause.** Ours. We moved to `crypto.randomUUID` to fix ID collisions. It exists
only in a secure context, so on plain HTTP it is `undefined` and threw at module
load, taking the whole frontend down before anything rendered. Invisible because
we only ran on `localhost`.

**Fix.** A `uuid()` helper falling through `crypto.randomUUID` →
`crypto.getRandomValues` (no secure-context restriction) → `Math.random`. RFC
4122 v4 in all three tiers.

**The fallback alone is not sufficient — this changes the answer.**
`getUserMedia` is *also* secure-context-only, so on plain HTTP the page now
loads and the mic still fails. **The honest answer to his question is that this
needs HTTPS.** The fallback means a misconfigured deployment says so instead of
rendering a blank page: `startAudioRecorderWorklet` now throws a message naming
the cause, and `startDictation`'s unguarded `await ensureAudio()` — which left
the UI frozen with planning disabled and no visible reason on *any* audio
failure, including a plain denied mic permission — is caught and surfaced.

**Verified.** 7 assertions, 500 ids per tier, checked for v4 conformance and
uniqueness.

### A8 — two sources of truth for `campaign_type` at commit

**Cause.** The commit path read the client-supplied `body.campaign_type` to
build the sink config, rather than the value the record was staged and validated
under. A client sending a different value at commit would have the CRM write
read from the wrong campaign's disposition registry.

**Fixed a level deeper than suggested.** Reading `record["campaign_type"]` in
`main.py` alone would not have worked — that field was itself populated from the
caller's value. `mock_db.commit_notes` now prefers the staged campaign and warns
when a commit claims a different one; `main.py` reads it off the record.

**Verified.** Staged under `standard_sales`, committed claiming
`enterprise_field` — record keeps `standard_sales`.

### A9 — whitespace-only text bypassed `turn_guard` but reached the model

**Cause.** When turn counting was added to the text path, the condition was put
on the counter but not on the send. A blank-but-non-empty message was processed
by the model as a real turn, yet every `turn_guard`-gated tool afterwards
reported `no_reply_heard` for a turn that genuinely happened.

**Fix.** Guard and send under the same condition; a blank message is dropped and
logged. Gating the send is the right direction — a whitespace-only message
carries no rep input, so counting it as a turn would defeat the backstop.

**Not covered by an automated check.** It sits in the WebSocket upstream loop,
which needs the full ADK stack. The change is a two-line restructure of an `if`.

### A10 — unguarded read-modify-write on guided topic state

**Cause.** `results = state.get(...); results.append(...); state[...] = results`
took the list *object held in session state* and mutated it in place.

**The stated mechanism does not apply.** Unlike A2 this sequence contains no
`await`, so under asyncio two invocations cannot interleave across it — the
lost-update race as described cannot occur today.

**The real defect is different and worth fixing.** In-place mutation is not
necessarily observed by ADK as a state delta. It now copies before appending
(matching what `pending` already did), which guarantees a real delta and makes
the sequence await-safe if one is ever introduced.

**Verified.** The previously-stored list is left untouched; state holds a new
object after a disposition.

---

## B — design / duplication (follow-up ticket)

Not fixed here, by agreement that they are design debt rather than defects. One
exception: **B1**'s signatures were corrected as part of A1, since a correct
Protocol is what would have caught A1 automatically. The rest of B1 — it
declares `self` on methods a *module* has to structurally satisfy — still
stands.

B2–B5 are one theme worth stating in the ticket: campaign rules and error
shaping are duplicated across implicit, guided and the server, which is the same
"three sources of truth" risk in four places. **B11** (session state never
evicted) is more valuable now than when he raised it, because A3 creates many
more sessions per shift and A5 retains committed records.

## C — cosmetic

Formatter pass, not yet run. C3 (redundant `get_agent_config()` on the rejection
path) is a small real cleanup rather than formatting.

## D — positive

Noted, no action.

---

## Verification

Three standalone scripts, 49 assertions, no mic / model / BigQuery / server.

| Suite | Covers | Assertions |
|---|---|---|
| `a1_check.py` | A1 — every gate inherited by the BigQuery backend | 13 |
| `groupA_check.py` | A2, A3, A4, A5, A8, A10 | 19 |
| `a6_a7_check.mjs` | A6, A7 | 17 |

**What is not covered, and should be said plainly:**

- Anything needing a real browser on a non-localhost origin — the A6 and A7
  integration paths. This is the same gap that let both ship.
- The WebSocket upstream loop, so **A9 has no automated check at all**.
- Real ADK concurrency: the A2 test simulates `asyncio.gather` dispatch rather
  than driving ADK itself.
