"""AIML-2928: the prompt rules behind the AIML-2702 baseline misses.

Reads the prompt sources directly. ``agent.py`` builds the live client at
import time, so its planned-topics block is loaded on its own via ``ast``
rather than by importing the module.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1] / "app" / "voice_notes_agent"
_RULES = yaml.safe_load(
    (_PKG / "resources" / "behavioral_rules.yaml").read_text(encoding="utf-8")
)["behavioral_rules"]
_DISPOSITIONS = yaml.safe_load(
    (_PKG / "resources" / "dispositions.yaml").read_text(encoding="utf-8")
)


def _planned_topics_block(topics: list[str]) -> str:
    tree = ast.parse((_PKG / "agent.py").read_text(encoding="utf-8"))
    func = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_format_planned_topics_block"
    )
    namespace: dict = {}
    exec(compile(ast.Module([func], []), "agent.py", "exec"), namespace)
    return namespace["_format_planned_topics_block"](topics)


def test_prompt_no_longer_asks_for_every_planned_topic():
    block = _planned_topics_block(["MF Pools 26", "MF HVAC Q1 26"])
    for text in (_RULES, block):
        assert "EACH planned" not in text
        assert "disposition for EACH" not in text


def test_discussed_only_when_offer_or_products_mentioned():
    block = _planned_topics_block(["MF Pools 26"])
    assert "offer or its products" in _RULES
    assert "offer or products" in block
    assert "leave the others out" in block


def test_event_type_rule_is_stated():
    assert "Phone Call: ONLY when the rep says the conversation was by phone" in _RULES
    assert "Meeting: the rep mentions a person" in _RULES
    assert "On-site visit: everything else" in _RULES


def test_code_1_cues_do_not_contradict_99_guidance():
    code_1 = next(r for r in _DISPOSITIONS["dispositions"] if r["code"] == 1)
    cues = {k.lower() for k in code_1["mapping_keywords"]}
    assert "interested" not in cues
    assert "send a quote" not in cues
    # The worked example in the prompt maps interest + a quote request to 99.
    assert "interested and asked for a" in _RULES
    assert "the answer is 99" in _RULES
