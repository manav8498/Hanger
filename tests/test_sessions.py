from __future__ import annotations

import asyncio
from typing import Any, cast

from httpx import AsyncClient

from tests.helpers import AUTH_HEADERS, create_agent, create_environment


async def test_session_create_running_and_terminate(client: AsyncClient) -> None:
    agent = await create_agent(client)
    environment = await create_environment(client)

    created = await client.post(
        "/v1/sessions",
        headers=AUTH_HEADERS,
        json={
            "agent": agent["id"],
            "environment_id": environment["id"],
            "title": "Quickstart session",
        },
    )
    assert created.status_code == 200
    session_id = created.json()["id"]

    running = await _wait_for_status(client, session_id, "running")
    assert running["status"] == "running"

    events = await client.get(f"/v1/sessions/{session_id}/events", headers=AUTH_HEADERS)
    event_types = {event["type"] for event in events.json()["data"]}
    assert {"session.status_starting", "session.status_running"} <= event_types

    terminated = await client.post(
        f"/v1/sessions/{session_id}/terminate",
        headers=AUTH_HEADERS,
    )
    assert terminated.status_code == 200
    assert terminated.json()["status"] == "terminated"


async def _wait_for_status(
    client: AsyncClient,
    session_id: str,
    status: str,
) -> dict[str, object]:
    for _ in range(20):
        response = await client.get(f"/v1/sessions/{session_id}", headers=AUTH_HEADERS)
        assert response.status_code == 200
        body = response.json()
        if body["status"] == status:
            return cast(dict[str, Any], body)
        await asyncio.sleep(0.05)
    raise AssertionError(f"session did not reach {status}")
