from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient

from hangar.api import health as health_module


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"hangar": "ok", "version": "0.1.0-dev"}


async def test_healthz_memory_store_path(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["database"] == {"status": "skipped", "reason": "memory store"}
    assert body["components"]["dbos"] == {"status": "skipped", "reason": "local runtime"}
    assert body["components"]["docker"] == {"status": "skipped", "reason": "fake mode"}


async def test_readyz_returns_200_when_ok(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readyz_returns_503_when_error(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def error_docker() -> dict[str, object]:
        return {"status": "error", "reason": "docker daemon unreachable"}

    monkeypatch.setattr(health_module, "check_docker", error_docker)

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["components"]["docker"]["status"] == "error"


async def test_healthz_db_failure_marks_error(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_database(app: Any) -> dict[str, object]:
        del app
        raise RuntimeError("database exploded")

    monkeypatch.setattr(health_module, "check_database", broken_database)

    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["components"]["database"]["status"] == "error"
    assert "RuntimeError" in body["components"]["database"]["reason"]


async def test_healthz_timeout_marks_degraded(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow_docker() -> dict[str, object]:
        await asyncio.sleep(1)
        return {"status": "ok", "container_count": 0}

    monkeypatch.setattr(health_module, "check_docker", slow_docker)

    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["docker"] == {"status": "degraded", "reason": "timeout"}
