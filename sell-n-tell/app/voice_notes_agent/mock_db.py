
"""Mock configuration database and CRM store for the Voice Notes Logger.

This module simulates two external systems referenced by the API spec:

1. A *dynamic config registry* (the source the backend pulls from at session
   init to inject system instructions, allowed event types, and the disposition
   rule registry into the Gemini agent based on ``campaign_type``).
2. A *CRM / BigQuery sink* where staged payloads live until the user confirms,
   then get "committed".

Everything here is in-memory and deterministic so the app runs with no external
dependencies.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DispositionCode(IntEnum):
    """The fixed set of disposition (outcome) codes a topic can be mapped to.

    These are the ONLY valid dispositions; using an ``IntEnum`` lets pydantic
    reject any code outside this list at the schema level (so the agent can
    only ever assign a disposition that exists in the registry).
    """

    CREATE_OPPORTUNITY = 1
    ORDER_PLACED = 2
    NO_CURRENT_NEED = 3
    CONTRACTED_TO_COMPETITOR = 4
    PREFERRED_VENDOR_ALREADY = 5
    NOT_A_PRODUCT_THEY_USE = 6
    FAILS_BRAND_GUIDELINES = 7
    PRICING_CONCERNS = 8
    RECENTLY_DISCUSSED = 9
    RECENTLY_PURCHASED_RELATED = 10
    # Escape hatch, available in EVERY campaign. Without an explicit "none of
    # these" option the model has no way to express that the registry does not
    # cover what happened -- filling a structured field is an argmax over the
    # allowed values, so it always returns a "best" code even when the best is
    # wrong. Measured: a renewals call where the customer asked for a quote
    # (no matching code exists) returned 2 "Order Placed" or 3 "No current
    # need" at random across six runs -- opposite meanings, both false. Making
    # "not covered" an ordinary peer option lets the model select it normally
    # instead of having to volunteer an exception against the grain.
    OUTCOME_NOT_COVERED = 99


class DiscussionTopic(BaseModel):
    """A single call topic within one visit, with its own disposition.

    A visit can cover several distinct call topics (e.g. pricing, then a
    renewal), and each one gets its own disposition + summary.

    Topics line up with the rep's *pre-call planned topics* (see
    ``PLANNED_TOPIC_CATALOG``). Every planned topic should end up here:
    - If it was actually discussed, ``discussed`` is True and
      ``disposition_code`` carries the mapped outcome (one of the fixed
      ``DispositionCode`` values).
    - If the rep confirmed they did not get to it, ``discussed`` is False and
      ``disposition_code`` may be omitted; ``executive_summary`` then holds the
      rep's feedback on why (e.g. "ran out of time, will cover next visit").
    """

    topic: str = Field(
        ..., description="Short label / subject of this call topic"
    )
    disposition_code: DispositionCode | None = Field(
        default=None,
        description=(
            "Disposition outcome for THIS topic, chosen from the fixed "
            "disposition registry (DispositionCode). Required when the topic "
            "was discussed; null for a planned-but-not-discussed topic."
        ),
    )
    executive_summary: str = Field(
        default="",
        description=(
            "Condensed 1-2 sentence summary of THIS topic. Leave empty rather "
            "than inventing one -- a topic the rep skipped without giving a "
            "reason has nothing to summarize, and a required field here forces "
            "the model to confabulate (observed live: 'Rep did not get to "
            "pricing due to time constraints' when the rep never said so)."
        ),
    )
    discussed: bool = Field(
        default=True,
        description=(
            "Whether this planned topic was actually covered in the dictation. "
            "False means the rep planned it but did not get to it."
        ),
    )
    needs_manual_review: bool = Field(
        default=False,
        description=(
            "Guided flow only: true if 3 disposition-confirm attempts failed "
            "and the code had to be left unresolved for a human to fix."
        ),
    )

# ---------------------------------------------------------------------------
# Disposition registry (the 10 fixed outcome codes). These are the disposition
# codes a *call topic* can be mapped to. Each rule carries mapping_keywords the
# LLM uses to map spoken language to a code. Codes mirror ``DispositionCode``.
# ---------------------------------------------------------------------------

_FULL_DISPOSITION_REGISTRY: list[dict[str, Any]] = [
    {
        "code": DispositionCode.CREATE_OPPORTUNITY,
        "label": "Create Opportunity",
        "mapping_keywords": [
            "interested",
            "wants to buy",
            "ready to purchase",
            "send a quote",
            "create an opportunity",
            "new opportunity",
        ],
    },
    {
        "code": DispositionCode.ORDER_PLACED,
        "label": "Order Placed",
        "mapping_keywords": [
            "placed an order",
            "ordered",
            "order confirmed",
            "purchase made",
            "bought",
            "closed the sale",
        ],
    },
    {
        "code": DispositionCode.NO_CURRENT_NEED,
        "label": "No current need - revisit in the future",
        "mapping_keywords": [
            "no need",
            "not right now",
            "revisit later",
            "check back",
            "future",
            "no current need",
        ],
    },
    {
        "code": DispositionCode.CONTRACTED_TO_COMPETITOR,
        "label": "Contracted to buy from competitor",
        "mapping_keywords": [
            "contracted with competitor",
            "locked in with a competitor",
            "signed with another vendor",
            "under contract elsewhere",
        ],
    },
    {
        "code": DispositionCode.PREFERRED_VENDOR_ALREADY,
        "label": "Buying from preferred vendor already",
        "mapping_keywords": [
            "preferred vendor",
            "already buying from",
            "existing supplier",
            "loyal to current vendor",
            "happy with current supplier",
        ],
    },
    {
        "code": DispositionCode.NOT_A_PRODUCT_THEY_USE,
        "label": "Not a product or service they use/need",
        "mapping_keywords": [
            "don't use this",
            "not relevant",
            "no use for it",
            "not applicable",
            "not something they need",
        ],
    },
    {
        "code": DispositionCode.FAILS_BRAND_GUIDELINES,
        "label": "Does not meet brand/property guidelines",
        "mapping_keywords": [
            "brand guidelines",
            "property guidelines",
            "not approved",
            "not on brand",
            "compliance",
            "not compliant",
        ],
    },
    {
        "code": DispositionCode.PRICING_CONCERNS,
        "label": "Pricing concerns",
        "mapping_keywords": [
            "expensive",
            "cost too much",
            "pricing high",
            "too pricey",
            "budget issue",
            "price is a concern",
        ],
    },
    {
        "code": DispositionCode.RECENTLY_DISCUSSED,
        "label": "Recently discussed",
        "mapping_keywords": [
            "already discussed",
            "talked recently",
            "covered last time",
            "recent conversation",
            "discussed before",
        ],
    },
    {
        "code": DispositionCode.RECENTLY_PURCHASED_RELATED,
        "label": "Customer recently purchased related item(s)",
        "mapping_keywords": [
            "recently purchased",
            "just bought",
            "already purchased related",
            "bought a related item",
            "recent purchase",
        ],
    },
]

# Appended to EVERY campaign's registry by get_agent_config -- see the
# OUTCOME_NOT_COVERED note on DispositionCode. Kept out of
# _FULL_DISPOSITION_REGISTRY so campaign subsets stay a clean list of real
# business outcomes and this is added deliberately in one place.
_NOT_COVERED_RULE: dict[str, Any] = {
    "code": DispositionCode.OUTCOME_NOT_COVERED,
    # Kept short: the agent reads this label aloud in the confirmation.
    "label": "Outcome not covered - needs manual review",
    "mapping_keywords": [
        "none of the other codes describe what happened",
        "the real outcome is not in this list",
        "would have to force a code that misstates the call",
    ],
}

_DISPOSITION_BY_CODE: dict[int, dict[str, Any]] = {
    # _NOT_COVERED_RULE is included here even though it is deliberately absent
    # from _FULL_DISPOSITION_REGISTRY: label lookups (disposition_label, used
    # to build the spoken confirmation) must resolve code 99, otherwise the
    # agent reads it back to the rep as "Other".
    int(rule["code"]): rule
    for rule in [*_FULL_DISPOSITION_REGISTRY, _NOT_COVERED_RULE]
}


# ---------------------------------------------------------------------------
# Pre-call planned-topic catalog (the SUBJECTS a rep plans to bring up).
#
# These are distinct from disposition codes: a topic is *what* gets discussed
# (e.g. "Contract renewal"), and the disposition (DispositionCode) is the
# *outcome* of discussing it (e.g. "Pricing concerns"). Before a call the rep
# multi-selects which of these topics they intend to cover; the selection is
# seeded into session state and the agent must extract a disposition for EACH
# selected topic, reminding the rep about any topic that was never mentioned.
# ---------------------------------------------------------------------------

# Product category titles, per the business (Jeremy Daniell, 2026-08-07):
# reps plan a call around the categories they intend to sell into.
#
# Note from the real-notes sample (1000 rows, see
# docs/far-notes-dataset-analysis.md): only Appliances, HVAC, Pool and Plumbing
# appear with real frequency in post-visit notes; Ceiling Fans never appears,
# and 67% of notes mention no category at all. Coverage reminders will
# therefore be the common path rather than the exception.
PLANNED_TOPIC_CATALOG: list[dict[str, str]] = [
    {"id": "appliances", "label": "Appliances"},
    {"id": "cleaning_janitorial", "label": "Cleaning & Janitorial"},
    {"id": "electrical", "label": "Electrical"},
    {"id": "hardware", "label": "Hardware"},
    {"id": "hvac", "label": "HVAC"},
    {"id": "lighting_ceiling_fans", "label": "Lighting & Ceiling Fans"},
    {"id": "linens_towels", "label": "Linens & Towels"},
    {"id": "office_supplies", "label": "Office Supplies"},
    {"id": "paint_supplies", "label": "Paint & Supplies"},
    {"id": "plumbing", "label": "Plumbing"},
    {"id": "pool_supplies", "label": "Pool Supplies"},
    {"id": "storage", "label": "Storage"},
    {"id": "tools", "label": "Tools"},
]


def get_planned_topic_catalog() -> list[dict[str, str]]:
    """Return the selectable pre-call planned-topic catalog (copy)."""
    return [dict(t) for t in PLANNED_TOPIC_CATALOG]


def _topic_key(label: str) -> str:
    """Normalize a topic label for tolerant matching."""
    return (label or "").strip().lower()


def compute_missing_topics(
    planned_topics: list[str],
    staged_topics: list[dict[str, Any]],
    allow_skips: bool = True,
) -> list[str]:
    """Return planned topics that have no corresponding entry in the payload.

    A planned topic is considered *covered* once it appears in the staged
    ``topics`` list. Matching is tolerant of case/whitespace and falls back to
    substring overlap so the model doesn't have to reproduce the catalog label
    verbatim.

    ``allow_skips`` decides whether a ``discussed=false`` entry counts as
    coverage. It must be False on the FIRST staging call: the model can
    otherwise mark a topic the rep never mentioned as "not discussed", invent a
    reason for it, and satisfy the coverage check without the rep ever being
    asked (observed live: a topic came back as "Rep did not get to pricing due
    to time constraints" when the rep said nothing of the kind). A skip is only
    trustworthy once the rep has actually been asked, which is exactly what a
    re-stage represents -- so skips count only on a correction.
    """
    covered_keys = {
        _topic_key(t.get("topic", ""))
        for t in staged_topics
        if allow_skips or t.get("discussed", True)
    }
    missing: list[str] = []
    for planned in planned_topics:
        pk = _topic_key(planned)
        if not pk:
            continue
        hit = pk in covered_keys or any(
            pk in ck or ck in pk for ck in covered_keys if ck
        )
        if not hit:
            missing.append(planned)
    return missing


def _registry_subset(codes: list[int]) -> list[dict[str, Any]]:
    """Return disposition rules restricted to the given codes (preserve order)."""
    return [
        _DISPOSITION_BY_CODE[c] for c in codes if c in _DISPOSITION_BY_CODE
    ]


# ---------------------------------------------------------------------------
# Campaign config registry. Each campaign_type yields a different system
# instruction, allowed event types, and disposition subset -- demonstrating
# dynamic schema fetching (Step 1 of the spec).
# ---------------------------------------------------------------------------

_CAMPAIGN_CONFIGS: dict[str, dict[str, Any]] = {
    "standard_sales": {
        "system_instruction_template": (
            "You are an advanced CRM logging assistant for a field sales rep. "
            "Your goal is to map the user's spoken text to the provided schema "
            "parameters precisely and never invent details that were not said."
        ),
        "allowed_event_types": ["Meeting", "On-site visit", "Phone Call"],
        "disposition_registry": _FULL_DISPOSITION_REGISTRY,
    },
    "enterprise_field": {
        "system_instruction_template": (
            "You are an enterprise field-sales CRM logging assistant. Reps log "
            "high-value, in-person interactions. Map spoken notes to the schema "
            "with extra care on the executive summary, capturing stakeholder "
            "names and next steps when mentioned."
        ),
        # Enterprise reps only log in-person touchpoints.
        "allowed_event_types": ["Meeting", "On-site visit"],
        # Enterprise campaign cares about a focused set of outcomes.
        "disposition_registry": _registry_subset([1, 2, 4, 5, 8]),
    },
    "renewals": {
        "system_instruction_template": (
            "You are a renewals-desk CRM logging assistant. The rep is calling "
            "existing customers about contract renewals. Prioritize accurate "
            "disposition mapping around pricing, competition, and prior "
            "purchases."
        ),
        "allowed_event_types": ["Phone Call", "Meeting"],
        "disposition_registry": _registry_subset([2, 3, 5, 8, 9]),
    },
}

_DEFAULT_CAMPAIGN = "standard_sales"

VALID_EVENT_TYPES = ["Meeting", "On-site visit", "Phone Call"]
VALID_DISPOSITION_CODES = [int(c) for c in DispositionCode]


# ---------------------------------------------------------------------------
# In-memory data stores for staged + committed records.
# ---------------------------------------------------------------------------

# session_id (uuid str) -> staged record
_STAGED_NOTES: dict[str, dict[str, Any]] = {}
# committed records (acts as the mock CRM / BigQuery table)
_COMMITTED_NOTES: list[dict[str, Any]] = []


def get_agent_config(campaign_type: str | None) -> dict[str, Any]:
    """Return the dynamic agent config for a campaign (the GET /config payload)."""
    key = campaign_type or _DEFAULT_CAMPAIGN
    config = _CAMPAIGN_CONFIGS.get(key)
    if config is None:
        logger.warning(
            "Unknown campaign_type=%r, falling back to %r",
            campaign_type,
            _DEFAULT_CAMPAIGN,
        )
        config = _CAMPAIGN_CONFIGS[_DEFAULT_CAMPAIGN]
    # Return a copy so callers can't mutate the registry in place.
    return {
        "campaign_type": key if key in _CAMPAIGN_CONFIGS else _DEFAULT_CAMPAIGN,
        "system_instruction_template": config["system_instruction_template"],
        "allowed_event_types": list(config["allowed_event_types"]),
        # Every campaign gets the "not covered" escape hatch appended, so a
        # narrowed registry can never leave the agent with no way to say the
        # outcome isn't representable.
        "disposition_registry": [
            dict(rule)
            for rule in [*config["disposition_registry"], _NOT_COVERED_RULE]
        ],
    }


class IncompleteCoverageError(Exception):
    """Raised when a commit is attempted while planned topics lack an outcome.

    The rep pre-selected topics they intended to cover; committing while any of
    them has no outcome writes a knowingly-incomplete record to the CRM. The
    prompt already tells the agent not to do this, but prompt rules are not a
    guarantee (see turn_guard), so this is the code-level backstop.
    """

    def __init__(self, missing_topics: list[str]) -> None:
        self.missing_topics = missing_topics
        super().__init__(
            "Planned topics still have no outcome: "
            + ", ".join(missing_topics)
        )


def validate_against_campaign(
    payload: dict[str, Any], campaign_type: str | None
) -> list[str]:
    """Check a staged payload against *this campaign's* rules.

    The campaign config is injected into the agent's prompt, but a prompt only
    asks -- it does not constrain. This validates the model's actual output
    against the same config, so a campaign-illegal event type or disposition
    code is rejected instead of being read back to the rep as though it were
    valid.

    Returns a list of human-readable problems (empty when the payload is legal).
    """
    config = get_agent_config(campaign_type)
    allowed_events = config["allowed_event_types"]
    allowed_codes = {
        int(rule["code"]) for rule in config["disposition_registry"]
    }
    campaign = config["campaign_type"]
    problems: list[str] = []

    event_type = payload.get("event_type")
    if event_type not in allowed_events:
        problems.append(
            f"event_type {event_type!r} is not allowed for the {campaign!r} "
            f"campaign; choose one of: {', '.join(allowed_events)}"
        )

    for idx, topic in enumerate(payload.get("topics") or []):
        label = (topic.get("topic") or f"topic #{idx + 1}").strip()
        code = topic.get("disposition_code")
        # Two cases legitimately carry no code: a planned topic the rep never
        # got to, and a discussed topic the guided flow could not resolve after
        # its confirm attempts (flagged for a human instead of guessing -- see
        # tools_guided.record_topic_disposition). Anything else is a gap.
        if code is None:
            if topic.get("discussed", True) and not topic.get(
                "needs_manual_review", False
            ):
                problems.append(
                    f"topic {label!r} was discussed but has no disposition_code"
                )
            continue
        try:
            code = int(code)
        except (ValueError, TypeError):
            problems.append(
                f"topic {label!r} has a non-numeric disposition_code {code!r}"
            )
            continue
        if code not in allowed_codes:
            allowed = ", ".join(str(c) for c in sorted(allowed_codes))
            problems.append(
                f"disposition_code {code} on topic {label!r} is not in the "
                f"{campaign!r} registry; allowed codes are: {allowed}"
            )

    return problems


def disposition_label(code: int | None) -> str:
    """Human-readable label for a disposition code."""
    if code is None:
        return "no outcome yet"
    try:
        rule = _DISPOSITION_BY_CODE.get(int(code))
    except (ValueError, TypeError):
        return "Other"
    return rule["label"] if rule else "Other"


def _join_natural(items: list[str]) -> str:
    """Join a list into natural English: 'a', 'a and b', 'a, b, and c'."""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def build_confirmation_text(
    payload: dict[str, Any],
    planned_topics: list[str] | None = None,
    allow_skips: bool = True,
) -> str:
    """Compose the full implicit-confirmation string from staged JSON values.

    Reads back the overall call summary plus each topic's disposition so the
    rep hears what was captured before saving. When ``planned_topics`` are
    supplied and one or more of them were never addressed, the text instead
    *reminds* the rep about the gaps and asks for an outcome on each, rather
    than offering to save (requirement: collect feedback for missing topics).
    """
    event_type = payload["event_type"]
    article = _article_for(event_type)
    topics = payload.get("topics") or []
    overall = (payload.get("executive_summary") or "").strip()
    summary_clause = f"Here's my summary: {overall} " if overall else ""

    missing = compute_missing_topics(
        planned_topics or [], topics, allow_skips=allow_skips
    )

    if topics:
        topic_parts = [
            f"{(t.get('topic') or 'a topic').strip()} marked as "
            f"{disposition_label(t.get('disposition_code')).lower()}"
            for t in topics
            if t.get("discussed", True)
        ]
        captured_clause = (
            f"I've staged {article} {event_type} covering "
            f"{_join_natural(topic_parts)}. "
            if topic_parts
            else f"I've staged {article} {event_type}. "
        )
    else:
        captured_clause = f"I've staged {article} {event_type}. "

    if missing:
        gap_text = _join_natural(missing)
        plural = "those topics" if len(missing) > 1 else "that topic"
        return (
            f"Got it. {summary_clause}{captured_clause}"
            f"Before I save, you'd planned to cover {gap_text}, but I didn't "
            f"hear an outcome on {plural}. What happened with {gap_text}? "
            f"(If you didn't get to it, just say so and I'll note it.)"
        )

    return (
        f"Got it. {summary_clause}{captured_clause}"
        f"Should I save this, or do you want to change something?"
    )


def build_change_confirmation(
    old: dict[str, Any],
    new: dict[str, Any],
    planned_topics: list[str] | None = None,
) -> str:
    """Compose a confirmation that reads back ONLY what changed vs ``old``."""
    changes: list[str] = []

    if old.get("event_type") != new.get("event_type"):
        changes.append(f"changed the event type to {new['event_type']}")

    if (old.get("executive_summary") or "").strip() != (
        new.get("executive_summary") or ""
    ).strip():
        changes.append("updated the call summary")

    old_topics = {
        (t.get("topic") or "").strip().lower(): t
        for t in old.get("topics", [])
    }
    new_keys = set()
    for nt in new.get("topics", []):
        name = (nt.get("topic") or "").strip()
        key = name.lower()
        new_keys.add(key)
        ot = old_topics.get(key)
        if ot is None:
            label = disposition_label(nt.get("disposition_code"))
            changes.append(f"added a new topic, {name}, as {label.lower()}")
            continue
        if ot.get("disposition_code") != nt.get("disposition_code"):
            label = disposition_label(nt.get("disposition_code"))
            changes.append(f"changed the {name} outcome to {label.lower()}")
        if (ot.get("executive_summary") or "").strip() != (
            nt.get("executive_summary") or ""
        ).strip():
            changes.append(f"updated the summary for {name}")

    for key, ot in old_topics.items():
        if key not in new_keys:
            changes.append(f"removed the {ot.get('topic')} topic")

    # If planned topics are still uncovered after this change, keep nudging
    # rather than offering to save.
    missing = compute_missing_topics(
        planned_topics or [], new.get("topics", [])
    )
    if missing:
        gap_text = _join_natural(missing)
        change_clause = (
            f"Done. I've {_join_natural(changes)}. " if changes else ""
        )
        plural = "those topics" if len(missing) > 1 else "that topic"
        return (
            f"{change_clause}I still need an outcome on {gap_text}. What "
            f"happened with {plural}? (Say you skipped it and I'll note that.)"
        )

    if not changes:
        return (
            "I didn't catch a change there. Should I save it as is, or tell me "
            "what to change?"
        )
    return (
        f"Done. I've {_join_natural(changes)}. Should I save this now, or "
        f"change anything else?"
    )


def _article_for(noun: str) -> str:
    return "an" if noun[:1].lower() in "aeiou" else "a"


def stage_notes(
    payload: dict[str, Any],
    previous_session_id: str | None = None,
    planned_topics: list[str] | None = None,
    campaign_type: str | None = None,
    agent_mode: str = "implicit",
) -> dict[str, Any]:
    """Stage an extracted payload for confirmation; return id + confirmation.

    Implements POST /api/v1/notes/stage. When ``previous_session_id`` points at
    an earlier staged record (i.e. this is a correction), the confirmation text
    reads back ONLY what changed relative to that record. ``planned_topics``
    drives the coverage check: any planned topic not yet addressed turns the
    confirmation into a reminder asking the rep for an outcome.
    """
    session_id = str(uuid.uuid4())
    planned_topics = planned_topics or []

    # A topic the agent could not map to a real outcome is by definition one a
    # human has to look at. Set the flag here rather than trusting each caller
    # to pair the code with it, so implicit, guided and plain REST all agree.
    for topic in payload.get("topics") or []:
        if topic.get("disposition_code") == int(
            DispositionCode.OUTCOME_NOT_COVERED
        ):
            topic["needs_manual_review"] = True
    previous = (
        _STAGED_NOTES.get(previous_session_id) if previous_session_id else None
    )
    # A "skip" (discussed=false) only counts as coverage once the rep has
    # actually been asked about the topic -- which is what a re-stage means.
    # On the first staging call the model can otherwise skip topics on the
    # rep's behalf and bypass the coverage reminder entirely.
    #
    # Guided is exempt. There, a discussed=false entry can ONLY be produced by
    # record_topic_disposition, which is gated by turn_guard.has_new_reply --
    # so the rep provably answered the outcome question for that topic before
    # the skip was recorded. The provenance the re-stage rule infers is already
    # guaranteed at the tool level. Without this exemption guided deadlocks:
    # it asks about the topic, the rep says they skipped it, and the first (and
    # only) staging call then reports that same topic as uncovered, so the
    # commit 409s and the agent asks again. Observed live 2026-08-11.
    allow_skips = previous is not None or agent_mode == "guided"
    if previous:
        confirmation_text = build_change_confirmation(
            previous["payload"], payload, planned_topics
        )
    else:
        confirmation_text = build_confirmation_text(
            payload, planned_topics, allow_skips=allow_skips
        )

    missing = compute_missing_topics(
        planned_topics, payload.get("topics", []), allow_skips=allow_skips
    )
    # A correction re-stages under a brand-new session_id, so the count has to
    # be carried forward from the record it's correcting rather than derived
    # from this one alone.
    correction_count = (previous.get("correction_count", 0) + 1) if previous else 0
    _STAGED_NOTES[session_id] = {
        "payload": dict(payload),
        "planned_topics": list(planned_topics),
        "confirmation_text": confirmation_text,
        "staged_at": datetime.now(timezone.utc).isoformat(),
        "committed": False,
        "correction_count": correction_count,
        # Recorded at stage time so the commit gate re-checks coverage against
        # the campaign this record was actually staged under, rather than
        # trusting whatever the commit caller claims.
        "campaign_type": campaign_type,
        # Whether skips were trustworthy for THIS staging, so the commit gate
        # applies the same rule the confirmation text was built from.
        "allow_skips": allow_skips,
    }
    logger.info(
        "Staged notes session_id=%s event_type=%s topics=%d missing=%d "
        "(correction=%s, correction_count=%d)",
        session_id,
        payload.get("event_type"),
        len(payload.get("topics") or []),
        len(missing),
        bool(previous),
        correction_count,
    )
    return {
        "session_id": session_id,
        "confirmation_text": confirmation_text,
        "missing_topics": missing,
        "all_topics_covered": not missing,
    }


def get_staged(session_id: str) -> dict[str, Any] | None:
    """Return a staged record (or None)."""
    return _STAGED_NOTES.get(session_id)


def commit_notes(
    session_id: str,
    confirmed: bool,
    agent_mode: str = "implicit",
    campaign_type: str | None = None,
    ws_user_id: str | None = None,
    ws_session_id: str | None = None,
) -> dict[str, Any]:
    """Commit a staged payload to the mock CRM. Implements POST /notes/commit.

    ``agent_mode``/``campaign_type``/``ws_user_id``/``ws_session_id`` are pure
    metadata the REST spec never required, but which the BigQuery sink needs
    to know which table to write to and how to correlate a row back to the
    actual conversation. They default so existing callers keep working.
    """
    record = _STAGED_NOTES.get(session_id)
    if record is None:
        raise KeyError(f"No staged notes found for session_id={session_id}")
    if not confirmed:
        return {
            "status": "cancelled",
            "closing_statement": "No problem, I've discarded this note.",
        }

    planned_topics = record.get("planned_topics") or []
    missing_topics = compute_missing_topics(
        planned_topics,
        record["payload"].get("topics", []),
        allow_skips=record.get("allow_skips", True),
    )
    # Coverage gate: refuse to write a record the system already knows is
    # incomplete. This runs BEFORE the record is marked committed so a blocked
    # attempt leaves the staged record re-usable -- the agent collects the
    # missing outcomes and re-stages.
    if missing_topics:
        logger.warning(
            "Commit BLOCKED for session_id=%s: planned topics without an "
            "outcome: %s",
            session_id,
            missing_topics,
        )
        raise IncompleteCoverageError(missing_topics)

    record["committed"] = True
    record["committed_at"] = datetime.now(timezone.utc).isoformat()
    crm_record_id = f"CRM-{uuid.uuid4().hex[:10].upper()}"
    committed = {
        "crm_record_id": crm_record_id,
        "staged_session_id": session_id,
        "ws_user_id": ws_user_id,
        "ws_session_id": ws_session_id,
        "agent_mode": agent_mode,
        "campaign_type": campaign_type,
        **record["payload"],
        "planned_topics": planned_topics,
        "missing_topics": missing_topics,
        "correction_count": record.get("correction_count", 0),
        "staged_at": record.get("staged_at"),
        "committed_at": record["committed_at"],
    }
    _COMMITTED_NOTES.append(committed)
    logger.info(
        "Committed notes session_id=%s crm_record_id=%s agent_mode=%s",
        session_id,
        crm_record_id,
        agent_mode,
    )
    return {
        "status": "success",
        "crm_record_id": crm_record_id,
        "closing_statement": "Saved successfully. Have a great day!",
        # Consumed by the /notes/commit endpoint to feed the BigQuery sink;
        # stripped before building the REST response model.
        "_record": committed,
    }


def list_committed() -> list[dict[str, Any]]:
    """Return all committed records (the mock CRM table contents)."""
    return list(_COMMITTED_NOTES)
