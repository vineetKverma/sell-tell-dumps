# AIML-2702 PR review: comments and fixes

Seven review comments (two blocking). Each row: the comment, what changed, and
the reply to post on its thread before resolving it.

| # | File | Severity | Comment (short) | Fix |
|---|---|---|---|---|
| 1 | `evals/v1/golden_v1.evalset.json` | **Blocking** | Real customer notes; drop from the PR, keep in an access-controlled bucket, rewrite branch history | `evals/v1/` git-ignored; README says where to get it; branch squashed so no commit holds the data |
| 2 | `run.py` `_sha256` | **Blocking** | Hash is of raw bytes; baseline only matches a CRLF checkout, so Linux/CI get INVALID | One helper hashes with `\r\n` → `\n`; used by `run.py`, `baseline.py` and the test; baseline hash refreshed |
| 3 | `run.py` | Major | `run1.jsonl` written only at the end; a crash loses a 90-minute run | Each case is appended as it finishes; an incomplete run is INVALID instead of scoring the cases it has |
| 4 | `baseline.py` `threshold_for` | Major | Quick-mode disposition limit is 55.5 points, so it can never fail | A metric whose noise limit is above 20 points is shown but left out of the verdict ("too noisy in this mode"); README says so |
| 5 | `drive.py` `_create_session` | Minor | Probe the session endpoint once before the run; `planned_topics` sent twice | One probe call before the first case, aborting with a clear message; `planned_topics` removed from the WebSocket query (the app only logs it) |
| 6 | `baseline.py` docstring | Minor | Refers to `run.py --compare`, which doesn't exist | Docstring says comparison is automatic and the verdict is in `final_scores.json` |
| 7 | `judge.py` docstring | Minor | Says the judge only runs with `--judge`; it always runs | Docstring says it runs in both modes and needs Vertex credentials |

## Replies

**1. Golden data in the repo**
> Agreed. `evals/v1/` is now git-ignored and removed from the PR, and the branch is squashed to one commit so no commit in it holds the data. The data is in `gs://sellntell-eval-np/golden_v1/` (`prj-hds-np-data`, versioned, uniform access, public access prevented); the README says to fetch it from there and place it at `evals/v1/` or point `SELLNTELL_EVAL_DATA` at it. Bucket access is limited to the eval team; note that project-level Storage roles still apply, so if it needs to be tighter than that it's a platform-team change.

**2. Dataset hash and line endings**
> Good catch, thanks. The hash now normalises `\r\n` to `\n` in one helper (`cases.dataset_sha256`) used by `run.py`, `baseline.py` and the test, and the baseline's `dataset_sha256` is refreshed. Added a test that the CRLF and LF copies hash the same. No `.gitattributes` line, since the data no longer lives in the repo.

**3. `run1.jsonl` written at the end**
> Fixed. Each case is appended to `run1.jsonl` as it completes; the retry pass rewrites the file at the end. A run with missing cases is reported as INVALID rather than scored on what it has, so a partial file can't pass. Resume is left for a follow-up story.

**4. Quick-mode disposition threshold**
> Agreed, it can't catch anything at that size. Any metric whose noise limit is above 20 points is now shown but left out of the verdict ("too noisy in this mode to judge"). Today that's quick-mode disposition only (about 9 topics across 18 cases). The README says quick mode doesn't judge disposition; full mode does (limit ±15).

**5. Session probe and `planned_topics`**
> Done. One probe `POST /api/sessions` before the first case: if the endpoint is missing or its response has no `session_id`, the run stops with a clear message instead of failing every case. The WebSocket query no longer carries `planned_topics`; on `development` the app only logs it, and the agent reads the list from session state seeded by the POST.

**6. `run.py --compare` in the docstring**
> Fixed, thanks.

**7. Judge docstring**
> Fixed: the docstring now says the judge runs in both modes and needs Vertex credentials.

## Round 2

| # | File | Comment (short) | Fix |
|---|---|---|---|
| 8 | `drive.py` | The probe leaves an orphan session per run | Probe removed; the first case's own session request stops the run if the endpoint is missing or changed |
| 9 | `run.py` | `--rescore` crashes on a cut-off last line | Unreadable lines are skipped with a warning; that case counts as never ran, so the run is INVALID |
| 10 | `test_agent_eval_regression.py` | Data tests skip in CI (follow-up) | README notes they run only where the data is fetched; follow-up story for a CI fetch |
| 11 | `baseline.py` | The noisy rule can silently drop any metric | `export` refuses a too-noisy metric unless `--allow-noisy`; the baseline records it; every run lists it under "not in the verdict" |

Replies:

- **8:** Fixed — removed the probe; the first case's session request now stops the run if the endpoint is missing or changed, so no extra session.
- **9:** Fixed — an unreadable line is skipped and that case counts as never ran, so the run is INVALID instead of crashing.
- **10:** Agreed — README now says these tests run only where the data is fetched; raised a follow-up for a CI fetch with a read-only service account.
- **11:** Fixed — `baseline export` refuses a too-noisy metric unless it's named with `--allow-noisy`, the baseline records it, and every run lists it under "not in the verdict" in `final_scores.json` and the scorecard header.

Follow-up story (for 10):

> **Eval: run the golden-data tests in CI**
> The scorer's main checks need the golden set, which is no longer in the repo, so they skip in CI. Add a CI step that fetches `gs://sellntell-eval-np/golden_v1/` with a read-only service account (workload identity if available) before the tests.
> AC: (1) CI fetches the data with a read-only identity; (2) the data-dependent tests run and pass in CI; (3) the fetched data is not kept as a build artifact.

## Applying it

1. Run the tests: `uv run pytest tests/ -q`.
2. Refresh the baseline hash: the numbers are unchanged, only the checksum
   method changed.
3. Squash the branch onto `development`, leaving `evals/v1/` out, then
   force-push and check the PR shows no `evals/v1/` files.
4. Post the replies above and resolve each thread.
