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

Git is already 2.56.1, but its credential manager is still 2.9.1: install the
credential manager on its own.

```powershell
winget install --id Git.GCM -e
```

Close the terminal, open a new one, then:

```powershell
git --version
git credential-manager --version
```

The credential manager must be 3.0.0 or newer. Send the output and wait.

## Step 2 -- the review fixes: three files, then the tests (DONE: fingerprints match, 347 passed)

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

## Step 3 -- the extract() runs again (DONE: extract-20261118-132816)

The same command as the earlier runs (3 repeats, golden set):

```powershell
uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
```

Then, with the new run folder picked up automatically:

```powershell
$new = (Get-ChildItem evals\runs -Directory -Filter "extract-*" | Sort-Object Name | Select-Object -Last 1).Name
$new
Invoke-WebRequest "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup/tools/disposition_paired.py" -OutFile C:\tmp\disposition_paired.py -UseBasicParsing
uv run python C:\tmp\disposition_paired.py --old evals\runs\extract-20261116-231424 --new evals\runs\$new
Get-Content evals\runs\$new\scorecard_golden.md -TotalCount 40
```

- `$new` must be a folder from today, not `extract-20261116-231424`.
- Expected: about the same as before, with HL-005 possibly moving to 99.

Send all the output and wait.

## Step 4 -- the commit and the push (DONE: 37196ad pushed)

```powershell
git add app/extraction/extract.py tests/test_extraction.py evals/README.md
git commit -m "AIML-3152: extract() quote rule; sentence numbers removed from summaries and fields"
git push
git log --oneline -3
git status --short
```

- The commit reports 3 files changed; the push goes to `feature/AIML-3152-extract-followup`.
- `git status --short` shows only the two untracked items (`??`).

Send the output and wait.

## Step 5 -- the pull request (DONE: open, target development)

Open this link; the target branch must be **development**:

https://bitbucket.org/fm_ebiz/sell-n-tell/pull-requests/new?source=feature/AIML-3152-extract-followup&t=1

**Title** (copy the line):

```text
AIML-3152: extract() evidence by sentence number; rules per the business answers; answer key v1.5
```

**Description** (copy everything inside the box; it replaces any earlier draft):

````markdown
## What changes

**extract() (`app/extraction/`)**
- The note is shown as numbered sentences, run together as one text. The model returns sentence numbers for each topic's evidence and outcome; code copies those sentences into the record. The model never types evidence, so it cannot misquote it. A number that is not a sentence of the note is ignored and kept as `ignored_lines`. `quote_in` and `evidence_ok` are removed.
- A sentence number the model writes into a summary or a field ("[2]", "[1, 2]", "[1-2]") is removed in code; a value that was only a number becomes null.
- The prompt states the business's answers:
  - a visit where the rep met a contact in person is a Meeting, even if the decision maker was phoned;
  - a topic is discussed only if the rep talked with someone at the customer about it, the customer's reaction included; material, a flyer or a voicemail left with no one spoken to is not discussed;
  - code 1 is a quote the rep has already given for that topic's products; a quote to be sent later, a quote for other products, or asking the customer to order is not.
- U-04 and U-07 values start with the business category ("order placed: ...", "mispick: ...").

**This PR changes the live agent in production.** It reads the same outcome list and its own prompt:
- `dispositions.yaml`: code 1 is also cued by "gave a quote" and "quoted" ("send a quote" and "interested" stay out).
- `behavioral_rules.yaml`: the same quote rule as `extract()`. With the cue alone, the agent gave code 1 to "will email quote" in some runs and not others, and its disposition moved 21-26 of 28 topics across identical runs.

**Answer key v1.5** (`gs://sellntell-eval-np/golden_v1.5/`): two topics where material was left with no one spoken to are now not discussed. 28 topics scored, was 30.

**Agent baseline** (`evals/baselines/golden_v1.json`): three full runs on key v1.5 with the quote rule. Quick-mode disposition (9 topics, one topic = 11 points) is out of the quick verdict by design.

**README**: the rules, the evidence layout and its limits, the new baseline figures, `golden_v1.5`.

## Results on key v1.5

