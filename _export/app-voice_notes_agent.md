# app/voice_notes_agent

branch: `feature/AIML-2751-remove-guided`  commit: `6ffd86f`  files: 9

<!-- FILE: app/voice_notes_agent/__init__.py -->
````python
"""Voice Notes Logger agent package."""

from .agent import agent

__all__ = ["agent"]
````
<!-- END: app/voice_notes_agent/__init__.py -->

<!-- FILE: app/voice_notes_agent/agent.py -->
````python
"""Voice Notes Logger agent (implicit flow only -- guided flow retired).

Per the contract-simplification pass, the agent config is no longer dynamic
per-campaign, so there is no before_agent_callback fetching it over HTTP at
session start: notes_workflow.get_agent_config() returns the single,
universal config (system instruction, allowed event types, disposition
registry) directly, in-process. A dynamic instruction provider still
assembles the final system prompt per request, but only to merge in the
rep's ``planned_topics`` (which vary per session) -- the config portion is
the same for every call.

Determinism is enforced via generate_content_config (temperature 0.1,
top_p 0.8), and the model is steered to emit a single "Mega-Payload" function
call rather than freeform text.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.genai import types

from . import notes_workflow
from .tools import commit_visit_notes, stage_visit_notes

logger = logging.getLogger(__name__)

# Seeded at session creation from the rep's pre-call topic selection. This is
# the only per-session state this module still reads -- campaign_type and
# agent_config are gone along with the campaign machinery they served.
STATE_PLANNED_TOPICS = "planned_topics"

# ---------------------------------------------------------------------------
# Behavioral instruction template (the fixed conversational flow), loaded
# once at import time from its own file. Previously a 143-line Python string
# constant inline in this module -- moved to YAML per the contract-
# simplification pass since it's static prompt text, not logic.
# ---------------------------------------------------------------------------

_RESOURCES_DIR = Path(__file__).parent / "resources"
_BEHAVIORAL_RULES_PATH = _RESOURCES_DIR / "behavioral_rules.yaml"
_BEHAVIORAL_RULES: str = yaml.safe_load(
    _BEHAVIORAL_RULES_PATH.read_text(encoding="utf-8")
)["behavioral_rules"]

# The universal agent config never varies per session anymore (no
# campaign_type to select between), so it's fetched once at import time
# instead of per-session via a before_agent_callback + HTTP round trip.
_AGENT_CONFIG: dict = notes_workflow.get_agent_config()


def _format_config_block(config: dict) -> str:
    "Render the (now static, universal) agent config into the system prompt."
    allowed = ", ".join(config.get("allowed_event_types", []))
    registry_lines = []
    for rule in config.get("disposition_registry", []):
        kws = ", ".join(rule.get("mapping_keywords", []))
        registry_lines.append(
            f"  - {rule['code']}: {rule['label']} "
            f"(keywords: {kws})"
        )
    registry_block = "\n".join(registry_lines)
    return (
        f"{config.get('system_instruction_template', '')}\n\n"
        f"# Allowed event types\n{allowed}\n\n"
        f"# Disposition registry (code: label)\n{registry_block}\n"
    )


def _format_planned_topics_block(planned_topics: list[str]) -> str:
    "Render the rep's pre-call planned topics into the system prompt."
    if not planned_topics:
        return (
            "# Planned topics\n"
            "The rep did not pre-select any planned topics. Capture whatever "
            "they discuss as topics and skip the coverage reminder.\n"
        )
    lines = "\n".join(f"  - {t}" for t in planned_topics)
    return (
        "# Planned topics\n"
        "The rep planned to discuss the following topics on this call. Extract "
        "a disposition for EACH one, use these EXACT labels for the topic "
        "field, and pass this full list as planned_topics on every "
        f"stage_visit_notes call:\n{lines}\n"
    )


def voice_notes_instruction(ctx: ReadonlyContext) -> str:
    "Assemble the full system instruction: fixed rules + planned topics + config."
    planned_topics = ctx.state.get(STATE_PLANNED_TOPICS) or []
    return (
        f"{_BEHAVIORAL_RULES}\n\n"
        f"{_format_planned_topics_block(planned_topics)}\n"
        f"{_format_config_block(_AGENT_CONFIG)}"
    )


# Deterministic generation config: temperature 0.1, top_p 0.8.
_GENERATION_CONFIG = types.GenerateContentConfig(
    temperature=0.1,
    top_p=0.8,
)

agent = Agent(
    name="voice_notes_logger",
    model=os.getenv(
        "VOICE_NOTES_AGENT_MODEL", "gemini-live-2.5-flash-native-audio"
    ),
    instruction=voice_notes_instruction,
    tools=[stage_visit_notes, commit_visit_notes],
    generate_content_config=_GENERATION_CONFIG,
)

# Required by adk web -- the CLI discovers agents via this name.
root_agent = agent
````
<!-- END: app/voice_notes_agent/agent.py -->

<!-- FILE: app/voice_notes_agent/agent_guided.py -->
````python
"""Guided (explicit turn-by-turn) Voice Notes Logger agent.

Where the implicit flow (``agent.py``) extracts everything from freeform
dictation in one deterministic "Mega-Payload" tool call, this agent follows a
fixed, explicit script: dictate -> confirm/replay -> explicit event-type
question -> one explicit disposition question per topic (deduce + confirm,
max 3 attempts) -> commit. Campaign config loading, generation config, and
the CRM commit path are shared with the implicit agent so both flows are
directly comparable side by side (same ``/api/v1`` REST contract, same
disposition registry).
"""

from __future__ import annotations

import logging
import os

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext

from .agent import STATE_AGENT_CONFIG, STATE_PLANNED_TOPICS, _GENERATION_CONFIG
from .agent import load_campaign_config
from .tools_guided import (
    capture_dictation,
    choose_post_dictation_action,
    commit_guided_notes,
    record_topic_disposition,
    set_event_type,
)

logger = logging.getLogger(__name__)


# WHERE THE COMMIT ACTUALLY HAPPENS -- read before editing Stage 5 below.
#
# Stage 5 of this script tells the model to call `commit_guided_notes`. In
# practice it usually does not need to: `tools_guided.record_topic_disposition`
# commits inline once the last topic is dispositioned, and hands the model only
# the closing statement to read.
#
# That is deliberate (Gap 6 / F5): asked to make a second tool call when it has
# nothing left to say, the model reliably ends its turn instead -- the record is
# complete and nothing is saved, with no signal that the save didn't happen.
# Committing directly removes the hop.
#
# The consequence for anyone editing Stage 5: a prompt change around the commit
# step -- e.g. asking for a spoken confirmation before saving -- will be
# SILENTLY SHORT-CIRCUITED, because the tool has already committed before the
# model gets a turn to act on the new instruction. Change
# `record_topic_disposition` too, or the prompt edit will appear to do nothing.
_GUIDED_SCRIPT = """
# Your job
You are a hands-free, EXPLICIT-script voice dictation assistant for a field
sales rep. Unlike a freeform assistant, you follow this fixed script exactly,
one explicit question at a time, and you NEVER skip ahead or silently infer
an answer the rep didn't actually give.

# Stage 0 -- Greeting
Say exactly: "Hi, I'm your post-call summary assistant. I'll help you capture
your visit notes and update the post-call summary. You can speak naturally,
and you can replay or re-record your notes at any time. Ready to begin?"
- "not now" / "cancel" -> say a brief goodbye and end. Do not save anything.
- "yes" / "start" / "go ahead" with NOTHING else said -> go to Stage 1 and say
  its prompt.
- "yes" (or similar) FOLLOWED, in the same turn, by actual visit content
  (e.g. "Yes, this was a meeting where we discussed...") -> they've already
  started dictating. Do NOT say the Stage 1 prompt or ask them to start over.
  Instead, silently treat everything after the "yes" as the first part of
  their dictation and go straight into Stage 1's listening behavior with that
  content already captured (accumulate it, wait for more or an end phrase,
  same rules as Stage 1 below).
- Actual visit content with NO "yes"/"start" at all (a rep who starts
  dictating immediately, before you've even said the greeting, or answers
  the greeting by diving straight into their notes) -> same as above: this
  IS their consent, treat their entire utterance as the first part of the
  dictation and go straight into Stage 1's listening behavior. Never respond
  to real visit content by reciting the Stage 0 greeting or asking "ready to
  begin?" -- only say the greeting when you have NOTHING else to go on yet
  (silence, or a genuinely unrelated/unclear first utterance).

# Stage 1 -- Note dictation
Say exactly: "Great, please dictate your visit notes now. When you're done,
say 'end notes.'" (Skip this line entirely if you already moved into Stage 1
because they front-loaded dictation content in their Stage 0 answer -- in
that case, say nothing and just keep listening.) Then listen. A pause after
they stop talking is treated as
them being finished (the same automatic pause-detection used everywhere else
in this app) -- you do NOT need to hear an explicit end phrase to proceed. If
they do say one ("end notes", "that's it", "done", "I'm finished", or a close
variant), drop it from the transcript you pass on; otherwise pass everything
they said as-is.

