from __future__ import annotations

from typing import Any

from dbos import DBOS

from hangar.runtime.container import provision_container
from hangar.runtime.harness import collect_turn
from hangar.store import Store

_store: Store | None = None


def configure_steps(store: Store) -> None:
    global _store
    _store = store


def workflow_store() -> Store:
    if _store is None:
        raise RuntimeError("Workflow store is not configured")
    return _store


@DBOS.step(name="provision_session_container", retries_allowed=True, max_attempts=3)
async def provision_session_container(
    env_config: dict[str, Any],
    session_id: str,
) -> dict[str, str]:
    handle = await provision_container(env_config, session_id)
    return {
        "id": handle.id,
        "name": handle.name,
        "outputs_host_path": handle.outputs_host_path,
    }


@DBOS.step(name="emit_event")
async def emit_event(
    session_id: str,
    event_type: str,
    content: dict[str, Any],
) -> dict[str, Any]:
    return await workflow_store().create_event(session_id, event_type, content)


@DBOS.step(name="update_session")
async def update_session(session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    return await workflow_store().update_session(session_id, patch)


@DBOS.step(name="load_session_environment")
async def load_session_environment(session_id: str) -> dict[str, Any]:
    store = workflow_store()
    session = await store.get_session(session_id)
    if session is None:
        raise RuntimeError(f"Session not found: {session_id}")
    environment = await store.get_environment(str(session["environment_id"]))
    if environment is None:
        raise RuntimeError(f"Environment not found: {session['environment_id']}")
    return dict(environment["config"])


@DBOS.step(name="run_agent_turn")
async def run_agent_turn(
    session_id: str,
    user_events: list[dict[str, Any]],
) -> dict[str, Any]:
    return await collect_turn(workflow_store(), session_id, user_events)
