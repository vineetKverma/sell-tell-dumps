"""Score one agent run against the golden answer key. Pure Python, no model.

The agent's whole CRM record is the arguments of its last
``stage_visit_notes`` call, so every metric compares those arguments with the
expected ones in the key:

  event type    one of Meeting / On-site visit / Phone Call
  topic status  each planned topic discussed or not, with no duplicate rows
  disposition   the code chosen for each topic the rep did discuss
  fields        each must-capture field stated or "not stated", and its value
  faithfulness  the agent's summary is grounded in the note (filled in by the
                judge, see judge.py; None when the judge call failed)

Scoring rules fixed by the answer key:
  - an item listed in the case's ``contested`` is skipped
  - event type is skipped when the key says the note gives no clue (None)
  - a field with no stated example reports recall as n/a, never 0
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict

from evals.agent_eval.cases import DERIVED_FIELDS, Case

DISCUSSED, NOT_DISCUSSED, DUPLICATE = "discussed", "not discussed", "duplicate rows"
NOT_STAGED = "not staged"


NO_PERSON_EVENT = "On-site visit"

# "4 by 4", "4 x 4", "4X4" -> "4x4" (approved rule: store dimensions like 4x4,
# keeping whatever unit the rep gave).
_DIMENSION = re.compile(r"(\d+(?:\.\d+)?)\s*(?:by|x|×)\s*(?=\d)", re.IGNORECASE)


def norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _stated(value) -> bool:
    return value not in (None, "") and norm(value) not in ("not stated", "null", "none", "n/a")


_SPOKE_WITH = re.compile(r"^spoke (?:with|to) (?:the |an? )?(\w+)(['’]s\b)?")
_NOBODY = ("no", "nobody", "noone", "none")


def _spoke_with(value: str) -> str | None:
    """"target", "alternate", "someone" (a conversation, with whoever: "spoke
    with contact", "spoke with Rachel, the manager", "spoke with the target's
    assistant"), or None (no conversation: "spoke with no one")."""
    m = _SPOKE_WITH.match(norm(value))
    if not m or m.group(1) in _NOBODY:
        return None
    return m.group(1) if m.group(1) in ("target", "alternate") and not m.group(2) else "someone"


def field_value_agrees(field_id: str, expected: str, actual: str) -> bool:
    """value_agrees, plus one field rule: for U-02 (contact outcome) a KEY of
    "spoke with contact" -- a conversation is clear from the note but not
    whether it was the target or an alternate -- accepts any answer that says
    the rep spoke with someone. A key that names target or alternate still has
    to be matched ("spoke with the target" is the same answer)."""
    if field_id == "U-02":
        e, a = _spoke_with(expected), _spoke_with(actual)
        if e and a:
            return e == "someone" or e == a
    return value_agrees(expected, actual)


def value_agrees(expected: str, actual: str) -> bool:
    """Same after normalising, or one contains the other ("12 units" and
    "12 units a month") -- the rule the two answer-key builds were compared
    with, so the agent is held to the same bar as the key itself."""
    a, b = (_DIMENSION.sub(r"\1x", norm(x)) for x in (expected, actual))
    a, b = re.sub(r"[^\w$%./-]+", " ", a).strip(), re.sub(r"[^\w$%./-]+", " ", b).strip()
    return a == b or (min(len(a), len(b)) >= 3 and (a in b or b in a))


# ---------------------------------------------------------------------------
# One case
# ---------------------------------------------------------------------------

def score_case(case: Case, actual: dict | None) -> dict:
    """``actual``: the args of the agent's last stage_visit_notes call, or None
    if it never staged. Returns a JSON-safe dict of per-item outcomes."""
    staged = actual is not None
    actual = actual or {}
    out: dict = {"id": case.id, "vertical": case.vertical, "staged": staged,
                 "event_type": None, "topics": [], "off_plan": [], "fields": [],
                 "fields_captured": "must_capture" in actual, "faithful": None}

    # Event type. The key leaves it null when the note shows no conversation
    # and no call; the business's rule (Jeremy, AIML-1537 thread; confirmed
    # by Tobi, 2026-10-14) makes that On-site visit: a Meeting is a business
    # conversation with a customer contact, and front desk or gatekeeper only
    # is an On-site visit.
    if "event_type" not in case.contested:
        want = case.event_type or NO_PERSON_EVENT
        got = actual.get("event_type")
        out["event_type"] = {"expected": want, "actual": got, "ok": norm(got) == norm(want)}

    # Topics
    rows = [t for t in (actual.get("topics") or []) if isinstance(t, dict)]
    planned = {norm(t) for t in case.planned_topics}
    out["off_plan"] = [t.get("topic") for t in rows if norm(t.get("topic")) not in planned]
    for exp in case.topics:
        title = exp["topic"]
        if title in case.contested:
            continue
        mine = [t for t in rows if norm(t.get("topic")) == norm(title)]
        if not staged:
            status, code = NOT_STAGED, None
        elif len(mine) > 1:
            status, code = DUPLICATE, None
        elif mine and mine[0].get("discussed", True):
            status, code = DISCUSSED, mine[0].get("disposition_code")
        else:
            status, code = NOT_DISCUSSED, None
        want = DISCUSSED if exp["discussed"] else NOT_DISCUSSED
        item = {"topic": title, "expected": want, "actual": status,
                "status_ok": status == want}
        if exp["discussed"]:
            item["expected_code"] = exp["disposition_code"]
            item["actual_code"] = code
            item["code_ok"] = status == DISCUSSED and _as_int(code) == exp["disposition_code"]
        out["topics"].append(item)

    # Must-capture fields
    got_fields = actual.get("must_capture") or {}
    for fid, want in case.fields.items():
        if fid in DERIVED_FIELDS or fid in case.contested:
            continue
        got = got_fields.get(fid)
        e, a = _stated(want), _stated(got)
        outcome = ("TP" if e and a else "FN" if e else "FP" if a else "TN")
        item = {"field": fid, "expected": want, "actual": got, "outcome": outcome}
        if outcome == "TP":
            item["value_ok"] = field_value_agrees(fid, want, got)
        out["fields"].append(item)
    return out


def _as_int(code):
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Many cases
# ---------------------------------------------------------------------------

def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def aggregate(scores: list[dict], priorities: dict[str, int]) -> dict:
    """Roll up per group: 'all' plus each vertical. Field precision/recall are
    also rolled up per priority and per field."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in scores:
        groups["all"].append(s)
        groups[s["vertical"]].append(s)
    return {g: _rollup(items, priorities) for g, items in sorted(
        groups.items(), key=lambda kv: (kv[0] != "all", kv[0]))}


def _rollup(scores: list[dict], priorities: dict[str, int]) -> dict:
    ev = [s["event_type"] for s in scores if s["event_type"]]
    topics = [t for s in scores for t in s["topics"]]
    codes = [t for t in topics if "code_ok" in t]
    judged = [s["faithful"] for s in scores if s["faithful"] is not None]
    captured = any(s["fields_captured"] for s in scores)

    by_prio: dict[str, list[dict]] = defaultdict(list)
    by_field: dict[str, list[dict]] = defaultdict(list)
    for s in scores:
        for f in s["fields"]:
            by_prio[f"P{priorities.get(f['field'], '?')}"].append(f)
            by_field[f["field"]].append(f)

    not_discussed = [t for t in topics if t["expected"] == NOT_DISCUSSED]
    return {
        "cases": len(scores),
        "not_staged": sum(not s["staged"] for s in scores),
        "event_type": _acc(sum(e["ok"] for e in ev), len(ev)),
        "topic_status": _acc(sum(t["status_ok"] for t in topics), len(topics)),
        # Of the planned topics the rep did NOT discuss, the share the agent
        # claimed as discussed -- the costly miss (an outcome is recorded for a
        # campaign nobody talked about). Lower is better.
        "over_claimed": _acc(sum(t["actual"] == DISCUSSED for t in not_discussed), len(not_discussed)),
        "disposition": _acc(sum(t["code_ok"] for t in codes), len(codes)),
        "duplicate_rows": sum(t["actual"] == DUPLICATE for t in topics),
        "off_plan_rows": sum(len(s["off_plan"]) for s in scores),
        "faithfulness": _acc(sum(judged), len(judged)),
        "fields_captured": captured,
        "fields": {"all": _prf(sum(by_prio.values(), []))}
                  | {p: _prf(v) for p, v in sorted(by_prio.items())},
        "per_field": {fid: _prf(v) for fid, v in sorted(by_field.items())},
    }


def _acc(ok: int, n: int) -> dict:
    return {"ok": ok, "n": n, "rate": _rate(ok, n)}


def _prf(items: list[dict]) -> dict:
    c = defaultdict(int)
    for f in items:
        c[f["outcome"]] += 1
    right = sum(1 for f in items if f.get("value_ok"))
    return {
        "stated": c["TP"] + c["FN"],
        "tp": c["TP"], "fn": c["FN"], "fp": c["FP"], "tn": c["TN"],
        # recall: of what the rep said, how much the agent captured
        "recall": _rate(c["TP"], c["TP"] + c["FN"]),
        # precision: of what the agent filled in, how much the rep said
        "precision": _rate(c["TP"], c["TP"] + c["FP"]),
        # fabrication: of what the rep did NOT say, how much the agent filled in
        "fabrication": _rate(c["FP"], c["FP"] + c["TN"]),
        # value accuracy: of the fields captured, how many match the key
        "value_accuracy": _rate(right, c["TP"]),
    }


# ---------------------------------------------------------------------------
# Repeats: run-to-run variance
# ---------------------------------------------------------------------------

HEADLINE = ("event_type", "topic_status", "disposition", "faithfulness")


def variance(runs: list[dict]) -> dict:
    """Spread of each headline rate (group 'all') across repeated runs of the
    same config, so a real change can be told from model noise."""
    out = {}
    for m in HEADLINE:
        vals = [r["all"][m]["rate"] for r in runs if r["all"][m]["rate"] is not None]
        if vals:
            out[m] = {"runs": len(vals), "mean": statistics.fmean(vals),
                      "min": min(vals), "max": max(vals),
                      "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0}
    return out
