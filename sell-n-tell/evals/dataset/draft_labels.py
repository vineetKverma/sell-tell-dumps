"""Draft the expected answers for each sampled record with Gemini (AIML-2898, step 2).

    uv run python -m evals.dataset.draft_labels --name pilot

Reads ``sample_<name>.jsonl`` and writes ``drafts_<name>.jsonl`` beside it.
Uses the same Vertex settings as the app (``app/.env``). Re-running skips
records already drafted, so an interrupted run can simply be started again.

These are DRAFTS. Nothing here is ground truth until a person has reviewed it
(``review.py``). Two things keep the drafts honest enough to be worth reviewing:

- The model sees only what the agent would hear -- the note -- plus the planned
  topics and the field definitions. Not the pre-call objective: a label taken
  from the plan rather than the note is exactly the restatement failure the
  golden set has to catch.
- Every value must come with a verbatim quote from the note. A quote that is
  not actually in the note is flagged for the reviewer instead of trusted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from evals.dataset.fields import Catalog, load_catalog
from evals.dataset.paths import APP_ENV, DISPOSITIONS_YAML, OUT

# Mirrors notes_workflow.VALID_EVENT_TYPES; tests/test_dataset_labels.py fails
# if the two drift apart.
EVENT_TYPES = ("Meeting", "On-site visit", "Phone Call")
DEFAULT_MODEL = os.getenv("DATASET_LABEL_MODEL", "gemini-2.5-pro")
MAX_ATTEMPTS = 3
# Seconds to wait after each consecutive 429 before trying the same call again.
RATE_LIMIT_WAITS = (15, 30, 60, 120)


def load_dispositions(path: Path = DISPOSITIONS_YAML) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [*data["dispositions"], data["not_covered"]]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


# "..." or a single ellipsis character, as models use to shorten a quote.
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|" + chr(0x2026) + r")\s*")


def is_quote_of(evidence: object, note: str) -> bool:
    """True if ``evidence`` is taken from ``note`` word for word.

    Case and whitespace are ignored. A quote shortened with "..." counts when
    every piece appears in the note, in order -- the model often abbreviates a
    long passage, and flagging a genuine quote only buries the real problems.
    """
    if not isinstance(evidence, str) or not evidence.strip():
        return False
    note, pos = _norm(note), 0
    for piece in (_norm(p) for p in _ELLIPSIS.split(evidence)):
        if not piece:
            continue
        found = note.find(piece, pos)
        if found < 0:
            return False
        pos = found + len(piece)
    return pos > 0


def context_text(record: dict, catalog: Catalog) -> str:
    """The visit as the agent receives it: vertical, planned topics, dictation."""
    vertical = catalog.verticals[record["vertical"]]
    topic_lines = "\n".join(
        f'- "{t["title"]}"' + (f": {t['description_short']}" if t["description_short"] else "")
        for t in record["topics"]
    )
    return f"""Vertical: {vertical.code} - {vertical.name}. What governs the buy here: {vertical.governs_the_buy}

Planned topics for this visit (with the campaign description the agent is given):
{topic_lines}

The dictation:
<<<
{record["note"]}
>>>"""


def rules_text(dispositions: list[dict]) -> str:
    """The labelling rules. Shared word for word by the drafter, the second
    labeller and the judge, so all three are held to the same standard."""
    disposition_lines = "\n".join(
        f"- {d['code']}: {d['label']} (cues: {', '.join(d.get('mapping_keywords') or [])})"
        for d in dispositions
    )
    return f"""Rules:
- Event type: "met with" / "spoke with" / "talked to" a person at the customer is a
  Meeting. A call or phone conversation is a Phone Call. On-site visit is for being
  on site without such a conversation (e.g. walked the property, dropped off
  material, nobody available). If the dictation gives no clue at all how the
  contact happened (e.g. just "missing toilet paper order"), the event type is
  null -- do not guess.
- A topic counts as discussed only if the dictation says something about it.
  Many dictations mention none of the planned topics; then all are not discussed.
- Disposition codes (use 99 when the topic was discussed but no code fits):
{disposition_lines}
- Fields: fill a value only when the dictation states it. Never infer or guess.
  Most fields in most dictations are NOT stated -- null is the normal answer.
- What counts as STATED: the dictation says it, in any words. An explicit
  negative is stated: "nothing more needed at this time" -> Commercial outcome
  "none"; "no issues with deliveries" -> Service issue "none". What needs
  reasoning beyond the words is NOT stated: a job title is not buying authority,
  "busy season" is not an occupancy figure, one order of 3 is not a stocking par,
  "follow up" with no date or action is not a next step.
