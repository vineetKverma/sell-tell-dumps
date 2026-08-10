# AIML-2698 — Gap findings report

Scope: **discovery and reproduction only.** This documents the correctness gaps
found in the current Implicit and Guided flows, how each was reproduced, and
where reproduction was not possible, why not. Remediation is out of scope and
will be raised as a separate ticket.

Branch under test: `feature/AIML-2130-guided-flow` @ `3ecd956`
Campaigns exercised: `standard_sales`, `renewals`

---

## Method

Two independent approaches, deliberately:

1. **REST-level reproduction.** The ADK tools call the app's own `/api/v1`
   endpoints over HTTP, so a gap in staging or commit logic can be reproduced
   with plain HTTP calls — no microphone, no model, no Vertex dependency, fully
   deterministic. Used wherever the gap lives in application logic.
2. **Live session reproduction.** Browser mic against Vertex/Gemini Live, for
   anything involving model behaviour, conversation flow, or the UI.

Where a gap could be reproduced both ways, both are given: the REST version is
the one to put in a regression suite; the live version is what a FAR would
actually experience.

---

## Summary

| # | Gap | Reproduced | Demo risk |
|---|---|---|---|
| 1 | Commit succeeds when planned topics have no outcome | ✅ REST + live | **High** |
| 2 | Campaign disposition codes / event types not enforced | ✅ REST + live | **High** |
| 3 | Model marks topics "not discussed" on the rep's behalf, with an invented reason | ✅ live | **High** |
| 4 | Invented skip reasons appear in the call summary | ✅ live | Medium |
| 5 | Disposition is wrong and non-deterministic when the registry has no fitting code | ✅ live, 6 runs + control | **High** |
| 6 | Guided stalls before saving after the last topic | ✅ harness, intermittent | **High** |
| 7 | `turn_guard` counts only spoken turns, so text input is permanently blocked | ✅ harness | Medium (blocks testing) |
| 8 | Stale CRM record id shown against a newly staged record | ✅ live | Low |
| 9 | Readback is paraphrased rather than read verbatim | ✅ live | Medium |
| 10 | Skipped topics are not mentioned in the spoken readback | ✅ live | Medium |
| 11 | Topic labels containing "/" are read aloud as "slash" | ✅ live | Low |
| 12 | ADK/OpenTelemetry traceback on every disconnect | ✅ live | Low (log noise) |
| 13 | Mic streams continuously while the page is open | ✅ observed | Low (cost) |
| 14 | Frontend infers success by enumerating failure statuses | ⚠️ latent | Medium |
| 15 | Orphaned staged records after a correction | ❌ not reproduced | Unknown |
| 16 | `turn_guard` state never reset between connections | ❌ not reproduced | Unknown |
| 17 | Ticket rows 1–3 (splintered topics, commit without stage, tools blocked) | ❌ not reproduced | — |

---

## Gap 1 — Commit succeeds when planned topics have no outcome

The rep pre-selects topics to cover. The system detects when one has no outcome
and reports it, but nothing prevents the record being committed.

**Reproduction (REST).** Stage a record covering 1 of 2 planned topics, then
commit it:

```powershell
$body = @{
  event_type = "On-site visit"
  executive_summary = "Visited Acme. Renewal on track; pricing pushback."
  raw_transcript_backup = "Just left Acme..."
  topics = @(@{ topic = "Contract / agreement renewal"; disposition_code = 3; executive_summary = "Wants to re-sign."; discussed = $true })
  planned_topics = @("Contract / agreement renewal", "Pricing")
} | ConvertTo-Json -Depth 5
$stage = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/notes/stage" -Body $body -ContentType "application/json"
$stage | ConvertTo-Json -Depth 5
$commit = @{ session_id = $stage.session_id; confirmed = $true; agent_mode = "implicit"; campaign_type = "standard_sales" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/notes/commit" -Body $commit -ContentType "application/json"
```

**Observed.** Staging correctly reports `missing_topics: ["Pricing"]`,
`all_topics_covered: false`, and generates a confirmation that asks about
Pricing. The commit then succeeds and returns `CRM-B598122C53`. The committed
record itself carries `missing_topics: ["Pricing"]` — **the system stores the
fact that the record is incomplete and saves it anyway.**

`compute_missing_topics` is called at both stage and commit, but no layer
branches on the result. The only thing discouraging a premature save is prompt
text ("Do NOT save yet"), which is model-dependent.

**Live.** Same result via the UI: dictate one of two planned topics, say "Save",
record commits.

---

## Gap 2 — Campaign disposition codes / event types not enforced

