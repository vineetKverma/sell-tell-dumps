"""Drive the running app through one golden case, the way the rep would.

Uses the app's own public contract -- ``POST /api/sessions`` then the
``/ws/{user}/{session}`` WebSocket -- with TEXT turns, exactly like
``scripts/ws_smoke_test.py``. So the production agent, model, prompt, tools,
turn guard and session service are all under test; nothing is mocked.

The rep's side of the conversation is scripted and deterministic:

  1. The note, verbatim, as the dictation.
  2. If the agent staged the record without some planned topic, it reminds
     the rep about it (the coverage check). The rep answers that they did not
     get to it -- the note is all the rep said, so that is the truthful answer.
     Repeated at most MAX_COVERAGE_ROUNDS times.
  3. "Yes, that's right. Save it." -- so the record is committed.

What is scored is the arguments of the LAST ``stage_visit_notes`` call: the
record the rep was asked to confirm.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import websockets

from evals.agent_eval.cases import Case
from evals.agent_eval.score import norm

USER_ID = "golden-eval"
CAMPAIGN_TYPE = "standard_sales"

COVERAGE_REPLY = "I didn't get to that on this visit. There is nothing else to add."
CONFIRM_REPLY = "Yes, that's right. Save it."
MAX_COVERAGE_ROUNDS = 2

# Same pacing as scripts/ws_smoke_test.py: one agent response emits several
# turnComplete events, so a turn is over only after a quiet spell.
QUIET_PERIOD_S = 3.0
FINAL_QUIET_PERIOD_S = 15.0
TURN_TIMEOUT_S = 90.0


class Transcript:
    """Everything observed on the socket for one case."""

    def __init__(self) -> None:
        self.stage_calls: list[dict] = []
        self.committed = False
        self.lines: list[tuple[str, str]] = []  # (who, text)
        self.tool_errors: list[dict] = []

    def take(self, evt: dict) -> None:
        for key, who in (("inputTranscription", "rep"), ("outputTranscription", "agent")):
            text = (evt.get(key) or {}).get("text")
            if text:
                self.lines.append((who, text))
        for part in ((evt.get("content") or {}).get("parts") or []):
            fc = part.get("functionCall")
            if fc and fc.get("name") == "stage_visit_notes":
                self.stage_calls.append(fc.get("args") or {})
            elif fc and fc.get("name") == "commit_visit_notes":
                self.committed = True
            fr = part.get("functionResponse")
            if fr:
                resp = fr.get("response") or {}
                if resp.get("status") in ("incomplete", "error"):
                    self.tool_errors.append({"tool": fr.get("name"), **resp})

    @property
    def final(self) -> dict | None:
        return self.stage_calls[-1] if self.stage_calls else None


def missing_topics(case: Case, staged: dict | None, allow_skips: bool = True) -> list[str]:
    """Planned topics the app's coverage check will remind the rep about.

    Mirrors ``notes_workflow.compute_missing_topics`` so the scripted rep
    answers exactly when the agent asks: a planned topic is covered only by a
    row with its own label (ignoring case and spacing), and a
    ``discussed=false`` row counts only after the first staging call
    (``allow_skips``)."""
    if not staged:
        return []
    covered = {norm(t.get("topic")) for t in staged.get("topics") or []
               if isinstance(t, dict) and (allow_skips or t.get("discussed", True))}
    covered.discard("")
    return [p for p in case.planned_topics if norm(p) and norm(p) not in covered]


async def _settle(ws, tx: Transcript, quiet: float) -> bool:
    """Read until the agent has been quiet for ``quiet`` seconds after at
    least one turnComplete. False if it never answered within the timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + TURN_TIMEOUT_S
    saw_complete = False
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return saw_complete
        try:
            raw = await asyncio.wait_for(
                ws.recv(), timeout=min(quiet, remaining) if saw_complete else remaining)
        except asyncio.TimeoutError:
            return saw_complete
        evt = json.loads(raw)
        tx.take(evt)
        if evt.get("turnComplete"):
            saw_complete = True