- Value formats (use exactly these shapes, so two labellers write the same thing):
  Contact identity: "<name or blank> | <role or blank> | orders / approves / neither / unknown"
  Contact outcome: one of "spoke with target", "spoke with alternate", "no contact"
  Commercial outcome: one of "order placed", "quote created", "quote pending approval",
    "return/credit", "none" -- add value or number after a colon if stated
  Counts: "<number> <unit>". Next step: "<action> | <owner> | <date>", leaving a
  part empty when it is not stated. "soon" or "next visit" is not a date.
  Anything else: the shortest phrase that carries the fact.
- Every evidence string must be copied character-for-character from the dictation.
  Do not shorten it with "..."; quote the shortest exact span that proves the value.
- Masked tokens like [NUMBER], [EMAIL], [PHONE] stand for real values; treat
  them as stated."""


# Filled in from the topic answers, never labelled on its own. U-03 ("topic
# status per planned topic") restates the per-topic discussed/disposition
# answers as free text; two labellers never word it the same way, and it caused
# 7 of the 17 wording disagreements when two pilot keys were compared.
DERIVED_FIELDS = frozenset({"U-03"})


def labelled_fields(catalog: Catalog, vertical: str):
    """The fields a labeller answers -- every field except the derived ones."""
    return tuple(f for f in catalog.fields_for(vertical) if f.field_id not in DERIVED_FIELDS)


def field_lines(fields) -> str:
    return "\n".join(f"- {f.field_id} | {f.name} | {f.captures}" for f in fields)


def build_prompt(record: dict, catalog: Catalog, dispositions: list[dict]) -> str:
    fields = labelled_fields(catalog, record["vertical"])
    return f"""You are labelling a golden test set for a voice agent that turns a field
sales rep's post-visit dictation into a structured CRM record. Write the answer
a careful human would, using ONLY what the dictation states.

{context_text(record, catalog)}

Produce exactly this JSON object:
{{
  "event_type": one of {list(EVENT_TYPES)}, or null if the dictation gives no clue,
  "event_type_evidence": verbatim quote from the dictation, or "" if none,
  "topics": [ one entry per planned topic, same titles, same order:
    {{"title": "<planned title>",
      "discussed": true/false,
      "disposition_code": integer code, or null when not discussed,
      "evidence": verbatim quote, or ""}} ],
  "fields": [ one entry per field listed below, same order:
    {{"field_id": "<id>",
      "value": short normalised value, or null if the dictation does not state it,
      "evidence": verbatim quote supporting the value, or "" when value is null}} ]
}}

{rules_text(dispositions)}

