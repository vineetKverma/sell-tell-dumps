"""Turn a frozen answer key into an ADK eval set for the AIML-2702 harness.

    uv run python -m evals.dataset.export_adk --version v1

Refuses to export unless ``golden_<version>.jsonl`` still matches the SHA-256 in
its manifest -- the eval must run against exactly the key that was frozen.

Each record becomes one ADK ``EvalCase``, built and validated with ADK's own
models so the file loads in ``adk eval`` / ``AgentEvaluator`` unchanged:

- session state: what the sales app hands the agent at call time -- planned
  topic names, their short descriptions, the vertical and campaign type.
  (``planned_topics`` and ``campaign_type`` are the keys main.py already
  seeds; the agent does not read ``vertical`` or the descriptions yet.)
- user turn: the rep's note, as the dictation.
- expected tool use: one ``stage_visit_notes`` call whose arguments are the
  golden answers -- event type, per-topic disposition, the must-capture values
  and the list of contested items to skip when scoring.

Only fields every ADK version accepts are used. Some versions forbid extra
fields on an EvalCase, so per-record metadata (strata, which models built it)
is not copied in: it stays in ``golden_<version>.jsonl``, joined on
``eval_id`` == record ``id``.

Writes ``golden_<version>.evalset.json`` (contains notes; stays on this machine).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.dataset.finalize import sha256
from evals.dataset.paths import OUT

APP_NAME = "voice-notes-logger"  # app/main.py APP_NAME
STATE_PLANNED_TOPICS = "planned_topics"  # app/voice_notes_agent/agent.py
EVAL_USER = "golden-eval"


def expected_args(rec: dict) -> dict:
    exp = rec["expected"]
    return {
        "event_type": exp.get("event_type"),
        "topics": [
            {"topic": t["title"], "discussed": t["discussed"], "disposition_code": t["disposition_code"]}
            for t in exp["topics"]
        ],
        "must_capture": exp["fields"],
        "contested": exp.get("contested", []),
    }


def session_state(rec: dict) -> dict:
    return {
        STATE_PLANNED_TOPICS: [t["title"] for t in rec["topics"]],
        "campaign_type": rec.get("campaign_type"),
        "vertical": rec["vertical"],
        "planned_topic_descriptions": {t["title"]: t.get("description_short", "") for t in rec["topics"]},
    }


def to_eval_case(rec: dict):
    from google.adk.evaluation.eval_case import (  # noqa: PLC0415
        EvalCase,
        IntermediateData,
        Invocation,
        SessionInput,
    )
    from google.genai import types  # noqa: PLC0415

    return EvalCase(
        eval_id=rec["id"],
        conversation=[
            Invocation(
                invocation_id=f"{rec['id']}-dictation",
                user_content=types.Content(role="user", parts=[types.Part(text=rec["note"])]),
                intermediate_data=IntermediateData(
                    tool_uses=[types.FunctionCall(name="stage_visit_notes", args=expected_args(rec))]
                ),
            )
        ],
        session_input=SessionInput(app_name=APP_NAME, user_id=EVAL_USER, state=session_state(rec)),
    )


def main() -> None:
    from google.adk.evaluation.eval_set import EvalSet  # noqa: PLC0415

    ap = argparse.ArgumentParser(description="Export a frozen answer key as an ADK eval set.")
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    golden = args.out / f"golden_{args.version}.jsonl"
    manifest = json.loads((args.out / f"golden_{args.version}.manifest.json").read_text(encoding="utf-8"))
    if sha256(golden) != manifest["sha256"]:
        raise SystemExit(f"{golden.name} no longer matches its manifest checksum -- it was changed "
                         "after freezing. Re-freeze under a new version.")

    records = [json.loads(line) for line in golden.read_text(encoding="utf-8").splitlines() if line]
    eval_set = EvalSet(
        eval_set_id=f"sellntell_golden_{args.version}",
        name=f"SellNTell golden set {args.version}",
        description=(f"{len(records)} FAR visit notes across {len(manifest['per_vertical'])} verticals; "
                     f"answers agreed by two independent model builds ({manifest['sha256'][:12]})."),
        eval_cases=[to_eval_case(r) for r in records],
    )
    path = args.out / f"golden_{args.version}.evalset.json"
    path.write_text(eval_set.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    print(f"{len(records)} eval cases -> {path}")


if __name__ == "__main__":
    main()