`extract()`, three repeats each, run `extract-20261118-132816` (this branch's final code). "Before" is a fresh run of `development` on the same key.

| Score | Before | After |
|---|---|---|
| Disposition | 80/84 = 95.2% | 80/84 = 95.2% |
| Topics right by majority | 27 of 28 | 27 of 28 |
| Topic status | 99.5% | 99.2% |
| Over-claimed | 0% | 0.7% (2 of 306) |
| Event type | 91.1% | 93.4% |
| Faithfulness | 90.7% | 90.0% |
| Invented fields | 1.6% | 1.3% |
| Cost per 1,000 notes | $3.60 | $3.85 |

Disposition is the same count with different topics: this branch gets MH-006 right (a quote given, code 1); `development` gets HL-005 (see the limits).

Agent baseline (three full runs):

| Score | Range | Limit |
|---|---|---|
| Disposition | 80.0-85.2 | ±9 points |
| Topic status | 92.1-93.6 | ±5 points |
| Event type | 82.9-84.7 | ±5 points |
| Faithfulness | 73.9-80.2 | ±9.6 points |

## Known limits

- **HL-005**: the key gives code 1 to a quote the customer asked for; by the business's answer and the prompts' own worked example that is 99, which both `extract()` and the agent now answer. To settle with the business.
- **The agent and `extract()` follow different rules, by design**: the agent's prompt has the quote rule only, not the topic rule (material left) or the event-type rule, so key v1.5 counts those cases against it. Code 5 for "another brand preferred" is stated in neither prompt (code 5's cues are about vendors); both got it right on the golden set. MH-002 ("ownership wants a different brand"): the agent gives 99, the key says 7.
- **Sentence splitting**: evidence is no finer than a sentence. A note with no sentence end is one unit (30 of the 90 golden notes), so citing it counts for any topic. A full stop after an abbreviation ("Mr. Smith", "approx.", "e.g.") splits a sentence.
- **Bracketed numbers**: a "[3]" typed in a dictation looks like a sentence number to the model, and a bracketed number in a summary or field ("Suite [204]") is removed with the sentence numbers. Spoken input has no brackets, so neither is expected live.
- **Cost**: $0.25 more per 1,000 notes. Per-call time varies by day (p95 6.7 s in the final run, 10.7 s in an earlier run of the same prompt, 8.9 s for `development`), so no speed difference is claimed.
- **Connection drops**: the agent runs lost 1-4 cases each to dropped connections, under the 10% limit.
- **Text, not speech**: the golden notes are typed text; spoken input is not measured.
- **For the live-flow story**: an unconfirmed topic keeps its summary for the rep's question; nothing yet stops it being saved as confirmed.

## How to check

    uv run pytest tests/ -q                                         # 347 passed, 1 xfailed with the golden data
    uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
    uv run python -m evals.agent_eval.run full

Data: `gs://sellntell-eval-np/golden_v1.5/` into `evals/v1/`.
````

Send the pull request link once it is open.

## Step 6 -- the Jira update and the reviewer (the last step)

1. On the pull request, add Suresh as a reviewer (it shows 0 reviewers).
2. On AIML-3152 in Jira, add this comment and move the ticket to review:

```text
PR raised for review: extract() evidence by sentence number, the business's topic and quote rules, answer key v1.5 (in the eval bucket) and the agent baseline re-measured on it; final run: disposition 95.2%, topic status 99.2%, event type 93.4%.
```

## Step 7 -- the reviewer's number check (numbers only; no model calls)

From `C:\Developer\sellNtell\sell-n-tell`. The first line keeps a copy of the
run folder, because the re-score rewrites its summary and scorecard.

```powershell
git log --oneline -1
XCOPYLINEuns\extract-20261118-132816 C:	mp\extract-20261118-132816-copy
uns\extract-20261118-132816 C:	mp\extract-20261118-132816-copy
uv run python -m evals.extract_eval.compare evals/runs/extract-20261116-230453 evals/runs/extract-20261118-132816
uv run python -m evals.extract_eval.run --rescore evals/runs/extract-20261118-132816 | Select-String -Pattern "Disposition by|Cost:|^\| all|^\| event_type|^\| topic_status|^\| over_claimed|^\| disposition|^\| faithfulness|written"
uv run python -m evals.extract_eval.compare evals/runs/extract-20261118-132816
uv run python -m evals.agent_eval.baseline show
```

- `git log` must show `37196ad` (the PR's head).
- The first compare gives the PR table's two columns (before = `development`, after = this branch).
- The re-score and the second compare must give the same figures as the first compare's second row.
- Send all the output (numbers, run names and checksums only). Do not send the scorecard file: it quotes customer notes.
