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
import contextvars
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
from google.adk.models.google_llm import Gemini
from google.adk.plugins.bigquery_agent_analytics_plugin import (
    BigQueryAgentAnalyticsPlugin,
    BigQueryLoggerConfig,
)
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.sessions import (
    BaseSessionService,
    Session,
    VertexAiSessionService,
)
from typing import Any
import datetime
import pydantic
from google.genai import types

# Custom-metadata keys for compaction and usage data. They must be the exact
# names ADK's VertexAiSessionService reads back in get_session ("_compaction",
# "_usage_metadata" in both 2.1.0 and 2.10.0); copied rather than imported
# because ADK keeps them private. With different names ("adk_compaction" here
# before), the data was stored but never restored when a session was reloaded.
# tests/test_session_metadata_keys.py checks they still match ADK.
_COMPACTION_CUSTOM_METADATA_KEY = "_compaction"
_USAGE_METADATA_CUSTOM_METADATA_KEY = "_usage_metadata"


def _drop_unsupported_part_fields(content_dict: dict[str, Any]) -> None:
    """Remove Part fields the Agent Engine Sessions API rejects.

    ADK 2.10's own VertexAiSessionService.append_event strips `part_metadata`
    (a Gemini Developer API-only field) before appending, because the API
    fails the whole append with 400 "Unknown name part_metadata". Our
    non-blocking copy of that write path has to do the same, or those events
    are silently missing from the stored session.
    """
    for part in content_dict.get("parts") or []:
        if isinstance(part, dict):
            part.pop("part_metadata", None)
            part.pop("partMetadata", None)


def _set_internal_custom_metadata(
    metadata_dict: dict[str, Any], key: str, value: Any
) -> None:
    if "custom_metadata" not in metadata_dict or not isinstance(
        metadata_dict["custom_metadata"], dict
    ):
        metadata_dict["custom_metadata"] = {}
    metadata_dict["custom_metadata"][key] = value


# Make the agent package importable regardless of launch cwd (so both
# `uvicorn main:app` from app/ and `uvicorn app.main:app` from the repo root
# work).
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables from .env file BEFORE importing the agent.
load_dotenv(Path(__file__).parent / ".env")

# When running with Vertex AI (GOOGLE_GENAI_USE_VERTEXAI=TRUE), ensure dummy or placeholder
# GOOGLE_API_KEY values (e.g. "your_api_key_here") are removed from os.environ.
# Otherwise, google.genai attempts Vertex AI Express Mode with an invalid key instead of
# using standard Google Application Default Credentials (ADC) OAuth2 tokens!
if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("true", "1"):
    _api_key = os.getenv("GOOGLE_API_KEY")
    if _api_key and ("your_api_key" in _api_key.lower() or not _api_key.strip()):
        del os.environ["GOOGLE_API_KEY"]

# pylint: disable=wrong-import-position
# Contract simplification: db_interface.py / mock_db.py / bigquery_sink.py
# are gone. main.py no longer needs a CRM/workflow import at all -- every
# REST route that used to call into it (config, stage, commit, debug list)
# is deleted; the workflow is called directly and only from tools.py now.
from voice_notes_agent.agent import STATE_PLANNED_TOPICS, agent, live_client  # noqa: E402
from voice_notes_agent.live_credentials import start_background_refresh  # noqa: E402
from voice_notes_agent import notes_workflow, turn_guard  # noqa: E402


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

from contextlib import asynccontextmanager


async def _periodic_staged_notes_prune():
    """Periodically evict stale staged records from _STAGED_NOTES to prevent memory leaks."""
    while True:
        try:
            await asyncio.sleep(300)
            notes_workflow.prune_stale_staged_notes()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Error in background staged notes prune: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.ensure_future(start_background_refresh(live_client))
    prune_task = asyncio.ensure_future(_periodic_staged_notes_prune())
    yield
    prune_task.cancel()
    if "session_service" in globals() and hasattr(session_service, "flush"):
        logger.info("Flushing pending cloud session persistence tasks on shutdown...")
        await session_service.flush()


