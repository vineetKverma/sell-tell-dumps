# AIML-3152 on the dev machine -- what is left

Done: the commit `52ea954` is pushed to `feature/AIML-3152-extract-followup`;
key v1.5 is in `gs://sellntell-eval-np/golden_v1.5/`.

Do the steps in order. Do not start a step until the one before it is confirmed.

## Step 1 -- upgrade Git (Bitbucket blocks this Git Credential Manager on November 30, 2026)

```powershell
winget upgrade --id Git.Git -e
```

Close the terminal, open a new one, then:

```powershell
git --version
git credential-manager --version
```

The credential manager must be 3.0.0 or newer. Send the output and wait.

## Step 2 -- open the pull request

Open this link; the target branch must be **development**:

https://bitbucket.org/fm_ebiz/sell-n-tell/pull-requests/new?source=feature/AIML-3152-extract-followup&t=1

Before pasting, check the `extract()` command under "How to check" against the
one used for the extract runs, and adjust it if it differs.

**Title** (copy the line):

```text
AIML-3152: extract() evidence by sentence number; rules per the business answers; answer key v1.5
```

**Description** (copy everything inside the box):

````markdown
## What changes

**extract() (`app/extraction/`)**
- The note is shown as numbered sentences, run together as one text. The model returns sentence numbers for each topic's evidence and outcome; code copies those sentences into the record. The model never types evidence, so it cannot misquote it. A number that is not a sentence of the note is ignored and kept as `ignored_lines`. `quote_in` and `evidence_ok` are removed.
- The prompt states the business's answers:
  - a visit where the rep met a contact in person is a Meeting, even if the decision maker was phoned;
  - a topic is discussed only if the rep talked with someone at the customer about it, the customer's reaction included;
  - material, a flyer or a voicemail left with no one spoken to is not discussed;
  - another brand or vendor preferred is discussed, code 5;
  - a quote the rep gave is code 1.
- U-04 and U-07 values start with the business category ("order placed: ...", "mispick: ...").

**Outcome list (`dispositions.yaml`)**: code 1 is also cued by "gave a quote" and "quoted". "send a quote" and "interested" stay out.

**Live agent (`behavioral_rules.yaml`)**: code 1 is a quote already given for that topic's products. A quote to be sent later, a quote for other products, or asking for an order is not code 1. With the cue alone, the agent gave code 1 to "will email quote" in some runs and not others, and its disposition moved 21–26 of 28 topics across identical runs.

**Answer key v1.5** (`gs://sellntell-eval-np/golden_v1.5/`): two topics where material was left with no one spoken to are now not discussed. 28 topics scored, was 30.

**Agent baseline** (`evals/baselines/golden_v1.json`): three full runs on key v1.5 with the quote rule. Quick-mode disposition (9 topics, one topic = 11 points) is out of the quick verdict by design.

**README**: the rules, the evidence layout, the new baseline figures, `golden_v1.5`.

## Results on key v1.5

`extract()`, three repeats each. "Before" is a fresh run of `development` on the same key.

| Score | Before | After |
|---|---|---|
| Disposition | 95.2% | 97.6% (82/84) |
| Topic status | 99.5% | 99.2% |
| Over-claimed | 0% | 0.3% (one topic, 1 of 3 repeats) |
| Event type | 91.1% | 91.9% |
| Faithfulness | 90.7% | 88.2% |
| Invented fields | 1.6% | 1.1% |
| Cost per 1,000 notes | $3.60 | $3.82 |
| p95 per call | 8.9 s | 10.7 s |

Agent baseline (three full runs):

| Score | Range | Limit |
|---|---|---|
| Disposition | 80.0–85.2 | ±9 points |
| Topic status | 92.1–93.6 | ±5 points |
| Event type | 82.9–84.7 | ±5 points |
| Faithfulness | 73.9–80.2 | ±9.6 points |

## Known limits

- **Faithfulness** is 2.5 points lower. The difference is not significant (p = 0.51). The judge's objections are mixed: an added purpose or result in 3 cases, one wrong name, the rest strict readings.
- **Speed and cost:** p95 is 1.8 s slower and cost is $0.22 per 1,000 notes higher.
- **Sentence granularity:** evidence is no finer than a sentence. 30 of the 90 notes have no sentence end, so the whole note is one unit.
- **Quotes only asked for:** a quote the customer only asked for has no code (99).
  - HL-005 (a quote request) is code 1 in the key, against the prompt's own worked example. To settle with the business.
- **Agent misses:**
  - MH-002 ("ownership wants a different brand"): the agent gives 99, the key says 7.
  - A few topics move by one item between runs, inside the limit.
- **Agent prompt:** it states only the quote rule, not the topic and event-type rules. On those, the key scores the agent against rules it was not given.
- **Connection drops:** agent runs had 1–4 per run, under the 10% limit.
- **Text, not speech:** the golden notes are typed text; spoken input is not measured.

## How to check

    uv run pytest tests/ -q                                         # 345 passed, 1 xfailed with the golden data
    uv run python -m evals.extract_eval.run --model gemini-3.8-flash --allow-labelling-model --dispositions
    uv run python -m evals.agent_eval.run full

Data: `gs://sellntell-eval-np/golden_v1.5/` into `evals/v1/`.
````

Send the pull request link once it is open.
