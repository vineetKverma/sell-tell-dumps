"""AIML-2703 -- reproduce (or rule out) orphaned staged records after a correction.

Gap 15 hypothesis, from code reading, never reproduced:

    stage_notes() mints a BRAND-NEW session_id on every call, including a
    correction (`previous_session_id=...`). The record being corrected is left
    in _STAGED_NOTES: not deleted, not marked superseded, and still a valid
    commit target. So one visit with N corrections leaves N+1 committable
    drafts, each holding a different version of the data.

    Committing an old draft writes the PRE-correction payload -- the exact
    thing the rep just corrected. And because mock_db's idempotency guard keys
    on session_id, draft A and draft B look like two unrelated commits, so both
    succeed and one visit produces two CRM records.

Why it was never reproduced through the agent: tools.py overwrites
`crm_staged_session_id` on every re-stage, so the agent only ever knows the
newest id and always commits the right one. This script bypasses the agent and
holds the old id deliberately -- which is what a retry, a second client, or any
future non-agent API consumer would effectively do.

REST only: no microphone, no model, no Vertex. Deterministic, runs in seconds.

    uv run python scripts/repro_orphan_restage.py

Exit code 1 if the gap reproduces, 0 if it does not.
"""

from __future__ import annotations

import sys

import httpx

BASE = "http://localhost:8000/api/v1"
CAMPAIGN = "standard_sales"
PLANNED = ["HVAC"]


def _payload(event_type: str, summary: str) -> dict:
    """A minimal, legal single-topic payload for `standard_sales`."""
    return {
        "event_type": event_type,
        "executive_summary": summary,
        "raw_transcript_backup": (
            "Met with Bethany about HVAC. She is sending an order for AC units."
        ),
        "topics": [
            {
                "topic": "HVAC",
                "disposition_code": 2,  # Order Placed
                "executive_summary": "Rep received an order for AC units.",
                "discussed": True,
            }
        ],
        "planned_topics": PLANNED,
        "campaign_type": CAMPAIGN,
    }


def _stage(client: httpx.Client, payload: dict, previous: str | None) -> str:
    params = {"agent_mode": "implicit"}
    if previous:
        params["previous_session_id"] = previous
    resp = client.post(f"{BASE}/notes/stage", json=payload, params=params)
    resp.raise_for_status()
    return resp.json()["session_id"]


def _commit(client: httpx.Client, session_id: str) -> httpx.Response:
    return client.post(
        f"{BASE}/notes/commit",
        json={
            "session_id": session_id,
            "confirmed": True,
            "agent_mode": "implicit",
            "campaign_type": CAMPAIGN,
        },
    )


def main() -> int:
    with httpx.Client(timeout=15.0) as client:
        # 1. Rep dictates. Draft A: "On-site visit".
        draft_a = _stage(
            client, _payload("On-site visit", "Visit covering HVAC."), None
        )
        print(f"draft A (original)          : {draft_a}")

        # 2. Rep corrects the event type. Draft B supersedes A -- in intent.
        draft_b = _stage(
            client,
            _payload("Phone Call", "Phone call covering HVAC."),
            previous=draft_a,
        )
        print(f"draft B (after correction)  : {draft_b}")

        if draft_a == draft_b:
            print(
                "\nNOT REPRODUCED: the correction reused the same session_id, "
                "so it overwrote in place and no orphan exists."
            )
            return 0

        # 3. Commit the OLD draft -- the pre-correction data the rep rejected.
        resp_a = _commit(client, draft_a)
        print(f"\ncommit(A) -> HTTP {resp_a.status_code}")

        if resp_a.status_code != 200:
            print(
                "NOT REPRODUCED: the superseded draft was refused "
                f"({resp_a.json().get('detail', resp_a.text)})."
            )
            return 0

        crm_a = resp_a.json().get("crm_record_id")
        print(f"  committed as {crm_a}")

        # 4. And the newest one, as the agent would have.
        resp_b = _commit(client, draft_b)
        crm_b = resp_b.json().get("crm_record_id") if resp_b.status_code == 200 else None
        print(f"commit(B) -> HTTP {resp_b.status_code}  {crm_b or ''}")

        # 5. What actually landed in the CRM.
        records = client.get(f"{BASE}/notes/committed").json()["records"]
        ours = [
            r
            for r in records
            if r.get("crm_record_id") in {crm_a, crm_b}
        ]

        print("\n--- committed records for ONE visit ---")
        for rec in ours:
            # commit_notes spreads the payload at the top level of the
            # committed record, so event_type is not nested under "payload".
            print(
                f"  {rec.get('crm_record_id')}  "
                f"event_type={rec.get('event_type')!r}"
            )

        if crm_a and crm_b:
            print(
                "\nREPRODUCED: one visit produced two CRM records, and the "
                "first carries the event type the rep corrected away from. "
                "The idempotency guard cannot catch this -- it keys on "
                "session_id, and these are two different ids."
            )
            return 1

        print(
            "\nPARTIALLY REPRODUCED: the superseded draft committed, but the "
            "corrected one did not. Still a wrong-data write."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
