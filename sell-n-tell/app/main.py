"""Agentic AI Voice Notes Logger - FastAPI backend.

Per the "Contract Simplification & Audit Logging" pass: the only
network-reachable surface is the bidirectional WebSocket
(/ws/{user_id}/{session_id}) that bridges the browser microphone to an ADK
Gemini Live agent, plus a health check. Staging, confirmation, the coverage
gate, and commit all happen in-process (see notes_workflow.py and tools.py)
-- there is no REST API to call them from outside, and no self-loopback HTTP
call back into this same process either.

Flow:
    [User dictates] -> [VAD silence stop-trigger] -> [single Mega-Payload tool
    call, in-process] -> [spoken confirmation] -> [user says save or change]
    -> [commit, in-process] -> [spoken closing, Output2 delivered] -> [end]

Audit logging is handled entirely by ADK's BigQueryAgentAnalyticsPlugin
attached to the Runner below -- there is no hand-rolled BigQuery writer in
this codebase anymore.
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import sys
import warnings
from pathlib import Path
import time

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.plugins.bigquery_agent_analytics_plugin import (
    BigQueryAgentAnalyticsPlugin,
    BigQueryLoggerConfig,
)
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Make the agent package importable regardless of launch cwd (so both
# `uvicorn main:app` from app/ and `uvicorn app.main:app` from the repo root
# work).
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables from .env file BEFORE importing the agent.
load_dotenv(Path(__file__).parent / ".env")

# pylint: disable=wrong-import-position
# Contract simplification: db_interface.py / mock_db.py / bigquery_sink.py
# are gone. main.py no longer needs a CRM/workflow import at all -- every
# REST route that used to call into it (config, stage, commit, debug list)
# is deleted; the workflow is called directly and only from tools.py now.
from voice_notes_agent.agent import STATE_PLANNED_TOPICS, agent  # noqa: E402
from voice_notes_agent import turn_guard  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

APP_NAME = "voice-notes-logger"

# VAD silence threshold (ms) -- how long the rep must stay silent before the
# server's automatic VAD finalizes their turn. This MUST be patient:
# dictation naturally has pauses between sentences, and a short threshold
# (the Live API default) chops the dictation into many tiny turns, each of
# which the model tries to answer and gets interrupted by the next sentence
# -- so it never completes a staging call. A ~2.5s window lets the rep speak
# several sentences and only ends the turn when they are genuinely done.
VAD_SILENCE_MS = int(os.getenv("VOICE_NOTES_VAD_SILENCE_MS", "2500"))
if VAD_SILENCE_MS > 2000:
    logger.warning(
        "VAD_SILENCE_MS=%d exceeds Live API cap of 2000ms; clamping to 2000.",
        VAD_SILENCE_MS,
    )
SERVER_VAD_SILENCE_MS = min(VAD_SILENCE_MS, 2000)

app = FastAPI(
    title="Agentic AI Voice Notes Logger API",
    version="2.0.0",
    description=(
        "Dynamic, agentic voice dictation application for field sales reps. "
        "WebSocket + health check only -- see module docstring."
    ),
)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.middleware("http")
async def _no_store_static(request, call_next):
    """Forbid caching of /static so a code change is never invisible.

    app.js is loaded as an ES module, which browsers cache aggressively. A
    deployed change staying invisible for an hour with no error anywhere to
    explain why is a worse failure than any round trip this costs -- these
    are a handful of small files served from localhost.

    Revisit only if this app is ever put behind a CDN, where the right
    answer is content-hashed filenames instead.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


# KNOWN LIMITATION: All ADK sessions live in process memory. A server
# restart drops all sessions. Swapping this for a VertexAiSessionService is
# a separate, heavier decision (real network call on every turn event) and
# is explicitly OUT OF SCOPE for this pass -- see the PR's closing note.
session_service = InMemorySessionService()

# ---------------------------------------------------------------------------
# BigQuery audit logging via ADK's built-in plugin. Replaces the hand-rolled
# bigquery_sink.py writer entirely -- no custom write code, no call site to
# maintain. Attached with no event_allowlist restriction so every LLM/tool
# turn is logged (full lifecycle tracing), not just the commit event.
# session_id, timestamp, and user_id are captured natively by the plugin
# (log_session_metadata, default True) -- nothing in this app needs to pass
# them explicitly.
# ---------------------------------------------------------------------------

