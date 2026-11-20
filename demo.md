# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`, in one terminal. Every
command to run is in this file; nothing is only in chat.

## Done

- `development` merged in (`028730b`); first review fixes (`3bc5683`); first
  replies posted.
- Second-round fixes (`15a1bb2`, pushed); replies on the two new comments
  posted (not resolved until Suresh's "verified").
- `extract()` re-measured: `extract-20261120-113412` (disposition 79/84 =
  94.0%; 26/28 by topic, p = 1.0 against `development`).
- Agent: `development` (`full-20261119-182215`) and three branch runs
  (`full-20261119-234138`, `full-20261120-113919`, `full-20261120-141514`).
- Baseline exported from the three branch runs; `evals/baselines/golden_v1.json`
  is modified on dev, not committed yet.

## Now: Step C -- the baseline commit (one terminal, a few minutes)

What goes in, in one commit:

- `evals/baselines/golden_v1.json`: already written by the export.
- `evals/README.md`: the new baseline figures (disposition 24/28 in all three
  runs, limit 5 points; every score in the verdict).
- `tests/test_agent_eval_regression.py`: the no-reply test uses placeholder
  text instead of a real note.

Paste once (a new terminal does not keep it):

```powershell
cd C:\Developer\sellNtell\sell-n-tell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
$raw = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup"
```

Then:

```powershell
git log --oneline -1
foreach ($f in "evals/README.md", "tests/test_agent_eval_regression.py") { Invoke-WebRequest "$raw/sell-n-tell/$f" -OutFile $f -UseBasicParsing }
fp evals/README.md tests/test_agent_eval_regression.py
uv run python -m evals.agent_eval.baseline show
uv run pytest tests/ -q
git status --short
```

- `git log` must show `15a1bb2`.
- `fp` must print `2a22fd0ed6ad` and `04205b8a70d9`.
- `baseline show` prints the same figures as the export, and no "not in the
  ... verdict" line.
- Tests: 424 passed, 1 xfailed, 0 failed.
- `git status --short` lists ` M` for exactly `evals/README.md`,
  `evals/baselines/golden_v1.json` and `tests/test_agent_eval_regression.py`,
  plus the three untracked items.

If all of that holds:

```powershell
git add evals/baselines/golden_v1.json evals/README.md tests/test_agent_eval_regression.py
git commit -m "AIML-3152: agent baseline re-taken after the review fixes; placeholder text in a test"
git push
git log --oneline -2
```

Send the output and wait.

## After that (prepared from the numbers; no commands)

- The PR description's results and the reply under Suresh's reminder: text to
  paste, given here after the push.
