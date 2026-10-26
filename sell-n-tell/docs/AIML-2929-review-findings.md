# Review findings on the AIML-2928 / AIML-2929 branch — triage

An automated read-only review of the branch diff returned 10 findings. Each
was checked here against the code and, where it bears on a number, against
the data. **No code was changed**; this is the analysis and a proposed order.

| Verdict | Count | Findings |
|---|---|---|
| Valid — worth fixing before the PRs | 4 | 1, 2, 3, 4 |
| Valid but narrow — fix with the above, low risk | 3 | 5, 7, 8 |
| Already fixed elsewhere / by design | 1 | 6 |
| Valid only for other data / partly an artifact | 2 | 9, 10 |

**None of them changes the AIML-2929 result.** Finding 2 is the one that
needs a number put next to it (below); findings 3 and 4 were checked against
the reported runs and did not affect them.

## The findings

### 1. An empty record can be saved — `tools.py:127` — VALID (AIML-2928)

Confirmed by reading the path end to end. AIML-2928 removed the "no
discussion topics were provided" rejection so the agent can send an empty
list and let the coverage reminder ask the rep. That is right when there are
planned topics: `compute_missing_topics` then blocks the save until each is
addressed. But with **no planned topics** (`planned_topics=[]`) and
`topics=[]`, nothing is missing, validation passes and `commit_notes` saves a
record with no topics at all.

- **Impact:** only sessions started with no planned topics. Every row of the
  source export has planned topics, so rare in practice — but it is a
  regression AIML-2928 introduced.
- **Fix:** keep accepting an empty list when there are planned topics; reject
  it when there are none. One condition and one test. In the AIML-2928 PR.

### 2. The agent and the answer key use different event-type rules — `behavioral_rules.yaml:96` — VALID, the important one

Confirmed. Three places state the rule, and they are not the same:

| Where | Rule for Meeting |
|---|---|
| Agent prompt (AIML-2928) | "the rep mentions a **person** they met or spoke with, by name or by role" — otherwise On-site |
| Answer key v1.2 / v1.3 | **any interaction**, named or not ("we discussed the order") |
| `extract()` prompt (AIML-2929) | any interaction, named or not |

So on the 7 "interaction, nobody named" cases (HL-010, HL-015, HS-003,
IN-009, IN-015, MH-006, TR-007) an agent that follows its own prompt answers
On-site visit and is marked wrong. Two consequences:

- The agent's event-type baseline (80.5%) is depressed by up to 7 of 87
  cases (about 8 points) by a rule mismatch, not by the agent.
- The event-type comparison (agent 80.5% vs `extract()` 93.9%) mixes two
  things: a better architecture and a different rule. Part of that gap is
  the rule.

What still holds: topic status, over-claiming, faithfulness and fields do
not depend on the event-type rule, and that is where the result rests. On the
original key (v1.1), where neither side had this mismatch, the 3.7-flash run
still beat the agent on event type (80.8% vs 74.7%).

- **To put a number on it (read-only):** list how the agent and `extract()`
  answered those 7 cases — command under "Checks to run".
- **Fix:** one rule in all three places, decided by Jeremy's answer. If
  "any interaction" stands: change the agent prompt (and its test) to match.
  If "named or by role" stands: rebuild the key with `--named-only` and
  change the `extract()` prompt. Either way, state in the report that the
  event-type gap includes the rule difference until then.

### 3. The evidence check is easy to satisfy — `extract.py` `quote_in` — VALID

Confirmed by running it: on a real note, `"a ... e ... i ... o"` and
`"s ... h ... a ... r"` both pass, and `"units ... Shared"` passes although
the words are in the wrong order. The check requires each fragment around an
ellipsis to appear somewhere in the note, in any order, with no minimum per
fragment and no word boundaries — only 4 characters in total.

- **Impact on the reported numbers:** the check is there to stop a campaign
  being kept as discussed without the rep's words. Over-claiming measured 0%
  on every 3.x run, so it was not exploited there; but that is the model
  behaving, not the check holding. As a guard it is weak.
- **To confirm on the real runs (read-only):** the shortest evidence and how
  many use an ellipsis — command below.
