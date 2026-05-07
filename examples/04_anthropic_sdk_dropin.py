from __future__ import annotations

import os
import sys
import time

from anthropic import Anthropic

client = Anthropic(
    base_url=os.environ.get("HANGAR_URL", "http://localhost:8080"),
    api_key=os.environ.get("HANGAR_API_KEY", "hgr_test_key"),
)

agent = client.beta.agents.create(
    name="dropin-example-agent",
    model={"id": "claude-opus-4-7"},
    system="When asked simple questions, answer in one word.",
    tools=[{"type": "agent_toolset_20260401"}],
)
env = client.beta.environments.create(
    name="dropin-example-env",
    config={"type": "cloud", "networking": {"type": "unrestricted"}},
)
session = client.beta.sessions.create(
    agent=agent.id,
    environment_id=env.id,
    title="Drop-in SDK example",
)

deadline = time.time() + 60
while time.time() < deadline:
    current = client.beta.sessions.retrieve(session.id)
    if current.status == "running":
        break
    time.sleep(1)
else:
    raise RuntimeError("Session did not reach running state")

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
        sys.stdout.write(f"{event}\n")
        if event.type == "session.status_idle":
            break
