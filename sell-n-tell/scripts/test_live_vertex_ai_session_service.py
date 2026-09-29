"""Live integration test for VertexAiSessionService against real GCP Reasoning Engine.

Tests:
1. NonBlockingVertexAiSessionService can create real sessions in Vertex AI.
2. NonBlockingVertexAiSessionService can read back real sessions from Vertex AI.
3. append_event with sequential chaining writes events into Vertex AI without blocking.
4. flush() drains all background event tasks.
5. POST /api/sessions endpoint creates a live Vertex AI session when USE_IN_MEMORY_SESSION_SERVICE=false.

Usage:
    uv run python scripts/test_live_vertex_ai_session_service.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "app"))
sys.path.insert(0, str(_REPO_ROOT))

load_dotenv(_REPO_ROOT / "app" / ".env")

from google.adk.events import Event
from starlette.testclient import TestClient

import main as app_main
from main import NonBlockingVertexAiSessionService, app


async def test_live_vertex_ai_service() -> None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "prj-hds-np-data")
    location = os.getenv("VERTEX_AI_AGENT_ENGINE_LOCATION", "us-central1")
    engine_urn = os.getenv("VERTEX_AI_AGENT_ENGINE_ID", "")
    
    # Extract numeric ID if URN format
    engine_id = engine_urn.split(":")[-1] if ":" in engine_urn else engine_urn

    print(f"Connecting to Vertex AI Session Service:")
    print(f"  Project: {project}")
    print(f"  Location: {location}")
    print(f"  Engine ID: {engine_id}")

    service = NonBlockingVertexAiSessionService(
        project=project,
        location=location,
        agent_engine_id=engine_id,
    )

    # 1. Test live create_session (without user-supplied session_id, matching Comment 6)
    print("\n1. Testing live create_session...")
    session = await service.create_session(
        app_name=engine_id,
        user_id="integration-test-user",
        state={"planned_topics": ["Pricing discussion"], "test_marker": "vertex_live_ok"},
    )
    assert session is not None
    assert session.id, "Session ID should be non-empty"
    print(f"   SUCCESS: Created live Vertex AI session ID: {session.id}")

    # 2. Test live get_session
    print("\n2. Testing live get_session...")
    fetched_session = await service.get_session(
        app_name=engine_id,
        user_id="integration-test-user",
        session_id=session.id,
    )
    assert fetched_session is not None
    assert fetched_session.id == session.id
    print(f"   SUCCESS: Fetched live session: {fetched_session.id}")
    print(f"   Session state: {fetched_session.state}")

    # 3. Test sequential event appending
    print("\n3. Testing non-blocking append_event with sequential chaining...")
    event1 = Event(
        id=f"{session.id}-ev1",
        author="user",
        timestamp=1700000000.0,
    )
    event2 = Event(
        id=f"{session.id}-ev2",
        author="agent",
        timestamp=1700000001.0,
    )

    await service.append_event(session, event1)
    await service.append_event(session, event2)
    print(f"   Appended 2 events to session {session.id}")

    # 4. Test flush()
    print("\n4. Testing flush() on shutdown...")
    await service.flush(timeout=10.0)
    assert len(service._pending_tasks) == 0
    print("   SUCCESS: All background persistence tasks flushed cleanly!")

    # 5. Test POST /api/sessions endpoint with VertexAiSessionService configured
    print("\n5. Testing POST /api/sessions with NonBlockingVertexAiSessionService...")
    original_service = app_main.session_service
    try:
        app_main.session_service = service
        client = TestClient(app)
        resp = client.post(
            "/api/sessions",
            json={
                "user_id": "rep-test-vertex-endpoint",
                "planned_topics": ["Efficacy", "Pricing"],
                "campaign_type": "standard_sales",
            },
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        print(f"   Response from POST /api/sessions: {data}")
        assert data["status"] == "ok"
        assert data["session_id"]
        # Verify that minted ID can be fetched
        minted_session = await service.get_session(
            app_name=engine_id,
            user_id=data["user_id"],
            session_id=data["session_id"],
        )
        assert minted_session is not None
        assert minted_session.id == data["session_id"]
        print(f"   SUCCESS: Minted session {data['session_id']} verified in Vertex AI!")
    finally:
        app_main.session_service = original_service


async def main() -> None:
    try:
        await test_live_vertex_ai_service()
        print("\n=======================================================")
        print("ALL LIVE VERTEX AI SESSION SERVICE CHECKS PASSED!")
        print("=======================================================")
    except Exception as exc:
        print(f"\nFAILED with exception: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
