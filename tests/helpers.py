from __future__ import annotations

from typing import Any, cast

from httpx import AsyncClient

AUTH_HEADERS = {"x-api-key": "hgr_test_key"}


async def create_agent(client: AsyncClient) -> dict[str, object]:
    response = await client.post(
        "/v1/agents",
        headers=AUTH_HEADERS,
        json={
            "name": "Coding Assistant",
            "model": {"id": "claude-opus-4-7"},
            "system": "You are a helpful coding agent.",
            "tools": [{"type": "agent_toolset_20260401"}],
        },
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


async def create_environment(client: AsyncClient) -> dict[str, object]:
    response = await client.post(
        "/v1/environments",
        headers=AUTH_HEADERS,
        json={
            "name": "python-dev",
            "config": {"type": "cloud", "networking": {"type": "unrestricted"}},
        },
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())
