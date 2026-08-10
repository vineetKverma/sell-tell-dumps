"""Manual dev smoke-test client for the voice-notes WebSocket, text-mode.

Drives a scripted conversation through /ws/{user}/{session} using TEXT turns
(bypassing the mic/audio pipeline entirely) so both the implicit and guided
agents can be exercised quickly from the terminal. The native-audio model
still replies with audio, but `output_audio_transcription` is enabled server
side, so we can read back what it *said* as text.

Usage:
    uv run python scripts/ws_smoke_test.py implicit
    uv run python scripts/ws_smoke_test.py guided
    uv run python scripts/ws_smoke_test.py guided --scenario missing_topic

Requires the app to already be running locally (uvicorn app.main:app).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.parse
import uuid

import websockets

BASE_WS_URL = "ws://localhost:8000/ws"
RAW_MODE = False

# ---------------------------------------------------------------------------
# Scripted turns per scenario. Each turn is one simulated "rep speaks" event.
# ---------------------------------------------------------------------------

IMPLICIT_SCENARIOS: dict[str, list[str]] = {
    "clean_save": [
        "I met with the customer on site today. We discussed pricing and "
        "they said it was too expensive for their budget right now. End of "
        "notes.",
        "Save it.",
    ],
    "correction": [
        "Had a phone call about pricing concerns, budget is tight. Done.",
        "Actually change that to a meeting.",
        "Save.",
    ],
    "missing_topic": [
        "Talked about pricing, they said it's too expensive.",
        "We didn't get to the contract renewal, ran out of time.",
        "Save it.",
    ],
    "multi_topic": [
        "Met on site. Discussed pricing -- too expensive for them right "
        "now. Also talked about a contract renewal, they already placed an "
        "order for it.",
        "Save.",
    ],
}

# NOTE on the trailing "Okay." turns below.
#
# After the last topic is dispositioned, record_topic_disposition returns
# "all topics are dispositioned, call commit_guided_notes now" -- and the model
# reliably does NOT act on it. It emits an empty output turn, closes the turn,
# and waits. Observed with a 15s quiet period and no nudge rescue.
#
# In a real session that is dead air at the worst moment: every question has
# been answered, the record is complete, and nothing is saved. It is logged as
# a defect (see docs/AIML-2698-experiments.md). The trailing turn here exists
# only so the scenario can reach a commit and exercise the rest of the
# pipeline -- it is NOT evidence that the flow works unaided, and it should be
# removed once the stall is fixed.
GUIDED_SCENARIOS: dict[str, list[str]] = {
    "clean_save": [
        "Yes let's begin.",
        "I met with the customer today, we talked about pricing and a "
        "contract renewal. End notes.",
        "Save.",
        "On-site visit.",
        "They said it was too expensive, pricing was a big concern.",
        "Yes that's right.",
        "They already placed an order for the renewal.",
        "Yes correct.",
        "Okay.",  # trailing nudge -- see NOTE above
    ],
    "playback_then_save": [
        "Start.",
        "Quick call about pricing concerns. End notes.",
        "Play back.",
        "Save.",
        "Phone call.",
        "Too expensive for their budget.",
        "Yes.",
    ],
    "rerecord": [
        "Yes.",
        "Talked about pricing. Done.",
        "Re-record.",
        "Actually, we discussed a contract renewal instead. That's it.",
        "Save.",
        "Meeting.",
        "They placed the order already.",
        "Yes.",
    ],
    "ambiguous_disposition": [
        "Go ahead.",
        "We covered pricing, it was a weird conversation, hard to say "
        "where it landed. End notes.",
        "Save.",
        "Meeting.",
        "It was complicated, kind of all over the place, not sure.",
        "No, that's not it.",
        "Still not quite right, I don't know honestly.",
        "I really don't know, let's just move on.",
    ],
}

PLANNED_TOPICS_IMPLICIT = {
    "clean_save": "Pricing discussion",
    "correction": "Pricing discussion",
    "missing_topic": "Pricing discussion,Contract renewal",
    "multi_topic": "Pricing discussion,Contract renewal",
}

PLANNED_TOPICS_GUIDED = {
    "clean_save": "Pricing discussion,Contract renewal",
    "playback_then_save": "Pricing discussion",
    "rerecord": "Contract renewal",
    "ambiguous_disposition": "Pricing discussion",
}


def _summarize_event(evt: dict) -> str | None:
    bits = []
    author = evt.get("author", "?")
    if evt.get("inputTranscription", {}).get("text"):
        bits.append(f"IN_TX={evt['inputTranscription']['text']!r}")
    if evt.get("outputTranscription", {}).get("text"):
        bits.append(f"OUT_TX={evt['outputTranscription']['text']!r}")
    content = evt.get("content") or {}
    for part in content.get("parts", []) or []:
        if part.get("functionCall"):
            fc = part["functionCall"]
            bits.append(f"TOOL_CALL={fc.get('name')}({fc.get('args')})")
        elif part.get("functionResponse"):
            fr = part["functionResponse"]
            bits.append(f"TOOL_RESP={fr.get('name')} -> {fr.get('response')}")
        elif part.get("text"):
            bits.append(f"TEXT={part['text'][:200]!r}")
    if evt.get("interrupted"):
        bits.append("INTERRUPTED")
    if evt.get("turnComplete"):
        bits.append("TURN_COMPLETE")
    if not bits:
        return None
    return f"[{author}] " + " | ".join(bits)


# How long the agent must stay silent AFTER a turn_complete before we accept
# that it has finished and send the next scripted turn.
QUIET_PERIOD_S = 3.0
# After the LAST scripted turn the agent often still owes trailing work -- e.g.
# guided's record_topic_disposition returns "all topics done, call
# commit_guided_notes now", which needs another beat (and may need main.py's
# auto-continue nudge to land). Closing the socket at the normal quiet period
# cuts the commit off and the scenario ends with no CRM record for reasons that
# have nothing to do with the code under test.
FINAL_QUIET_PERIOD_S = 15.0
# Absolute cap on how long one scripted turn may take.
TURN_TIMEOUT_S = 60.0


async def _drain_until_agent_settles(
    ws, quiet_period: float = QUIET_PERIOD_S
) -> None:
    """Read events until the agent has genuinely finished its response.

    A single agent response emits MULTIPLE ``turnComplete`` events -- one after
    a tool call returns, another after it finishes speaking, and so on. Breaking
    on the first one sends the next scripted turn while the agent is still
    working, so the "rep" ends up answering a question that has not been asked
    yet. That desynchronisation is not cosmetic: it makes the model answer its
    own questions, which turn_guard then (correctly) blocks, which leaves
    required state unset, which makes the final commit fail. One race,
    four layers of fallout, and none of it reproducible against a real rep.

    So instead of stopping at the first turn_complete, we keep reading until
    the agent has been silent for QUIET_PERIOD_S after at least one
    turn_complete.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + TURN_TIMEOUT_S
    saw_turn_complete = False

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            print("(turn timeout -- moving on)")
            return
        # Before the first turn_complete, wait as long as the overall cap
        # allows. After it, a short silence means the agent is done.
        wait_for = min(quiet_period, remaining) if saw_turn_complete else remaining
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=wait_for)
        except asyncio.TimeoutError:
            if saw_turn_complete:
                return  # agent has gone quiet -- safe to send the next turn
            print("(no response from agent -- moving on)")
            return

        evt = json.loads(raw)
        if RAW_MODE:
            print("RAW:", json.dumps(evt))
        summary = _summarize_event(evt)
        if summary:
            print(summary)
        if evt.get("turnComplete"):
            saw_turn_complete = True


