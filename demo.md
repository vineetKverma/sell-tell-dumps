# AIML-3152 -- what is left

No commands on the dev machine. The last step is in the browser, on the pull
request.

## Done

- `development` merged in; both review rounds fixed (`3bc5683`, `15a1bb2`);
  replies on all comments posted.
- `extract()` re-measured; agent `development` vs branch; agent baseline
  re-taken and committed (`1d97230`).
- The two misses explained by a focused experiment: HL-005 (the quote rule)
  and IS-010 (the topic rule). The business answers and the key correction go
  to a follow-up story, with the baseline re-run.

## Now: three things to send (any order), then Step F on the PR

### Step F1 -- the message to Jeremy (Teams, the chat with his earlier answers)

```text
Hi Jeremy, thanks again for the answers. Two follow-ups on quotes came out of testing them:

5. The customer asks for a quote on the campaign's products, but no quote has been given yet ("She asked me for a quote on the microwaves" or "He'll send me what he orders so I can quote it"). Create Opportunity, or needs review (99)?

6. The rep says they'll send a quote, but the customer didn't ask for one ("Went over the microwaves, I'll email her a quote"). Create Opportunity, or needs review (99)?

Something like "5: 1, 6: 99" works perfectly. Thanks!
```

### Step F2 -- the follow-up story (Jira, 3 points)

Title:

```text
Apply the product manager's quote answers and correct two answer-key labels; re-take the baselines
```

Description:

```text
Background
AIML-3152 left two golden topics where development scores higher than the branch. A focused experiment traced each to a case the rules don't settle yet:
- HL-005: a quote the customer asked for (key: code 1; the branch gives 99).
- IS-010: "Revisit <campaign>" with no conversation stated (key: discussed, code 3; the branch is split between discussed and not discussed).

Scope
1. Quote rule: apply the product manager's answers (a quote the customer asked for; a quote the rep offers to send) to extract()'s prompt and to the agent's behavioral_rules.yaml, and to the dispositions.yaml cue if needed.
2. Answer key v1.5, corrected in place:
   - IS-010 becomes not discussed, per the business answer on material left (discussed only when someone was spoken to about it);
   - HL-005 follows answer 5.
   Done with a fix script and a test, uploaded to the bucket, README updated.
3. Re-measure:
   - extract() golden run (3 repeats) against development;
   - three full agent runs and the baseline re-export;
   - the README baseline figures.

Acceptance criteria
- Both prompts state the same quote rule, with tests that include a negative control: a quote for other products, or the rep asking for an order, is never code 1.
- The rule experiment (tools/rule_probe.py) gets every written quote case right, including the two new ones, with no case flipping between repeats.
- Key v1.5 corrected; every saved run used in comparisons is re-scored on it.
- The extract() run and the new agent baseline are committed, with a before/after against development in the PR.
```

### Step F -- the PR description and the reply on the reminder

**PR description.** On the pull request, click Edit and select everything in
the description box. Paste the text inside the box below over it, then save.
The title stays.

````markdown
## What changes

**extract() (`app/extraction/`)**
- The note is shown as numbered sentences, run together as one text. The model returns sentence numbers for each topic's evidence and outcome, and code copies those sentences into the record. The model never types evidence, so it cannot misquote it. A number that is not a sentence of the note is ignored and kept as `ignored_lines`. `quote_in` and `evidence_ok` are removed.
- No sentence split after Mr, Mrs, Ms, Dr, e.g., i.e., vs., approx., sq. or ft., nor after "no." when a number follows ("PO no. 4567"); a bare "No." still ends a sentence. 1 of the 90 golden notes splits differently (HL-001, 4 units to 3).
- A topic's evidence, and a code's sentences, need two different non-filler words within neighbouring sentences. "Pools. Interested." passes; "Frank. ... Pools." (one word from each of two sentences far apart) does not.
- Sentence numbers never reach the record. In a summary or `executive_summary` (the model's own text) every bracketed number is removed, glued or not, in range or not ("shared[1]", "asked [7]"). In a field (the rep's values) only a bracket whose numbers are all sentences of that note and that is not glued to a word is removed, so "PO [1234567]", "Qty [10-12] units" and "Model X[2]" stay; a value that was only a number becomes null.
- The prompt states the business's answers:
  - a visit where the rep met a contact in person is a Meeting, even if the decision maker was phoned;
  - a topic is discussed only if the rep talked with someone at the customer about it, the customer's reaction included; material, a flyer or a voicemail left with no one spoken to is not discussed;
  - a quote the rep has given for that topic's products is code 1 (Create Opportunity); a quote for other products, or asking the customer to order, is not.
