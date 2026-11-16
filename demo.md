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

Then, in `sell-n-tell` (Python 3.12, as on the machine the code was made on;
uv downloads it if needed; changes no file in the repo):

```powershell
uv python install 3.12
uv sync --python 3.12
uv run python --version
```

The last line must print `Python 3.12.x`. Without `--python 3.12`, uv took a
newer Python for which `cffi` has no ready-made package, so it tried to build
it and needed the Microsoft C++ Build Tools.

## Step 0b -- gcloud and the Google sign-in (two test files and every run need it)

Is it installed but not on the PATH?

```powershell
Test-Path "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"; Test-Path "${env:ProgramFiles(x86)}\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
```

- A `True`: add that folder for this terminal, e.g.
  `$env:Path = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin;$env:Path"`
- Both `False`: install it -- `winget install --id Google.CloudSDK -e`, or the
  installer from https://cloud.google.com/sdk/docs/install (or the company
  software portal, if downloads are blocked). Then restart VS Code fully.

Then:

```powershell
gcloud --version
gcloud auth login
gcloud auth application-default login
```

Both sign-ins open the browser; use the work account. `app\.env` is made by
hand from `app\.env.example` (never through this repository).

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

All ten in one go, straight from this branch (the repository must be public
while it runs):

```powershell
$base = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup/sell-n-tell"
$files = "app/extraction/__init__.py", "app/extraction/extract.py", "app/voice_notes_agent/resources/dispositions.yaml", "evals/README.md", "evals/extract_eval/run.py", "tests/test_extraction.py", "evals/dataset/__init__.py", "evals/dataset/fix_event_types.py", "evals/dataset/fix_left_material.py", "tests/test_dataset_fix_left_material.py"
foreach ($f in $files) { New-Item -ItemType Directory -Force (Split-Path $f) | Out-Null; Invoke-WebRequest "$base/$f" -OutFile $f -UseBasicParsing }
```

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

## Later: the eval data, the `.env`, the tools, the runs

### Step 5b -- the eval data and `app\.env` (needs Step 0b, the gcloud sign-in)

```powershell
New-Item -ItemType Directory -Force evals/v1 | Out-Null
gcloud storage cp "gs://sellntell-eval-np/golden_v1.4/*" evals/v1/
gcloud storage cp -r gs://sellntell-eval-np/reference evals/
Get-ChildItem evals/v1, evals/reference
```

The listing must show `evals\v1`: `golden_v1.evalset.json`,
`universal_fields.csv`, `vertical_fields.csv`; and `evals\reference`:
`campaign_topics.csv`. A `gcloud storage cp` error (access denied, not found):
stop and report it. Both folders are git-ignored: never commit them.

```powershell
Copy-Item app\.env.example app\.env
notepad app\.env
```

Fill in the same values as the local `app\.env` (typed by hand, never through
this repository).

### The tools, to `C:\tmp`

| From this repository | To |
|---|---|
| `tools/disposition_misses.py` | `C:\tmp\disposition_misses.py` |
| `tools/sentence_check.py` | `C:\tmp\sentence_check.py` |
| `tools/case_report.py` | `C:\tmp\case_report.py` |
| `tools/value_recount.py` | `C:\tmp\value_recount.py` |
| `tools/run_diff.py` | `C:\tmp\run_diff.py` |
| `tools/try_extract_ideas.py` | `C:\tmp\try_extract_ideas.py` |

All six in one go:

```powershell
New-Item -ItemType Directory -Force C:\tmp | Out-Null
$tools = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup/tools"
foreach ($t in "disposition_misses.py", "sentence_check.py", "case_report.py", "value_recount.py", "run_diff.py", "try_extract_ideas.py") { Invoke-WebRequest "$tools/$t" -OutFile "C:\tmp\$t" -UseBasicParsing }
```

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

### Step 6 -- answer key v1.5 (only after Step 5b lists the four files)

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

Done: BEFORE = `extract-20261116-230453`, AFTER = `extract-20261116-231424`.

### Step 8 -- the checks on the two runs (copy and run as is)

```powershell
$before = "evals\runs\extract-20261116-230453"
$after = "evals\runs\extract-20261116-231424"
uv run python -m evals.extract_eval.compare $before $after
uv run python C:\tmp\case_report.py $before $after
uv run python C:\tmp\disposition_misses.py $after
uv run python C:\tmp\sentence_check.py $after
uv run python C:\tmp\value_recount.py $after
foreach ($r in $before, $after) { $ids = Get-ChildItem "$r\raw_golden_r*.jsonl" | Get-Content | ConvertFrom-Json | Where-Object { $_.score -and $_.score.faithful -eq $false } | ForEach-Object { $_.id }; "$r not faithful: $(@($ids).Count): $((@($ids) | Sort-Object) -join ', ')" }
```

Report all of it. The last line lists, per run, the cases the judge marked
not faithful (ids only, over the three repeats). The scorecard saying "the
golden set differs from the baseline's" is expected: the agent baseline is
re-measured after this.

Done (results reported).

