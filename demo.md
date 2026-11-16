# AIML-3152 on the dev machine

Run everything in `C:\Developer\sellNtell\sell-n-tell`. Files to bring over are
listed by their path in this repository; put each at the same path under
`sell-n-tell\` on dev (tools go to `C:\tmp`). After copying, the fingerprint
command must print exactly the values listed.

Fingerprint command used below (prints one line per file; plain PowerShell,
needs nothing installed; paste it again in every new terminal):

```powershell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
```

## Step 0 -- uv (needed for the tests and runs)

```powershell
Get-Command uv -ErrorAction SilentlyContinue; Test-Path "$env:USERPROFILE\.local\bin\uv.exe"
```

- If the second line says `True`, uv is installed but not on the PATH:
  `$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"` (this terminal), then `uv --version`.
- If both find nothing, install it (the official installer), then open a new terminal:
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Then, in `sell-n-tell`: `uv sync` (builds the environment from `uv.lock`; changes no file).

---

## Step 1 -- on development (done)

`git log --oneline -1` shows `e1f787b Merged in feature/AIML-3004-topic-dispositions (pull request #17)`.

## Step 2 -- check the base files

```powershell
fp app/extraction/__init__.py app/extraction/extract.py app/voice_notes_agent/resources/dispositions.yaml evals/README.md evals/extract_eval/run.py tests/test_extraction.py
```

Expected:

```
972cfeed8c36 app/extraction/__init__.py
85e43f56a944 app/extraction/extract.py
a9cd386a9589 app/voice_notes_agent/resources/dispositions.yaml
ff8067b42ae2 evals/README.md
f1618aa95230 evals/extract_eval/run.py
bdf15affa440 tests/test_extraction.py
```

Any line different: stop and report which.

## Step 3 -- the branch and the files

```powershell
git switch -c feature/AIML-3152-extract-followup
```

Bring over these six (they go in the PR):

| From this repository | To, on dev |
|---|---|
| `sell-n-tell/app/extraction/__init__.py` | `app\extraction\__init__.py` |
| `sell-n-tell/app/extraction/extract.py` | `app\extraction\extract.py` |
| `sell-n-tell/app/voice_notes_agent/resources/dispositions.yaml` | `app\voice_notes_agent\resources\dispositions.yaml` |
| `sell-n-tell/evals/README.md` | `evals\README.md` |
| `sell-n-tell/evals/extract_eval/run.py` | `evals\extract_eval\run.py` |
| `sell-n-tell/tests/test_extraction.py` | `tests\test_extraction.py` |

And these four (they stay untracked on dev, never committed):

| From this repository | To, on dev |
|---|---|
| `sell-n-tell/evals/dataset/__init__.py` | `evals\dataset\__init__.py` |
| `sell-n-tell/evals/dataset/fix_event_types.py` | `evals\dataset\fix_event_types.py` |
| `sell-n-tell/evals/dataset/fix_left_material.py` | `evals\dataset\fix_left_material.py` |
| `sell-n-tell/tests/test_dataset_fix_left_material.py` | `tests\test_dataset_fix_left_material.py` |

## Step 4 -- check and test

```powershell
fp app/extraction/__init__.py app/extraction/extract.py app/voice_notes_agent/resources/dispositions.yaml evals/README.md evals/extract_eval/run.py tests/test_extraction.py evals/dataset/__init__.py evals/dataset/fix_event_types.py evals/dataset/fix_left_material.py tests/test_dataset_fix_left_material.py
git status --short
uv run pytest tests/ -q
```

Expected fingerprints:

```
69205903f2fc app/extraction/__init__.py
a5246cef00df app/extraction/extract.py
fdbbba0022b1 app/voice_notes_agent/resources/dispositions.yaml
75ef4aca29f5 evals/README.md
8b29d8369d27 evals/extract_eval/run.py
0f0e8bc02e7f tests/test_extraction.py
7de00c320ae2 evals/dataset/__init__.py
fb83495bbfee evals/dataset/fix_event_types.py
0abf56cb2118 evals/dataset/fix_left_material.py
30006e1a9c05 tests/test_dataset_fix_left_material.py
```

`git status --short`: the six files as `M`; `evals/dataset/` and
`tests/test_dataset_fix_left_material.py` as `??`. Tests: no failures (some
skip until the golden data is back).

## Step 5 -- commit (and the backup push, if wanted)

```powershell
git add app/extraction/__init__.py app/extraction/extract.py app/voice_notes_agent/resources/dispositions.yaml evals/README.md evals/extract_eval/run.py tests/test_extraction.py
git commit -m "AIML-3152: evidence by sentence number; topic, event and quote rules per the business answers"
git show --stat HEAD
```

Six files in the commit. Backup push (no PR is opened):

```powershell
git push -u origin feature/AIML-3152-extract-followup
```

---

## Later, once the eval data, `app/.env` and gcloud login are back

### The tools, to `C:\tmp`

| From this repository | To |
|---|---|
| `tools/disposition_misses.py` | `C:\tmp\disposition_misses.py` |
| `tools/sentence_check.py` | `C:\tmp\sentence_check.py` |
| `tools/case_report.py` | `C:\tmp\case_report.py` |
| `tools/value_recount.py` | `C:\tmp\value_recount.py` |
| `tools/run_diff.py` | `C:\tmp\run_diff.py` |
| `tools/try_extract_ideas.py` | `C:\tmp\try_extract_ideas.py` |

```powershell
fp C:\tmp\disposition_misses.py C:\tmp\sentence_check.py C:\tmp\case_report.py C:\tmp\value_recount.py C:\tmp\run_diff.py C:\tmp\try_extract_ideas.py
```

```
6f6fad7e2af2 C:\tmp\disposition_misses.py
cdff2f52ddea C:\tmp\sentence_check.py
ac55e3004fc4 C:\tmp\case_report.py
dcf4ee2b6c1a C:\tmp\value_recount.py
91e4ff310a5f C:\tmp\run_diff.py
713303e55553 C:\tmp\try_extract_ideas.py
```

### Step 6 -- answer key v1.5 (from the restored v1.4 in `evals\v1`)

```powershell
Copy-Item evals\v1\golden_v1.evalset.json C:\tmp\golden_v1.4.evalset.json
uv run python -m evals.dataset.fix_left_material evals\v1\golden_v1.evalset.json C:\tmp\golden_v1.5
Copy-Item C:\tmp\golden_v1.5\golden_v1.evalset.json evals\v1\golden_v1.evalset.json -Force
uv run pytest tests/ -q
```

The second command must print `to not discussed: HL-007 ..., HS-013 ...`.
If it prints `not applied`, stop and report the message.

### Step 7 -- before and after, both on key v1.5

Before (the merged code, on development):

```powershell
git stash -u
git switch development
uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
git switch feature/AIML-3152-extract-followup
git stash pop
```

`git stash -u` sets the untracked helpers aside so the merged code runs
without them; `git stash pop` brings them back. Note the run folder name it
prints (`extract-<time>`, call it BEFORE).

After (this branch):

```powershell
uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
```

Note the folder (AFTER). Then, with both names filled in:

```powershell
uv run python -m evals.extract_eval.compare evals\runs\BEFORE evals\runs\AFTER
uv run python C:\tmp\case_report.py evals\runs\BEFORE evals\runs\AFTER
uv run python C:\tmp\disposition_misses.py evals\runs\AFTER
uv run python C:\tmp\sentence_check.py evals\runs\AFTER
uv run python C:\tmp\value_recount.py evals\runs\AFTER
```

Report all five outputs. The scorecard saying "the golden set differs from the
baseline's" is expected: the agent baseline is re-measured after this.
