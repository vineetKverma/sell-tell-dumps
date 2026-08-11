# Golden path — FAR demo, Monday 17 Aug

Two scenarios, one per mode, both drawn from real rows in
`Notes Examples(Sheet1).csv` so the language in the room is language the FARs
recognise. Scenario A shows **speed** (implicit). Scenario B shows **control and
the guard that stops a wrong record** (guided).

Decision (2026-08-11): demo **both modes, one scripted scenario each**.

**Design rules these scenarios obey** — every one of them is a measured failure
if broken, see `AIML-2698-gap-findings.md` and `far-notes-dataset-analysis.md`:

1. Planned topics come only from **Appliances, HVAC, Plumbing, Pool Supplies** —
   the four categories that appear with real frequency in the notes sample.
2. **No quote language.** "Send me a quote" has no disposition code and returns a
   different wrong code per run (Gap 5). Never say it on stage.
3. **No no-contact visit.** "Nobody was there" has no event type and no code.
4. **No one-word notes.** Sub-40-character input forces the model to invent a
   summary (Gap 4).
5. Every disposition the script expects exists in `standard_sales`.

---

## Setup (identical for both)

```
campaign_type   = standard_sales
agent_mode      = implicit | guided
```

Server, from the repo root:

```powershell
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload 2>&1 | Tee-Object -FilePath "..\live-run.log"
```

Hard-refresh the browser (**Ctrl+Shift+R**) before the first run — `app.js` is a
cached ES module and a stale one has cost us a rehearsal before.

---

## Scenario A — implicit. "The fast one."

**Source row:** *"I met with Betthany the property manager… We also discussed
HVAC plumbing and also hardware. She is sending me an order for some AC units
some coils and some compressors. I got the order at 5:10 today."*

**Planned topics:** `HVAC`, `Plumbing`

**What to say** (one breath, no pauses — implicit is a single Mega-Payload call):

> "On-site visit at Brookfield Apartments. I met with Bethany, the property
> manager. We went through HVAC — she's sending me an order for AC units, coils
> and compressors, I got that order at ten past five. We also talked plumbing,
> she's got no immediate need there but wants me to check back next quarter."

**Expected record:**

| Field | Value |
|---|---|
| Event type | On-site visit |
| HVAC | **2 — Order Placed** |
| Plumbing | **3 — No current need, revisit in the future** |

Agent reads the record back; rep says **"yes, save it"**; record commits.

**Why this one:** two planned topics, both genuinely covered, two *different*
and unambiguous dispositions. Nothing here depends on a code that doesn't exist.
Roughly 30 seconds end to end.

---

## Scenario B — guided. "The one that refuses to guess."

**Source row:** *"Met with Katie and discussed appliances incl $499 Seasons
refrigerator. They are a Samsung shop so offered parts for future needs.
Emailed promos in hope of stimulating some orders."*

**Planned topics:** `Appliances`, `Pool Supplies`

Guided confirms field by field, so this is spoken as a conversation. Pool
Supplies is planned and **deliberately never mentioned** — that is the point of
the scenario.

| Turn | Rep says |
|---|---|
| 1 | "Meeting at Lakeview Property Management." |
| 2 | "I met with Katie and we went through appliances — I showed her the four-ninety-nine Seasons refrigerator. They're a Samsung shop though, so they stay with Samsung for units. I offered parts for future needs and emailed her the promos." |
| 3 | *(agent confirms Appliances → 5 — Preferred vendor already)* → "Yes, that's right." |
| 4 | *(agent reminds: Pool Supplies was planned and hasn't been covered)* → "We didn't get to pool supplies, she had to run to a walkthrough." |
| 5 | *(agent reads the full record back)* → "Yes, save it." |

**Expected record:**

| Field | Value |
|---|---|
| Event type | Meeting |
| Appliances | **5 — Preferred vendor already** |
| Pool Supplies | `discussed = false`, summary = the rep's own reason, **no invented disposition** |

**The moment to narrate.** At turn 4 the agent will not save. That is not the
model being polite — it is a code-level gate in the REST layer
(`IncompleteCoverageError`). Before we added it, the agent committed the record
with Pool Supplies silently missing. Worth saying out loud to the FARs: *the
system will not write a record it knows is incomplete.*

And it does **not** fill in a reason on the rep's behalf. The reason in that
field is the one the rep just said. We measured the alternative — the model
invented *"Rep did not get to pricing due to time constraints"* when the rep had
said nothing of the kind.

---

## Known risks on stage

| Risk | Where | Mitigation |
|---|---|---|
| ~~Guided goes quiet before saving~~ (Gap 6) | — | **FIXED 2026-08-11.** The final `record_topic_disposition` now commits directly instead of asking the model for a second call. Verified via `ws_smoke_test guided`: the agent speaks the closing statement and a record lands. |
| ~~Guided leaves the record card empty~~ (Gap 18) | — | **FIXED** by the lead's `c6860bd` — `renderPayload(guidedPayload)` in `app.js:845`. Both modes now populate the card, so they can be shown side by side. |
| Disposition non-determinism (Gap 5) | Either, if off-script | Only bites when no code fits. Both scripts avoid that. **Do not improvise an utterance.** |
| Stale `app.js` | Either | Ctrl+Shift+R before the first run. |
| Model asks something unscripted | Either | Answer plainly and briefly, then return to the script. Do not argue with it. |

---

## Rehearsal checklist

Branch to demo: **`feature/AIML-2698-on-2130`** — the lead's `c6860bd` with our
2698 fixes rebased on top.

- [ ] 9-case REST suite green on the branch being demoed
- [ ] `ws_smoke_test.py implicit` and `guided` both green
- [ ] Trailing `"Okay."` workaround turn removed from the guided scenarios
      (it existed only to mask Gap 6; leaving it in hides regressions)
- [ ] Scenario A run 3× live on the mic — same record every time
- [ ] Scenario B run 5× live on the mic — confirm it saves unaided
- [ ] Exactly **one** CRM record per run, not two (guided commit idempotency)
- [ ] Record card populates in **both** modes
- [ ] Server restarted clean before the room walks in; store is in-memory and
      carries staged records across runs

---

## Do not demo

Grounded in the real-notes analysis; each of these produces a visibly wrong or
dishonest record today:

- A visit where nobody was in — no event type, no disposition (8% of real visits)
- Anything ending in "send them a quote" — no code exists (~15% of real visits)
- A one-word note — forces a fabricated summary (9% of real notes)
- A campaign other than `standard_sales` without re-testing it first

If a FAR in the room asks for one of these — and on this data one probably will —
that is a **good** outcome, not a failure. The honest answer is that the
disposition registry has no code for it, we have measured how often it comes up,
and it needs a business decision rather than an engineering fix. See the open
questions in `far-notes-dataset-analysis.md`.
