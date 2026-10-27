# AIML-2929 — `extract()`: quality, cost and latency by model

The text extraction (`extract()`: one Gemini call, fixed JSON schema) scored on
the full golden set — 90 real FAR notes, 3 runs each (270 extractions per
row) — against the live agent's baseline. All rows use the same answer key
(golden **v1.3**: event types per the approved rule, contact outcome filled
where the note shows a conversation — see "The rule for must-capture
fields"), the same prompt, schema and campaign descriptions.

## Final result (answer key v1.4)

The tables after this section chose the model and thinking level (key v1.3,
13 October). Since then: the business confirmed the event-type rule (front
desk or gatekeeper only is an On-site visit; key v1.4), `extract()` follows
it, and a rule for the next step (U-09) was added. The chosen configuration,
re-run on key v1.4, against the live agent's committed baseline (three full runs after PR #11 merged):

| Measure (mean of 3 runs) | Live agent | `extract()` |
|---|---|---|
| Event type | 81.0% | **92.6%** |
| Topic status | 80.0% | **95.6%** |
| Campaigns wrongly marked discussed | 21.3% | **0%** |
| Faithfulness | 56.3% | **91.8%** |
| P1 field recall ¹ | 0% | **92.2%** |
| All-field recall ¹ | 0% | **93.0%** |
| Invented field values | — | **1.6%** |
| Schema or call errors | — | **0** of 270 |
| Cost per 1,000 notes | — | **USD 3.03** (USD 6.05 from 2027) |
| Time per note, median / p95 | — | **4.5 s / 9.8 s** |

¹ Not like for like: the live agent fills no must-capture fields.

gemini-3.8-flash, thinking low, global endpoint (`extract-20261027-161300`, the
code after the PR #13 review fixes; before them, `extract-20261020-174739`
measured 93.8 / 95.4 / 91.1 / 93.0 on the same rows, within run-to-run variation).
The agent row is the committed baseline: three full runs of the code as
merged (disposition 67.8%; over-claim 20.0–23.0% across the runs).

**The next-step rule** tells `extract()` to record the next step as
"action | owner | date", keeping the action when no owner or date is said,
the way the answer key does. Measured against the same configuration
without it (`extract-20261014-220710`): U-09 recall 25.8% → 93.5%, P1 recall
79.5% → 93.0%, all-field recall 81.5% → 93.7%; invented values 1.4% → 1.8%;
every other score within noise.

## Summary

- Every configuration beats the live agent on event type, topic status,
  over-claiming, faithfulness and field recall, by far more than the
  run-to-run noise. The invented-value rate is 0.4–2.8%; the agent has no
  figure to compare, since it captures no fields.
- **Low thinking is the setting to use**: about 3× faster and a third to half
  the cost of the default, with every score still well above the agent.
- **At low thinking, 3.8-flash and 3.7-flash are equivalent** — differences
  are about 1 point, within run-to-run spread — at the same price and speed.
- **2.5-flash** is the only regional option (all 3.x models are served on the
  global endpoint only in our project). It is close on quality but slower
  than the 3.x models at low thinking, and the only one that over-claims.

## Quality (mean of 3 runs; agent = the committed baseline)

| Run | Event type | Topic status | Over-claimed | Faithfulness | P1 field recall | All-field recall | Invented values |
|---|---|---|---|---|---|---|---|
| **Live agent (baseline)** | 80.5% | 75.4% | 27.3% | 52.6% | 0% | 0% | — |
| 3.8-flash, default thinking ¹ | 96.9% | 95.4% | 0% | 91.5% ² | 57.1% | 60.7% | 0.4% |
| **3.8-flash, low thinking** ¹ | 93.9% | 94.9% | 0% | 93.3% ² | 79.6% | 81.5% | 1.6% |
| 3.7-flash, default thinking | 96.5% | 96.2% | 0% | 90.0% | 72.2% | 74.5% | 1.1% |
| **3.7-flash, low thinking** | 94.2% | 93.8% | 0% | 90.2% | 80.2% | 82.0% | 1.7% |
| 2.5-flash, default (us-east1) | 91.6% | 92.3% | 2.0% | 88.5% | 77.8% | 79.9% | 2.8% |

The agent's over-claimed figure is a lower bound: it counts only a campaign
marked discussed under its exact planned label, so an over-claim under a
paraphrased label or as duplicate rows is not counted. `extract()` can
produce neither (labels are fixed to the planned titles, duplicates are
merged), so its figures are exact.

On key v1.2 (before the contact-outcome fix) field recall was about 1–3
points higher and invented values about 1 point higher in every row: the 21
added "spoke with contact" values turn the model's "spoke with…" answers
from invented into correct, and count as misses where it left U-02 blank.

Noise limits on the baseline (a change must exceed these to count): event
type ±5.0, topic status ±10.6, over-claimed ±12.1, faithfulness ±6.0.
Schema errors and dropped topic labels: 0 in every run. Campaigns left
"unconfirmed" (the live flow would ask the rep): 0–0.7 per run of 90 notes
for 3.x, 2.0 for 2.5-flash.

¹ gemini-3.8-flash was one of the two models that built the golden set's
answers, so its scores may be slightly flattering. 3.7-flash, which had no
part in it, scoring the same at low thinking suggests the effect is small.
² The faithfulness judge is gemini-3.8-flash for every row, so the 3.8-flash
rows were judged by the same model that wrote the summaries.

## Cost

Per note, from the tokens each call actually used (`usage_metadata`, averaged
over 270 calls) × the published price. Thinking tokens are billed as output.

| Run | Input tokens / note | Output tokens / note | USD per 1,000 notes (now) | USD per 100,000 notes (now) | USD per 1,000 notes (from 2027) | Output share of cost |
|---|---|---|---|---|---|---|
| 3.8-flash, default thinking | 2,083 | 2,176 | USD 9.72 | USD 972 | USD 19.44 | 84% |
| **3.8-flash, low thinking** | 2,083 | 365 | **USD 2.93** | **USD 293** | **USD 5.86** | 47% |
| 3.7-flash, default thinking | 2,083 | 1,182 | USD 5.99 | USD 599 | USD 11.99 | 74% |
| **3.7-flash, low thinking** | 2,083 | 375 | **USD 2.97** | **USD 297** | **USD 5.93** | 47% |
| 2.5-flash, default (us-east1) | 1,583 | 1,370 | USD 3.90 | USD 390 | USD 3.90 | 88% |

Prices used (USD per 1M tokens, input / output):

| Model | Now | From 1 Jan 2027 | Source |
|---|---|---|---|
| gemini-3.8-flash | USD 0.75 / USD 3.75 | USD 1.50 / USD 7.50 | Google Gemini API pricing page, standard paid tier (introductory price until 31 Dec 2026); confirmed twice |
| gemini-3.7-flash | USD 0.75 / USD 3.75 | USD 1.50 / USD 7.50 | **Unconfirmed**: third-party listings; not on Google's page |
| gemini-2.5-flash | USD 0.30 / USD 2.50 | same | Google Gemini API pricing page; USD 0.30 is the text rate (audio USD 1.00) — `extract()` sends text only |

How the figures were checked: every row was recomputed independently from
the measured tokens and the prices above; each matches the run's scorecard to
the cent (3.7-flash low, from 2027: USD 5.94 recomputed vs USD 5.93 on the
scorecard — rounding of the per-note averages; the table shows the run's own
figure). Every figure in the quality, cost and latency tables was then
checked against `evals.extract_eval.compare` output, read from the runs' own
files (`evals/runs/`): all match, all five runs scored on key v1.3.

## Latency (per extraction call)

| Run | Median | 95th percentile |
|---|---|---|
| 3.8-flash, default thinking | 13.5 s | 37.7 s |
| **3.8-flash, low thinking** | **3.8 s** | **8.9 s** |
| 3.7-flash, default thinking | 10.7 s | 16.2 s |
| **3.7-flash, low thinking** | **3.9 s** | **7.8 s** |
| 2.5-flash, default (us-east1) | 8.1 s | 14.2 s |

In the live flow the rep waits for this after dictating, so the median and
the slow tail both matter.

## What the numbers cover — and what they don't

- **Cost is `extract()` only.** It excludes the faithfulness judge (an eval
  cost, not a production one) and Gemini Live (the voice), which is unchanged
  by this decision.
- **Prices are the Gemini API's published rates.** Calls go through Vertex AI,
  which normally charges the same; confirm on the Vertex AI pricing page
  before quoting costs outside the team. The 3.x price doubles on 1 Jan 2027.
- **Latency was measured from a developer workstation on the global endpoint (3.x)
  and us-east1 (2.5), 8 calls in parallel.** Production latency, from Cloud
  Run in us-central1 with one call per conversation, may differ; the relative
  order between rows is the useful part.
- **Answer key v1.3** = v1.2 (17 event types corrected to the approved rule
  as written, "any interaction is a Meeting"; since confirmed with the
  front-desk exception, which is key v1.4)
  plus U-02 "spoke with contact" on 21 cases. The agent baseline was
  re-scored on the same key (unchanged: it captures no fields), so the
  comparison is like for like. Every run was re-scored, not re-run.
- **Event type: the agent keeps its earlier rule by design.** The business
  confirmed (Tobi, for Jeremy, 14 October) that front desk or gatekeeper only
  is an On-site visit; key v1.4 and `extract()` follow it. Every wording of
  that rule tried in the agent's prompt cost it topic status and
  faithfulness (three wordings, six runs, a control run), so the agent keeps
  "a person by name or by role", and about 8 cases count against it: the 7
  with nobody named (HL-010, HL-015, HS-003, IN-009, IN-015, MH-006, TR-007)
  and one front-desk visit (HS-007). The result does not rest on event type:
  topic status, over-claiming, faithfulness and fields do not depend on it.
- **The evidence check was tightened after these runs** (review finding:
  loose fragments such as "a ... e ... i" passed, in any order). It then
  needed whole words, at least 4 letters or digits per fragment, in the order
  they appear in the note; since the PR #13 review it also needs at least two
  different words that are not filler, and an unconfirmed topic keeps no
  summary. Over-claiming was 0% in every 3.x run, so the old
  check was not what kept it there. **Confirmed by a re-run of the chosen
  configuration with the stricter check** (`extract-20261013-200024`, 3
  runs): topic status 95.6% (was 94.9%), over-claimed 0%, unconfirmed 0.3
  per run (was 0.7), event type 94.6%, faithfulness 93.0%, P1 recall 79.2%,
  invented 1.4%, USD 2.92 per 1,000 notes — all within run-to-run variation of
  the table above, which is left as measured.
- **The slow tail varies between runs.** The same configuration and token
  counts gave a 95th percentile of 8.9 s in one run and 19.4 s in the next
  (medians 3.8 s and 4.6 s). Plan for a tail of up to about 20 s.
- **Top-up and synthetic sets** still carry the v1.1 key (event type and
  U-02 not yet reviewed — AIML-2929's AC2 covers the golden set only): their
  numbers are reported separately below with that caveat.
- **Low is the lowest thinking level for 3.8-flash.** `minimal` is rejected
  by the API ("400 INVALID_ARGUMENT: Thinking level is unsupported:
  THINKING_LEVEL_MINIMAL"); those runs made no extractions and are not
  counted.

## Top-up and synthetic sets (3.8-flash, low thinking)

Notes chosen for their field examples (65 real; 5 written for HS-08/HS-09).
Key still v1.1, so event type is not meaningful here and invented values
include the U-02 / IS-05 disagreement described below. Quality figures are
from the **last of the 3 runs** (the scorecard's tables), not the mean; cost
and latency cover all 3 runs. 0 schema errors, 0 dropped labels, 0
unconfirmed topics on both sets.

| Set | Topic status | Over-claimed | Faithfulness | All-field recall | P1 recall | Invented (P1) | USD / 1,000 notes | Median / p95 |
|---|---|---|---|---|---|---|---|---|
| Top-up (65) | 89.9% | 0% | 84.6% | 88.4% | 87.0% | 5.0% | USD 3.14 | 4.6 s / 9.8 s |
| Synthetic (5) | 2 of 5 | — | 5 of 5 | 90.5% | 86.7% | 9.3% (1–2 values) | USD 2.94 | 4.3 s / 19.8 s |

## The rule for must-capture fields

**A field is filled when the note clearly shows it, and left blank when
filling it would be a guess.** Decided from what we already have, not asked:

- The must-capture sheet makes contact outcome (U-02) a Priority-1 field,
  "capture on every call" (spoke with target / alternate / no contact). Reps
  never write "I spoke with the target"; they write "Rachel said…". The field
  can only mean what the note shows.
- The approved event-type rule judges by what happened, not exact words
  ("mentions interacting with a person → Meeting").
- The answer key had been stricter — a verbatim quote for every value — but
  that was our own labelling instruction, not a business requirement.

Applied: in the key, U-02 becomes "spoke with contact" where the rep
interacted with someone (21 golden cases, each read); target vs alternate
usually can't be told from a note, so the scorer accepts either against it.
In `extract()`, a count field (U-10) with no number in it ("turns") is
dropped. On the top-up set, most "invented values" were this disagreement:
U-02 (37 of at least 85 across 3 runs) and authority scope IS-05 ("orders for most
locations"), whose values come straight from the notes. Jeremy can overrule
the rule; it would mean a re-score, not a re-run.

## Open decisions

1. **Global endpoint** — **approved**: the dictation text may be processed
   on Gemini's global endpoint (all 3.x models require it in our project).
2. **Model and thinking level** — **3.8-flash at low thinking**, on the global
   endpoint (Suresh's preference for the newer model; equal to 3.7-flash on
   quality, speed and cost). 2.5-flash stays on record as the regional option.
   AIML-2929 asks for a model other than the two that labelled the golden
   set: that measurement is 3.7-flash (equal to the chosen 3.8-flash at low
   thinking), so the 3.8-flash numbers are not resting on self-agreement.
3. **Go/no-go targets** — proposed: beat the baseline beyond noise on topic
   status, event type and faithfulness, fewer over-claims, P1 field recall
   ≥ 60%, invented-value rate ≤ 5%. Every configuration meets them **except
   3.8-flash at default thinking, whose P1 recall is 57.1%**; the chosen
   configuration (3.8-flash low: 79.6%, 1.6%) meets all of them.
4. **Event-type rule** — **confirmed** by the business (14 October): front
   desk or gatekeeper only is an On-site visit. In key v1.4 and `extract()`;
   the live agent keeps its earlier rule (see "What the numbers cover").

## Runs

| Run | Folder (`evals/runs/`) |
|---|---|
| Agent baseline after PR #11 (key v1.4) | `full-20261020-212704`, `full-20261021-004113`, `full-20261022-134511` (re-scored) |
| 3.8-flash, low — key v1.4, after the PR #13 review fixes (final) | `extract-20261027-161300` |
| 3.8-flash, low — key v1.4, a stricter evidence rule tried and dropped (three words, no label-only quotes) | `extract-20261027-151522` |
| 3.8-flash, low — key v1.4, with the next-step rule | `extract-20261020-174739` |
| 3.8-flash, low — key v1.4, before the next-step rule | `extract-20261014-220710` |
| Agent baseline used in the tables below (3 runs, re-scored on v1.3) | `full-20261008-212950`, `full-20261008-232134`, `full-20261009-210636` |
| 3.8-flash, default | `extract-20261012-220905` |
| 3.7-flash, default | `extract-20261012-222552` |
| 3.7-flash, low | `extract-20261012-224318` |
| 3.8-flash, low | `extract-20261012-225347` |
| 2.5-flash, default (us-east1) | `extract-20261012-230115` |
| 3.8-flash, low — re-run with the stricter evidence check | `extract-20261013-200024` |
| 3.8-flash, low — top-up + synthetic sets | `extract-20261012-231609` |
| 3.8-flash, minimal (rejected by the API, not counted) | `extract-20261012-225959`, `extract-20261012-231026` |

Key versions in `gs://sellntell-eval-np/`: `golden_v1/` (v1.1, as labelled),
`golden_v1.2/`, `golden_v1.3/`, `golden_v1.4/` (in use: front-desk rule);
each with a manifest of what changed.

Commands: `uv run python -m evals.extract_eval.run --model <model> [--thinking low] [--location us-east1] [--allow-labelling-model]`.
The quality, cost and latency tables can be regenerated from the runs'
own files: `uv run python -m evals.extract_eval.compare evals/runs/<folder> ...`.
