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

**Status, split by change:**

- `tools.py` plumbing — **`verified-rest`, keep.** This was a genuine bug:
  `needs_manual_review` was *unreachable* from implicit mode. `_normalize_topics`
  rebuilt each topic dict from scratch and silently dropped the field, so
  nothing could ever set it. Worth keeping regardless of the prompt outcome —
  it is what makes an "outcome doesn't fit" option implementable at all.
- Prompt rules — **`attempted, ineffective`.** Measured over 6 live runs of the
  same utterance (3 before, 3 after): the agent never once flagged, and the
  inconsistency was unchanged.

| Config | Runs | Codes returned | Flagged? |
|---|---|---|---|
| Before | 3 | 2, 3, 3 | never |
| After | 3 | 2, 2, 3 | never |
| Control (correct code exists) | 2 | 8, 8 (correct) | n/a |

File sync was verified by marker/line-count comparison before the final run, so
this is not a stale-file artifact.

**Why it failed.** Filling a structured field is effectively an argmax over the
allowed options — there is always a "best" one. Flagging instead requires the
model to judge that its own best answer is still wrong, which is
self-calibration, and `temperature=0.1` explicitly pushes it to commit to the
top choice. The instruction also competes with everything else in the system
telling it to produce a code: the schema has the field, the flow expects it,
the registry is presented as the list to choose from. Same pattern as
`turn_guard` and F3 — a prompt rule losing to structure. The difference is
those had a structural fix available at our layer and this one does not.

Note the model is not confused about the call: its own summary said "expressed
interest, requested a quote", which is accurate. The loss happens in the
**compression** onto five buckets, not in comprehension.