Each campaign declares its own allowed event types and disposition codes.
`renewals` allows event types `[Phone Call, Meeting]` and codes `[2,3,5,8,9]`.

**Reproduction (REST).** Stage a `renewals` payload violating both:

```powershell
$bad = @{
  event_type = "On-site visit"      # not allowed for renewals
  executive_summary = "Renewals call with Acme."
  raw_transcript_backup = "They're interested, wants a quote..."
  topics = @(@{ topic = "Contract / agreement renewal"; disposition_code = 1; executive_summary = "Wants a quote."; discussed = $true })  # code 1 not in renewals registry
  planned_topics = @("Contract / agreement renewal")
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/notes/stage?campaign_type=renewals" -Body $bad -ContentType "application/json"
```

**Observed.** Both illegal values accepted, `all_topics_covered: true`, and the
generated confirmation reads the illegal disposition back to the rep as valid:
*"I've staged an On-site visit covering Contract / agreement renewal marked as
create opportunity."*

**Root cause.** `POST /api/v1/notes/stage` accepts no `campaign_type` parameter,
so the `?campaign_type=renewals` above is silently ignored by FastAPI. With no
campaign in scope, validation falls back to global lists — `event_type` against
all three types, disposition codes against all ten. **The campaign config is
injected into the model's prompt but never used to validate its output.**

---

## Gap 3 — Model marks topics "not discussed" on the rep's behalf

**Reproduction (live).** Campaign `standard_sales`, planned topics *Contract /
agreement renewal* and *Pricing & promotions*. Dictate only the renewal:

> "Just left Acme. We talked through the contract renewal and they're happy to
> re-sign for another year. That's it."

**Observed.** The agent staged **both** topics, marking the second:

```json
{"topic": "Pricing & Promotions",
 "executive_summary": "Rep did not get to pricing due to time constraints.",
 "discussed": false}
```

The rep said nothing about time constraints. The agent then skipped the coverage
question entirely and went straight to "Should I save this?".

**Why it matters.** Coverage treats a planned topic as addressed once its label
appears in `topics`, regardless of `discussed`. That is reasonable for a rep who
says "I skipped it" — but a rep-stated skip and a model-invented skip produce
identical payloads. **The check has no way to tell who decided.**

**Non-deterministic.** An earlier run of the same scenario asked about Pricing
correctly. The prompt supports both readings: step 2 says to add an entry for
every topic "the rep actually discussed", while the field-mapping rules describe
`discussed: false` as a plain value with no timing constraint.

---

## Gap 4 — Invented skip reasons in the call summary

**Reproduction (live).** Continue Gap 3's session. When asked what happened with
Pricing, answer exactly *"I skipped it"* — give no reason.

**Observed.** The topic-level summary was factual ("Topic was skipped"), but the
overall call summary read: *"The planned discussion on pricing and promotions was
skipped **due to time constraints**."* No reason was given by the rep. Note this
is the same invented phrase as Gap 3, suggesting a default filler rather than a
one-off.

---

## Gap 5 — Disposition wrong and non-deterministic when no code fits

**Reproduction (live).** Campaign `renewals`, planned topic *Contract / agreement
renewal*. Dictate:

> "Just got off the phone with Acme about their renewal. They're really
> interested and want me to send over a quote."

Run it several times, refreshing between each.

**Observed, six runs:** disposition returned **2 — Order Placed** or **3 — No
current need, revisit in the future**, varying run to run (2, 3, 3, 2, 2, 3).
Code 2 says the sale closed. Code 3 says there is no deal. Neither happened.

**Control, same campaign, an utterance that does have a matching code:**

> "They said our price is about ten percent higher than a competitor."

returned **8 — Pricing concerns** correctly, twice out of two.

**Second control, same utterance as above but campaign `standard_sales`**
(which includes code 1): returned **1 — Create Opportunity** correctly, twice.

**Conclusion.** This is not a model-quality problem. `renewals` allows codes
2, 3, 5, 8, 9, and none of them describes "customer is interested and requested a
quote" — Create Opportunity is excluded from that campaign. With no correct
option available the model returns the nearest, and which "nearest" varies.

**Why this is the most dangerous gap found.** Nothing errors, so the readback
sounds fluent and the rep says "Save". In one run the free-text summary was
accurate — *"the next step is to prepare and send a formal quote"* — while the
disposition code said Order Placed. **The prose a human would read was right;
the structured field that feeds reporting was wrong.**

---

## Gap 6 — Guided stalls before saving after the last topic

