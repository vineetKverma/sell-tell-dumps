# Voice agent eval: first baseline

What was measured: the live voice agent, run end to end on the 90 golden cases
(15 per vertical) from AIML-2898, three times. Each run creates a session,
sends the rep's note as the dictation, answers the agent's reminders, confirms,
and scores the record the agent saved against the answer key.

## Scores

| Measure | Mean of 3 runs | Range | What it checks |
|---|---|---|---|
| Event type | **59.7%** | 58.6 to 61.2% | Meeting / On-site visit / Phone Call, per the approved rule (a person: Meeting; otherwise On-site visit) |
| Topic status | **48.7%** | 47.2 to 49.6% | each planned campaign correctly marked discussed or not |
| Disposition | **72.2%** | 66.7 to 76.7% | the right code for each discussed topic |
| Summary faithfulness | **22.0%** | 19.1 to 24.1% | the summaries say only what the rep said (checked by a judge model) |
| Must-capture fields | **0%** | | not built yet; the agent has no place to record them |

Scores move 1 to 5 points between identical runs, so a change larger than
about 5 points is a real effect.

## Where the misses come from

**Topic status.** When the rep did discuss a campaign, the agent gets it right
97% of the time (84 of 87). But it marks 65% of the campaigns the rep never
mentioned as discussed (190 of 293).

**Event type.** Mix-ups in both directions: Meeting recorded as On-site visit
(46), On-site visit recorded as Meeting (31), and Phone Call chosen with no
call (23).

**Disposition.** Every miss is the agent choosing a specific code where the
key says none fits (99), mostly code 1, Create Opportunity (17 of 47). When a
real code applies, it is chosen correctly.

**Faithfulness.** Most flagged statements describe campaigns that were not
discussed, the same root cause as topic status. A few are invented reasons for
skipped topics ("ran out of time").

## Likely causes

1. The prompt tells the agent to give every planned topic an outcome, which
   conflicts with "leave out topics the rep never mentioned".
2. The agent sees only campaign titles (e.g. "2026 Q2 Hospitality Managed -
   $30 off $300"), not what the campaign is about.
3. The prompt lists the three event types without saying what each means.
4. Code 1's cue words include "interested" and "send a quote", which conflicts
   with the prompt's guidance to use 99 when nothing fits.

## Suggested next steps

- Fix 1 to 3 in the prompt and re-run the eval (about an hour per run).
- Decide whether disposition codes are needed at all; the must-capture fields
  U-04 and U-06 cover the same outcomes.
- Build must-capture field extraction (the vertical work); the eval already
  scores it.

The full scorecard, with every miss shown as expected vs actual, is available
on request. It quotes customer notes, so it stays internal.
