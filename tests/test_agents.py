from __future__ import annotations

from httpx import AsyncClient

from tests.helpers import AUTH_HEADERS, create_agent


async def test_create_and_get_agent(client: AsyncClient) -> None:
    created = await create_agent(client)

    response = await client.get(f"/v1/agents/{created['id']}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["model"] == {"id": "claude-opus-4-7", "speed": "standard"}
    assert body["tools"][0]["default_config"]["permission_policy"]["type"] == "always_allow"


async def test_patch_creates_new_version(client: AsyncClient) -> None:
    created = await create_agent(client)

    response = await client.patch(
        f"/v1/agents/{created['id']}",
        headers=AUTH_HEADERS,
        json={"system": "Updated prompt."},
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2

    v1 = await client.get(f"/v1/agents/{created['id']}?version=1", headers=AUTH_HEADERS)
    assert v1.status_code == 200
    assert v1.json()["system"] == "You are a helpful coding agent."


async def test_archive_prevents_new_sessions(client: AsyncClient) -> None:
    agent = await create_agent(client)
    env_response = await client.post(
        "/v1/environments",
        headers=AUTH_HEADERS,
        json={"name": "env", "config": {"type": "cloud"}},
    )
    assert env_response.status_code == 200

    archive = await client.post(f"/v1/agents/{agent['id']}/archive", headers=AUTH_HEADERS)
    assert archive.status_code == 200

    response = await client.post(
        "/v1/sessions",
        headers=AUTH_HEADERS,
        json={"agent": agent["id"], "environment_id": env_response.json()["id"]},
    )

    assert response.status_code == 409