async def _say(ws, tx: Transcript, text: str, quiet: float = QUIET_PERIOD_S) -> bool:
    tx.lines.append(("rep (sent)", text))
    await ws.send(json.dumps({"type": "text", "text": text}))
    return await _settle(ws, tx, quiet)


SESSION_ATTEMPTS = 3
SESSION_RETRY_WAIT_S = 10


class SessionEndpointError(RuntimeError):
    """The app has no usable POST /api/sessions -- missing, or its reply has
    changed shape. Every case would fail the same way, so the run stops at the
    first one instead of retrying all 90."""


def _session_id(r: httpx.Response) -> str | None:
    """The session id, None for a transient failure worth retrying (a 5xx, a
    408 or 429 from a proxy or load balancer in front of a deployed app, or the
    app's status "error" for a failed Vertex call), or SessionEndpointError
    when the endpoint itself is wrong (including 401 / 403: not transient)."""
    if r.status_code in (404, 405, 422):
        raise SessionEndpointError(f"POST /api/sessions returned {r.status_code}; the app does not "
                                   "offer the session endpoint this eval needs")
    if r.status_code >= 500 or r.status_code in (408, 429):
        return None
    try:
        body = r.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or "status" not in body:
        raise SessionEndpointError(f"POST /api/sessions replied in an unexpected shape: {r.text[:200]}")
    if body["status"] != "ok":
        return None
    if not body.get("session_id"):
        raise SessionEndpointError("POST /api/sessions replied ok without a session_id")
    return body["session_id"]


async def _create_session(base_url: str, case: Case) -> str:
    """POST /api/sessions, retried: the app reports a failed Vertex call (e.g.
    a token fetch timing out) as status "error", which is worth one more try.
    A missing or changed endpoint raises SessionEndpointError at once."""
    last = ""
    for attempt in range(1, SESSION_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(base_url=base_url, timeout=150) as http:
                r = await http.post("/api/sessions", json={
                    "user_id": USER_ID,
                    "planned_topics": case.planned_topics,  # a list: titles may contain commas
                    "campaign_type": CAMPAIGN_TYPE,
                })
            session_id = _session_id(r)
            if session_id:
                return session_id
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < SESSION_ATTEMPTS:
            await asyncio.sleep(SESSION_RETRY_WAIT_S)
    raise RuntimeError(f"session not created after {SESSION_ATTEMPTS} tries: {last}")


async def run_case(case: Case, base_url: str) -> dict:
    """One case end to end. A failure is recorded on the result so one bad case
    cannot stop a 90-case run -- except SessionEndpointError, which would fail
    every case and so stops the run."""
    tx = Transcript()
    result = {"id": case.id, "vertical": case.vertical}
    try:
        session_id = await _create_session(base_url, case)

        ws_base = base_url.replace("http", "ws", 1).rstrip("/")
        # The contract: the POST above seeds planned_topics and campaign_type;
        # the WebSocket takes only the ids in the path.
        url = f"{ws_base}/ws/{USER_ID}/{session_id}"
        # No client keepalive: while the app waits on a slow Google token
        # refresh it cannot answer pings, and the default 20 s ping timeout
        # dropped the socket mid-case ("no close frame received or sent").
        # TURN_TIMEOUT_S still bounds every turn.
        async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
            await _say(ws, tx, case.note)
            for _ in range(MAX_COVERAGE_ROUNDS):
                if not missing_topics(case, tx.final, allow_skips=len(tx.stage_calls) > 1):
                    break
                await asyncio.sleep(0.5)
                await _say(ws, tx, COVERAGE_REPLY)
            if tx.final:
                await asyncio.sleep(0.5)
                await _say(ws, tx, CONFIRM_REPLY, FINAL_QUIET_PERIOD_S)
    except SessionEndpointError:
        raise
    except Exception as exc:  # recorded, not raised
        result["error"] = f"{type(exc).__name__}: {exc}"

    result.update({
        "final": tx.final,
        "stage_calls": len(tx.stage_calls),
        "committed": tx.committed,
        "tool_errors": tx.tool_errors,
        "transcript": tx.lines,
    })
    return result
