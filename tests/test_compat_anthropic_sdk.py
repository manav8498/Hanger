"""
Compatibility test: the official Anthropic Python SDK works against Hangar.

This test is the contract with the outside world. If it fails, the
implementation is wrong, not the test. Never modify this test to make
it pass.
"""
from __future__ import annotations

import os
import time
from typing import Any

import pytest
from anthropic import Anthropic

pytestmark = pytest.mark.skipif(
    os.environ.get("HANGAR_RUN_COMPAT") != "1",
    reason="compat test requires a running Hangar stack",
)

HANGAR_URL = os.environ.get("HANGAR_URL", "http://localhost:8080")
HANGAR_API_KEY = os.environ.get("HANGAR_API_KEY", "hgr_test_key")


@pytest.fixture
def client() -> Anthropic:
    return Anthropic(base_url=HANGAR_URL, api_key=HANGAR_API_KEY)


def test_create_agent(client: Anthropic) -> None:
    agent = client.beta.agents.create(
        name="compat-test-agent",
        model={"id": "claude-opus-4-7"},
        system="You are a helpful coding agent. Be brief.",
        tools=[{"type": "agent_toolset_20260401"}],
    )
    assert agent.id.startswith("agent_")
    assert agent.version == 1
    assert agent.model.id == "claude-opus-4-7"
    assert agent.model.speed == "standard"


def test_create_environment(client: Anthropic) -> None:
    env = client.beta.environments.create(
        name="compat-test-env",
        config={"type": "cloud", "networking": {"type": "unrestricted"}},
    )
    assert env.id.startswith("env_")


def test_full_session_lifecycle(client: Anthropic) -> None:
    agent = client.beta.agents.create(
        name="compat-test-lifecycle",
        model={"id": "claude-opus-4-7"},
        system="When asked simple questions, answer in one word.",
        tools=[{"type": "agent_toolset_20260401"}],
    )
    env = client.beta.environments.create(
        name="compat-test-lifecycle-env",
        config={"type": "cloud", "networking": {"type": "unrestricted"}},
    )

    session = client.beta.sessions.create(
        agent=agent.id,
        environment_id=env.id,
        title="Compat lifecycle test",
    )
    assert session.id.startswith("ses_")

    deadline = time.time() + 60
    while time.time() < deadline:
        current = client.beta.sessions.retrieve(session.id)
        if current.status == "running":
            break
        time.sleep(1)
    else:
        pytest.fail(f"Session never reached running status: {current.status}")

    saw_message = False
    saw_idle = False

    with client.beta.sessions.events.stream(session.id) as stream:
        client.beta.sessions.events.send(
            session.id,
            events=[
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": "What is 2+2?"}],
                }
            ],
        )

        for event in stream:
            if event.type == "agent.message":
                saw_message = True
            elif event.type == "session.status_idle":
                if _stop_reason_type(event.stop_reason) == "end_turn":
                    saw_idle = True
                    break

    assert saw_message, "Never received agent.message"
    assert saw_idle, "Never received session.status_idle with end_turn"

    client.beta.sessions.delete(session.id)


def _stop_reason_type(stop_reason: Any) -> str | None:
    if stop_reason is None:
        return None
    if isinstance(stop_reason, dict):
        value = stop_reason.get("type")
        return str(value) if value is not None else None
    value = getattr(stop_reason, "type", None)
    return str(value) if value is not None else None
