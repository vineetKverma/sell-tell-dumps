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

from google.adk.tools import ToolContext

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
    return current > baseline


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
