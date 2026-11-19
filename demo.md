# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`. Do the steps in order;
do not start a step until the one before it is confirmed.

This round answers the review on the pull request:

1. bring `development` into the branch (the PR is 8 commits behind);
2. run the agent on `development` (the "before" the reviewer asked for);
3. the review fixes;
4. `extract()` again;
5. the agent on the branch, for the new baseline;
6. the commit, the PR text and the replies (written once the numbers are in).

## Before anything: the `fp` function and the download address

Paste these two lines once in the terminal (again in every new terminal):

```powershell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
$raw = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup"
```

Step 1 is done: `development` (at `c5b76c3`) adds AIML-3012, the confirmation
classifier: 14 files, none of them a file this PR changes.

## Step 2 -- bring `development` into the branch

```powershell
git merge --no-edit origin/development
git status --short
fp app/extraction/extract.py tests/test_extraction.py tests/test_prompt_rules.py evals/README.md app/voice_notes_agent/resources/behavioral_rules.yaml
uv run pytest tests/ -q
```

- If the merge reports a conflict, stop and send the output. Do not fix it by hand.
- `fp` must still print `3068a1c48c33`, `c4bd3d9b8a30`, `edc8efc167e8`,
  `383af0f09a08`, `ae5f8814aac0` (the merge left this PR's files as they were).
- Tests: more than 347 passed (AIML-3012 adds two test files), 1 xfailed, 0 failed.

If both are fine:

```powershell
git push
git log --oneline -3
```

Then put the files `development` changed into one file for the local machine:

```powershell
Invoke-WebRequest "$raw/tools/export-files-md.ps1" -OutFile C:\tmp\export-files-md.ps1 -UseBasicParsing
git diff --name-only --diff-filter=d 37196ad HEAD | Set-Content C:\tmp\dev-sync-files.txt
git diff --name-only --diff-filter=D 37196ad HEAD
powershell -ExecutionPolicy Bypass -Command "& C:\tmp\export-files-md.ps1 -Out C:\tmp\dev-sync.md -Files (Get-Content C:\tmp\dev-sync-files.txt)"
```

- The third line lists files `development` deleted (often none).
- Open `C:\tmp\dev-sync.md`, copy all of it, and paste it into
  `C:\tmp\dev-sync.md` on the local machine (a new file, saved as is).

Send the output, and say when the file is pasted. Wait: before Step 3 the
local side checks AIML-3012's `app/.env.example` (15 new lines) for settings
the agent now needs in `app/.env`.

## Step 3 -- the agent on `development`, three full runs (the reviewer's "before")

The tree must be clean (Step 2 pushed). This switches to `development` for
the runs only:

```powershell
git switch --detach origin/development
git log --oneline -1
uv run python -m evals.agent_eval.run full
uv run python -m evals.agent_eval.run full
uv run python -m evals.agent_eval.run full
git switch feature/AIML-3152-extract-followup
git log --oneline -1
```

- Each run ends **INVALID**. That is expected: `development`'s committed
  baseline is on key v1.4. The scores are still written; only the verdict is skipped.
- The last line must show the merge commit from Step 2.

Then read the three runs (ids and codes only):

```powershell
$dev = Get-ChildItem evals\runs -Directory -Filter "full-*" | Sort-Object CreationTime | Select-Object -Last 3 | ForEach-Object Name
$dev
$dev | Set-Content C:\tmp\dev-runs.txt
Invoke-WebRequest "$raw/tools/agent_flips.py" -OutFile C:\tmp\agent_flips.py -UseBasicParsing
uv run python C:\tmp\agent_flips.py $dev
```

Send all the output (not with `--notes`: notes are customer text) and wait.

## Step 4 -- the review fixes: four files, then the tests

What changes:

- `extract()` removes a "[2]" only when it is a sentence number of that note,
  so "PO [1234567]" and "Model X[2]" stay.
- A full stop after Mr, Mrs, Ms, Dr, e.g., i.e., vs. or approx. no longer
  ends a sentence. The 90 golden notes split exactly as before.
- The bare cue "quoted" is dropped from code 1 ("gave a quote" stays).
- A test pins the one-word-sentences limit again.

```powershell
foreach ($f in "app/extraction/extract.py", "app/voice_notes_agent/resources/dispositions.yaml", "tests/test_extraction.py", "tests/test_prompt_rules.py") { Invoke-WebRequest "$raw/sell-n-tell/$f" -OutFile $f -UseBasicParsing }
fp app/extraction/extract.py app/voice_notes_agent/resources/dispositions.yaml tests/test_extraction.py tests/test_prompt_rules.py
uv run pytest tests/ -q
git status --short
```

- `fp` must print `806aa777f091`, `d62e52df2912`, `b41c4c6b09f2`, `53a9dcab5586`
  (confirmed again after Step 2, in case `development` changed any of them).
- Tests: 422 passed, 2 xfailed (Step 2 gave 421 passed, 1 xfailed).
- `git status --short` lists ` M` for exactly these four files, plus the two
  untracked items.

Send the output and wait.

## Step 5 -- `extract()` again (3 repeats, golden set)

```powershell
uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
$new = (Get-ChildItem evals\runs -Directory -Filter "extract-*" | Sort-Object Name | Select-Object -Last 1).Name
$new
uv run python -m evals.extract_eval.compare evals/runs/extract-20261116-230453 evals/runs/$new
Invoke-WebRequest "$raw/tools/disposition_paired.py" -OutFile C:\tmp\disposition_paired.py -UseBasicParsing
uv run python C:\tmp\disposition_paired.py --old evals\runs\extract-20261116-230453 --new evals\runs\$new
uv run python C:\tmp\disposition_paired.py --old evals\runs\extract-20261118-132816 --new evals\runs\$new
Invoke-WebRequest "$raw/tools/overclaim_units.py" -OutFile C:\tmp\overclaim_units.py -UseBasicParsing
fp C:\tmp\overclaim_units.py
uv run python C:\tmp\overclaim_units.py extract-20261116-230453 extract-20261118-132816 $new
```

- `$new` must be a folder from today.
- `extract-20261116-230453` is `development`, `extract-20261118-132816` is the
  branch before these fixes. The first paired table compares against
  `development`; the second shows what dropping "quoted" did.
- `fp` must print `d65b82929e82`. The last line lists each over-claimed topic
  and how many sentences its note has (the reviewer's one-unit question).

Send all the output (numbers and ids only; not the scorecard) and wait.

## Step 6 -- the agent on the branch, three full runs

```powershell
git log --oneline -1
uv run python -m evals.agent_eval.run full
uv run python -m evals.agent_eval.run full
uv run python -m evals.agent_eval.run full
$br = Get-ChildItem evals\runs -Directory -Filter "full-*" | Sort-Object CreationTime | Select-Object -Last 3 | ForEach-Object Name
$br
$br | Set-Content C:\tmp\branch-runs.txt
$dev = Get-Content C:\tmp\dev-runs.txt
uv run python C:\tmp\agent_flips.py $br
uv run python C:\tmp\disposition_paired.py --old ($dev | ForEach-Object { "evals\runs\$_" }) --new ($br | ForEach-Object { "evals\runs\$_" })
```

- Each run gives a verdict against the committed baseline (same key, v1.5).
- The paired table is the reviewer's before/after for the agent:
  `development` against this branch, topic by topic.

Send all the output and wait.

## Step 7 -- the new baseline, the commit, the PR text and the replies

Written once Step 6's numbers are in: the baseline export, the README
figures, one commit, the PR description and the replies on each comment.