**Reproduction (harness).** `scripts/ws_smoke_test.py guided --scenario clean_save`,
after the harness limitation in Gap 7 is worked around.

**Observed.** After the final topic is dispositioned,
`record_topic_disposition` returns `{'status': 'all_topics_done',
'instruction_for_model': "...Call commit_guided_notes now..."}`. The model then
emits an empty output turn, closes the turn, and does nothing further. Waited 15
seconds; the auto-continue nudge in `main.py` did not rescue it (the 4-nudge
session cap may already have been consumed). Any further rep utterance unblocks
it immediately.

**Intermittent.** In a four-scenario run, `rerecord` and `ambiguous_disposition`
committed unaided while `playback_then_save` did not. **This is worse than a
consistent failure — it will pass rehearsal and can still fail in front of the
FARs.**

**Impact.** Dead air at the worst possible moment: every question answered, the
record complete, nothing saved, and no signal to the rep that anything is wrong.

---

## Gap 7 — `turn_guard` counts only spoken turns

**Reproduction (harness).** Run any scenario in either mode:
`scripts/ws_smoke_test.py guided`.

**Observed.** Every tool after `capture_dictation` returns
`{'status': 'error', 'error': 'no_reply_heard'}`, in all four scenarios, despite
the harness sending a reply each turn. No scenario reaches a commit.

**Cause.** The turn counter is incremented only from `input_transcription`
events, which the audio path produces and text input does not. Any client using
the text channel therefore has every `turn_guard`-gated tool
(`commit_visit_notes`, `set_event_type`, `record_topic_disposition`,
`choose_post_dictation_action`) permanently blocked.

**Consequence for the project:** the existing smoke harness has been unable to
complete a scenario since `turn_guard` was introduced, which is why **Guided
mode has had no automated coverage at all.**

---

## Gap 8 — Stale CRM record id against a newly staged record

**Reproduction (live).** Complete one dictation through to save, then without
refreshing, start a second dictation in the same page session.

**Observed.** The staged-record panel shows the badge `staged` alongside the
**previous** session's `CRM-…` id. `renderPayload` never clears that field; it is
only written on commit.

---

## Gap 9 — Readback paraphrased rather than read verbatim

**Reproduction (live).** Any session where a planned topic is uncovered.

**Observed.** The prompt requires the agent to speak the generated
`confirmation_text` "verbatim and in full". In practice it paraphrases. In one
run, where the generated text asked *"What happened with Pricing & promotions?"*,
the agent instead said *"You didn't mention pricing and promotions. Does that
sound correct?"* — inviting a bare "yes" to a question that was never asked.

**Impact.** The backend controls that wording deliberately, to collect a specific
answer. Paraphrasing costs a conversational round trip and can steer the rep
toward confirming rather than supplying the missing outcome.

---

## Gap 10 — Skipped topics are absent from the spoken readback

**Reproduction (live).** Have a topic recorded as `discussed=false`, then listen
to the confirmation.

**Observed.** `build_confirmation_text` lists only discussed topics, so the rep
hears a summary that omits the topic being recorded as skipped, then says "Save".
It is visible on screen but never spoken — and the rep is driving.

---

## Gap 11 — "/" in topic labels read aloud as "slash"

**Reproduction (live).** Use the planned topic *Contract / agreement renewal*.

**Observed.** The agent says "Contract **slash** agreement renewal" in the
readback. Cosmetic, but audible in every demo that uses that topic.

---

## Gap 12 — ADK/OpenTelemetry traceback on every disconnect

**Reproduction.** Open a session, then disconnect (close the tab or end a harness
run).

**Observed.**

```
opentelemetry.context - ERROR - Failed to detach context
ValueError: <Token var=<ContextVar name='current_context'...>> was created in a
different Context
  ... google/adk/agents/base_agent.py, line 331, in run_live → GeneratorExit
```

Library-level teardown when `run_live` is cancelled, after the session has
finished. No impact on saved data, but it appears in every log and will be seen
by anyone reviewing a dry run.

---

## Gap 13 — Continuous mic streaming

**Observed.** `Upstream audio: 15850 chunks, 4057600 bytes total` in a single
session — roughly 4 MB, about two minutes of continuous streaming. The mic
streams for as long as the page is open, not only while the rep is dictating.
Not a defect for a POC; relevant to per-rep cost and bandwidth at scale.

---

## Gap 14 — Frontend infers success by enumerating failure statuses

**Latent — not currently triggerable.**

`handleFunctionResponse` in `app/static/js/app.js` decides a commit succeeded by
checking `resp.status === "error"` and treating everything else as success. Every
refusal the backend can currently return uses `status: "error"`, so today the
behaviour is correct.

