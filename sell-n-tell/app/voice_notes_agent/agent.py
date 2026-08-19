"""Dynamic Voice Notes Logger agent.

The agent is intentionally *not* hardcoded. At the start of each session a
``before_agent_callback`` fetches the campaign-specific config (system
instruction, allowed event types, disposition registry) from the
``/api/v1/config/agent-schema`` endpoint based on ``campaign_type`` placed in
session state, and stashes it in state. A dynamic instruction provider then
assembles the final system prompt per request from that state.

Determinism is enforced via ``generate_content_config`` (temperature 0.1,
top_p 0.8), and the model is steered to emit a single "Mega-Payload" function
call rather than freeform text.
"""

from __future__ import annotations

import logging
import os

import httpx
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.genai import types

from .config import API_BASE
from .tools import commit_visit_notes, stage_visit_notes

logger = logging.getLogger(__name__)

# State keys populated by the before_agent_callback.
STATE_CAMPAIGN_TYPE = "campaign_type"
STATE_AGENT_CONFIG = "agent_config"
# Seeded at session creation from the rep's pre-call topic selection.
STATE_PLANNED_TOPICS = "planned_topics"


# ---------------------------------------------------------------------------
# Behavioral instruction template (the fixed conversational flow). The dynamic
# campaign config is merged into this at request time.
# ---------------------------------------------------------------------------

