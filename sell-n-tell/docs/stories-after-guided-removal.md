# Follow-up stories — updated after guided mode is removed

The six stories were written while guided mode still existed. With the implicit
model chosen, the work inside them shrinks. Nothing new is added.

**Do the guided removal first** — otherwise these stories tidy up code that is
about to be deleted.

| # | Story | Was | Now |
|---|---|---|---|
| 1 | One place for campaign rules and error messages | 8 | **3** |
| 2 | Disposition registry cleanup | 5 | **3** |
| 3 | Enforce the storage backend contract | 2 | **2** |
| 4 | Session state: survive restarts, and clean up | 8 | **7** |
| 5 | Define what happens on reconnect | 5 | **5** |
| 6 | Decide where CRM records actually live | 5 | **5** |

Total 33 → 20.

---

# Story 1 — One place for campaign rules and error messages

**Points: 3**

## What to do

Three things, all about the same rule being written twice.

**1. Campaign rules.** "Which event types and disposition codes are legal for
this campaign?" is answered in two places that read different data —
`tools.py::_allowed_codes` (~L44) reads a cached copy from session state, and
`mock_db.validate_against_campaign` (~L474) does a fresh lookup. Make them use
one source.

**2. State keys.** `tools.py` (~L38-40) hardcodes the strings `agent_config` and
`campaign_type`, which `agent.py` already defines as constants. Move them to a
small shared file both can import. (`agent.py` can't be imported directly —
circular import — but `db_interface.py` shows the pattern.)

Today, if someone renames a key and misses this copy, the lookup quietly returns
`None`, campaign validation falls back to allowing *everything*, and nothing is
logged.

**3. Client-side response handling.** `app.js` (~L1017, ~L1066) checks tool names
and statuses in a long chain, then renders success if nothing matched. Add small
helpers so a response that isn't recognised doesn't fall through to "saved".

## Acceptance criteria

1. Adding a disposition code to a campaign means editing one place, and both the
   agent and the REST 422 reflect it.
2. A renamed state key either can't be missed, or logs a warning instead of
   silently allowing everything.
3. `app.js` does not show success for a tool name or status it doesn't
   recognise.
4. The smoke suite passes unchanged and `scripts/repro_orphan_restage.py` exits 0.

---

# Story 2 — Disposition registry cleanup

**Points: 3**

## What to do

**1. One writer for `needs_manual_review`.** Right now `tools.py` sets it, and
`mock_db` (~L708) sets it again unconditionally for code 99 — with a comment
admitting it doesn't fully trust the tool layer. Let `mock_db` be the only
place that sets it; the tool layer just leaves the code empty.

**2. Fix code 99.** `_NOT_COVERED_RULE` (~L238) is deliberately kept out of the
disposition registries, then added back in two places that read them (~L428).
So code 99 is accepted as valid everywhere, but has no label or keywords for
anything that walks the registry. Either put it in the registries, or make the
registries only reachable through an accessor that includes it.

**Note:** the topic-status enum that was originally in this story has been
dropped. It only existed because guided mode needed a special case in
`allow_skips`, and that special case disappears with guided.

## Acceptance criteria

1. `needs_manual_review` is set in one module only.
2. Walking any disposition registry includes code 99 with its label and
   keywords.
3. The smoke suite and the REST coverage cases pass.

---

# Story 3 — Enforce the storage backend contract

**Points: 2**

## What to do

`CRMStore` in `db_interface.py` is supposed to guarantee that `mock_db` and
`bigquery_db` have matching function signatures. It never did — it declares
`self` on its methods, but the things that have to satisfy it are **modules**,
not classes, so nothing ever matched and nothing was ever checked.

This is why the BigQuery backend shipped with three missing gates: the safety
net was decorative.

Fix by dropping `self`, or by wrapping each store in a thin class, so a mismatch
is actually caught.

**Do Story 6 first.** If that story deletes `bigquery_db`, there is only one
store and this story isn't needed.

## Acceptance criteria

