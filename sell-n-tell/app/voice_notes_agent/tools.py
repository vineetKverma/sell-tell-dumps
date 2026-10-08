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
_CLOSING_STATEMENT = notes_workflow._CLOSING_STATEMENT

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
            "On-site visit", or "Phone Call", chosen by the event-type rule
            in your instructions (Phone Call only for a call; Meeting when a
            person is mentioned; otherwise On-site visit).
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
    # Dual-Sync (AIML-2807 & 2743): Persist full staged record to ADK session
    # state so it survives process restarts and can rehydrate on reconnect.
    raw_staged = notes_workflow.get_staged(data["session_id"])
    if raw_staged:
        tool_context.state["staged_record"] = dict(raw_staged)

    # Clear prior commit tracking so a newly staged note in the same session
    # is never blocked by or replays an earlier visit's commit result:
    tool_context.state["commit_result"] = None
    tool_context.state["committed"] = False


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
    staged_record = tool_context.state.get("staged_record")
    if not session_id and not staged_record:
        logger.warning("commit_visit_notes called with no staged session")
        return {
            "status": "error",
            "error": "no_staged_notes",
            "instruction_for_model": (
                "There are no staged notes yet. Ask the user to dictate their "
                "notes first."
            ),
        }
    if not session_id and staged_record:
        session_id = staged_record.get("session_id") or tool_context.session.id

    # If the process restarted or redeployed, _STAGED_NOTES in RAM is empty,
    # but tool_context.state["staged_record"] persisted in VertexAiSessionService.
    # Rehydrate it back into _STAGED_NOTES now so gates and commits work seamlessly.
    if notes_workflow.get_staged(session_id) is None and staged_record:
        logger.info(
            "commit_visit_notes: rehydrating _STAGED_NOTES for session_id=%s from session state",
            session_id,
        )
        notes_workflow.rehydrate_staged(session_id, staged_record)


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
        # Arm the baseline so the upcoming rep confirmation will satisfy has_new_reply
        turn_guard.snapshot(tool_context)
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

    closing = getattr(result, "closing_statement", _CLOSING_STATEMENT) if not isinstance(result, dict) else result.get("closing_statement", _CLOSING_STATEMENT)
    if isinstance(result, dict):
        # confirmed=False path returns {"status": "cancelled", ...} instead
        # of a CommitResult -- not reachable from this tool (we always pass
        # confirmed=True), but handled rather than assumed away.
        return {
            **result,
            "instruction_for_model": (
                f"Say out loud to the user right now, verbatim: \"{closing}\". "
                "Do not stay silent. You MUST speak this sentence aloud before ending."
            ),
        }

    commit_payload = (
        result.model_dump() if hasattr(result, "model_dump") else dict(result)
    )
    # Persist commit result to tool_context.state so restarts and reconnects survive
    tool_context.state["commit_result"] = commit_payload
    tool_context.state["committed"] = True

    # Dual-Sync: update staged_record in session state so rehydration across
    # process restart carries committed=True and commit_result intact.
    staged_rec = notes_workflow.get_staged(session_id)
    if staged_rec:
        tool_context.state["staged_record"] = dict(staged_rec)

    # Clear staged session so a fresh dictation starts clean.
    tool_context.state[_STAGED_SESSION_KEY] = None

    # Output2: the commit tool's own, authoritative response -- the UI
    # renders from this directly instead of reconstructing it from earlier
    # streamed tool-call arguments.
    return {
        "status": "success",
        **commit_payload,
        "instruction_for_model": (
            f"Say out loud to the user right now, verbatim: \"{closing}\". "
            "Do not stay silent. You MUST speak this sentence aloud before ending."
        ),
    }
