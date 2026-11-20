# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`. Every command to run
is in this file; nothing is only in chat.

## Done

- `development` merged in (`028730b`); first review fixes (`3bc5683`); first
  replies posted.
- Agent: one run of `development` (`full-20261119-182215`) and one of the
  branch (`full-20261119-234138`).
- Second-round fixes (`15a1bb2`, pushed; 424 passed, 1 xfailed); replies on
  the two new comments posted (not resolved until Suresh's "verified").
- `extract()` re-measured: `extract-20261120-113412` (disposition 79/84 =
  94.0%, key 99 45/45, real code 34/39, over-claimed 1 of 306, 0 unconfirmed).
- The first of the two new agent runs is running in **terminal 1**.

## Now: two things at the same time, in two terminals

### Terminal 2 (open a new one) -- Step A: the two paired tables

Read-only (saved files, no model calls), so it does not disturb terminal 1.

```powershell
cd C:\Developer\sellNtell\sell-n-tell
$new = "extract-20261120-113412"
uv run python C:/tmp/disposition_paired.py --old evals/runs/extract-20261116-230453 --new evals/runs/$new
uv run python C:/tmp/disposition_paired.py --old evals/runs/extract-20261119-175710 --new evals/runs/$new
```

- The first table: `development` vs the branch now (the reviewer's before/after).
- The second: the branch before today's fixes vs now (what "sq."/"ft."/"no." did).

Send both outputs.

### Terminal 1 (the one running the agent) -- Step B: the second agent run and the export

Wait until the agent run there ends (`VERDICT: ...`, about 1.5 hours). Then
look at what terminal 1 does next:

- **It starts another `run full` by itself** (`app started ...` again): the rest
  of the earlier block is running. Do nothing until it ends at a `PS ...>`
  prompt, then run only the last part, "Step B2", below.
- **It goes back to the `PS ...>` prompt:** run Step B1, then Step B2.

Step B1 -- the second agent run (about 1.5 hours):

```powershell
uv run python -m evals.agent_eval.run full
```

Step B2 -- the baseline export from the three branch runs (seconds):

```powershell
$runs = (Get-ChildItem evals/runs -Directory -Filter "full-*" | Where-Object Name -gt "full-20261120" | Sort-Object Name).Name
$runs
uv run python -m evals.agent_eval.baseline export evals/runs/full-20261119-234138 evals/runs/$($runs[0]) evals/runs/$($runs[1]) --allow-noisy quick:disposition
git status --short
```

- `$runs` must print exactly two folder names, both from today. If not, stop
  and send the output.
- The export prints the new baseline per score. If it refuses with "too noisy
  to gate" for a score other than `quick:disposition`, stop and send the output.
- The last `git status` shows `evals/baselines/golden_v1.json` modified, plus
  the three untracked items. Do **not** commit it yet: the README's baseline
  figures change with it.

Send: both agent scorecards (verdict and tables; nothing with `--notes`),
`$runs`, the export output and `git status`. Then wait.

## After that (prepared from the numbers; no commands yet)

- The baseline commit (`golden_v1.json` + README figures), the PR
  description's results, and the reply under Suresh's reminder.
