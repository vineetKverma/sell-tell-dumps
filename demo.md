# AIML-3152 on the dev machine -- what is left

Run everything in `C:\Developer\sellNtell\sell-n-tell`, in one terminal. Every
command to run is in this file; nothing is only in chat.

## Done

- `development` merged in (`028730b`); review fixes (`3bc5683`, `15a1bb2`);
  replies on all comments posted.
- `extract()` re-measured (`extract-20261120-113412`); agent `development` vs
  branch; agent baseline re-taken and committed (`1d97230`, pushed).
- Step E, the rule experiment (`probe-20261120-182101`): both causes
  confirmed (HL-005: the quote rule; IS-010: the topic rule).

## On hold: the PR description and the reply on the reminder

Do not post them yet. Two steady misses on the branch are being explained
first, and the description will carry the answer:

- **HL-005** (3 of the 5 misses): the branch's quote rule gives 99 to a quote
  the customer will ask for; the key says 1.
- **IS-010** (2 of the 5): the branch's topic rule ("talked with someone at
  the customer") marks "Revisit <topic>" alone as not discussed; the key says
  discussed, code 3.

## Now: nothing to run

Waiting for the business's answers on the two questions (quotes asked for or
offered; "Revisit <topic>" alone). The next dev steps are written once the
answers are in.
