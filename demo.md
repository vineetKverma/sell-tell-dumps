# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`. Do the steps in order;
do not start a step until the one before it is confirmed.

Done: commit `52ea954` is pushed; key v1.5 is in `gs://sellntell-eval-np/golden_v1.5/`.

## Before anything: the `fp` function

Paste this line once in the terminal (again in every new terminal):

```powershell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
```

## Step 1 -- upgrade Git (Bitbucket blocks this Git Credential Manager on November 30, 2026)

```powershell
winget upgrade --id Git.Git -e
```

Close the terminal, open a new one, then:

```powershell
git --version
git credential-manager --version
```

The credential manager must be 3.0.0 or newer. Send the output and wait.

## Step 2 -- the review fixes: three files, then the tests

What changed: `extract()` now states the quote rule (a quote already given for
that topic's products is code 1), and sentence numbers like "[2]" are removed
from summaries and field values. The live agent is not changed.

```powershell
$base = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup/sell-n-tell"
foreach ($f in "app/extraction/extract.py", "tests/test_extraction.py", "evals/README.md") { Invoke-WebRequest "$base/$f" -OutFile $f -UseBasicParsing }
fp app/extraction/extract.py tests/test_extraction.py evals/README.md
uv run pytest tests/ -q
git status --short
```

- `fp` must print `3068a1c48c33`, `c4bd3d9b8a30`, `383af0f09a08`.
- Tests: 347 passed, 1 xfailed (two new tests).
- `git status --short` lists ` M` for exactly these three files (plus the two
  untracked items, `evals/dataset/` and `tests/test_dataset_fix_left_material.py`).

Send the output and wait.

## Step 3 -- the extract() runs again (the prompt changed; a few minutes)

Written here after Step 2 is confirmed.

## Step 4 -- the commit and the push

Written here after Step 3 is confirmed.

## Step 5 -- the pull request

Written here after Step 4, with the figures from Step 3.