_BQ_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
_BQ_DATASET = os.getenv("BQ_ANALYTICS_DATASET_ID", "voice_notes_agent_events")
_BQ_TABLE = os.getenv("BQ_ANALYTICS_TABLE_ID", "agent_events")
_BQ_LOCATION = os.getenv("BQ_ANALYTICS_LOCATION", "US")

# Hard-disabled pending a non-blocking replacement (see PR notes / ticket):
# BigQueryAgentAnalyticsPlugin's first-use setup (auth + gRPC channel +
# dataset/table resolution) runs synchronously inside runner.run_live()'s
# startup path. In this environment that added a ~40s delay before every
# live dictation could connect (measured: ~40s with plugin enabled vs
# ~0.2s disabled). Rather than patch this specific plugin, a separate
# off-request-path traceability mechanism is planned. Default is FALSE
# until that lands -- do not flip this on without re-verifying startup
# latency first.
_BQ_ANALYTICS_ENABLED = (
    os.getenv("BQ_ANALYTICS_ENABLED", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)

_analytics_plugins: list = []
if _BQ_ANALYTICS_ENABLED and _BQ_PROJECT:
    try:
        _analytics_plugins.append(
            BigQueryAgentAnalyticsPlugin(
                project_id=_BQ_PROJECT,
                dataset_id=_BQ_DATASET,
                table_id=_BQ_TABLE,
                location=_BQ_LOCATION,
                config=BigQueryLoggerConfig(
                    event_allowlist=None,
                ),
            )
        )
    except Exception:  # noqa: BLE001 - audit logging must never block startup
        logger.exception(
            "Failed to initialize BigQueryAgentAnalyticsPlugin (dataset=%s); "
            "continuing without audit logging.",
            _BQ_DATASET,
        )
elif not _BQ_ANALYTICS_ENABLED:
    logger.warning(
        "BigQuery audit logging disabled via BQ_ANALYTICS_ENABLED "
        "(see module docstring for why)."
    )
else:
    logger.warning(
        "GOOGLE_CLOUD_PROJECT not set -- BigQuery audit logging disabled."
    )


# Guided flow retired: one Runner, one agent. (Previously a RUNNERS dict
# keyed by agent_mode selected between "implicit" and "guided" runners.)
runner = Runner(
    app_name=APP_NAME,
    agent=agent,
    session_service=session_service,
    plugins=_analytics_plugins,
)


# ============================================================================
# Health check
# ============================================================================


@app.get("/healthz", summary="Health check")
async def healthz() -> dict:
    """Liveness/readiness probe. No auth, no state -- just confirms the
    process is up and serving requests."""
    return {"status": "ok"}


# ============================================================================
# Frontend
# ============================================================================


@app.get("/")
async def root():
    """Serve the dictation UI."""
    return FileResponse(static_dir / "index.html")


# ============================================================================
# WebSocket: browser mic <-> ADK Gemini Live agent
# ============================================================================


def _log_event(event) -> None:
    """Log a concise, audio-free summary of an ADK live event.

    This is the key diagnostic for the "no transcription / no response"
    symptom: it shows exactly what the model emits and when (input/output
    transcription, tool calls, audio, turn boundaries) without flooding the
    log with raw PCM.
    """
    try:
        bits = [f"author={getattr(event, 'author', '?')}"]
        if getattr(event, "input_transcription", None):
            it = event.input_transcription
            bits.append(f"INPUT_TX text={it.text!r} finished={it.finished}")
        if getattr(event, "output_transcription", None):
            ot = event.output_transcription
            bits.append(f"OUTPUT_TX text={ot.text!r} finished={ot.finished}")
        content = getattr(event, "content", None)
        if content and getattr(content, "parts", None):
            for part in content.parts:
                if getattr(part, "function_call", None):
                    bits.append(f"TOOL_CALL={part.function_call.name}")
                elif getattr(part, "function_response", None):
                    bits.append(f"TOOL_RESP={part.function_response.name}")
                elif getattr(part, "inline_data", None):
                    n = len(part.inline_data.data or b"")
                    bits.append(f"AUDIO({n}b)")
                elif getattr(part, "text", None):
                    bits.append(f"TEXT={part.text[:80]!r}")
        if getattr(event, "interrupted", None):
            bits.append("INTERRUPTED")
        if getattr(event, "turn_complete", None):
            bits.append("TURN_COMPLETE")
        logger.info("DOWNSTREAM EVENT | %s", " | ".join(bits))
    except Exception as exc:  # noqa: BLE001 - logging must never break streaming
        logger.warning("Failed to log event: %s", exc)


_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    session_id: str,
    planned_topics: str = "",
    campaign_type: str = "standard_sales"
) -> None:
    
    """Bidirectional streaming session for one dictation conversation.

    ``planned_topics`` is a comma-separated list of the topic labels the rep
    selected during pre-call planning; it is seeded into session state so the
    agent can extract a disposition for each and remind the rep about any it
    never heard.

    ``campaign_type`` is accepted for forward-compatibility but is NOT
    processed by this pass -- it is stored as inert session-state metadata
    only. No validation, config, or disposition-registry logic reads it
    (notes_workflow.get_agent_config()/validate_payload() take no campaign
    parameter). If business later decides per-campaign event-type/
    disposition restrictions are needed again, the value is already flowing
    end-to-end from the frontend and just needs to be read out of session
    state and wired into validate_payload() -- no change to the WS contract,
    the frontend, or this signature is required to enable that later.

    As a side effect, storing it in session state means ADK's
    BigQueryAgentAnalyticsPlugin (log_session_metadata=True by default)
    captures it automatically in the audit trail's attributes for every
    logged event on this session -- so campaign context is NOT lost from
    the audit log even though it has no effect on validation today.
    """
    await websocket.accept()
    if not _SAFE_ID.match(user_id) or not _SAFE_ID.match(session_id):
        await websocket.close(code=1008, reason="Invalid session identifiers")
        return

    planned_topic_list = [
        t.strip() for t in planned_topics.split(",") if t.strip()
    ]

    logger.info(
        "WS connect user_id=%s session_id=%s planned=%s campaign_type=%s (inert)",
        user_id,
        session_id,
        planned_topic_list,
        campaign_type,
    )

    model_name = runner.agent.model
    is_native_audio = "native-audio" in model_name.lower()

    # Patient automatic VAD so multi-sentence DICTATION isn't chopped into tiny
    # turns. With the Live API's short default silence window, every pause
    # between sentences ends the turn, the model starts answering, and the next
    # sentence barges in and interrupts it -- so staging never completes. A
    # longer silence_duration_ms only finalizes once the rep is truly done.
    # (Real-time captions come from the browser SpeechRecognizer, not from this,
    # so a patient server VAD no longer costs us live transcription.)
    realtime_input_config = types.RealtimeInputConfig(
        automatic_activity_detection=types.AutomaticActivityDetection(
            silence_duration_ms=SERVER_VAD_SILENCE_MS,
            prefix_padding_ms=300,
            # LOW start sensitivity requires a clearer, louder, more speech-like
            # signal before a turn is considered "started" -- reduces false
            # triggers from keyboard clicks, mouse clicks, and other transient
            # desk noise that isn't the rep's voice.
            start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
        )
    )

    # Lets the model choose to stay silent / not speak yet instead of always
    # narrating something immediately -- this is the API-level lever for the
    # "don't guess a summary out loud before stage_visit_notes returns" rule
    # in the prompt; the prompt alone wasn't reliably suppressing it.
    proactivity = types.ProactivityConfig(proactive_audio=True)

    if is_native_audio:
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(),
            realtime_input_config=realtime_input_config,
            proactivity=proactivity,
        )
    else:
        # Half-cascade fallback (text responses).
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["TEXT"],
            session_resumption=types.SessionResumptionConfig(),
            realtime_input_config=realtime_input_config,
            proactivity=proactivity,
        )
        logger.warning(
            "Model %s is not native-audio; spoken playback disabled.",
            model_name,
        )

    # Create/reuse the session, seeding planned_topics so the agent's prompt
    # assembly can render the coverage-reminder block. No campaign_type seed
    # anymore -- there is nothing per-campaign left to fetch.
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if not session:
        session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
            state={
                STATE_PLANNED_TOPICS: planned_topic_list,
                "campaign_type":campaign_type,
            },
        )

    live_request_queue = LiveRequestQueue()

    async def upstream_task() -> None:
        """Browser -> LiveRequestQueue (audio chunks + control messages)."""
        audio_chunks = 0
        audio_bytes = 0
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                # Starlette hands back a disconnect message instead of raising
                # -- calling receive() again after this raises a raw
                # RuntimeError, which used to blow up as an ugly "Streaming
                # error" traceback on every normal client disconnect. Raise
                # the proper exception so the existing WebSocketDisconnect
                # handling below (clean log, prompt task cancellation) kicks
                # in immediately instead.
                raise WebSocketDisconnect(code=message.get("code", 1000))

            if "bytes" in message:
                audio_data = message["bytes"]
                audio_chunks += 1
                audio_bytes += len(audio_data)
                # Log periodically so we can confirm mic audio is actually
                # reaching the server (without spamming every chunk).
                if audio_chunks % 50 == 0:
                    logger.info(
                        "Upstream audio: %d chunks, %d bytes total",
                        audio_chunks,
                        audio_bytes,
                    )
                audio_blob = types.Blob(
                    mime_type="audio/pcm;rate=16000", data=audio_data
                )
                live_request_queue.send_realtime(audio_blob)

            elif "text" in message:
                json_message = json.loads(message["text"])
                msg_type = json_message.get("type")

                if msg_type == "text":
                    text = json_message.get("text") or ""
                    logger.info("Upstream text: %r", text)
                    # A typed turn is a genuine rep turn and must count towards
                    # turn_guard, exactly like a spoken one. The audio path
                    # increments the counter from input_transcription events in
                    # downstream_task, but text input produces no transcription
                    # event -- so without this every turn_guard-gated tool
                    # (commit_visit_notes, etc.) is permanently blocked with
                    # "no_reply_heard" in text mode, which is what
                    # scripts/ws_smoke_test.py uses.
                    #
                    # The guard and the send have to agree. Previously only the
                    # counter was gated on strip(), so a blank-but-non-empty
                    # message was still forwarded to the model as a real turn --
                    # the model took its turn, but every turn_guard-gated tool
                    # afterwards reported `no_reply_heard` for a turn that
                    # genuinely happened, and the agent re-asked a question the
                    # rep had already been asked.
                    if text.strip():
                        turn_guard.record_user_turn(session_id)
                        content = types.Content(parts=[types.Part(text=text)])
                        live_request_queue.send_content(content)
                    else:
                        logger.info(
                            "Dropping blank text message (session_id=%s) -- "
                            "not a turn, not forwarded to the model.",
                            session_id,
                        )

    async def downstream_task() -> None:
        """ADK events -> browser."""
        # Tracks whether the model has done ANYTHING (spoken real words or
        # called a tool) since the rep's last genuine turn. Native-audio Live
        # models sometimes go silently inert -- no speech, no tool call --
        # after hearing the rep, apparently waiting for "something more"
        # that never comes. If a turn closes having done neither, nudge
        # instead of leaving dead air until the rep happens to say something
        # else to unstick it.
        responded_since_user_turn = True
        tool_called_since_user_turn = True
        nudge_sent_this_cycle = False
        # Total nudges sent this whole session -- if the model is truly
        # wedged (some sessions have been observed to go permanently silent
        # no matter what's said afterward), stop trying after a few attempts
        # instead of spamming a dead connection forever.
        total_nudges_sent = 0
        _MAX_NUDGES_PER_SESSION = 4

        # Every one of these tools returns an instruction_for_model that MUST
        # be spoken next (a summary, a scripted question, a closing
        # statement...). Native-audio Live models sometimes close the turn
        # with zero output right after the tool call instead of speaking it,
        # leaving dead air the rep has no way to unstick -- see
        # turn_guard.needs_readback_nudge.
        _READBACK_OWED_TOOLS = {
            "stage_visit_notes",
            "commit_visit_notes",
        }

        async def _send_nudge(text: str) -> None:
            # ADK updates the session-resumption handle immediately after
            # turn_complete; injecting content in that exact instant appears
            # to be able to wedge the live session (observed: model goes
            # silent for the rest of the connection, even to unrelated
            # follow-ups). A short delay lets that handshake settle first.
            await asyncio.sleep(0.4)
            live_request_queue.send_content(
                types.Content(parts=[types.Part(text=text)])
            )

        async for event in runner.run_live(
            user_id=user_id,
            session_id=session_id,
            live_request_queue=live_request_queue,
            run_config=run_config,
        ):
            _log_event(event)
            # Bump a real "the rep actually said something new" counter that
            # tools use as a hard backstop against committing/advancing on a
            # self-answered question (see voice_notes_agent.turn_guard). Only
            # a genuine, non-empty, FINISHED transcription of the rep's own
            # speech counts -- not the model's output, not partial chunks.
            it = getattr(event, "input_transcription", None)
            if it is not None and it.finished and (it.text or "").strip():
                turn_guard.record_user_turn(session_id)
                responded_since_user_turn = False
                tool_called_since_user_turn = False
                nudge_sent_this_cycle = False
            # Track whether a tool's spoken summary/question actually got
            # read aloud (see turn_guard.confirmation_was_read docstring) --
            # a pre-tool-call guess must never count as having delivered it.
            content = getattr(event, "content", None)
            if content and getattr(content, "parts", None):
                for part in content.parts:
                    fr = getattr(part, "function_response", None)
                    if fr is not None and fr.name in _READBACK_OWED_TOOLS:
                        turn_guard.mark_awaiting_readback(session_id)
                    if getattr(part, "function_call", None) is not None:
                        tool_called_since_user_turn = True
            ot = getattr(event, "output_transcription", None)
            if ot is not None and ot.finished:
                turn_guard.record_agent_speech(session_id, ot.text)
                if (ot.text or "").strip():
                    responded_since_user_turn = True
            event_json = event.model_dump_json(exclude_none=True, by_alias=True)
            await websocket.send_text(event_json)
            if (
                getattr(event, "turn_complete", None)
                and not responded_since_user_turn
                and not tool_called_since_user_turn
                and not nudge_sent_this_cycle
                and total_nudges_sent < _MAX_NUDGES_PER_SESSION
            ):
                nudge_sent_this_cycle = True
                total_nudges_sent += 1
                logger.warning(
                    "session_id=%s went silent (no speech, no tool call) "
                    "after a rep turn -- injecting auto-continue nudge "
                    "(#%d)",
                    session_id,
                    total_nudges_sent,
                )
                asyncio.ensure_future(
                    _send_nudge(
                        "[SYSTEM] The rep just finished speaking and you "
                        "have not yet responded or called any tool. Act "
                        "now, per your instructions: if they just finished "
                        "dictating their notes, call stage_visit_notes "
                        "with the full extracted payload immediately. "
                        "Otherwise respond to what they said. Do not stay "
                        "silent."
                    )
                )
            # The model sometimes closes its turn right after one of the
            # _READBACK_OWED_TOOLS returns without ever speaking its
            # instruction_for_model out loud -- it treats an earlier
            # pre-tool-call guess as if it already asked the question, then
            # goes silent until the rep says *something* to unstick it.
            # Rather than leave dead air, immediately inject a synthetic
            # continuation turn the moment we see that happen.
            if (
                getattr(event, "turn_complete", None)
                and turn_guard.needs_readback_nudge(session_id)
                and total_nudges_sent < _MAX_NUDGES_PER_SESSION
            ):
                turn_guard.mark_nudge_sent(session_id)
                total_nudges_sent += 1
                asyncio.ensure_future(
                    _send_nudge(
                        "[SYSTEM] Your last tool call has already returned "
                        "an instruction_for_model. You have not yet spoken "
                        "aloud. Speak that response out loud right now, in "
                        "full, per your instructions. Do not wait for "
                        "anything else before doing this."
                    )
                )

    # Start runner.run_live first. Its async generator is responsible for
    # establishing the Gemini Live connection.
    down_task = asyncio.create_task(
        downstream_task(),
        name=f"gemini-downstream-{session_id}",
    )

    # Explicitly yield control so downstream_task can enter runner.run_live()
    # before upstream_task begins draining microphone messages.
    await asyncio.sleep(0)

    up_task = asyncio.create_task(
        upstream_task(),
        name=f"browser-upstream-{session_id}",
    )
    try:
        # `asyncio.gather` does NOT cancel a sibling task when the other one
        # raises -- if we used it here, a client disconnect (upstream raises)
        # would leave `downstream_task` (and its underlying Gemini Live
        # session) running orphaned forever, silently reconnecting to Vertex
        # AI on every "go away" refresh signal with no consumer. `wait` +
        # explicit cancellation of whatever's still pending avoids that leak.
        done, pending = await asyncio.wait(
            {up_task, down_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except RuntimeError as exc:
        # Starlette raises RuntimeError("Cannot call 'receive' once a disconnect
        # message has been received.") when the browser closes the socket while
        # upstream_task is blocked on websocket.receive(). This is a clean
        # client-side disconnect, not a server error -- log at INFO level.
        if "disconnect" in str(exc).lower():
            logger.info("Client disconnected (upstream_task): %s", exc)
        else:
            logger.error("Streaming error: %s", exc, exc_info=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("Streaming error: %s", exc, exc_info=True)
    finally:
        live_request_queue.close()
