# Golden path — demo script

Both solutions (Implicit, Guided) on both campaigns (`standard_sales`,
`enterprise_field`). Utterances are drawn from real rows in
`Notes Examples(Sheet1).csv`.

**Between every scenario:** Ctrl+Shift+R, then re-select Solution, Campaign and
topics — the page resets. Click the mic to connect.

**Stop talking once you hear "All set" / "Saved successfully."** Speaking again
re-arms the mic and the run timer keeps climbing.

> Record IDs below are from runs with the original two-topic scripts. Each
> scenario has since been extended by one topic, so re-run once to confirm the
> added topic maps as expected.

---

## Scenario A — Implicit / `standard_sales`. "The fast one."

| | |
|---|---|
| Solution | **Implicit (Mega-Payload)** |
| Campaign | **standard_sales** |
| Topics | **HVAC** + **Plumbing** + **Hardware** |

**Say** — one breath, no pauses:

> "On-site visit at Brookfield Apartments. I met with Bethany, the property
> manager. We went through HVAC — she's sending me an order for AC units, coils
> and compressors, I got that order at ten past five. We also talked plumbing,
> she's got no immediate need there but wants me to check back next quarter.
> Hardware we already covered last time I was in, so we didn't go over it again.
> I emailed her the everyday essentials brochure before I left. **End notes.**"

Then, after the readback:

> "Yes, save it."

**Check**

- Event type **On-site visit**
- HVAC → **2 — Order Placed**
- Plumbing → **3 — No current need, revisit in the future**
- Hardware → **9 — Recently discussed**
- All three coverage chips green, `missing_topics` empty
- ~30–70 seconds end to end

*Verified (2 topics): `CRM-87C74DDD6F`, `CRM-C802DAD2EB`.*

---

## Scenario B — Guided / `standard_sales`. "The one that refuses to guess."

| | |
|---|---|
| Solution | **Guided (explicit script)** |
| Campaign | **standard_sales** |
| Topics | **Appliances** + **Linens & Towels** + **Pool Supplies** |

Wait for the agent between each turn. Do **not** mention pool supplies until it
asks.

| # | You say |
|---|---|
| 1 | "Yes, let's begin." |
| 2 | "I met with Katie and we went through appliances — I showed her the four ninety-nine Seasons refrigerator. They're a Samsung shop though, so they stay with Samsung for their units. I offered parts for future needs and emailed her the promos. We also went through linens — she's short on sheets and pillows and she's checking the counts and texting me numbers this week. **End notes.**" |
| 3 | "Save." |
| 4 | "Meeting." |
| 5 | "They're staying with Samsung, they're already set up with their preferred vendor." |
| 6 | "Yes, that's right." |
| 7 | *(it asks about Linens & Towels)* → "She needs sheets and pillows, she's sending me counts so I can quote it." |
| 8 | *(it asks about Pool Supplies)* → "We didn't get to pool supplies, she had to run to a walkthrough." |
| 9 | *(it reads the record back)* → "Yes, save it." |

**Check**

- At turn 8 it **asks about Pool Supplies** instead of offering to save
- Record card fills in progressively as it works
- Appliances → **5 — Preferred vendor already**
- Linens & Towels → **1 — Create Opportunity**
- Pool Supplies → no code, `discussed: false`, carrying **your** reason
- `missing_topics` empty, exactly **one** record

**Narrate turn 8.** The agent isn't being polite — a code-level gate in the REST
layer refuses to write a record the system already knows is incomplete. And it
does not fill in a reason on the rep's behalf; the reason in that field is the
one the rep just said.

*Verified (2 topics): `CRM-4465FE3A80`, `CRM-9B6000D420`, `CRM-16E4DB8A72`.*

---

## Scenario C — Implicit / `enterprise_field`. "Same speed, tighter rules."

| | |
|---|---|
| Solution | **Implicit (Mega-Payload)** |
| Campaign | **enterprise_field** ← not standard_sales |
| Topics | **HVAC** + **Appliances** + **Electrical** |

**Say** — one breath:

> "On-site visit at Magnolia Court. I met with Mark, the maintenance supervisor.
> On HVAC — our pricing on the electric Magic-Pak units came in a lot higher
> than Famous, so he's holding off. On appliances, they're locked into a
> contract with Lowe's through year end. Electrical went better — he placed an
> order on the spot for LED lamps, wall plates and batteries. **End notes.**"

Then:

> "Yes, save it."

**Check**

- Event type **On-site visit**
- HVAC → **8 — Pricing concerns**
- Appliances → **4 — Contracted to buy from competitor**
- Electrical → **2 — Order Placed**
- All three coverage chips green, `missing_topics` empty
- Timing comparable to Scenario A — the campaign swap costs nothing

*Not yet run end to end.*

---

## Scenario D — Guided / `enterprise_field`. "The rule that speaks up."

The enterprise-specific beat: `enterprise_field` does not allow **Phone Call**,
so offer one and watch it refuse.

| | |
|---|---|
| Solution | **Guided (explicit script)** |
| Campaign | **enterprise_field** |
| Topics | **HVAC** + **Paint & Supplies** + **Plumbing** |

Wait for the agent between each turn. Do **not** mention plumbing until it asks.

