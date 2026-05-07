from __future__ import annotations

import asyncio

from httpx import AsyncClient

from hangar.api.app import app
from hangar.streaming.sse import stream_session_events
from tests.helpers import AUTH_HEADERS, create_agent, create_environment


async def test_sse_stream_receives_agent_events(client: AsyncClient) -> None:
    agent = await create_agent(client)
    environment = await create_environment(client)
    created = await client.post(
        "/v1/sessions",
        headers=AUTH_HEADERS,
        json={"agent": agent["id"], "environment_id": environment["id"]},
    )
    assert created.status_code == 200
    session_id = str(created.json()["id"])

    for _ in range(20):
        poll = await client.get(f"/v1/sessions/{session_id}", headers=AUTH_HEADERS)
        if poll.json()["status"] == "running":
            break
        await asyncio.sleep(0.05)

    generator = stream_session_events(app.state.store, session_id, last_event_id=None)
    first_event = asyncio.create_task(generator.__anext__())

    send = await client.post(
        f"/v1/sessions/{session_id}/events",
        headers=AUTH_HEADERS,
        json={
            "events": [
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": "hi"}],
                }
            ]
        },
    )
    assert send.status_code == 200

    seen = {str((await asyncio.wait_for(first_event, timeout=1))["event"])}
    for _ in range(10):
        event = await asyncio.wait_for(generator.__anext__(), timeout=1)
        seen.add(str(event["event"]))
        if event["event"] == "session.status_idle":
            break
    await generator.aclose()

    assert "agent.message" in seen
    assert "session.status_idle" in seen
