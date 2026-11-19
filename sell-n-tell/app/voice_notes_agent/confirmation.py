"""Confirmation intent classifier for SellNTell (AIML-3012).

Classifies the sales rep's reply after the agent asks:
"Shall I go ahead and save those notes?" (or reads back the staged summary)
into one of four distinct states:
  - confirm: Rep gave clear, unconditional consent to save the notes as-is.
  - correction: Rep agreed with changes, modified a field, or corrected information.
  - skip: Rep explicitly requested not to save or to cancel/abandon the notes.
  - unclear: Rep's response was ambiguous, noisy, empty, a question, or filler.

Gating invariant:
A FALSE CONFIRM (classifying an unverified, modifying, or non-affirmative statement
as confirm) is a critical error. When in doubt, the system must classify as 'unclear'.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_INTERPRET_MODEL = os.getenv("CONFIRMATION_INTENT_MODEL", "gemini-3.8-flash")
CONFIRMATION_LOCATION = os.getenv("CONFIRMATION_LOCATION", "global")
CONFIRMATION_TIMEOUT_S = float(os.getenv("CONFIRMATION_TIMEOUT_S", "4.0"))
CONFIRMATION_MAX_ATTEMPTS = int(os.getenv("CONFIRMATION_MAX_ATTEMPTS", "2"))

# Known transcriber noise and acoustic tags that represent non-speech or background sound
_NOISE_TOKENS = frozenset(
    {
        "[cough]",
        "[clears throat]",
        "[road noise]",
        "[traffic]",
        "[inaudible]",
        "[background noise]",
        "[static]",
        "*sigh*",
        "[noise]",
        "[laughter]",
        "[pause]",
        "[groan]",
        "[sigh]",
    }
)

_PUNCTUATION_OR_SPACE = re.compile(r"^[\s\.,!?:;\-\u2013\u2014\*\(\)\[\]]*$")


class ConfirmationResult(BaseModel):
    """Structured classification output of the rep's confirmation reply."""

    intent: Literal["confirm", "correction", "skip", "unclear"] = Field(
        description="The classified intent of the rep's reply."
    )
    correction_detail: str | None = Field(
        default=None,
        description=(
            "If intent is 'correction', the specific detail, field, or modification requested. "
            "Otherwise null."
        ),
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief explanation of why this intent was chosen.",
    )


CONFIRMATION_SYSTEM_PROMPT = """You are an intent classification assistant for a sales voice-notes application.
The sales representative has just completed dictating post-visit notes. The agent has read back a summary and asked for confirmation (e.g. "Shall I go ahead and save those notes?").

Your task is to analyze the representative's spoken reply transcript and classify it into EXACTLY ONE of four intents:

1. "confirm":
   The representative gives CLEAR, UNCONDITIONAL agreement to save the notes as-is.
   Examples: "Yeah", "Yes", "Yep", "Yup", "Okay", "OK", "Sure", "Sounds good", "Looks good", "All set", "Save it", "Go ahead and save", "That's correct", "That's right", "Perfect", "Good to go", "Wrap it up and save".

2. "correction":
   The representative modifies, corrects, adds, removes, or qualifies any information in the notes.
   CRITICAL: If the representative says "yes" or "yeah" but IMMEDIATELY follows with a correction, addition, or condition ("Yes, but change the date to Tuesday", "Yeah, except the contact was Sarah not Mike", "Sounds good, but make it 50 units"), you MUST classify this as "correction", NEVER as "confirm".
   Other examples: "No, change the meeting to a phone call", "Wait, it was a quote not an order", "Actually next step is Friday".
   When intent is "correction", populate `correction_detail` with the requested change.

3. "skip":
   The representative explicitly states they DO NOT want to save, or wants to cancel, discard, or abort the session.
   Examples: "Don't save", "Do not save this", "Cancel", "Cancel this note", "Never mind", "Scratch that", "Discard that", "Forget it", "Don't commit this", "Leave it unsaved".

4. "unclear":
   The representative's reply is ambiguous, non-committal, a clarification question, hesitation, filler words, or empty/ambient noise.
   Examples: "Uh...", "Um", "Hmm", "Well...", "What did you say?", "Did you say Tuesday?", "Wait a sec", "Let me see", "Maybe", "I don't know", "[cough]".
   - Hedged assent ("I guess so", "Suppose so") expresses doubt/hesitation and MUST be classified as "unclear".
   - Question intonation ("yes?", "okay?") indicates uncertainty or asking for repetition and MUST be classified as "unclear".
   - Negation-as-agreement or contradictory phrasing ("no, that's fine", "no it's good") is ambiguous when answering a confirmation prompt and MUST be classified as "unclear", NEVER as "confirm".
   - Trailing pause qualifiers ("yes... wait", "sure... hang on") represent unfinished thoughts and MUST be classified as "unclear" (or "correction" if followed by a specific edit).

SAFETY RULE:
A "false confirm" (classifying a correction, skip, noise, or ambiguous reply as "confirm") corrupts customer CRM records. If there is ANY doubt, ambiguity, or hesitation, classify as "unclear". Never guess "confirm".
"""


