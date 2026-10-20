"""The per-session planned-topics block of the system prompt.

Kept apart from agent.py, which builds the live client at import time, so the
exact text the model sees can be tested by importing this module alone.
"""

from __future__ import annotations


def format_planned_topics_block(planned_topics: list[str]) -> str:
    "Render the rep's pre-call planned topics into the system prompt."
    if not planned_topics:
        return (
            "# Planned topics\n"
            "The rep did not pre-select any planned topics. Capture whatever "
            "they discuss as topics and skip the coverage reminder.\n"
        )
    lines = "\n".join(f"  - {t}" for t in planned_topics)
    # "Pass this full list as planned_topics ..." names an argument that
    # stage_visit_notes does not have (ADK drops unknown arguments). It stays
    # because it is part of the measured prompt: removing it, with two other
    # wording edits, made the agent answer 8-10 golden notes per run with an
    # empty turn instead of 1-3 (AIML-2928). Change it only with a full eval.
    return (
        "# Planned topics\n"
        "The rep planned to discuss the following campaigns on this call. Add "
        "a topics entry ONLY for a campaign whose offer or products the rep "
        "actually talked about, using its EXACT label below as the topic "
        "field; leave the others out so the tool can remind the rep. Pass "
        "this full list as planned_topics on every stage_visit_notes call:"
        f"\n{lines}\n"
    )
