# PR #5 — VDI sync + test plan (Section A)

What to copy to the app machine and how to prove each of A1–A10 there.

Run the phases in order — a failure in phase 2 makes phases 3-5 meaningless.
Do not post the Section A replies until phase 5 is green.

---

## Phase 0 — files to copy

### Code — 8 files, all required

```
app/main.py
app/static/index.html
app/static/js/app.js
app/static/js/audio-recorder.js
app/voice_notes_agent/bigquery_db.py
app/voice_notes_agent/db_interface.py
app/voice_notes_agent/mock_db.py
app/voice_notes_agent/tools_guided.py
```

`index.html` is a one-character change (`app.js?v=5` → `?v=6`) but **do not skip
it** — without the bump the browser keeps running the old `app.js` and phases
4-5 test nothing.

### Docs — 4 files, optional for testing

```
docs/HANDOFF.md
docs/PR5-review-findings.md
docs/PR5-response.md
docs/PR5-comment-replies.md
docs/PR5-vdi-test-plan.md     (this file)
```

### Verification scripts — 3 files

From the scratchpad, into `scripts/pr5/` on the app machine:

```
a1_check.py        -> scripts/pr5/a1_check.py
groupA_check.py    -> scripts/pr5/groupA_check.py
a6_a7_check.mjs    -> scripts/pr5/a6_a7_check.mjs
```

They stub `google.adk`, `httpx` and the BigQuery client by inserting into
`sys.modules` **before** importing, so they behave identically on the app machine even
with the real packages installed. Run them from the repo root, not from
`scripts/pr5/`.

### Not changed — do not copy

`tools.py`, `agent.py`, `agent_guided.py`, `turn_guard.py`, `config.py`,
`bigquery_sink.py`, `ws_smoke_test.py`.

---

## Phase 1 — automated suites (~2 min)

From the repo root:

```powershell
uv run python scripts/pr5/a1_check.py
uv run python scripts/pr5/groupA_check.py
```

Expect `13/13` and `19/19`.

**A6/A7 (18 assertions) run in the browser, not Node** — the app machine has no `node`.
With the server up (phase 2), open:

```
http://localhost:8000/static/pr5-check.html
```

It fetches the real `audio-recorder.js` and `app.js`, lifts the two private
functions out of them, and runs the same assertions on a real browser engine —
a stronger check than Node was. Expect `18/18`.

`scripts/pr5/a6_a7_check.mjs` is the Node equivalent, kept for machines that
have it. Either one is sufficient; don't run both.

Covers **A1, A2, A3, A4, A5, A8, A10** fully, and the logic of **A6, A7**.
Everything after this phase is about the things a stub cannot prove.

---

## Phase 2 — regression: existing smoke suite (~15 min)

Start the server in its own window. **No `--reload`** — a file save drops every
live WebSocket and wipes the session store.

```powershell
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then:

```powershell
uv run python scripts/ws_smoke_test.py implicit   # 6 scenarios
uv run python scripts/ws_smoke_test.py guided     # 4 scenarios
```

Bar: every scenario commits, one CRM record each, no duplicates.

`guided/ambiguous_disposition` is intermittent (~2 in 3) — re-run it before
calling a failure a regression:

```powershell
uv run python scripts/ws_smoke_test.py guided --scenario ambiguous_disposition
```

**Watch for two things specifically**, since A3 and A5 changed session/store
lifetime:

- the guided run still commits once per scenario (A3's reset didn't over-fire)
- no `KeyError`/404 on any commit (A5's retained record didn't break lookup)

---

## Phase 3 — REST checks the smoke suite doesn't reach (~10 min)

Server running, no mic, no model. PowerShell.

```powershell
$B = "http://localhost:8000/api/v1"

function Stage($planned, $topics, $campaign = "standard_sales") {
  $body = @{
    event_type            = "Meeting"
    executive_summary     = "Test visit summary."
    raw_transcript_backup = "test transcript"
    topics                = $topics
    planned_topics        = $planned
    campaign_type         = $campaign
  } | ConvertTo-Json -Depth 6
  Invoke-RestMethod -Uri "$B/notes/stage" -Method Post -Body $body -ContentType "application/json"
}