app = FastAPI(
    title="Agentic AI Voice Notes Logger API",
    version="2.0.0",
    description=(
        "Dynamic, agentic voice dictation application for field sales reps. "
        "WebSocket + health check only -- see module docstring."
    ),
    lifespan=lifespan,
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


# ---------------------------------------------------------------------------
# Session Service Configuration (AIML-2807 & 2743)
# ---------------------------------------------------------------------------
# VertexAiSessionService persists session state and turns across process restarts,
# redeployments, and network disconnects.
_SESSION_PROJECT = os.getenv("VERTEX_AI_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")

# Parse raw engine ID or URN (e.g., "urn:agent:...:reasoningEngines:2221633612665585664")
_raw_agent_engine = (
    os.getenv("VERTEX_AI_AGENT_ENGINE_ID")
    or os.getenv("AGENT_ENGINE_ID")
    or ""
).strip()

_extracted_location = None
if "locations:" in _raw_agent_engine:
    # e.g. ...locations:us-central1:...
    parts = _raw_agent_engine.split("locations:")
    if len(parts) > 1:
        _extracted_location = parts[1].split(":")[0].split("/")[0]

_SESSION_LOCATION = (
    os.getenv("VERTEX_AI_AGENT_ENGINE_LOCATION")
    or os.getenv("VERTEX_AI_LOCATION")
    or _extracted_location
    or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
)
# Normalize common typo / AWS convention to standard GCP region:
if _SESSION_LOCATION.lower() in ("us-central-1", "us_central_1"):
    _SESSION_LOCATION = "us-central1"

# Extract trailing numeric ID if full URN or resource path was provided
_AGENT_ENGINE_ID = None
if _raw_agent_engine:
    if ":" in _raw_agent_engine:
        _AGENT_ENGINE_ID = _raw_agent_engine.split(":")[-1].strip()
    elif "/" in _raw_agent_engine:
        _AGENT_ENGINE_ID = _raw_agent_engine.split("/")[-1].strip()
    else:
        _AGENT_ENGINE_ID = _raw_agent_engine


class NonBlockingVertexAiSessionService(VertexAiSessionService):
    """Subclass of VertexAiSessionService that decouples cloud event persistence
    from the live audio streaming loop.

    ADK's base VertexAiSessionService awaits `agent_engines.sessions.events.append`
    inline on every single live streaming event (transcriptions, tool calls, tool results,
    turn completions). Across high-latency connections (e.g. 7-10s per roundtrip to us-central1),
    this synchronous await stalls the live audio loop, causing long audio delays (up to 1.5 min)
    and buffer overflows (APIError: 1011 data sent too fast).

    This class updates the in-memory session object immediately (<0.01ms) and schedules the
    cloud REST append as a non-blocking background task.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending_tasks: set[asyncio.Task] = set()
        self._session_tail_tasks: dict[str, asyncio.Task] = {}

    async def flush(self, timeout: float = 8.0) -> None:
        """Wait for in-flight background cloud persistence tasks to finish."""
        if self._pending_tasks:
            pending = list(self._pending_tasks)
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True), timeout=timeout
                )
            except asyncio.TimeoutError:
                if self._pending_tasks:
                    logger.warning(
                        "Timed out waiting for %d background persistence task(s) to flush",
                        len(self._pending_tasks),
                    )

    async def append_event(self, session: Session, event: Event) -> Event:
        # 1. Update in-memory session state (temp state, state deltas, events list) immediately
        # via BaseSessionService.append_event (<0.01ms):
        event = await BaseSessionService.append_event(self, session=session, event=event)

        if getattr(event, "partial", False):
            return event

        # 2. Dispatch cloud persistence to a non-blocking background task.
        # Chained sequentially per session so events arrive at Vertex AI in strict chronological order:
        prev_task = self._session_tail_tasks.get(session.id)

        async def _ordered_worker(p_task: asyncio.Task | None, s: Session, e: Event) -> None:
            if p_task is not None:
                try:
                    await p_task
                except Exception:
                    pass  # Don't drop subsequent events if a prior event write threw an error
            await self._persist_cloud_event(s, e)

        task = asyncio.create_task(
            _ordered_worker(prev_task, session, event),
            name=f"cloud-event-{session.id}-{getattr(event, 'id', 'unknown')}",
        )
        self._session_tail_tasks[session.id] = task
        self._pending_tasks.add(task)

        def _cleanup(t: asyncio.Task) -> None:
            self._pending_tasks.discard(t)
            if self._session_tail_tasks.get(session.id) is t:
                self._session_tail_tasks.pop(session.id, None)

        task.add_done_callback(_cleanup)
        return event

    async def _persist_cloud_event(self, session: Session, event: Event) -> None:
        try:
            reasoning_engine_id = self._get_reasoning_engine_id(session.app_name)
            config: dict[str, Any] = {}
            if event.content:
                config["content"] = event.content.model_dump(
                    exclude_none=True, mode="json"
                )
                _drop_unsupported_part_fields(config["content"])
            if event.actions:
                config["actions"] = {
                    "skip_summarization": event.actions.skip_summarization,
                    "state_delta": event.actions.state_delta,
                    "artifact_delta": event.actions.artifact_delta,
                    "transfer_agent": event.actions.transfer_to_agent,
                    "escalate": event.actions.escalate,
                    "requested_auth_configs": {
                        k: json.loads(v.model_dump_json(exclude_none=True, by_alias=True))
                        for k, v in event.actions.requested_auth_configs.items()
                    },
                }
            if event.error_code:
                config["error_code"] = event.error_code
            if event.error_message:
                config["error_message"] = event.error_message

            metadata_dict: dict[str, Any] = {
                "partial": event.partial,
                "turn_complete": event.turn_complete,
                "interrupted": event.interrupted,
                "branch": event.branch,
                "custom_metadata": event.custom_metadata,
                "long_running_tool_ids": (
                    list(event.long_running_tool_ids)
                    if event.long_running_tool_ids
                    else None
                ),
            }
            if event.grounding_metadata:
                metadata_dict["grounding_metadata"] = event.grounding_metadata.model_dump(
                    exclude_none=True, mode="json"
                )

            if event.actions and event.actions.compaction:
                compaction_dict = event.actions.compaction.model_dump(
                    exclude_none=True, mode="json"
                )
                _set_internal_custom_metadata(
                    metadata_dict,
                    key=_COMPACTION_CUSTOM_METADATA_KEY,
                    value=compaction_dict,
                )
            if event.usage_metadata:
                usage_dict = event.usage_metadata.model_dump(
                    exclude_none=True, mode="json"
                )
                _set_internal_custom_metadata(
                    metadata_dict,
                    key=_USAGE_METADATA_CUSTOM_METADATA_KEY,
                    value=usage_dict,
                )

            config["event_metadata"] = metadata_dict
            config["raw_event"] = event.model_dump(
                exclude_none=True,
                mode="json",
                by_alias=True,
            )
            if isinstance(config["raw_event"].get("content"), dict):
                _drop_unsupported_part_fields(config["raw_event"]["content"])

            inv_id = event.invocation_id if event.invocation_id else f"inv-{getattr(event, 'id', 'default')}"
            async def _do_append(cfg: dict[str, Any]):
                async with self._get_api_client() as api_client:
                    await api_client.agent_engines.sessions.events.append(
                        name=f"reasoningEngines/{reasoning_engine_id}/sessions/{session.id}",
                        author=event.author,
                        invocation_id=inv_id,
                        timestamp=datetime.datetime.fromtimestamp(
                            event.timestamp, tz=datetime.timezone.utc
                        ),
                        config=cfg,
                    )

            try:
                await _do_append(config)
            except pydantic.ValidationError as pydantic_err:
                if "raw_event" in config:
                    logger.warning(
                        "Pydantic validation error when persisting event to Vertex AI (session_id=%s, author=%s): %s. "
                        "Retrying cloud persistence without raw_event payload.",
                        session.id,
                        getattr(event, "author", "unknown"),
                        pydantic_err,
                    )
                    del config["raw_event"]
                    await _do_append(config)
                else:
                    raise
        except Exception as exc:
            logger.warning(
                "Background cloud event persist failed session_id=%s author=%s: %r",
                session.id,
                getattr(event, "author", "unknown"),
                exc,
            )


if not _AGENT_ENGINE_ID:
    raise RuntimeError(
        "VERTEX_AI_AGENT_ENGINE_ID / AGENT_ENGINE_ID must be configured. "
        "InMemorySessionService has been completely removed."
    )

_api_key = os.getenv("GOOGLE_API_KEY", "")
_express_key = None if (_api_key and "your_api_key" not in _api_key.lower()) else ""

logger.info(
    "Initializing NonBlockingVertexAiSessionService (project=%s, location=%s, agent_engine_id=%s)",
    _SESSION_PROJECT,
    _SESSION_LOCATION,
    _AGENT_ENGINE_ID,
)
session_service: BaseSessionService = NonBlockingVertexAiSessionService(
    project=_SESSION_PROJECT,
    location=_SESSION_LOCATION,
    agent_engine_id=_AGENT_ENGINE_ID,
    express_mode_api_key=_express_key,
)


# Reconnection policy configuration:
# Controls whether reconnecting clients attempt to resume the same session_id (true)
# or mint a brand new session_id (false). Defaults to false so consecutive visits rotate cleanly.
_RECONNECT_SAME_SESSION_ENV = os.getenv("VOICE_NOTES_RECONNECT_SAME_SESSION")
if _RECONNECT_SAME_SESSION_ENV is not None:
    VOICE_NOTES_RECONNECT_SAME_SESSION = _RECONNECT_SAME_SESSION_ENV.lower() in (
        "true",
        "1",
        "yes",
    )
else:
    VOICE_NOTES_RECONNECT_SAME_SESSION = False

# Graceful auto-close delay in seconds after a visit is committed to CRM
VOICE_NOTES_AUTO_CLOSE_DELAY_S = int(os.getenv("VOICE_NOTES_AUTO_CLOSE_DELAY_S", "10"))

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

# Instrument Gemini.connect to detect the exact millisecond Vertex AI Live establishes its connection.
# This powers the server-side `live_ready` notification sent to the client, preventing audio chunk
# accumulation/bursts while the model is cold-starting.
_CURRENT_SESSION_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_session_id", default=""
)
_LIVE_READY_EVENTS: dict[str, asyncio.Event] = {}

_orig_gemini_connect = Gemini.connect


@contextlib.asynccontextmanager
async def _instrumented_gemini_connect(self, llm_request):
    async with _orig_gemini_connect(self, llm_request) as conn:
        current_sid = _CURRENT_SESSION_ID.get()
        ev = _LIVE_READY_EVENTS.get(current_sid)
        if ev is not None:
            ev.set()
        yield conn


Gemini.connect = _instrumented_gemini_connect



# ============================================================================
# Health check
# ============================================================================


@app.get("/healthz", summary="Health check")
async def healthz() -> dict:
    """Liveness/readiness probe. No auth, no state -- just confirms the
    process is up and serving requests."""
    return {"status": "ok"}


@app.get("/api/config", summary="Frontend configuration")
async def get_config() -> dict:
    """Return runtime configuration flags for the frontend."""
    return {
        "vad_silence_ms": SERVER_VAD_SILENCE_MS,
        "auto_close_delay_s": VOICE_NOTES_AUTO_CLOSE_DELAY_S,
        "reconnect_same_session": VOICE_NOTES_RECONNECT_SAME_SESSION,
    }



class CreateSessionRequest(pydantic.BaseModel):
    user_id: str = "rep"
    planned_topics: list[str] = []
    campaign_type: str = "standard_sales"


@app.post("/api/sessions", summary="Create and mint a new session")
async def create_session_endpoint(
    payload: CreateSessionRequest | None = None,
) -> dict:
    """Create a new session and return the server-minted session ID.

    Essential for VertexAiSessionService, which generates 64-bit integer resource
    IDs on the server and rejects user-supplied session IDs.
    """
    user_id = payload.user_id if payload else "rep"
    planned_topics = payload.planned_topics if payload else []
    campaign_type = payload.campaign_type if payload else "standard_sales"

    target_app_name = APP_NAME
    initial_state = {
        STATE_PLANNED_TOPICS: planned_topics,
        "campaign_type": campaign_type,
    }
    try:
        session = await session_service.create_session(
            app_name=target_app_name,
            user_id=user_id,
            state=initial_state,
        )
        return {
            "status": "ok",
            "session_id": session.id,
            "user_id": session.user_id,
        }
    except Exception as exc:
        logger.exception("Failed to create session in session_service: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
        }


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

# ---------------------------------------------------------------------------
# Concurrent-attach guard (AIML-2806).
#
# Problem: nothing tracked which session_id values had a LIVE WebSocket
# connection. If a second connection attached with the same session_id
# before the first one's teardown finished, both independently built their
# own LiveRequestQueue() and called runner.run_live(...) -- driving the same
# underlying Gemini Live session concurrently, which surfaces upstream as an
# opaque APIError 1000.
#
# Fix: an in-process, per-session_id asyncio.Lock. A second attach for a
# session_id that is already held is REJECTED IMMEDIATELY with a structured
# signal ("session_busy", close code 4409) rather than queuing or letting both
# connections drive runner.run_live(...) concurrently.
#
# Client-side behavior note: the reference web frontend (app.js) currently
# avoids race conditions on reconnect by minting a brand-new session_id
# (newSessionId()) on every reconnect attempt, treating any disconnect as a
# generic drop. Under normal single-tab operation, the frontend never reconnects
# with the same session_id. This server-side guard serves as a strict
# defense-in-depth guarantee: it prevents upstream APIError 1000 crashes if
# multiple browser tabs open the same session, if external API clients connect
# concurrently, or if future frontend reconnection logic implements true
# same-session resumption (AIML-2749).
#
# Scope decision (deliberate, revisit if deployment changes): this lock is
# in-process memory, which is only a correct guard because this service is
# deployed on Cloud Run with `max-instances=1` -- a single instance serves
# every concurrent rep via `concurrency`, not one instance per rep. Cloud
# Run does NOT guarantee a reconnecting client lands back on the same
# instance if more than one instance is ever allowed to run, so an
# in-process lock alone would silently stop catching the race under
# horizontal scaling. If this service is ever scaled to max-instances > 1,
# replace this with a cross-instance store (e.g. Redis/Memorystore via
# `SET NX` + TTL, or a Firestore transaction) instead of this dict.
# ---------------------------------------------------------------------------

# Advisory retry-after hint handed to a rejected concurrent attach. This is
# NOT a server-side wait -- the rejection is immediate; this only tells the
# client how long to back off before retrying with the same session_id.
SESSION_BUSY_RETRY_AFTER_MS = int(
    os.getenv("VOICE_NOTES_SESSION_BUSY_RETRY_AFTER_MS", "1000")
)


class _SessionSlot:
    """One session_id's lock, plus a live waiter count.

    The waiter count is what lets `_release_session_slot` reap the dict
    entry the instant nobody holds or is waiting on it, without reaching
    into asyncio.Lock's private internals to inspect its waiters queue.
    """

    __slots__ = ("lock", "waiters")

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.waiters = 0


# session_id -> slot. Grows by one entry per distinct session_id ever seen
# while a connection is in flight or queued -- same accumulation shape as
# notes_workflow._STAGED_NOTES and turn_guard's dicts (see their own module
# docstrings). _release_session_slot() below is this dict's own cleanup, so
# it does NOT keep growing once every connection for a given session_id has
# disconnected.
_SESSION_SLOTS: dict[str, _SessionSlot] = {}


def _acquire_session_slot(session_id: str) -> _SessionSlot:
    """Get-or-create the slot for a session_id and register one waiter.

    Safe without a separate guard lock: there is no `await` between the
    dict lookup/creation and the waiters increment, so no other coroutine
    on this single-threaded event loop can interleave here.
    """
    slot = _SESSION_SLOTS.get(session_id)
    if slot is None:
        slot = _SessionSlot()
        _SESSION_SLOTS[session_id] = slot
    slot.waiters += 1
    return slot


def _release_session_slot(
    session_id: str, slot: _SessionSlot, acquired: bool
) -> None:
    """Release the lock (if held) and reap the entry once nobody needs it.

    ``acquired`` must be False if the caller timed out waiting for the
    lock -- releasing a lock this coroutine never actually acquired would
    raise, and would wrongly free it out from under whoever holds it.
    """
    if acquired:
        slot.lock.release()
    slot.waiters -= 1
    if slot.waiters == 0:
        # Only remove OUR slot -- a new one could already have been
        # created for this session_id between our last await and here.
        current = _SESSION_SLOTS.get(session_id)
        if current is slot:
            del _SESSION_SLOTS[session_id]



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

    AIML-2806: a second connection attaching with a session_id that is
    already active is REJECTED IMMEDIATELY with a structured "session_busy"
    error (code 4409) instead of racing it to Gemini Live or queuing.
    (Note: the reference web frontend mints a fresh session_id on reconnect,
    so this guard primarily catches multi-tab conflicts, external API clients,
    and paves the way for future session resumption.)
    """

    await websocket.accept()
    if not _SAFE_ID.match(user_id) or not _SAFE_ID.match(session_id):
        await websocket.close(code=1008, reason="Invalid session identifiers")
        return
    slot = _acquire_session_slot(session_id)
    acquired = False
    try:
        # AIML-2806 -- immediate concurrent-attach rejection.
        #
        # If this session_id's lock is ALREADY held, another connection is
        # actively driving the same underlying Gemini Live session right now.
        # Reject THIS attach immediately with a structured, documented signal
        # (AC#1) rather than letting both reach runner.run_live() and collide
        # into an opaque APIError 1000.
        #
        # Deliberately NOT a wait_for(timeout) race: .locked() + .acquire() on
        # a free lock never suspend, and there is no `await` between them, so
        # the check is race-free -- and, crucially, being a SYNCHRONOUS
        # decision makes it robust to the event-loop freeze during another
        # connection's Gemini setup (see BLOCKING_AUTH_FINDING.md). The old
        # timeout-based design failed because that freeze delayed both this
        # connection's acceptance AND the rejection timer, so the timer fired
        # after the holder had already released. An instant lock-state check
        # has no timer to be delayed: whenever this connection is finally
        # accepted, it reads the true current state and rejects-or-proceeds
        # correctly.
        #
        # Note: queue-and-wait-for-teardown reconnect semantics (previously
        # attempted via the timeout) belong to the SEPARATE reconnection-
        # protocol ticket, which is blocked on AIML-2743; the reference client
        # mints a fresh session_id on reconnect today, so no production client
        # relies on same-id queueing. A rejected client is told to retry.
        if slot.lock.locked():
            with contextlib.suppress(Exception):
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "error": "session_busy",
                            "message": (
                                "session busy, retry after "
                                f"{SESSION_BUSY_RETRY_AFTER_MS}ms"
                            ),
                            "retry_after_ms": SESSION_BUSY_RETRY_AFTER_MS,
                        }
                    )
                )
            logger.warning(
                "session_id=%s already active -- rejecting concurrent attach "
                "(session_busy)",
                session_id,
            )
            await websocket.close(code=4409, reason="session_busy")
            return

        await slot.lock.acquire()  # free (checked above, no await between) -> instant
        acquired = True
        await _run_dictation_session(
            websocket, user_id, session_id, planned_topics, campaign_type
        )
    finally:
        _release_session_slot(session_id, slot, acquired)
        # Disconnect cleanup hook (AIML-2807 & 2743):
        # Only reap process-local dictionaries if THIS connection was the one
        # that acquired the lock (i.e. was the active session). If acquired is
        # False, this connection was a rejected concurrent attach (code 4409)
        # and must NOT touch the active session's state!
        if acquired:
            turn_guard.cleanup_session(session_id)
            notes_workflow.cleanup_session(session_id)
            if hasattr(session_service, "flush"):
                with contextlib.suppress(Exception):
                    await session_service.flush(timeout=5.0)


