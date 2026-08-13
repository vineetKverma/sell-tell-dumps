# Golden path — demo script

Three scenarios, verified live on `feature/AIML-2698-on-2130` (2026-08-11).
Utterances are drawn from real rows in `Notes Examples(Sheet1).csv`.

**Before starting:** restart the server so the record list is empty, and
hard-refresh the browser (Ctrl+Shift+R).

```powershell
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload 2>&1 | Tee-Object -FilePath "..\live-run.log"
```

**Between every scenario:** Ctrl+Shift+R, then re-select Solution, Campaign and
topics — the page resets. Click the mic to connect.

**Stop talking once you hear "All set" / "Saved successfully."** Speaking again
re-arms the mic and the run timer keeps climbing.

---

## Scenario A — Implicit. "The fast one."

**Select**

| | |
|---|---|
| Solution | **Implicit (Mega-Payload)** |
| Campaign | **standard_sales** |
| Topics | **HVAC** + **Plumbing** |

**Say** — one breath, no pauses:

> "On-site visit at Brookfield Apartments. I met with Bethany, the property
> manager. We went through HVAC — she's sending me an order for AC units, coils
> and compressors, I got that order at ten past five. We also talked plumbing,
> she's got no immediate need there but wants me to check back next quarter.
> **End notes.**"

Then, after the readback:

> "Yes, save it."

**Check**

- Event type **On-site visit**
- HVAC → **2 — Order Placed**
- Plumbing → **3 — No current need, revisit in the future**
- Both coverage chips green, `missing_topics` empty
- ~30–70 seconds end to end

*Verified: `CRM-87C74DDD6F`, `CRM-C802DAD2EB`.*

---

## Scenario B — Guided. "The one that refuses to guess."

**Select**

| | |
|---|---|
| Solution | **Guided (explicit script)** |
| Campaign | **standard_sales** |
| Topics | **Appliances** + **Pool Supplies** |

**Say** — wait for the agent between each turn. Do **not** mention pool supplies
until it asks.

| # | You say |
|---|---|
| 1 | "Yes, let's begin." |
| 2 | "I met with Katie and we went through appliances — I showed her the four ninety-nine Seasons refrigerator. They're a Samsung shop though, so they stay with Samsung for their units. I offered parts for future needs and emailed her the promos. **End notes.**" |
| 3 | "Save." |
| 4 | "Meeting." |
| 5 | "They're staying with Samsung, they're already set up with their preferred vendor." |
| 6 | "Yes, that's right." |
| 7 | *(it asks about Pool Supplies)* → "We didn't get to pool supplies, she had to run to a walkthrough." |
| 8 | *(it reads the record back)* → "Yes, save it." |

**Check**

- At turn 7 it **asks about Pool Supplies** instead of offering to save
- Record card fills in progressively as it works
- Appliances → **5 — Preferred vendor already**
- Pool Supplies → no code, `discussed: false`, carrying **your** reason
- `missing_topics` empty, exactly **one** record

**Narrate turn 7.** The agent isn't being polite — a code-level gate in the REST
layer refuses to write a record the system already knows is incomplete. And it
does not fill in a reason on the rep's behalf; the reason in that field is the
one the rep just said.

*Verified: `CRM-4465FE3A80`, `CRM-9B6000D420`, `CRM-16E4DB8A72`.*

---

## Scenario C — Implicit on `renewals`. "The one we can't record."

**Engineering audience only.** For a room of FARs this reads as a broken
product rather than a measured gap.

**Select**

| | |
|---|---|
| Solution | **Implicit (Mega-Payload)** |
| Campaign | **renewals** ← not standard_sales |
| Topics | **Appliances** only |

**Say**

> "Phone call with Cedar Ridge. On appliances — the GM's interested in renewing
> and wants me to send a quote for approval. **End notes.**"

Then:

> "Yes, save it."

**Check**

- Event type **Phone Call** (`renewals` rejects On-site visit)
- Appliances → **99 — Outcome not covered, needs manual review**
- **One** topic row, not two

**Two things to get right when speaking.**

*Say "appliances", not "appliance contract renewal".* Hand the model a noun
phrase and it adopts it as the topic label; "Appliance Contract Renewal" does
not match the planned topic, so coverage reports it uncovered and the model
appends a second topic row for the same discussion (F7 in `change-log.md`).

*The campaign is the point.* `standard_sales` carries the full registry, and
code 1's mapping keywords literally include "send a quote" — so a quote maps
correctly there and demonstrates nothing. `renewals` is `[2,3,5,8,9]`,
excluding code 1, and that is where the gap actually lives.

**What this shows.** Before the code-99 escape hatch, this input returned codes
2, 3, 3, 2, 2, 3 across six runs — Order Placed and No Current Need, opposite
meanings, both false. Filling a required enum is an argmax over the allowed
values, so the model always returns a "best" code even when every option is
wrong. Adding "not covered" as an ordinary peer option lets it pick that instead.

**The ask this sets up.** Still genuinely uncovered on every campaign: **no
contact made** (~8% of real visits, and it has no valid event type either) and
**renewal agreed**. Those need a product decision, not an engineering fix.

*Verified: `CRM-6016747B1F`.*

---

## Do not demo

- A visit where nobody was in — no event type, no disposition (~8% of real visits)
- A one-word note ("Junk", "OK for Now") — forces a fabricated summary
- Scenario C to a FAR audience
- Any campaign other than the two above without re-testing first
