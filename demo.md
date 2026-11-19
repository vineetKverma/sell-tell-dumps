# AIML-3152 on the dev machine -- what is left

Done: `development` is merged into the branch (`028730b`), and the review
fixes are pushed (`3bc5683`; 424 passed, 1 xfailed; the replay on the saved
run rejected nothing).

## Step 2 -- the PR description and the replies

**PR description.** On the pull request, click Edit and select everything in
the description box. Paste the text inside the box below over it, then save.
The title stays.

````markdown
## What changes

**extract() (`app/extraction/`)**
- The note is shown as numbered sentences, run together as one text. The model returns sentence numbers for each topic's evidence and outcome, and code copies those sentences into the record. The model never types evidence, so it cannot misquote it. A number that is not a sentence of the note is ignored and kept as `ignored_lines`. `quote_in` and `evidence_ok` are removed.
- No sentence split after Mr, Mrs, Ms, Dr, e.g., i.e., vs. or approx. The 90 golden notes split exactly as before.
- A topic's evidence, and a code's sentences, need two different non-filler words within neighbouring sentences. "Pools. Interested." passes; "Frank. ... Pools." (one word from each of two sentences far apart) does not.
- A sentence number the model writes into a summary or a field ("[2]", "[1, 2]", "[1-2]") is removed in code, and a value that was only a number becomes null. Only brackets whose numbers are all sentences of that note, and that are not glued to a word, are removed: "PO [1234567]" and "Model X[2]" stay.
- The prompt states the business's answers:
  - a visit where the rep met a contact in person is a Meeting, even if the decision maker was phoned;
  - a topic is discussed only if the rep talked with someone at the customer about it, the customer's reaction included; material, a flyer or a voicemail left with no one spoken to is not discussed;
  - code 1 is a quote the rep has already given for that topic's products; a quote to be sent later, a quote for other products, or asking the customer to order is not.
- U-04 and U-07 values start with the business category ("order placed: ...", "mispick: ...").

**This PR changes the live agent in production.** It reads the same outcome list and its own prompt:
- `dispositions.yaml`: code 1 is also cued by "gave a quote". "Send a quote", "interested" and the bare "quoted" stay out: "quoted" also fits a vendor's quote or a quote for other products (2 of the 3 golden notes with it).
- `behavioral_rules.yaml`: the same quote rule as `extract()`. With a cue alone, the agent gave code 1 to "will email quote" in some runs and not others, and its disposition moved 21-26 of 28 topics across identical runs.

**Answer key v1.5** (`gs://sellntell-eval-np/golden_v1.5/`): two topics where material was left with no one spoken to are now not discussed. 28 topics scored, was 30.

**Agent baseline** (`evals/baselines/golden_v1.json`): three full runs on key v1.5 with the quote rule. Quick-mode disposition (9 topics, one topic = 11 points) is out of the quick verdict by design.

**README**: the rules, the evidence layout and its limits, the new baseline figures, `golden_v1.5`.

`development` (AIML-3012, the confirmation classifier) is merged in. It changes none of this PR's files.

## Results on key v1.5

`extract()`, three repeats each, run `extract-20261118-132816`. "Before" is a fresh run of `development` on the same key.

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

Measured before the review fixes. Since then:
- **No result changes:** the sentence split is identical on all 90 notes, and the neighbouring-sentences rule rejects none of the run's 88 discussed topics or 38 kept codes when replayed on its saved sentence numbers.
- **One prompt change:** dropping the cue "quoted" changes both prompts. It is not re-measured yet; the agent before/after follows in the review thread.

Agent baseline (three full runs):

| Score | Range | Limit |
|---|---|---|
| Disposition | 80.0-85.2 | ±9 points |
| Topic status | 92.1-93.6 | ±5 points |
| Event type | 82.9-84.7 | ±5 points |
| Faithfulness | 73.9-80.2 | ±9.6 points |

## Known limits

