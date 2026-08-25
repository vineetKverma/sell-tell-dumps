# Why the review found so much, and what to simplify

Written 2026-08-24, after PR #5's review turned up 28 findings.

---

## 1. Why did these surface so late?

Five causes. None is "we weren't careful" — each is a structural blind spot.

### a. Almost everything was tested *through the model*

`ws_smoke_test.py` drives scripted conversations. That is a good end-to-end
check, but it tests the gates only when the model happens to do the wrong thing.
A gate can be missing entirely and every scenario still passes.

Concrete: `bigquery_db.commit_notes` had **no coverage gate, no supersede check
and no idempotency guard**. Ten conversational scenarios passed. A 15-line
script calling the REST endpoint directly found it in seconds.

The same pattern repeats. Each of these took one direct call to expose, and
zero conversational runs:

| Defect | How it was found |
|---|---|
| Retry after commit returned 404 instead of the cached record | direct double-commit |
| Superseded draft was committable | direct commit of the old id |
| `/notes/confirm` returned 500 instead of 409 | direct call with an incomplete record |
| `campaign_type` at commit overrode the staged one | direct commit with a mismatched value |

**Lesson:** the model is the *slowest and least reliable* way to test a rule.
The design already says "all enforcement belongs in the REST layer" — so test
the REST layer directly. `scripts/test_correction_reliability.py` is the shape:
16 assertions, ~10 seconds, no model.

### b. One environment: localhost, one tab, one user, never restarted

That single environment hid four separate findings:

- **`crypto.randomUUID` throws on plain HTTP** — `localhost` is a "secure
  context", so it never threw for us. On a LAN IP the whole page was blank.
- **The concurrent-commit race** — one browser tab never issues two overlapping
  tool calls.
- **Reusing a `session_id` across dictations** — we always reloaded the page
  between tests, which minted a fresh id and hid the stale state.
- **Nothing survives a restart** — we restarted so often we never noticed we
  were relying on in-memory state that a redeploy would erase.

### c. Every rule is written two or three times

| Rule | Where it lives |
|---|---|
| "what's legal for this campaign" | `tools.py`, `tools_guided.py`, `mock_db.validate_against_campaign` |
| how a 409 becomes a model instruction | `tools.py`, `tools_guided.py` |
| how a 422 becomes a model instruction | `tools.py`, `tools_guided.py` |
| `needs_manual_review` | `tools.py`, `tools_guided.py`, `mock_db` |
| the CRM store itself | `mock_db.py`, `bigquery_db.py` |

Fixing one copy and missing another is not carelessness — it is the predictable
outcome of this shape. Most of the review's design findings are instances of it.

### d. Model workarounds accumulated as state

`turn_guard`, the inline commit in `record_topic_disposition`, the proactivity
config, the VAD tuning, the readback nudge — each was added to work around
something the model did unreliably. Each is individually justified. Together
they add per-session state and cross-file coupling, which is where the races
and the stale-state bugs came from.

### e. `bigquery_db` had never been run — at all

This is worth stating plainly. `bigquery_db.commit_notes(session_id, confirmed)`
did not accept the kwargs `main.py` passes, so **every** commit with
`BIGQUERY_ENABLED=true` raised `TypeError` immediately. Not "it had a bug" — it
could never have completed a single commit.

So the flag has never been switched on. It is dead code that reads as a working
alternative backend.

---

## 2. What the Google Live API already does — and what it doesn't

Fair question: we're using a managed real-time voice API. Why are we hand-rolling
turn tracking, reconnects and transcripts?

**It does more than you might think.** From `main.py` ~L717:

```python
run_config = RunConfig(
    streaming_mode=StreamingMode.BIDI,
    response_modalities=["AUDIO"],
    input_audio_transcription=types.AudioTranscriptionConfig(),   # rep -> text
    output_audio_transcription=types.AudioTranscriptionConfig(),  # agent -> text
    session_resumption=types.SessionResumptionConfig(),           # resume after a blip
    realtime_input_config=realtime_input_config,                  # server-side VAD
    proactivity=proactivity,                                      # may stay silent
)
```