**What would work instead** (needs the lead's approval, see below): make "none
of these apply" a real code in the registry rather than a meta-instruction.
That turns flagging into an ordinary option competing on equal terms, which
argmax can select, instead of an exception the model must volunteer against
the grain.

---

## Batch 6 — Make "no code fits" a selectable option (SOLVED)

Ticket: AIML-2698 · Commit: pending · Supersedes the Batch 5 prompt attempt

Batch 5 failed because it asked the model to volunteer an exception outside the
set of allowed values. Filling a structured field is an argmax over that set —
so the fix is to put the escape hatch *inside* the set.

| File | Change | Why |
|---|---|---|
| `mock_db.py` | `DispositionCode.OUTCOME_NOT_COVERED = 99` | The registry needed a real value meaning "none of these" |
| `mock_db.py` | `_NOT_COVERED_RULE`, appended to every campaign by `get_agent_config` | A narrowed campaign registry must never leave the agent unable to say the outcome isn't representable |
| `mock_db.py` | `_DISPOSITION_BY_CODE` includes the rule | **Bug found in testing:** without it `disposition_label(99)` fell through to `"Other"`, and the agent read "marked as other" aloud while the UI badge showed the correct label |
| `mock_db.py` | `stage_notes` sets `needs_manual_review` whenever code is 99 | Server-side so implicit, guided and plain REST agree, rather than trusting each caller to pair them |
| `agent.py` | Prompt: match on OUTCOME not keywords; 99 is a normal expected choice, with a worked example | Presents 99 as a peer option rather than a failure state |
| `tools.py` | Tool docstring points at 99 | The model had no way to know the option existed |

**Status: `verified-live`.** Six runs across three scenarios:

| Test | Campaign | Utterance | Expected | Result |
|---|---|---|---|---|
| A | renewals | "interested, wants a quote" | 99 — no fitting code exists | **99, 99** |
| B | renewals | "price ~10% higher than a competitor" | 8 — fitting code exists | **8, 8** |
| C | standard_sales | "interested, wants a quote" | 1 — fitting code exists | **1, 1** |

A and C are the same sentence under different campaigns. B and C are the
over-triggering controls: 99 never won when a real code was available. Prior to
this change the A scenario returned 2 or 3 at random across six runs and never
once flagged.

**Transferable lesson:** three fixes in this ticket followed the same shape —
`turn_guard`, F3 (self-skip) and this one. A prompt rule cannot beat a
structure that points the other way. Change the structure and the behaviour
follows; leave the structure and the rule is ignored, however emphatically it
is worded.

## Batch 7 — Make the smoke harness able to hold a conversation

Ticket: AIML-2698 (AC#1, AC#5) · Commit: pending

Guided mode had never been exercised automatically. Investigating why produced
two fixes, neither of which is in the agent logic.

| File | Change | Why |
|---|---|---|
| `main.py` | `upstream_task` calls `turn_guard.record_user_turn()` for non-empty **text** turns | The counter only incremented on `input_transcription` events, which audio produces and text does not. Every turn_guard-gated tool (`commit_visit_notes`, `set_event_type`, `record_topic_disposition`, `choose_post_dictation_action`) was therefore permanently blocked in text mode — so the harness could never get past `capture_dictation`. A typed turn is a genuine rep turn and must count. |
| `ws_smoke_test.py` | Wait for the agent to fall silent (`_drain_until_agent_settles`) instead of breaking on the first `turnComplete` | One agent response emits several `turnComplete` events. Breaking on the first sent the next scripted turn mid-response — the "rep" answered questions before they were asked, the model then answered its own question, `turn_guard` (correctly) blocked it, required state was never set, and the commit failed. One race, four layers of fallout. |
| `ws_smoke_test.py` | Longer quiet period after the final turn; trailing `"Okay."` on `clean_save` | Works around F5 so scenarios can reach a commit. Marked in-code as a workaround, not a fix. |

**Diagnosis note.** The turn_guard blocks looked like a bug for most of a day.
Instrumenting `record_user_turn` / `snapshot` / `has_new_reply` and interleaving
them with `Upstream text` in one log settled it in minutes: `snapshot
baseline<-4` followed 1s later by `has_new_reply current=4 baseline=4 -> False`
with no rep turn in between — the model calling two tools in one turn. **The
guard was right every time.** Worth remembering before "fixing" it again; the
temporary instrumentation is described here rather than left in the code.

**Status: `verified-live`.** All 8 scenarios across both modes now commit:

| Mode | Scenario | Outcome |
|---|---|---|
| guided | clean_save | Pricing=8, Renewal=2 |
| guided | rerecord | Renewal=2 only — re-record correctly discarded prior state |
| guided | ambiguous_disposition | no code, `needs_manual_review=true`, summary "Rep was unsure how to classify the outcome after three attempts" |
| guided | playback_then_save | **did not commit — hit F5** |
| implicit | clean_save | Pricing=8 |
| implicit | correction | event type corrected to Meeting |
| implicit | missing_topic | Renewal skipped, no code — coverage path |
| implicit | multi_topic | Pricing=8, Renewal=2 |

## Open: needs sign-off from the project lead (mechanism solved)

**The `renewals` disposition registry has no code for "customer is interested
and requested a quote."** Measured behaviour, one utterance, four runs:

Utterance: *"Just got off the phone with Acme about their renewal. They're
really interested and want me to send over a quote."* Campaign `renewals`,
which allows codes 2, 3, 5, 8, 9.

| Runs | Codes returned | Correct? |
|---|---|---|
| 6 (3 before + 3 after the prompt mitigation) | 2, 3, 3, 2, 2, 3 | **no** — 2 means the sale closed, 3 means there is no deal; opposite meanings, neither true |
| 2 control: *"our price is ~10% higher than a competitor"* | 8, 8 | **yes**, both times |

The control proves the model maps correctly when a correct code exists, so the
fault is the registry, not the agent. In one run the free-text summary was
accurate ("next step is to prepare and send a formal quote") while the
disposition code said Order Placed — **the structured field that feeds
reporting was the wrong one**, while the prose a human would read was right.

A prompt-level mitigation was attempted and measurably failed (see Batch 5).

**Options, both product decisions:**

1. **Add code 1 (Create Opportunity) to `renewals`.** Renewal conversations do
   generate new opportunities; excluding it looks like an oversight.
2. **Add a registry-wide "outcome not covered by this registry" code.** More
   general — catches every future gap and gives the agent a way to say "I don't
   know" that it can actually express.

Recommend both: (1) closes this hole, (2) makes the system fail loudly rather
than silently the next time a hole appears.

---

## Batch 6 — Rebase onto the lead's branch, and Gap 6 closed

Date: 2026-08-11 · Branch: `feature/AIML-2698-on-2130`

### Context

`feature/AIML-2130-guided-flow` had moved to `c6860bd` after all. An earlier
check read a stale remote-tracking ref and concluded it had not — always settle
that with `git ls-remote`, not `git rev-parse`, when the web UI disagrees.

Decision: **rebase our five 2698 commits on top of `c6860bd`** rather than
merging his into ours. His branch is what leadership saw, so it is the
demo-credible base.

### What his commit contained

Despite the message ("Fixed both implicit and guided flow disposition fields"),
`c6860bd` does **not** touch the disposition registry. It contains:

| File | Change |
|---|---|
| `app.js` (+186), `style.css` (+20), `index.html` (+16) | Guided-flow record card rendering |
| `mock_db.py` (+19) | Idempotent `commit_notes` — returns the original `crm_record_id` on retry instead of minting a duplicate |
| `main.py` (+41), `agent_guided.py` (+23) | Supporting changes |
| `demo_assets/` | Slide generators + 5 PNGs — a leadership deck, not code |

**`app.js:845` — `renderPayload(guidedPayload)` — closes Gap 18.** Guided mode
now populates the on-screen record card from its incremental tool calls. That
was on our list as a demo blocker; his fix removed it.

### Conflicts and how they were resolved

| File | Resolution |
|---|---|
| `mock_db.py :: commit_notes` | His idempotency guard placed **above** our coverage gate. Safe because the gate runs before `record["committed"] = True` is ever set, so `committed=True` implies the record already passed validation. Kept his `record["crm_record_id"] = crm_record_id` (the guard reads a key nothing else wrote); dropped his duplicate assignment block, which would otherwise have marked the record committed *before* validation. |
| `app.js` | Kept his `renderPayload` call **and** our comment about `turnComplete` re-arming the mic. Ours was comment-only; taking either side alone would have lost something. |

Also caught: `VOICE_NOTES_BQ_ENABLED=false` had ridden into a commit. Restored
to `true` (`6b7e27b`); the local override belongs in the working tree,
uncommitted.

**Status:** `verified-live` — server boots, both modes reach a commit.

---

## Batch 7 — Gap 6 / F5: guided stalls before saving

Ticket: AIML-2698 · Commit: `3ce0c34`

| File | Change | Why |
|---|---|---|
| `tools_guided.py` | `record_topic_disposition` commits directly at `all_topics_done` instead of returning "call `commit_guided_notes` now" | The model reliably did not act on that instruction — empty output turn, turn closed, nothing saved, no signal to the rep. The second hop bought nothing: no further rep input is needed at that point. |
| `tools_guided.py` | `_S_COMMIT_RESULT`; `commit_guided_notes` replays the prior result instead of re-staging | Without it, a model that still makes the call re-stages under a **new** `session_id` and mints a duplicate record. `mock_db`'s idempotency guard keys on `session_id` and cannot catch that. |
| `ws_smoke_test.py` | Removed the trailing `"Okay."` nudge from `clean_save` | It existed only to mask this defect. Leaving it in would let the stall return without any scenario failing. |

This is the fifth fix in this ticket to follow the same shape: **a structural
change beat an instruction the model was free to ignore.** The one prompt-only
attempt (Batch 5) remains the only measured failure.

**Status:** `verified-live`. 4 guided + 4 implicit scenarios, one CRM record
each, no duplicates. `clean_save` reaches `CRM-0408460644` with the nudge turn
removed — the fix stands unaided.

---

## Batch 8 — Guided deadlocked whenever the rep skipped a planned topic

Ticket: AIML-2698 · Found during live rehearsal, 2026-08-11

### Symptom

Scenario B (guided, Appliances + Pool Supplies, rep skips Pool Supplies): the
agent asked *"What was the outcome for Pool Supplies?"*, the rep answered
*"we didn't get to it"* — and the agent then said "Let me check" and hung.

```
record_topic_disposition topic=Pool Supplies code=None remaining=0
Staged notes ... topics=2 missing=1
Commit BLOCKED ... planned topics without an outcome: ['Pool Supplies']
POST /api/v1/notes/commit 409 Conflict
Guided commit blocked -- uncovered topics: ['Pool Supplies']
```

### Cause

`stage_notes` sets `allow_skips = previous is not None` — a `discussed=false`
topic counts as coverage only on a **re-stage**, because a re-stage implies the
rep was asked (the F3 fix, Batch 3).

Guided stages exactly **once**, from `commit_guided_notes`. So the skip never
counted, the commit 409'd, and the agent was instructed to ask about a topic it
had just asked about — a loop with no exit.

### Fix

| File | Change |
|---|---|
| `mock_db.py` | `stage_notes(..., agent_mode="implicit")`; `allow_skips = previous is not None or agent_mode == "guided"` |
| `main.py` | `/api/v1/notes/stage` accepts `agent_mode` as a query param and passes it through |
| `tools_guided.py` | `commit_guided_notes` stages with `params={"agent_mode": "guided"}` |

**Why guided is safe to exempt:** a `discussed=false` entry there can only be
produced by `record_topic_disposition`, which is gated on
`turn_guard.has_new_reply` — the rep provably answered the outcome question for
that topic. The provenance the re-stage rule *infers* is guaranteed at the tool
level. **Implicit is unchanged**, so the F3 protection still applies where it
was measured.

**Status:** `verified-live`. `topics=2 missing=0`, commit 200, `CRM-9B6000D420`
with Pool Supplies as `discussed=false` carrying the rep's own reason.

### Why this took so long to find

The Gap 6 stall was **masking** it. Guided never reached the commit, so the 409
never fired. Every guided session where the rep skipped a planned topic would
have deadlocked — and on real data that is the *common* case, since 67% of
notes mention no planned category at all.

Neither the REST suite nor `ws_smoke_test` covered "rep skips a topic in
guided". **Live rehearsal found it; the harness would not have.** Add that case
to both before AIML-2702.