async def run_scenario(
    agent_mode: str, scenario: str, turns: list[str], planned_topics: str
) -> None:
    user_id = "smoke_tester"
    session_id = f"smoke-{agent_mode}-{scenario}-{uuid.uuid4().hex[:6]}"
    query = urllib.parse.urlencode(
        {
            "campaign_type": "standard_sales",
            "planned_topics": planned_topics,
            "agent_mode": agent_mode,
        }
    )
    url = f"{BASE_WS_URL}/{user_id}/{session_id}?{query}"
    print(f"\n=== {agent_mode} / {scenario} ===")
    print(f"connecting: {url}")

    async with websockets.connect(url, max_size=None) as ws:
        for i, turn in enumerate(turns, start=1):
            if i > 1:
                # Small courtesy pause only; the real synchronisation is the
                # quiet-period wait below.
                await asyncio.sleep(0.5)
            print(f"\n--- turn {i}: REP SAYS: {turn!r} ---")
            await ws.send(json.dumps({"type": "text", "text": turn}))
            is_last = i == len(turns)
            await _drain_until_agent_settles(
                ws, FINAL_QUIET_PERIOD_S if is_last else QUIET_PERIOD_S
            )
        print("\n--- scenario complete ---")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("agent_mode", choices=["implicit", "guided"])
    parser.add_argument("--scenario", default=None, help="run just one scenario")
    parser.add_argument(
        "--raw", action="store_true", help="print full raw event JSON"
    )
    args = parser.parse_args()
    global RAW_MODE
    RAW_MODE = args.raw

    if args.agent_mode == "implicit":
        scenarios, planned_lookup = IMPLICIT_SCENARIOS, PLANNED_TOPICS_IMPLICIT
    else:
        scenarios, planned_lookup = GUIDED_SCENARIOS, PLANNED_TOPICS_GUIDED
    names = [args.scenario] if args.scenario else list(scenarios.keys())

    for name in names:
        turns = scenarios[name]
        planned = planned_lookup.get(name, "")
        await run_scenario(args.agent_mode, name, turns, planned)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