- **What this branch gains, and what it does not**:
  - **Disposition:** the same as `development` (95.2% in both); the gain is against the agent (83.5%).
  - **What it brings:** evidence that cannot be misquoted, the business rules in the prompt, and event type +2.3 points.
  - **Trade-offs:** over-claimed 0 → 0.7% (1 of 102 in the last repeat). Topic status (99.5 → 99.2) and faithfulness (90.7 → 90.0) are slightly lower, within the run-to-run spread.
- **HL-005**: the key gives code 1 to a quote the customer asked for. By the business's answer and the prompts' own worked example that is 99, which both `extract()` and the agent now answer. To settle with the business.
- **The agent and `extract()` follow different rules, by design**:
  - **Topic and event-type rules:** the agent's prompt has the quote rule only, not the topic rule (material left) or the event-type rule, so key v1.5 counts those cases against it.
  - **Code 5:** "another brand preferred" is stated in neither prompt (code 5's cues are about vendors); both got it right on the golden set.
  - **MH-002** ("ownership wants a different brand"): the agent gives 99, the key says 7.
- **Sentence splitting**: evidence is no finer than a sentence. A note with no sentence end is one unit (30 of the 90 golden notes; 24 of them discuss no planned topic), so citing it counts for any topic. Splitting those on ";" or " - " would change 1 of the 30. "etc.", "a.m." and "p.m." still end a sentence.
- **Bracketed numbers**: a "[3]" typed in a dictation looks like a sentence number to the model. "Suite [2]" in a note of two or more sentences is removed with the sentence numbers. Spoken input has no brackets, so neither is expected live.
- **Cost**: about 7% more ($3.60 → $3.85 per 1,000 notes; 2,836 → 3,174 input tokens per note, from the numbered sentences and the rules). Per-call time varies by day (p95 6.7 s in the final run, 10.7 s in an earlier run of this branch before the quote rule, 8.9 s for `development`), so no speed difference is claimed.
- **Connection drops**: the agent runs lost 1-4 cases each to dropped connections, under the 10% limit.
- **Text, not speech**: the golden notes are typed text; spoken input is not measured.
- **For the live-flow story**: an unconfirmed topic keeps its summary for the rep's question; nothing yet stops it being saved as confirmed.

## How to check

    uv run pytest tests/ -q                                         # 424 passed, 1 xfailed with the golden data
    uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
    uv run python -m evals.agent_eval.run full

Data: `gs://sellntell-eval-np/golden_v1.5/` into `evals/v1/`.
````

**Replies.** Post one reply on each comment (Reply under it). Do not
resolve them; wait for Suresh to verify.

1. On **"`_no_line_refs` strips any `[digits]`"**:

```text
Fixed: a bracket is removed only when all its numbers are sentences of that note and it is not glued to a word. "PO [1234567]", "Qty [10-12] units" and "Model X[2]" now stay (test added).
```

2. On **"two non-adjacent one-word sentences pass `enough_words`"**:

```text
Fixed: the two words must sit in neighbouring sentences, for a topic's evidence and for a code's. "Pools. Interested." still passes, "Frank. ... Pools." does not (tests added). Replayed on the saved run's sentence numbers: no result changes.
```

3. On **"sentence splitter breaks on abbreviations"**:

```text
(a) Fixed: no split after Mr, Mrs, Ms, Dr, e.g., i.e., vs., approx.; the 90 golden notes split exactly as before. (b) Kept: splitting on ";" or " - " would change 1 of the 30 one-unit notes, and 24 of the 30 discuss no planned topic. Documented in the README.
```

4. On **"the bare cue `quoted` is risky"**:

```text
Dropped; "gave a quote" stays. 2 of the 3 golden notes with "quoted" are quotes for other products. Tests pin it for both prompts.
```

5. On the **review summary** (production impact and the fields FYI):

```text
Production impact: agreed. The quote cue is narrower now; a v1.5 agent run of development next to this branch will be added here. Fields FYI: by design, the agent's stage_visit_notes has no must_capture argument yet (the run report says "Not captured", README: 0% until the agent captures fields). field_invented_rate still catches the agent starting to fill fields.
```

Send a screenshot once the description and the replies are posted.

## Step 3 -- the measurements (only if the reviewer asks for them before approving)

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
