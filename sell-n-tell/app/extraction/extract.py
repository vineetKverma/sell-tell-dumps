"""extract(): one text Gemini call returns the whole record in a fixed schema.

The schema (``record_model``) fixes the record's shape, so there is no repair
step: a reply that does not validate is an error, never patched. Every
must-capture field is optional -- null is the normal answer.

Evidence is given by reference (AIML-3152): the prompt shows the dictation
as numbered sentences (``sentences``), the model lists the numbers
(``evidence_lines``, ``outcome_lines``), and code copies those sentences into
the record. So evidence in the record is the rep's words by construction: the
model never types it, and cannot misquote it. A number that is not a sentence
of the note is ignored. Evidence can be no finer than a sentence: a note with
no sentence ends is one unit, and citing it cites the whole note.

After the call, code (not the model) settles each planned topic:

  - a topic the model marked discussed keeps that status only if the
    sentences it cites hold at least MIN_EVIDENCE_WORDS different words that
    are not filler (no sentence cited, or only "Pools.", is not evidence).
    Otherwise it becomes ``unconfirmed`` (the live flow asks the rep about
    it), never discussed, and it keeps no evidence. Its
    summary is kept, marked unverified by the ``unconfirmed`` status: it is
    what the model heard, so the live flow builds the rep's question from it.
    This assumes the rep confirms an unconfirmed topic before the record is
    committed; unconfirmed text must never be saved as confirmed. The
    check proves the words are the rep's, not that they are about the
    campaign ("Nothing on pools." is a sentence of the note): that judgement
    stays the model's, and the eval measures it (over-claimed);
  - a planned topic the model left out is not discussed;
  - a topic label that is not one of the planned topics is reported as
    off-plan and dropped.

With ``dispositions`` (AIML-3004), each discussed topic also gets a code from
the registry, and code settles it too:

  - a code other than 99 stays only if the sentences in ``outcome_lines``
    pass the same check as a topic's evidence (sentences of the note, with
    two different non-filler words); otherwise it becomes 99 (manual review);
  - a discussed topic with no code is 99; a topic that is not discussed (or
    unconfirmed) has no code.

That check proves the outcome words are the rep's, not that they state that
outcome for that topic: a sentence that negates the outcome ("He did not
place an order."), another topic's outcome, or the topic's own evidence
sentences again all pass. Whether the code is right stays the model's call;
the eval measures it as disposition.
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
# Measured on key v1.4 with quoted evidence: two words lose one right call in
# three runs; three words, or refusing evidence made only of the label's
# words, lose 11 (reps name a campaign by its own words).
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
    evidence_lines: list[int] = pydantic.Field(
        default_factory=list,
        description="For a discussed topic: the numbers of the dictation sentences where the rep talks "
                    "about this campaign's offer or products. Empty when not discussed.")
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
    text: the schema's enums are strings) and the sentences that state it."""
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
        # The sentences come before the code, so the model points at the
        # rep's words first and chooses the code from them.
        extra["outcome_lines"] = (list[int], pydantic.Field(
            default_factory=list, description="For a code other than 99: the numbers of the dictation "
                                              "sentences that state the outcome. Empty otherwise."))
        extra["disposition_code"] = (Optional[Literal[tuple(str(c) for c in codes)]], pydantic.Field(
            default=None, description="For a discussed topic: the outcome code that matches what the rep "
                                      "said about this campaign; 99 when no code fits or no outcome was "
                                      "stated. Null when not discussed."))
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
  related but different product does not count (use the description to tell). The
  dictation's sentences are numbered [1], [2], ... For a discussed topic, "evidence_lines"
  must list the numbers of the sentences where the rep talks about it. If no sentence
  does, the topic is "not_discussed". Never put the numbers in a summary or a field.
- Must-capture fields: fill a field only when the rep states it. Never infer, guess or
  pad; null is the normal answer. Store dimensions like 4x4, keeping the rep's unit if
  given. In Trades, trucks count the way units or properties do in other verticals.