1. Removing a keyword argument from `bigquery_db.commit_notes` is caught by
   type-checking instead of passing silently.

---

# Story 4 — Session state: survive restarts, and clean up

**Points: 7**

## What to do

**1. Survive restarts.** Session state lives entirely in one process's memory
(`InMemorySessionService` in `main.py`, with a `KNOWN LIMITATION` comment).
A restart or redeploy loses every in-progress session. Migrate to
`VertexAISessionService`.

**2. Clean up when a session ends.** Five module-level dictionaries grow by one
entry per session and are never emptied: `turn_guard`'s four
(`_TURN_COUNTS`, `_BASELINES`, `_AWAITING_READBACK`, `_NUDGE_SENT`) plus
`mock_db._STAGED_NOTES`. Add a cleanup hook on WebSocket disconnect.

**Two things to know before starting:**

- The migration does **not** fix the five dicts. They are not ADK session state
  — `turn_guard` deliberately keeps its own dicts because ADK state didn't work
  for this (the tool layer couldn't see updates written by `main.py`). Both
  pieces of work are needed.
- Do **not** clean up committed records at the moment of commit. They are kept
  on purpose so a retry gets the original record back instead of a 404. Reap
  them on disconnect or after a timeout instead.

## Acceptance criteria

1. Session state survives a server restart.
2. After many sessions connect and disconnect, the five dicts are not still
   holding an entry for each one.
3. A commit retry shortly after committing still returns the original
   `crm_record_id`, not a 404.
4. `scripts/repro_orphan_restage.py` still exits 0 (the supersede gate holds).

---

# Story 5 — Define what happens on reconnect

**Points: 5**

## What to do

If a client reconnects using the same `session_id` before the previous
connection has finished shutting down, both connections drive the same Gemini
Live session at once and the result is an unexplained `APIError 1000`.

Nothing in the service prevents this. The only reason it doesn't happen today is
that our browser client always generates a **new** `session_id` when it
reconnects — a workaround in one client, not a guarantee from the service. Any
other client integrating with this backend would hit it.

Track which `session_id`s currently have a live connection. When a second one
attaches for an id that is still active, either wait for the first to finish, or
reject it with a clear message like "session busy, retry in X ms". Then write
that behaviour down as part of the API contract.

## Acceptance criteria

1. The service knows which `session_id`s have a live connection.
2. A second connection for an active id gets either a clean wait or an explicit
   error — never an opaque `APIError 1000`.
3. The behaviour is documented, so a consumer knows whether reusing a
   `session_id` is supported.

---

# Story 6 — Decide where CRM records actually live

**Points: 5**

## What to do

Right now there is **no setting under which a committed visit note survives a
restart**. With the default configuration, records are held in a Python list in
`mock_db` and are lost when the process stops.

It looks like they're safe because BigQuery rows do appear — but those come from
`bigquery_sink`, which is a separate analytics log of the payload, not the CRM
record. Two similarly-named flags make this easy to misread:

- `BIGQUERY_ENABLED` (default **false**) — chooses the CRM store
- `VOICE_NOTES_BQ_ENABLED` (default **true**) — the analytics log, runs
  regardless

Pick one of two directions:

- **(a)** Make BigQuery the real CRM store when `BIGQUERY_ENABLED=true` — its own
  staging, commit and read — and leave `bigquery_sink` as the analytics log it
  already is.
- **(b)** Delete `bigquery_db.py`, keep `bigquery_sink` for visibility, and
  document `mock_db` as the only store until a real CRM backend exists.

Option (b) is cheap: `bigquery_db` now hands everything to `mock_db` and only
adds the insert.

Then rename the flags so they don't look like the same switch, and document them
in `.env.example` — `BIGQUERY_ENABLED` isn't mentioned there at all today.

## Acceptance criteria

1. A decision between (a) and (b) is written down with the reasoning.
2. The two flags no longer read as the same switch.
3. `.env.example` documents whichever flags remain.
4. It is clear from configuration alone whether a committed record survives a
   restart.
