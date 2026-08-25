# Impact of removing guided on the six existing stories

Written 2026-08-24. The six follow-up stories were scoped while guided was still
in play. With the implicit model selected, four of them change and two do not.

**Net: 33 → 20 points.** Nothing is added; nothing new is discovered. This is
purely scope that evaporates.

| Story | Before | After | Change |
|---|---|---|---|
| 1. Single source of truth for rules + error shaping | 8 | **3** | most of it was implicit-vs-guided duplication |
| 2. Disposition registry + topic-state model | 5 | **3** | the `allow_skips` carve-out disappears |
| 3. Storage backend contract | 2 | **2** | unaffected |
| 4. Session-state durability + eviction | 8 | **7** | one of six dicts was guided-only |
| 5. WebSocket reconnect behaviour | 5 | **5** | unaffected |
| 6. Durable CRM storage + flag naming | 5 | **5** | unaffected |

Do the guided removal **first**. Doing any of these before it means consolidating
code that is about to be deleted.

---

## Story 1 — Single source of truth · 8 → 3

Four of its five parts shrink or vanish.

**Campaign rules — three implementations → two.**
`tools_guided.py::_campaign_rules` goes. Left with `tools.py::_allowed_codes`
(cached session state) and `mock_db.validate_against_campaign` (fresh lookup).
Still worth unifying — they still read different data — but it is one
reconciliation, not three.

**Duplicated 409 handling — gone entirely.**
The finding was that `tools.py` ~L462 and `tools_guided.py` ~L520-527 parse the
409 body independently. With one tool module there is one handler. Nothing to do.

**Duplicated 422 shaping — gone entirely.**
Same shape: `tools.py` ~L264 and `tools_guided.py` ~L482. Nothing to do.

**State-key literals — two files → one.**
`tools_guided.py` ~L41-42 goes. `tools.py` ~L38-40 still hardcodes
`agent_config` / `campaign_type` as strings that duplicate `agent.py`'s
constants, so the silent-`None`-then-global-registry failure is still reachable.
Smaller, still real.

**Client conditional — the one part that shrinks but stays.**
`app.js` ~L1017 and ~L1066 branch on three tool names:

```js
fr.name === "commit_visit_notes" ||
fr.name === "commit_guided_notes" ||      // gone
fr.name === "record_topic_disposition"    // gone
```

Two of the three are guided. The conditional collapses to one name, which is
most of the "hard to extend" problem. Worth still adding `isRefusal(resp)` as a
guard clause, but it is now a small tidy-up rather than a restructure.

**What is left to actually do:** reconcile the two campaign-rule readers, move
the state keys into a shared leaf module, and simplify the `app.js` conditional.

---

## Story 2 — Disposition registry and topic-state model · 5 → 3

**`allow_skips` — the biggest part, and it mostly resolves itself.**

The reason this was a redesign is the guided exemption:

```python
# mock_db.py ~L741
allow_skips = previous is not None or agent_mode == "guided"
```

The guided-removal story already collapses that to `previous is not None`. Once
it is a single, explainable condition, the topic-status enum
(*unaddressed / skipped-unconfirmed / skipped-confirmed / discussed*) is
optional rather than necessary — it was justified by "a third calling pattern
needs another carve-out", and there is now only one caller.

**Recommendation:** drop the enum from scope. Keep it in the backlog for when a
second flow genuinely appears. Re-adding it later is cheap; building an
abstraction for one caller is not.

**`needs_manual_review` — three writers → two.**
`tools_guided.py::record_topic_disposition` ~L323 goes. `tools.py::_normalize_topics`
and `mock_db` ~L708 remain, and `mock_db`'s comment still admits it does not
trust the tool layer. Still worth making `mock_db` the single writer.

**Code 99 registry splice — unaffected.**
Nothing about `_NOT_COVERED_RULE` being excluded from the registries it is
spliced into depends on guided. Unchanged.

**What is left to actually do:** make `mock_db` the only writer of
`needs_manual_review`, and fix the code-99 splice.

---

## Story 3 — Storage backend contract · unchanged at 2

`CRMStore` and the two storage backends have nothing to do with guided.

Still gated on **Story 6**: if that story deletes `bigquery_db`, there is only
one store and no contract to enforce, and this story disappears instead.

---

## Story 4 — Session-state durability and eviction · 8 → 7

**Six dicts become five.** `tools_guided._COMMIT_LOCKS` goes with the module.

Everything else stands, and it is worth being explicit that `turn_guard` is
**not** guided-only — `tools.py` uses it in three places (~L326 snapshot,
~L372 `confirmation_was_read`, ~L397 `has_new_reply`), and `main.py` drives
`mark_awaiting_readback`, `record_agent_speech` and `needs_readback_nudge` for
every session regardless of mode.

So all four `turn_guard` dicts remain, plus `mock_db._STAGED_NOTES`. The
`InMemorySessionService` migration is untouched by this decision, as is the
constraint that it will not fix those dicts — they are not ADK state.

**What is left to actually do:** all of it, minus one dict.

---

## Story 5 — WebSocket reconnect behaviour · unchanged at 5

The race is between two connections attaching to the same `session_id`, in
`websocket_endpoint`. Mode-independent.

One detail worth keeping in the ticket: PR #5 made this *harder* to observe,
because the client now rotates `session_id` after every commit and so reuses ids
less often than before.

---

## Story 6 — Durable CRM storage and flag naming · unchanged at 5

`BIGQUERY_ENABLED` vs `VOICE_NOTES_BQ_ENABLED`, and the fact that no
configuration currently persists a committed record across a restart. Nothing to
do with guided.

Still the story to decide **first**, because it may delete Story 3.

---

## Revised order

1. **Remove guided** — everything below gets smaller
2. **Story 6** — decide what the CRM is; may delete Story 3
3. **Story 1** (now 3 pts) — consolidate before vertical-market adds a second
   config dimension
4. **Story 2** (now 3 pts) — registry and manual-review writer
5. **Stories 4 and 5** — platform work, parallelisable
6. **Story 3** — only if Story 6 keeps `bigquery_db`

---

## What to tell the ticket owners

- Stories **1, 2 and 4** need re-pointing after guided is removed. The
  descriptions stay accurate; the scope inside them shrinks.
- Story **2's topic-status enum should be dropped from scope** and parked. It
  was justified by a second caller that no longer exists.
- Stories **3, 5 and 6** are unaffected — no action.