- U-04 and U-07 values start with the business category ("order placed: ...", "mispick: ...").

**This PR changes the live agent in production.** It reads the same outcome list and its own prompt:
- `dispositions.yaml`: code 1 is also cued by "gave a quote". "Send a quote", "interested" and the bare "quoted" stay out: "quoted" also fits a vendor's quote or a quote for other products (2 of the 3 golden notes with it).
- `behavioral_rules.yaml`: the same quote rule as `extract()`. With a cue alone, the agent gave code 1 to "will email quote" in some runs and not others.
- Measured below: the agent's disposition is the same on `development` and this branch.

**Answer key v1.5** (`gs://sellntell-eval-np/golden_v1.5/`): two topics where material was left with no one spoken to are now not discussed. 28 topics scored, was 30.

**Agent baseline** (`evals/baselines/golden_v1.json`): re-taken after the review fixes, three full runs of this branch on key v1.5. Every score is in the verdict.

**README**: the rules, the evidence layout and its limits, the new baseline figures, `golden_v1.5`.

`development` (AIML-3012, the confirmation classifier) is merged in. It changes none of this PR's files.

## Results on key v1.5, after all review fixes

`extract()`, three repeats each. "Before" is a run of `development` on the same key (`extract-20261116-230453`), "after" is this branch (`extract-20261120-113412`).

| Score | Before | After |
|---|---|---|
| Disposition | 80/84 = 95.2% | 79/84 = 94.0% |
| Topics right by majority | 27 of 28 | 26 of 28 |
| Topic status | 99.5% | 99.2% |
| Over-claimed | 0% | 0.3% (1 of 306) |
| Event type | 91.1% | 94.2% |
| Faithfulness | 90.7% | 89.6% |
| Invented fields | 1.6% | 1.3% |

By topic the two differ on 3 topics, not significant (p = 1.0). The branch gets MH-006 right (a quote given, code 1). `development` gets HL-005 and IS-010, both explained under the limits: each is a case the business has not ruled on yet, and each goes to the follow-up story.

The agent, one full run each on key v1.5: `development` and this branch both get 24 of 28 topics' disposition right (3 flips each way, p = 1.0; MH-006 right only on the branch). The branch run is PASS against the earlier baseline.

The new agent baseline (three full runs of this branch):

| Score | Mean | Range |
|---|---|---|
| Disposition | 85.7% | 24 of 28 in all three runs |
| Topic status | 92.0% | 91.5-92.3 |
| Event type | 84.1% | 82.6-86.0 |
| Over-claimed | 8.5% | 7.8-8.8 |
| Faithfulness | 77.2% | 71.9-79.8 |

Disposition did not move between runs, so its limit is the 5-point floor: a drop of 2 topics in 28 is a REGRESSION. The earlier baseline moved 80.0-85.2, so the README says to confirm a disposition-only REGRESSION with a second full run.

## Known limits

- **What this branch gains, and what it does not**:
  - **Disposition:** about the same as `development` (79 vs 80 of 84, p = 1.0); the gain is against the agent (85.7%).
  - **What it brings:** evidence that cannot be misquoted, the business rules in the prompt, and event type +3 points.
  - **Trade-offs:** over-claimed 0 → 0.3% (1 of 306). Topic status and faithfulness are slightly lower, within the run-to-run spread.
