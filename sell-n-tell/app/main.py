"""Agentic AI Voice Notes Logger - FastAPI backend.

Implements the API spec (config / stage / commit) plus a bidirectional
WebSocket that bridges the browser microphone to an ADK Gemini Live agent.

Flow:
    [User dictates] -> [VAD silence stop-trigger] -> [single Mega-Payload tool
    call -> POST /notes/stage] -> [spoken confirmation] -> [user says save or
    change] -> [POST /notes/commit] -> [spoken closing] -> [end]
"""

import asyncio
import contextlib
import json
import logging
import os
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

# Make the agent package importable regardless of launch cwd (so both
# `uvicorn main:app` from app/ and `uvicorn app.main:app` from the repo root
# work).
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables from .env file BEFORE importing the agent.
load_dotenv(Path(__file__).parent / ".env")

# pylint: disable=wrong-import-position
from voice_notes_agent import bigquery_sink, mock_db  # noqa: E402
from voice_notes_agent.agent import (  # noqa: E402
    STATE_CAMPAIGN_TYPE,
    STATE_PLANNED_TOPICS,
    agent,
)
from voice_notes_agent.agent_guided import agent_guided  # noqa: E402
from voice_notes_agent.mock_db import DiscussionTopic  # noqa: E402
from voice_notes_agent import turn_guard  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

APP_NAME = "voice-notes-logger"

# VAD silence threshold (ms) -- how long the rep must stay silent before the
# server's automatic VAD finalizes their turn (spec Step 2: 2.5-3.0s stop
# trigger). This MUST be patient: dictation naturally has pauses between
# sentences, and a short threshold (the Live API default) chops the dictation
# into many tiny turns, each of which the model tries to answer and gets
# interrupted by the next sentence -- so it never completes a staging call.
# A ~2.5s window lets the rep speak several sentences and only ends the turn
# when they are genuinely done. The browser mirrors this for its UI countdown.
VAD_SILENCE_MS = int(os.getenv("VOICE_NOTES_VAD_SILENCE_MS", "2500"))
SERVER_VAD_SILENCE_MS = VAD_SILENCE_MS

app = FastAPI(
    title="Agentic AI Voice Notes Logger API",
    version="1.0.0",
    description=(
        "Dynamic, agentic voice dictation application for field sales reps."
    ),
)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

session_service = InMemorySessionService()
# One Runner per solution so both flows can be compared side by side behind
# the `agent_mode` toggle: "implicit" (single Mega-Payload extraction, VAD
# auto-stop) vs. "guided" (explicit turn-by-turn script).
RUNNERS = {
    "implicit": Runner(
        app_name=APP_NAME, agent=agent, session_service=session_service
    ),
    "guided": Runner(
        app_name=APP_NAME, agent=agent_guided, session_service=session_service
    ),
}


# ============================================================================
# Pydantic models (mirror the OpenAPI spec components)
# ============================================================================


class DispositionRule(BaseModel):
    code: int
    label: str
    mapping_keywords: list[str] = Field(default_factory=list)


class AgentConfigResponse(BaseModel):
    campaign_type: str
    system_instruction_template: str
    allowed_event_types: list[str]
    disposition_registry: list[DispositionRule]


class StagedVisitPayload(BaseModel):
    event_type: str = Field(
        ...,
        description="Meeting | On-site visit | Phone Call",
    )
    executive_summary: str = Field(
        ...,
        description="A condensed 2-sentence summary of the overall call.",
    )
    raw_transcript_backup: str
    topics: list[DiscussionTopic] = Field(
        ...,
        min_length=1,
        description="One or more discussion topics, each with its own "
        "disposition_code and executive_summary.",
    )
    planned_topics: list[str] = Field(
        default_factory=list,
        description="The pre-call planned topics the rep selected. Drives the "
        "coverage reminder for any topic that was not addressed.",
    )
    campaign_type: str = Field(
        default="standard_sales",
        description="Campaign this record is staged under. Determines which "
        "event types and disposition codes are legal -- without it the "
        "endpoint cannot enforce campaign rules.",
    )


class StageResponse(BaseModel):
    session_id: str
    confirmation_text: str
    missing_topics: list[str] = Field(default_factory=list)
    all_topics_covered: bool = True