function T($name, $code = 1) {
  @{ topic = $name; disposition_code = $code; executive_summary = "s"; discussed = $true }
}
```

### 3a. A5 — retry replays instead of 404ing

```powershell
$s = Stage @("Appliances") @((T "Appliances"))
$c = @{ session_id = $s.session_id; confirmed = $true } | ConvertTo-Json
$r1 = Invoke-RestMethod -Uri "$B/notes/commit" -Method Post -Body $c -ContentType "application/json"
$r2 = Invoke-RestMethod -Uri "$B/notes/commit" -Method Post -Body $c -ContentType "application/json"
$r1.crm_record_id; $r2.crm_record_id
(Invoke-RestMethod -Uri "$B/notes/committed").records.Count
```

**Pass:** both ids identical, count is 1.
**Before the fix:** the second call returned 404.

### 3b. A8 — staged campaign wins over the one claimed at commit

```powershell
$s = Stage @("Appliances") @((T "Appliances")) "standard_sales"
$c = @{ session_id = $s.session_id; confirmed = $true; campaign_type = "enterprise_field" } | ConvertTo-Json
Invoke-RestMethod -Uri "$B/notes/commit" -Method Post -Body $c -ContentType "application/json" | Out-Null
(Invoke-RestMethod -Uri "$B/notes/committed").records[-1].campaign_type
```

**Pass:** `standard_sales`. Server log shows
`was staged under campaign_type=standard_sales but the commit claims enterprise_field`.

### 3c. A4 — `/notes/confirm` returns 409, not 500

```powershell
$s = Stage @("Appliances","Mattresses") @((T "Appliances"))   # Mattresses uncovered
$body = @{ session_id = $s.session_id; action = "save" } | ConvertTo-Json
try {
  Invoke-RestMethod -Uri "$B/notes/confirm" -Method Post -Body $body -ContentType "application/json"
} catch {
  $_.Exception.Response.StatusCode.value__
  $_.ErrorDetails.Message
}
```

**Pass:** `409`, body carries `"error":"incomplete_coverage"` and
`"missing_topics":["Mattresses"]`.
**Before the fix:** 500 `{"error":"Internal server error"}`.

Also confirm the response body of a *successful* confirm has no `_record` key.

### 3d. A9 — blank text is dropped

Send a whitespace-only text frame over the WebSocket (easiest by editing a
`ws_smoke_test.py` scenario to send `"   "` as one turn, or via a scratch WS
client). **Pass:** server log shows `Dropping blank text message (session_id=…)`
and the model takes no turn for it. The tool that follows must not report
`no_reply_heard`.

This is the one item with no automated coverage.

---

## Phase 4 — browser checks (~15 min)

Hard-reload first (Ctrl+F5). `index.html` is bumped to `?v=6`, but
**`audio-recorder.js` has no version query** — it relies on `no-store`, so
confirm in DevTools → Network that it fetched fresh. If an old service worker is
still installed in that profile, unregister it (Application → Service Workers).

### 4a. A6 — the last syllable survives

Dictate a note ending in a short, distinctive final word — e.g.
"…and they agreed to the renewal, **Betty**". End by pausing, not by clicking
stop, then repeat clicking stop.

**Pass:** the final word appears in the readback / staged payload both ways.
**Before the fix:** the trailing ~20 ms was dropped and spliced onto the front
of the next turn, so the final word came back clipped or missing.

### 4b. A3 — two dictations, two records

Without reloading the page, complete a full dictation to a confirmed save, then
immediately start a second one and save it too.

**Pass:** two distinct `crm_record_id`s, and
`GET /api/v1/notes/committed` shows two records holding their own topics.
**Before the fix:** the second said "saved" and replayed the first's id while
nothing was staged.

**Expect the second dictation to take 6-10s longer to connect** — that is the
cold-start handshake A3 deliberately reintroduces, not a bug.

### 4c. A2 — no duplicate on a guided commit

Run a guided dictation to completion. **Pass:** exactly one CRM record.
The race itself is not manually triggerable; phase 1 covers it.

---

## Phase 5 — the two phases 1-4 cannot prove (~15 min)

### 5a. A7 — plain HTTP from another machine

**This is the one check that cannot be done on the app machine itself.** `localhost` is
a secure context, which is exactly why A7 shipped. From a second machine on the
same network:

```
http://<VDI-LAN-IP>:8000/static/pr5-check.html    <- run this first
http://<VDI-LAN-IP>:8000/                         <- then the real app
```

The check page's context panel reports `isSecureContext: false` and
`crypto.randomUUID: undefined` over plain HTTP — that is the A7 precondition,
demonstrated rather than asserted — and its last test exercises the real
`uuid()` in that exact context. Screenshot it; it is the single best evidence
for the A7 reply.

**Pass:** the page renders and is usable; clicking the mic gives a visible error
naming HTTPS rather than a blank page or a frozen UI.
**Before the fix:** blank page — `crypto.randomUUID` threw at module load.

Then confirm over HTTPS (or back on `localhost`) that the mic still works
normally — the fallback must not have changed the happy path.

Also check the denied-permission path: block mic access in the browser and
click the mic. **Pass:** a visible error and the controls re-enable, rather than
the UI freezing with planning disabled and the timer running.

### 5b. A1 — the BigQuery backend

Only meaningful with a real dataset/table. In a fresh shell:

```powershell
$env:BIGQUERY_ENABLED = "true"
$env:BIGQUERY_DATASET = "<dataset>"
$env:BIGQUERY_TABLE   = "<table>"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Repeat **3a, 3b and 3c** against it. All three must behave identically to the
mock backend — that is the whole point of the fix.

**Pass:** the 409 in 3c fires (it previously did not exist on this backend), the
retry in 3a replays, and one row lands in BigQuery per committed record — not
one per commit *call*.

Also confirm a coverage-blocked commit writes **no** BigQuery row.

If there is no dataset available, say so in the A1 reply rather than implying it
was tested end-to-end.

---

## Coverage summary

| Item | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 |
|---|:--:|:--:|:--:|:--:|:--:|
| A1 | ✅ | | | | ✅ real BQ |
| A2 | ✅ | ✅ | | ✅ | |
| A3 | ✅ | ✅ | | ✅ | |
| A4 | ✅ | | ✅ | | ✅ |
| A5 | ✅ | ✅ | ✅ | | ✅ |
| A6 | logic | | | ✅ | |
| A7 | logic | | | | ✅ **only here** |
| A8 | ✅ | | ✅ | | ✅ |
| A9 | ✗ | | ✅ manual | | |
| A10 | ✅ | ✅ | | | |

**A7 is provable only in phase 5a, from a different machine.** A green phase 1-4
says nothing about it. If 5a is skipped, the A7 reply should say the fallback is
logic-verified and the HTTPS requirement stands, rather than claiming it was
tested on a plain-HTTP deployment.
