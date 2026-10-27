# AIML-2929 — `extract()` results, for verification

**What was measured:** the text extraction (`extract()`: one Gemini call,
fixed JSON schema) on the full golden set — 90 real FAR notes, 3 runs —
against the live agent's committed baseline (three full runs after PR #11 merged). Same answer key
(golden v1.4), same scorer and judge for both.

**Configuration:** gemini-3.8-flash, thinking = low, global endpoint.

## Results

| Measure | Live agent (baseline) | `extract()` |
|---|---|---|
| Topic status | 80.0% | **95.6%** |
| Campaigns wrongly marked discussed | 21.3% | **0%** |
| Event type | 81.0% | **92.6%** |
| Summary faithfulness | 56.3% | **91.8%** |
| Must-capture fields, P1 recall ¹ | 0% | **92.2%** |
| Must-capture fields, all recall ¹ | 0% | **93.0%** |
| Invented field values | — | **1.6%** |
| Schema or call errors (270 calls) | — | **0** |
| Cost per 1,000 notes | — | **USD 3.03** (USD 6.05 from 2027) |
| Time per note, median / 95th percentile | — | **4.5 s / 9.8 s** |

¹ Not like for like: the live agent fills no must-capture fields.

`extract-20261027-161300`: the code as it is after the PR #13 review fixes. Rules changed after that run (more filler words; "no one" and spacing in the U-10 number check; the U-02 voicemail and title rules) were re-checked on its saved records (2026-10-27): no discussed topic and no U-10 value changes, and a re-score with the final scorer gives identical figures. The settling rules only reject more, and the prompt and schema did not change, so this is exact.

The agent's 21.3% is a lower bound: an over-claim under a paraphrased label
or as duplicate rows is not counted. `extract()`'s 0% is exact (labels are
fixed to the planned titles).

Proposed go/no-go targets, all met: beats the baseline beyond noise on topic
status, event type and faithfulness; fewer wrongly-marked campaigns; P1
recall ≥ 60%; invented values ≤ 5%.

## How to verify

From the repo, branch `feature/AIML-2929-text-extraction`, where the eval runs are stored (`evals/runs/`):

```powershell
# the extract() numbers above, read from the run's own files
uv run python -m evals.extract_eval.compare evals/runs/extract-20261027-161300

# the full scorecard for that run (per vertical, per field, every miss)
Get-Content evals\runs\extract-20261027-161300\scorecard_golden.md -Encoding utf8

# reproduce it from scratch (about 15 minutes)
uv run python -m evals.extract_eval.run --model gemini-3.8-flash --allow-labelling-model --thinking low

# the agent baseline it is compared with (committed in evals/baselines/)
uv run python -m evals.agent_eval.baseline show
```

## What to keep in mind

- **Field recall is not like for like.** The live agent fills no
  must-capture fields (0% over 210 P1 items), so the recall rows show what
  `extract()` adds, not a contest between two capturing systems.
- **Prices.** USD 3.03 per 1,000 notes is the introductory rate, which ends
  2026-12-31; at the published rate from 2027 the same run costs USD 6.05.
- **Limits of the checks in code.** The evidence check proves a topic's
  quote is the rep's own words (at least two different words that are not
  filler), not that it is about the campaign: "Nothing on pools" still passes;
  that judgement is the model's, measured as over-claiming (0%). The call
  summary is not checked against the topic evidence; the faithfulness judge
  scores it. "<<<" and ">>>" inside a note are spaced out and a note over
  10,000 characters is refused, but Model Armor (S-09) is the real screen.
  Vague counts ("hundreds of beds") are kept as said.
- **The next-step rule.** `extract()` records the next step (U-09) as
  "action | owner | date", keeping the action when no owner or date is said,
  as the answer key does. Measured when it was added (`extract-20261020-174739`
  against the same configuration without it), U-09 recall rose from 25.8% to
  93.5% and P1 recall from 79.5% to 93.0%; invented values went from 1.4% to
  1.8%.
- **Event type.** The business confirmed that front desk or gatekeeper only is
  an On-site visit; the key (v1.4) and `extract()` follow it. The live agent
  keeps its earlier rule, because every wording tried in its prompt cost
  topic status and faithfulness, so about 8 cases count against it by
  design. Topic status, faithfulness and fields do not depend on this.
- **gemini-3.8-flash helped build the golden set's answers and is also the
  faithfulness judge**, so its scores may be slightly flattering.
  gemini-3.7-flash, which had no part in either, scored the same at the same
  setting in the model comparison (key v1.3).
- **Prices** are Google's published Gemini API rates (USD 0.75 / USD 3.75 per
  1M tokens until 31 Dec 2026, then double); the cost is `extract()` only.
- **The slow tail varies** between runs with identical token counts (95th
  percentile from 8.9 s to 19.4 s in earlier runs); plan for up to about 20 s.
- **Answer key v1.4**: v1.3 plus the front-desk rule (HS-007 becomes an
  On-site visit; HL-011 contested). Every changed case is listed in the
  key's manifest.

Full comparison (all models, default vs low thinking, 2.5-flash regional,
top-up and synthetic sets): `AIML-2929-model-comparison.md`.
