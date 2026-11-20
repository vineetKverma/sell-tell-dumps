# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`. Do the steps in order;
do not start a step until the one before it is confirmed.

Done: `development` merged in (`028730b`), the first review fixes (`3bc5683`),
the first replies, one agent run of `development` (`full-20261119-182215`)
and one of the branch (`full-20261119-234138`).

The second review round asks for:

- **Step 1:** two `extract()` fixes (glued sentence numbers in summaries;
  "sq.", "ft.", "no." splitting a fact), the tests, the commit and the push;
- **Step 2:** the replies on those two comments;
- **Step 3:** the measurements after every fix: `extract()` once more, and the
  agent baseline re-taken (two more branch runs, plus `full-20261119-234138`);
- then the PR description's results and the reply on the reminder.

## Before anything: the `fp` function and the download address

Paste once in the terminal (again in every new terminal):

```powershell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
$raw = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup"
```

## Step 1 -- the two fixes: three files, the tests, a check, the commit and the push

What changes:

- In a summary and `executive_summary` (the model's own text) every bracketed
  number is removed, glued to a word or not ("shared[1]", "asked [7]"). In a
  field (the rep's values) the rule stays as it was, so "PO [1234567]" and
  "Qty [10-12] units" keep their numbers.
- No sentence split after "sq." or "ft.", nor after "no." when a number
  follows ("PO no. 4567"); a bare "No." still ends a sentence.
- The README says so.

```powershell
git log --oneline -1
foreach ($f in "app/extraction/extract.py", "tests/test_extraction.py", "evals/README.md") { Invoke-WebRequest "$raw/sell-n-tell/$f" -OutFile $f -UseBasicParsing }
Invoke-WebRequest "$raw/tools/split_check.py" -OutFile C:\tmp\split_check.py -UseBasicParsing
fp app/extraction/extract.py tests/test_extraction.py evals/README.md C:\tmp\split_check.py
uv run pytest tests/ -q
uv run python C:\tmp\split_check.py extract-20261119-175710
git status --short
```

- `git log` must show `3bc5683`.
- `fp` must print `363aff2451cc`, `00e5228cf7c2`, `3174e1833168`, `682eb21fa653`.
- Tests: 424 passed, 1 xfailed, 0 failed.
- `split_check` prints ids and counts only: how many golden notes now split
  differently, and how many saved summaries of the last run still hold a
  bracketed number (those the new rule removes). Any number is fine here; it
  goes into the reply.
- `git status --short` lists ` M` for exactly these three files, plus the two
  untracked items.

If the tests pass:

```powershell
git add app/extraction/extract.py tests/test_extraction.py evals/README.md
git commit -m "AIML-3152: review fixes: citations in summaries, sq./ft./no. abbreviations"
git push
git log --oneline -2
```

Send the output and wait.

## Step 2 -- the replies on the two new comments (after the push)

Under "Medium: the fix introduces a regression for the usual citation shape":

```text
Fixed as suggested: summaries and executive_summary drop every bracketed number (glued or out of range); fields keep the conservative rule, so "PO [1234567]" and "Qty [10-12] units" stay. The leak test now has the glued and out-of-range cases.
```

Under "Low: the abbreviation list misses forms common in pool, hospitality and trades dictation":

```text
Fixed: no split after "sq." or "ft.", and after "no." only when no number follows, so a bare "No." stays a sentence; "Inc." and "St." left as they are. Tests cover both examples.
```

Do not resolve them yet: wait for Suresh's "verified".

## Step 3 -- the measurements after every fix (about 3.5 hours, unattended)

`extract()` once more (minutes), then two full agent runs of the branch
(about 1.5 hours each), then the baseline re-export from the three branch runs.
The two fixes change only `extract()`, which the agent does not use, so
`full-20261119-234138` counts as the first of the three.

```powershell
git log --oneline -1
git status --short
uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
$new = (Get-ChildItem evals\runs -Directory -Filter "extract-*" | Sort-Object Name | Select-Object -Last 1).Name
$new
uv run python -m evals.extract_eval.compare evals/runs/extract-20261116-230453 evals/runs/extract-20261119-175710 evals/runs/$new
uv run python C:\tmp\disposition_paired.py --old evals\runs\extract-20261116-230453 --new evals\runs\$new
uv run python C:\tmp\overclaim_units.py extract-20261119-175710 $new
uv run python -m evals.agent_eval.run full
$b2 = (Get-ChildItem evals\runs -Directory -Filter "full-*" | Sort-Object CreationTime | Select-Object -Last 1).Name
uv run python -m evals.agent_eval.run full
$b3 = (Get-ChildItem evals\runs -Directory -Filter "full-*" | Sort-Object CreationTime | Select-Object -Last 1).Name
$b2; $b3
uv run python -m evals.agent_eval.baseline export evals/runs/full-20261119-234138 evals/runs/$b2 evals/runs/$b3 --allow-noisy quick:disposition
git status --short
```

- `git log` shows the Step 1 commit; `git status` (first) shows only the two
  untracked items.
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
