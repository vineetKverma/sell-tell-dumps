# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`, in one terminal. Every
command to run is in this file; nothing is only in chat.

## Done

- `development` merged in (`028730b`); review fixes (`3bc5683`, `15a1bb2`);
  replies on all comments posted.
- `extract()` re-measured (`extract-20261120-113412`); agent `development` vs
  branch; agent baseline re-taken and committed (`1d97230`, pushed).

## On hold: the PR description and the reply on the reminder

Do not post them yet. Two steady misses on the branch are being explained
first, and the description will carry the answer:

- **HL-005** (3 of the 5 misses): the branch's quote rule gives 99 to a quote
  the customer will ask for; the key says 1.
- **IS-010** (2 of the 5): the branch's topic rule ("talked with someone at
  the customer") marks "Revisit <topic>" alone as not discussed; the key says
  discussed, code 3.

## Now: Step E -- a focused experiment on the two rules (a few minutes)

What it does: `extract()` on HL-005, IS-010, the golden cases the two rules
were written for, and short written notes with a set answer; 5 repeats each,
under three prompts:

- **branch**: as it is;
- **old topic rule**: the topic rule as `development` has it;
- **asked-for quote**: a quote the customer asked for on that topic's
  products counts as code 1.

Nothing in the repo changes (the wording is swapped in memory). It prints ids,
counts and the written notes only, never golden note text. About 300 calls.

```powershell
cd C:\Developer\sellNtell\sell-n-tell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
$raw = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup"
Invoke-WebRequest "$raw/tools/rule_probe.py" -OutFile C:/tmp/rule_probe.py -UseBasicParsing
fp C:/tmp/rule_probe.py
uv run python C:/tmp/rule_probe.py --dry
```

- `fp` must print `25ca519f987b`.
- `--dry` makes no calls: every answer is "discussed 99", and it ends with
  `calls: extract 300`. It must not stop with "wording moved" or "not in the
  golden set".

Then the real run:

```powershell
uv run python C:/tmp/rule_probe.py
```

Send all of its output (ids, counts, the written notes) and wait. Nothing to
commit.