- **The two topics `development` gets and this branch does not** (5 of 84 repeats), measured with a focused experiment (5 repeats, one rule changed at a time):
  - **HL-005** (the customer will send items to be quoted; key: code 1). Cause: the quote rule here gives 99 to a quote not yet given. Saying "a quote the customer asked for is code 1" gives HL-005 code 1 in 5 of 5 and keeps every other quote case right, but also turns "I will email her a quote" (no one asked) into code 1 in 3 of 5. The business has answered only for a quote given; the two other cases are asked of the product manager.
  - **IS-010** ("Revisit <campaign>" with no conversation about it stated; key: discussed, code 3). Cause: the topic rule here, which needs someone at the customer to have talked about the campaign; `development`'s wording gets it 5 of 5 but marked a material-left topic discussed once. By the business's answer on material left (discussed only when someone was spoken to about it), the key's "discussed" is the one to correct.
  - **Follow-up story:** apply the product manager's answers to both prompts, correct both labels in key v1.5, re-run `extract()` and the agent baseline.
- **The agent and `extract()` follow different rules, by design**:
  - **Topic and event-type rules:** the agent's prompt has the quote rule only, not the topic rule (material left) or the event-type rule, so key v1.5 counts those cases against it.
  - **Code 5:** "another brand preferred" is stated in neither prompt (code 5's cues are about vendors); both got it right on the golden set.
  - **MH-002** ("ownership wants a different brand"): the agent gives 99, the key says 7.
- **HL-006** (a two-word note): the agent asks the rep a question and stages nothing, and the harness's scripted rep answers only after something is staged. NOT STAGED in all 9 agent runs, so it moves no comparison; changing the harness is its own ticket.
- **Sentence splitting**: evidence is no finer than a sentence. A note with no sentence end is one unit (30 of the 90 golden notes; 24 of them discuss no planned topic), so citing it counts for any topic. Splitting those on ";" or " - " would change 1 of the 30. "etc.", "a.m.", "p.m.", "Inc." and "St." still end a sentence; a sentence ending in "ft." runs into the next one.
- **Bracketed numbers**: in a summary every bracketed number is removed, so "Model X[2]" copied into a summary loses its "[2]". In a field, "Suite [2]" in a note of two or more sentences is removed with the sentence numbers. Spoken input has no brackets, so neither is expected live.
- **Cost**: about 7% more ($3.60 → $3.85 per 1,000 notes, measured before the review fixes; 2,836 → 3,174 input tokens per note, from the numbered sentences and the rules). Per-call time varies by day, so no speed difference is claimed.
- **Connection drops**: the agent runs lost 1-4 cases each to dropped connections, under the 10% limit.
- **Text, not speech**: the golden notes are typed text; spoken input is not measured.
- **For the live-flow story**: an unconfirmed topic keeps its summary for the rep's question; nothing yet stops it being saved as confirmed.

## How to check

    uv run pytest tests/ -q                                         # 424 passed, 1 xfailed with the golden data
    uv run python -m evals.extract_eval.run --model gemini-3.8-flash --thinking low --allow-labelling-model --dispositions
    uv run python -m evals.agent_eval.run full

Data: `gs://sellntell-eval-np/golden_v1.5/` into `evals/v1/`.
````

**Reply under Suresh's reminder** (production impact / re-take the baseline).
Reply under it; do not resolve it.

```text
Re-measured after both review rounds: extract() 79/84 vs development 80/84 (p = 1.0); agent 24/28 on both; baseline re-taken from three branch runs and committed. The two topics development gets (HL-005, IS-010) are traced to cases the business hasn't ruled on; they go to a follow-up story, details in the description.
```

Send a screenshot once the message, the story, the description and the reply
are posted (the story's number, so the description can name it), then wait
for Jeremy's answers and Suresh's "verified".
