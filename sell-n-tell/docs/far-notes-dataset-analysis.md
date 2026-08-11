# Real FAR notes — dataset analysis

Source: `FAR Notes Examples.xlsx` (Jeremy Daniell, 2026-08-07), exported to
`Notes Examples(Sheet1).csv`. Column 1 = the rep's pre-call planning objective,
column 2 = their notes written after the meeting.

**1000 rows, 975 with both columns.** Meeting notes average 190 characters
(min 4, max 1472).

This is the first real-language sample we have. It contradicts several
assumptions built into the current flow, and it is the natural source for the
golden set in AIML-2702.

---

## 1. Product categories as planned topics — coverage will fire constantly

Jeremy's instruction is to use the 13 product category titles as pre-call plan
topics (Appliances, Cleaning & Janitorial, Electrical, Hardware, HVAC, Lighting
& Ceiling Fans, Linens & Towels, Office Supplies, Paint & Supplies, Plumbing,
Pool Supplies, Storage, Tools).

How often those words actually appear in the meeting notes:

| Category | Mentions | | Category | Mentions |
|---|---|---|---|---|
| Appliances | 120 | | Paint | 9 |
| HVAC | 119 | | Hardware | 6 |
| Pool | 62 | | Cleaning / Janitorial | 4 each |
| Plumbing | 52 | | Tools | 4 |
| Lighting | 31 | | Electrical, Towels, Office Supplies | 3 each |
| | | | Linens, Storage | 2 each |
| | | | Ceiling Fans | **0** |

**650 of 975 notes (67%) mention no product category at all.**

Under the current design, a rep who plans "HVAC" and "Appliances" and then
writes notes that never name either will have **both planned topics reported as
uncovered**. The agent will ask about each one before it can save. On this
sample that happens on roughly two visits in three.

The coverage check itself is working as designed — but with real planned topics
and real notes, "ask about every unmentioned topic" becomes the common path
rather than the exception. Worth deciding whether coverage should be a *blocker*
or a *prompt* before the demo.

---

## 2. Reps do not actually plan in product categories

The real pre-call objectives are campaign codes, questions, and admin
follow-ups — not categories:

```
Q3 EE, Q2 BM&S ($75 off $750 QUS), Q3 Fire Safety
credit issues
Did you make a decision on your magic pak units / When do you change out your
  smoke/co detectors / Any issues with your deliveries
Q3 EE, $0 Spend WH / Still purchasing from Lowe's Pro? Last sale date 6/20/25
FU TEMP GM / Thank 7/20 order Leah / FU MRO Quote ready / FU RENO + Apply/PTAC
  plan / HH core 4 BOMB Textiles, Tissue, P&G, PCA stock review
BMS 60 off 600. Offers Tab. Campaigns. All Green.
```

So the 13 categories are a **demo simplification**, not what a FAR would
recognise as their plan. Fine for Monday; worth flagging that the real thing is
messier, heavily abbreviated (FU, EE, BM&S, MRO, PTAC, CAPX, BOMB, CE, HH, AMR,
QUS, DNL), and will need mapping rather than literal matching.

---

## 3. Outcomes the disposition registry cannot express

Frequency of outcome language across the 975 notes:

| Outcome in the notes | Count | Registry code available? |
|---|---|---|
| Quote created / requested / sent | **142** | **none** |
| Pricing / cost / $ discussed | 122 | 8 — Pricing concerns |
| Order placed | 89 | 2 — Order Placed |
| **Contact not available / no meeting** | **81** | **none** |
| Follow-up required | 49 | none (arguably 3) |
| Buys via corporate / another vendor | 20 | 4 or 5 |
| No current need / nothing going on | 18 | 3 |

Two of the largest categories have no code at all:

**Quoting (142 / 975).** Creating and sending a quote is one of the most common
real outcomes — *"Quote created together on site and sent to GM Marsha for
approval"*. There is no disposition for it. This is the same gap we measured for
renewals ("interested, wants a quote" → the model returned Order Placed or
No current need at random), now shown to affect ~15% of all visits.

**No-contact visits (81 / 975, 8%).** The rep turned up and nobody was there:

```
Not there
Not available
Office closed at 1 and 2:30. Rerouted for 8/4
No one ever in at this property.
Office was closed / Drove around property looking for movement / No luck at all
Jason not available during visit, left message regarding concerns for deliveries
```

There is no disposition for "visit attempted, no contact made", and no event
type either — the record still demands Meeting / On-site visit / Phone Call plus
a per-topic outcome. Roughly one visit in twelve cannot be recorded honestly.

---

## 4. Very short notes will force fabrication

**88 of 975 (9%) are under 40 characters.** The shortest real entries:

```
Junk
REHAB
Not there
OK for Now
placed order
unavailable.
```

The current flow asks for an overall 2-sentence executive summary, plus a topic
entry per planned topic with its own summary and disposition. Given "Junk" or
"OK for Now" there is nothing to summarise — and we have already measured (Gap 4)
that a required summary field with no content makes the model invent one.

These are the inputs most likely to produce confident nonsense, and they are not
rare.

---

## 5. Data quality note

The export contains mojibake where apostrophes should be (`Alberto�s`,
`don�t`) — UTF-8 read as a single-byte codepage somewhere in the Excel → CSV
path. Cosmetic for analysis; worth getting a clean export before using this as
golden-set input.

---

## What this means

**For Monday's demo**
- Switch the planned-topic catalog to the 13 product categories as instructed.
- Choose demo topics the dictation will actually name (Appliances, HVAC, Plumbing
  and Pool are the only ones with real frequency).
- Avoid demonstrating a no-contact or one-word visit; neither can currently be
  recorded honestly.

**For the disposition registry** — this materially strengthens the case already
raised. Three outcomes are missing, and they are common rather than edge cases:
quote created/requested (~15% of visits), no contact made (~8%), and renewal
agreed. Until they exist, the agent must pick a wrong code for roughly a quarter
of real visits.

**For AIML-2702** — this dataset is the golden set. Sample it stratified rather
than taking the first N: long multi-topic notes, one-word notes, no-contact
visits, order-placed, quote-created, and notes containing none of the planned
topics. That last stratum is 67% of reality and currently untested.

**For AIML-2703** — nothing here changes the correction path, but the short-note
cases are the most likely to need correction, so they belong in its scenarios.

---

## Open questions for the business

1. **Should a no-contact visit be recordable?** 8% of visits are "nobody was
   there". Today the flow cannot express it — no event type, no disposition.
2. **Should "quote created/sent" be a disposition?** It appears in ~15% of notes
   and is currently forced onto an unrelated code.
3. **Is coverage a blocker or a prompt?** With product categories as planned
   topics, two visits in three mention none of them, so the agent will ask about
   every planned topic on most visits. Acceptable, or should unmentioned topics
   be recorded as not-discussed without interrogation?
4. **Are the 13 categories the real taxonomy, or a demo stand-in?** Actual
   pre-call plans are campaign codes and follow-ups, and are far messier.
