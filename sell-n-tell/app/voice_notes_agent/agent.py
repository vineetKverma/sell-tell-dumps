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
from google.genai import types

from . import notes_workflow
from .tools import commit_visit_notes, stage_visit_notes

logger = logging.getLogger(__name__)

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
    model=os.getenv(
        "VOICE_NOTES_AGENT_MODEL", "gemini-live-2.5-flash-native-audio"
    ),
    instruction=voice_notes_instruction,
    tools=[stage_visit_notes, commit_visit_notes],
    generate_content_config=_GENERATION_CONFIG,
)

# Required by adk web -- the CLI discovers agents via this name.
root_agent = agent
