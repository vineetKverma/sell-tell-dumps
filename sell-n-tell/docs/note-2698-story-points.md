# Draft message — AIML-2698 story points 3 → 5

*(for Sainitheesh, Teams or a ticket comment)*

---

Hi Sainitheesh — could we bump AIML-2698 from 3 to 5 points? It's complete and
verified, but it ran wider than the ticket described.

Three of the five gaps listed in the ticket turned out to be already fixed on
your branch. In their place we found five more, three of which only reproduce in
a live session:

- Commit succeeded on records the system already knew were incomplete — it
  computed `missing_topics` and stored it on the record, but nothing gated on it.
- The staging endpoint took no `campaign_type`, so campaign rules could not be
  enforced at all; both event types and disposition codes were validated against
  the global lists.
- The model could mark a planned topic "not discussed" with an invented reason
  and satisfy the coverage check without ever asking the rep.
- A campaign registry with no fitting code produced random wrong dispositions —
  six runs of one utterance returned "Order Placed" or "No current need" at
  random. Fixed by adding an "Outcome not covered" code (needs your sign-off,
  separate note).
- The frontend reported "Saved to CRM" on refused commits, which our own
  backend change exposed.

Two extra pieces of work that weren't foreseeable from the ticket:

- **The smoke harness was non-functional.** `turn_guard` only counted audio
  turns, so every gated tool was permanently blocked for text input — guided
  mode had never had any automated coverage. That had to be fixed before AC#5
  could even be attempted, along with a turn-synchronisation bug in the harness.
- **A prompt-level fix for the disposition problem was tried, measured over
  three runs before and after, and failed** — which is what led to the
  registry-level fix. Worth the detour, but it was a detour.

All five ACs are now met: 9 REST regression cases, a dual-mode dry run across 8
conversational scenarios (logs ready for your review), and the failure-modes
runbook.

The harness work also de-risks AIML-2703 and AIML-2702, since both depend on it.