Exception: if what they've said so far trails off mid-thought (ends with
"and", "also", "um", "let me think", or similar unfinished-sounding filler),
you may wait ONE additional pause for them to continue before calling
capture_dictation. Never wait through a second consecutive pause -- if they
were silent, then spoke again, then paused again (even on a word like "and"),
that is your hard cutoff: call capture_dictation immediately with everything
said so far as raw_transcript. You must never go more than one pause without
either speaking or calling a tool -- silently waiting forever is not
acceptable.

When you finish listening, say and produce ABSOLUTELY NOTHING out loud before
calling capture_dictation -- no filler, no "one moment", no narration, no
partial or guessed summary, no mention of what you captured. Silence is the
correct, expected behavior here; the rep is fine waiting. You do not know the
final wording of the summary/menu until capture_dictation returns it -- do
not say or guess ANY of it beforehand.

  Example -- rep just said an end phrase or paused long enough to finish:
    WRONG: "I've captured your visit notes, summarizing that the contract
    renewal was successful and the client confirmed they'll be a preferred
    vendor... You can save, play back, or re-record."  <- spoken BEFORE the
    tool ran. Forbidden, even though it turned out roughly accurate -- it is
    still a duplicate of what capture_dictation is about to have you say for
    real, and the rep will hear the summary twice.
    RIGHT: (nothing spoken at all) -- silently call capture_dictation with
    the raw_transcript and your composed executive_summary, wait for it to
    return, and only then speak using its instruction_for_model.

When you call capture_dictation, also pass executive_summary: a real 2-3
sentence summary of what the rep just dictated, written by you, in your own
words. This is not a placeholder -- it must actually condense what they said
(similar to a call summary), because you will speak it back to them next
(after the tool returns, per the rule above) and may be asked to repeat it
verbatim later.

# Stage 2 -- Save / Play back / Re-record menu
After capture_dictation, present the menu it tells you to (which speaks the
executive_summary you just wrote), then call choose_post_dictation_action
with the rep's choice ("save", "playback", or "rerecord"). Follow whatever
instruction_for_model it returns next -- it may send you back to Stage 1
(re-record, which discards everything captured so far including any event
type/dispositions and the summary), keep you in this menu (playback, which
repeats the same summary, NOT the raw verbatim dictation), or move you to
Stage 3 (save).

# Stage 3 -- Event type (single explicit question)
Ask exactly: "Was this a meeting or an on-site visit?" Map the answer to
exactly one of Meeting / On-site visit / Phone Call and call set_event_type.
Never guess this from the earlier dictation -- always ask it explicitly.

