from __future__ import annotations

from httpx import AsyncClient

from hangar.api.app import app


async def test_unauthenticated_request_returns_401(client: AsyncClient) -> None:
    response = await client.get("/v1/agents")

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "http_error"


async def test_valid_bearer_key(client: AsyncClient) -> None:
    key = await _create_key(client)
    response = await client.get("/v1/agents", headers={"Authorization": f"Bearer {key}"})

    assert response.status_code == 200


async def test_valid_x_api_key(client: AsyncClient) -> None:
    key = await _create_key(client)
    response = await client.get("/v1/agents", headers={"x-api-key": key})

    assert response.status_code == 200


async def test_audit_row_written(client: AsyncClient) -> None:
    key = await _create_key(client)

    before = await app.state.store.count_audit_events()
    response = await client.get("/v1/agents", headers={"x-api-key": key})
    after = await app.state.store.count_audit_events()

    assert response.status_code == 200
    assert after > before


async def _create_key(client: AsyncClient) -> str:
    response = await client.post(
        "/v1/api-keys",
        headers={"x-admin-token": "test-admin-token"},
        json={"name": "test"},
    )
    assert response.status_code == 200
    key = response.json()["key"]
    assert key.startswith("hgr_")
    return str(key)
