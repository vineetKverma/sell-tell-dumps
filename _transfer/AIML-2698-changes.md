# AIML-2698 changed files

<!-- FILE: app/main.py -->
````python
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
) -> StageResponse | JSONResponse:
    """Stage notes parsed by the Gemini agent and return a confirmation string.

    When ``previous_session_id`` is supplied (a correction), the confirmation
    reads back only what changed relative to that prior staged record.
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
                    logger.info("Upstream text: %r", json_message.get("text"))
                    content = types.Content(
                        parts=[types.Part(text=json_message["text"])]
                    )
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
````
<!-- END: app/main.py -->

<!-- FILE: app/voice_notes_agent/mock_db.py -->
````python

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
        ...,
        description="Condensed 1-2 sentence summary of THIS topic",
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

_DISPOSITION_BY_CODE: dict[int, dict[str, Any]] = {
    int(rule["code"]): rule for rule in _FULL_DISPOSITION_REGISTRY
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

PLANNED_TOPIC_CATALOG: list[dict[str, str]] = [
    {"id": "new_product_intro", "label": "New product introduction"},
    {"id": "pricing_promotions", "label": "Pricing & promotions"},
    {"id": "contract_renewal", "label": "Contract / agreement renewal"},
    {"id": "reorder_replenishment", "label": "Reorder & replenishment"},
    {"id": "upsell_crosssell", "label": "Upsell & cross-sell opportunities"},
    {"id": "competitive_landscape", "label": "Competitive landscape"},
    {"id": "account_review", "label": "Account satisfaction & service review"},
    {"id": "delivery_logistics", "label": "Delivery & logistics"},
    {"id": "payment_terms", "label": "Payment terms & credit"},
    {"id": "brand_compliance", "label": "Marketing & brand compliance"},
]


def get_planned_topic_catalog() -> list[dict[str, str]]:
    """Return the selectable pre-call planned-topic catalog (copy)."""
    return [dict(t) for t in PLANNED_TOPIC_CATALOG]


def _topic_key(label: str) -> str:
    """Normalize a topic label for tolerant matching."""
    return (label or "").strip().lower()


def compute_missing_topics(
    planned_topics: list[str], staged_topics: list[dict[str, Any]]
) -> list[str]:
    """Return planned topics that have no corresponding entry in the payload.

    A planned topic is considered *covered* once it appears in the staged
    ``topics`` list (whether or not it was actually discussed -- a topic the
    rep explicitly skipped still counts as addressed). Matching is tolerant of
    case/whitespace and falls back to substring overlap so the model doesn't
    have to reproduce the catalog label verbatim.
    """
    covered_keys = {_topic_key(t.get("topic", "")) for t in staged_topics}
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
        "disposition_registry": [
            dict(rule) for rule in config["disposition_registry"]
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
        # A planned-but-not-discussed topic legitimately carries no code.
        if code is None:
            if topic.get("discussed", True):
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
    payload: dict[str, Any], planned_topics: list[str] | None = None
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

    missing = compute_missing_topics(planned_topics or [], topics)

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
    previous = (
        _STAGED_NOTES.get(previous_session_id) if previous_session_id else None
    )
    if previous:
        confirmation_text = build_change_confirmation(
            previous["payload"], payload, planned_topics
        )
    else:
        confirmation_text = build_confirmation_text(payload, planned_topics)

    missing = compute_missing_topics(planned_topics, payload.get("topics", []))
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
        planned_topics, record["payload"].get("topics", [])
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
````
<!-- END: app/voice_notes_agent/mock_db.py -->

<!-- FILE: app/voice_notes_agent/tools.py -->
````python
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

        if not topic:
            problems.append(f"topic #{idx + 1} is missing a subject label")
        # A discussed topic needs a valid disposition; a not-discussed planned
        # topic is allowed to have none (it's awaiting the rep's feedback).
        if discussed and code is None:
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
            - discussed: true if the rep covered it; false for a planned topic
              they did not get to (then disposition_code may be omitted).

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
````
<!-- END: app/voice_notes_agent/tools.py -->

<!-- FILE: docs/AIML-2698-experiments.md -->
````markdown
# AIML-2698 â€” Reproduction Log

Evidence for **Close Implicit/Guided Agent Gaps (Disposition + State Correctness)**.
Satisfies AC#1 ("Repro scripts for the log failures above").

Every experiment below runs against the **REST layer only** â€” no microphone, no
Gemini, no Vertex AI, no BigQuery. The failures are in application logic, not in
the model, so they reproduce deterministically and cost nothing to run.

---

## Test environment

| Setting | Value | Why |
|---|---|---|
| Branch | `feature/AIML-2698-disposition-state-correctness` | cut from `feature/AIML-2130-guided-flow` @ `3ecd956` |
| Server | `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` | |
| `VOICE_NOTES_BQ_ENABLED` | `false` | BigQuery writes disabled â€” keeps logs clean, removes an external dependency |
| AI / Vertex | **not used** | every experiment hits REST endpoints directly |
| Store | in-memory (`mock_db.py`) | resets on server restart |

> Because the store is in-memory, restarting the server clears all staged and
> committed records. Re-run the experiments after any restart.

### Reference: campaign rules

Retrieved from `GET /api/v1/config/agent-schema?campaign_type=...`

| Campaign | Allowed event types | Allowed disposition codes |
|---|---|---|
| `standard_sales` | Meeting, On-site visit, Phone Call | 1â€“10 (all) |
| `renewals` | Phone Call, Meeting | 2, 3, 5, 8, 9 |
| `enterprise_field` | Meeting, On-site visit | 1, 2, 4, 5, 8 |

Disposition registry (standard_sales): 1 Create Opportunity Â· 2 Order Placed Â·
3 No current need â€“ revisit Â· 4 Contracted to buy from competitor Â· 5 Buying
from preferred vendor already Â· 6 Not a product/service they use Â· 7 Does not
meet brand guidelines Â· 8 Pricing concerns Â· 9 Recently discussed Â·
10 Customer recently purchased related item(s)

---

## Experiment 1 â€” Commit succeeds with an uncovered planned topic

**Ticket AC:** #3 â€” *"Commit never succeeds without a valid stage + full
planned-topic coverage"*

**Hypothesis:** `missing_topics` is computed and reported but never enforced, so
a record can be committed while a planned topic has no outcome.

### Steps

```powershell
# Stage a record that covers only 1 of 2 planned topics ("Pricing" omitted).
$body = @{
  event_type = "On-site visit"
  executive_summary = "Visited Acme. Renewal on track; pricing pushback."
  raw_transcript_backup = "Just left Acme..."
  topics = @(
    @{ topic = "Contract / agreement renewal"; disposition_code = 3; executive_summary = "Wants to re-sign."; discussed = $true }
  )
  planned_topics = @("Contract / agreement renewal", "Pricing")
} | ConvertTo-Json -Depth 5

$stage = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/notes/stage" -Body $body -ContentType "application/json"
$stage | ConvertTo-Json -Depth 5

# Commit it anyway.
$commit = @{ session_id = $stage.session_id; confirmed = $true; agent_mode = "implicit"; campaign_type = "standard_sales" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/notes/commit" -Body $commit -ContentType "application/json"

Invoke-RestMethod "http://localhost:8000/api/v1/notes/committed" | ConvertTo-Json -Depth 5
```

### Result â€” **FAILS (bug confirmed)**

Staging correctly detects the gap:

```json
{
  "session_id": "04038b1c-98ef-4db0-8534-e433a5089b6a",
  "confirmation_text": "... you'd planned to cover Pricing, but I didn't hear an outcome on that topic. What happened with Pricing? ...",
  "missing_topics": ["Pricing"],
  "all_topics_covered": false
}
```

Commit accepts it regardless:

```
status   crm_record_id    closing_statement
success  CRM-B598122C53   Saved successfully. Have a great day!
```

And the committed CRM record carries the incompleteness as stored data:

```json
{
  "crm_record_id": "CRM-B598122C53",
  "planned_topics": ["Contract / agreement renewal", "Pricing"],
  "missing_topics": ["Pricing"],
  "committed_at": "2026-08-09T12:39:43.397172+00:00"
}
```

### Analysis

`mock_db.commit_notes` calls `compute_missing_topics` and writes the result onto
the committed record, but never branches on it. No layer treats it as a gate:

- `tools.py :: commit_visit_notes` â€” checks staged session + turn guards only
- `main.py :: commit_notes` â€” passes straight through
- `mock_db.py :: commit_notes` â€” computes, stores, commits

The only thing discouraging a premature save is prompt text
(`instruction_for_model`: *"Do NOT save yet"*), which is model-dependent and
therefore not a guarantee.

---

## Experiment 2 â€” Campaign rules are not enforced

**Ticket AC:** #2 â€” *"100% valid disposition codes on golden scripts for both
modes (no invented codes)"*

**Hypothesis:** validation uses the global registry rather than the active
campaign's, so a campaign-illegal event type and disposition code are accepted.

### Steps

```powershell
# renewals allows only event types [Phone Call, Meeting] and codes [2,3,5,8,9].
# This payload violates BOTH: "On-site visit" and code 1.
$bad = @{
  event_type = "On-site visit"
  executive_summary = "Renewals call with Acme."
  raw_transcript_backup = "They're interested, wants a quote..."
  topics = @(
    @{ topic = "Contract / agreement renewal"; disposition_code = 1; executive_summary = "Wants a quote."; discussed = $true }
  )
  planned_topics = @("Contract / agreement renewal")
} | ConvertTo-Json -Depth 5

$s2 = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/notes/stage?campaign_type=renewals" -Body $bad -ContentType "application/json"
$s2 | ConvertTo-Json -Depth 5
```

### Result â€” **FAILS (bug confirmed)**

```json
{
  "session_id": "4032cae1-9391-481f-93e9-14a324d620e4",
  "confirmation_text": "Got it. Here's my summary: Renewals call with Acme. I've staged an On-site visit covering Contract / agreement renewal marked as create opportunity. Should I save this, or do you want to change something?",
  "missing_topics": [],
  "all_topics_covered": true
}
```

Both illegal values were accepted, and the confirmation text reads the illegal
disposition back to the rep as though it were valid â€” the "silent wrong code"
failure named in the ticket.

### Analysis â€” root cause

**The staging endpoint does not know which campaign it is staging for.**

`POST /api/v1/notes/stage` accepts no `campaign_type` parameter
(`main.py :: stage_notes` takes only the payload and `previous_session_id`), so
the `?campaign_type=renewals` above was silently ignored by FastAPI. With no
campaign in scope, both validators fall back to global lists:

| Check | Location | Validates against | Should validate against |
|---|---|---|---|
| event type | `main.py:212` | `mock_db.VALID_EVENT_TYPES` (all 3) | campaign's `allowed_event_types` |
| disposition code | `tools.py:32` | `VALID_DISPOSITION_CODES` (all 10, resolved at import) | campaign's `disposition_registry` |

The campaign config is injected into the model's **prompt** but never used to
**validate** the model's output. The fix requires threading `campaign_type`
through to the staging endpoint before either check can be made campaign-aware.

---

## Experiment 3 â€” `turn_guard` state is never reset *(not yet reproduced)*

**Ticket rows:** Guided â€” *"Tools blocked on 'no new reply'"*

Found by code reading; needs a live WebSocket session to demonstrate, so it is
not yet covered by a REST-only repro.

`turn_guard` keeps four module-level dicts keyed by `session_id`
(`_TURN_COUNTS`, `_BASELINES`, `_AWAITING_READBACK`, `_NUDGE_SENT`). Nothing
clears them â€” the WebSocket teardown in `main.py` closes only the
`LiveRequestQueue`. Because sessions are reused by `session_id`, a reconnect
inherits the previous connection's guard state, so a commit can be blocked by a
readback owed on an earlier connection.

**Proposed repro:** connect with a fixed `session_id`, stage notes, disconnect
before the readback completes, reconnect with the same `session_id`, and attempt
a commit. Expect `commit_visit_notes BLOCKED: confirmation_not_read`.

---

## Status summary

| # | Issue | AC | Status |
|---|---|---|---|
| 1 | Commit ignores uncovered planned topics | #3 | Reproduced |
| 2 | Campaign event types / disposition codes unenforced | #2 | Reproduced |
| 3 | `turn_guard` state leaks across connections | â€” | Code-read only |

### Already fixed on this branch (ticket rows now stale)

The ticket's first three "known gaps" appear to be addressed already at
`3ecd956` and should be re-verified rather than re-fixed:

- **Splintered `topics`** â€” `tools.py :: _normalize_topics` coerces strings and
  partial objects, drops out-of-registry codes, and returns a re-ask instead of
  raising (an exception inside a tool tears down the live stream).
- **Commit with no staged session** â€” rejected in `tools.py :: commit_visit_notes`.
- **"Tools blocked on no new reply"** â€” was a defect *in the guard itself*: an
  earlier version stored counters in ADK session state and always read a stale
  baseline, permanently blocking commits. Rewritten to process-local dicts
  (see the `turn_guard` module docstring).

### Open question

Branch `feature/AIML-2686` ("Added hybrid (partial guidance) flow") forks from
the same commit as this branch and adds a **third** mode. Neither AIML-2698 nor
AIML-2697 accounts for it. Confirm with the project lead whether fixes should be
based on `AIML-2686` instead, and whether hybrid is a third selectable demo mode.
````
<!-- END: docs/AIML-2698-experiments.md -->

<!-- FILE: docs/AIML-2698-jira-comment.md -->
````markdown
# Draft comment for AIML-2698

*(paste into the Jira ticket; trim as needed)*

---

Reproduced two of the listed gaps against `feature/AIML-2130-guided-flow`
(`3ecd956`) using REST calls only â€” no mic, no Gemini, no Vertex, BigQuery
disabled. Both are deterministic and take seconds to run, so they can go
straight into the smoke harness. Full log with copy-pasteable scripts:
`docs/AIML-2698-experiments.md`.

**1. Commit succeeds without full planned-topic coverage (AC#3)**

Staged a record covering 1 of 2 planned topics. Staging correctly returned
`missing_topics: ["Pricing"]`, `all_topics_covered: false`. Commit then
succeeded anyway and returned `CRM-B598122C53`. The committed record stores
`missing_topics: ["Pricing"]` as a field â€” the system records that the data is
incomplete and saves it regardless.

`compute_missing_topics` is computed at both stage and commit but never gates
anything. The only thing discouraging a premature save today is prompt text
("Do NOT save yet"), which is model-dependent.

**2. Campaign disposition codes and event types are not enforced (AC#2)**

`renewals` allows event types `[Phone Call, Meeting]` and codes `[2,3,5,8,9]`.
Staged a `renewals` payload with `event_type: "On-site visit"` and
`disposition_code: 1` â€” both illegal, both accepted, `all_topics_covered: true`.
The generated readback then states *"I've staged an On-site visit ... marked as
create opportunity"*, i.e. an invalid code is spoken back to the rep as valid.

Root cause: **`POST /api/v1/notes/stage` takes no `campaign_type`**, so it cannot
look up campaign rules. Both checks fall back to global lists â€” `event_type`
against `mock_db.VALID_EVENT_TYPES` (all 3) and disposition codes against
`VALID_DISPOSITION_CODES` (all 10, resolved at import time in `tools.py`). The
campaign config is injected into the model's prompt but never used to validate
its output. Fixing this requires threading `campaign_type` through to the
staging endpoint first.

**3. `turn_guard` state is never reset between connections** (code reading, no
repro yet)

The four module-level dicts keyed by `session_id` are never cleared; WS teardown
closes only the `LiveRequestQueue`. Since sessions are reused by `session_id`, a
reconnect inherits stale state and a commit can be blocked by a readback owed on
a previous connection. Likely to show up during repeated demo runs.

**Ticket rows 1â€“3 appear already fixed on this branch** and should be
re-verified rather than re-implemented:
- splintered `topics` â†’ handled by `tools.py :: _normalize_topics`
- commit with no staged session â†’ rejected in `commit_visit_notes`
- "tools blocked on no new reply" â†’ was a bug *in the guard*; the ADK-session-state
  version always read a stale baseline and blocked every commit. Already rewritten.

**Proposed fix location:** all of #1 and #2 belong in the REST layer
(`main.py` + `mock_db.py`) rather than in the ADK tools. Because the tools call
the API over HTTP, implicit / guided / hybrid all inherit the fix from one place.

**Question for the lead:** `feature/AIML-2686` ("Added hybrid (partial guidance)
flow") branches from the same commit as this work and adds a third mode. Should
these fixes be based on `AIML-2686` instead of `AIML-2130-guided-flow`? And does
hybrid become a third selectable mode in AIML-2697's demo UX?
````
<!-- END: docs/AIML-2698-jira-comment.md -->