Fields:
{field_lines(fields)}
"""


def check_draft(
    draft: dict, record: dict, field_ids: list[str], codes: set[int]
) -> tuple[list[str], list[str]]:
    """(problems, flags). Problems make the draft unusable and trigger a retry;
    flags are passed to the reviewer as things to look at first."""
    problems: list[str] = []
    flags: list[str] = []

    def quoted(evidence: object) -> bool:
        return is_quote_of(evidence, record["note"])

    # None is allowed: some notes ("missing toilet paper order") say nothing
    # about how the contact happened. That record is then not scored on event
    # type, rather than scored against a guess.
    if draft.get("event_type") is not None and draft.get("event_type") not in EVENT_TYPES:
        problems.append(f"event_type {draft.get('event_type')!r} not allowed")
    elif draft.get("event_type_evidence") and not quoted(draft["event_type_evidence"]):
        flags.append("event_type: evidence not found in note")

    planned = [t["title"] for t in record["topics"]]
    topics = draft.get("topics") or []
    if [t.get("title") for t in topics] != planned:
        problems.append("topics do not match the planned titles")
    for t in topics:
        code = t.get("disposition_code")
        if t.get("discussed"):
            if code not in codes:
                problems.append(f"topic {t.get('title')!r}: code {code!r} not allowed")
            if not quoted(t.get("evidence")):
                flags.append(f"topic {t.get('title')!r}: discussed, but evidence not found in note")
        elif code is not None:
            problems.append(f"topic {t.get('title')!r}: not discussed but has code {code}")

    fields = draft.get("fields") or []
    if [f.get("field_id") for f in fields] != field_ids:
        problems.append("fields do not match the expected field list")
    for f in fields:
        if f.get("value") not in (None, "") and not quoted(f.get("evidence")):
            flags.append(f"{f.get('field_id')}: value without a quote found in the note")
    return problems, flags


def _client(location: str | None):
    from dotenv import load_dotenv  # noqa: PLC0415 - only needed for live calls
    from google import genai  # noqa: PLC0415

    load_dotenv(APP_ENV)
    kwargs = {"location": location} if location else {}
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").upper() == "TRUE":
        kwargs.update(vertexai=True, project=os.getenv("GOOGLE_CLOUD_PROJECT"))
        kwargs.setdefault("location", os.getenv("GOOGLE_CLOUD_LOCATION"))
    return genai.Client(**kwargs)


def is_rate_limited(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text


def _generate(client, model: str, prompt: str) -> str:
    """One model call. A rate-limit error (429) is waited out here, with
    growing pauses, before it is allowed to count as a failed attempt -- a
    few seconds is not enough for Vertex quota to recover."""
    from google.genai import types  # noqa: PLC0415

    config = types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json")
    for wait in (*RATE_LIMIT_WAITS, None):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            return response.text or ""
        except Exception as exc:
            if wait is None or not is_rate_limited(exc):
                raise
            print(f"      rate limited by Vertex; waiting {wait}s and trying again")
            time.sleep(wait)
    raise AssertionError("unreachable")


def as_object(draft: object) -> dict | None:
    """The answer object. Some replies wrap it in a one-item list (`[{...}]`),
    which is the same answer; any other list is not."""
    if isinstance(draft, dict):
        return draft
    if isinstance(draft, list) and len(draft) == 1 and isinstance(draft[0], dict):
        return draft[0]
    return None


def draft_record(client, model: str, record: dict, catalog: Catalog, dispositions: list[dict]) -> dict:
    field_ids = [f.field_id for f in labelled_fields(catalog, record["vertical"])]
    codes = {int(d["code"]) for d in dispositions}
    prompt = build_prompt(record, catalog, dispositions)
    last_problems: list[str] = []
    raw = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = _generate(client, model, prompt)
            draft = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_problems = [f"invalid JSON: {exc}"]
            continue
        except Exception as exc:  # API errors: back off and retry
            last_problems = [f"{type(exc).__name__}: {exc}"]
            time.sleep(2 * attempt)
            continue
        obj = as_object(draft)
        if obj is None:
            shape = f"list of {len(draft)}" if isinstance(draft, list) else type(draft).__name__
            last_problems = [f"expected a JSON object, got {shape}"]
            continue
        draft = obj
        problems, flags = check_draft(draft, record, field_ids, codes)
        if not problems:
            return {"draft": draft, "flags": flags, "problems": [], "attempts": attempt}
        last_problems = problems
    # The raw reply is kept (in the drafts file, on this machine) so a failure
    # can be diagnosed from what the model actually said.
    return {"draft": None, "flags": [], "problems": last_problems,
            "attempts": MAX_ATTEMPTS, "raw_response": raw[:4000]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Draft golden-set labels with Gemini.")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--name", default="pilot")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--location", help="override GOOGLE_CLOUD_LOCATION for this run")
    ap.add_argument(
        "--tag",
        help="write drafts_<name>_<tag>.jsonl instead -- used for the blind second "
        "labelling that adjudicate.py compares against",
    )
    args = ap.parse_args()

    sample_path = args.out / f"sample_{args.name}.jsonl"
    drafts_path = args.out / f"drafts_{args.name}{'_' + args.tag if args.tag else ''}.jsonl"
    records = [json.loads(line) for line in sample_path.read_text(encoding="utf-8").splitlines() if line]
    done = set()
    if drafts_path.exists():
        done = {
            json.loads(line)["id"]
            for line in drafts_path.read_text(encoding="utf-8").splitlines()
            if line and json.loads(line).get("draft") is not None
        }

    catalog = load_catalog()
    dispositions = load_dispositions()
    client = _client(args.location)
    todo = [r for r in records if r["id"] not in done]
    print(f"{len(records)} records, {len(done)} already drafted, {len(todo)} to draft with {args.model}")

    with drafts_path.open("a", encoding="utf-8") as fh:
        for n, record in enumerate(todo, 1):
            result = draft_record(client, args.model, record, catalog, dispositions)
            out = {
                **record,
                **result,
                "model": args.model,
                "drafted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            fh.flush()
            status = "ok" if result["draft"] else "FAILED: " + "; ".join(result["problems"])
            print(f"  [{n}/{len(todo)}] {record['id']}  {status}  flags={len(result['flags'])}")

    print(f"\nDrafts written to {drafts_path}")


if __name__ == "__main__":
    main()
