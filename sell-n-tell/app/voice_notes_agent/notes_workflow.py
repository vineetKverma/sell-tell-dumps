"""Notes workflow: staging, confirmation, coverage gate, commit -- for one
live call.

Renamed from mock_db.py as part of the contract-simplification pass: once
the fake CRM/persistence framing is gone, what's left is a workflow for a
single dictation session, not a database. This module holds:

- The disposition registry (loaded from resources/dispositions.yaml at
  import time -- static data, not logic).
- The staging/confirmation/coverage-gate/commit workflow that bridges
  stage -> confirm -> commit within ONE session.

What this module does NOT do (see PR: "Contract Simplification & Audit
Logging"):
- No campaign_type / per-campaign disposition registries. One universal
  scheme applies to every call.
- No crm_record_id minting. session_id is already a fresh UUID per commit
  (AIML-2703 guarantees one session = one commit) and is the only
  identifier a caller needs.
- No persistence to a database, JSON file, or any other on-disk store.
  _STAGED_NOTES is in-process, ephemeral call state -- it lives only for
  the duration of one session and is never read back after the process
  restarts. Durable audit logging is handled entirely by ADK's
  BigQueryAgentAnalyticsPlugin attached to the Runner (see main.py); this
  module has no writer of its own.
- No guided-flow support. The guided flow is retired (AIML-2751); agent_mode
  / per-flow branching has been removed from this workflow. The last code is
  recoverable from the tag ``archive/guided-flow``.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml

from .schemas import CommitResult, TopicOutcome

logger = logging.getLogger(__name__)

# Session-state key holding the rep's pre-call planned topics (seeded by
# POST /api/sessions). Read by agent.py and tools.py.
STATE_PLANNED_TOPICS = "planned_topics"

# ---------------------------------------------------------------------------
# Disposition registry, loaded from YAML at import time (static data, not
# logic -- see resources/dispositions.yaml). Replaces the Python-literal
# _FULL_DISPOSITION_REGISTRY / _NOT_COVERED_RULE that used to live here.
# ---------------------------------------------------------------------------

_RESOURCES_DIR = Path(__file__).parent / "resources"
_DISPOSITIONS_PATH = _RESOURCES_DIR / "dispositions.yaml"

_disposition_data: dict[str, Any] = yaml.safe_load(
    _DISPOSITIONS_PATH.read_text(encoding="utf-8")
)
_DISPOSITION_REGISTRY: list[dict[str, Any]] = list(
    _disposition_data["dispositions"]
)
_NOT_COVERED_RULE: dict[str, Any] = _disposition_data["not_covered"]

# DispositionCode.CREATE_OPPORTUNITY == 1, etc. -- built from the YAML so the
# enum and the registry can never drift out of sync with each other.
DispositionCode = IntEnum(
    "DispositionCode",
    {
        rule["name"]: rule["code"]
        for rule in [*_DISPOSITION_REGISTRY, _NOT_COVERED_RULE]
    },
)

_DISPOSITION_BY_CODE: dict[int, dict[str, Any]] = {
    # _NOT_COVERED_RULE is included here even though it is deliberately kept
    # out of _DISPOSITION_REGISTRY: label lookups (disposition_label, used to
    # build the spoken confirmation) must resolve code 99, otherwise the
    # agent reads it back to the rep as "Other".
    int(rule["code"]): rule
    for rule in [*_DISPOSITION_REGISTRY, _NOT_COVERED_RULE]
}

VALID_EVENT_TYPES: list[str] = ["Meeting", "On-site visit", "Phone Call"]
VALID_DISPOSITION_CODES: list[int] = [int(c) for c in DispositionCode]

# ---------------------------------------------------------------------------
# Universal agent config (the GET /config/agent-schema payload, now served
# in-process rather than over its own REST route). Replaces the three
# per-campaign entries that used to live in _CAMPAIGN_CONFIGS -- there is
# now exactly one scheme, so there is nothing to select between and no
# campaign_type parameter anywhere in this module.
#
# NOTE: this system_instruction_template is the former "standard_sales"
# template, chosen as the universal instruction since it was the default
# campaign. Confirm with the team whether this exact wording should carry
# over verbatim as the ONE instruction, or whether it should be revised now
# that it's no longer "the standard campaign" but "the only campaign".
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTION_TEMPLATE = (
    "You are an advanced CRM logging assistant for a field sales rep. "
    "Your goal is to map the user's spoken text to the provided schema "
    "parameters precisely and never invent details that were not said."
)


def get_agent_config() -> dict[str, Any]:
    """Return the single, universal agent config (no campaign_type)."""
    return {
        "system_instruction_template": _SYSTEM_INSTRUCTION_TEMPLATE,
        "allowed_event_types": list(VALID_EVENT_TYPES),
        # Every response gets the "not covered" escape hatch appended, so
        # the agent always has a way to say the outcome isn't representable.
        "disposition_registry": [
            dict(rule) for rule in [*_DISPOSITION_REGISTRY, _NOT_COVERED_RULE]
        ],
    }


def disposition_label(code: int | None) -> str:
    """Human-readable label for a disposition code."""
    if code is None:
        return "no outcome yet"
    try:
        rule = _DISPOSITION_BY_CODE.get(int(code))
    except (ValueError, TypeError):
        return "Other"
    return rule["label"] if rule else "Other"


# ---------------------------------------------------------------------------
# Payload validation (was validate_against_campaign; no campaign_type left
# to validate against, so this checks the payload against the one universal
# scheme instead of a per-campaign subset).
# ---------------------------------------------------------------------------


def validate_payload(payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Check a staged payload against the universal event/disposition rules.

    The universal config is injected into the agent's prompt, but a prompt
    only asks -- it does not constrain. This validates the model's actual
    output against the same rules, so an illegal event type or disposition
    code is rejected instead of being read back to the rep as though valid.

    Returns ``(problems, config)``: human-readable problems (empty when the
    payload is legal), and the config they were checked against (handed back
    so the caller can build its 422 body without re-fetching it).
    """
    config = get_agent_config()
    allowed_events = config["allowed_event_types"]
    allowed_codes = {
        int(rule["code"]) for rule in config["disposition_registry"]
    }
    problems: list[str] = []

    event_type = payload.get("event_type")
    if event_type not in allowed_events:
        problems.append(
            f"event_type {event_type!r} is not allowed; choose one of: "
            f"{', '.join(allowed_events)}"
        )

    for idx, topic in enumerate(payload.get("topics") or []):
        label = (topic.get("topic") or f"topic #{idx + 1}").strip()
        code = topic.get("disposition_code")
        # A planned topic the rep never got to legitimately carries no
        # code. Anything else is a gap.
        #
        # VESTIGIAL: the `needs_manual_review` half of this exemption is
        # effectively dead. It existed for the retired guided flow's
        # "3 failed confirm attempts" path, which set the flag with no code.
        # The surviving flow only reaches needs_manual_review=True via
        # disposition_code=99 (see stage_notes below), which is not None, so
        # the exemption is never the reason a topic passes. Kept rather than
        # removed because dropping it would newly REJECT a payload where the
        # model sets the flag itself -- a behaviour change that belongs with
        # the AIML-2705 flag-shape unification, not here.
        if code is None:
            if topic.get("discussed", True) and not topic.get(
                "needs_manual_review", False
            ):
                problems.append(
                    f"topic {label!r} was discussed but has no "
                    "disposition_code"
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
                f"registry; allowed codes are: {allowed}"
            )

    return problems, config


