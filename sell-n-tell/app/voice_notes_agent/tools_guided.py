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


def _reset_guided_state(tool_context: ToolContext) -> None:
    """Discard everything captured so far (a full re-record restart)."""
    tool_context.state[_S_TRANSCRIPT] = None
    tool_context.state[_S_SUMMARY] = None
    tool_context.state[_S_EVENT_TYPE] = None
    tool_context.state[_S_TOPIC_RESULTS] = []
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

    results = tool_context.state.get(_S_TOPIC_RESULTS) or []
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
    prior = tool_context.state.get(_S_COMMIT_RESULT)
    if prior:
        logger.info(
            "commit_guided_notes: already committed as crm_record_id=%s -- "
            "replaying the original result instead of re-staging",
            prior.get("crm_record_id"),
        )
        return prior

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
            # agent_mode=guided: a discussed=false topic here was recorded by
            # record_topic_disposition, which only runs after a genuine rep
            # reply -- so it counts as coverage on this first (and only)
            # staging call. Without it the commit 409s on a topic the rep was
            # just asked about and the flow deadlocks.
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
