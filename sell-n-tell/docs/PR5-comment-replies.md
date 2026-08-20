# PR #5 — inline reply text

Short replies for Suresh's 25 comments. Detail lives in `PR5-response.md` and
`PR5-vdi-results.md` — link those if he wants more.

**🔴 = says something he did not report.** Read those four before posting; each
either corrects his diagnosis or admits the problem was bigger.

---

## Section A — all 10 fixed and verified on the app machine

### A1 · `main.py`, commit endpoint 🔴

> Fixed — `bigquery_db.commit_notes` now takes the full kwarg set and delegates
> the whole commit to `mock_db.commit_notes`, owning only the BigQuery insert.
> Every gate is inherited rather than re-implemented, so the two backends can't
> drift again.
>
> It was worse than reported: `bigquery_db` also skipped the `superseded_by`
> check and had no idempotency guard, so AIML-2703's fix was absent there too
> and a retry minted a duplicate record. Three gates, not one.
>
> Also fixed the `CRMStore` signatures (your other comment) — that's what should
> have caught this.
>
> Verified with a stubbed BQ client: coverage-blocked, superseded, cancelled and
> replayed commits all write zero rows. Not yet exercised against a live
> dataset.

### A2 · `tools_guided.py` ~L405

> Confirmed and fixed. A per-session `asyncio.Lock` now wraps the read-then-
> commit sequence with the check repeated inside it; the loser replays the
> winner's result.
>
> Reproduced before fixing: the unlocked path yields 2 CRM records under
> `asyncio.gather`, the locked path 1.

### A3 · `tools_guided.py` ~L572

> Fixed on both sides. Your client fix is in — `finishSession()` closes the
> socket and rotates `sessionId`.
>
> Also reset server-side: `capture_dictation` clears guided state when a
> dictation arrives on a session that already committed. `ws_smoke_test.py`
> reuses sessions, so the guarantee shouldn't rest on one client.
>
> Verified in the browser: three dictations in one page load produced three
> distinct CRM records. Timings were 45.6s / 59.2s / 36.6s, so the socket
> re-establishment isn't a consistent penalty.
>
> One thing this surfaced: the planning panel stayed locked after a save, so the
> rep couldn't pick different topics without reloading. Harmless while
> back-to-back dictations weren't really supported — rotating the id is what
> makes them supported, so `finishSession` now unlocks it.

### A4 · `main.py`, `confirm_notes_endpoint2`

> Fixed. The mapping moved into one `_commit_failure_response(exc)` helper both
> commit endpoints share — the drift between them was the defect. Falls through
> to 500 only for genuinely unmapped errors.
>
> It was also leaking the internal `_record` key into its response body; that's
> stripped now.
>
> Verified: 409 + `missing_topics`, 409 + `superseded_by`, 404, and an unmapped
> error still reaching 500.

### A5 · `mock_db.py` ~L822

> Fixed — the `del` was the wrong half. The committed record now stays in
> `_STAGED_NOTES`; `committed=True` retires it as a commit target, and the entry
> has to survive to answer the retry it exists for.
>
> One consequence closed with it: a committed record became findable as a
> correction base, which would let a correction supersede a record already in
> the CRM. `stage_notes` now refuses that — which is what happened before, when
> the lookup simply missed.
>
> This does mean `_STAGED_NOTES` retains one entry per committed visit. It
> already leaked (your B11 comment); that eviction hook now matters more.
>
> Verified: three commits of one `session_id` return the same id and leave one
> committed record.

### A6 · `audio-recorder.js` ~L120 🔴