So we already get, for free: **both transcripts**, **turn detection**
(when did the rep stop speaking), and **Live session resumption**.

**What it cannot do**, and why our extra layers exist:

| We built | Because the Live API… |
|---|---|
| `turn_guard` | tells you a turn *ended*; it cannot tell you the model's tool call was actually *grounded* in the rep's answer |
| WS reconnect handling | resumes a *Gemini* session; it has no idea which `session_id` maps to which staged CRM record, and doesn't stop two connections attaching to one session |
| REST gates (`mock_db`) | has no concept of your business rules — coverage, supersede, idempotency |
| the session store | is stateless about *your* data |

### turn_guard, concretely

The failure it exists for, observed live: the model speaks a question and
answers it itself, then calls the tool — without the rep ever replying.

```
AGENT: "So that's pricing marked as too expensive. Does that sound right?
        ... Great, saving that now."          <- rep said nothing
TOOL:  record_topic_disposition(...)          <- records a fabricated answer
```

Prompt rules did not reliably prevent it — this is model decoding
non-determinism, not something wording controls. So `turn_guard` counts *real*
finished rep transcriptions and refuses the tool call if none arrived since the
question was asked:

```python
# tools_guided.py ~L299
if not turn_guard.has_new_reply(tool_context):
    return {"status": "error", "error": "no_reply_heard", ...}
```

`main.py` increments the counter only on a genuine finished input transcription
(~L832). It is 117 lines and it is the reason the agent cannot invent a
disposition the rep never gave.

**Why it's a module-level dict rather than ADK session state** — this is the
part that looks wrong and isn't. From its own docstring: an earlier version
stored the counter in `tool_context.state`, and `ToolContext.state` does **not**
observe mutations made to the `Session` object from `main.py`'s downstream loop.
Every commit read a stale baseline and was permanently blocked. Hence the plain
dict, which both sides can write.

That is also why migrating to `VertexAISessionService` will **not** fix
`turn_guard`'s memory growth — it isn't ADK state.

---

## 3. What BigQuery is actually for

Two separate things with confusingly similar names. This is the source of the
confusion, and it is a real defect, not just your reading of it.

### `bigquery_sink.py` — an analytics side-log (this one runs)

- Flag: `VOICE_NOTES_BQ_ENABLED`, **default `true`**
- Writes **one row per committed call**, to a different table per mode:
  `implicit_flow_calls` / `guided_flow_calls`
- Purpose, from its own docstring: *"so the two flows can be compared side by
  side"* — it exists to measure implicit vs guided, not to store CRM records
- Best-effort: every failure is caught and logged, never raised, and it runs
  in the background so it can't slow a commit
- Runs **regardless** of which CRM store is active

### `bigquery_db.py` — a pretend CRM backend (this one has never run)

- Flag: `BIGQUERY_ENABLED`, **default `false`**, undocumented in `.env.example`
- Meant to be a durable `CRMStore`
- Until PR #5 it raised `TypeError` on every commit, so it has never worked
- Even now it delegates *everything* — staging, config, all gates — to
  `mock_db`, and owns only the insert

### The practical consequence

With the defaults, BigQuery rows **do** appear — from the sink. That looks like
"our CRM data is in BigQuery". It isn't. The CRM record lives in
`mock_db._COMMITTED_NOTES`, a Python list, and **a restart erases it**.

There is currently no configuration in which a committed visit note survives a
restart. That is Story 6.

---

## 4. Where the complexity actually is

Ranked by how much simplification is available:

1. **Two tool modules** (`tools.py` 497 lines, `tools_guided.py` 660) that
   implement the same rules differently. → Story 1
2. **Two CRM stores**, one of which is a shell. → Story 6, then Story 3
3. **Model workarounds as session state** — `turn_guard`, `_S_COMMIT_RESULT`,
   `_COMMIT_LOCKS`. Reducible but not removable; they exist because the model is
   non-deterministic.
4. **`mock_db.py` at 954 lines** doing config registry, validation, staging,
   coverage, confirmation text and storage. → Story 2 takes the domain-model
   part.