The fragility is that success is inferred from the absence of one known failure
string rather than from evidence of a write. Any refusal added later that does
not use exactly that status will fall through and display **"Saved to CRM.
Session complete."** for a record that was never written — failing in the
direction that hides data loss.

Recorded because the flows are actively being extended.

---

## Not reproduced

### Gap 15 — Orphaned staged records after a correction

**Hypothesis from code reading, not reproduced.** Each correction calls
`stage_notes` with `previous_session_id`, which creates a **new** `session_id` and
a new entry in `_STAGED_NOTES`. The prior record is left in place, is not marked
superseded, and `commit_notes` will still commit it if given that older id. A
session with two corrections therefore leaves three staged records, all
committable.

**Why not reproduced:** the agent overwrites its stored `crm_staged_session_id`
on each re-stage, so it always commits the newest, and we found no path where it
offers an older one. Demonstrating a duplicate would require driving the REST
layer directly with a retained old id, which we did not do. Whether it is
reachable through the agent is unproven. Relevant to AIML-2703.

### Gap 16 — `turn_guard` state never reset between connections

**From code reading, not reproduced.** `turn_guard` keeps four module-level dicts
keyed by `session_id` (`_TURN_COUNTS`, `_BASELINES`, `_AWAITING_READBACK`,
`_NUDGE_SENT`). Nothing clears them; the WebSocket teardown in `main.py` closes
only the `LiveRequestQueue`. Because sessions are reused by `session_id`, a
reconnect inherits the previous connection's state, so a commit could be blocked
by a readback owed on an earlier connection.

**Why not reproduced:** it requires reconnecting with the *same* `session_id`
after ending a session mid-readback. The browser generates a fresh session id per
page load and the harness generates a random one per run, so neither client
produces the condition naturally. It would need a hand-crafted client. Suspected
but unproven.

### Gap 17 — The three failure modes listed in the ticket description

The ticket lists: `topics` arriving string-splintered with missing/invalid
`disposition_code`; `commit_visit_notes` called with no staged session; and
guided tools blocked on "no new reply".

**None reproduced, and we believe all three are already handled on this branch:**

- **String-splintered `topics`** — `_normalize_topics` in `tools.py` coerces bare
  strings and partial objects into full entries, drops codes outside the
  registry, and returns a re-ask instead of raising (an exception inside a tool
  tears down the live stream). Attempts to reproduce produced a clean re-ask.
- **Commit with no staged session** — `commit_visit_notes` checks for a staged
  session id and refuses with `no_staged_notes`. Verified by calling commit
  before any staging.
- **Tools blocked on "no new reply"** — the module docstring in `turn_guard.py`
  records that an earlier version stored counters in ADK session state and always
  read a stale baseline, permanently blocking commits; it was rewritten to
  process-local dicts. We did observe `no_reply_heard` blocks during testing, but
  in every case the log showed the model calling two tools within a single turn
  with no rep utterance between them — i.e. the guard behaving correctly. See
  Gap 7 for the one case where the block is not correct.

Recommend these three rows be marked as already addressed rather than carried
forward.

---

## Suggested priority for remediation

Ranked by risk to the **Aug 17 FAR demo**:

1. **Gap 6** — guided stalls before saving. Intermittent, on the happy path, at
   the final step. Most likely to be seen live.
2. **Gap 5** — wrong, non-deterministic dispositions where the registry has no
   fitting code. Silent, and lands in the field that feeds reporting. Needs a
   product decision on the registry, not only an engineering fix.
3. **Gap 1** — incomplete records can be committed.
4. **Gap 2** — campaign rules unenforced.
5. **Gap 3 / Gap 4** — model deciding and narrating on the rep's behalf.
6. **Gap 7** — blocks all automated testing of both flows; a prerequisite for
   any repeatable verification before the demo.
7. Gaps 9–11 — conversational polish, visible in a demo.
8. Gaps 8, 12–14 — low risk, worth logging.

---

## Questions for the business

1. **The `renewals` registry has no outcome for "interested, requested a quote"**
   (Gap 5). Should Create Opportunity be available on renewals calls, or should
   there be an explicit "outcome not covered" option? This cannot be resolved in
   code — with no correct code available, any choice the agent makes is wrong.
2. **Who reviews records flagged `needs_manual_review`, and where?** The field is
   set on the record but nothing downstream consumes it.
3. **Is a skipped topic acceptable in a saved record**, or must every planned
   topic carry an outcome before a visit can be closed?
