"""Drafts expressed as review-sheet answers. No spreadsheet library needed, so
the unit tests and the adjudicator can use it without openpyxl."""

from __future__ import annotations

import json
from pathlib import Path

NOT_STATED = "(not stated)"
NOT_DISCUSSED = "not discussed"


def latest_drafts(path: Path) -> list[dict]:
    """Last line per record wins: a re-run after a failure appends a new line."""
    by_id: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            rec = json.loads(line)
            by_id[rec["id"]] = rec
    return list(by_id.values())


def disposition_text(topic: dict, labels: dict[int, str]) -> str:
    if not topic.get("discussed"):
        return NOT_DISCUSSED
    code = topic.get("disposition_code")
    return f"{code} - {labels.get(code, '?')}"


def derive_topic_status(topics: list[dict], labels: dict[int, str]) -> str:
    """U-03 built from the expected topic answers, in one fixed wording."""
    parts = []
    for t in topics:
        if t.get("discussed"):
            code = t.get("disposition_code")
            parts.append(f"{t['title']}: discussed - {code} {labels.get(code, '?')}")
        else:
            parts.append(f"{t['title']}: {NOT_DISCUSSED}")
    return " | ".join(parts)


def row_answers(draft: dict, labels: dict[int, str]) -> dict[str, str]:
    """A draft as review-sheet values, keyed like the sheet's ``key`` column."""
    answers = {"event_type": draft.get("event_type") or NOT_STATED}
    for t in draft["topics"]:
        answers[t["title"]] = disposition_text(t, labels)
    for f in draft["fields"]:
        answers[f["field_id"]] = NOT_STATED if f.get("value") in (None, "") else str(f["value"])
    return answers
