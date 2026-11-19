# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`. Do the steps in order;
do not start a step until the one before it is confirmed.

Done: `development` is merged into the branch (`028730b`, pushed); `app/.env`
needs no change.

Steps 1-2 finish the review: the fixes go onto the PR and every comment gets
its reply. The measurements (Step 3, optional) come after that.

## Before anything: the `fp` function and the download address

Paste these two lines once in the terminal (again in every new terminal):

```powershell
function fp { foreach ($f in $args) { $b = [IO.File]::ReadAllBytes((Resolve-Path $f).Path); $o = New-Object System.Collections.Generic.List[byte]; for ($i = 0; $i -lt $b.Length; $i++) { if (-not ($b[$i] -eq 13 -and $i + 1 -lt $b.Length -and $b[$i + 1] -eq 10)) { $o.Add($b[$i]) } }; $h = [Security.Cryptography.SHA256]::Create().ComputeHash($o.ToArray()); (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12) + ' ' + $f } }
$raw = "https://raw.githubusercontent.com/vineetKverma/sell-tell-dumps/feature/AIML-3152-extract-followup"
```

## Step 1 -- the review fixes: five files, the tests, the commit and the push

What changes:

- `extract()` removes a "[2]" only when it is a sentence number of that note,
  so "PO [1234567]" and "Model X[2]" stay.
- A full stop after Mr, Mrs, Ms, Dr, e.g., i.e., vs. or approx. no longer
  ends a sentence. The 90 golden notes split exactly as before.
- The bare cue "quoted" is dropped from code 1 ("gave a quote" stays).
- A test pins the one-word-sentences limit again.
- The README states the limits.

```powershell
git log --oneline -1
foreach ($f in "app/extraction/extract.py", "app/voice_notes_agent/resources/dispositions.yaml", "tests/test_extraction.py", "tests/test_prompt_rules.py", "evals/README.md") { Invoke-WebRequest "$raw/sell-n-tell/$f" -OutFile $f -UseBasicParsing }
fp app/extraction/extract.py app/voice_notes_agent/resources/dispositions.yaml tests/test_extraction.py tests/test_prompt_rules.py evals/README.md
uv run pytest tests/ -q
git status --short
```

- `git log` must show `028730b`.
- `fp` must print `806aa777f091`, `d62e52df2912`, `b41c4c6b09f2`, `53a9dcab5586`, `25a5e90e12f8`.
- Tests: 422 passed, 2 xfailed, 0 failed.
- `git status --short` lists ` M` for exactly these five files, plus the two
  untracked items.

If all of that holds:

```powershell
git add app/extraction/extract.py app/voice_notes_agent/resources/dispositions.yaml tests/test_extraction.py tests/test_prompt_rules.py evals/README.md
git commit -m "AIML-3152: review fixes: sentence-number strip, abbreviations, quote cue"
git push
git log --oneline -2
```

Send the output and wait.

## Step 2 -- the PR text and the replies

**PR description:** Edit, and in "What changes" replace the `dispositions.yaml`
bullet with:

```text
- `dispositions.yaml`: code 1 is also cued by "gave a quote" ("send a quote", "interested" and the bare "quoted" stay out: "quoted" also fits a vendor's quote).
```

Save the description.

**Replies** (one per comment; post each as a reply on its comment, do not resolve):

On `_no_line_refs strips any [digits]`:

```text
Fixed: a bracket is removed only when all its numbers are sentences of that note and it is not glued to a word. "PO [1234567]", "Qty [10-12] units" and "Model X[2]" now stay (test added).
```

On `two non-adjacent one-word sentences pass enough_words`:

```text
Kept as a known limit, since terse notes ("Pools. Interested.") need words counted across sentences. The strict xfail is back, and the docstring and README say so.
```

On `sentence splitter breaks on abbreviations`:

```text
(a) Fixed: no split after Mr, Mrs, Ms, Dr, e.g., i.e., vs., approx.; the 90 golden notes split exactly as before. (b) Kept: splitting on ";" or " - " would change 1 of the 30 one-unit notes, and 24 of the 30 discuss no planned topic. Documented in the README.
```

On `the bare cue "quoted" is risky`:

```text
Dropped; "gave a quote" stays. 2 of the 3 golden notes with "quoted" are quotes for other products. Tests pin it for both prompts.
```

On the review summary:

```text
Production impact: agreed. The quote cue is narrower now; a v1.5 agent run of development next to this branch will be added here. Fields FYI: by design, the agent's stage_visit_notes has no must_capture argument yet (the run report says "Not captured", README: 0% until the agent captures fields). field_invented_rate still catches the agent starting to fill fields.
```

Send a screenshot once they are posted.

## Step 3 -- the measurements (optional; only if the reviewer asks for them before approving)

Dropping "quoted" changes both prompts, so the PR's figures were taken before
this change. To refresh them:

- **`extract()`** (minutes):

  ```powershell
  uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
  ```

- **The agent before/after the reviewer asked for:** one full run of
  `development`, then one of the branch. The baseline is re-exported only if
  the reviewer wants it refreshed.

The exact commands are written when this step starts.
