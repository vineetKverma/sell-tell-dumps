# app/voice_notes_agent

branch: `development`  commit: `85b108c`  files: 8

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
from google.adk.models import Gemini
from google.genai import types

from . import notes_workflow
from .live_credentials import build_prewarmed_live_client
from .tools import commit_visit_notes, stage_visit_notes




logger = logging.getLogger(__name__)

# Pre-warm Gemini Live credentials ONCE at import time (before `agent` below
# is constructed) -- see BLOCKING_AUTH_FINDING.md for why this must happen
# HERE, not in main.py: main.py imports this module (and therefore fully
# constructs `agent`) before any code back in main.py could run, so building
# the client any later would be too late to use it here.
live_client = build_prewarmed_live_client()


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
    model=Gemini(
        model=os.getenv(
            "VOICE_NOTES_AGENT_MODEL", "gemini-live-2.5-flash-native-audio"
        ),
        client=live_client,
    ),
    instruction=voice_notes_instruction,
    tools=[stage_visit_notes, commit_visit_notes],
    generate_content_config=_GENERATION_CONFIG,
)

# Required by adk web -- the CLI discovers agents via this name.
root_agent = agent
````
<!-- END: app/voice_notes_agent/agent.py -->

<!-- FILE: app/voice_notes_agent/config.py -->
````python
import os

API_BASE = os.getenv("VOICE_NOTES_API_BASE", "http://localhost:8000")
````
<!-- END: app/voice_notes_agent/config.py -->

<!-- FILE: app/voice_notes_agent/live_credentials.py -->
````python
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
````
<!-- END: app/voice_notes_agent/live_credentials.py -->

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
- No guided-flow support. The guided flow is retired (AIML-2751); agent_mode
  / per-flow branching has been removed from this workflow. The last code is
  recoverable from the tag ``archive/guided-flow``.
