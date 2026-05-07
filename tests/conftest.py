from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["HANGAR_STORAGE"] = "memory"
os.environ["HANGAR_RUNTIME_MODE"] = "fake"
os.environ["HANGAR_ADMIN_TOKEN"] = "test-admin-token"

from hangar.api.app import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as test_client:
            yield test_client