The single highest-leverage change is not on the list because it isn't a
refactor: **test the REST layer directly**. It is where all enforcement lives,
it is deterministic, and it is where every gate defect was found.

---

## 5. The six stories in plain terms

### Story 1 — one place per rule (8 pts)

*Today:* "is code 4 legal for renewals?" is answered in three files that read
different data.

```python
# tools.py ~L44          reads cached session state
# tools_guided.py ~L45   reads cached session state
# mock_db.py  ~L474      fresh lookup   <- the only one the server trusts
```

*After:* one function, three callers.

**Why you care:** today, changing a campaign rule can make guided mode accept
something implicit mode rejects, with no error anywhere.

---

### Story 2 — make the topic model explicit (5 pts)

*Today:* a boolean decides whether a skipped topic counts as covered.

```python
# mock_db.py ~L741
allow_skips = previous is not None or agent_mode == "guided"
```

That line needed a five-line comment to justify, and it took a live deadlock to
get right. It is then read by four functions, including the gate that decides
whether a record can be saved at all.

*After:* a topic has a *status* — `unaddressed` / `skipped-unconfirmed` /
`skipped-confirmed` / `discussed`.

**Why you care:** adding a third flow today means adding a clause to that
boolean and re-checking four functions.

---

### Story 3 — make the backend contract real (2 pts)

*Today:* `CRMStore` in `db_interface.py` is supposed to guarantee both stores
match. It declares `self` on its methods — but the things that must satisfy it
are **modules**, not classes, so nothing ever matched and nothing was ever
checked.

**Why you care:** this is exactly why the BigQuery backend shipped with three
missing gates. The safety net was decorative.

*Note:* if Story 6 removes `bigquery_db`, this may not be needed at all.

---

### Story 4 — state that survives, and gets cleaned up (8 pts)

*Today:* two problems.

```python
# main.py — nothing survives a restart
session_service = InMemorySessionService()   # KNOWN LIMITATION comment
```

And six dicts that only ever grow — `turn_guard`'s four, plus
`mock_db._STAGED_NOTES` and `tools_guided._COMMIT_LOCKS`. Nothing is removed
when a rep disconnects.

**Why you care:** a redeploy loses every in-flight dictation, and a
long-running process leaks. PR #5 made both worse — `session_id` now rotates per
dictation (more sessions), and committed records are deliberately retained.

**Catch:** `VertexAISessionService` fixes ADK session state only. The six dicts
above are not ADK state and still need eviction hooks.

---

### Story 5 — say what happens on reconnect (5 pts)

*Today:* if a client reconnects with the same `session_id` before the old
connection has finished tearing down, both drive the same Live session and you
get an opaque `APIError 1000`.

Nothing prevents it. The only reason it doesn't happen is that our browser
client always mints a **new** id on reconnect — a workaround in one client, not
a property of the service.

**Why you care:** the REST layer already has a solid retry story. The WS layer
doesn't, and any second client integrating against this backend would hit the
race immediately.

---

### Story 6 — decide what the CRM actually is (5 pts)

*Today:* see §3. BigQuery rows appear from the analytics sink while the real
records sit in a Python list that a restart erases, behind two flags that read
like the same switch.

*Decide:* either BigQuery genuinely becomes the store, or `bigquery_db` is
deleted and `mock_db` is documented as the only CRM until a real backend exists.

**Why you care:** this is the one story that changes what the product *is* —
whether a committed visit note is durable. It should be decided before Story 3,
because it may delete Story 3's subject.

---

## 6. What would have caught most of this earlier

1. **A direct REST test suite**, run in CI. Deterministic, seconds, no model.
   Every gate defect in this review would have been caught by one.
2. **One non-localhost environment.** Would have caught the secure-context bug
   and made the session-reuse and restart problems obvious.
3. **A real contract between the two stores** (Story 3) — the one guard that
   existed was decorative.
4. **Not building a second backend before the first one was needed.**
   `bigquery_db` has never run. It cost review time, carried three missing
   gates, and delivered nothing.
