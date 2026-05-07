from __future__ import annotations

import asyncio

from httpx import AsyncClient

from tests.helpers import AUTH_HEADERS, create_agent, create_environment


async def test_user_message_produces_agent_message_and_idle(client: AsyncClient) -> None:
    session_id = await _running_session(client)

    response = await client.post(
        f"/v1/sessions/{session_id}/events",
        headers=AUTH_HEADERS,
        json={
            "events": [
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": "What is 2+2?"}],
                }
            ]
        },
    )
    assert response.status_code == 200

    event_types = await _wait_for_event_types(client, session_id)
    assert "agent.message" in event_types
    assert "session.status_idle" in event_types


async def _running_session(client: AsyncClient) -> str:
    agent = await create_agent(client)
    environment = await create_environment(client)
    response = await client.post(
        "/v1/sessions",
        headers=AUTH_HEADERS,
        json={"agent": agent["id"], "environment_id": environment["id"]},
    )
    assert response.status_code == 200
    session_id = str(response.json()["id"])
    for _ in range(20):
        poll = await client.get(f"/v1/sessions/{session_id}", headers=AUTH_HEADERS)
        if poll.json()["status"] == "running":
            return session_id
        await asyncio.sleep(0.05)
    raise AssertionError("session did not reach running")


async def _wait_for_event_types(client: AsyncClient, session_id: str) -> set[str]:
    for _ in range(20):
        response = await client.get(f"/v1/sessions/{session_id}/events", headers=AUTH_HEADERS)
        event_types = {event["type"] for event in response.json()["data"]}
        if "session.status_idle" in event_types:
            return event_types
        await asyncio.sleep(0.05)
    raise AssertionError("agent events did not arrive")
