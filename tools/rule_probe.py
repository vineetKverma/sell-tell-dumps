"""A focused experiment on extract()'s two rules behind the steady misses on
key v1.5: the quote rule (HL-005) and the topic rule (IS-010). Nothing in the
repo changes: each arm swaps one rule's wording in memory for the run.

    cd <repo>
    uv run python C:/tmp/rule_probe.py --dry        # check the script, no calls
    uv run python C:/tmp/rule_probe.py              # about 300 calls, a few minutes

Arms (each is the branch's prompt with at most one rule changed):
  branch            the prompt as it is on the branch
  old topic rule    the topic rule as development has it ("talks about the offer
                    or its products"), not "talked with someone at the customer"
  asked-for quote   a quote the customer asked for on that topic's products is
                    code 1, like a quote already given

Cases:
  golden   HL-005 and IS-010, plus the cases the two rules were written for
           (material left with no one spoken to, a quote given, a quote for
           other products, asking for an order). Scored against the key on
           disk; only ids and counts are printed, never note text.
  written  short notes whose answer is set by how they are written (no customer
           data), to see whether each arm keeps the clear cases right.

Results go to evals/runs/probe-<time>/results.json (git-ignored).
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

sys.path.insert(0, os.getcwd())

ex = importlib.import_module("app.extraction.extract")   # the module, not the function

from app.extraction import fields_for, load_catalog, load_dispositions, load_registry  # noqa: E402
from evals.agent_eval.cases import GOLDEN_DIR  # noqa: E402
from evals.extract_eval import run  # noqa: E402

MODEL, THINKING, WORKERS, REPEATS = "gemini-3.8-flash", "low", 8, 5
CALLS = Counter()

# --- the arms ------------------------------------------------------------------

TOPIC_NOW = """is "discussed" ONLY if the rep talked with someone at the customer about that campaign's
  offer, its products or its brand: the rep presenting it, or the customer's reaction to it
  (including a refusal, or preferring another brand or vendor). Material, a flyer or a
  voicemail left about it with no one spoken to does not count, and neither does a related
  but different product (use the description to tell)."""
TOPIC_OLD = """is "discussed" ONLY if the rep talks about that campaign's offer or its products; a
  related but different product does not count (use the description to tell)."""

QUOTE_NOW = """A quote is code 1 only when the rep has already given the
  customer a quote for that topic's products; a quote to be sent later, a quote for
  other products, or the rep asking the customer to order is not code 1."""
QUOTE_ASKED = """A quote is code 1 when the rep has already given the customer
  a quote for that topic's products, or the customer asked the rep for one on that
  topic's products; a quote for other products, or the rep asking the customer to order,
  is not code 1."""

assert TOPIC_NOW in ex.RULES, "the topic rule's wording moved; update this script"
assert QUOTE_NOW in ex.CODES_RULE, "the quote rule's wording moved; update this script"
BASE = (ex.RULES, ex.CODES_RULE)
ARMS = {
    "branch": BASE,
    "old topic rule": (ex.RULES.replace(TOPIC_NOW, TOPIC_OLD), ex.CODES_RULE),
    "asked-for quote": (ex.RULES, ex.CODES_RULE.replace(QUOTE_NOW, QUOTE_ASKED)),
}
assert ARMS["old topic rule"][0] != BASE[0] and ARMS["asked-for quote"][1] != BASE[1], "an arm changed nothing"

# --- the cases -----------------------------------------------------------------

GOLDEN = {
    "HL-005": "a quote the customer will ask for (the dispute)",
    "IS-010": "'Revisit <topic>' with no conversation stated",
    "MH-006": "a quote given (code 1)",
    "HS-002": "a quote for other products",
    "HL-014": "the rep asking for an order",
    "HL-007": "material left, no one spoken to",
    "HS-013": "material left, no one spoken to",
    "IN-005": "material left, no one spoken to",
    "TR-008": "a quote given on other products",
}

TOPIC = "HC Q2 Compact Appliances"
ABOUT = ("Strikethrough pricing on compact refrigerators and countertop microwaves: microwaves from $69, "
         "refrigerators from $99.")
WEATHER = "Severe Weather - Q2 PS"
WEATHER_ABOUT = "Severe weather supplies so customers can protect their properties and minimise storm downtime."
OPEN = "Met with Dana, the maintenance supervisor. "

# (what it tests, topic, about, note, wanted per arm: (status, code) or None = only reported)
WRITTEN = [
    ("quote given", TOPIC, ABOUT, OPEN + "Gave her a quote for the compact fridges.",
     {"*": ("discussed", 1)}),
    ("customer asks for a quote", TOPIC, ABOUT, OPEN + "She asked me for a quote on the countertop microwaves.",
     {"branch": ("discussed", 99), "old topic rule": ("discussed", 99), "asked-for quote": ("discussed", 1)}),
    ("customer will send items to quote", TOPIC, ABOUT,
     OPEN + "Went over the promo. She will send me the fridges she orders so I can quote them.",
     {"branch": ("discussed", 99), "old topic rule": ("discussed", 99), "asked-for quote": ("discussed", 1)}),
    ("rep offers to email a quote", TOPIC, ABOUT, OPEN + "Went over the microwaves. I will email her a quote.",
     None),
    ("quote asked on other products", TOPIC, ABOUT,
     OPEN + "Went over the fridge promo, no interest. She asked for a quote on ceiling tiles.",
     {"*": "not 1"}),
    ("interest only", TOPIC, ABOUT, OPEN + "Showed her the microwave pricing and she seemed interested.",
     {"*": ("discussed", 99)}),
    ("rep asks for the order", TOPIC, ABOUT, OPEN + "Went over the fridges and asked her to place an order.",
     {"*": ("discussed", 99)}),
    ("revisit, customer said so", WEATHER, WEATHER_ABOUT,
     OPEN + "Went over severe weather supplies. She said to revisit it next quarter.",
     {"*": ("discussed", 3)}),
    ("revisit, not got to", WEATHER, WEATHER_ABOUT,
     OPEN + "Spent the visit on open invoices. Did not get to severe weather, will revisit next time.",
     {"*": ("not_discussed", None)}),
    ("revisit, alone (IS-010's shape)", WEATHER, WEATHER_ABOUT,
     "Sorted out a billing question. Revisit severe weather.", None),
    ("flyer left, no one there", WEATHER, WEATHER_ABOUT,
     "Stopped by, no one in the office. Left a severe weather flyer at the desk.",
     {"*": ("not_discussed", None)}),
]


# --- calls -----------------------------------------------------------------------

class FakeClient:
    """--dry: every planned topic discussed on the last sentence with code 99."""

    def __init__(self) -> None:
        class Models:
            def generate_content(self, *, model, contents, config):
                topic = config.response_schema.model_fields["topics"].annotation.__args__[0]
                labels = getattr(topic.model_fields["topic"].annotation, "__args__", ())
                reply = {"event_type": "Meeting", "executive_summary": "x", "must_capture": {},
                         "topics": [{"topic": lab, "status": "discussed", "evidence_lines": [1],
                                     "summary": "x", "outcome_lines": [1], "disposition_code": "99"}
                                    for lab in labels]}
                return type("R", (), {"text": json.dumps(reply)})()
        self.models = Models()


class Setup:
    def __init__(self, dry: bool) -> None:
        self.catalog = load_catalog(GOLDEN_DIR)
        self.registry = load_registry(run.REGISTRY)
        self.codes = load_dispositions()
        self.client = FakeClient() if dry else run._client("global")

    def topics(self, note, planned, vertical, descriptions=None) -> dict | None:
        """{label: (status, code)} from extract() as the golden runs call it; None on an error."""
        CALLS["extract"] += 1
        known = self.registry.descriptions(planned, vertical)
        res = ex.extract(note, planned, vertical, fields_for(self.catalog, vertical), client=self.client,
                         model=MODEL, thinking=THINKING, dispositions=self.codes,
                         descriptions={**known, **(descriptions or {})})
        if res.record is None:
            CALLS[f"extract error ({res.error_kind})"] += 1
            return None
        return {t["topic"]: (t.get("status"), _code(t.get("disposition_code")))
                for t in res.record.get("topics", [])}


def _code(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def matches(answer, want) -> bool:
    """want is (status, code), or "not 1": discussed with any code but 1."""
    if answer is None:
        return False
    if want == "not 1":
        return answer[0] == "discussed" and answer[1] != 1
    return tuple(answer) == want


def pooled(fn, items):
    with ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(fn, items))


def tally(results) -> str:
    """'discussed 1 x3, not_discussed x2' -- each distinct answer and how often."""
    c = Counter("error" if r is None else (f"{r[0]} {r[1]}" if r[1] is not None else r[0]) for r in results)
    return ", ".join(f"{k} x{n}" for k, n in c.most_common())


# --- main ------------------------------------------------------------------------

def main() -> None:
    dry = "--dry" in sys.argv[1:]
    setup = Setup(dry)
    cases = {c.id: c for c in run.set_cases("golden") if c.id in GOLDEN}
    missing = sorted(set(GOLDEN) - set(cases))
    if missing:
        raise SystemExit(f"not in the golden set on disk: {', '.join(missing)}")

    jobs = []
    for arm in ARMS:
        for cid in GOLDEN:
            jobs += [(arm, "golden", cid)] * REPEATS
        for i in range(len(WRITTEN)):
            jobs += [(arm, "written", i)] * REPEATS

    def one(job):
        arm, kind, ref = job
        rules, codes_rule = ARMS[arm]
        # The arms run one after another (below), so the module-level swap is safe.
        if kind == "golden":
            c = cases[ref]
            return setup.topics(c.note, c.planned_topics, c.vertical)
        _, topic, about, note, _ = WRITTEN[ref]
        got = setup.topics(note, [topic], "HL", {topic: about})
        return None if got is None else {topic: got.get(topic)}

    out = {"model": MODEL, "thinking": THINKING, "repeats": REPEATS, "arms": {}}
    for arm, (rules, codes_rule) in ARMS.items():
        ex.RULES, ex.CODES_RULE = rules, codes_rule
        mine = [j for j in jobs if j[0] == arm]
        got = pooled(one, mine)
        out["arms"][arm] = [{"kind": k, "ref": r, "topics": g} for (_, k, r), g in zip(mine, got)]
    ex.RULES, ex.CODES_RULE = BASE

    print(f"model {MODEL}, thinking {THINKING}, {REPEATS} repeats per case and arm")
    print("\n== golden (key v1.5 on disk; ids and counts only) ==")
    for cid, what in GOLDEN.items():
        c = cases[cid]
        print(f"\n{cid}: {what}")
        for t in c.topics:
            label = t["topic"]
            want = ("discussed", t.get("disposition_code")) if t.get("discussed") else ("not_discussed", None)
            print(f"  topic {c.planned_topics.index(label) + 1 if label in c.planned_topics else '?'}"
                  f" -- key: {want[0]}{'' if want[1] is None else ' ' + str(want[1])}")
            for arm, rows in out["arms"].items():
                answers = [None if r["topics"] is None else r["topics"].get(label)
                           for r in rows if r["kind"] == "golden" and r["ref"] == cid]
                right = sum(matches(a, want) for a in answers)
                print(f"    {arm:16s} right {right}/{len(answers)}   {tally(answers)}")

    print("\n== written notes (answer set by how they are written) ==")
    for i, (what, topic, _, note, wants) in enumerate(WRITTEN):
        print(f"\n{what}: \"{note}\"")
        for arm, rows in out["arms"].items():
            answers = [None if r["topics"] is None else r["topics"].get(topic)
                       for r in rows if r["kind"] == "written" and r["ref"] == i]
            want = None if wants is None else wants.get(arm, wants.get("*"))
            mark = "(only reported)" if want is None else f"right {sum(matches(a, want) for a in answers)}/{len(answers)}"
            print(f"    {arm:16s} {mark:16s} {tally(answers)}")

    print("\ncalls: " + ", ".join(f"{k} {v}" for k, v in sorted(CALLS.items())))
    if not dry:
        folder = run.RUNS / f"probe-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        folder.mkdir(parents=True)
        (folder / "results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(f"written: {folder}")


if __name__ == "__main__":
    main()
