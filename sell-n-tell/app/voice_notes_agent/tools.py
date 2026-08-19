"""ADK function-call tools for the Voice Notes Logger agent.

True to the API spec, these tools do NOT touch the data store directly: they
issue real HTTP calls to the FastAPI ``/api/v1`` endpoints (the same endpoints
an external client would use). The base URL is configurable via the
``VOICE_NOTES_API_BASE`` environment variable.

Two tools cover the whole flow:

* ``stage_visit_notes`` -- the single "Mega-Payload" function call the model
  emits after the user finishes dictating (Step 3/4). It POSTs to
  ``/api/v1/notes/stage`` and returns the natural-language confirmation string.
  Re-calling it with corrected fields handles the correction branch (Step 5B).
* ``commit_visit_notes`` -- POSTs to ``/api/v1/notes/commit`` once the user
  gives positive confirmation (Step 5A), returning the closing statement.
"""

from __future__ import annotations

import json
import logging
import os

import httpx
from google.adk.tools import ToolContext

from .mock_db import DiscussionTopic, VALID_DISPOSITION_CODES
from . import turn_guard

logger = logging.getLogger(__name__)

_API_BASE = os.getenv("VOICE_NOTES_API_BASE", "http://localhost:8000")
_HTTP_TIMEOUT = 15.0

# Session-state key holding the CRM session_id returned by the staging endpoint.
_STAGED_SESSION_KEY = "crm_staged_session_id"
_LAST_CONFIRMATION_KEY = "crm_last_confirmation_text"
# Written by agent.load_campaign_config (kept as a literal to avoid a circular
# import back into the agent module).
_AGENT_CONFIG_KEY = "agent_config"
_CAMPAIGN_TYPE_KEY = "campaign_type"


