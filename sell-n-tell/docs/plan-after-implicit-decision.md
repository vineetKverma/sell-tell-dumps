# Plan after the implicit-model decision

Jeremy's note (2026-08-18): FAR research group has chosen **the implicit model**
for FAR Post-Call Summary. Moving from validation into build, with two business
requirement refinements.

This changes the follow-up plan substantially — mostly by deleting work.

---

## 1. Dropping guided removes about half the review findings

`tools_guided.py` (660 lines) and `agent_guided.py` (261) exist only for the
guided flow. If guided is out of scope, these findings go with it:

| Finding | Why it disappears |
|---|---|
| Race on the guided commit result | guided-only state |
| Stale commit result across dictations | guided-only state (the client-side `session_id` rotation is general and stays) |
| Read-modify-write on guided topic state | guided-only |
| Duplicated 409 handling | only one implementation left |
| Duplicated 422 shaping | only one implementation left |
| Campaign rules in 3 places | becomes 2 |
| State-key literals in 2 files | becomes 1 |
| `needs_manual_review` in 3 places | becomes 2 |
| Guided commit trigger split across files | moot |
| `allow_skips` guided carve-out | **the carve-out exists only for guided** |

That last one matters most. The whole reason `allow_skips` is a confusing
boolean is the guided exemption:

```python
# mock_db.py ~L741
allow_skips = previous is not None or agent_mode == "guided"
```

Without guided it collapses to `previous is not None` — which is a plain,
explainable rule. Story 2 shrinks from a redesign to a tidy-up.

**Recommendation: confirm guided is genuinely out, then delete it** rather than
leaving it to rot. Dead code that looks alive is exactly what
`bigquery_db` was, and it cost us three missing gates and a review cycle.

---

## 2. Requirement 1 — event type interpretation

> *"When a FAR says they 'met with' or 'spoke with' someone, the model is
> currently defaulting the Event Type to On-Site Visit. We need it trained to
> default to Meeting in those cases… Verb + Person at Customer = Meeting"*

### Why it's happening — a real asymmetry in the config

Disposition codes carry **mapping keywords**. Event types carry **nothing**:

```python
# mock_db.py ~L238
"allowed_event_types": ["Meeting", "On-site visit", "Phone Call"],

# vs each disposition rule
{"code": 8, "label": "Pricing concerns",
 "mapping_keywords": ["expensive", "cost too much", "budget issue", ...]}
```

`_format_config_block` (`agent.py` ~L188) renders the codes with their keywords
and the event types as a bare comma-separated list. So the model is told *which*
event types are legal, and nothing about *how to choose between them*. It picks
a default. That is the bug.

### Fix shape

Give event types the same structure the disposition registry already has —
label plus mapping cues — and render them the same way. Roughly:

```python
"allowed_event_types": [
    {"label": "Meeting",
     "cues": ["met with", "spoke with", "sat down with", "caught up with"],
     "note": "Verb + person at the customer = Meeting, even if on their site"},
    {"label": "On-site visit",
     "cues": ["walked the property", "did a site walk", "toured the"],
     "note": "Use only for site/property inspection language"},
    {"label": "Phone Call", "cues": ["called", "phone call", "rang"]},
]
```

**Small change, but it touches the config contract** — `allowed_event_types` is
currently a `list[str]` read in five places (`agent.py`, `tools.py`,
`tools_guided.py`, `mock_db.validate_against_campaign`, and the 422 body). This
is a concrete example of why consolidating first is worth it: a shape change to
one field currently means editing five readers.

**Testable deterministically.** No model needed to check the config renders;
a handful of transcript→event_type cases in the eval set checks the behaviour.

---

## 3. Requirement 2 — vertical market context

> *"add account vertical market to the metadata and train the model on it so it
> can interpret the significance of details differently by vertical"*
>
> *Example: a new truck is a $30–60K opportunity in Trades; largely irrelevant
> for Hospitality or Multifamily.*

### The mechanism already exists

This is structurally identical to `campaign_type`: a value supplied per session
that selects a config block injected into the system prompt.

```
WS /ws/{user}/{session}?campaign_type=…&planned_topics=…&agent_mode=…
                        ^^^^^^^^^^^^^ add account_vertical here
```