async def _run_dictation_session(

    websocket: WebSocket,
    user_id: str,
    session_id: str,
    planned_topics: str,
    campaign_type: str,
) -> None:
    """The dictation session body -- unchanged behavior from before
    AIML-2806, extracted verbatim so websocket_endpoint can wrap it with
    the concurrent-attach guard above. Runs only once this session_id's
    slot lock has been acquired, so this is the ONLY connection for this
    session_id driving Gemini Live at any given moment.
    """
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

    # Inform client of server policies (e.g. reconnecting with same session vs new session)
    with contextlib.suppress(Exception):
        await websocket.send_text(
            json.dumps(
                {
                    "type": "server_config",
                    "reconnect_same_session": VOICE_NOTES_RECONNECT_SAME_SESSION,
                    "auto_close_delay_s": VOICE_NOTES_AUTO_CLOSE_DELAY_S,
                }
            )
        )


    # runner.agent.model is now a Gemini(...) object (since it wraps a
    # pre-warmed client -- see live_credentials.py / BLOCKING_AUTH_FINDING.md),
    # not a plain string like before. Its own `.model` attribute holds the
    # actual model name string. Falls back to treating it as a plain string
    # if it ever IS one again (e.g. if client= wiring is ever removed),
    # so this doesn't silently break a second time in the same way.
    _agent_model = runner.agent.model
    model_name = getattr(_agent_model, "model", None) or _agent_model
    is_native_audio = "native-audio" in model_name.lower()

    # Patient automatic VAD so multi-sentence DICTATION isn't chopped into tiny
    # turns. With the Live API's short default silence window, every pause
    # between sentences ends the turn, the model starts answering, and the next
    # sentence barges in and interrupts it -- so staging never completes. A
    # longer silence_duration_ms only finalizes once the rep is truly done.
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

    if is_native_audio:
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(),
            realtime_input_config=realtime_input_config,
        )
    else:
        # Half-cascade fallback (text responses).
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["TEXT"],
            session_resumption=types.SessionResumptionConfig(),
            realtime_input_config=realtime_input_config,
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
        logger.error(
            "WebSocket attach requested nonexistent session_id=%s with cloud session service.",
            session_id,
        )
        await websocket.close(code=4404, reason="Session not found")
        return

    live_ready_event = asyncio.Event()
    _LIVE_READY_EVENTS[session_id] = live_ready_event
    sid_token = _CURRENT_SESSION_ID.set(session_id)

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
                if not live_ready_event.is_set():
                    logger.debug(
                        "Dropping early audio chunk received before live connection ready (session_id=%s)",
                        session_id,
                    )
                    continue
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
        # be spoken next (a summary, a scripted question...). Native-audio Live
        # models sometimes close the turn with zero output right after the tool
        # call instead of speaking it, leaving dead air the rep has no way to
        # unstick -- see turn_guard.needs_readback_nudge.
        _READBACK_OWED_TOOLS = {
            "stage_visit_notes",
        }

        readback_nudge_task: asyncio.Task | None = None
        commit_nudge_task: asyncio.Task | None = None
        commit_nudge_owed = False

        def _cancel_nudges() -> None:
            nonlocal readback_nudge_task, commit_nudge_task, commit_nudge_owed
            if readback_nudge_task is not None and not readback_nudge_task.done():
                readback_nudge_task.cancel()
            readback_nudge_task = None
            if commit_nudge_task is not None and not commit_nudge_task.done():
                commit_nudge_task.cancel()
            commit_nudge_task = None
            commit_nudge_owed = False

        async def _watchdog_readback_nudge(delay: float = 2.5) -> None:
            """Inject a readback nudge ONLY if the model remains genuinely silent.

            If the model begins streaming audio, emits partial transcriptions,
            or invokes another tool within `delay` seconds, this task is cancelled
            so duplicate readbacks are never queued into Gemini Live.
            """
            nonlocal total_nudges_sent
            try:
                await asyncio.sleep(delay)
                if (
                    turn_guard.needs_readback_nudge(session_id)
                    and total_nudges_sent < _MAX_NUDGES_PER_SESSION
                ):
                    turn_guard.mark_nudge_sent(session_id)
                    total_nudges_sent += 1
                    logger.warning(
                        "session_id=%s stayed silent for %.1fs after tool return -- injecting readback nudge (#%d)",
                        session_id,
                        delay,
                        total_nudges_sent,
                    )
                    nudge_text = (
                        "[SYSTEM] Your last tool call has already returned "
                        "an instruction_for_model. You have not yet spoken "
                        "aloud. Speak that response out loud right now, in "
                        "full, per your instructions. Do not wait for "
                        "anything else before doing this."
                    )
                    live_request_queue.send_content(
                        types.Content(parts=[types.Part(text=nudge_text)])
                    )
            except asyncio.CancelledError:
                pass

        async def _watchdog_commit_nudge(delay: float = 2.0) -> None:
            """Inject a spoken confirmation nudge ONLY if the model remains silent after commit."""
            nonlocal total_nudges_sent
            try:
                await asyncio.sleep(delay)
                if total_nudges_sent < _MAX_NUDGES_PER_SESSION:
                    total_nudges_sent += 1
                    logger.warning(
                        "session_id=%s stayed silent for %.1fs after commit_visit_notes -- injecting commit spoken confirmation nudge (#%d)",
                        session_id,
                        delay,
                        total_nudges_sent,
                    )
                    nudge_text = (
                        "[SYSTEM] commit_visit_notes has succeeded. Say out loud "
                        "right now, verbatim: 'Saved successfully. Have a great day!' "
                        "Do not stay silent."
                    )
                    live_request_queue.send_content(
                        types.Content(parts=[types.Part(text=nudge_text)])
                    )
            except asyncio.CancelledError:
                pass

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

        try:
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
                    _cancel_nudges()
                    turn_guard.record_user_turn(session_id)
                    responded_since_user_turn = False
                    tool_called_since_user_turn = False
                    nudge_sent_this_cycle = False
                if getattr(event, "interrupted", None):
                    _cancel_nudges()
                # Track whether a tool's spoken summary/question actually got
                # read aloud (see turn_guard.confirmation_was_read docstring) --
                # a pre-tool-call guess must never count as having delivered it.
                content = getattr(event, "content", None)
                if content and getattr(content, "parts", None):
                    for part in content.parts:
                        if getattr(part, "inline_data", None) is not None:
                            _cancel_nudges()
                        if getattr(part, "function_call", None) is not None:
                            _cancel_nudges()
                            tool_called_since_user_turn = True
                        fr = getattr(part, "function_response", None)
                        if fr is not None:
                            if fr.name in _READBACK_OWED_TOOLS:
                                turn_guard.mark_awaiting_readback(session_id, fr.name)
                            elif fr.name == "commit_visit_notes":
                                resp_dict = getattr(fr, "response", {})
                                if isinstance(resp_dict, dict) and resp_dict.get("status") in ("success", "committed"):
                                    commit_nudge_owed = True
                ot = getattr(event, "output_transcription", None)
                if ot is not None:
                    if (ot.text or "").strip():
                        _cancel_nudges()
                    if ot.finished:
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
                # tools returns without ever speaking its instruction_for_model out loud --
                # it treats an earlier pre-tool-call guess as if it already asked the question,
                # then goes silent until the rep says *something* to unstick it.
                # Rather than leave dead air, start a watchdog timer. If the model
                # stays completely silent for 2.0s-2.5s, the watchdog injects the nudge.
                # If the model begins speaking audio or emitting text, the watchdog
                # is cancelled to avoid duplicate readbacks.
                if (
                    getattr(event, "turn_complete", None)
                    and commit_nudge_owed
                    and total_nudges_sent < _MAX_NUDGES_PER_SESSION
                ):
                    commit_nudge_owed = False
                    if commit_nudge_task is not None and not commit_nudge_task.done():
                        commit_nudge_task.cancel()
                    commit_nudge_task = asyncio.create_task(
                        _watchdog_commit_nudge(2.0)
                    )
                elif (
                    getattr(event, "turn_complete", None)
                    and turn_guard.needs_readback_nudge(session_id)
                    and total_nudges_sent < _MAX_NUDGES_PER_SESSION
                ):
                    if readback_nudge_task is not None and not readback_nudge_task.done():
                        readback_nudge_task.cancel()
                    readback_nudge_task = asyncio.create_task(
                        _watchdog_readback_nudge(2.5)
                    )
        finally:
            _cancel_nudges()

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

    async def _notify_live_ready() -> None:
        try:
            await asyncio.wait_for(live_ready_event.wait(), timeout=60.0)
            with contextlib.suppress(Exception):
                await websocket.send_text(json.dumps({"type": "live_ready"}))
                logger.info(
                    "Live connection established -- sent live_ready for session_id=%s",
                    session_id,
                )
        except asyncio.TimeoutError:
            logger.error(
                "Timed out waiting for Gemini Live connection after 60s (session_id=%s)",
                session_id,
            )
            with contextlib.suppress(Exception):
                await websocket.close(code=4430, reason="gemini_connect_timeout")
            down_task.cancel()
            up_task.cancel()
        except asyncio.CancelledError:
            pass

    notify_task = asyncio.create_task(
        _notify_live_ready(),
        name=f"gemini-live-ready-{session_id}",
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
        for task in pending | {notify_task}:
            task.cancel()
        for task in pending | {notify_task}:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            if task.cancelled():
                continue
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
        _LIVE_READY_EVENTS.pop(session_id, None)
        _CURRENT_SESSION_ID.reset(sid_token)
        if not notify_task.done():
            notify_task.cancel()