def _allowed_codes(tool_context: ToolContext) -> set[int]:
    """Disposition codes legal for THIS session's campaign.

    Falls back to the full registry only if the dynamic config never loaded --
    validating against the global list would defeat the purpose, but a failed
    config fetch must not block the rep entirely (the REST layer re-validates
    campaign rules regardless, so nothing illegal can be staged).
    """
    config = tool_context.state.get(_AGENT_CONFIG_KEY) or {}
    registry = config.get("disposition_registry") or []
    codes = {int(rule["code"]) for rule in registry if "code" in rule}
    return codes or set(VALID_DISPOSITION_CODES)


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
        # API schema would reject it. Drop it and let the discussed-topic
        # check below ask the model to re-map.
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
              is present in every campaign registry. Never pick a nearby code
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
    valid_codes = _allowed_codes(tool_context)
    topic_list, problems = _normalize_topics(topics, valid_codes)
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
                + ", ".join(str(c) for c in sorted(valid_codes))
                + "), and `executive_summary` (1-2 sentences). Do not "
                "pass topics as plain strings."
            ),
        }

    # Planned topics were seeded into session state at connect time. They drive
    # the coverage check (which planned topics still need an outcome).
    planned_topics = tool_context.state.get("planned_topics") or []

    payload = {
        "caller_session_id": tool_context.session.id,
        "event_type": event_type,
        "executive_summary": executive_summary,
        "raw_transcript_backup": raw_transcript_backup,
        "topics": topic_list,
        "planned_topics": list(planned_topics),
        # Without this the staging endpoint cannot tell which campaign's rules
        # to enforce, and falls back to allowing every event type / code.
        "campaign_type": tool_context.state.get(_CAMPAIGN_TYPE_KEY)
        or "standard_sales",
    }
    logger.info("stage_visit_notes tool invoked: %s", payload)

    # If notes were already staged this session, this call is a correction:
    # pass the prior session id so the backend reads back only the changes.
    previous_session_id = tool_context.state.get(_STAGED_SESSION_KEY)
    params = (
        {"previous_session_id": previous_session_id}
        if previous_session_id
        else None
    )

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{_API_BASE}/api/v1/notes/stage", json=payload, params=params
            )
    except httpx.HTTPError as exc:
        logger.error("Staging request failed: %s", exc)
        return {
            "status": "error",
            "error": "Could not reach the staging endpoint.",
            "instruction_for_model": (
                "Tell the user there was a temporary problem saving and to try "
                "again in a moment."
            ),
            "ui_event": "tool_error",
        }

    if resp.status_code == 422:
        # Campaign-rule violation (illegal event type or disposition code).
        # Never silently accept it and never guess a replacement -- hand the
        # model the legal values and make it re-map or ask the rep.
        try:
            detail = resp.json()
        except ValueError:
            detail = {"detail": resp.text[:300]}
        problems = detail.get("problems") or [detail.get("detail", "")]
        allowed_codes = detail.get("allowed_disposition_codes") or []
        allowed_events = detail.get("allowed_event_types") or []
        logger.warning("Staging rejected by campaign rules: %s", problems)
        return {
            "status": "rejected",
            "problems": problems,
            "instruction_for_model": (
                "The record was REJECTED and nothing was saved: "
                + "; ".join(p for p in problems if p)
                + ". This campaign only allows event types ["
                + ", ".join(allowed_events)
                + "] and disposition codes ["
                + ", ".join(str(c) for c in allowed_codes)
                + "]. Re-map to the closest ALLOWED value and call "
                "stage_visit_notes again. Never invent a code. If no allowed "
                "code genuinely fits what the rep said, do not guess -- ask "
                "the rep out loud which outcome applies, then re-stage."
            ),
        }

    if resp.status_code != 200:
        logger.error(
            "Staging failed: %s %s", resp.status_code, resp.text[:300]
        )
        return {
            "status": "error",
            "error": f"Staging endpoint returned {resp.status_code}",
            "detail": resp.text[:300],
        }

    data = resp.json()
    # Persist the CRM session id so the commit tool can reference it later.
    tool_context.state[_STAGED_SESSION_KEY] = data["session_id"]
    tool_context.state["last_staged_id"] = data["session_id"]

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
        A dict containing ``closing_statement`` -- the exact sentence to read
        back to the user before ending the session.
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

    body = {
        "session_id": session_id,
        "confirmed": True,
        "agent_mode": "implicit",
        "campaign_type": tool_context.state.get("campaign_type"),
        "ws_user_id": tool_context.user_id,
        "ws_session_id": tool_context.session.id,
    }
    logger.info("commit_visit_notes tool invoked: %s", body)

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{_API_BASE}/api/v1/notes/commit", json=body
            )
    except httpx.HTTPError as exc:
        logger.error("Commit request failed: %s", exc)
        return {
            "status": "error",
            "error": "Could not reach the commit endpoint.",
            "instruction_for_model": (
                "Tell the user there was a temporary problem saving and to try "
                "again in a moment."
            ),
            "ui_event": "tool_error",
        }

    if resp.status_code == 409:
        # Coverage gate: planned topics still have no outcome. Nothing was
        # written. Collect the outcomes and re-stage before trying again.
        try:
            detail = resp.json()
        except ValueError:
            detail = {}
        missing = detail.get("missing_topics") or []
        logger.warning("Commit blocked -- uncovered planned topics: %s", missing)
        return {
            "status": "blocked",
            "error": "incomplete_coverage",
            "missing_topics": missing,
            "instruction_for_model": (
                "NOTHING was saved. These planned topics still have no "
                "outcome: " + ", ".join(missing) + ". Say out loud that you "
                "still need those before saving, and ask the rep what "
                "happened with them. When they answer, call stage_visit_notes "
                "again with the FULL payload including an entry for each "
                "(discussed=true with a disposition_code if they give an "
                "outcome, or discussed=false with their reason if they "
                "skipped it), then commit."
            ),
        }

    if resp.status_code != 200:
        logger.error(
            "Commit failed: %s %s", resp.status_code, resp.text[:300]
        )
        return {
            "status": "error",
            "error": f"Commit endpoint returned {resp.status_code}",
            "detail": resp.text[:300],
        }

    data = resp.json()
    # Clear staged session so a fresh dictation starts clean.
    tool_context.state[_STAGED_SESSION_KEY] = None
    return {
        "status": data.get("status", "success"),
        "crm_record_id": data.get("crm_record_id"),
        "closing_statement": data.get("closing_statement"),
        "instruction_for_model": (
            "Read the closing_statement to the user verbatim. The session is "
            "now complete."
        ),
    }
