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

Wait for the word: the commands are added here once Step 1's numbers are in
the README.
