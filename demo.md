# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`. Do the steps in order;
do not start a step until the one before it is confirmed.

Done: `development` merged in (`028730b`), the review fixes pushed (`3bc5683`),
the PR description and the replies posted.

What is measured now: dropping the cue "quoted" changed both prompts, so:

- **Step 1:** `extract()` once more;
- **Steps 2-3:** the agent on `development` and on the branch, one full run
  each (the reviewer's before/after).

Nothing here changes code or commits anything.

## Before anything: the `fp` function, the download address, the tools

Paste once in the terminal (again in every new terminal, except the downloads):

```powershell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
$raw = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup"
foreach ($t in "disposition_paired.py", "overclaim_units.py", "agent_flips.py") { Invoke-WebRequest "$raw/tools/$t" -OutFile "C:\tmp\$t" -UseBasicParsing }
fp C:\tmp\overclaim_units.py
```

- `fp` must print `d65b82929e82`.

## Step 1 -- `extract()` again (3 repeats, golden set; minutes)

```powershell
git log --oneline -1
git status --short
uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
$new = (Get-ChildItem evals\runs -Directory -Filter "extract-*" | Sort-Object Name | Select-Object -Last 1).Name
$new
$new | Set-Content C:\tmp\extract-new.txt
uv run python -m evals.extract_eval.compare evals/runs/extract-20261116-230453 evals/runs/extract-20261118-132816 evals/runs/$new
uv run python C:\tmp\disposition_paired.py --old evals\runs\extract-20261116-230453 --new evals\runs\$new
uv run python C:\tmp\disposition_paired.py --old evals\runs\extract-20261118-132816 --new evals\runs\$new
uv run python C:\tmp\overclaim_units.py extract-20261116-230453 extract-20261118-132816 $new
```

- `git log` shows `3bc5683`; `git status` shows only the two untracked items.
- `$new` must be a folder from today.
- The three runs are:
  - `extract-20261116-230453`: `development`;
  - `extract-20261118-132816`: the branch before the review fixes;
  - `$new`: the branch now.
- The compare gives all three side by side.
- The first paired table compares the branch now against `development`; the
  second shows what dropping "quoted" did (MH-006 is the topic to watch).
- The last command lists each over-claimed topic with how many sentences its
  note has.

Send all the output (numbers and ids only; not the scorecard) and wait.

## Step 1b -- the two read-outs left from Step 1 (reads only)

Step 1's run is `extract-20261119-175710`. The first command is the one that
failed (`-d` instead of `--old`); the second lists, per topic, the codes that
were wrong in any repeat (ids and codes only):

```powershell
uv run python C:\tmp\disposition_paired.py --old evals\runs\extract-20261116-230453 --new evals\runs\extract-20261119-175710
@'
import json
for run in ("extract-20261116-230453", "extract-20261118-132816", "extract-20261119-175710"):
    reps = json.load(open(f"evals/runs/{run}/scores_golden.json", encoding="utf-8"))["cases"]
    seen = {}
    for rep in reps:
        for s in rep:
            for i, t in enumerate((s or {}).get("topics", []), 1):
                if "code_ok" in t:
                    seen.setdefault((s["id"], i, t["expected_code"]), []).append((t["actual_code"], t["code_ok"]))
    print(run)
    for (cid, i, want), got in sorted(seen.items()):
        if not all(ok for _, ok in got):
            print(f"  {cid} topic {i}: key {want}, repeats {[c for c, _ in got]}")
'@ | uv run python -
```

Send the output and wait.

## Step 2 -- the agent on `development`, one full run (the "before")

```powershell
git switch --detach origin/development
git log --oneline -1
uv run python -m evals.agent_eval.run full
$dev = (Get-ChildItem evals\runs -Directory -Filter "full-*" | Sort-Object CreationTime | Select-Object -Last 1).Name
$dev
$dev | Set-Content C:\tmp\agent-dev.txt
git switch feature/AIML-3152-extract-followup
git log --oneline -1
```

- The first `git log` shows `c5b76c3`; the last shows `3bc5683`.
- The run ends **INVALID**, which is expected: `development`'s committed
  baseline is on key v1.4, so the verdict is skipped. The scores are written.

Send the output and wait.

## Step 3 -- the agent on the branch, one full run (the "after"), and the before/after

```powershell
git log --oneline -1
uv run python -m evals.agent_eval.run full
$br = (Get-ChildItem evals\runs -Directory -Filter "full-*" | Sort-Object CreationTime | Select-Object -Last 1).Name
$br
$dev = Get-Content C:\tmp\agent-dev.txt
uv run python C:\tmp\agent_flips.py $dev $br
uv run python C:\tmp\disposition_paired.py --old evals\runs\$dev --new evals\runs\$br
```

- The run gives a verdict against the committed baseline (same key, v1.5):
  PASS means dropping "quoted" kept the agent within its noise limits.
- `agent_flips` shows, topic by topic, where `development` and the branch differ.
- The paired table is the reviewer's before/after for disposition.

Send all the output (not with `--notes`: notes are customer text) and wait.
