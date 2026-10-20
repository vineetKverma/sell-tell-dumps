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
`gcloud auth application-default login`) in both modes: the summary judge
calls Vertex. And it needs the golden data, which is not in the repo (see
[The golden data](#the-golden-data)).

The harness follows the app's contract: `POST /api/sessions` seeds
`planned_topics` and `campaign_type`, and the WebSocket takes only the ids
in the path (`/ws/{user_id}/{session_id}`, no query parameters).

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
| event_type | Meeting / On-site visit / Phone Call: a call is a Phone Call; a business conversation with a customer contact (the decision maker or another contact such as a manager) is a Meeting; otherwise On-site visit, including front desk or gatekeeper only |
| topic_status | each planned campaign correctly marked discussed or not |
| disposition | the right code for each discussed topic |
| faithfulness | the summaries say only what the rep said (checked by a judge model) |
| field_recall_* / field_invented_rate | must-capture fields captured when stated, and filled in when not (0% until the agent captures fields) |

Event type is scored against the business's rule (the answer key, v1.4).
The agent's prompt keeps its earlier rule -- "a person they met or spoke
with, by name or by role" is a Meeting -- because every wording of the
business rule tried in the prompt cost topic status and faithfulness. So
about 8 golden cases count against the agent by design: 7 where the rep
interacted with someone not named (the key says Meeting), and one where the
rep spoke only to the front desk (the key says On-site visit). AIML-2929
adds `extract()`, which follows the business rule.

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
  retried once and then left out; if more than 10% fail, or the run stopped
  before every case ran, the run is INVALID.
- **A too-noisy score leaves the verdict only on purpose.** A score whose noise
  limit is above 20 points can't catch anything, but it is never dropped
  silently: `baseline export` refuses it unless it is named with
  `--allow-noisy`, the baseline records it, and every run lists it under "not
  in the verdict" (in `final_scores.json`, the scorecard header and the
  console). Today that is faithfulness in quick mode (one summary moves it 6
  points). Quick-mode disposition stays in the verdict because the baseline's
  three runs happened to agree, but it rests on about 9 topics, so one topic
  moves it 11 points: confirm a quick-mode disposition REGRESSION with a full
  run. Full mode judges both.

Limits to keep in mind: the golden notes are written text sent as text turns,
not speech; quick mode (18 cases) only catches large drops, and leaves out
of its verdict whatever the baseline records as too noisy there (today
faithfulness; field scores are compared, at 0% until the agent captures
fields); per-vertical
numbers rest on 15 cases each; faithfulness is judged by a model whose
agreement with a human reviewer has not been measured yet.

## The same eval on ADK's framework (`adk eval`)

`evals/adk_eval/` runs the golden set through ADK's own evaluation service
instead of the app's WebSocket. Our scores are registered as ADK custom
metrics, and ADK's built-in judge (`rubric_based_tool_use_quality_v1`) checks
the summaries against rubrics. It needs ADK's live evaluation, which the
pinned version (2.10.0, with `[eval]` in the dev group) has:

```powershell
uv run python -m evals.adk_eval.run quick
```

It loads the agent in-process (no app needed) and writes
`evals/runs/adk-<mode>-<time>/summary.json`. This is where audio-based testing
will go later; the WebSocket run above stays the regression gate.

## Updating the baseline (when a change is accepted as the new normal)

Run `full` three times, then export the scores (numbers only) to
`evals/baselines/golden_v1.json` and commit it with the change:

```powershell
uv run python -m evals.agent_eval.baseline export evals/runs/full-A evals/runs/full-B evals/runs/full-C --allow-noisy quick:disposition --allow-noisy quick:faithfulness
```

If the export names another score as too noisy, add more runs first; pass
`--allow-noisy mode:metric` for it only as a deliberate choice.

## The golden data

The golden set contains customer notes and contact names, so it is not in the
repo. It lives in the access-controlled bucket `gs://sellntell-eval-np`
(project `prj-hds-np-data`; versioned; access limited to the eval team and
CI). Fetch the folder, then either place it at `evals/v1/` (git-ignored) or
point `SELLNTELL_EVAL_DATA` at it:

```powershell
New-Item -ItemType Directory -Force evals/v1 | Out-Null   # gcloud needs the folder to exist
gcloud storage cp "gs://sellntell-eval-np/golden_v1.4/*" evals/v1/
```

`golden_v1.4` is the answer key the committed baseline was made on; with any
other version a run ends INVALID ("the golden set differs from the one the
baseline was made on").

The folder holds `golden_v1.evalset.json`, `universal_fields.csv` and
`vertical_fields.csv`. Do not copy it anywhere else. Without it, `run` stops
with a message saying where it looked, and the data-dependent unit tests skip.

## Unit tests

`uv run pytest tests/` runs the scoring tests with no model or network.

The tests that need the golden data -- including "a perfect record scores 100%
on all 90 cases", the 90- and 18-case checks and the field priorities -- run
only where the data has been fetched (above). Elsewhere, including CI today,
they skip; fetch the data before relying on a green run.
