"""The disposition codes extract() may give a discussed topic (AIML-3004).

Read from the agent's own registry (resources/dispositions.yaml), so both
choose from the same list with the same cues: codes 1-10 plus 99, "outcome
not covered".

The file is read here, not through ``voice_notes_agent.notes_workflow``, on
purpose: importing anything from that package builds the live agent and logs
in, which extract() and its eval must not need. A test holds the two readers
to the same codes and labels.
"""

from __future__ import annotations

from pathlib import Path

import yaml

DISPOSITIONS = Path(__file__).parents[1] / "voice_notes_agent" / "resources" / "dispositions.yaml"


def load_dispositions(path: Path = DISPOSITIONS) -> dict[int, str]:
    """{code: "label (e.g. cue; cue)"} for every code in the registry, 99 last."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = {}
    for rule in [*data["dispositions"], data["not_covered"]]:
        cues = "; ".join(rule.get("mapping_keywords") or [])
        out[int(rule["code"])] = f"{rule['label']}" + (f" (e.g. {cues})" if cues else "")
    return out