# ---------------------------------------------------------------------------
# Coverage gate helpers (unchanged logic from mock_db.py).
# ---------------------------------------------------------------------------


def _topic_key(label: str) -> str:
    """A topic label ignoring case and spacing."""
    return " ".join((label or "").split()).casefold()


def compute_missing_topics(
    planned_topics: list[str],
    staged_topics: list[dict[str, Any]],
    allow_skips: bool = True,
) -> list[str]:
    """Return planned topics that have no corresponding entry in the payload.

    A planned topic is considered *covered* once a staged row carries its
    label (ignoring case and spacing). Only its own label counts: the agent
    leaves undiscussed planned topics out and adds off-plan subjects as their
    own rows, so an off-plan row such as "Plumbing leak" must not cover the
    planned "Plumbing" -- the rep would never be asked about it, and it would
    be saved with no outcome.

    ``allow_skips`` decides whether a ``discussed=false`` entry counts as
    coverage. It must be False on the FIRST staging call: the model can
    otherwise mark a topic the rep never mentioned as "not discussed",
    invent a reason for it, and satisfy the coverage check without the rep
    ever being asked. A skip is only trustworthy once the rep has actually
    been asked, which is exactly what a re-stage represents -- so skips
    count only on a correction.
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
        if pk not in covered_keys:
            missing.append(planned)
    return missing


def near_matches(
    missing: list[str], staged_topics: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    """(planned label, staged label) pairs where a missing planned topic and a
    staged row nearly match -- one label contains the other ("MF Pools" for
    "MF Pools 26"). Coverage needs the exact label, so such a row does not
    count; these pairs show how often the model paraphrases a label."""
    staged = [
        (_topic_key(t.get("topic", "")), t.get("topic", ""))
        for t in staged_topics
    ]
    pairs = []
    for planned in missing:
        pk = _topic_key(planned)
        for sk, label in staged:
            if pk and sk and sk != pk and (pk in sk or sk in pk):
                pairs.append((planned, label))
    return pairs


def log_near_matches(
    session_id: str,
    missing: list[str],
    staged_topics: list[dict[str, Any]],
    already_logged: set[tuple[str, str]] = frozenset(),
) -> set[tuple[str, str]]:
    """Log, at INFO, a staged row that nearly matches a planned topic still
    counted as missing -- once per (planned, staged) pair per visit, not on
    every save. A near-match is a candidate, not proof of a paraphrase: a
    real off-plan subject ("Plumbing leak" beside a planned "Plumbing") looks
    the same, so the count is an upper bound on paraphrased labels and each
    hit is also a reminder the rep may not have needed. Returns every pair
    logged so far, for the next save of the same visit."""
    pairs = set(near_matches(missing, staged_topics))
    for planned, label in sorted(pairs - set(already_logged)):
        logger.info(
            "Coverage near-match session_id=%s planned=%r staged=%r -- not "
            "counted as covered (exact label required); the rep will be "
            "reminded about it",
            session_id,
            planned,
            label,
        )
    return pairs | set(already_logged)


# ---------------------------------------------------------------------------
# In-memory, ephemeral call state. NOT a database: this dict lives only for
# the life of the process and is never read back after a restart. Bridges
# stage -> confirm -> commit within one session, and is what the
# idempotent-retry check in commit_notes() reads.
#
# Known gap (unchanged from mock_db.py, tracked separately): this grows for
# the life of the process with nothing to evict a session's entry once the
# WebSocket disconnects -- the same shape as the session-state eviction gap
# flagged in PR #5. The recommended fix is migrating this onto
# tool_context.state (ADK's per-session store), which gets a real
# create/get/delete lifecycle for free. Tracked as follow-up work, not done
# in this pass.
# ---------------------------------------------------------------------------

# session_id (uuid str) -> staged record
_STAGED_NOTES: dict[str, dict[str, Any]] = {}


class IncompleteCoverageError(Exception):
    """Raised when a commit is attempted while planned topics lack an outcome.

    The rep pre-selected topics they intended to cover; committing while any
    of them has no outcome writes a knowingly-incomplete record. The prompt
    already tells the agent not to do this, but prompt rules are not a
    guarantee (see turn_guard), so this is the code-level backstop.
    """

    def __init__(self, missing_topics: list[str]) -> None:
        self.missing_topics = missing_topics
        super().__init__(
            "Planned topics still have no outcome: "
            + ", ".join(missing_topics)
        )


class SupersededRecordError(Exception):
    """Raised when a commit targets a draft that a later correction replaced.

    A correction re-stages under a NEW session_id, so the record being
    corrected stays in _STAGED_NOTES. Without this guard it remains a valid
    commit target holding the exact data the rep just corrected away from --
    and because the idempotency check keys on session_id, committing both
    drafts looks like two unrelated saves for one visit.

    Guarded by tests/test_notes_workflow_gates.py (AIML-2703). Note this
    orphan shape needs DISTINCT session ids, so it is reachable only by a
    caller that is not tools.py -- see that test module's docstring.
    """

    def __init__(self, session_id: str, superseded_by: str) -> None:
        self.session_id = session_id
        self.superseded_by = superseded_by
        super().__init__(
            f"Staged record {session_id} was superseded by {superseded_by}; "
            "commit the corrected record instead."
        )


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


def _article_for(noun: str) -> str:
    return "an" if noun[:1].lower() in "aeiou" else "a"


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
    than offering to save.
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

    # Same label rule as the coverage check, so a spacing difference is not
    # read back as one topic removed and another added.
    old_topics = {_topic_key(t.get("topic") or ""): t for t in old.get("topics", [])}
    planned_keys = {_topic_key(p) for p in planned_topics or []}
    new_keys = set()
    for nt in new.get("topics", []):
        name = (nt.get("topic") or "").strip()
        key = _topic_key(name)
        new_keys.add(key)
        ot = old_topics.get(key)
        if ot is None:
            if nt.get("discussed") is False:
                # The rep's answer to a reminder: skipping it IS the outcome.
                changes.append(f"noted that you didn't get to {name}")
            elif key in planned_keys:
                label = disposition_label(nt.get("disposition_code"))
                changes.append(f"added {name} as {label.lower()}")
            else:
                label = disposition_label(nt.get("disposition_code"))
                changes.append(f"added a new topic, {name}, as {label.lower()}")
            continue
        if nt.get("discussed") is False and ot.get("discussed", True) is not False:
            # A correction to "we didn't get to it": that is the outcome now,
            # not "no outcome yet" -- and it is the whole change (its summary
            # changes with it, so that is not read back separately).
            changes.append(f"noted that you didn't get to {name}")
            continue
        if ot.get("discussed") is False and nt.get("discussed", True) is not False:
            # The reverse correction: "actually we did talk about it". There
            # was no outcome before, so one is added rather than changed.
            label = disposition_label(nt.get("disposition_code"))
            changes.append(f"added an outcome for {name}: {label.lower()}")
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
            f"happened with {plural}? (Say you skipped it and I'll note "
            "that.)"
        )

    if not changes:
        return (
            "I didn't catch a change there. Should I save it as is, or "
            "tell me what to change?"
        )
    return (
        f"Done. I've {_join_natural(changes)}. Should I save this now, or "
        f"change anything else?"
    )


def stage_notes(
    payload: dict[str, Any],
    previous_session_id: str | None = None,
    planned_topics: list[str] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Stage an extracted payload for confirmation; return id + confirmation.

    When ``previous_session_id`` points at an earlier staged record (i.e.
    this is a correction), the confirmation text reads back ONLY what
    changed relative to that record. ``planned_topics`` drives the coverage
    check: any planned topic not yet addressed turns the confirmation into
    a reminder asking the rep for an outcome.

    No campaign_type parameter: one universal scheme applies to every call,
    so there is nothing to record or re-check per campaign.
    """
    session_id = session_id or str(uuid.uuid4())
    planned_topics = planned_topics or []

    # A topic the agent could not map to a real outcome is by definition one
    # a human has to look at. Set the flag here rather than trusting each
    # caller to pair the code with it.
    for topic in payload.get("topics") or []:
        if topic.get("disposition_code") == int(
            DispositionCode.OUTCOME_NOT_COVERED
        ):
            topic["needs_manual_review"] = True

    previous = (
        _STAGED_NOTES.get(previous_session_id) if previous_session_id else None
    )
    # A committed record is not a correction base. It is retained only so
    # commit_notes can answer an idempotent retry -- before that retention it
    # was deleted at commit and this lookup simply missed. Keep that
    # behaviour rather than letting a correction supersede a record that is
    # already committed.
    if previous is not None and previous.get("committed"):
        logger.warning(
            "stage_notes: previous_session_id=%s is already committed -- "
            "staging as a new record rather than a correction.",
            previous_session_id,
        )
        previous = None

    # A "skip" (discussed=false) only counts as coverage once the rep has
    # actually been asked about the topic -- which is what a re-stage means.
    # On the first staging call the model can otherwise skip topics on the
    # rep's behalf and bypass the coverage reminder entirely.
    allow_skips = previous is not None

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
    # Stored as a sorted list of [planned, staged] lists: the record is
    # copied into ADK session state and persisted as JSON, which has no sets
    # or tuples, and comes back that way after a restart (rehydrate_staged).
    already_logged = {
        tuple(pair) for pair in (previous or {}).get("near_matches_logged") or []
    }
    near_match_pairs = log_near_matches(
        session_id, missing, payload.get("topics", []), already_logged
    )
    # A correction re-stages under a brand-new session_id, so the count has
    # to be carried forward from the record it's correcting rather than
    # derived from this one alone.
    correction_count = (
        (previous.get("correction_count", 0) + 1) if previous else 0
    )

    # Retire the record this one corrects. Marked rather than deleted so a
    # commit against it can say what happened and point at the replacement,
    # instead of 404ing as if the session never existed.
    if previous is not None and previous_session_id != session_id:
        previous["superseded_by"] = session_id

    _STAGED_NOTES[session_id] = {
        "payload": dict(payload),
        "planned_topics": list(planned_topics),
        "confirmation_text": confirmation_text,
        "staged_at": datetime.now(timezone.utc).isoformat(),
        "committed": False,
        "correction_count": correction_count,
        # Whether skips were trustworthy for THIS staging, so the commit
        # gate applies the same rule the confirmation text was built from.
        "allow_skips": allow_skips,
        # Near-match pairs already logged for this visit (logged once each).
        "near_matches_logged": sorted(list(pair) for pair in near_match_pairs),
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


def rehydrate_staged(session_id: str, record: dict[str, Any]) -> None:
    """Restore a staged record into _STAGED_NOTES from external/session state.

    Used when resuming an active session across process restarts or reconnects.
    """
    _STAGED_NOTES[session_id] = record
    logger.debug("rehydrate_staged: restored session_id=%s into _STAGED_NOTES", session_id)


def _build_commit_result(
    session_id: str, record: dict[str, Any], closing_statement: str
) -> CommitResult:
    """Build the Output2 payload from a staged record's data.

    Shared by the first-time commit and the idempotent-retry replay branch,
    so both paths return an identical shape -- the retry branch used to
    return a thinner {status, crm_record_id, closing_statement}; this is
    the fix for that.
    """
    payload = record["payload"]
    topics = [
        TopicOutcome(
            topic=t.get("topic", ""),
            executive_summary=t.get("executive_summary", ""),
            disposition_code=t.get("disposition_code"),
            disposition_label=disposition_label(t.get("disposition_code")),
            discussed=t.get("discussed", True),
            needs_manual_review=t.get("needs_manual_review", False),
        )
        for t in payload.get("topics", [])
    ]
    return CommitResult(
        session_id=session_id,
        executive_summary=payload.get("executive_summary", ""),
        planned_topics=list(record.get("planned_topics") or []),
        topics=topics,
        closing_statement=closing_statement,
    )


_CLOSING_STATEMENT = "Saved successfully. Have a great day!"


def commit_notes(session_id: str, confirmed: bool) -> CommitResult | dict[str, str]:
    """Commit a staged payload. Returns Output2 (CommitResult) on success.

    No agent_mode / campaign_type / ws_user_id / ws_session_id parameters:
    those existed only for the guided flow (now retired) and the hand-rolled
    BigQuery sink (now replaced by ADK's BigQueryAgentAnalyticsPlugin, which
    reads session_id/user_id/timestamp natively off the ADK session -- this
    function doesn't need to carry them).

    No crm_record_id: session_id is already a fresh UUID per commit
    (AIML-2703), so it is the one identifier a caller needs.
    """
    record = _STAGED_NOTES.get(session_id)
    if record is None:
        raise KeyError(f"No staged notes found for session_id={session_id}")
    if not confirmed:
        return {
            "status": "cancelled",
            "closing_statement": "No problem, I've discarded this note.",
        }

    if record.get("committed"):
        # Idempotent retry: a retry can still happen at the model level
        # (Gemini Live re-invoking a tool for its own reasons) even though
        # the old HTTP-loopback timeout scenario is gone now that
        # commit_visit_notes calls this function directly in-process.
        # Without this guard a retry would produce a second, distinct
        # Output2 payload -- and a second audit row in BigQuery -- for what
        # is really one commit.
        #
        # Safe above the coverage gate: the gate runs before the record is
        # ever marked committed, so committed=True implies it already
        # passed.
        logger.info(
            "commit_notes: session_id=%s already committed -- returning "
            "the original Output2 instead of creating a duplicate",
            session_id,
        )
        return record["commit_result"]

    # Refuse a superseded draft before any coverage work: this record's data
    # is what the rep explicitly corrected away from, so committing it is
    # wrong regardless of whether its topic coverage happens to be
    # complete.
    superseded_by = record.get("superseded_by")
    if superseded_by:
        logger.warning(
            "Commit BLOCKED for session_id=%s: superseded by %s",
            session_id,
            superseded_by,
        )
        raise SupersededRecordError(session_id, superseded_by)

    planned_topics = record.get("planned_topics") or []
    missing_topics = compute_missing_topics(
        planned_topics,
        record["payload"].get("topics", []),
        allow_skips=record.get("allow_skips", True),
    )
    # Coverage gate: refuse to write a record the system already knows is
    # incomplete. Runs BEFORE the record is marked committed so a blocked
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

    result = _build_commit_result(session_id, record, _CLOSING_STATEMENT)
    # Stored so the idempotent-retry branch above can replay the exact same
    # Output2 object rather than rebuilding it (and so there is only ever
    # one canonical result for this session_id).
    record["commit_result"] = result

    # Deliberately NOT deleted from _STAGED_NOTES. The idempotent-retry
    # branch above needs the record to still be there to answer a retry;
    # deleting here would make that branch dead code again (a genuine
    # retry would find nothing and raise KeyError instead of replaying the
    # original result).
    #
    # This does mean _STAGED_NOTES retains one entry per committed visit
    # for the life of the process -- see the eviction note on _STAGED_NOTES
    # above.
    logger.info(
        "Committed notes session_id=%s",
        session_id,
    )
    return result


def cleanup_session(session_id: str) -> None:
    """Clean up in-memory staged notes for a session on disconnect or completion."""
    _STAGED_NOTES.pop(session_id, None)
    logger.debug("notes_workflow._STAGED_NOTES cleaned up for session_id=%s", session_id)


# Configurable retention TTLs for defense-in-depth in-memory dictionary pruning
VOICE_NOTES_COMMITTED_PRUNE_TTL_SECONDS = float(
    os.getenv("VOICE_NOTES_COMMITTED_PRUNE_TTL_SECONDS", "3600.0")
)
VOICE_NOTES_UNCOMMITTED_PRUNE_TTL_SECONDS = float(
    os.getenv("VOICE_NOTES_UNCOMMITTED_PRUNE_TTL_SECONDS", "7200.0")
)


def prune_stale_staged_notes(
    max_age_seconds: float | None = None,
    committed_max_age_seconds: float | None = None,
    uncommitted_max_age_seconds: float | None = None,
) -> int:
    """Prune stale records from _STAGED_NOTES as a defense-in-depth safety net.

    Configurable via environment variables:
    - VOICE_NOTES_COMMITTED_PRUNE_TTL_SECONDS (default 3600s / 1 hr)
    - VOICE_NOTES_UNCOMMITTED_PRUNE_TTL_SECONDS (default 7200s / 2 hrs)

    - Committed or superseded records older than committed TTL are evicted
      to prevent memory leaks while giving clients a generous window to retry.
    - Active uncommitted records older than uncommitted TTL are evicted as abandoned.

    Returns the count of evicted records.
    """
    if max_age_seconds is not None:
        c_ttl = max_age_seconds
        u_ttl = max_age_seconds * 2
    else:
        c_ttl = (
            committed_max_age_seconds
            if committed_max_age_seconds is not None
            else VOICE_NOTES_COMMITTED_PRUNE_TTL_SECONDS
        )
        u_ttl = (
            uncommitted_max_age_seconds
            if uncommitted_max_age_seconds is not None
            else VOICE_NOTES_UNCOMMITTED_PRUNE_TTL_SECONDS
        )

    now = datetime.now(timezone.utc)
    to_delete = []
    for sid, rec in list(_STAGED_NOTES.items()):
        ts_str = rec.get("committed_at") or rec.get("staged_at")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            age = (now - ts).total_seconds()
        except (ValueError, TypeError):
            continue

        if rec.get("committed") or rec.get("superseded_by"):
            if age > c_ttl:
                to_delete.append(sid)
        elif age > u_ttl:
            to_delete.append(sid)

    for sid in to_delete:
        _STAGED_NOTES.pop(sid, None)
    if to_delete:
        logger.info("prune_stale_staged_notes evicted %d records", len(to_delete))
    return len(to_delete)
