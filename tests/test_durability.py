from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from hangar.store import MemoryStore
from hangar.utils.ids import new_id
from hangar.workflows import session as session_workflow_module
from hangar.workflows.steps import configure_steps, emit_event, update_session


async def test_replayed_turn_completes_without_duplicate_agent_events(monkeypatch: Any) -> None:
    store = MemoryStore()
    configure_steps(store)
    agent = await store.create_agent(
        {
            "id": new_id("agent"),
            "name": "durability-agent",
            "model": {"id": "claude-opus-4-7", "speed": "standard"},
            "system": "Be brief.",
            "tools": [{"type": "agent_toolset_20260401"}],
            "mcp_servers": [],
            "skills": [],
            "metadata": {},
        }
    )
    environment = await store.create_environment(
        {
            "id": new_id("env"),
            "name": "durability-env",
            "config": {"type": "cloud", "networking": {"type": "unrestricted"}},
        }
    )
    session = await store.create_session(
        {
            "id": new_id("ses"),
            "agent_id": agent["id"],
            "agent_version": agent["version"],
            "environment_id": environment["id"],
            "title": "durability",
        }
    )
    session_id = str(session["id"])
    user_events = [
        {
            "type": "user.message",
            "content": [{"type": "text", "text": "What is 2+2?"}],
        }
    ]
    calls = 0

    async def flaky_turn(_session_id: str, _events: list[dict[str, Any]]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated worker death")
        return {
            "events": [
                {
                    "type": "agent.message",
                    "content": {"content": [{"type": "text", "text": "4"}]},
                },
                {
                    "type": "session.status_idle",
                    "content": {"stop_reason": {"type": "end_turn"}},
                },
            ],
            "session_patch": {"status": "idle", "stop_reason": {"type": "end_turn"}},
        }

    monkeypatch.setattr(session_workflow_module, "run_agent_turn", flaky_turn)
    run_agent_turn = cast(
        Callable[[str, list[dict[str, Any]]], Awaitable[dict[str, Any]]],
        vars(session_workflow_module)["run_agent_turn"],
    )

    await emit_event(session_id, "user.message", {"content": user_events[0]["content"]})
    try:
        await run_agent_turn(session_id, user_events)
    except RuntimeError:
        pass

    assert [event["type"] for event in await store.list_events(session_id)] == ["user.message"]

    turn_result = await run_agent_turn(session_id, user_events)
    for event in turn_result["events"]:
        await emit_event(session_id, event["type"], event["content"])
    await update_session(session_id, turn_result["session_patch"])

    events = await store.list_events(session_id)
    assert [event["type"] for event in events].count("agent.message") == 1
    assert [event["type"] for event in events].count("session.status_idle") == 1
    assert (await store.get_session(session_id) or {})["status"] == "idle"
