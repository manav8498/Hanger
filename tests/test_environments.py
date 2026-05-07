from __future__ import annotations

from httpx import AsyncClient

from tests.helpers import AUTH_HEADERS


async def test_environment_round_trip_preserves_config(client: AsyncClient) -> None:
    config = {
        "type": "cloud",
        "packages": {"pip": ["pandas"], "npm": []},
        "networking": {"type": "unrestricted"},
    }
    created = await client.post(
        "/v1/environments",
        headers=AUTH_HEADERS,
        json={"name": "python-dev", "config": config},
    )
    assert created.status_code == 200

    fetched = await client.get(
        f"/v1/environments/{created.json()['id']}",
        headers=AUTH_HEADERS,
    )

    assert fetched.status_code == 200
    assert fetched.json()["config"] == config


async def test_environment_validation_errors(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/environments",
        headers=AUTH_HEADERS,
        json={"name": "bad", "config": {"type": "cloud", "networking": {"type": "blocked"}}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "invalid_request_error"


async def test_archive_environment(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/environments",
        headers=AUTH_HEADERS,
        json={"name": "archive-me", "config": {"type": "cloud"}},
    )
    assert created.status_code == 200

    response = await client.post(
        f"/v1/environments/{created.json()['id']}/archive",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["archived_at"] is not None
