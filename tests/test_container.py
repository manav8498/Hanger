from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from hangar.runtime import container
from hangar.runtime.container import ContainerHandle


async def test_provision_does_not_block_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow_sync(env_config: dict[str, Any], session_id: str) -> ContainerHandle:
        assert env_config == {}
        assert session_id == "ses_test"
        time.sleep(0.5)
        return ContainerHandle(id="x", name="x", outputs_host_path="/tmp")

    monkeypatch.setattr(container, "_provision_container_sync", slow_sync)
    monkeypatch.setenv("HANGAR_RUNTIME_MODE", "real")

    provision_task = asyncio.create_task(container.provision_container({}, "ses_test"))
    await asyncio.sleep(0.1)

    assert not provision_task.done()
    handle = await provision_task
    assert handle.id == "x"
