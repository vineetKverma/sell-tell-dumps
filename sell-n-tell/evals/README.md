# Agent eval: regression scores for the voice agent

Runs the real app on the golden set (90 real FAR notes with expected answers)
and scores what the agent saves. Run it before and after a change to the
agent's prompt, tools or rules to see whether the scores moved.

## Quick start

```powershell
# fast check, 18 cases (about 20 minutes); starts and stops the app for you
uv run python -m evals.agent_eval.run --name my-change --quick --start-app

# full check, 90 cases (about 1.5 hours per repeat)
uv run python -m evals.agent_eval.run --name my-change --start-app
```

The scorecard is written to `evals/runs/<name>/scorecard.md` and printed. It
shows each score against the committed baseline:

| metric | baseline | this run | change | verdict |
|---|---|---|---|---|
| event_type | 59.7% | 71.2% | +11.5 | improved |
| topic_status | 48.7% | 47.9% | -0.8 | same (within noise) |

A score worse than the baseline by more than 5 points is a **REGRESSION**
(the run-to-run spread is 1 to 5 points, so smaller moves are noise). Add
`--fail-on-regression` to make the command exit with code 1 in that case.

## What it needs

- The app's normal setup (`app/.env`, `gcloud auth application-default login`).
  The run uses the same Vertex project as the app.
- The golden data folder. It holds customer notes, so it is not in the repo:
  get it from the team and either put it at `evals/v1/` (git-ignored) or set
  `SELLNTELL_EVAL_DATA` to its folder.

Without `--start-app`, start the app yourself first
(`uv run uvicorn app.main:app --port 8000`) and the harness uses it.

## What is scored

| Score | Meaning |
|---|---|
| event_type | Meeting / On-site visit / Phone Call, per the approved rule: a person mentioned is a Meeting, otherwise On-site visit |
| topic_status | each planned campaign correctly marked discussed or not |
| disposition | the right code for each discussed topic |
| faithfulness | the summaries say only what the rep said (needs `--judge`, which makes extra Gemini calls) |
| field_recall_* / field_invented_rate | must-capture fields captured when stated, and filled in when not stated (0% until the agent captures fields) |

Every miss is listed in the scorecard as expected vs actual.

## Other options

| Option | Use |
|---|---|
| `--repeat 3` | run the set 3 times to see the spread (use for a new baseline) |
| `--judge` | also score summary faithfulness |
| `--cases HL-001,MH-004` | run a few named cases while debugging |
| `--retry-errors evals/runs/<name>` | re-run only cases that hit a connection error |
| `--rescore evals/runs/<name>` | re-score a saved run without running the agent again |
| `python -m evals.agent_eval.diagnose evals/runs/<name>` | break the misses into patterns (counts only) |

## Updating the baseline

When a change is accepted as the new normal, record it:

```powershell
uv run python -m evals.agent_eval.run --name new-baseline --repeat 3 --judge --start-app
uv run python -m evals.agent_eval.baseline export evals/runs/new-baseline
```

That rewrites `evals/baselines/golden_v1.json`: aggregate numbers only, no
notes or names, so it is committed with the change.

## Unit tests

`uv run pytest tests/` runs the harness's scoring tests with no model or
network. Tests that need the golden data skip when it is not present.
