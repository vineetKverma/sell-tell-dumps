"""Manual dev smoke-test client for the voice-notes WebSocket, text-mode.

Drives a scripted conversation through /ws/{user}/{session} using TEXT turns
(bypassing the mic/audio pipeline entirely). The native-audio model still
replies with audio, but `output_audio_transcription` is enabled server side,
so we can read back what it *said* as text.

Per the contract-simplification pass: the guided flow is retired (no more
`agent_mode` argument -- there is only one flow now).

`campaign_type` IS sent on the connection query string (business decision:
keep it flowing end-to-end for forward-compatibility) but is NOT processed
by the backend -- see main.py's websocket_endpoint docstring. It has no
effect on this test's scenarios or assertions; it's included only so the
smoke test continues to exercise the full, real connection contract the
frontend uses.

Usage:
    uv run python scripts/ws_smoke_test.py
    uv run python scripts/ws_smoke_test.py --scenario missing_topic

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

# campaign_type is sent but inert on the backend (see module docstring).
# Kept as a plain constant, not a CLI flag, since there is currently nothing
# server-side to vary it against -- add a --campaign-type flag if/when
# notes_workflow.validate_payload() starts reading it.
DEFAULT_CAMPAIGN_TYPE = "standard_sales"

# ---------------------------------------------------------------------------
# Scripted turns per scenario. Each turn is one simulated "rep speaks" event.
# (Guided-flow scenarios removed -- that flow is retired.)
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, list[str]] = {
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
    # AIML-2703 AC#3. The correction shapes the ticket names, one per scenario,
    # because they exercise different paths through stage_notes: `correction`
    # above changes a top-level field (event_type), and the three below change a
    # topic's disposition, restate the summary, and add a topic that was never
    # staged.
    #
    # None of these can exercise the supersede gate -- the model always commits
    # the record it just staged, never the one it replaced. That gate is covered
    # by scripts/repro_orphan_restage.py, which drives notes_workflow directly.
    "correction_summary": [
        "Met on site to talk about pricing. They said it was too expensive. "
        "End of notes.",
        "That summary isn't right -- say they're reviewing it with their "
        "finance team before deciding.",
        "Save it.",
    ],
    "correction_disposition": [
        "Met on site and went through pricing. They placed an order for it. "
        "End of notes.",
        "That's wrong -- they didn't order anything, the price was too high "
        "for their budget.",
        "Save it.",
    ],
    "correction_add_topic": [
        "Met on site, we went through pricing and they said it was too "
        "expensive. End of notes.",
        "I also covered the contract renewal and they placed an order for it.",
        "Save it.",
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

PLANNED_TOPICS: dict[str, str] = {
    "clean_save": "Pricing discussion",
    "correction": "Pricing discussion",
    "correction_summary": "Pricing discussion",
    "correction_disposition": "Pricing discussion",
    # Contract renewal is planned but deliberately not mentioned on the first
    # pass -- the correction turn is what adds it, so this also proves the
    # coverage gate releases once a re-stage supplies the missing topic.
    "correction_add_topic": "Pricing discussion,Contract renewal",
    "missing_topic": "Pricing discussion,Contract renewal",
    "multi_topic": "Pricing discussion,Contract renewal",
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
# After the LAST scripted turn the agent often still owes trailing work --
# e.g. speaking the closing_statement after commit_visit_notes returns, which
# needs another beat (and may need main.py's auto-continue nudge to land).
# Closing the socket at the normal quiet period cuts that off and the
# scenario ends with no commit for reasons that have nothing to do with the
# code under test.
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


async def run_scenario(scenario: str, turns: list[str], planned_topics: str) -> None:
    user_id = "smoke_tester"
    session_id = f"smoke-{scenario}-{uuid.uuid4().hex[:6]}"
    # campaign_type is sent per the business decision to keep it flowing
    # end-to-end, but the backend stores it as inert session-state metadata
    # only -- see main.py's websocket_endpoint docstring. It does not affect
    # any scenario's assertions here. agent_mode is not sent: guided flow is
    # retired and there is only one flow now.
    query = urllib.parse.urlencode(
        {
            "planned_topics": planned_topics,
            "campaign_type": DEFAULT_CAMPAIGN_TYPE,
        }
    )
    url = f"{BASE_WS_URL}/{user_id}/{session_id}?{query}"
    print(f"\n=== {scenario} ===")
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
    parser.add_argument("--scenario", default=None, help="run just one scenario")
    parser.add_argument(
        "--raw", action="store_true", help="print full raw event JSON"
    )
    args = parser.parse_args()
    global RAW_MODE
    RAW_MODE = args.raw

    names = [args.scenario] if args.scenario else list(SCENARIOS.keys())

    for name in names:
        turns = SCENARIOS[name]
        planned = PLANNED_TOPICS.get(name, "")
        await run_scenario(name, turns, planned)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