"""

from __future__ import annotations

import logging
import os
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
        # A planned topic the rep never got to legitimately carries no
        # code. Anything else is a gap.
        #
        # VESTIGIAL: the `needs_manual_review` half of this exemption is
        # effectively dead. It existed for the retired guided flow's
        # "3 failed confirm attempts" path, which set the flag with no code.
        # The surviving flow only reaches needs_manual_review=True via
        # disposition_code=99 (see stage_notes below), which is not None, so
        # the exemption is never the reason a topic passes. Kept rather than
        # removed because dropping it would newly REJECT a payload where the
        # model sets the flag itself -- a behaviour change that belongs with
        # the AIML-2705 flag-shape unification, not here.
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

    Guarded by tests/test_notes_workflow_gates.py (AIML-2703). Note this
    orphan shape needs DISTINCT session ids, so it is reachable only by a
    caller that is not tools.py -- see that test module's docstring.
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


def rehydrate_staged(session_id: str, record: dict[str, Any]) -> None:
    """Restore a staged record into _STAGED_NOTES from external/session state.

    Used when resuming an active session across process restarts or reconnects.
    """
    _STAGED_NOTES[session_id] = record
    logger.debug("rehydrate_staged: restored session_id=%s into _STAGED_NOTES", session_id)


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


def cleanup_session(session_id: str) -> None:
    """Clean up in-memory staged notes for a session on disconnect or completion."""
    _STAGED_NOTES.pop(session_id, None)
    logger.debug("notes_workflow._STAGED_NOTES cleaned up for session_id=%s", session_id)


# Configurable retention TTLs for defense-in-depth in-memory dictionary pruning
VOICE_NOTES_COMMITTED_PRUNE_TTL_SECONDS = float(
    os.getenv("VOICE_NOTES_COMMITTED_PRUNE_TTL_SECONDS", "3600.0")
)
VOICE_NOTES_UNCOMMITTED_PRUNE_TTL_SECONDS = float(
    os.getenv("VOICE_NOTES_UNCOMMITTED_PRUNE_TTL_SECONDS", "7200.0")
)


def prune_stale_staged_notes(
    max_age_seconds: float | None = None,
    committed_max_age_seconds: float | None = None,
    uncommitted_max_age_seconds: float | None = None,
) -> int:
    """Prune stale records from _STAGED_NOTES as a defense-in-depth safety net.

    Configurable via environment variables:
    - VOICE_NOTES_COMMITTED_PRUNE_TTL_SECONDS (default 3600s / 1 hr)
    - VOICE_NOTES_UNCOMMITTED_PRUNE_TTL_SECONDS (default 7200s / 2 hrs)

    - Committed or superseded records older than committed TTL are evicted
      to prevent memory leaks while giving clients a generous window to retry.
    - Active uncommitted records older than uncommitted TTL are evicted as abandoned.

    Returns the count of evicted records.
    """
    if max_age_seconds is not None:
        c_ttl = max_age_seconds
        u_ttl = max_age_seconds * 2
    else:
        c_ttl = (
            committed_max_age_seconds
            if committed_max_age_seconds is not None
            else VOICE_NOTES_COMMITTED_PRUNE_TTL_SECONDS
        )
        u_ttl = (
            uncommitted_max_age_seconds
            if uncommitted_max_age_seconds is not None
            else VOICE_NOTES_UNCOMMITTED_PRUNE_TTL_SECONDS
        )

    now = datetime.now(timezone.utc)
    to_delete = []
    for sid, rec in list(_STAGED_NOTES.items()):
        ts_str = rec.get("committed_at") or rec.get("staged_at")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            age = (now - ts).total_seconds()
        except (ValueError, TypeError):
            continue

        if rec.get("committed") or rec.get("superseded_by"):
            if age > c_ttl:
                to_delete.append(sid)
        elif age > u_ttl:
            to_delete.append(sid)

    for sid in to_delete:
        _STAGED_NOTES.pop(sid, None)
    if to_delete:
        logger.info("prune_stale_staged_notes evicted %d records", len(to_delete))
    return len(to_delete)
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
            "True if the disposition code had to be left unresolved for a "
            "human to fix. NOT partitioned by flow: stage_notes sets this "
            "automatically whenever disposition_code == 99, so the surviving "
            "flow produces both together. The retired guided flow set it "
            "WITHOUT a code (after 3 failed disposition-confirm attempts), "
            "which is the shape validate_payload's no-code exemption was "
            "written for -- that exemption is now vestigial. Unifying the "
            "two shapes is an open decision -- see AIML-2705."
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
````
<!-- END: app/voice_notes_agent/tools.py -->

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
    if session_id not in _BASELINES:
        logger.debug(
            "turn_guard blocked: session_id=%s has no recorded baseline in this process",
            session_id,
        )
        return False
    current = _TURN_COUNTS.get(session_id, 0)
    baseline = _BASELINES[session_id]
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


# session_id -> tool name that triggered the awaiting readback (e.g. stage_visit_notes, commit_visit_notes)
_AWAITING_TOOL: dict[str, str] = {}


def mark_awaiting_readback(session_id: str, tool_name: str = "") -> None:
    """Call from the WS downstream loop when a tool whose result MUST be read
    aloud (e.g. stage_visit_notes) returns a response. Some native-audio
    Live model turns speak a guessed filler BEFORE the tool call and then, on
    return, decide they already "said enough" and skip the real readback --
    this flag makes that a hard-detectable condition rather than a silent
    UX bug.
    """
    _AWAITING_READBACK[session_id] = True
    _AWAITING_TOOL[session_id] = tool_name
    _NUDGE_SENT[session_id] = False


def awaiting_tool_name(session_id: str) -> str:
    """Return the tool name currently awaiting readback, if any."""
    return _AWAITING_TOOL.get(session_id, "")


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


def cleanup_session(session_id: str) -> None:
    """Clean up in-memory turn_guard tracking state for a completed or disconnected session.

    Evicts session_id from all process-local tracking dictionaries to prevent memory leaks.
    """
    _TURN_COUNTS.pop(session_id, None)
    _BASELINES.pop(session_id, None)
    _AWAITING_READBACK.pop(session_id, None)
    _NUDGE_SENT.pop(session_id, None)
    _AWAITING_TOOL.pop(session_id, None)
    logger.debug("turn_guard state cleaned up for session_id=%s", session_id)
````
<!-- END: app/voice_notes_agent/turn_guard.py -->