# Stage 4 -- Topic disposition (one topic at a time, deduce + confirm, max 3
attempts)
For the topic set_event_type (or record_topic_disposition) names as next:
1. Ask exactly: "What was the outcome for [topic]?"
2. Attempt 1: silently deduce the single best-fit disposition code from the
   rep's answer (using the disposition registry/keywords below) and ask:
   "I think you mean [label] -- is that correct?"
   - "yes" -> call record_topic_disposition(topic, that code, a 1-2 sentence
     summary, discussed=true, needs_manual_review=false). Then continue with
     whatever topic it names next (repeat this Stage), or go to Stage 5 if it
     says all topics are done.
   - "no" -> Attempt 2: say "No problem, here are the outcome options:" and
     read the full numbered list of the 10 disposition options from the
     registry below, then ask "Which number best fits?"
     - A valid number 1-10 -> confirm once ("Got it, marking that as
       [label].") and call record_topic_disposition with that code,
       needs_manual_review=false.
     - Still no valid pick -> Attempt 3: repeat the numbered list ONE more
       time and ask again.
       - Still nothing valid after this 3rd attempt -> call
         record_topic_disposition with disposition_code=null,
         needs_manual_review=true, and executive_summary set to the rep's
         raw answer (for a human to resolve later). Do NOT retry past 3
         attempts, and do NOT cancel the whole session over one unresolved
         topic -- move on.
- If the rep says they didn't get to a topic (e.g. "skip that", "didn't cover
  it", "ran out of time"), call record_topic_disposition immediately with
  discussed=false, disposition_code=null, needs_manual_review=false, and
  their reason as executive_summary. Do not run the deduce/confirm loop for a
  skipped topic.
- If there were no pre-call planned topics, set_event_type will tell you to
  ask "What topics did you discuss?" instead -- take each topic the rep
  names, run the same deduce/confirm loop for it, then ask "Any other
  topics?" after each one until they say no, then proceed to Stage 5.

# Stage 5 -- Commit + closing
Once every topic is recorded (record_topic_disposition tells you when all
are done), call commit_guided_notes, then speak its closing_statement
verbatim and end the session. Do not say anything after the closing
statement. If record_topic_disposition already returned a closing_statement,
the record is saved -- just read it; calling commit_guided_notes again is
safe and will replay the same result.

# Speaking style
Speak every question and confirmation at a measured, unhurried pace -- not
rushed. Brief natural pause between sentences.

# Hard rules
- Never invent an answer the rep didn't give -- always ask explicitly, never
  infer event type or disposition silently from the earlier dictation.
- Never call record_topic_disposition with a fabricated disposition_code the
  rep didn't confirm (or explicitly skip/discuss).
- Only ever run the full script once per session.
- Every question you ask ("is that correct?", "was this a meeting or an
  on-site visit?", etc.) MUST be followed by actually stopping and waiting for
  a new rep utterance. Never answer your own question, never assume a "yes",
  and never call the next tool in the sequence until the rep has given a new,
  real response since your question was asked. Speak ZERO words guessing at
  an outcome before the relevant tool call -- only ask the exact scripted
  question, then wait.
"""


def _format_config_block(config: dict) -> str:
    """Render allowed event types + a numbered disposition list for retries."""
    allowed = ", ".join(config.get("allowed_event_types", []))
    registry_lines = [
        f"  {rule['code']}. {rule['label']}"
        for rule in config.get("disposition_registry", [])
    ]
    registry_block = "\n".join(registry_lines)
    return (
        f"# Allowed event types\n{allowed}\n\n"
        f"# Disposition registry (read as a numbered list on retry)\n"
        f"{registry_block}\n"
    )


def _format_planned_topics_block(planned_topics: list[str]) -> str:
    """Render the rep's pre-call planned topics as the guided-loop anchor."""
    if not planned_topics:
        return (
            "# Planned topics\nNone pre-selected -- ask the rep what topics "
            "they discussed instead of anchoring to a planned list.\n"
        )
    lines = "\n".join(f"  - {t}" for t in planned_topics)
    return f"# Planned topics (ask about each, in this order)\n{lines}\n"


def voice_notes_guided_instruction(ctx: ReadonlyContext) -> str:
    """Assemble the full system instruction from the dynamic config in state."""
    config = ctx.state.get(STATE_AGENT_CONFIG)
    if not config:
        logger.debug("Agent config missing from state; using script only")
        config = {}
    planned_topics = ctx.state.get(STATE_PLANNED_TOPICS) or []
    return (
        f"{_GUIDED_SCRIPT}\n\n"
        f"{_format_planned_topics_block(planned_topics)}\n"
        f"{_format_config_block(config)}"
    )


agent_guided = Agent(
    name="voice_notes_logger_guided",
    model=os.getenv(
        "VOICE_NOTES_AGENT_MODEL", "gemini-live-2.5-flash-native-audio"
    ),
    instruction=voice_notes_guided_instruction,
    tools=[
        capture_dictation,
        choose_post_dictation_action,
        set_event_type,
        record_topic_disposition,
        commit_guided_notes,
    ],
    before_agent_callback=load_campaign_config,
    generate_content_config=_GENERATION_CONFIG,
)
````
<!-- END: app/voice_notes_agent/agent_guided.py -->

<!-- FILE: app/voice_notes_agent/config.py -->
````python
import os

API_BASE = os.getenv("VOICE_NOTES_API_BASE", "http://localhost:8000")
````
<!-- END: app/voice_notes_agent/config.py -->

<!-- FILE: app/voice_notes_agent/notes_workflow.py -->
````python
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
- No guided-flow support. The guided flow is being retired separately;
  agent_mode / per-flow branching has been removed from this workflow.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml

from .schemas import CommitResult, TopicOutcome

logger = logging.getLogger(__name__)

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
        # Two cases legitimately carry no code: a planned topic the rep
        # never got to, and (guided-flow only, now retired) a topic flagged
        # for manual review. Anything else is a gap.
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
    """Normalize a topic label for tolerant matching."""
    return (label or "").strip().lower()


def compute_missing_topics(
    planned_topics: list[str],
    staged_topics: list[dict[str, Any]],
    allow_skips: bool = True,
) -> list[str]:
    """Return planned topics that have no corresponding entry in the payload.

    A planned topic is considered *covered* once it appears in the staged
    ``topics`` list. Matching is tolerant of case/whitespace and falls back
    to substring overlap so the model doesn't have to reproduce the catalog
    label verbatim.

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
        hit = pk in covered_keys or any(
            pk in ck or ck in pk for ck in covered_keys if ck
        )
        if not hit:
            missing.append(planned)
    return missing


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

    Reproduced by scripts/repro_orphan_restage.py (AIML-2703).
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
````
<!-- END: app/voice_notes_agent/notes_workflow.py -->

<!-- FILE: app/voice_notes_agent/schemas.py -->
````python
"""Pydantic schemas shared across the voice-notes workflow and tools layer.

Pulled out of mock_db.py (now notes_workflow.py) per the contract-
simplification pass: this module holds data shapes only, no logic, so both
notes_workflow.py and tools.py can import from here without either one
importing the other for type definitions.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiscussionTopic(BaseModel):
    """A single call topic within one visit, with its own disposition.

    A visit can cover several distinct call topics (e.g. pricing, then a
    renewal), and each one gets its own disposition + summary.

    Topics line up with the rep's *pre-call planned topics* (now hardcoded
    client-side; the server no longer serves or validates the catalog).
    Every planned topic should end up here:
    - If it was actually discussed, ``discussed`` is True and
      ``disposition_code`` carries the mapped outcome (one of the fixed
      disposition codes loaded from the workflow module's YAML registry).
    - If the rep confirmed they did not get to it, ``discussed`` is False and
      ``disposition_code`` may be omitted; ``executive_summary`` then holds
      the rep's feedback on why (e.g. "ran out of time, will cover next
      visit").
    """

    topic: str = Field(
        ..., description="Short label / subject of this call topic"
    )
    disposition_code: int | None = Field(
        default=None,
        description=(
            "Disposition outcome for THIS topic, chosen from the fixed "
            "disposition registry. Required when the topic was discussed; "
            "null for a planned-but-not-discussed topic."
        ),
    )
    executive_summary: str = Field(
        default="",
        description=(
            "Condensed 1-2 sentence summary of THIS topic. Leave empty "
            "rather than inventing one -- a topic the rep skipped without "
            "giving a reason has nothing to summarize, and a required field "
            "here forces the model to confabulate (observed live: 'Rep did "
            "not get to pricing due to time constraints' when the rep never "
            "said so)."
        ),
    )
    discussed: bool = Field(
        default=True,
        description=(
            "Whether this planned topic was actually covered in the "
            "dictation. False means the rep planned it but did not get to "
            "it."
        ),
    )
    needs_manual_review: bool = Field(
        default=False,
        description=(
            "Guided flow only: true if 3 disposition-confirm attempts "
            "failed and the code had to be left unresolved for a human to "
            "fix."
        ),
    )


class TopicOutcome(BaseModel):
    """One planned topic's final outcome, as delivered in Output2.

    Distinct from DiscussionTopic: this is the read-side shape returned by
    the commit tool, not the write-side shape the model stages. It adds
    ``disposition_label`` (the human-readable label, e.g. "Pricing
    concerns") so the UI and the spoken closing statement don't need their
    own copy of the disposition registry to render a code -- the workflow
    module fills it in from the loaded registry at commit time.
    """

    topic: str
    executive_summary: str = ""
    disposition_code: int | None = None
    disposition_label: str | None = None
    discussed: bool = True
    needs_manual_review: bool = False


class CommitResult(BaseModel):
    """Output2: the commit tool's own, authoritative response.

    Replaces both the old REST CommitResponse (which only carried
    {status, crm_record_id, closing_statement}) and the pattern of
    reconstructing the final record client-side from earlier streamed
    tool-call arguments. Identified by ``session_id`` alone -- there is no
    ``crm_record_id``: mock_db/notes_workflow never was a real CRM, and
    session_id is already a fresh UUID per commit (see AIML-2703), so it is
    the one genuine identifier for "this commit event".

    Used for BOTH a first-time commit and an idempotent-retry replay (the
    "already committed" branch in commit_notes returns this same shape,
    just reconstructed from the previously committed record instead of
    freshly built).
    """

    session_id: str
    executive_summary: str = Field(
        ..., description="Condensed whole-call summary."
    )
    planned_topics: list[str] = Field(
        default_factory=list,
        description="The pre-call planned topics the rep selected.",
    )
    topics: list[TopicOutcome] = Field(
        default_factory=list,
        description=(
            "One entry per planned topic: its brief summary and final "
            "disposition."
        ),
    )
    closing_statement: str = Field(
        ..., description="What the agent speaks aloud after a successful save."
    )
````
<!-- END: app/voice_notes_agent/schemas.py -->

<!-- FILE: app/voice_notes_agent/tools.py -->
````python
"""ADK function-call tools for the Voice Notes Logger agent.

These tools call the notes workflow (notes_workflow.py) directly, in-process
-- there is no HTTP hop. Previously they issued real HTTP calls to this same
FastAPI process's own /api/v1 endpoints (a self-loopback); that pattern, and
the endpoints it called, existed only to serve the guided flow and the
headless /api/v1/notes/process+/confirm API, both retired. Removing the
loopback also removes the one network hop that could time out mid-commit --
see the idempotent-retry comment in notes_workflow.commit_notes for what
that used to protect against and why the guard stays anyway (a retry can
still happen at the model level).

Two tools cover the whole flow:

* ``stage_visit_notes`` -- the single "Mega-Payload" function call the model
  emits after the user finishes dictating. Stages the payload and returns the
  natural-language confirmation string. Re-calling it with corrected fields
  handles the correction branch.
* ``commit_visit_notes`` -- commits the staged payload once the user gives
  positive confirmation, returning the full Output2 payload (see
  schemas.CommitResult) plus the closing statement.
"""

from __future__ import annotations

import json
import logging

from google.adk.tools import ToolContext

from . import notes_workflow, turn_guard
from .schemas import DiscussionTopic

logger = logging.getLogger(__name__)

# Session-state key holding the notes_workflow session_id for the currently
# staged record. This is the SAME id as tool_context.session.id: the ADK
# WebSocket session id is passed straight through as the staging session_id
# (see stage_visit_notes below), and app.js's finishSession() ->
# newSessionId() guarantees a fresh one per dictation (AIML-2703: one
# session = one commit) -- so there is nothing else to mint or track here.
_STAGED_SESSION_KEY = "crm_staged_session_id"
_LAST_CONFIRMATION_KEY = "crm_last_confirmation_text"

# The disposition registry is universal now (no campaign_type, no per-session
# fetch) -- codes legal for a topic are just every code notes_workflow knows
# about, always.
_VALID_DISPOSITION_CODES = set(notes_workflow.VALID_DISPOSITION_CODES)


def _normalize_topics(
    topics, valid_codes: set[int]
) -> tuple[list[dict], list[str]]:
    """Coerce the model's ``topics`` arg into well-formed dicts.

    The Live model occasionally emits ``topics`` as bare strings or partial
    objects instead of full ``{topic, disposition_code, executive_summary}``
    entries. We must NEVER raise here: an exception inside the tool tears down
    the whole live stream (the UI gets stuck on "agent responding" with no
    spoken read-back). Instead we normalize what we can and report which
    entries are incomplete so the caller can ask the model to retry.

    Returns ``(normalized, problems)`` where ``problems`` is a list of
    human-readable issues (empty when every topic is valid).
    """
    normalized: list[dict] = []
    problems: list[str] = []

    for idx, raw in enumerate(topics or []):
        item = raw
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        elif isinstance(item, str):
            # Could be a JSON object encoded as a string, or just a label.
            try:
                parsed = json.loads(item)
                item = parsed if isinstance(parsed, dict) else {"topic": item}
            except (ValueError, TypeError):
                item = {"topic": item}
        elif not isinstance(item, dict):
            item = {"topic": str(item)}

        topic = (item.get("topic") or "").strip()
        code = item.get("disposition_code")
        try:
            code = int(code) if code is not None else None
        except (ValueError, TypeError):
            code = None
        # Never forward a code that isn't in the disposition registry -- the
        # workflow's validation would reject it. Drop it and let the
        # discussed-topic check below ask the model to re-map.
        if code is not None and code not in valid_codes:
            code = None

        # Default to discussed=True for backward compatibility; only an
        # explicit False marks a planned-but-not-covered topic.
        discussed = item.get("discussed")
        discussed = True if discussed is None else bool(discussed)
        # The rep was asked but no allowed code genuinely fits what they said.
        # Flagging for a human is a legitimate terminal state, not an error --
        # without carrying this through, the model's only options are to guess
        # a wrong code or loop.
        needs_review = bool(item.get("needs_manual_review", False))

        if not topic:
            problems.append(f"topic #{idx + 1} is missing a subject label")
        # A discussed topic needs a valid disposition; a not-discussed planned
        # topic is allowed to have none (it's awaiting the rep's feedback), and
        # so is one explicitly flagged for manual review.
        if discussed and code is None and not needs_review:
            problems.append(
                f"topic '{topic or idx + 1}' is missing a valid "
                f"disposition_code from the registry"
            )

        normalized.append(
            {
                "topic": topic or f"topic {idx + 1}",
                "disposition_code": code,
                "executive_summary": (item.get("executive_summary") or "").strip(),
                "discussed": discussed,
                "needs_manual_review": needs_review,
            }
        )

    if not normalized:
        problems.append("no discussion topics were provided")

    return normalized, problems


async def stage_visit_notes(
    event_type: str,
    executive_summary: str,
    raw_transcript_backup: str,
    topics: list[DiscussionTopic],
    tool_context: ToolContext,
) -> dict:
    """Stage the fully extracted visit notes for the user to confirm.

    Call this exactly once after the rep finishes dictating, with every field
    populated from the spoken notes. To apply a correction the user requested,
    call it again with the full, updated set of fields -- the backend will read
    back only what changed.

    A single visit can cover MULTIPLE discussion topics (e.g. the rep talked
    about pricing AND an integration timeline). Capture each distinct topic as
    its own entry in ``topics``, each with its own disposition_code and
    executive_summary. If the rep only discussed one thing, pass a single
    topic.

    Args:
        event_type: Interaction type for the whole visit. One of "Meeting",
            "On-site visit", or "Phone Call".
        executive_summary: A condensed, structured 2-sentence summary of the
            ENTIRE call across all topics.
        raw_transcript_backup: The full verbatim transcript of the dictation,
            preserved for auditing.
        topics: One or more discussion topics, anchored to the rep's planned
            topics. Each topic has:
            - topic: the planned-topic label, copied exactly (or a new label
              only if the rep discussed something off-plan).
            - disposition_code: outcome code 1-10 mapped from the disposition
              registry for THAT topic (e.g. 8 = Pricing concerns). Required
              when the topic was discussed.
            - executive_summary: a condensed 1-2 sentence summary of THAT topic
              (or the rep's reason if it was planned but not discussed).
              If no business-outcome code describes what actually happened,
              use code 99 ("Outcome not covered - needs manual review"), which
              is always present in the registry. Never pick a nearby code
              that states something false -- a record flagged 99 gets corrected
              by a human, a confidently wrong one never gets noticed.
            - needs_manual_review: set automatically when disposition_code is
              99; you do not need to set it yourself.
            - discussed: true if the rep covered it. Set false ONLY after you
              asked the rep about the topic and they said they did not get to
              it -- never on the first call. A planned topic the rep never
              mentioned must be omitted from this list entirely, so the
              coverage check can remind you to ask. If they give no reason,
              leave executive_summary empty rather than inventing one.

    Returns:
        A dict containing ``confirmation_text`` -- the exact sentence to read
        back to the user -- and ``session_id``.
    """
    topic_list, problems = _normalize_topics(topics, _VALID_DISPOSITION_CODES)
    if problems:
        # Don't stage an incomplete record (and don't raise -- that would kill
        # the live stream). Ask the model to re-call with full topic objects.
        logger.warning("stage_visit_notes incomplete topics: %s", problems)
        return {
            "status": "incomplete",
            "problems": problems,
            "instruction_for_model": (
                "The topics were incomplete: "
                + "; ".join(problems)
                + ". Call stage_visit_notes again. Each entry in `topics` MUST "
                "be an object with three fields: `topic` (short subject), "
                "`disposition_code` (one of these integers, and no other: "
                + ", ".join(str(c) for c in sorted(_VALID_DISPOSITION_CODES))
                + "), and `executive_summary` (1-2 sentences). Do not "
                "pass topics as plain strings."
            ),
        }

    # Planned topics were seeded into session state at connect time. They
    # drive the coverage check (which planned topics still need an outcome).
    planned_topics = tool_context.state.get("planned_topics") or []

    payload = {
        "event_type": event_type,
        "executive_summary": executive_summary,
        "raw_transcript_backup": raw_transcript_backup,
        "topics": topic_list,
    }

    # Validate against the universal event/disposition rules before staging.
    # Previously this was the REST layer's job (a 422 from
    # /api/v1/notes/stage); calling it directly here is the same check,
    # just without a network hop to carry the rejection back over.
    validation_problems, config = notes_workflow.validate_payload(payload)
    if validation_problems:
        allowed_codes = [
            rule["code"] for rule in config["disposition_registry"]
        ]
        allowed_events = config["allowed_event_types"]
        logger.warning(
            "Staging rejected by validation: %s", validation_problems
        )
        return {
            "status": "rejected",
            "problems": validation_problems,
            "instruction_for_model": (
                "The record was REJECTED and nothing was saved: "
                + "; ".join(p for p in validation_problems if p)
                + ". Only these event types are allowed: ["
                + ", ".join(allowed_events)
                + "] and only these disposition codes: ["
                + ", ".join(str(c) for c in allowed_codes)
                + "]. Re-map to the closest ALLOWED value and call "
                "stage_visit_notes again. Never invent a code. If no allowed "
                "code genuinely fits what the rep said, do not guess -- ask "
                "the rep out loud which outcome applies, then re-stage."
            ),
        }

    logger.info("stage_visit_notes tool invoked: %s", payload)

    # If notes were already staged this session, this call is a correction:
    # pass the prior session id so the confirmation reads back only the
    # changes.
    previous_session_id = tool_context.state.get(_STAGED_SESSION_KEY)

    try:
        data = notes_workflow.stage_notes(
            payload,
            previous_session_id=previous_session_id,
            planned_topics=list(planned_topics),
            # The ADK WebSocket session id doubles as the notes_workflow
            # session_id -- see the module docstring above. Passing it
            # explicitly (rather than letting stage_notes mint a fresh uuid)
            # is what makes commit_visit_notes's later lookup and the
            # eventual audit row line up with the same session_id the rest
            # of the app already knows about.
            session_id=tool_context.session.id,
        )
    except Exception:  # noqa: BLE001 - must never break the live stream
        logger.exception("stage_notes raised for session_id=%s", tool_context.session.id)
        return {
            "status": "error",
            "error": "Could not stage the notes due to an internal error.",
            "instruction_for_model": (
                "Tell the user there was a temporary problem saving and to "
                "try again in a moment."
            ),
            "ui_event": "tool_error",
        }

    # Persist the staged session id so the commit tool can reference it
    # later (also handles the correction branch above, next time through).
    tool_context.state[_STAGED_SESSION_KEY] = data["session_id"]

    missing = data.get("missing_topics") or []
    if missing:
        instruction = (
            "Now speak the confirmation_text aloud to the user, verbatim and "
            "in full. It REMINDS them that these planned topics still need an "
            f"outcome: {', '.join(missing)}. Do NOT save yet. Wait for the "
            "rep's feedback, then call stage_visit_notes again with the full "
            "payload, adding a topic entry for each of these (discussed=true "
            "with a disposition_code if they give an outcome, or "
            "discussed=false with their reason if they skipped it)."
        )
    else:
        instruction = (
            "Now speak the confirmation_text aloud to the user, verbatim and in "
            "full (it includes your summary of what was captured). Do not stay "
            "silent. Then wait for them to either confirm saving or request a "
            "change."
        )

    # From here on, the model is about to ask the rep a question (the
    # confirmation_text). commit_visit_notes must not fire until a genuine
    # NEW reply is heard after this point -- see turn_guard. Cache the exact
    # wording so a blocked commit can re-ask with the SAME real summary
    # instead of a generic filler line.
    turn_guard.snapshot(tool_context)
    tool_context.state[_LAST_CONFIRMATION_KEY] = data["confirmation_text"]

    return {
        "status": "staged",
        "session_id": data["session_id"],
        "confirmation_text": data["confirmation_text"],
        "missing_topics": missing,
        "all_topics_covered": data.get("all_topics_covered", True),
        "instruction_for_model": instruction,
    }


async def commit_visit_notes(tool_context: ToolContext) -> dict:
    """Commit the currently staged visit notes to the CRM.

    Call this only after the user gives positive confirmation (e.g. "save it",
    "yes", "that's correct"). Do not call it before notes have been staged.

    Returns:
        A dict containing the full Output2 payload (session_id,
        executive_summary, planned_topics, per-topic outcomes) plus
        ``closing_statement`` -- the exact sentence to read back to the user
        before ending the session.
    """
    session_id = tool_context.state.get(_STAGED_SESSION_KEY)
    if not session_id:
        logger.warning("commit_visit_notes called with no staged session")
        return {
            "status": "error",
            "error": "no_staged_notes",
            "instruction_for_model": (
                "There are no staged notes yet. Ask the user to dictate their "
                "notes first."
            ),
        }

    # Hard backstop: refuse to commit unless a genuine NEW rep utterance has
    # arrived since the confirmation question was staged/asked. This blocks
    # the model self-answering its own "does that sound correct?" question
    # and committing with nobody actually having confirmed anything.
    #
    # Second, independent check: the model must have actually SPOKEN the real
    # confirmation_text after stage_visit_notes returned -- a pre-tool-call
    # guess/filler does not count, even if the rep replied to that guess. This
    # catches the case where the model asks its own guessed question, then
    # goes silent once the tool returns and treats the rep's answer to the
    # guess as if it were confirmation of the REAL extracted data.
    if not turn_guard.confirmation_was_read(tool_context):
        logger.warning(
            "commit_visit_notes BLOCKED: real confirmation_text was never "
            "spoken after staging (session_id=%s) -- refusing to save.",
            session_id,
        )
        last_confirmation = tool_context.state.get(_LAST_CONFIRMATION_KEY)
        return {
            "status": "error",
            "error": "confirmation_not_read",
            "instruction_for_model": (
                "Do not call commit_visit_notes. You have not yet actually "
                "spoken the real staged summary to the rep -- anything you "
                "said before the tool call was a guess and does not count. "
                "Say this out loud, verbatim, right now: "
                f"\"{last_confirmation}\" Then wait for their answer."
            )
            if last_confirmation
            else (
                "Do not call commit_visit_notes -- you have not yet spoken "
                "the real staged confirmation to the rep. Ask them to "
                "confirm the details now and wait for their answer."
            ),
        }

    if not turn_guard.has_new_reply(tool_context):
        logger.warning(
            "commit_visit_notes BLOCKED: no new rep reply since staging "
            "(session_id=%s) -- refusing to save.",
            session_id,
        )
        last_confirmation = tool_context.state.get(_LAST_CONFIRMATION_KEY)
        if last_confirmation:
            reask = (
                "Do not call commit_visit_notes -- you have not actually "
                "heard the rep reply yet. Say this out loud, verbatim: "
                f"\"{last_confirmation}\" Then wait for their answer. Never "
                "leave the rep in silence."
            )
        else:
            reask = (
                "Do not call commit_visit_notes -- you have not actually "
                "heard the rep reply yet. Say out loud: 'Sorry, did you want "
                "me to save this?' and then wait for their answer. Never "
                "leave the rep in silence."
            )
        return {
            "status": "error",
            "error": "no_confirmation_heard",
            "instruction_for_model": reask,
        }

    logger.info("commit_visit_notes tool invoked: session_id=%s", session_id)

    try:
        result = notes_workflow.commit_notes(session_id, confirmed=True)
    except KeyError:
        # The staged record is gone (should not normally happen -- the
        # _STAGED_SESSION_KEY check above already confirmed one was staged
        # -- but never let this surface as a crash).
        logger.exception("commit_notes found no staged record for session_id=%s", session_id)
        return {
            "status": "error",
            "error": "no_staged_notes",
            "instruction_for_model": (
                "There are no staged notes to save anymore. Ask the user to "
                "dictate their notes again."
            ),
        }
    except notes_workflow.SupersededRecordError as exc:
        # The rep corrected this record after it was staged, but before this
        # confirm -- committing it would save the outcome they corrected
        # away from. This should be rare given turn_guard's checks above,
        # but is a real, named failure mode (AIML-2703), not a crash.
        logger.warning(
            "Commit blocked -- session_id=%s was superseded by %s",
            session_id,
            exc.superseded_by,
        )
        tool_context.state[_STAGED_SESSION_KEY] = exc.superseded_by
        return {
            "status": "blocked",
            "error": "superseded_record",
            "instruction_for_model": (
                "NOTHING was saved -- that draft was replaced by a later "
                "correction. Say so, then confirm with the rep whether the "
                "most recent version is correct before calling "
                "commit_visit_notes again."
            ),
        }
    except notes_workflow.IncompleteCoverageError as exc:
        # Coverage gate: planned topics still have no outcome. Nothing was
        # written. Collect the outcomes and re-stage before trying again.
        logger.warning(
            "Commit blocked -- uncovered planned topics: %s",
            exc.missing_topics,
        )
        return {
            "status": "blocked",
            "error": "incomplete_coverage",
            "missing_topics": exc.missing_topics,
            "instruction_for_model": (
                "NOTHING was saved. These planned topics still have no "
                "outcome: " + ", ".join(exc.missing_topics) + ". Say out "
                "loud that you still need those before saving, and ask the "
                "rep what happened with them. When they answer, call "
                "stage_visit_notes again with the FULL payload including an "
                "entry for each (discussed=true with a disposition_code if "
                "they give an outcome, or discussed=false with their reason "
                "if they skipped it), then commit."
            ),
        }
    except Exception:  # noqa: BLE001 - must never break the live stream
        logger.exception("commit_notes raised for session_id=%s", session_id)
        return {
            "status": "error",
            "error": "Could not commit the notes due to an internal error.",
            "instruction_for_model": (
                "Tell the user there was a temporary problem saving and to "
                "try again in a moment."
            ),
            "ui_event": "tool_error",
        }

    if isinstance(result, dict):
        # confirmed=False path returns {"status": "cancelled", ...} instead
        # of a CommitResult -- not reachable from this tool (we always pass
        # confirmed=True), but handled rather than assumed away.
        return {
            **result,
            "instruction_for_model": "Read the closing_statement to the user verbatim.",
        }

    # Clear staged session so a fresh dictation starts clean.
    tool_context.state[_STAGED_SESSION_KEY] = None

    # Output2: the commit tool's own, authoritative response -- the UI
    # renders from this directly instead of reconstructing it from earlier
    # streamed tool-call arguments.
    return {
        "status": "success",
        **result.model_dump(),
        "instruction_for_model": (
            "Read the closing_statement to the user verbatim. The session is "
            "now complete."
        ),
    }
````
<!-- END: app/voice_notes_agent/tools.py -->

<!-- FILE: app/voice_notes_agent/tools_guided.py -->
````python
"""ADK function-call tools for the Guided (explicit turn-by-turn) Voice Notes
agent.

Unlike the implicit flow's single "Mega-Payload" call, the guided flow builds
the CRM record incrementally across several small, explicit tool calls -- one
per conversational stage -- mirroring the fixed script (dictation -> menu ->
event type -> per-topic disposition -> commit). Like the implicit flow's
tools, these call the real ``/api/v1`` REST endpoints rather than touching the
store directly, so both flows commit through the identical CRM path.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from google.adk.tools import ToolContext

from .mock_db import VALID_DISPOSITION_CODES, VALID_EVENT_TYPES
from . import turn_guard

logger = logging.getLogger(__name__)

_API_BASE = os.getenv("VOICE_NOTES_API_BASE", "http://localhost:8000")
_HTTP_TIMEOUT = 15.0

# Session-state keys tracking progress through the guided script.
_S_TRANSCRIPT = "guided_raw_transcript"
_S_SUMMARY = "guided_executive_summary"
_S_EVENT_TYPE = "guided_event_type"
_S_TOPIC_RESULTS = "guided_topic_results"
_S_PENDING_TOPICS = "guided_pending_topics"
# Set once the record has actually been committed, so a second
# commit_guided_notes call replays the original result instead of re-staging
# and minting a duplicate CRM record. Needed because the last topic's
# disposition now commits directly (see record_topic_disposition) -- the model
# may still make the call it was previously instructed to make.
_S_COMMIT_RESULT = "guided_commit_result"
# Written by agent_guided's config callback (literal to avoid a circular import).
_AGENT_CONFIG_KEY = "agent_config"
_CAMPAIGN_TYPE_KEY = "campaign_type"


def _campaign_rules(tool_context: ToolContext) -> tuple[list[str], set[int]]:
    """Event types and disposition codes legal for THIS session's campaign.

    Falls back to the global registry only if the dynamic config never loaded;
    the REST layer re-validates campaign rules regardless, so a failed config
    fetch cannot let an illegal value through to the CRM.
    """
    config = tool_context.state.get(_AGENT_CONFIG_KEY) or {}
    events = list(config.get("allowed_event_types") or []) or list(
        VALID_EVENT_TYPES
    )
    registry = config.get("disposition_registry") or []
    codes = {int(rule["code"]) for rule in registry if "code" in rule}
    return events, (codes or set(VALID_DISPOSITION_CODES))


# One lock per live session, guarding the read-then-commit sequence in
# commit_guided_notes. ADK's Live flow can dispatch several function calls from
# a single model turn concurrently (asyncio.gather), and that sequence spans
# two awaited HTTP round-trips -- long enough for a second invocation to read
# _S_COMMIT_RESULT as unset and commit independently.
#
# Keyed by session id and never evicted; folds into B11's cleanup hook along
# with turn_guard's dicts and mock_db._STAGED_NOTES.
_COMMIT_LOCKS: dict[str, asyncio.Lock] = {}


def _commit_lock(tool_context: ToolContext) -> asyncio.Lock:
    """Return this session's commit lock, creating it if needed.

    Safe without its own lock: there is no await between the lookup and the
    insert, so no other task can run in between and create a second one.
    """
    key = tool_context.session.id
    lock = _COMMIT_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _COMMIT_LOCKS[key] = lock
    return lock


def _reset_guided_state(tool_context: ToolContext) -> None:
    """Discard everything captured so far (a full re-record restart)."""
    tool_context.state[_S_TRANSCRIPT] = None
    tool_context.state[_S_SUMMARY] = None
    tool_context.state[_S_EVENT_TYPE] = None
    tool_context.state[_S_TOPIC_RESULTS] = []
    # Cleared with the rest: a commit result belongs to the record that was
    # just discarded, and leaving it set makes the next commit replay a CRM id
    # for a record this session no longer holds.
    tool_context.state[_S_COMMIT_RESULT] = None
    tool_context.state[_S_PENDING_TOPICS] = list(
        tool_context.state.get("planned_topics") or []
    )


def _topic_matches(a: str, b: str) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def _join_natural(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


async def capture_dictation(
    raw_transcript: str, executive_summary: str, tool_context: ToolContext
) -> dict:
    """Call this exactly once the rep is done dictating -- either because they
    said an explicit end phrase ("end notes", "that's it", "done", "I'm
    finished") OR because they simply stopped talking and a pause was
    detected (silence alone IS sufficient; do not wait indefinitely for an
    explicit end phrase that may never come -- see Stage 1's trailing-off
    cutoff rule for the one-extra-pause exception).

    Args:
        raw_transcript: The rep's full dictation, verbatim, up to (not
            including) any end phrase they said.
        executive_summary: A condensed, structured 2-3 sentence summary of
            what the rep just dictated, written by you right now. This is
            what gets spoken back to the rep next and played back verbatim
            on request -- it must actually summarize the content, never a
            generic placeholder like "visit log covering N topics."

    Returns:
        instruction_for_model describing what to say (including the
        summary) and the Save / Play back / Re-record menu to present next.
    """
    # A dictation arriving when a commit result is already on the session means
    # the rep has started their NEXT visit without the client having rotated
    # session_id (it holds the socket open between dictations to skip Vertex's
    # cold-start handshake). Without this reset that stale result is replayed at
    # the next commit: the agent says "saved" and reads back the PREVIOUS
    # visit's CRM id, while nothing for this visit was ever staged.
    #
    # The client also rotates session_id after a commit now, which makes this
    # state empty by construction -- but the guarantee cannot depend on one
    # client behaving. Any caller reusing a session gets it here.
    if tool_context.state.get(_S_COMMIT_RESULT):
        logger.info(
            "capture_dictation: new dictation on a session that already "
            "committed -- clearing guided state before capturing."
        )
        _reset_guided_state(tool_context)

    tool_context.state[_S_TRANSCRIPT] = raw_transcript
    tool_context.state[_S_SUMMARY] = executive_summary
    if not tool_context.state.get(_S_PENDING_TOPICS):
        tool_context.state[_S_PENDING_TOPICS] = list(
            tool_context.state.get("planned_topics") or []
        )
    tool_context.state.setdefault(_S_TOPIC_RESULTS, [])
    logger.info(
        "capture_dictation: %d chars, summary: %d chars",
        len(raw_transcript),
        len(executive_summary),
    )
    # You're about to ask the Save/Playback/Re-record question -- the next
    # choose_post_dictation_action call must be a genuine reply to it.
    turn_guard.snapshot(tool_context)
    return {
        "status": "captured",
        "instruction_for_model": (
            "Say: 'Got it, here's your summary: ' then speak this "
            f"executive_summary verbatim: {executive_summary!r}. Then ask: "
            "'Would you like to Save, Play back what I captured, or "
            "Re-record?' Wait for the rep's choice and call "
            "choose_post_dictation_action with it."
        ),
    }


async def choose_post_dictation_action(
    action: str, tool_context: ToolContext
) -> dict:
    """Handle the rep's Save / Play back / Re-record choice after dictation.

    Args:
        action: One of "save", "playback", "rerecord" (map the rep's spoken
            choice to exactly one of these; treat "continue" as "save").
    """
    action = (action or "").strip().lower()

    # Hard backstop: this tool must only fire in direct response to a real
    # rep reply to the Save/Playback/Re-record question (or a subsequent
    # re-ask of it) -- never a self-answered guess.
    if not turn_guard.has_new_reply(tool_context):
        logger.warning("choose_post_dictation_action BLOCKED: no new reply")
        return {
            "status": "error",
            "error": "no_reply_heard",
            "instruction_for_model": (
                "Do not call choose_post_dictation_action -- you have not "
                "actually heard the rep answer yet. Ask again out loud: "
                "'Sorry, would you like to Save, Play back, or Re-record?' "
                "and wait for their answer. Never leave the rep in silence."
            ),
        }

    if action == "rerecord":
        _reset_guided_state(tool_context)
        turn_guard.snapshot(tool_context)
        return {
            "status": "rerecord",
            "instruction_for_model": (
                "Say: 'Okay, let's re-record your notes.' Then say: 'Please "
                "dictate your visit notes now. When you're done, say "
                "\"end notes.\"' and wait for the new dictation."
            ),
        }
    if action == "playback":
        summary = tool_context.state.get(_S_SUMMARY) or ""
        turn_guard.snapshot(tool_context)
        return {
            "status": "playback",
            "summary": summary,
            "instruction_for_model": (
                "Say: 'Here's your summary again: ' Then speak this "
                f"executive_summary verbatim: {summary!r}. Then ask: 'Would "
                "you like to Save, Re-record, or continue as-is?' and wait, "
                "calling choose_post_dictation_action again with their "
                "answer (treat 'continue' the same as 'save')."
            ),
        }
    if action in ("save", "continue"):
        pending = tool_context.state.get(_S_PENDING_TOPICS) or []
        turn_guard.snapshot(tool_context)
        return {
            "status": "proceed_to_event_type",
            "instruction_for_model": (
                "Ask exactly: 'Was this a meeting or an on-site visit?' Map "
                "the rep's answer to one of Meeting / On-site visit / Phone "
                "Call, then call set_event_type with it. (Pending topics to "
                f"disposition afterward: {pending!r})"
            ),
        }
    turn_guard.snapshot(tool_context)
    return {
        "status": "unrecognized",
        "instruction_for_model": (
            "That choice wasn't recognized. Ask again: 'Would you like to "
            "Save, Play back, or Re-record?'"
        ),
    }


async def set_event_type(event_type: str, tool_context: ToolContext) -> dict:
    """Record the rep's answer to the explicit event-type question.

    Args:
        event_type: Must be one of "Meeting", "On-site visit", "Phone Call".
    """
    # Hard backstop: must be a genuine reply to the "was this a meeting or
    # on-site visit?" question, never a self-answered guess.
    if not turn_guard.has_new_reply(tool_context):
        logger.warning("set_event_type BLOCKED: no new reply")
        return {
            "status": "error",
            "error": "no_reply_heard",
            "instruction_for_model": (
                "Do not call set_event_type -- you have not actually heard "
                "the rep answer yet. Ask again out loud: 'Sorry, was this a "
                "meeting or an on-site visit?' and wait for their answer. "
                "Never leave the rep in silence."
            ),
        }

    allowed_events, _ = _campaign_rules(tool_context)
    if event_type not in allowed_events:
        turn_guard.snapshot(tool_context)
        return {
            "status": "invalid",
            "instruction_for_model": (
                f"'{event_type}' isn't allowed for this campaign. Ask again, "
                "offering only the allowed options out loud, and map the "
                f"answer to exactly one of {allowed_events}."
            ),
        }
    tool_context.state[_S_EVENT_TYPE] = event_type
    pending = tool_context.state.get(_S_PENDING_TOPICS) or []
    logger.info("set_event_type=%s pending_topics=%s", event_type, pending)
    turn_guard.snapshot(tool_context)

    if not pending:
        return {
            "status": "no_planned_topics",
            "instruction_for_model": (
                "Got it. The rep had no pre-call planned topics, so ask: "
                "'What topics did you discuss?' Take the first topic they "
                "name and start the disposition loop for it (see topic "
                "disposition rules), then ask 'Any other topics?' after each "
                "one until they say no."
            ),
        }
    first_topic = pending[0]
    return {
        "status": "event_type_set",
        "next_topic": first_topic,
        "instruction_for_model": (
            f"Say 'Got it.' Then ask exactly: 'What was the outcome for "
            f"{first_topic}?' and begin the disposition deduction/confirm "
            "loop for that topic (max 3 attempts, per the disposition "
            "rules), then call record_topic_disposition."
        ),
    }


async def record_topic_disposition(
    topic: str,
    disposition_code: int | None,
    executive_summary: str,
    discussed: bool,
    needs_manual_review: bool,
    tool_context: ToolContext,
) -> dict:
    """Finalize the disposition for ONE topic and advance to the next.

    Call this ONCE per topic, only after the rep has confirmed the deduced
    disposition ("yes"), after they explicitly skip the topic, or after 3
    failed confirm attempts (set needs_manual_review=True and
    disposition_code=None in that case -- never fabricate a code the rep
    didn't confirm).

    Args:
        topic: The exact topic label being dispositioned.
        disposition_code: Confirmed code 1-10, or None if unresolved/skipped.
        executive_summary: 1-2 sentence summary of this topic's outcome (or
            the rep's raw answer / skip reason if unresolved).
        discussed: True unless the rep explicitly skipped this topic.
        needs_manual_review: True only if 3 attempts failed to get a
            confirmed disposition.
    """
    # Hard backstop: must be a genuine reply since the outcome question (or
    # its confirm/numbered-list follow-up) was asked, never a self-answered
    # guess immediately followed by recording a fabricated result.
    if not turn_guard.has_new_reply(tool_context):
        logger.warning("record_topic_disposition BLOCKED: no new reply topic=%s", topic)
        return {
            "status": "error",
            "error": "no_reply_heard",
            "instruction_for_model": (
                f"Do not call record_topic_disposition -- you have not "
                f"actually heard the rep reply yet. Ask again out loud: "
                f"'Sorry, what was the outcome for {topic}?' and wait for "
                f"their answer. Never leave the rep in silence."
            ),
        }

    _, valid_codes = _campaign_rules(tool_context)
    if disposition_code is not None and int(disposition_code) not in valid_codes:
        logger.warning(
            "record_topic_disposition: code %s is not in this campaign's "
            "registry %s -- flagging topic %r for manual review instead of "
            "recording an invalid code.",
            disposition_code,
            sorted(valid_codes),
            topic,
        )
        disposition_code = None
        needs_manual_review = True

    # Copy-then-replace, never append in place. Mutating the list held in
    # session state edits the stored object directly, which ADK does not
    # necessarily see as a state delta, and it makes the sequence order-
    # dependent if an await is ever introduced between the read and the write.
    # `pending` below already follows this pattern.
    results = list(tool_context.state.get(_S_TOPIC_RESULTS) or [])
    results.append(
        {
            "topic": topic,
            "disposition_code": disposition_code,
            "executive_summary": executive_summary,
            "discussed": discussed,
            "needs_manual_review": needs_manual_review,
        }
    )
    tool_context.state[_S_TOPIC_RESULTS] = results

    pending = list(tool_context.state.get(_S_PENDING_TOPICS) or [])
    if pending and _topic_matches(pending[0], topic):
        pending = pending[1:]
    tool_context.state[_S_PENDING_TOPICS] = pending

    logger.info(
        "record_topic_disposition topic=%s code=%s manual_review=%s "
        "remaining=%d",
        topic,
        disposition_code,
        needs_manual_review,
        len(pending),
    )

    note = (
        "Say: 'Got it, I'll flag this one for manual review.' "
        if needs_manual_review
        else "Say: 'Got it.' "
    )

    # About to ask another question (next topic) or hand off to commit --
    # either way, the NEXT tool call must follow a genuine new reply.
    turn_guard.snapshot(tool_context)

    if pending:
        return {
            "status": "next_topic",
            "next_topic": pending[0],
            "instruction_for_model": (
                f"{note}Then ask exactly: 'What was the outcome for "
                f"{pending[0]}?' and run the disposition loop again."
            ),
        }
    # Every topic is dispositioned. Commit HERE rather than instructing the
    # model to make a second tool call.
    #
    # THIS IS THE REAL COMMIT TRIGGER for the guided flow -- not Stage 5 of the
    # prompt in agent_guided.py, which still tells the model to call
    # commit_guided_notes. A matching note sits above _GUIDED_SCRIPT there.
    # Anyone changing the prompt around the commit step (e.g. requiring a spoken
    # confirmation first) has to change this call too, or the prompt edit is
    # silently short-circuited: the record is already saved by the time the
    # model gets a turn.
    #
    # Gap 6 / F5: asking for that second call is where guided mode stalls --
    # the model emits `OUT_TX text='' finished=True`, closes its turn and
    # never calls commit_guided_notes. The rep has answered everything, the
    # record is complete, and nothing is saved, with no signal that the save
    # didn't happen. Reproduced on demand via ws_smoke_test.
    #
    # The extra hop bought nothing: no further rep input is needed at this
    # point, so the record can be committed directly and the model handed only
    # the words to say. A prompt rule cannot fix this -- the model is being
    # asked to act when it has nothing left to say, which is exactly when it
    # ends the turn.
    result = await commit_guided_notes(tool_context)
    if result.get("status") not in ("blocked", "rejected", "error"):
        result["instruction_for_model"] = (
            f"{note}Read the closing_statement verbatim. The session is now "
            "complete."
        )
    # blocked/rejected/error keep their own recovery instruction -- the model
    # asks the rep, re-records, and calls commit_guided_notes itself.
    return result


async def commit_guided_notes(tool_context: ToolContext) -> dict:
    """Assemble the completed guided record and commit it to the CRM.

    Call this only after every topic has a recorded disposition (or
    needs_manual_review flag).

    Normally the last record_topic_disposition call commits directly and you
    do not need to call this at all -- but calling it again is safe.
    """
    # Idempotency. The final disposition already commits, so a model that
    # still makes this call would otherwise re-stage under a NEW session_id
    # and mint a duplicate CRM record -- mock_db's own idempotency guard is
    # keyed on session_id and cannot catch that.
    #
    # The check has to be an atomic claim, not get-then-set. The commit below
    # spans two awaited HTTP round-trips, and ADK's Live flow can dispatch
    # several function calls from one model turn concurrently: both invocations
    # would read `prior` as unset, both would stage under their own new
    # session_id, and both would commit. Two independent stagings, so neither
    # the supersede gate nor mock_db's session-keyed idempotency sees anything
    # wrong -- two CRM records for one visit.
    #
    # The lock serializes them; the loser then finds the winner's result on the
    # re-check inside and replays it, which is exactly the intended behaviour
    # for a duplicate call.
    prior = tool_context.state.get(_S_COMMIT_RESULT)
    if prior:
        logger.info(
            "commit_guided_notes: already committed as crm_record_id=%s -- "
            "replaying the original result instead of re-staging",
            prior.get("crm_record_id"),
        )
        return prior

    async with _commit_lock(tool_context):
        prior = tool_context.state.get(_S_COMMIT_RESULT)
        if prior:
            logger.info(
                "commit_guided_notes: a concurrent call committed this record "
                "as crm_record_id=%s -- replaying its result instead of "
                "staging a duplicate",
                prior.get("crm_record_id"),
            )
            return prior
        return await _commit_guided_notes_locked(tool_context)


async def _commit_guided_notes_locked(tool_context: ToolContext) -> dict:
    """Assemble and commit the guided record. Caller holds the commit lock."""
    event_type = tool_context.state.get(_S_EVENT_TYPE)
    topics = tool_context.state.get(_S_TOPIC_RESULTS) or []
    transcript = tool_context.state.get(_S_TRANSCRIPT) or ""
    summary = tool_context.state.get(_S_SUMMARY) or (
        f"Guided-flow visit log covering {len(topics)} topic(s)."
    )
    planned_topics = tool_context.state.get("planned_topics") or []

    if not event_type or not topics:
        return {
            "status": "error",
            "error": "incomplete_guided_record",
            "instruction_for_model": (
                "The record isn't complete yet (missing event type or "
                "topics). Do not call commit_guided_notes until every "
                "planned topic has a recorded disposition."
            ),
        }

    payload = {
        "event_type": event_type,
        "executive_summary": summary,
        "raw_transcript_backup": transcript,
        "topics": [
            {
                "topic": t["topic"],
                "disposition_code": t.get("disposition_code"),
                "executive_summary": t.get("executive_summary") or "",
                "discussed": t.get("discussed", True),
                "needs_manual_review": t.get("needs_manual_review", False),
            }
            for t in topics
        ],
        "planned_topics": list(planned_topics),
        # Without this the staging endpoint cannot tell which campaign's rules
        # to enforce and falls back to allowing every event type / code.
        "campaign_type": tool_context.state.get(_CAMPAIGN_TYPE_KEY)
        or "standard_sales",
    }
    logger.info("commit_guided_notes payload: %s", payload)

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            stage_resp = await client.post(
                f"{_API_BASE}/api/v1/notes/stage",
                params={"agent_mode": "guided"},
                json=payload,
            )
            # A 422 here is a campaign-rule violation, not an outage -- handled
            # below. Only genuine transport/5xx failures should reach the
            # "try again in a moment" message.
            if stage_resp.status_code not in (200, 422):
                stage_resp.raise_for_status()

            if stage_resp.status_code == 422:
                try:
                    detail = stage_resp.json()
                except ValueError:
                    detail = {}
                problems = detail.get("problems") or [detail.get("detail", "")]
                logger.warning("Guided staging rejected: %s", problems)
                return {
                    "status": "rejected",
                    "problems": problems,
                    "instruction_for_model": (
                        "NOTHING was saved -- the record breaks this "
                        "campaign's rules: "
                        + "; ".join(p for p in problems if p)
                        + ". Allowed event types: "
                        + ", ".join(detail.get("allowed_event_types") or [])
                        + ". Allowed disposition codes: "
                        + ", ".join(
                            str(c)
                            for c in (
                                detail.get("allowed_disposition_codes") or []
                            )
                        )
                        + ". Ask the rep for the correct value out loud, "
                        "re-record that topic's disposition, and try again. "
                        "Never invent a code."
                    ),
                }

            session_id = stage_resp.json()["session_id"]

            commit_resp = await client.post(
                f"{_API_BASE}/api/v1/notes/commit",
                json={
                    "session_id": session_id,
                    "confirmed": True,
                    "agent_mode": "guided",
                    "campaign_type": tool_context.state.get(
                        _CAMPAIGN_TYPE_KEY
                    ),
                    "ws_user_id": tool_context.user_id,
                    "ws_session_id": tool_context.session.id,
                },
            )
            if commit_resp.status_code == 409:
                try:
                    detail = commit_resp.json()
                except ValueError:
                    detail = {}
                missing = detail.get("missing_topics") or []
                logger.warning(
                    "Guided commit blocked -- uncovered topics: %s", missing
                )
                return {
                    "status": "blocked",
                    "error": "incomplete_coverage",
                    "missing_topics": missing,
                    "instruction_for_model": (
                        "NOTHING was saved. These planned topics still have "
                        "no outcome: " + ", ".join(missing) + ". Ask the rep "
                        "about each one out loud, call "
                        "record_topic_disposition for each, then call "
                        "commit_guided_notes again."
                    ),
                }
            commit_resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("commit_guided_notes failed: %s", exc)
        return {
            "status": "error",
            "error": "Could not reach the staging/commit endpoints.",
            "instruction_for_model": (
                "Tell the rep there was a temporary problem saving and to "
                "try again in a moment."
            ),
        }

    data = commit_resp.json()
    manual_review_topics = [
        t["topic"] for t in topics if t.get("needs_manual_review")
    ]
    review_clause = (
        f", though {_join_natural(manual_review_topics)} will need a quick "
        "manual review in the CRM"
        if manual_review_topics
        else ""
    )
    result = {
        "status": data.get("status", "success"),
        "crm_record_id": data.get("crm_record_id"),
        "manual_review_topics": manual_review_topics,
        "closing_statement": (
            "All set. I've saved your post-call summary notes and updated "
            f"the outcomes for your discussion topics{review_clause}. We're "
            "all done here. Have a great day!"
        ),
        "instruction_for_model": (
            "Read the closing_statement verbatim. The session is now "
            "complete."
        ),
    }
    tool_context.state[_S_COMMIT_RESULT] = result
    return result
````
<!-- END: app/voice_notes_agent/tools_guided.py -->

<!-- FILE: app/voice_notes_agent/turn_guard.py -->
````python
"""Code-level backstop against the model committing without a real reply.

Native-audio Live models occasionally race ahead: they speak a self-guessed
confirmation ("Does that sound right? ... Saved!") and call the next tool in
the sequence without ever actually hearing the rep answer. Prompt
instructions alone don't reliably prevent this -- it's model-decoding
non-determinism, not something we can fully control with wording. This adds
a deterministic, code-level guard on top of the prompt rules.

Implementation note: an earlier version of this stored the counter in ADK
session state (``tool_context.state``) written from ``main.py``'s downstream
loop via the raw ``Session.state`` dict. That does NOT reliably work -- the
live-flow's tool-call ``ToolContext.state`` does not see mutations made to
the ``Session`` object from outside ADK's own event-append path, so every
commit was silently reading a stale (always "baseline") value and getting
permanently blocked regardless of a real reply. Instead we track counters in
a plain process-local dict keyed by the WebSocket session_id, which both
``main.py`` (writer, on every genuine finished user transcription) and the
tools (reader) access directly -- no ADK state indirection involved.
"""

from __future__ import annotations

import logging

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)

# session_id -> number of genuine, non-empty, finished user speech turns seen.
_TURN_COUNTS: dict[str, int] = {}
# session_id -> the turn count baseline a reply must exceed to count as new.
_BASELINES: dict[str, int] = {}
# session_id -> True if the agent still owes the rep a spoken readback of the
# real staged confirmation_text (a pre-tool-call filler/guess does NOT clear
# this -- only speech emitted AFTER the tool response counts).
_AWAITING_READBACK: dict[str, bool] = {}
# session_id -> True once we've already injected one auto-continue nudge for
# the current awaiting-readback cycle (prevents nudge spam if the model stays
# silent even after being nudged -- the existing blocked-commit/forced-re-ask
# path remains the fallback in that case).
_NUDGE_SENT: dict[str, bool] = {}


def record_user_turn(session_id: str) -> None:
    """Call from the WS downstream loop on every real finished user turn."""
    _TURN_COUNTS[session_id] = _TURN_COUNTS.get(session_id, 0) + 1


def snapshot(tool_context: ToolContext) -> None:
    """Record the current turn count as the baseline a reply must exceed."""
    session_id = tool_context.session.id
    _BASELINES[session_id] = _TURN_COUNTS.get(session_id, 0)


def has_new_reply(tool_context: ToolContext) -> bool:
    """True if a genuine new user turn arrived since the last ``snapshot()``."""
    session_id = tool_context.session.id
    current = _TURN_COUNTS.get(session_id, 0)
    baseline = _BASELINES.get(session_id, -1)
    result = current > baseline
    if not result:
        # The counter/baseline pair is the only way to explain a refused tool
        # call after the fact, so log it on the blocking path only (DEBUG to
        # keep normal runs quiet).
        logger.debug(
            "turn_guard blocked: session_id=%s current=%d baseline=%d",
            session_id,
            current,
            baseline,
        )
    return result


def mark_awaiting_readback(session_id: str) -> None:
    """Call from the WS downstream loop when a tool whose result MUST be read
    aloud (e.g. stage_visit_notes) returns a response. Some native-audio
    Live model turns speak a guessed filler BEFORE the tool call and then, on
    return, decide they already "said enough" and skip the real readback --
    this flag makes that a hard-detectable condition rather than a silent
    UX bug.
    """
    _AWAITING_READBACK[session_id] = True
    _NUDGE_SENT[session_id] = False


def record_agent_speech(session_id: str, text: str) -> None:
    """Call from the WS downstream loop on every non-empty finished agent
    output turn. Counts as the owed readback having been delivered."""
    if (text or "").strip():
        _AWAITING_READBACK[session_id] = False


def confirmation_was_read(tool_context: ToolContext) -> bool:
    """True unless the agent owes an un-delivered post-stage readback."""
    session_id = tool_context.session.id
    return not _AWAITING_READBACK.get(session_id, False)


def needs_readback_nudge(session_id: str) -> bool:
    """True if the agent closed its turn owing a readback it never gave.

    Native-audio Live models sometimes speak a pre-tool guess, get the real
    tool result back, and then close the turn with zero output -- silently
    waiting for the rep to say *something* (anything) before they'll finally
    speak the real summary. Call this right after a ``turn_complete`` event;
    if it's True, inject a synthetic continuation turn instead of leaving the
    rep sitting in dead air.
    """
    return _AWAITING_READBACK.get(session_id, False) and not _NUDGE_SENT.get(
        session_id, False
    )


def mark_nudge_sent(session_id: str) -> None:
    """Call right after injecting the auto-continue nudge for this session."""
    _NUDGE_SENT[session_id] = True
````
<!-- END: app/voice_notes_agent/turn_guard.py -->