class PlannedTopic(BaseModel):
    id: str
    label: str


class PlannedTopicCatalogResponse(BaseModel):
    topics: list[PlannedTopic]


class CommitRequest(BaseModel):
    session_id: str
    confirmed: bool
    agent_mode: str = "implicit"
    campaign_type: str | None = None
    ws_user_id: str | None = None
    ws_session_id: str | None = None


class CommitResponse(BaseModel):
    status: str
    crm_record_id: str | None = None
    closing_statement: str


# ============================================================================
# REST API (the spec)
# ============================================================================


@app.get(
    "/api/v1/config/agent-schema",
    response_model=AgentConfigResponse,
    summary="Fetch Dynamic Agent Config & Rules",
)
async def get_agent_schema(
    campaign_type: str = Query(default="standard_sales"),
) -> AgentConfigResponse:
    """Dynamically inject required fields, tool params, and disposition codes."""
    config = mock_db.get_agent_config(campaign_type)
    return AgentConfigResponse(**config)


@app.get(
    "/api/v1/config/planned-topics",
    response_model=PlannedTopicCatalogResponse,
    summary="Fetch selectable pre-call planned topics",
)
async def get_planned_topics() -> PlannedTopicCatalogResponse:
    """Return the catalog of topics a rep can plan to discuss before a call."""
    return PlannedTopicCatalogResponse(
        topics=mock_db.get_planned_topic_catalog()
    )


@app.post(
    "/api/v1/notes/stage",
    response_model=StageResponse,
    summary="Stage Extracted Structured Notes",
)
async def stage_notes(
    payload: StagedVisitPayload,
    previous_session_id: str | None = Query(default=None),
    agent_mode: str = Query(default="implicit"),
) -> StageResponse | JSONResponse:
    """Stage notes parsed by the Gemini agent and return a confirmation string.

    When ``previous_session_id`` is supplied (a correction), the confirmation
    reads back only what changed relative to that prior staged record.

    ``agent_mode`` decides whether a ``discussed=false`` topic counts as
    coverage on a FIRST stage -- see the allow_skips note in mock_db.stage_notes.
    Guided asks about every topic before recording a skip; implicit does not.
    """
    data = payload.model_dump()
    planned_topics = data.pop("planned_topics", [])
    campaign_type = data.pop("campaign_type", None)

    # Validate against THIS campaign's rules, not the global registry. The
    # campaign config is injected into the agent's prompt, but a prompt only
    # asks -- an illegal event type or disposition code that slips through
    # would be read back to the rep as if it were valid ("silent wrong code").
    problems = mock_db.validate_against_campaign(data, campaign_type)
    if problems:
        logger.warning(
            "Staging rejected for campaign_type=%s: %s", campaign_type, problems
        )
        config = mock_db.get_agent_config(campaign_type)
        return JSONResponse(
            status_code=422,
            content={
                "detail": "; ".join(problems),
                "problems": problems,
                "campaign_type": config["campaign_type"],
                "allowed_event_types": config["allowed_event_types"],
                "allowed_disposition_codes": [
                    rule["code"] for rule in config["disposition_registry"]
                ],
            },
        )

    result = mock_db.stage_notes(
        data,
        previous_session_id=previous_session_id,
        planned_topics=planned_topics,
        campaign_type=campaign_type,
        agent_mode=agent_mode,
    )
    return StageResponse(**result)


@app.post(
    "/api/v1/notes/commit",
    response_model=CommitResponse,
    summary="Commit Staged Payload to CRM",
)
async def commit_notes(body: CommitRequest) -> CommitResponse | JSONResponse:
    """Push the staged payload to the target CRM instance."""
    try:
        result = mock_db.commit_notes(
            body.session_id,
            body.confirmed,
            agent_mode=body.agent_mode,
            campaign_type=body.campaign_type,
            ws_user_id=body.ws_user_id,
            ws_session_id=body.ws_session_id,
        )
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except mock_db.IncompleteCoverageError as exc:
        # The rep planned topics that still have no outcome. Refuse the write
        # and hand back exactly which ones, so the caller can collect them.
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "error": "incomplete_coverage",
                "missing_topics": exc.missing_topics,
            },
        )

    record = result.pop("_record", None)
    if record is not None:
        disposition_config = mock_db.get_agent_config(
            body.campaign_type or "standard_sales"
        )
        try:
            await asyncio.to_thread(
                bigquery_sink.insert_call_record, record, disposition_config
            )
        except Exception:  # noqa: BLE001 - a BQ hiccup must never fail commit
            logger.exception(
                "BigQuery sink raised for crm_record_id=%s",
                record.get("crm_record_id"),
            )
    return CommitResponse(**result)