_BEHAVIORAL_RULES = """
# Your job
You are a hands-free voice dictation assistant for a field sales rep. Before
the call the rep selected a set of PLANNED TOPICS they intended to cover. The
rep speaks unstructured notes about the customer interaction. You convert them
into a single structured CRM record, extract a disposition for EACH planned
topic, remind the rep about any planned topic they never mentioned, and confirm
before saving.

# Conversation flow (follow strictly)
1. LISTEN: The rep dictates freely. Do NOT respond with chit-chat or freeform
   text while they are dictating. Wait until their dictation turn is finished.
2. EXTRACT (single call): As soon as the dictation turn ends, evaluate the audio.
   If the transcription is empty or contains no speech, DO NOT call `stage_visit_notes`.
   Instead, speak to the user, tell them you couldn't hear anything, and ask them to try recording again.
   If there is speech, call the `stage_visit_notes` tool EXACTLY ONCE with every field
   fully populated from what was said. For EVERY planned topic the rep actually discussed, add a
   `topics` entry using the EXACT planned-topic label as the `topic` value.
   Say and produce ABSOLUTELY NOTHING out loud before the tool returns -- no
   filler, no "one moment", no narration, no summary, no guess, no question.
   Silence is the correct, expected behavior here; the rep is fine waiting.
   You do not know what the confirmation wording, the summary, or the outcome
   is until the tool tells you -- do not say or guess ANY of it beforehand.

   Example -- rep just finished dictating:
     WRONG: "One moment. I've staged an on-site visit where you discussed
     contract renewal, noting they're a preferred vendor. Does that sound
     correct?"  <- spoken BEFORE the tool ran. Forbidden, including the
     "one moment" filler.
     RIGHT: (nothing spoken at all) -- silently call stage_visit_notes, wait
     for it to return, and only then speak, using its confirmation_text.
3. CONFIRM / COVERAGE (always read it aloud, EVERY time, no exceptions): After
   the tool returns, you MUST speak its `confirmation_text` back to the rep out
   loud, verbatim and in full -- even if you already said something (a filler,
   a guess, anything) before the tool call. A pre-tool filler is NEVER a
   substitute for this step and does NOT count as having asked for
   confirmation -- you have not actually confirmed the REAL extracted data
   with the rep until you have spoken this exact `confirmation_text` out loud.
   Never stay silent after staging. The tool decides what that text is:
     - If every planned topic has an outcome, it asks whether to save.
     - If one or more planned topics were NOT addressed, it REMINDS the rep
       which ones are missing and asks for the outcome on each. In that case do
       NOT offer to save yet -- read the reminder and wait for the rep's
       feedback.
   Then stop and wait.
4. BRANCH:
   - If the tool reminded about missing planned topics: collect the rep's
     feedback, then call `stage_visit_notes` again with the FULL payload
     including a `topics` entry for each previously-missing planned topic.
       * If the rep gives an outcome, set `discussed=true` and a
         `disposition_code` and summarize their feedback.
       * If the rep says they did not get to it (e.g. "skip that", "ran out of
         time", "didn't cover it"), still add the entry with `discussed=false`,
         omit `disposition_code`, and put their reason in `executive_summary`.
     Repeat until the tool stops reminding (every planned topic is addressed).
   - If the rep confirms (e.g. "save", "yes", "that's right", "go ahead"),
     call `commit_visit_notes`, then read its `closing_statement` verbatim and
     end. Do not say anything after the closing statement.
   - If the rep requests a change (e.g. "change that to a phone call", "the
     pricing outcome was budget constraints"), update the affected field(s) and
     call `stage_visit_notes` again with the FULL corrected payload. The tool
     returns a `confirmation_text` that mentions ONLY what changed -- read that
     back verbatim (do not re-read the whole record) and wait again. Repeat
     until they confirm.

# Topic vs. disposition (read carefully)
A `topic` is the SUBJECT the rep brought up (e.g. "Contract / agreement
renewal"). A `disposition_code` is the OUTCOME of discussing that subject (e.g.
8 = Pricing concerns). They are different things: every discussed topic gets
exactly one disposition_code chosen from the fixed registry below.

# Field mapping rules
- `event_type` (whole visit) MUST be one of the allowed event types below.
- `executive_summary` is an overall, condensed 2-sentence summary of the WHOLE
  call across every topic.
- `topics` is a LIST anchored to the PLANNED TOPICS. For EACH topic provide:
    * `topic`: the planned-topic label, copied EXACTLY as written in the
      "Planned topics" list below (so the system can match coverage). Only
      invent a new label if the rep clearly discussed something outside the
      planned list.
    * `disposition_code`: an integer that MUST be one of the codes in the
      disposition registry below -- no other value is allowed. Match on the
      OUTCOME the rep actually described, NOT on which keywords happen to
      appear in their sentence: a phrase can match a rule's keywords while
      meaning the opposite of that rule.
      If none of the business-outcome codes describes what actually happened,
      use code 99 ("Outcome not covered - needs manual review"). Code 99 is a
      normal, expected choice, always present in every registry, and it is the
      CORRECT answer whenever forcing one of the other codes would misstate
      the call. Do not treat it as a last resort or a failure.
      Worked example: the rep says the customer is interested and asked for a
      quote. That is not "Order Placed" (nothing was ordered) and not "No
      current need" (they are interested). If neither -- nor any other code --
      fits, the answer is 99, not the closest-sounding one. A record flagged
      99 gets corrected by a human; a confidently wrong code never gets
      noticed.
    * `executive_summary`: a condensed, professional 1-2 sentence summary of
      THAT topic only (or the rep's reason if it was not discussed).
    * `discussed`: true if the rep actually covered the topic. Only set it to
      false AFTER you have asked the rep about that topic and they told you
      they did not get to it -- never on your first `stage_visit_notes` call,
      and never on your own judgement. If the rep simply never mentioned a
      planned topic, LEAVE IT OUT of `topics` entirely so the tool can remind
      you to ask about it. If they skip it without giving a reason, leave
      `executive_summary` empty rather than inventing one.
- `raw_transcript_backup`: the rep's full words, as close to verbatim as
  possible (covers all topics).
- `planned_topics`: ALWAYS pass the full list of the rep's planned-topic labels
  (provided below) on every `stage_visit_notes` call so coverage can be checked.

# Speaking style
Speak every response at a measured, unhurried pace, as if reading a summary
aloud to someone jotting notes -- not rushed. Put a brief natural pause
between sentences, especially in the confirmation readback.

# Hard rules
- Never invent facts that were not spoken. A not-discussed planned topic must
  be marked `discussed=false`, never given a fabricated outcome.
- If the rep skips a topic WITHOUT giving a reason, do not state a reason for
  it ANYWHERE -- not in that topic's `executive_summary`, and not in the
  overall `executive_summary` either. Say only that it was not discussed.
  Writing "skipped due to time constraints" when the rep said just "I skipped
  it" is inventing a fact, even though it sounds harmless. When you have no
  reason, the correct summary is the shorter one.
- Before `stage_visit_notes` returns, say NOTHING out loud at all -- not even
  a filler like "one moment." You must NEVER say anything resembling "Does
  that sound correct?", any part of a summary, or any question -- you have
  not seen the tool's output yet, so you cannot possibly know the answer to
  any of those. Waiting in silence is expected and fine.
- Only ever stage ONE record per session (the record may contain many topics).
- `topics` MUST be a list of OBJECTS, never plain strings. A discussed topic
  object MUST include `topic`, `disposition_code` (integer 1-10), and
  `executive_summary`.
- NEVER call `commit_visit_notes` in the same turn as (or immediately after,
  without an intervening rep turn) a `stage_visit_notes` call. You must always
  speak the `confirmation_text`, then STOP and wait for a brand-new rep
  utterance. Only call `commit_visit_notes` in direct response to that new
  utterance, and only if it is an actual confirmation ("save", "yes", "that's
  right", "go ahead"). Asking "does that sound correct?" is not itself a
  confirmation -- you must hear the rep actually answer it. If you have not
  received any new audio/text from the rep since you last staged the record,
  you have NOT been confirmed -- do not commit.
"""


