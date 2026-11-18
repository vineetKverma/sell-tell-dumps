# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`.

## Step 1 -- the baseline export

```powershell
uv run python -m evals.agent_eval.baseline export evals\runs\full-20261117-175125 evals\runs\full-20261117-203642 evals\runs\full-20261117-234544 --allow-noisy quick:faithfulness --allow-noisy quick:disposition
git diff --stat
uv run python -m evals.extract_eval.run --rescore evals\runs\extract-20261116-231424
Get-Content evals\runs\extract-20261116-231424\scorecard_golden.md -TotalCount 40
```

- `git diff --stat` must now list `evals/baselines/golden_v1.json`.
- The scorecard must no longer say "re-score the baseline first".
- Quick-mode disposition is left out of the verdict by design: 9 topics, one
  topic is 11 points.

Send the export's output and the scorecard lines. Do not commit yet: the
README gets its baseline figures from this first (Step 3).

## Step 2 -- key v1.5 to the shared bucket (only once agreed)

The README tells people to fetch `golden_v1.5`, so the PR needs it there.
Others read this bucket: run it only when you have decided to.

```powershell
gcloud storage cp evals\v1\golden_v1.evalset.json evals\v1\golden_v1.5.manifest.json evals\v1\universal_fields.csv evals\v1\vertical_fields.csv gs://sellntell-eval-np/golden_v1.5/
gcloud storage ls gs://sellntell-eval-np/golden_v1.5/
```

## Step 3 -- the README's final figures, then the commit and the push

Done (Step 1): `written: ...\evals\baselines\golden_v1.json`.

First the README with the new baseline figures. Paste the `fp` function
first (one line, plain PowerShell):

```powershell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
```

```powershell
Invoke-WebRequest "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup/sell-n-tell/evals/README.md" -OutFile evals/README.md -UseBasicParsing
fp evals/README.md
uv run pytest tests/ -q
git branch --show-current
git status --short
```

- `fp` must print `3502c09b949a`.
- Tests: 345 passed, 1 xfailed.
- The branch is `feature/AIML-3152-extract-followup`.
- `git status --short` lists exactly these six, all ` M`:
  `app/extraction/extract.py`, `app/voice_notes_agent/resources/behavioral_rules.yaml`,
  `evals/README.md`, `evals/baselines/golden_v1.json`, `tests/test_extraction.py`,
  `tests/test_prompt_rules.py`.

Send the output. Then, only when I say so, the commit and the push:

```powershell
git add app/extraction/extract.py app/voice_notes_agent/resources/behavioral_rules.yaml evals/README.md evals/baselines/golden_v1.json tests/test_extraction.py tests/test_prompt_rules.py
git commit -m "AIML-3152: agent quote rule; agent baseline on key v1.5; README figures"
git push
```
