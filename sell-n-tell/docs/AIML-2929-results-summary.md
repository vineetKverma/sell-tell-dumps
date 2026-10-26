# AIML-2929 — `extract()` results, for verification

**What was measured:** the text extraction (`extract()`: one Gemini call,
fixed JSON schema) on the full golden set — 90 real FAR notes, 3 runs —
against the live agent's committed baseline (three full runs after PR #11 merged). Same answer key
(golden v1.4), same scorer and judge for both.

**Configuration:** gemini-3.8-flash, thinking = low, global endpoint.

## Results

| Measure | Live agent (baseline) | `extract()` |
|---|---|---|
| Topic status | 80.0% | **95.4%** |
| Campaigns wrongly marked discussed | 21.3% | **0%** |
| Event type | 81.0% | **93.8%** |
| Summary faithfulness | 56.3% | **91.1%** |
| Must-capture fields, P1 recall | 0% | **93.0%** |
| Must-capture fields, all recall | 0% | **93.7%** |
| Invented field values | — | **1.8%** |
| Schema or call errors (270 calls) | — | **0** |
| Cost per 1,000 notes | — | **USD 3.03** (USD 6.05 from 2027) |
| Time per note, median / 95th percentile | — | **4.2 s / 11.4 s** |

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
uv run python -m evals.extract_eval.compare evals/runs/extract-20261020-174739

# the full scorecard for that run (per vertical, per field, every miss)
Get-Content evals\runs\extract-20261020-174739\scorecard_golden.md -Encoding utf8

# reproduce it from scratch (about 15 minutes)
uv run python -m evals.extract_eval.run --model gemini-3.8-flash --allow-labelling-model --thinking low

# the agent baseline it is compared with (committed in evals/baselines/)
uv run python -m evals.agent_eval.baseline show
```

## What to keep in mind

- **The next-step rule.** `extract()` records the next step (U-09) as
  "action | owner | date", keeping the action when no owner or date is said,
  as the answer key does. Against the same configuration without it, U-09
  recall rose from 25.8% to 93.5% and P1 recall from 79.5% to 93.0%;
  invented values went from 1.4% to 1.8%.
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