- **Fix:** each fragment at least a few words (or N characters), matched on
  word boundaries, in the order they appear in the note. With tests for the
  cases above. In AIML-2929.

### 4. Failed calls are scored as misses — `extract_eval/run.py` — VALID

Confirmed: a failed `extract()` call is scored as "not staged" and stays in
the means. The agent harness excludes such cases; this runner does not. A
run with up to 10% failed calls counts as valid, and its scores would drop
for reasons unrelated to the model.

- **Impact on the reported numbers: none.** All five reported runs had 0
  schema or call errors (the `compare` table, read from the runs' files).
- **Fix:** leave failed calls out of the scores and report them, as the
  agent harness does. In AIML-2929.

### 5. A count written in words is dropped — `extract.py` — VALID, narrow

Confirmed: `U-10 = "twelve units"` has no digit and becomes blank. Reps
mostly write digits, and the check exists to drop values like "turns"; but a
spelled-out number is a real count. **Fix:** accept number words as well as
digits. In AIML-2929.

### 6. One 4xx aborts the whole run — `drive.py:137` — ALREADY FIXED / BY DESIGN

On this branch a 408 or 429 does stop the run. That was raised in the PR #10
review and fixed there (`833a4ec`: 408 and 429 are retried like a 5xx); this
branch gets it when it is rebased after PR #10 merges. A 401 or 403 stopping
the run is intended — the reviewer of PR #10 asked for exactly that.
**Nothing to do here** beyond the rebase.

### 7. `--rescore` loses information — `extract_eval/run.py` — VALID, cosmetic

Confirmed: after a re-score the scorecard header no longer says
"(thinking: low)", because the setting is not read back from the saved run.
The saved `summary.json` does keep it (the `compare` table shows "low" for
the two low-thinking runs), so the report was not affected. A set with no
raw files would also be dropped from the summary; that does not happen in a
normal run. **Fix:** restore the run's settings on a re-score. In AIML-2929.

### 8. `extract()` can raise despite "never raises" — `extract.py` — PARTLY VALID

- The specific example does not happen: an unknown thinking level is
  accepted by the SDK with a warning and rejected by the API, which the run
  reports as INVALID (as it did for `minimal`).
- The structural point stands: the schema and thinking setup run before the
  `try`, so an error there would propagate.
- Duplicate planned titles do produce duplicate rows (confirmed). No golden
  case has duplicate planned titles.

**Fix:** move the setup inside the `try`; de-duplicate planned titles. Low
risk, in AIML-2929.

### 9. The contact-outcome key script's blank check — `fix_contact_outcome.py` — VALID FOR OTHER DATA

Confirmed in the code: a U-02 of "not stated" is not treated as blank, and a
record with `must_capture: null` would raise. **Checked against the golden
set: neither occurs** (U-02 is blank, "spoke with target", "spoke with
alternate" or "no contact"; every case has its fields). So key v1.3 is
correct. It matters before the script is run on the top-up or synthetic
sets. **Fix then**, with the same blank test the scorer uses.

### 10. The dependency-pinning comment — `pyproject.toml:10` — PARTLY AN ARTIFACT

- "uv.lock is untracked" is true of the copy that was reviewed, not of the
  repository: there `uv.lock` is tracked and was updated in AIML-2928.
- The ADK version itself is pinned everywhere (`google-adk[gcp]==2.10.0`),
  which is what the comment claims.
- What is true: the Dockerfile runs `pip install .`, so the image does not
  use the lockfile and transitive dependencies can float. That is known and
  was handed to the team (noted in the AIML-2928 PR text).

**Fix:** reword the comment so it does not claim the image uses the lock.
One line, in AIML-2928.

## Status

Fixed after this triage (each with a test that fails when the fix is undone):

| # | Fix | Branch |
|---|---|---|
| 1 | An empty topic list is refused when nothing was planned; still accepted, with the reminder, when there are planned topics | AIML-2928 |
| 10 | **Not applied.** `pyproject.toml` is managed with uv and is not hand-edited, even for a comment. The fact itself (the image runs `pip install .`, not the lockfile) is stated in the AIML-2928 PR text | — |
| 3 | Evidence fragments need whole words, at least 4 letters or digits each, in note order | AIML-2929 |
| 4 | Failed calls are left out of the scores and counted | AIML-2929 |
| 5 | A count in words ("twelve units", "a dozen") is kept | AIML-2929 |
| 7 | A re-score keeps the run's thinking level, location and its other sets | AIML-2929 |
| 8 | Setup is inside the error handling; a title planned twice is one topic | AIML-2929 |
| 9 | The contact-outcome script uses the scorer's meaning of blank and tolerates missing fields; key v1.3 checksum unchanged (`1f0cbbc0…`) | AIML-2929 (dataset tooling) |

Settled since: **2** — the business confirmed the rule (2026-10-14); the
key (v1.4) and `extract()` follow it, and the agent's prompt keeps its earlier
rule after measurement. **6** came with the rebase after PR #10. The evidence check (3) is stricter than the one
the reported runs used; a re-run of the chosen configuration confirmed the
numbers (`extract-20261013-200024`: topic status 95.6%, over-claimed 0%,
unconfirmed 0.3 per run, 0 errors — within run-to-run variation).

## Round 2 — seven more findings

A second pass (and the PR #10 reviewer independently, for the first) found
seven more. All valid; all fixed, each with a test that fails when the fix is
undone.

| # | Finding | Verdict and fix | Branch |
|---|---|---|---|
| R1 | `quick --rescore <full run>` cut `run1.jsonl` from 90 rows to 18 and replaced the full run's scores, verdict and scorecard | **Valid — data loss.** A re-score now writes to `<run>/rescore-<mode>/` and never rewrites the run's own files. A baseline exported from a rescore folder names the run | AIML-2702 (PR #10) |
| R2 | `extract_eval --rescore` rewrote the raw record files with only the rows in the currently loaded set | **Valid.** A re-score no longer writes the raw files at all (the records did not change) | AIML-2929 |
| R3 | `planned_topics: [""]` switched the empty-record guard off | **Valid.** A blank label (`""`, spaces, null) is not a plan | AIML-2928 |
| R4 | The contact-outcome key script treated a Phone Call as a conversation ("called, left a voicemail") | **Valid for future keys.** Now Meeting only; a call keeps a blank U-02 until read. Golden v1.3 is unchanged (checksum `1f0cbbc0…`, the same 21 cases — none was a call) | AIML-2929 (dataset tooling) |
| R5 | That script could be run on its own output, replacing the manifest's case list with an empty one | **Valid.** It refuses a key that already carries the target version, and writes nothing when no case changes | AIML-2929 (dataset tooling) |
| R6 | A key of "spoke with alternate" accepted an answer of "spoke with contact" | **Valid.** Only a key of "spoke with contact" accepts either; a key that names target or alternate must be matched. Slightly lowers field value accuracy; no headline number depends on it | AIML-2929 |
| R7 | The registry damage map, repair and short description existed twice | **Valid (maintenance).** One source in `app/extraction/campaigns.py`; the curation tools import it | AIML-2929 |

Workflow change from R1: after the 2928 / 2929 branches are rebased onto the
merged PR #10, re-scoring an agent run for a new baseline writes to
`<run>/rescore-full/`, and that folder is what `baseline export` takes.

## Round 3 — fifteen more findings

Each was checked against the code. Thirteen are valid, two are valid in
principle but cannot happen with today's data (14, 15). The reported runs had
0 errors, so 1 and 5 change no reported number. The chosen run had 0.3
unconfirmed topics per run — one topic in three runs — so the evidence check
(8) can have cost at most that one. Whether any summary went unjudged (2) is
not recorded in the saved runs; the re-score under "Checks" below prints it.

| # | Finding | Verdict and fix | Branch | Status |
|---|---|---|---|---|
| 1 | A reply that does not fit the schema was left out of the scores like a network failure | **Valid.** `extract()` now says which kind of error it is. A failed call is still left out; a reply that is not a record is scored as a miss (as an agent that never staged). Only failed calls count towards INVALID | AIML-2929 | Fixed |
| 2 | A failed judge call was dropped with no count or limit | **Valid.** Unjudged summaries are counted on the scorecard and in `summary.json`; above 10% (the agent harness's limit) faithfulness is shown but not compared. A re-score still cannot re-judge — it makes no model call by design | AIML-2929 | Fixed |
| 3 | `summary.json` was written only after the last set | **Valid.** A missing set now stops the run before any call, and the summary is written after every set | AIML-2929 | Fixed |
| 4 | A run where no case is scored ends in a `KeyError` (exit 1, read as REGRESSION) | **Valid.** Happens when every case hits a connection error. Now ends INVALID (exit 2), and `final_scores.json` says no case was scored | AIML-2702 (PR #10, `7ec9c98`) | Fixed |
| 5 | Cost and latency included failed calls | **Valid.** Per-note tokens, cost and the latency percentiles are over the calls the model answered | AIML-2929 | Fixed |
| 6 | Over-claiming counts only a row under the exact planned label | **Valid — the agent's 27.3% is a lower bound.** An over-claim under a paraphrased label, or as duplicate rows, is not counted. `extract()` cannot produce either (labels are an enum, duplicates are merged), so its 0% is exact. Not changed in the scorer: that would redefine a baseline metric. Stated in the report instead, with the agent's duplicate and off-plan row counts | Report | Fixed (round 4: in both reports) |
| 7 | U-02: "Spoke with the target" wrong against "spoke with target"; "Spoke with Rachel, the property manager" wrong against "spoke with contact" | **Valid.** "the" is ignored; a key of "spoke with contact" accepts any answer that says the rep spoke with someone. Field value accuracy only | AIML-2929 | Fixed |
| 8 | The evidence check rejected a verbatim quote when the rep's own note has an ellipsis | **Valid — a regression from round 1's stricter check.** A quote found whole in the note passes before any splitting | AIML-2929 | Fixed |
| 9 | `summary.json` stored only the golden key's checksum | **Valid.** Each set records its own `key_sha256`; `compare` shows it | AIML-2929 | Fixed |
| 10 | `baseline export` stamps the current key's checksum without checking each run's | **Valid.** Each run's `final_scores.json` has the checksum it was scored on; export refuses a run scored on another key, or one with no `final_scores.json` | AIML-2702 (PR #10, `7ec9c98`) | Fixed |
| 11 | "topics lists ONLY the planned topics the rep actually discussed" reads against the older rule to add a `discussed=false` entry after a reminder | **Valid as wording.** The two rules apply at different steps (first record; after a reminder), and the measured runs did save, so the model reads it as intended. One clause makes it explicit. A prompt change, so it is measured before it is kept: it goes in with the event-type rule change (finding 2 of round 1), so one full run covers both | AIML-2928 | Resolved: measured, the clause was dropped |
| 12 | The app's copy of the session write path has no retry on HTTP 429 | **Valid.** ADK 2.10 retries the append once after 1 s on a 429; the app's copy logged a warning and dropped the event. It now does the same one retry | AIML-2928 (`987cb52`) | Fixed |
| 13 | `extract()` could still raise | **Valid.** `planned=None`, the usage read and settling the record are now inside the error handling | AIML-2929 | Fixed |
| 14 | Two planned titles that differ only in case collapse to one | **Valid, not reachable today** (no two registry titles collide). The exact title is matched first | AIML-2929 | Fixed |
| 15 | Two versions of a top-up key in one folder are both loaded | **Valid, not reachable today.** Each case id is loaded once, from the later file, with a note | AIML-2929 | Fixed |

Smaller items: the compare table survives a multi-line error message; the
contact-outcome script leaves an unchanged case exactly as it was; the
registry loader refuses a file without its three columns. Not changed: the
coverage count (it counts registry matches, not non-empty descriptions) and
the labelling-model check (now a scorecard note only).

Each fix has a test that fails when the fix is undone (12 new tests on this branch, 2 on PR #10, 3 on AIML-2928).

### Checks for round 3 (read-only, on the machine with the runs)

Did any summary go unjudged in the chosen run (2)? Re-score it and read
"Summaries not judged" in the header line:

```powershell
uv run python -m evals.extract_eval.run --rescore evals/runs/extract-20261013-200024
```

Which topic the evidence check left unconfirmed (8) — if its case is one of
the two notes with an ellipsis, a fresh run would now confirm it:

```powershell
uv run python -c "import json, glob
for f in sorted(glob.glob('evals/runs/extract-20261013-200024/raw_golden_r*.jsonl')):
    print(f[-9:], [(r['id'], r['unconfirmed']) for r in map(json.loads, open(f, encoding='utf-8')) if r['unconfirmed']])"
```

The agent's duplicate and off-plan rows (6) — the over-claims the 27.3% does
not count:

```powershell
uv run python -c "import json
for d in ('full-20261009-210636',):
    r = json.load(open(f'evals/runs/{d}/scores.json', encoding='utf-8'))['runs'][0]['all']
    print(d, 'duplicate rows:', r['duplicate_rows'], ' off-plan rows:', r['off_plan_rows'], ' over-claimed:', r['over_claimed'])"
```

## Round 4 — three more findings

All three are in AIML-2929-only code, so PR #10 and AIML-2928 are not
touched. All valid; all fixed, each with a test that fails when the fix is
undone. No reported number changes (every reported run had 0 errors).

| # | Finding | Verdict and fix |
|---|---|---|
| R4-1 | Round 3's fix (1) put reading usage and settling the record inside the error labelled "reply", so a bug in our own code would be scored as the model's miss on every case and never make the run INVALID | **Valid — a gap in our round-3 fix.** "reply" is now only a reply that does not parse into the schema. Our own code failing after a valid reply is "internal": left out of the scores and counted towards INVALID, like a failed call |
| R4-2 | U-02: "spoke with no one" and "spoke to nobody" counted as a conversation; "spoke with the target's assistant" read as the target | **Valid.** Read as no conversation, and as "someone" (accepted against "spoke with contact", not against "spoke with target"). Field value accuracy only |
| R4-3 | Round 3's fix (15) kept one case per id across the top-up files, the later file winning — but `golden_topup_v1..v3` are three rounds of different notes, not versions of one key | **Valid — round-3 finding 15 misread the files, and the fix followed it.** Every file is loaded again; an id in two files stops the run before any call (a data mistake, never resolved quietly). Check: `uv run python -c "from evals.extract_eval.run import set_cases; print(len(set_cases('topup')))"` prints 65 |

Carried over: finding 6 (the agent's over-claim figure is a lower bound) is
now stated in `AIML-2929-model-comparison.md` and
`AIML-2929-results-summary.md`. Finding 11 stays deferred to the event-type
rule change.

## Order of the fixes

Done: everything above is fixed or settled, except 9, which waits for a
review of the top-up and synthetic keys.

## Checks to run (read-only, on the machine with the runs)

How the agent and `extract()` answered the 7 "nobody named" cases
(finding 2):

```powershell
uv run python -c "import json; ids=['HL-010','HL-015','HS-003','IN-009','IN-015','MH-006','TR-007']
for label, f in (('agent  ', 'evals/runs/full-20261009-210636/scores.json'), ('extract', 'evals/runs/extract-20261012-225347/scores_golden.json')):
    last = json.load(open(f, encoding='utf-8'))['cases'][-1]
    print(label, {s['id']: (s['event_type'] or {}).get('actual') for s in last if s['id'] in ids})"
```

The evidence the model actually gave (finding 3): shortest quotes and how
many use an ellipsis.

```powershell
uv run python -c "import json; rows=[json.loads(l) for l in open('evals/runs/extract-20261012-225347/raw_golden_r1.jsonl', encoding='utf-8')]
ev=[t['evidence'] for r in rows for t in (r['record'] or {}).get('topics', []) if t['status']=='discussed']
print(len(ev), 'discussed topics; shortest evidence lengths:', sorted(len(e) for e in ev)[:8]); print('with an ellipsis:', sum('...' in e or chr(8230) in e for e in ev))"
```
