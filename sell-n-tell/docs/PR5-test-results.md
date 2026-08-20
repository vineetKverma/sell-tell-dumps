# PR #5 — VDI test results

Run on the app machine, 2026-08-19/20, against the synced Section A fixes.
Method and commands: `PR5-vdi-test-plan.md`.

> **The verification scripts are deliberately not in the repo.** They existed to
> prove these ten fixes and are recorded here by their results, following the
> same precedent as the AIML-2703 orphan repro. `scripts/pr5/{a1_check.py,
> groupA_check.py, a6_a7_check.mjs, a9_check.py}` and
> `app/static/pr5-check.html` were removed before commit — the last of those
> especially, since it would otherwise ship to every deployment.
>
> `fix_mojibake.py` was kept at `tools/fix_mojibake.py`, outside the repo,
> alongside the export/import scripts whose bug it repairs.

---

## Phase 1 — offline suites ✅

| Suite | Result |
|---|---|
| `scripts/pr5/a1_check.py` | **13/13** |
| `scripts/pr5/groupA_check.py` | **19/19** |
| `/static/pr5-check.html` (browser) | **18/18** |

`a6_a7_check.mjs` not run — no Node on the app machine; the browser page is the
equivalent and is the stronger check for browser defects.

Notable evidence from `groupA_check.py`:

- A2 reproduced before asserting the fix — unlocked path **2 CRM records, peak
  concurrent stagings 2**; locked path **1 record, peak concurrency 1**.
- A6 measured — **14 stale samples** spliced into the next turn without the
  flush, **1** with it.

Browser context at time of run: `isSecureContext: true`,
`crypto.randomUUID: function` — i.e. the **secure** path. A7's failure case is
not covered here.

## Phase 2 — smoke suite ✅

```
implicit  6/6 scenarios committed
guided    4/4 scenarios committed
TOTAL 10 records · implicit 6 / guided 4 · no duplicate ws_session_id
```

No committed record carried missing topics. No `KeyError` (A5's retained record
did not break lookup). No unexpected `Commit BLOCKED`.

**`guided/rerecord` failed to commit on the first run and passed on an immediate
re-run with no code change.** Model non-determinism, same family as Gap 6/F5 —
not a regression. `ambiguous_disposition` passed first time. Both are now
documented as intermittent in `HANDOFF.md`.

Positive evidence in the `rerecord` transcript: the commit arrived on the
`record_topic_disposition` response (the inline-commit path), and the following
turn produced `INTERRUPTED`/`TURN_COMPLETE` with **no second tool call** — the
shape that previously risked a duplicate.

## Phase 3 — REST checks ✅

| Check | Item | Result |
|---|---|---|
| 3a | **A5** | Two commits of one `session_id` → same id `CRM-7F008BC91E`, count 10→11 (not 12). Previously the second call 404'd. |
| 3b | **A8** | Staged `standard_sales`, committed claiming `enterprise_field` → record keeps **`standard_sales`**. |
| 3c | **A4** | `/notes/confirm` on an incomplete record → **409** `{"error":"incomplete_coverage","missing_topics":["Mattresses"]}`. Previously a bare 500. |
| 3d | **A9** | `scripts/pr5/a9_check.py` **3/3** — blank frame produced 0 events / no model turn; the real turn that followed produced 145 events and 0 `no_reply_heard` responses. |

## Phase 4 — browser ✅

**A6 — the dropped tail. Confirmed on the real audio path.** Dictated a note
ending "…they placed an order next week. **Thanks Betty.**" The page provides
its own control: the Live Transcription "YOU" caption comes from the browser's
own recognizer reading the **raw mic**, while "Raw transcript" on the staged
card is what **Gemini** received through our resampler. The final word appears
in **both** — so the tail is no longer being dropped between them. That is the
same discrepancy that exposed the earlier aliasing bug (Gemini hearing "the t"
where the browser heard "Betty").

**A3 — back-to-back dictations. Confirmed.** Three dictations in one page load,
no reload between them, each saved:

| Record | Content | Disposition |
|---|---|---|
| `CRM-1597C46B51` | appliances, order placed | 2 — Order Placed |
| `CRM-8AE1A651F2` | wants to place an order next week | 1 — Create Opportunity |
| `CRM-72B47AF1B5` | wants to cancel and get a refund | 99 — manual review |

Three distinct ids, summaries and transcripts. The old behaviour replayed the
first id and staged nothing for the later visits.

**Run timers: 45.6s → 59.2s → 36.6s.** No consistent cold-start penalty from
A3's `session_id` rotation — milder than predicted. The PR reply should say the
socket is re-established per dictation rather than claiming a guaranteed 6-10s
hit.

