"""Summary faithfulness: is everything in the agent's summaries said in the note?

The one metric that makes extra model calls, so it only runs with ``--judge``.
A summary is faithful when every claim in it -- the call summary and each
topic summary -- is supported by the note. Leaving something out is not
unfaithful; adding something the rep never said is (the "due to time
constraints" failure seen live).
"""

from __future__ import annotations

import json
import os
import time

DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_LOCATION = "global"
RATE_LIMIT_WAITS = (15, 30, 60, 120)

PROMPT = """You check a sales rep's visit record against what the rep actually said.

WHAT THE REP SAID (the only source of truth):
<<<
{note}
>>>

THE AGENT'S SUMMARIES:
{summaries}

Is every statement in the summaries supported by what the rep said? Omissions are
fine. A statement is unsupported if it adds a fact, reason, outcome, number, name
or intent the rep did not say. Saying a topic was "not discussed" is supported
when the rep did not mention it.

Answer with JSON only: {{"faithful": true|false, "unsupported": ["<each unsupported statement>"]}}"""


def summaries_of(staged: dict) -> str:
    lines = [f"- Call summary: {staged.get('executive_summary') or '(empty)'}"]
    for t in staged.get("topics") or []:
        if isinstance(t, dict) and t.get("executive_summary"):
            lines.append(f"- Topic \"{t.get('topic')}\": {t['executive_summary']}")
    return "\n".join(lines)


class Judge:
    def __init__(self, model: str = DEFAULT_MODEL, location: str = DEFAULT_LOCATION):
        from google import genai  # imported here: scoring and tests never need it

        self.model = model
        self.client = genai.Client(vertexai=True, location=location,
                                   project=os.environ.get("GOOGLE_CLOUD_PROJECT"))

    def check(self, note: str, staged: dict) -> dict:
        from google.genai import errors, types

        prompt = PROMPT.format(note=note, summaries=summaries_of(staged))
        cfg = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
        for wait in (*RATE_LIMIT_WAITS, None):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt, config=cfg)
                data = json.loads(resp.text)
                return {"faithful": bool(data["faithful"]),
                        "unsupported": list(data.get("unsupported") or [])}
            except errors.APIError as exc:
                if getattr(exc, "code", None) != 429 or wait is None:
                    return {"faithful": None, "error": f"{exc}"}
                time.sleep(wait)
            except (ValueError, KeyError, TypeError) as exc:
                return {"faithful": None, "error": f"unreadable judge reply: {exc}"}
        return {"faithful": None, "error": "rate limited"}
