# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`. Do the steps in order;
do not start a step until the one before it is confirmed.

Done: `development` merged in (`028730b`), the first review fixes (`3bc5683`),
the first replies, one agent run of `development` (`full-20261119-182215`)
and one of the branch (`full-20261119-234138`), and the second-round fixes
(`15a1bb2`, pushed: citations out of summaries, "sq.", "ft.", "no."; 424
passed, 1 xfailed; 1 of 90 golden notes splits differently, 0 of 355 saved
summaries held a bracketed number), and the replies on the two new comments
(posted; not resolved until Suresh's "verified").

`extract()` re-measured: `extract-20261120-113412` (disposition 79/84 = 94.0%,
key 99 45/45, real code 34/39; over-claimed 1 of 306; 0 unconfirmed). The two
paired tables are re-run separately (the path broke in the paste).

Left:

- **Step 3:** the measurements after every fix: `extract()` once more, and the
  agent baseline re-taken (two more branch runs, plus `full-20261119-234138`);
- then the PR description's results and the reply on the reminder.

## Before anything: the `fp` function and the download address

Paste once in the terminal (again in every new terminal):

```powershell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
$raw = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup"
```

## Step 3 -- the measurements after every fix (about 3.5 hours, unattended)

`extract()` once more (minutes), then two full agent runs of the branch
(about 1.5 hours each), then the baseline re-export from the three branch runs.
The two fixes change only `extract()`, which the agent does not use, so
`full-20261119-234138` counts as the first of the three.

```powershell
git log --oneline -1
git status --short
uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
$new = (Get-ChildItem evals/runs -Directory -Filter "extract-*" | Sort-Object Name | Select-Object -Last 1).Name
$new
uv run python -m evals.extract_eval.compare evals/runs/extract-20261116-230453 evals/runs/extract-20261119-175710 evals/runs/$new
uv run python C:/tmp/disposition_paired.py --old evals/runs/extract-20261116-230453 --new evals/runs/$new
uv run python C:/tmp/overclaim_units.py extract-20261119-175710 $new
uv run python -m evals.agent_eval.run full
$b2 = (Get-ChildItem evals/runs -Directory -Filter "full-*" | Sort-Object CreationTime | Select-Object -Last 1).Name
uv run python -m evals.agent_eval.run full
$b3 = (Get-ChildItem evals/runs -Directory -Filter "full-*" | Sort-Object CreationTime | Select-Object -Last 1).Name
$b2; $b3
uv run python -m evals.agent_eval.baseline export evals/runs/full-20261119-234138 evals/runs/$b2 evals/runs/$b3 --allow-noisy quick:disposition
git status --short
```

- `git log` shows `15a1bb2`; `git status` (first) shows only the three
  untracked items (`demo.md`, `evals/dataset/`,
  `tests/test_dataset_fix_left_material.py`).
- The three `extract()` runs in the compare are `development`, the branch
  after the first fixes, and the branch now.
- `$b2` and `$b3` must be two different folders from today.
- The export prints the new baseline per score. If it refuses with "too noisy
  to gate" for a score other than `quick:disposition`, stop there and send the
  output.
- The last `git status` shows `evals/baselines/golden_v1.json` modified. Do
  not commit it yet: the README's baseline figures change with it.

Send the output (the scorecard tables and verdicts are enough from the agent
runs; nothing with `--notes`) and wait.