### Step 9 -- what the judge objected to in HS-001 (flagged 3/3 after, 0/3 before)

Prints the judge's objections for one case in both runs. They quote the
summaries, so keep the output on this machine and report it in your own words
or as a screenshot.

```powershell
foreach ($r in $before, $after) { "== $r"; Get-ChildItem "$r\raw_golden_r*.jsonl" | Get-Content | ConvertFrom-Json | Where-Object { $_.id -eq "HS-001" } | ForEach-Object { "  faithful: $($_.score.faithful) | unsupported: $(@($_.score.unsupported) -join ' || ')" } }
```

Done: in HS-001 the summaries add a purpose ("met with ... to address the
mis-picked amenities") the rep did not state.

### Step 9b -- the same for the other cases flagged only after

```powershell
foreach ($c in "HL-003", "HL-010", "IS-005", "IS-013", "MH-011") { "== $c"; Get-ChildItem "$after\raw_golden_r*.jsonl" | Get-Content | ConvertFrom-Json | Where-Object { $_.id -eq $c -and $_.score.faithful -eq $false } | ForEach-Object { "  $(@($_.score.unsupported) -join ' || ')" } }
```

Report it as a screenshot (it quotes summaries). What is looked for: does the
judge object to a purpose or link the rep did not state ("to address",
"regarding", "in order to"), or to something else.

Done: no single pattern (an added purpose or result in 3 cases, one wrong
name, the rest strict readings). The code stays as it is.

### Step 9c -- three files tidied after the review (no change to the prompt)

A comment and two test comments lost a reference to a document that is not in
the repo, and the README now says 28 scored topics and states the rules. The
prompt is byte-for-byte the same, so the runs above stand.

```powershell
$base = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup"
foreach ($f in "app/extraction/extract.py", "tests/test_extraction.py", "evals/README.md") { Invoke-WebRequest "$base/sell-n-tell/$f" -OutFile $f -UseBasicParsing }
Invoke-WebRequest "$base/tools/disposition_paired.py" -OutFile C:\tmp\disposition_paired.py -UseBasicParsing
fp app/extraction/extract.py tests/test_extraction.py evals/README.md C:\tmp\disposition_paired.py
git status --short
uv run pytest tests/ -q
```

Expected:

```
095986de7591 app/extraction/extract.py
d67dd332898b tests/test_extraction.py
24727dfd6ecf evals/README.md
8de3264c8f36 C:\tmp\disposition_paired.py
```

`git status --short`: those three as `M`, plus the two `??` helpers. Tests:
344 passed, 1 xfailed. Do not commit yet (one commit after Step 11).

Then the topic-by-topic comparison of the two runs (ids and counts only):

```powershell
uv run python C:\tmp\disposition_paired.py --old evals\runs\extract-20261116-230453 --new evals\runs\extract-20261116-231424
```

Report its output.

### Step 10 -- the agent baseline on key v1.5 (three full runs, about 1.5 hours each)

The live agent reads the same outcome list, which now has the quote cue, and
the key changed; so its baseline is measured again. The app starts by itself
(port 8000 must be free). Run one after another, unattended:

```powershell
uv run python -m evals.agent_eval.run full
uv run python -m evals.agent_eval.run full
uv run python -m evals.agent_eval.run full
```

Each ends with a verdict and `evals\runs\full-<time>`; note the three names.
Report the three verdict lines. A REGRESSION or INVALID against the old
baseline is expected here (the old baseline is on key v1.4); what matters is
that all three ran to the end.

### Step 11 -- the new baseline, and the extract run compared with it

With the three folder names from Step 10 in place of A, B, C:

```powershell
uv run python -m evals.agent_eval.baseline export evals\runs\full-A evals\runs\full-B evals\runs\full-C --allow-noisy quick:faithfulness
git diff --stat
uv run python -m evals.extract_eval.run --rescore evals\runs\extract-20261116-231424
Get-Content evals\runs\extract-20261116-231424\scorecard_golden.md -TotalCount 40
```

- If the export names another score as too noisy and refuses, stop and
  report the message.
- `git diff --stat` must now also list `evals/baselines/golden_v1.json`.
- The re-score makes no model call; it fills in the comparison with the new
  baseline. Report the export's output and the scorecard's first 40 lines
  (numbers only). The README's lines about the baseline get their new figures
  from this before the commit.

### Step 12 -- key v1.5 to the shared bucket (only once agreed)

The README now tells people to fetch `golden_v1.5`, so the PR needs it there.
Others read this bucket: run it only when you have decided to.

```powershell
gcloud storage cp evals\v1\golden_v1.evalset.json evals\v1\golden_v1.5.manifest.json evals\v1\universal_fields.csv evals\v1\vertical_fields.csv gs://sellntell-eval-np/golden_v1.5/
gcloud storage ls gs://sellntell-eval-np/golden_v1.5/
```

### Step 13 -- the commit and the push (after Steps 9c to 12, and the README's final figures)

Wait for the word: the README gets one more update from Step 11's numbers.

