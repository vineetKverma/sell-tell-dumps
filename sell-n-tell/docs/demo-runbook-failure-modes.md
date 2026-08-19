# FAR demo runbook — known failure modes & agent recovery

For whoever drives the demo. Covers what can go wrong, what the agent does
about it, and what you should do. Satisfies AIML-2698 AC#4.

---

## Normal flow, so deviations are obvious

**Implicit:** rep dictates → ~2s silence auto-stops → agent reads back a summary
→ rep says "Save" → CRM record.

**Guided:** rep dictates → agent offers Save / Play back / Re-record → asks
event type → asks the outcome for each planned topic, confirming each one →
saves.

**First connect takes 6–10 seconds** while the Vertex stream opens. This is
expected. Audio is buffered, so the rep can start speaking immediately — but
there is no visual "connecting" cue, so don't fill the silence by clicking
things.

---

## F5 — Guided may stall before saving *(most likely to bite)*

**What you see:** every topic has been dispositioned, the agent says "Got it",
then goes quiet. Nothing is saved.

**Why:** the final step asks the model to make one more tool call
(`commit_guided_notes`). Sometimes it closes its turn instead. **Intermittent —
it will pass rehearsal and can still fail live.**

**Agent recovery:** none automatic in this state.

**What to do:** say anything — "Okay", "Go ahead", "Save it". It commits
immediately. Have that ready as a natural-sounding line rather than a pause.

**Status:** open. Recommended fix is to commit directly when the last topic is
dispositioned rather than asking the model for a second call.

---

## Disposition may be flagged instead of coded

**What you see:** a topic saved with no disposition code and
`needs_manual_review: true`, or code **99 — "Outcome not covered"**.

**Why:** this is correct behaviour, not a fault. If the campaign's registry has
no code that matches what actually happened, the agent flags it rather than
picking the nearest wrong one. Example: on a `renewals` call, "customer is
interested and wants a quote" has no matching code — Create Opportunity is
excluded from that campaign.

**If asked about it in the demo:** this is the system refusing to write
something false. Prior to this work it silently recorded "Order Placed" or "No
current need" at random — opposite meanings, both wrong. A flagged record gets
corrected by a human; a confidently wrong one never gets noticed.

**Note:** guided flags with a null code + `needs_manual_review`; implicit uses
code 99. Two shapes for the same idea — pending a decision to unify.

---

## Readback may be paraphrased

**What you see:** the agent summarises in its own words rather than reading the
generated confirmation verbatim, occasionally ending with "Does that sound
correct?" instead of asking about a missing topic.

**Impact:** cosmetic in most cases. If the rep answers "yes" while a planned
topic is still uncovered, the save is **blocked server-side** and the agent then
asks the right question. Costs one extra exchange; no bad data.

---

## Skipped topics are not read back

**What you see:** the rep says they didn't get to a topic; the agent records it
as not discussed but doesn't mention it in the spoken summary.

**Impact:** the rep confirms a save without hearing that the topic was recorded
as skipped. Visible on screen, not in audio. Logged as an improvement, not
fixed.

---

## Pronunciation

The agent reads "Contract / agreement renewal" aloud as **"Contract slash
agreement renewal"**. Cosmetic; avoid that topic in the demo if it will grate.

---

## Traceback in the server log on disconnect

**What you see:**

```
opentelemetry.context - ERROR - Failed to detach context
ValueError: <Token var=<ContextVar name='current_context'...>> was created in a
different Context
```

**Why:** ADK's OpenTelemetry instrumentation failing to unwind when the live
stream is cancelled — i.e. on every client disconnect, *after* the session has
finished. Library-level, not application code, and no impact on saved data.

**If showing logs to stakeholders, mention it before they spot it.**

---

## Corrections — what to expect *(AIML-2703)*

**How to correct anything:** just say it. *"Change the event type to a phone
call"*, *"That's wrong, they didn't order — the price was too high"*, *"I also
covered the contract renewal."* No keyword is required, and it works at any
point before you say Save.

**What happens:** the agent re-stages the whole record and reads back **only
what changed**, not the entire summary again. That is deliberate — a full
re-read of an eight-line record is what makes voice correction unusable.

**Adding a topic you forgot** is a correction like any other. If it was a
planned topic the coverage gate was holding the save for, supplying it releases
the block in the same turn.

**You can correct repeatedly.** Each correction supersedes the last. Only the
final version is saved.

**If a correction seems ignored:** check the record card rather than the audio.
The card is the truth; the spoken readback is a summary of it and occasionally
paraphrases.

### Draft recovered from a previous session

**What you see:** on opening the page, a record card already filled in, badged
**"draft from a previous session"**, with Save and Change greyed out.

**Why:** the browser keeps a local copy of the last staged record so a refresh
or a dropped connection doesn't lose the rep's dictation. The matching
server-side record is gone (it lives in memory), so there is nothing to commit
against — hence the disabled buttons.

**What to do:** ignore it and start dictating, or hard-refresh. It is reference
only. **Do not narrate it as a saved record** — it has no CRM record id, and
the card shows `—` for that field.

---

## What is enforced, and cannot silently go wrong

These now fail loudly rather than producing bad CRM data:

| Guard | Behaviour |
|---|---|
| Planned-topic coverage | Commit refused (`409`) until every planned topic has an outcome or an explicit skip. Agent names what's missing and asks. |
| Campaign rules | Event types and disposition codes are validated against the active campaign (`422`). Illegal values are rejected and the agent re-maps or asks. |
| Real confirmation | Commit refused unless a genuine rep reply arrived after the readback — the agent cannot answer its own question and save. |
| Skip provenance | A topic can only be marked "not discussed" after the rep was asked; the model cannot decide on their behalf. |
| Frontend truthfulness | The UI only shows "Saved to CRM" when a CRM record id actually exists. |

If a save is refused, the agent says why and asks for what it needs. **A refusal
in the demo is the system working**, and is worth narrating as such.

---

## Quick recovery cheat-sheet

| Symptom | Do this |
|---|---|
| Agent silent after all topics answered (guided) | Say "Okay" or "Save it" |
| Agent asks about a topic you already covered | Answer it again; it re-stages |
| Agent says it can't save yet | Answer the question it asks, then say "Save" |
| Nothing happens on first connect | Wait 10s before touching anything |
| Wrong event type in the readback | "Change that to a phone call" |
| Traceback in the log | Ignore — teardown noise |
