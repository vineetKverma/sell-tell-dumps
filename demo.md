# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`. Do the steps in order;
do not start a step until the one before it is confirmed.

Done: `development` merged in (`028730b`), the review fixes pushed (`3bc5683`),
the PR description and the replies posted.

What is measured now: dropping the cue "quoted" changed both prompts, so:

- **Steps 1-2 (done):** `extract()` once more; the agent on `development`;
- **Step 3:** the agent on the branch, one full run, and the before/after.

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

Step 1 is done: `extract-20261119-175710` (disposition 77/84, 27 of 28 by
majority, MH-006 right in all 3 repeats, over-claimed 1 of 306).

Step 2 is done: the agent on `development` is `full-20261119-182215` (saved in
`C:\tmp\agent-dev.txt`; INVALID as expected, key v1.4 baseline).

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
