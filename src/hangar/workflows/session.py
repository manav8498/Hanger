from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from dbos import DBOS

from hangar.utils.time import utc_now
from hangar.workflows.steps import (
    emit_event,
    load_session_environment,
    provision_session_container,
    run_agent_turn,
    update_session,
)

USER_EVENTS_TOPIC = "user_events"
WORKFLOW_STATUSES = {"starting", "running", "idle"}
ReceiveMessage = Callable[[], Awaitable[Any]]


@DBOS.workflow(name="session_workflow")
async def session_workflow(session_id: str) -> None:
    await _session_loop(session_id, _dbos_recv)


async def run_local_session_workflow(session_id: str, receive: ReceiveMessage) -> None:
    await _session_loop(session_id, receive)


async def _session_loop(session_id: str, receive: ReceiveMessage) -> None:
    await emit_event(
        session_id,
        "session.status_starting",
        {"session_id": session_id, "ts": utc_now().isoformat()},
    )

    environment_config = await load_session_environment(session_id)
    handle = await provision_session_container(environment_config, session_id)
    await update_session(session_id, {"status": "running", "container_id": handle["id"]})
    await emit_event(
        session_id,
        "session.status_running",
        {"session_id": session_id, "ts": utc_now().isoformat()},
    )

    while True:
        message = await receive()
        if not isinstance(message, dict):
            continue
        if message.get("type") == "terminate":
            break
        user_events = message.get("events")
        if not isinstance(user_events, list):
            continue

        await update_session(session_id, {"status": "running", "stop_reason": None})
        for event in user_events:
            if isinstance(event, dict):
                await emit_event(
                    session_id,
                    str(event.get("type", "user.message")),
                    _event_content(event),
                )

        turn_result = await run_agent_turn(session_id, _typed_events(user_events))
        for event in turn_result.get("events", []):
            if isinstance(event, dict):
                event_type = event.get("type")
                content = event.get("content")
                if isinstance(event_type, str) and isinstance(content, dict):
                    await emit_event(session_id, event_type, content)

        session_patch = turn_result.get("session_patch")
        if isinstance(session_patch, dict) and session_patch:
            await update_session(session_id, session_patch)


def _event_content(event: dict[str, Any]) -> dict[str, Any]:
    content = event.get("content")
    if isinstance(content, list):
        return {"content": content}
    if isinstance(content, dict):
        return content
    return {}


def _typed_events(events: list[Any]) -> list[dict[str, Any]]:
    return [event for event in events if isinstance(event, dict)]


async def _dbos_recv() -> Any:
    return await DBOS.recv_async(USER_EVENTS_TOPIC, timeout_seconds=60 * 60 * 24 * 365)
