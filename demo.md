# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`, in this order. Do not
start a step until the one before it is confirmed.

Step 1 (the baseline export) is done.

## Before anything: the `fp` function

Paste this line once in the terminal (again in every new terminal):

```powershell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
```

## Step 2a -- check before the upload (reads only; uploads nothing)

```powershell
Get-ChildItem evals\v1 | Select-Object Name, Length
fp evals/v1/golden_v1.evalset.json
gcloud storage ls gs://sellntell-eval-np/
```

- `fp` must print `a0baafdd8d68` (key v1.5).
- The bucket list must NOT already have `golden_v1.5/`.

Send the output and wait.

## Step 2b -- upload key v1.5 to the bucket

Step 2a confirmed: the file is key v1.5 (`a0baafdd8d68`) and the bucket has
no `golden_v1.5/` yet. The four files to upload (not the v1.4 manifest):

```powershell
gcloud storage cp evals\v1\golden_v1.evalset.json evals\v1\golden_v1.5.manifest.json evals\v1\universal_fields.csv evals\v1\vertical_fields.csv gs://sellntell-eval-np/golden_v1.5/
gcloud storage ls -l gs://sellntell-eval-np/golden_v1.5/
```

The list must show exactly these four, with these sizes:
`golden_v1.evalset.json` 220491, `golden_v1.5.manifest.json` 1495,
`universal_fields.csv` 4221, `vertical_fields.csv` 21557.

Send the output and wait.

## Step 3a -- the README with the new baseline figures

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

Send the output and wait.

## Step 3b -- the commit and the push (only when told)

```powershell
git add app/extraction/extract.py app/voice_notes_agent/resources/behavioral_rules.yaml evals/README.md evals/baselines/golden_v1.json tests/test_extraction.py tests/test_prompt_rules.py
git commit -m "AIML-3152: agent quote rule; agent baseline on key v1.5; README figures"
git push
```