@app.get("/api/v1/notes/committed", summary="List committed CRM records (debug)")
async def list_committed() -> dict:
    """Inspect the mock CRM table contents (handy for demos / debugging)."""
    return {"records": mock_db.list_committed()}


@app.get("/api/v1/client-config", summary="Frontend runtime config")
async def client_config() -> dict:
    """Expose runtime knobs to the browser (e.g. the VAD silence threshold)."""
    return {"vad_silence_ms": SERVER_VAD_SILENCE_MS}


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

    This is the key diagnostic for the "no transcription / no response" symptom:
    it shows exactly what the model emits and when (input/output transcription,
    tool calls, audio, turn boundaries) without flooding the log with raw PCM.
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


@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    session_id: str,
    campaign_type: str = "standard_sales",
    planned_topics: str = "",
    agent_mode: str = "implicit",
) -> None:
    """Bidirectional streaming session for one dictation conversation.

    ``planned_topics`` is a comma-separated list of the topic labels the rep
    selected during pre-call planning; it is seeded into session state so the
    agent can extract a disposition for each and remind the rep about any it
    never heard.

    ``agent_mode`` selects which solution handles this session: "implicit"
    (single Mega-Payload extraction, VAD auto-stop -- default) or "guided"
    (explicit turn-by-turn script). Unknown values fall back to "implicit".
    """
    planned_topic_list = [
        t.strip() for t in planned_topics.split(",") if t.strip()
    ]
    if agent_mode not in RUNNERS:
        logger.warning(
            "Unknown agent_mode=%r, falling back to 'implicit'", agent_mode
        )
        agent_mode = "implicit"
    runner = RUNNERS[agent_mode]
    logger.info(
        "WS connect user_id=%s session_id=%s campaign_type=%s planned=%s "
        "agent_mode=%s",
        user_id,
        session_id,
        campaign_type,
        planned_topic_list,
        agent_mode,
    )
    await websocket.accept()

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

    # Create/reuse the session, seeding campaign_type so the agent's
    # before_agent_callback can dynamically fetch the matching config.
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if not session:
        session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
            state={
                STATE_CAMPAIGN_TYPE: campaign_type,
                STATE_PLANNED_TOPICS: planned_topic_list,
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
                    # (commit_visit_notes, set_event_type,
                    # record_topic_disposition, choose_post_dictation_action)
                    # is permanently blocked with "no_reply_heard" in text
                    # mode, which is what scripts/ws_smoke_test.py uses.
                    if text.strip():
                        turn_guard.record_user_turn(session_id)
                    content = types.Content(parts=[types.Part(text=text)])
                    live_request_queue.send_content(content)

    async def downstream_task() -> None:
        """ADK events -> browser."""
        # Tracks whether the model has done ANYTHING (spoken real words or
        # called a tool) since the rep's last genuine turn. Native-audio Live
        # models sometimes go silently inert -- no speech, no tool call --
        # after hearing the rep, apparently waiting for "something more"
        # that never comes (e.g. guided Stage 1 not calling capture_dictation
        # after a dictation pause with no explicit end phrase). If a turn
        # closes having done neither, nudge instead of leaving dead air until
        # the rep happens to say something else to unstick it.
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
            "capture_dictation",
            "choose_post_dictation_action",
            "set_event_type",
            "record_topic_disposition",
            "commit_guided_notes",
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
                        "dictating their notes, call capture_dictation "
                        "with their full transcript immediately. Otherwise "
                        "respond to what they said. Do not stay silent."
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

    up_task = asyncio.create_task(upstream_task())
    down_task = asyncio.create_task(downstream_task())
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
    except Exception as exc:  # noqa: BLE001
        logger.error("Streaming error: %s", exc, exc_info=True)
    finally:
        live_request_queue.close()
