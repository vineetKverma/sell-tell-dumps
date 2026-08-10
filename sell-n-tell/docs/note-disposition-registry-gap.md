# Disposition registry gap — fixed, needs your sign-off

*(draft message for Sainitheesh / the AIML-2698 ticket)*

---

While closing the disposition-correctness gaps in AIML-2698 I found a case
where the agent produced confidently wrong CRM data. It's fixed and verified,
but the fix adds a disposition code, so I'd like your sign-off on the semantics.

## The problem

On a `renewals` call, this dictation:

> "Just got off the phone with Acme about their renewal. They're really
> interested and want me to send over a quote."

produced **2 — Order Placed** or **3 — No current need, revisit** at random.
Six runs gave 2, 3, 3, 2, 2, 3. Code 2 says the sale closed; code 3 says there's
no deal. Neither happened — the customer asked for a quote.

It isn't a model-quality problem. The same campaign with an utterance that
*does* have a matching code ("our price is about 10% higher than a competitor")
mapped to **8 — Pricing concerns** correctly every time.

The cause is that `renewals` allows codes 2, 3, 5, 8, 9, and **none of them
describes "customer is interested and requested a quote."** Create Opportunity
(1) would, but it's excluded from this campaign. With no correct option, the
model picks the nearest, and which "nearest" it lands on varies run to run.

Two things made this the dangerous kind of bug: nothing errors, so the readback
sounds fluent and the rep says "Save" — and in one run the free-text summary was
accurate ("the next step is to prepare and send a formal quote") while the
disposition code said Order Placed. **The prose a human would read was right;
the structured field that feeds reporting was wrong.**

## What didn't work

First attempt was a prompt rule: if no code fits, ask the rep or flag for manual
review. Measured over three runs before and three after — no change, it never
flagged once. Filling a structured field is effectively an argmax over the
allowed values: there is always a "best" one. Asking the model to judge that its
own best answer is wrong is self-calibration, and it competes with the schema,
the flow and the registry all telling it to produce a code.

(One real bug fixed on the way: `needs_manual_review` was being silently dropped
before reaching the API, so implicit mode could never set it even if it tried.)

## What did work

Add **code 99 — "Outcome not covered - needs manual review"** as a real entry in
every campaign registry, so "none of these" becomes an ordinary option the model
can select rather than an exception it has to volunteer. Setting 99
automatically flags the topic for manual review, server-side, so all flows agree.

Verified live, six runs:

| Campaign | Utterance | Expected | Result |
|---|---|---|---|
| renewals | "interested, wants a quote" | 99 — nothing fits | **99, 99** |
| renewals | "price ~10% higher" | 8 — fits | **8, 8** |
| standard_sales | "interested, wants a quote" | 1 — fits | **1, 1** |

The last two are the over-triggering controls: 99 never won when a real code was
available. Rows 1 and 3 are the same sentence under different campaigns.

## What I'd like from you

1. **Is a 99 "outcome not covered" code acceptable**, and is that the right
   label? The agent reads it aloud, so wording matters — currently the rep hears
   *"marked as outcome not covered, needs manual review."*
2. **Should `renewals` also include code 1 (Create Opportunity)?** Renewal
   conversations do generate new opportunities, so excluding it may have been an
   oversight. With 99 in place this is no longer urgent — the call gets flagged
   rather than mis-recorded — but adding 1 would capture it properly instead of
   sending it for review.
3. **Who reviews flagged records, and where?** Right now `needs_manual_review`
   is set on the record but nothing downstream consumes it. For the demo that's
   fine; before real use it needs an owner.

Full evidence and repro steps: `docs/AIML-2698-experiments.md` and
`docs/change-log.md`.
