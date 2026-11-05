"""extract(): one text Gemini call returns the whole record in a fixed schema.

The schema (``record_model``) fixes the record's shape, so there is no repair
step: a reply that does not validate is an error, never patched. Every
must-capture field is optional -- null is the normal answer.

After the call, code (not the model) settles each planned topic:

  - a topic the model marked discussed keeps that status only if its
    ``evidence`` is the rep's own words: found in the dictation and at least
    MIN_EVIDENCE_WORDS different words that are not filler (one word, such as
    "pools", or "the pools", is not evidence). Otherwise it becomes ``unconfirmed`` (the live flow asks
    the rep about it), never discussed, and its evidence is dropped. Its
    summary is kept, marked unverified by the ``unconfirmed`` status: it is
    what the model heard, so the live flow builds the rep's question from it.
    This assumes the rep confirms an unconfirmed topic before the record is
    committed; unconfirmed text must never be saved as confirmed. The
    check proves the words are the rep's, not that they are about the
    campaign ("Nothing on pools" is the rep's words): that judgement stays
    the model's, and the eval measures it (over-claimed);
  - a planned topic the model left out is not discussed;
  - a topic label that is not one of the planned topics is reported as
    off-plan and dropped.

With ``dispositions`` (AIML-3004), each discussed topic also gets a code from
the registry, and code settles it too:

  - a code other than 99 stays only if ``outcome_evidence`` -- the rep's own
    words for that outcome -- passes the same check as a topic's evidence (in
    the dictation, with two different non-filler words); otherwise it becomes
    99 (manual review);
  - a discussed topic with no code is 99; a topic that is not discussed (or
    unconfirmed) has no code.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import pydantic

from app.extraction.catalog import Field

EVENT_TYPES = ("Meeting", "On-site visit", "Phone Call")
DISCUSSED, NOT_DISCUSSED, UNCONFIRMED = "discussed", "not_discussed", "unconfirmed"
NOT_STATED = ("", "not stated", "null", "none", "n/a")
MIN_QUOTE_CHARS = 4
# Measured on key v1.4: two words lose one right call in three runs; three
# words, or refusing evidence made only of the label's words, lose 11 (reps
# name a campaign by its own words).
MIN_EVIDENCE_WORDS = 2
# Words that do not count towards MIN_EVIDENCE_WORDS ("the pools" is one word).
# "no pools" and "about it" are one word too; a negation is the model's call (over-claimed).
_FILLER = frozenset("a an the on of to for with and or in at by is was no not about it this that".split())
# About five times the longest dictation in the eval sets (1,804 characters);
# a longer note is refused before the call.
MAX_NOTE_CHARS = 10_000
# Fields that are a count and nothing else: a value without a digit ("turns")
# is dropped. Other "how many" fields mix in text by definition (e.g. HL-03
# "bed count, facility type and census"), so they are not checked this way.
COUNT_FIELDS = ("U-10",)
# A number as digits or spelled out ("twelve units", "a dozen keys").
_HAS_NUMBER = re.compile(
    r"\d|\b(?:(?<!\bno[ \-‐-―])one(?![ -](?:off|time)\b)|couple|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"zero|hundreds?|thousands?|dozens?)\b", re.IGNORECASE)


class TopicResult(pydantic.BaseModel):
    topic: str = pydantic.Field(description="The planned topic's label, copied exactly.")
    status: Literal["discussed", "not_discussed"]
    evidence: str = pydantic.Field(
        default="",
        description="For a discussed topic: the rep's exact words about this campaign's offer or "
                    "products, copied verbatim from the dictation. Empty when not discussed.")
    summary: str = pydantic.Field(
        default="", description="One sentence on this topic, using only what the rep said. "
                                "Empty when not discussed.")


def _key(field_id: str) -> str:
    return field_id.replace("-", "_")


def record_model(fields: list[Field], planned: list[str] | None = None,
                 codes: list[int] | None = None) -> type[pydantic.BaseModel]:
    """The record's schema for one visit: event type, summary, topics and the
    vertical's must-capture fields, each optional. With ``planned``, a topic's
    label can only be one of those exact titles (an enum in the schema), so
    the model cannot return a label the code would fail to match. With
    ``codes``, each topic also carries a disposition code from that list (as
    text: the schema's enums are strings) and the rep's words for it."""
    captured = pydantic.create_model(
        "MustCapture",
        **{_key(f.id): (Optional[str], pydantic.Field(
            default=None, description=f"{f.id} {f.name}: {f.captures} Null when the rep did not say it."))
           for f in fields})
    topic = TopicResult
    labels = tuple(dict.fromkeys(planned or ()))
    extra: dict[str, Any] = {}
    if labels:
        extra["topic"] = (Literal[labels], pydantic.Field(description="The planned topic's label."))
    if codes:
        extra["disposition_code"] = (Optional[Literal[tuple(str(c) for c in codes)]], pydantic.Field(
            default=None, description="For a discussed topic: the outcome code that matches what the rep "
                                      "said about this campaign; 99 when no code fits or no outcome was "
                                      "stated. Null when not discussed."))
        extra["outcome_evidence"] = (str, pydantic.Field(
            default="", description="For a code other than 99: the rep's own words about the outcome, "
                                    "copied verbatim from the dictation. Empty otherwise."))
    if extra:
        topic = pydantic.create_model("PlannedTopic", __base__=TopicResult, **extra)
    return pydantic.create_model(
        "VisitRecord",
        event_type=(Literal[EVENT_TYPES], ...),
        executive_summary=(str, pydantic.Field(
            description="Two sentences on the whole visit, using only what the rep said.")),
        topics=(list[topic], ...),
        must_capture=(captured, ...),
    )


RULES = """You turn a field sales rep's dictated visit note into one CRM record.

Rules:
- Event type: "Phone Call" if the rep says the conversation was by phone. Otherwise
  "Meeting" if the rep had a conversation about the business with someone at the
  customer -- the decision maker or another customer contact such as a manager,
  supervisor or buyer, named or not ("met with Sarah", "the maintenance supervisor
  wants a quote", "she told me"). Otherwise "On-site visit" -- including when the rep
  only spoke to the front desk, a receptionist or another gatekeeper, only left samples
  or materials, or the contact was not available ("Lendy was off today").
  Decide by what happened, not by words like "meeting" or "on site".
- Topics: give one entry for every planned topic, with its label copied exactly. A topic
  is "discussed" ONLY if the rep talks about that campaign's offer or its products; a
  related but different product does not count (use the description to tell). For a
  discussed topic, "evidence" must be the rep's own words about it, copied verbatim from
  the dictation. If you cannot quote such words, the topic is "not_discussed".
- Must-capture fields: fill a field only when the rep states it. Never infer, guess or
  pad; null is the normal answer. Store dimensions like 4x4, keeping the rep's unit if
  given. In Trades, trucks count the way units or properties do in other verticals.
- Next step (U-09): when the rep says what will happen next, record it as
  "action | owner | date", leaving owner or date empty when the rep does not say them
  ("email quote | |", "follow up | | next week"). Record the action even with no owner
  or date; never invent an owner, a date or an action.
- Summaries say only what the rep said. Do not add reasons, outcomes, names or numbers
  the rep did not give.
"""


def _unmark(text: str) -> str:
    """No text in the prompt can hold the dictation block's markers: "<<<" or
    ">>>" is spaced out, so a note, title or description cannot close the
    block or open a fake one. (The label the model returns is still fixed to
    the planned title by the schema.)"""
    return re.sub(r"([<>])(?=\1\1)", r"\1 ", text)


CODES_RULE = """- Outcome codes: for each discussed topic, choose the code below that matches the
  outcome the rep stated for that campaign, and copy the rep's words about that outcome
  into outcome_evidence. If no code fits, or the rep stated no outcome, the code is 99:
  never pick a code because it sounds close. A topic that was not discussed has no code."""


def build_prompt(note: str, planned: list[str], vertical: str,
                 descriptions: dict[str, str] | None = None,
                 dispositions: dict[int, str] | None = None) -> str:
    descriptions = descriptions or {}
    topic_lines = "\n".join(
        f"{i}. label: {_unmark(t)}\n   about: "
        f"{_unmark(descriptions.get(t) or '(no description; judge by the label)')}"
        for i, t in enumerate(planned, 1)
    ) or "(none)"
    note = _unmark(note)
    codes = ""
    if dispositions:
        code_lines = "\n".join(f"  {c}: {label}" for c, label in dispositions.items())
        codes = f"{CODES_RULE}\n\nOutcome codes:\n{code_lines}\n"
    return (f"{RULES}{codes}\nAccount vertical: {vertical}\n\nPlanned topics (the topic field is the label "
            f"only, never the description):\n{topic_lines}\n\nDictation:\n<<<\n{note}\n>>>")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                         "–": "-", "—": "-"}))
    return re.sub(r"\s+", " ", text).strip(" .,;:!?\"'")


def quote_in(quote: str, note: str) -> bool:
    """The quote is the rep's own words: it, or every part of it around an
    ellipsis, appears in the note (ignoring case, spacing and curly quotes).

    Each part must be at least MIN_QUOTE_CHARS letters or digits, start and
    end on word boundaries, and the parts must come in the order they appear
    in the note -- so loose fragments ("a ... e ... i") or words stitched
    together out of order do not pass as evidence.

    A quote found whole is the rep's words even when the rep's own note has an
    ellipsis in it ("Ok... he wants 6 units"), so that is tried first."""
    hay, pos = _norm(note), 0

    def find(part: str, start: int):
        if len(re.sub(r"[\W_]", "", part)) < MIN_QUOTE_CHARS:
            return None
        return re.compile(r"(?<!\w)" + re.escape(part) + r"(?!\w)").search(hay, start)

    if find(_norm(quote or ""), 0):
        return True
    parts = [p for p in (_norm(x) for x in re.split(r"\.\.\.|…", quote or "")) if p]
    for part in parts:
        found = find(part, pos)
        if not found:
            return False
        pos = found.end()
    return bool(parts)


def evidence_ok(quote: str, note: str) -> bool:
    """A topic's evidence: the rep's own words (``quote_in``) and at least
    MIN_EVIDENCE_WORDS different words that are not filler.

    Known limits, kept: the words are counted over the whole quote, so two
    one-word parts around an ellipsis pass ("Frank ... pools"), and an
    apostrophe splits a word ("pool's" is two)."""
    words = set(re.findall(r"\w+", _norm(quote or ""))) - _FILLER
    return len(words) >= MIN_EVIDENCE_WORDS and quote_in(quote, note)


@dataclass
class ExtractResult:
    record: dict[str, Any] | None = None       # the settled record (see postprocess)
    raw: dict[str, Any] | None = None          # what the model returned, validated
    unconfirmed: list[str] = field(default_factory=list)
    off_plan: list[str] = field(default_factory=list)
    error: str | None = None
    # "call": the request failed (network, quota, a bad setting) -- says nothing
    # about the model. "reply": the model answered but not in the schema --
    # model behaviour, scored as a record that was never produced.
    # "internal": our own code failed after a valid reply (reading usage,
    # settling the record) -- a bug, never scored as the model's miss.
    # "input": the dictation was refused before any call (over MAX_NOTE_CHARS)
    # -- retrying cannot help.
    error_kind: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)   # tokens and seconds of the call
    # topics whose code fell back to 99 because its evidence was not in the note
    codes_downgraded: list[str] = field(default_factory=list)


NONE_FITS = 99


def postprocess(raw: dict[str, Any], note: str, planned: list[str],
                codes: list[int] | None = None) -> ExtractResult:
    """Settle the validated model output into the record (code, not model).
    With ``codes``: a discussed topic keeps a code other than 99 only if the
    rep's words for it pass ``evidence_ok``, otherwise 99; a missing code is 99;
    a topic that is not discussed has none."""
    by_label = {}
    off_plan = []
    planned = list(dict.fromkeys(planned))         # a title planned twice is one topic
    planned_keys = {_norm(p): p for p in planned}
    for t in raw.get("topics") or []:
        # The exact title first: two titles that differ only in case or edge
        # punctuation share a normalised key.
        label = (t["topic"] if t["topic"] in planned else None) or planned_keys.get(_norm(t["topic"])) or next(
            (p for k, p in planned_keys.items() if _norm(t["topic"]).startswith(k + ":")), None)
        if label is None:
            off_plan.append(t["topic"])
        else:
            by_label.setdefault(label, t)          # first entry wins; duplicates ignored
    topics, unconfirmed, downgraded = [], [], []
    for label in planned:
        t = by_label.get(label)
        status = t["status"] if t else NOT_DISCUSSED
        if status == DISCUSSED and not evidence_ok(t.get("evidence", ""), note):
            status = UNCONFIRMED
            unconfirmed.append(label)
        topic = {"topic": label, "status": status,
                 "evidence": (t or {}).get("evidence", "") if status == DISCUSSED else "",
                 # kept for an unconfirmed topic (the rep's question is built from it);
                 # the status marks it unverified
                 "summary": (t or {}).get("summary", "") if status != NOT_DISCUSSED else ""}
        if codes:
            code, outcome = None, ""
            if status == DISCUSSED:
                given = (t or {}).get("disposition_code")
                code = int(given) if given not in (None, "") else NONE_FITS
                outcome = (t or {}).get("outcome_evidence", "")
                if code != NONE_FITS and not evidence_ok(outcome, note):   # the topic evidence's rule
                    code, outcome = NONE_FITS, ""
                    downgraded.append(label)
                if code == NONE_FITS:
                    outcome = ""
            topic.update(disposition_code=code, outcome_evidence=outcome)
        topics.append(topic)
    fields = {k.replace("_", "-"): (None if v is None or _norm(v) in NOT_STATED else v)
              for k, v in (raw.get("must_capture") or {}).items()}
    for fid in COUNT_FIELDS:        # a count with no number in it is not a count
        if fields.get(fid) and not _HAS_NUMBER.search(re.sub(r"\s+", " ", fields[fid])):
            fields[fid] = None
    record = {"event_type": raw["event_type"], "executive_summary": raw.get("executive_summary", ""),
              "topics": topics, "must_capture": fields}
    return ExtractResult(record=record, raw=raw, unconfirmed=unconfirmed, off_plan=off_plan,
                         codes_downgraded=downgraded)


def thinking_config(thinking: str | int | None):
    """``None``: the model's default. A level name (minimal / low / medium /
    high; the 3.x models) or a token budget (0 = off; the 2.5 models)."""
    from google.genai import types

    if thinking is None:
        return None
    if isinstance(thinking, int) or str(thinking).lstrip("-").isdigit():
        return types.ThinkingConfig(thinking_budget=int(thinking))
    return types.ThinkingConfig(thinking_level=str(thinking).upper())


def extract(note: str, planned: list[str], vertical: str, fields: list[Field], *,
            client, model: str, descriptions: dict[str, str] | None = None,
            thinking: str | int | None = None, dispositions: dict[int, str] | None = None) -> ExtractResult:
    """One Gemini call. ``client`` is a google.genai Client (any object with
    ``models.generate_content``). Never raises: a failed call or a reply that
    does not fit the schema is returned as ``error``. With ``dispositions``
    ({code: label}), each discussed topic also gets a disposition code."""
    from google.genai import types

    planned = list(dict.fromkeys(planned or ()))   # a title planned twice is one topic
    if len(note or "") > MAX_NOTE_CHARS:            # refused before any call
        return ExtractResult(error=f"dictation is {len(note)} characters; the limit is {MAX_NOTE_CHARS}",
                             error_kind="input", usage={"seconds": 0.0})
    started = time.monotonic()
    try:        # the setup is inside too: a bad setting is an error result, not a crash
        codes = sorted(dispositions) if dispositions else None
        schema = record_model(fields, planned, codes)
        config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                             response_schema=schema, thinking_config=thinking_config(thinking))
        resp = client.models.generate_content(
            model=model, contents=build_prompt(note, planned, vertical, descriptions, dispositions),
            config=config)
    except Exception as exc:  # setup, network, quota, auth
        return ExtractResult(error=f"{type(exc).__name__}: {exc}"[:500], error_kind="call",
                             usage={"seconds": round(time.monotonic() - started, 2)})
    seconds = time.monotonic() - started
    try:
        usage = usage_of(resp, seconds)
    except Exception as exc:  # our code, not the model: an SDK change in the usage fields
        return ExtractResult(error=f"reading token usage failed: {type(exc).__name__}: {exc}"[:500],
                             error_kind="internal", usage={"seconds": round(seconds, 2)})
    try:
        raw = schema.model_validate(json.loads(resp.text)).model_dump()
    except (pydantic.ValidationError, ValueError, TypeError) as exc:  # the model answered, but not with a record
        return ExtractResult(error=f"reply does not fit the schema: {exc}"[:500], error_kind="reply",
                             usage=usage)
    try:
        result = postprocess(raw, note, planned, codes)
    except Exception as exc:  # our code, not the model
        return ExtractResult(error=f"settling the record failed: {type(exc).__name__}: {exc}"[:500],
                             error_kind="internal", usage=usage)
    result.usage = usage
    return result


def usage_of(resp, seconds: float) -> dict[str, Any]:
    """Tokens as the API reports them (``usage_metadata``), and the call's time.
    Thinking tokens are billed as output."""
    meta = getattr(resp, "usage_metadata", None)
    get = lambda name: int(getattr(meta, name, None) or 0)  # noqa: E731
    return {"input_tokens": get("prompt_token_count"), "output_tokens": get("candidates_token_count"),
            "thinking_tokens": get("thoughts_token_count"), "seconds": round(seconds, 2)}