**Incidental confirmation:** the cancellation came back as code 99, "outcome not
covered - needs manual review". Not a regression — it is the registry gap
(open decision #1) behaving correctly: no code expresses "order cancelled", so
the agent flags rather than inventing one. Useful evidence for that conversation
with the lead.

### Two defects found during phase 4, neither in the review

1. **Planning panel stayed locked after a save.** `startDictation` locks the
   topic checkboxes and only `endSession` unlocked them, so after a successful
   save the rep had to reload the page to plan a different call. Survivable
   while a second dictation in the same page wasn't a supported flow — A3's
   `session_id` rotation is what makes it one, so `finishSession` now calls
   `setPlanningEnabled(true)`. Fixed, `v=8`.
2. **The `?v=` cache-buster never covered the imported modules.** The VDI served
   `app.js?v=6` fresh (200, 65 kB) while `audio-recorder.js` came from disk
   cache (0 B) in the same load, despite the `no-store` middleware — so the A6
   fix could have been absent from the running page while `app.js` was
   demonstrably current. `app.js` now imports `audio-player.js?v=N` /
   `audio-recorder.js?v=N`. Fixed, `v=8`. Verified: all three now fetch with
   real byte counts.

### Also found and fixed: mojibake across the sync

`tools/import-repo-md.ps1` read the UTF-8 export with `Get-Content` and no
`-Encoding`, so PowerShell 5.1 decoded it as the ANSI codepage and every emoji
became mojibake (🎙️ → `ðŸŽ™ï¸`) on each import. The export side was already
correct; this was the one hop that wasn't. Fixed, plus
`scripts/pr5/fix_mojibake.py` to repair an affected tree (idempotent; clean
files are detected and skipped). Repaired `index.html`, `app.js` and
`style.css`.

## Phase 5a — A7 over plain HTTP ✅

**No second machine needed.** `localhost` is a secure context but the machine's
own LAN IP is not, so `http://10.250.200.109:8000` from the app machine's own browser is
the A7 case exactly.

`/static/pr5-check.html` over that origin — context panel:

| Field | via `localhost` | via LAN IP |
|---|---|---|
| `isSecureContext` | `true` | **`false`** |
| `crypto.randomUUID` | `function` | **`undefined`** |
| `navigator.mediaDevices` | `object` | **`undefined`** |
| `crypto.getRandomValues` | `function` | `function` |

**18/18 passed**, including `uuid() works in THIS context (NON-secure)`.

The app itself rendered completely at that origin — where before the fix it was
a blank page, `crypto.randomUUID()` having thrown at module load. Best single
piece of evidence: the header showed `Rep: rep-1869927c-eb…`. `localStorage` is
per-origin, so that id had to be minted on the spot — by the
`crypto.getRandomValues` fallback, in the real failure context.

### A defect this phase caught — the A7 fix was incomplete

Clicking the mic first produced **`Cannot read properties of undefined (reading
'addModule')`**, not the intended message.

**Cause:** `AudioWorklet` is secure-context-only too, and `ensureAudio()`
constructs the **player** worklet before the recorder. The HTTPS guard was in
`startAudioRecorderWorklet` — the second call — so it was never reached.

**Fix:** `ensureAudio()` now checks `window.isSecureContext` once, before
touching any audio API, covering all three secure-context dependencies
(`getUserMedia`, `AudioWorklet`, `crypto.randomUUID`). The recorder check stays
as a backstop. Deliberately not at module load — the page must still render over
plain HTTP, and this is the first point where the missing capability matters.
`v=9`. Re-tested: the banner now reads *"Microphone and audio playback require
HTTPS (or localhost)…"*, controls re-enable, timer stops.

**Worth recording why this was missed:** every prior test — phase 1's 18/18,
all of phase 4 — ran on `localhost`. The gap appeared the moment the code ran in
the context the finding was actually about. That is the same mistake that let A7
ship, caught this time.

What was already correct and what was not should be kept separate in the reply:

- **Correct as reported:** the page renders over plain HTTP and `uuid()`
  produces a real v4 there. A7 as Suresh raised it was fixed.
- **Wrong:** the failure message. Found here, not in review.

---

## Status by item

| Item | Proven | Where |
|---|---|---|
| A1 | mock backend only | phase 1 |
| A2 | ✅ | phase 1 (reproduced + fixed), phase 2 |
| A3 | ✅ | phases 1, 2, **4b** |
| A4 | ✅ | phases 1, 3c |
| A5 | ✅ | phases 1, 3a |
| A6 | ✅ | phases 1, **4a** |
| A7 | ✅ | phases 1, **5a** |
| A8 | ✅ | phases 1, 3b |
| A9 | ✅ | phase 3d |
| A10 | ✅ | phase 1 |

**All ten proven on the app machine.**

### Outstanding — one

**A1 against a real BigQuery dataset** (phase 5b). Gate inheritance is proven
against a stubbed client; a real insert is not. Repeat checks 3a/3b/3c with
`BIGQUERY_ENABLED=true`, a dataset and a table. Confirm one row lands per
committed record (not per commit *call*), and that a coverage-blocked commit
writes none.

If no dataset is available, the A1 reply must say the BigQuery path is verified
by delegation and stubbed-client assertions rather than implying a live insert
was observed.

### Regression check ✅

`http://localhost:8000` at `v=9`: full dictation → `CRM-06605C5FFE`, 42.2s,
Meeting / Appliance / code 1. The new `isSecureContext` guard is invisible in a
secure context, which is the only risk it introduced.

### Frontend version

Current: **`v=9`** in `index.html` and in `app.js`'s module imports. Bump both
together on any change to `app.js`, `audio-recorder.js` or `audio-player.js`.