`get_agent_config(campaign_type)` becomes
`get_agent_config(campaign_type, account_vertical)`, returning the same shape
plus vertical-specific guidance on what counts as material.

### Three things to settle before building

1. **"Train" — fine-tune, or context?** Fine-tuning is a different project with
   a different cost and timeline. Injecting vertical guidance into the prompt is
   days, uses machinery we already have, and is what the current architecture is
   built for. **Assume context-injection unless told otherwise**, and confirm.
2. **Where does the vertical come from?** The rep doesn't say it — it's an
   account attribute. That is an external-data dependency, and it's likely what
   Jeremy means by *"let's connect if the vertical-market context changes the
   external-data picture."* Either the client passes it at session start (it
   knows the account), or we look it up. This should be raised against the
   EDP/MuleSoft requirements.
3. **How do we know it worked?** "Recognises vertical-specific patterns" is not
   verifiable by the smoke suite — that tests whether a flow completes, not
   whether a judgement was right. This needs the eval harness (AIML-2702) and
   the golden set (AIML-2733). **Those two are now gating for this requirement,
   not optional follow-ups.**

### One caution

Vertical adds a *second dimension* to the config, on top of campaign. Doing that
across today's three divergent implementations of campaign rules would triple
the drift surface. Consolidate first.

---

## 4. Revised plan

Assuming guided is dropped and both requirements land.

| # | Item | Points | Change from before |
|---|---|---|---|
| 0 | **AIML-2751 — Delete the guided flow** | 3 | new — unlocks the rest |
| 1 | Single source of truth for rules + error shaping | 8 → **3** | most duplication disappears with guided |
| 2 | Disposition registry + topic model | 5 → **3** | `allow_skips` carve-out disappears |
| 3 | Enforce the storage backend contract | 2 | unchanged, or dropped if Story 6 deletes `bigquery_db` |
| 4 | Session-state durability and eviction | 8 → **5** | two of the six dicts were guided-only |
| 5 | WebSocket reconnect behaviour | 5 | unchanged |
| 6 | Durable CRM storage + flag naming | 5 | unchanged |
| 7 | **Event type interpretation** | **3** | new, from Jeremy |
| 8 | **Vertical market context** | **8** | new, from Jeremy — assumes context-injection, not fine-tuning |

**33 → 32 points**, but two of those are now new product requirements rather
than debt, and the debt half shrank from 33 to 21.

### Suggested order

1. **AIML-2751** — delete guided. Everything downstream gets smaller.
2. **Story 6** — decide what the CRM is. May delete Story 3.
3. **Story 1** — consolidate, *before* vertical adds a second config dimension.
4. **Story 7** — event type. Small, visible, directly asked for.
5. **AIML-2702 + AIML-2733** — eval harness and golden set. Gating for Story 8.
6. **Story 8** — vertical market context.
7. Stories 2, 4, 5 as capacity allows.

---

## 5. AIML-2751 — Remove the guided flow

**3 points · Sprint AIML-2026-Q3-S3**


### Description

The FAR research group has selected the implicit model, so the guided flow is no
longer a candidate. It is currently ~920 lines across `tools_guided.py` (660)
and `agent_guided.py` (261), plus a `Runner`, a mode selector in the UI, four
smoke scenarios, and guided-only state in three other files.

Leaving it in place is not free. It carries most of the duplication the PR #5
review flagged — campaign rules computed a third way, 409 and 422 responses
shaped a second way, state-key literals in a second file — and every future
change to a shared rule has to be mirrored into a flow nobody runs. The
precedent is `bigquery_db.py`: dead code that read as a working alternative,
which shipped with three missing gates and cost a review cycle to find.

Deleting it also simplifies code that stays. `allow_skips` in `mock_db` is only
a confusing boolean because of its guided exemption:

```python
# mock_db.py ~L741
allow_skips = previous is not None or agent_mode == "guided"
```

which collapses to `previous is not None` once guided is gone.

**Do this first.** Stories 1, 2 and 4 all shrink measurably once it lands, and
doing them first means consolidating code that is about to be deleted.

### Scope

- Delete `tools_guided.py`, `agent_guided.py`, and the guided `Runner` in
  `main.py`