| # | You say |
|---|---|
| 1 | "Yes, let's begin." |
| 2 | "I met with Haley, the assistant property manager — Andy wasn't available. We went through the eighteen-K AC units and she asked me to send a quote. I left her a follow-up text. We also talked paint — their painter runs Sherwin-Williams and they're staying with them. **End notes.**" |
| 3 | "Save." |
| 4 | **"Phone call."** ← *deliberately illegal on this campaign* |
| 5 | *(it should push back / re-ask)* → "On-site visit." |
| 6 | "She asked for a quote on the eighteen-K units." |
| 7 | "Yes, that's right." |
| 8 | *(it asks about Paint & Supplies)* → "Their painter is a Sherwin-Williams guy, they're sticking with him." |
| 9 | *(it asks about Plumbing)* → "We didn't get to plumbing, he had to take a call." |
| 10 | *(it reads the record back)* → "Yes, save it." |

**Check**

- **Turn 4 is the demo beat** — it must not accept Phone Call
- HVAC → **1 — Create Opportunity**
- Paint & Supplies → **5 — Preferred vendor already**
- Plumbing → no code, `discussed: false`, carrying **your** reason
- Event type lands on **On-site visit**
- Exactly **one** record

**Narrate turn 4.** The allowed event types aren't hardcoded in the prompt —
they're injected per campaign from the config the agent fetched at connect time,
and validated again server-side. The prompt asks; the REST layer enforces.

*Verified (2 topics): `CRM-0C47BBFCE4` — 2m 6.6s, $0.007187.*

---

## Scenario E — Implicit / `enterprise_field`. "The one we can't record."

**Engineering audience only.** For a room of FARs this reads as a broken product
rather than a measured gap.

| | |
|---|---|
| Solution | **Implicit (Mega-Payload)** |
| Campaign | **enterprise_field** |
| Topics | **Appliances** + **Pool Supplies** |

**Say**:

> "Meeting at Riverbend. No opportunities on appliances at this time — they only
> use this account for big purchases, so I'll check back next quarter. I asked
> about pool supplies too and he didn't need to order anything right now.
> **End notes.**"

Then:

> "Yes, save it."

**Check**

- Appliances → **99 — Outcome not covered, needs manual review**
- Pool Supplies → **99** as well
- **Two** topic rows, not four
- Specifically **not** codes 3, 5 or 8 — those would be confident and wrong

**Why the second topic matters.** One 99 looks like a model hiccup. Two, from
two different phrasings of the same underlying outcome, shows it's systematic.

**Why this gap is the important one.** `enterprise_field`'s registry is
`[1, 2, 4, 5, 8]`, which excludes **3 — No current need**. Scan the CSV: "No PI
opportunities at this time", "no immediate need", "didn't need to order anything
at this time", "check back next quarter" are everywhere. This isn't an exotic
edge case — it's the single most common thing a rep says, and on this campaign
there is no code for it.

Without the 99 escape hatch the model has to pick *something*: filling a required
enum is an argmax over the allowed values, so it returns a "best" code even when
every option is wrong. Codes 5 and 8 are the likely wrong answers here, and both
would read as plausible in a CRM report — which is what makes them dangerous.

**Two things to get right when speaking.**

*Say "appliances", not "appliance purchasing".* Hand the model a noun phrase and
it adopts it as the topic label; a label that doesn't match the planned topic
makes coverage report it uncovered and the model appends a second topic row for
the same discussion (F7 in `change-log.md`).

*Don't say "no current need" verbatim.* Those are code 3's mapping keywords. On
a campaign where code 3 exists this is fine; here it just makes the miss louder
than a real rep would.

**The ask this sets up.** Adding code 3 to `enterprise_field` is a config change,
not an engineering one. Still genuinely uncovered on every campaign: **no contact
made** (~8% of real visits, and it has no valid event type either) and **renewal
agreed**.

*Verified (1 topic): `CRM-04E2CBA70D` — 48.2s, $0.004216.*

---

## Scenario F — Implicit / `renewals`. The measured version of E.

Superseded by Scenario E for demo purposes; kept because it's the run that was
actually measured across repeats.

| | |
|---|---|
| Solution | **Implicit (Mega-Payload)** |
| Campaign | **renewals** |
| Topics | **Appliances** only |

**Say**:

> "Phone call with Cedar Ridge. On appliances — the GM's interested in renewing
> and wants me to send a quote for approval. **End notes.**"

Then:

> "Yes, save it."

**Check**

- Event type **Phone Call** (`renewals` rejects On-site visit)
- Appliances → **99 — Outcome not covered, needs manual review**
- **One** topic row, not two

**Why `renewals` and not `standard_sales`.** `standard_sales` carries the full
registry and code 1's mapping keywords literally include "send a quote" — so a
quote maps correctly there and demonstrates nothing. `renewals` is `[2,3,5,8,9]`,
excluding code 1, and that is where the gap lives.

**What it measured.** Before the 99 escape hatch, this input returned codes
2, 3, 3, 2, 2, 3 across six runs — Order Placed and No Current Need, opposite
meanings, both false.

*Verified: `CRM-6016747B1F`.*

---

## Do not demo

- A visit where nobody was in — no event type, no disposition (~8% of real visits)
- A one-word note ("Junk", "OK for Now") — forces a fabricated summary
- Scenario E or F to a FAR audience
- Any campaign other than the three above without re-testing first
