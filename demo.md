# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`.

Done: `development` merged in (`028730b`), the review fixes pushed (`3bc5683`),
the PR description and the replies posted, and the measurements:

- `extract()`: `extract-20261119-175710`, disposition 77/84, 27 of 28 by
  topic, MH-006 right in all 3 repeats, over-claimed 1 of 306.
- The agent, `development` `full-20261119-182215` vs the branch
  `full-20261119-234138`: disposition 24/28 both, 3 topics flip each way
  (p = 1.0), MH-006 right only on the branch; the branch run is PASS against
  the baseline.

Nothing is left to run on the dev machine.

## Step 1 -- the reply on the review summary (the production question)

Post as a reply to Suresh's review summary:

```text
Measured after the fixes (one full agent run each, key v1.5): development and this branch both score disposition 24/28, 3 topics flip each way (p = 1.0), and MH-006 (a quote given) is right only on this branch; the branch run is PASS against the baseline, every score within noise. extract(): disposition 77/84, 27 of 28 by topic, over-claimed 1 of 306.
```

Then wait for Suresh's "verified" before resolving anything.