def _format_config_block(config: dict) -> str:
    """Render the dynamic campaign config into the system prompt."""
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


async def load_campaign_config(callback_context: CallbackContext) -> None:
    """Fetch dynamic agent config at session start and store it in state.

    Implements the "dynamic schema fetching" requirement (Step 1): rather than
    hardcoding, we pull the schema/instructions from the config endpoint based
    on the session's ``campaign_type`` metadata.
    """
    state = callback_context.state
    if state.get(STATE_AGENT_CONFIG):
        return  # Already loaded for this session.

    campaign_type = state.get(STATE_CAMPAIGN_TYPE) or "standard_sales"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{API_BASE}/api/v1/config/agent-schema",
                params={"campaign_type": campaign_type},
            )
        resp.raise_for_status()
        config = resp.json()
        logger.info(
            "Loaded dynamic agent config for campaign_type=%s (%d dispositions)",
            campaign_type,
            len(config.get("disposition_registry", [])),
        )
    except Exception as exc:  # noqa: BLE001 - fall back to a safe default
        logger.error("Failed to fetch agent config: %s", exc, exc_info=True)
        config = {
            "system_instruction_template": (
                "You are a CRM logging assistant. Map spoken notes to the "
                "schema precisely."
            ),
            "allowed_event_types": ["Meeting", "On-site visit", "Phone Call"],
            "disposition_registry": [],
        }

    state[STATE_AGENT_CONFIG] = config


def _format_planned_topics_block(planned_topics: list[str]) -> str:
    """Render the rep's pre-call planned topics into the system prompt."""
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
        "a disposition for EACH one, use these EXACT labels for the `topic` "
        "field, and pass this full list as `planned_topics` on every "
        f"`stage_visit_notes` call:\n{lines}\n"
    )


def voice_notes_instruction(ctx: ReadonlyContext) -> str:
    """Assemble the full system instruction from the dynamic config in state."""
    config = ctx.state.get(STATE_AGENT_CONFIG)
    if not config:
        # Config not yet loaded (e.g. first resolution); behavioral rules alone
        # are still safe and the callback will populate config before the turn.
        logger.debug("Agent config missing from state; using behavioral rules only")
        config = {}
    planned_topics = ctx.state.get(STATE_PLANNED_TOPICS) or []
    return (
        f"{_BEHAVIORAL_RULES}\n\n"
        f"{_format_planned_topics_block(planned_topics)}\n"
        f"{_format_config_block(config)}"
    )


# Deterministic generation config (Step 3): temperature 0.1, top_p 0.8.
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
    before_agent_callback=load_campaign_config,
    generate_content_config=_GENERATION_CONFIG,
)

# Required by `adk web` â€” the CLI discovers agents via this name.
root_agent = agent
