from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

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


@pytest.mark.skipif(
    os.environ.get("HANGAR_RUN_DURABILITY_E2E") != "1",
    reason="requires a running docker compose stack",
)
def test_docker_restart_mid_turn_completes_without_duplicate_events() -> None:
    base_url = os.environ.get("HANGAR_URL", "http://localhost:8080")
    repo_root = Path(__file__).resolve().parents[1]

    with httpx.Client(base_url=base_url, timeout=10) as client:
        headers = _durability_auth_headers(client)
        agent = client.post(
            "/v1/agents",
            headers=headers,
            json={
                "name": "durability-e2e-agent",
                "model": {"id": "claude-opus-4-7"},
                "system": "Answer simple questions in one word.",
                "tools": [{"type": "agent_toolset_20260401"}],
            },
        ).raise_for_status().json()
        environment = client.post(
            "/v1/environments",
            headers=headers,
            json={
                "name": "durability-e2e-env",
                "config": {"type": "cloud", "networking": {"type": "unrestricted"}},
            },
        ).raise_for_status().json()
        session = client.post(
            "/v1/sessions",
            headers=headers,
            json={"agent": agent["id"], "environment_id": environment["id"]},
        ).raise_for_status().json()
        session_id = str(session["id"])

        _wait_for_session_status(client, headers, session_id, "running")
        client.post(
            f"/v1/sessions/{session_id}/events",
            headers=headers,
            json={
                "events": [
                    {
                        "type": "user.message",
                        "content": [{"type": "text", "text": "What is 2+2?"}],
                    }
                ]
            },
        ).raise_for_status()

    subprocess.run(["docker", "compose", "kill", "api"], cwd=repo_root, check=True, env=_compose_env())
    subprocess.run(["docker", "compose", "up", "-d", "api"], cwd=repo_root, check=True, env=_compose_env())
    _wait_for_health(base_url)

    with httpx.Client(base_url=base_url, timeout=10) as client:
        headers = _durability_auth_headers(client)
        events = _wait_for_event_types(
            client,
            headers,
            session_id,
            required={"agent.message", "session.status_idle"},
        )
        event_types = [event["type"] for event in events]
        assert event_types.count("user.message") == 1
        assert event_types.count("session.status_idle") == 1
        client.delete(f"/v1/sessions/{session_id}", headers=headers)


def _durability_auth_headers(client: httpx.Client) -> dict[str, str]:
    if os.environ.get("HANGAR_API_KEY"):
        return {"x-api-key": os.environ["HANGAR_API_KEY"]}
    admin_token = os.environ.get("HANGAR_E2E_ADMIN_TOKEN") or os.environ.get("HANGAR_ADMIN_TOKEN")
    if not admin_token:
        pytest.fail("HANGAR_API_KEY or HANGAR_E2E_ADMIN_TOKEN is required")
    response = client.post(
        "/v1/api-keys",
        headers={"x-admin-token": admin_token},
        json={"name": "durability-e2e"},
    )
    return {"x-api-key": str(response.raise_for_status().json()["key"])}


def _compose_env() -> dict[str, str]:
    env = os.environ.copy()
    if os.environ.get("HANGAR_E2E_ADMIN_TOKEN"):
        env["HANGAR_ADMIN_TOKEN"] = os.environ["HANGAR_E2E_ADMIN_TOKEN"]
    return env


def _wait_for_health(base_url: str) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/", timeout=2)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError("API did not restart")


def _wait_for_session_status(
    client: httpx.Client,
    headers: dict[str, str],
    session_id: str,
    expected: str,
) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        response = client.get(f"/v1/sessions/{session_id}", headers=headers)
        if response.raise_for_status().json()["status"] == expected:
            return
        time.sleep(1)
    raise AssertionError(f"Session did not reach {expected}")


def _wait_for_event_types(
    client: httpx.Client,
    headers: dict[str, str],
    session_id: str,
    required: set[str],
) -> list[dict[str, Any]]:
    deadline = time.time() + 90
    while time.time() < deadline:
        response = client.get(f"/v1/sessions/{session_id}/events", headers=headers)
        events = cast(list[dict[str, Any]], response.raise_for_status().json()["data"])
        event_types = {str(event["type"]) for event in events}
        if required <= event_types:
            return events
        time.sleep(1)
    raise AssertionError(f"Timed out waiting for events: {sorted(required)}")