def fast_prefilter(transcript: str | None) -> ConfirmationResult | None:
    """Evaluate trivial non-speech cases in 0ms without invoking an LLM.

    Returns ConfirmationResult(intent='unclear') if trivially determinable
    (e.g. empty, pure whitespace, pure punctuation, or acoustic noise token),
    else None. All candidate speech utterances fall through to the LLM classifier
    to guarantee zero false confirms.
    """
    if not transcript:
        return ConfirmationResult(
            intent="unclear",
            reasoning="Empty transcript",
        )

    stripped = transcript.strip()
    if not stripped or _PUNCTUATION_OR_SPACE.match(stripped):
        return ConfirmationResult(
            intent="unclear",
            reasoning="Transcript contains only whitespace or punctuation",
        )

    if stripped.lower() in _NOISE_TOKENS:
        return ConfirmationResult(
            intent="unclear",
            reasoning="Transcript is an acoustic noise marker",
        )

    return None


def build_confirmation_prompt(transcript: str) -> str:
    """Format user prompt for Gemini."""
    return f"""Spoken reply from sales representative:
\"\"\"{transcript}\"\"\"

Classify the intent into confirm, correction, skip, or unclear."""


_CLIENT_CACHE: dict[str, object] = {"client": None}


def prewarm_confirmation_client(client=None):
    """Pre-warm or register the cached genai.Client instance for confirmation classification.

    Creates a dedicated classifier client pinned to CONFIRMATION_LOCATION (default: 'global')
    with pre-warmed credentials to avoid regional 404s and ADC discovery cold-start livelocks.
    """
    if client is not None:
        _CLIENT_CACHE["client"] = client
        return _CLIENT_CACHE["client"]

    if _CLIENT_CACHE["client"] is not None:
        return _CLIENT_CACHE["client"]

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("CONFIRMATION_LOCATION", CONFIRMATION_LOCATION)
    use_vertex = (
        os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("true", "1")
        or bool(project)
    )

    creds = None
    try:
        from .agent import live_client

        if live_client is not None:
            creds = getattr(
                getattr(live_client, "_api_client", None), "_credentials", None
            )
            if project is None:
                project = getattr(
                    getattr(live_client, "_api_client", None), "project", None
                )
    except Exception as exc:
        logger.warning(
            "Could not extract pre-warmed credentials from live_client (%s); attempting credential resolution",
            type(exc).__name__,
        )

    if creds is None and use_vertex:
        try:
            import google.auth
            from google.auth.transport.requests import Request

            resolved_creds, resolved_proj = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            if not getattr(resolved_creds, "valid", False):
                resolved_creds.refresh(Request())
            creds = resolved_creds
            if project is None:
                project = resolved_proj
        except Exception as exc:
            logger.warning(
                "Failed to pre-warm credentials via google.auth.default: %s",
                type(exc).__name__,
            )

    from google.genai import Client

    client_kwargs = {
        "vertexai": use_vertex,
        "project": project,
        "location": location,
    }
    if creds is not None:
        client_kwargs["credentials"] = creds

    try:
        _CLIENT_CACHE["client"] = Client(**client_kwargs)
        logger.info(
            "Initialized dedicated confirmation client pinned to location=%s (has_credentials=%s)",
            location,
            creds is not None,
        )
    except Exception as exc:
        logger.warning(
            "Failed to initialize dedicated confirmation client (%s); falling back to default Client",
            type(exc).__name__,
        )
        _CLIENT_CACHE["client"] = Client(location=location)

    return _CLIENT_CACHE["client"]


def check_confirmation_client(client=None) -> dict[str, object]:
    """Perform startup self-check on the confirmation classifier client."""
    c = client or _CLIENT_CACHE.get("client") or _get_default_client()
    api_client = getattr(c, "_api_client", None)
    loc = getattr(api_client, "location", None)
    proj = getattr(api_client, "project", None)
    creds = getattr(api_client, "_credentials", None)
    status = {
        "configured": c is not None,
        "model": DEFAULT_INTERPRET_MODEL,
        "location": loc,
        "project": proj,
        "has_credentials": creds is not None,
        "credentials_valid": getattr(creds, "valid", False) if creds else False,
    }
    logger.info("Confirmation client startup check: %s", status)
    return status


