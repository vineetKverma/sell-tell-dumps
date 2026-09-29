"""Credential pre-warm + periodic background refresh for the Gemini Live
WebSocket connection path.

Intended location in the project: app/voice_notes_agent/live_credentials.py

--------------------------------------------------------------------------
Background (see BLOCKING_AUTH_FINDING.md for full evidence/writeup)
--------------------------------------------------------------------------
google/genai/live.py's `connect()` method contains a hardcoded, always-
SYNCHRONOUS auth block:

    if not self._api_client._credentials:
        creds, _ = google.auth.default(scopes=[...])   # BLOCKING
    else:
        creds = self._api_client._credentials
    if not (creds.token and creds.valid):
        ...
        creds.refresh(auth_req)                          # BLOCKING

Both `google.auth.default()` and `Credentials.refresh(Request())` use the
classic synchronous `requests`-based transport. Because this runs inside an
`async def` function with no `await` wrapping it, it freezes asyncio's
ENTIRE event loop for the length of the call -- observed as 5-11s per
Gemini Live connection attempt in this project.

This module skips BOTH blocking calls for every connection *after startup*
by pre-supplying an already-valid, already-refreshed Credentials object on
the `genai.Client` used for the live connection. `_api_client._credentials`
is then truthy AND `creds.valid` is already True, so live.py's own `if`
checks short-circuit before either blocking call is reached. Verified
directly against the installed google-genai library (not just read from
source) -- see scripts/verify_credential_prewarm_fix.py.

The ONE blocking call this module cannot avoid is the very first
`google.auth.default()` + `credentials.refresh()`, done once at server
STARTUP, before any WebSocket connection is accepted -- that cost is paid
once, off the request path, which is the whole point of the fix.

--------------------------------------------------------------------------
Usage (see main.py / agent.py wiring notes at the bottom of this file)
--------------------------------------------------------------------------

    from voice_notes_agent.live_credentials import (
        build_prewarmed_live_client,
        start_background_refresh,
    )

    @app.on_event("startup")
    async def _prewarm_live_credentials():
        client = build_prewarmed_live_client()
        app.state.live_client = client
        asyncio.ensure_future(start_background_refresh(client))
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import google.auth
from google.auth.transport.requests import Request
from google.genai import Client

logger = logging.getLogger(__name__)

_LIVE_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# Google-issued OAuth2 access tokens are typically valid for ~3600s.
# Refreshing well before expiry (rather than waiting for live.py's own
# `creds.valid` check to catch an expired token) is what keeps EVERY live
# connection's auth block a no-op. If we let a token actually expire before
# refreshing, the very next connection attempt hits the blocking path again
# for that one request -- defeating the fix for that request.
_REFRESH_MARGIN_SECONDS = 300  # refresh 5 minutes before actual expiry
_REFRESH_CHECK_INTERVAL_SECONDS = 60  # how often the background task wakes to check
_RETRY_AFTER_FAILURE_SECONDS = 60  # backoff if a refresh attempt itself fails


def _resolve_and_refresh_new_credentials(scopes: list[str]):
    """Runs entirely on a worker thread via asyncio.to_thread -- this
    function itself is plain synchronous code, deliberately.

    Returns a BRAND NEW Credentials object each time (rather than mutating
    an existing one in place). See the note on `_swap_credentials` below
    for why that distinction matters for thread-safety.
    """
    credentials, project = google.auth.default(scopes=scopes)
    credentials.refresh(Request())
    return credentials, project


def build_prewarmed_live_client() -> Client:
    """One-time, startup-only credential resolution + refresh.

    This DOES perform the same two calls that are blocking elsewhere in
    this project -- but doing it ONCE here, at server startup (before any
    WebSocket connection is accepted), costs nothing on the request path.
    The payoff: every connection afterward reuses this already-valid
    credential and skips both blocking calls inside
    google/genai/live.py's connect().

    Call this synchronously during startup (not inside a coroutine that
    also needs to stay responsive) -- it is expected to block briefly,
    exactly once, which is the intended tradeoff.
    """
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION")

    credentials, resolved_project = _resolve_and_refresh_new_credentials(_LIVE_SCOPES)

    client = Client(
        vertexai=True,
        project=project or resolved_project,
        location=location,
        credentials=credentials,
    )
    logger.info(
        "Pre-warmed Gemini Live credentials at startup (project=%s, "
        "location=%s, token_expiry=%s)",
        project or resolved_project,
        location,
        getattr(credentials, "expiry", None),
    )
    return client


def _swap_credentials(client: Client, new_credentials) -> None:
    """Replace the client's credentials with a freshly resolved object.

    Deliberately a full OBJECT SWAP (reassigning the attribute to a new
    Credentials instance), not an in-place mutation of the existing one.

    Why this matters: `credentials.refresh()` sets several attributes
    (token, expiry, ...) one at a time -- NOT atomically. If our background
    refresh task called `.refresh()` on the SAME object that live.py's
    connect() might be reading from concurrently (on the main event loop
    thread, via asyncio.to_thread's worker thread doing the refresh), a
    connect() call could theoretically observe a torn/partially-updated
    credential (e.g. a new expiry paired with a stale token).

    A plain attribute REASSIGNMENT (`client._api_client._credentials = X`)
    is a single bytecode STORE_ATTR under CPython's GIL, so any other
    thread reading `client._api_client._credentials` will see either the
    OLD object or the NEW one in full -- never a half-updated hybrid. This
    sidesteps the torn-read risk entirely, at the cost of resolving a fresh
    credential from scratch each cycle rather than refreshing in place.

    KNOWN COUPLING RISK: `client._api_client._credentials` is a PRIVATE
    attribute of the google-genai SDK, not a public API. This will need
    re-verification if google-genai is upgraded and happens to rename or
    restructure `_api_client` / `_credentials`. There is no public
    "replace the client's credentials" method as of the version this was
    written against -- flagged here deliberately so it isn't missed on a
    future dependency bump.
    """
    client._api_client._credentials = new_credentials  # noqa: SLF001


async def start_background_refresh(client: Client) -> None:
    """Runs forever (until the process exits), refreshing the client's
    credentials shortly before they expire.

    Uses asyncio.to_thread(...) for the actual (synchronous) refresh call
    -- this IS a call site we control directly, unlike the ones buried
    inside google/genai/live.py, so wrapping it here is straightforward
    and genuinely effective: the blocking work happens on a worker thread,
    never on the event loop that serves live WebSocket connections.

    Must be scheduled once via asyncio.ensure_future(...) (or an
    app-lifespan equivalent) during startup -- it does not return under
    normal operation.
    """
    while True:
        credentials = client._api_client._credentials  # noqa: SLF001
        expiry = getattr(credentials, "expiry", None)

        if expiry is None:
            # No known expiry (uncommon, e.g. certain service-account key
            # types) -- fall back to a fixed periodic refresh instead of
            # computing a margin against an expiry we don't have.
            await asyncio.sleep(_REFRESH_CHECK_INTERVAL_SECONDS * 30)  # ~30 min
        else:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            seconds_until_expiry = (expiry - now).total_seconds()
            seconds_until_due = seconds_until_expiry - _REFRESH_MARGIN_SECONDS

            if seconds_until_due > _REFRESH_CHECK_INTERVAL_SECONDS:
                # Not due yet. Wake periodically (rather than sleeping for
                # the entire remaining duration in one shot) so a manual
                # credential rotation/replacement would be picked up
                # reasonably promptly if this module is ever extended to
                # support that.
                await asyncio.sleep(_REFRESH_CHECK_INTERVAL_SECONDS)
                continue
            if seconds_until_due > 0:
                await asyncio.sleep(seconds_until_due)

        try:
            new_credentials, _ = await asyncio.to_thread(
                _resolve_and_refresh_new_credentials, _LIVE_SCOPES
            )
            _swap_credentials(client, new_credentials)
            logger.info(
                "Background-refreshed Gemini Live credentials (new expiry=%s)",
                getattr(new_credentials, "expiry", None),
            )
        except Exception:  # noqa: BLE001 -- must never crash the whole app
            logger.exception(
                "Background credential refresh failed -- will retry in "
                "%ss. Live connections may hit the blocking refresh path "
                "again until this succeeds.",
                _RETRY_AFTER_FAILURE_SECONDS,
            )
            await asyncio.sleep(_RETRY_AFTER_FAILURE_SECONDS)


# ---------------------------------------------------------------------------
# Wiring notes (apply these two small edits by hand -- not included as a
# full-file rewrite here, to avoid clobbering unrelated changes you may have
# made to main.py / agent.py since this was written):
#
# In main.py, near the other startup-time setup (alongside the existing
# `runner = Runner(...)` construction):
#
#     from voice_notes_agent.live_credentials import (
#         build_prewarmed_live_client,
#         start_background_refresh,
#     )
#
#     _live_client = build_prewarmed_live_client()
#
#     @app.on_event("startup")
#     async def _start_credential_refresh_task():
#         asyncio.ensure_future(start_background_refresh(_live_client))
#
# In agent.py, thread `_live_client` into the Agent's model construction.
# ADK's Gemini model class documents exactly this extension point:
#
#     from google.adk.models import Gemini
#
#     agent = Agent(
#         name="voice_notes_logger",
#         model=Gemini(
#             model=os.getenv("VOICE_NOTES_AGENT_MODEL", "gemini-live-2.5-flash-native-audio"),
#             client=_live_client,   # <-- the pre-warmed client from main.py
#         ),
#         ...
#     )
#
# (Exact wiring may differ slightly depending on how `agent` is currently
# constructed in your agent.py -- the key requirement is only that the SAME
# `_live_client` object built once at startup is the one ultimately used by
# `Gemini(client=...)`, so `_live_api_client` returns it via
# `if self.client: return self.client` instead of building its own.)
# ---------------------------------------------------------------------------
