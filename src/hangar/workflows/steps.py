from __future__ import annotations

from typing import Any

from hangar.runtime.container import ContainerHandle, provision_container
from hangar.runtime.harness import run_turn
from hangar.store import Store


async def provision_session_container(
    env_config: dict[str, Any],
    session_id: str,
) -> ContainerHandle:
    return await provision_container(env_config, session_id)


async def emit_event(
    store: Store,
    session_id: str,
    event_type: str,
    content: dict[str, Any],
) -> dict[str, Any]:
    return await store.create_event(session_id, event_type, content)


async def run_agent_turn(
    store: Store,
    session_id: str,
    user_events: list[dict[str, Any]],
) -> None:
    await run_turn(store, session_id, user_events)