async def probe_confirmation_client(
    client=None,
    timeout: float = CONFIRMATION_TIMEOUT_S,
) -> bool:
    """Active probe for confirmation classifier connectivity and model availability.

    Sends a live check (interpret_async("yes")) to surface broken configurations
    (regional 404s, auth errors, token exhaustion, or unreachable endpoints)
    before incoming traffic arrives. Logs an ERROR on failure or timeout.

    Returns:
        True if probe succeeded and classified intent as 'confirm', False otherwise.
    """
    c = client or _CLIENT_CACHE.get("client") or _get_default_client()
    try:
        result = await asyncio.wait_for(
            interpret_async("yes", client=c),
            timeout=timeout,
        )
        if result.intent != "confirm":
            logger.error(
                "Confirmation client active startup probe failed: expected 'confirm', got '%s' (reasoning: %s)",
                result.intent,
                result.reasoning,
            )
            return False
        logger.info(
            "Confirmation client active startup probe SUCCEEDED (intent=%s)",
            result.intent,
        )
        return True
    except asyncio.TimeoutError:
        logger.error(
            "Confirmation client active startup probe timed out after %.1fs",
            timeout,
        )
        return False
    except Exception as exc:
        logger.error(
            "Confirmation client active startup probe failed with error: %s",
            type(exc).__name__,
        )
        return False


def _get_default_client():
    """Lazily instantiate or return cached singleton genai.Client."""
    return prewarm_confirmation_client()


def _build_generation_config():
    """Build shared GenerateContentConfig for confirmation classification."""
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=CONFIRMATION_SYSTEM_PROMPT,
        temperature=0.0,
        max_output_tokens=256,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        response_mime_type="application/json",
        response_schema=ConfirmationResult,
    )


def _parse_confirmation_response(response_text: str | None) -> ConfirmationResult:
    """Parse and validate JSON response text into ConfirmationResult."""
    if not response_text:
        return ConfirmationResult(
            intent="unclear",
            reasoning="Empty response received from classification model",
        )
    return ConfirmationResult.model_validate_json(response_text)


def interpret(
    transcript: str,
    *,
    client=None,
    model: str = DEFAULT_INTERPRET_MODEL,
) -> ConfirmationResult:
    """Classify the rep's confirmation reply.

    Args:
        transcript: Spoken text transcript from the user.
        client: Optional google.genai.Client instance. If None, cached singleton is used.
        model: Gemini model to use for classification (default: gemini-3.8-flash).

    Returns:
        ConfirmationResult with intent ('confirm', 'correction', 'skip', 'unclear').
    """
    # 1. 0ms Fast Path Filter
    pre = fast_prefilter(transcript)
    if pre is not None:
        return pre

    # 2. LLM Intent Classification
    prompt = build_confirmation_prompt(transcript)
    started = time.monotonic()
    try:
        genai_client = client if client is not None else _get_default_client()
        config = _build_generation_config()
        response = genai_client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        if response.candidates:
            finish_reason = getattr(response.candidates[0], "finish_reason", None)
            if finish_reason == "MAX_TOKENS" or (
                hasattr(finish_reason, "name") and finish_reason.name == "MAX_TOKENS"
            ):
                logger.warning(
                    "Confirmation classification output truncated: finish_reason is MAX_TOKENS"
                )
        elapsed = time.monotonic() - started
        result = _parse_confirmation_response(response.text)
        logger.debug(
            "Confirmation classifier completed in %.2fs: intent=%s",
            elapsed,
            result.intent,
        )
        return result

    except Exception as exc:
        logger.warning(
            "Confirmation classification error for transcript (reply_len=%d): %s",
            len(transcript),
            type(exc).__name__,
        )
        # Fail safe: when classification fails or raises, default to 'unclear' so the
        # agent re-prompts the user instead of committing prematurely.
        return ConfirmationResult(
            intent="unclear",
            reasoning=f"Classification failed with exception: {type(exc).__name__}",
        )


async def interpret_async(
    transcript: str,
    *,
    client=None,
    model: str = DEFAULT_INTERPRET_MODEL,
) -> ConfirmationResult:
    """Async variant of interpret()."""
    # 1. 0ms Fast Path Filter
    pre = fast_prefilter(transcript)
    if pre is not None:
        return pre

    # 2. LLM Intent Classification
    prompt = build_confirmation_prompt(transcript)
    started = time.monotonic()
    try:
        genai_client = client if client is not None else _get_default_client()
        config = _build_generation_config()
        response = await genai_client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        if response.candidates:
            finish_reason = getattr(response.candidates[0], "finish_reason", None)
            if finish_reason == "MAX_TOKENS" or (
                hasattr(finish_reason, "name") and finish_reason.name == "MAX_TOKENS"
            ):
                logger.warning(
                    "Confirmation classification output truncated: finish_reason is MAX_TOKENS"
                )
        elapsed = time.monotonic() - started
        result = _parse_confirmation_response(response.text)
        logger.debug(
            "Async confirmation classifier completed in %.2fs: intent=%s",
            elapsed,
            result.intent,
        )
        return result

    except Exception as exc:
        logger.warning(
            "Async confirmation classification error for transcript (reply_len=%d): %s",
            len(transcript),
            type(exc).__name__,
        )
        return ConfirmationResult(
            intent="unclear",
            reasoning=f"Classification failed with exception: {type(exc).__name__}",
        )
