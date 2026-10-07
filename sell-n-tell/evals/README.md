# Agent eval: regression scores for the voice agent

Runs the real app on the golden set (90 real FAR notes with expected answers)
and scores what the agent saves. Run it before merging a change to the agent's
prompt, tools or rules.

## Run it

```powershell
uv run python -m evals.agent_eval.run quick    # 18 cases (3 per vertical), about 20 minutes
uv run python -m evals.agent_eval.run full     # all 90 cases, about 1.5 hours
```

The app starts automatically if nothing is running on port 8000, and stops
afterwards. It needs the app's normal setup (`app/.env`,
`gcloud auth application-default login`).

Every run ends with a verdict and writes `evals/runs/<mode>-<time>/`:

| File | What it is |
|---|---|
| `final_scores.json` | the verdict, the scores, the comparison with the baseline, and what was run (app commit, models, dataset checksum) |
| `scorecard.md` | the same, plus every miss as expected vs actual |

| Verdict | Meaning | Exit code |
|---|---|---|
| **PASS** | no score is worse than the baseline beyond the noise limit | 0 |
| **REGRESSION** | at least one score dropped beyond it; the scorecard says which | 1 |
| **INVALID** | the run can't be trusted: too many connection errors, no baseline, or the golden set changed | 2 |

## What is scored

| Score | Meaning |
|---|---|
| event_type | Meeting / On-site visit / Phone Call, per the approved rule: a person mentioned is a Meeting, otherwise On-site visit |
| topic_status | each planned campaign correctly marked discussed or not |
| disposition | the right code for each discussed topic |
| faithfulness | the summaries say only what the rep said (checked by a judge model) |
| field_recall_* / field_invented_rate | must-capture fields captured when stated, and filled in when not (0% until the agent captures fields) |

## Why the numbers can be trusted

- **The answers are checked.** Each golden case was labelled by two models
  independently with roles swapped (96.5% agreement); answers they disagreed on
  are marked contested and never scored. The set was sent to the architect
  for review.
- **The scorer is tested.** Unit tests feed it hand-built records with known
  right and wrong answers, and a perfect record scores 100% on all 90 cases.
- **Noise is measured, not guessed.** The baseline was run 3 times. A change
  only counts when it is bigger than 3 times that score's run-to-run spread,
  and never less than 5 points.
- **Like is compared with like.** Every result records the app commit, the
  agent and judge models and the dataset checksum. The comparison is refused
  if the golden set differs from the baseline's.
- **Broken runs are not scored.** Cases that hit connection errors are
  retried once and then left out; if more than 10% fail, the run is INVALID.

Limits to keep in mind: the golden notes are written text sent as text turns,
not speech; quick mode (18 cases) only catches large drops; per-vertical
numbers rest on 15 cases each; faithfulness is judged by a model whose
agreement with a human reviewer has not been measured yet.

## Updating the baseline (when a change is accepted as the new normal)

Run `full` three times, then export the scores (numbers only) to
`evals/baselines/golden_v1.json` and commit it with the change:

```powershell
uv run python -m evals.agent_eval.baseline export evals/runs/full-A evals/runs/full-B evals/runs/full-C
```

## The golden data

`evals/v1/` holds the golden set. It contains customer notes and contact
names: internal only, and not to be copied outside the team.

## Unit tests

`uv run pytest tests/` runs the scoring tests with no model or network.