- Remove the Solution/mode selector from the UI and the `agent_mode` query
  parameter, or fix it to `implicit`
- Remove `GUIDED_SCENARIOS` and `PLANNED_TOPICS_GUIDED` from `ws_smoke_test.py`
- Simplify `allow_skips` to `previous is not None`
- Remove `agent_mode`-conditional branches in `mock_db` and `main.py`
- Keep `agent_mode` on the committed record and the analytics sink if the
  implicit-vs-guided comparison data is still wanted historically

### Acceptance criteria

1. No file references `tools_guided` or `agent_guided`.
2. `allow_skips` has no `agent_mode` term.
3. The implicit smoke suite passes with the same scenario count.
4. `scripts/repro_orphan_restage.py` still exits 0 (the supersede gate holds).
5. A stage/commit cycle works end to end in the browser.

### Note

Confirm with Jeremy that guided is out of scope permanently, not parked. If it
may return, tag the deletion commit so it can be recovered rather than keeping
it on `main`.

---

## 6. Other stories likely needed

Not from the PR review — these come from moving into build, and from items
already open in the handoff. Rough sizing only; each needs a proper pass.

### a. Extend the direct REST test suite — **3 pts** *(CI deferred — still in development)*

Every gate defect in the review was found by calling the REST layer directly, in
seconds, while ten conversational scenarios passed. `scripts/repro_orphan_restage.py`
is the shape. Extend that idea to coverage, campaign validation and event-type mapping,
and run it by hand before pushing. Wiring it into CI can wait until there is a
pipeline to wire it into.

### b. Deployed non-localhost environment — **3 pts**

Everything to date has run on `localhost`, which is a secure context, a single
user, and restarted constantly. That hid the blank-page bug on plain HTTP, the
concurrency race, the session-reuse bug, and the fact that nothing persists.
Build phase needs somewhere reachable over HTTPS that stays up.

### c. Real CRM write path — **8 pts, needs a decision first**

Story 6 asks what the CRM *is*; this is what follows. Today the "CRM record"
is a Python list, and the downstream Salesforce sync is driven by this API's
response payload. Nothing has been integrated. Until this exists, "saved to CRM"
means "held in memory until the next redeploy".

### d. Disposition registry content gap — **product decision, then ~3 pts**

No code expresses "renewal agreed", "quote created" on campaigns lacking code 1,
or "no contact made" — roughly a quarter of real visits between them. A
no-contact visit has no valid event type either. The agent handles this honestly
today (code 99, flagged for manual review) but that is a fallback, not an
answer. Needs the lead to decide the registry, then a small implementation.

### e. Topic matching is substring-based — **3 pts**

`_topic_matches` uses containment, so an inflected label ("Appliance Contract
Renewal" vs planned "Appliances") reports the topic as uncovered and can produce
two rows for one discussion. Open as F7. More visible once vertical-specific
prompting produces richer topic labels.

### f. Invented skip reasons — **3 pts**

The agent still writes "due to time constraints" when the rep gave no reason,
despite a prompt rule naming that exact phrase. Measured over six runs before
and after: no difference. Needs a server-side fix — reject or blank a skip
summary that was not grounded in rep speech.

### g. Error handling and resilience (AIML-2651) — **5 pts**

No retry or backoff anywhere; timeouts hardcoded. Already ticketed, not started.
Matters more in a deployed environment than on localhost.

### h. Who consumes `needs_manual_review`? — **spike**

Nothing downstream reads it. Either something should, or the flag is
decoration. Worth an hour before building more on top of it.

---

## 7. To raise

**With Jeremy**

- Confirm guided is out of scope so we can delete it rather than maintain it.
- "Train the model" — confirm this means vertical context in the prompt, not
  fine-tuning. Materially different cost.
- Where does `account_vertical` come from per visit? This is probably an EDP /
  MuleSoft dependency and belongs in Thursday's data requirements.
- Verifying vertical behaviour needs the eval harness and golden set. Those are
  currently backlog items; they become prerequisites.

**With Sai**

- The four platform stories from the PR review (durable storage, session
  durability, WS reconnect, backend contract) are unchanged by this decision and
  still need slotting.
- There is currently **no configuration in which a committed visit note survives
  a restart**. That matters more now that we're building, not validating.