> Fixed, but not where you suggested — `stopMicrophone` is never called by
> `app.js`. The mic stays open across turns and streaming is gated by
> `micActive`, so a flush there would never have fired. The real end-of-stream
> points are the seven places that clear `micActive`, which now route through a
> `stopMicStreaming()` that flushes *then* closes the gate.
>
> Second symptom you didn't see: the stranded samples weren't just lost, they
> were spliced onto the front of the next turn. 14 stale samples at 48 kHz
> before the fix, 1 after (the resampler's deliberate interpolation carry).
>
> Verified in a real dictation ending "…Thanks Betty." — the final word appears
> both in the browser's own recognizer caption and in the raw transcript Gemini
> received.

### A7 · `app.js` L23, L25 🔴

> Fixed with a fallback — `crypto.randomUUID` → `crypto.getRandomValues` (no
> secure-context restriction) → `Math.random`, RFC 4122 v4 in all three tiers.
>
> Verified over plain HTTP by serving on the machine's LAN IP rather than
> `localhost` (only loopback is a secure context). There `crypto.randomUUID` is
> genuinely `undefined`, the page renders where it was previously blank, and the
> rep id in the header was minted by the fallback — `localStorage` is
> per-origin, so it had to be.
>
> **But the fallback alone isn't sufficient, so the answer is still yes, this
> needs HTTPS.** `getUserMedia` and `AudioWorklet` are both secure-context-only,
> so the mic can't work there regardless. What the fix buys is a legible failure
> instead of a blank page.
>
> That test also turned up a second bug in my own fix: I'd put the HTTPS guard
> in `startAudioRecorderWorklet`, but `ensureAudio()` builds the *player*
> worklet first, so the real error was `Cannot read properties of undefined
> (reading 'addModule')`. The check now sits in `ensureAudio()` on
> `window.isSecureContext`, before any audio API is touched.
>
> Also caught: `startDictation`'s `await ensureAudio()` was unguarded, so any
> audio failure — including a plain denied mic permission, far more likely than
> a non-HTTPS deployment — froze the UI with no visible reason. Now surfaced.

### A8 · `main.py` ~L340

> Fixed a level deeper than suggested. Reading `record["campaign_type"]` alone
> wouldn't have worked — that field was itself populated from the caller's
> value. `mock_db.commit_notes` now prefers the campaign the record was staged
> and validated under, and warns when a commit claims a different one.
>
> Verified: staged `standard_sales`, committed claiming `enterprise_field`,
> record keeps `standard_sales`.

### A9 · `main.py` ~L768

> Fixed — guard and send are now under the same condition, and a blank message
> is dropped and logged rather than forwarded. Gating the send rather than
> ungating the counter: a whitespace-only message carries no rep input, so
> counting it as a turn would defeat the backstop.
>
> Verified over a live WS session: a blank frame produces no model turn, and the
> real turn after it works with no tool reporting `no_reply_heard`.

### A10 · `tools_guided.py` ~L317 🔴

> Fixed, though I don't think the race can happen as described — unlike the
> `_S_COMMIT_RESULT` case, this sequence contains no `await`, so under asyncio
> two invocations can't interleave across it.
>
> There is a real defect underneath it: `results` was the same list object held
> in session state, so `.append()` mutated it in place, which ADK doesn't
> necessarily observe as a state delta. It now copies before appending, matching
> what `pending` already did — which also makes it await-safe if one is ever
> introduced.

---

## Section B — follow-up ticket

Swap `AIML-XXXX` for the real id once raised.

### B1 · `db_interface.py`

> Signatures fixed here — a correct Protocol is what should have caught the
> BigQuery mismatch, so it belonged with that fix. The rest is in AIML-XXXX: it
> declares `self` on methods a *module* has to satisfy, which is why it wasn't
> enforcing anything.

### B2 · `tools.py` ~L44 · `tools_guided.py` ~L45 · `mock_db.py` ~L452

> Agreed, AIML-XXXX. This is the core of that ticket — three implementations of
> "what's legal for this campaign", reading different data. B3/B4/B5 are the
> same theme.

### B3 · `tools.py` ~L462 · `tools_guided.py` ~L520-527

> Agreed, AIML-XXXX, with B2/B4/B5 as one consolidation.

### B4 · `tools.py` ~L264 · `tools_guided.py` ~L482

> Agreed, AIML-XXXX. The same fix already landed server-side — both commit
> endpoints now share one error-shaping helper (your `/notes/confirm` comment).

### B5 · `tools.py` ~L37-40 · `tools_guided.py` ~L41-42

> Agreed, AIML-XXXX. The silent-`None`-then-fall-back-to-global-registry failure
> is what makes this worth doing rather than cosmetic.

### B6 · `mock_db.py` ~L708 · `tools.py` · `tools_guided.py` ~L323

> Agreed, AIML-XXXX — `mock_db` as single source of truth, tool layers just null
> the code.

### B7 · `mock_db.py` ~L428

> Agreed, AIML-XXXX. Splicing 99 in at two read sites while keeping it out of
> the registries it's spliced into is a trap for the next reader.

### B8 · `mock_db.py` ~L728

> Agreed, AIML-XXXX. The topic-status enum is the right shape — it already
> needed one carve-out for guided, and a third calling pattern would need
> another.

### B9 · `tools_guided.py` ~L408

> Agreed, AIML-XXXX. The inline commit is deliberate (it works around a
> documented model-behaviour gap) but nothing at the prompt end says so; adding
> the cross-reference.

### B10 · `app.js` ~L1010-1023

> Agreed, AIML-XXXX — `isMidFlowContinue(resp)` / `isRefusal(resp)` as guard
> clauses. Fair point that it's the bug class Batch 3 already fixed once.

### B11 · `turn_guard.py` · `mock_db._STAGED_NOTES`

> Agreed, AIML-XXXX — and this got more valuable during this round. Two fixes
> push more state through those dicts: rotating `session_id` per dictation
> creates many more sessions per shift, and the idempotency fix keeps committed
> records in `_STAGED_NOTES` instead of deleting them. The cleanup hook needs to
> reap committed entries.

---

## Section C — formatter pass

### C1 · `mock_db.py`
> Fixed in the formatter pass.

### C2 · `tools_guided.py`
> Fixed in the formatter pass.

### C3 · `main.py` ~L275
> Fixed — treating this as a real cleanup rather than formatting.
> `validate_against_campaign` returning `(problems, config)` removes the second
> lookup.

### C4 · `audio-recorder.js`
> Noted. Leaving the closure as-is for now — A6 touched this file and I'd rather
> not reshape it in the same PR. Folding into AIML-XXXX with the other
> refactors.

---

## Section D

### D · `app.js` ~L1206
> Thanks — that one was a genuine find on our side too.