- Commercial outcome (U-04) and service issue (U-07) are categories. Start the value with
  the category, in these words -- U-04: order placed, quote created, quote pending approval
  or return/credit; U-07: backorder, mispick, damage, missing item, ETA request or warranty
  -- then the detail after a colon ("order placed: PO received", "mispick: wrong keypad
  sent"). If no category fits what the rep said, describe it without one.
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
  outcome the rep stated for that campaign, and list the numbers of the sentences that
  state that outcome in outcome_lines. If no code fits, or the rep stated no outcome,
  the code is 99: never pick a code because it sounds close. A topic that was not
  discussed has no code."""


def build_prompt(note: str, planned: list[str], vertical: str,
                 descriptions: dict[str, str] | None = None,
                 dispositions: dict[int, str] | None = None) -> str:
    descriptions = descriptions or {}
    topic_lines = "\n".join(
        f"{i}. label: {_unmark(t)}\n   about: "
        f"{_unmark(descriptions.get(t) or '(no description; judge by the label)')}"
        for i, t in enumerate(planned, 1)
    ) or "(none)"
    # The same units postprocess copies the evidence from, each under its number, run
    # together as one text: one sentence per line made a lone "we spoke on the phone"
    # outweigh the meeting around it (event type 237/258 against 245/258, D-80).
    note = " ".join(f"[{i}] {_unmark(s)}" for i, s in enumerate(sentences(note), 1))
    codes = ""
    if dispositions:
        code_lines = "\n".join(f"  {c}: {_unmark(label)}" for c, label in dispositions.items())
        codes = f"{CODES_RULE}\n\nOutcome codes:\n{code_lines}\n"
    return (f"{RULES}{codes}\nAccount vertical: {vertical}\n\nPlanned topics (the topic field is the label "
            f"only, never the description):\n{topic_lines}\n\nDictation:\n<<<\n{note}\n>>>")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                         "–": "-", "—": "-"}))
    return re.sub(r"\s+", " ", text).strip(" .,;:!?\"'")


def sentences(note: str) -> list[str]:
    """The dictation as the units the model cites by number: each line, split
    where a sentence ends. The prompt numbers these from 1 and ``postprocess``
    copies evidence from the same list, so a number means the same sentence
    on both sides."""
    return [s.strip() for line in (note or "").splitlines()
            for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]


def cited(lines: Any, units: list[str]) -> tuple[list[int], str]:
    """The sentences behind the numbers the model gave: the numbers that are
    sentences of the note (in order, each once; anything else is ignored) and
    their text. Neighbouring sentences are joined by a space, others by
    " ... "."""
    ids = sorted({i for i in lines or [] if type(i) is int and 1 <= i <= len(units)})
    text = ""
    for n, i in enumerate(ids):
        text += ("" if n == 0 else " " if i == ids[n - 1] + 1 else " ... ") + units[i - 1]
    return ids, text


def enough_words(text: str) -> bool:
    """Evidence needs at least MIN_EVIDENCE_WORDS different words that are not
    filler. Known limit, kept: an apostrophe splits a word ("pool's" is two)."""
    return len(set(re.findall(r"\w+", _norm(text or ""))) - _FILLER) >= MIN_EVIDENCE_WORDS


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
    # topics whose code fell back to 99 because the sentences cited for it failed the check
    codes_downgraded: list[str] = field(default_factory=list)
    # what the model gave for each check that failed, by topic: the sentence
    # numbers of its evidence (unconfirmed) or its code and the numbers for it
    # (set to 99). Never in the record; kept so an eval run can show why a
    # check failed. Numbers and codes only, none of the rep's words.
    rejected: dict[str, dict[str, Any]] = field(default_factory=dict)
    # by topic, the numbers the model cited that are not sentences of the note
    # (ignored when the evidence is copied); an eval run counts them
    ignored_lines: dict[str, list[int]] = field(default_factory=dict)


NONE_FITS = 99


def _code_of(topic: dict[str, Any] | None) -> int | None:
    """The code the model gave a topic, as a number; None when it gave none."""
    given = (topic or {}).get("disposition_code")
    return None if given in (None, "") else int(given)


def postprocess(raw: dict[str, Any], note: str, planned: list[str],
                codes: list[int] | None = None) -> ExtractResult:
    """Settle the validated model output into the record (code, not model).
    Evidence is copied from the note's sentences by the numbers the model
    gave (``cited``), never taken as text from the model.
    With ``codes``: a discussed topic keeps a code other than 99 only if it
    is one of ``codes`` and the sentences cited for it pass ``enough_words``,
    otherwise 99; a missing code is 99; a topic that is not discussed has
    none. ``codes`` must include 99, the code every fallback writes."""
    if codes and NONE_FITS not in codes:
        raise ValueError(f"the disposition codes must include {NONE_FITS}, the fallback")
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
    topics, unconfirmed, downgraded, rejected, ignored = [], [], [], {}, {}
    units = sentences(note)
    def given(t, name):      # the numbers as the model gave them; anything that is not a list is no numbers
        value = (t or {}).get(name)
        return list(value) if isinstance(value, (list, tuple)) else []
    for label in planned:
        t = by_label.get(label)
        status = t["status"] if t else NOT_DISCUSSED
        lines, evidence = cited(given(t, "evidence_lines"), units)
        stray = [i for i in given(t, "evidence_lines") + given(t, "outcome_lines")
                 if not (type(i) is int and 1 <= i <= len(units))]
        if stray:
            ignored[label] = stray
        if status == DISCUSSED and not enough_words(evidence):
            status = UNCONFIRMED
            unconfirmed.append(label)
            rejected[label] = {"evidence_lines": given(t, "evidence_lines")}
            if codes:
                rejected[label].update(disposition_code=_code_of(t), outcome_lines=given(t, "outcome_lines"))
        topic = {"topic": label, "status": status,
                 "evidence": evidence if status == DISCUSSED else "",
                 "evidence_lines": lines if status == DISCUSSED else [],
                 # kept for an unconfirmed topic (the rep's question is built from it);
                 # the status marks it unverified
                 "summary": (t or {}).get("summary", "") if status != NOT_DISCUSSED else ""}
        if codes:
            code, outcome_lines, outcome = None, [], ""
            if status == DISCUSSED:
                code = _code_of(t)
                code = NONE_FITS if code is None else code
                outcome_lines, outcome = cited(given(t, "outcome_lines"), units)
                # A code outside the list (the schema refuses it; a direct caller might not),
                # or one whose sentences fail the topic evidence's rule, is not kept.
                if code != NONE_FITS and (code not in codes or not enough_words(outcome)):
                    rejected[label] = {"disposition_code": code, "outcome_lines": given(t, "outcome_lines")}
                    code = NONE_FITS
                    downgraded.append(label)
                if code == NONE_FITS:
                    outcome_lines, outcome = [], ""
            topic.update(disposition_code=code, outcome_evidence=outcome, outcome_lines=outcome_lines)
        topics.append(topic)
    fields = {k.replace("_", "-"): (None if v is None or _norm(v) in NOT_STATED else v)
              for k, v in (raw.get("must_capture") or {}).items()}
    for fid in COUNT_FIELDS:        # a count with no number in it is not a count
        if fields.get(fid) and not _HAS_NUMBER.search(re.sub(r"\s+", " ", fields[fid])):
            fields[fid] = None
    record = {"event_type": raw["event_type"], "executive_summary": raw.get("executive_summary", ""),
              "topics": topics, "must_capture": fields}
    return ExtractResult(record=record, raw=raw, unconfirmed=unconfirmed, off_plan=off_plan,
                         codes_downgraded=downgraded, rejected=rejected, ignored_lines=ignored)


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
        if codes and NONE_FITS not in codes:        # refused before any call: no code to fall back to
            raise ValueError(f"dispositions must include code {NONE_FITS}, the fallback")
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
