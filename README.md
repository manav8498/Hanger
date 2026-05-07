Self-hostable, API-compatible runtime for Anthropic's Claude Managed Agents.

## The 90-second pitch

Hangar runs the same four primitives as Anthropic's Claude Managed Agents - Agent, Environment, Session, Event - on your own infrastructure with `docker compose up`.
It exists for teams that want the hosted CMA API shape without sending agent state to a hosted control plane.
If you already use the Anthropic Python SDK and want to point it at your own server, Hangar keeps the client-side change to `base_url`.

## Why Hangar

- **Drop-in compatible.** The Anthropic Python SDK works unchanged - just change the `base_url`.
- **Self-hostable, no platform tax.** One Postgres, one FastAPI process, one Docker daemon. No managed plane.
- **Model-agnostic where it can be.** Today targets Claude through the Claude Agent SDK; the runtime layer is model-neutral and other providers can be added.

## Quickstart

### One-line install

```sh
curl -fsSL https://raw.githubusercontent.com/manav8498/Hangar/main/scripts/install.sh | sh
```

The script clones the repo to `~/hangar`, generates a random admin token, brings up `docker compose`, and waits for the stack to be healthy.
Use `HANGAR_DIR=/path/to/dir` to install elsewhere, or pass `--force` with `sh -s -- --force` to overwrite an existing install.

### Manual install

```sh
git clone https://github.com/manav8498/Hangar.git
cd Hangar
cp .env.example .env
docker compose up -d
```

Run the shipped Anthropic SDK drop-in example:

```sh
uv run python examples/04_anthropic_sdk_dropin.py
```

The example code is:

```python
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
```

Expected event sequence:

```text
session.status_starting
session.status_running
agent.message: 4
session.status_idle
```

See the [CLI usage](#cli-usage) section for everything else.

## API compatibility

Hangar targets the Phase 1 Claude Managed Agents surface from the [Anthropic CMA docs](https://docs.anthropic.com/en/docs/agents-and-tools/managed-agents): agents, environments, sessions, event send, and event streaming are compatible with the Anthropic Python SDK, while vaults are not implemented and networking restrictions are accepted but not enforced yet.

| CMA primitive | Hangar endpoint | Status |
|---|---|---|
| Agent | `POST /v1/agents` | full |
| Environment | `POST /v1/environments` | full |
| Session | `POST /v1/sessions` | full |
| Event (send) | `POST /v1/sessions/{id}/events` | full |
| Event (stream) | `GET /v1/sessions/{id}/events/stream` | full |
| Vault | - | not yet |
| Networking restrictions | accepted, not enforced | partial |

## Architecture

FastAPI on port 8080 fronts a Postgres-backed event log and a DBOS workflow per session.
Each running session has a Docker container sandbox where Claude Agent SDK tool calls execute.

```mermaid
flowchart LR
    SDK[Anthropic SDK] -->|HTTPS| API[FastAPI :8080]
    API --> PG[(Postgres)]
    API --> DBOS[DBOS workflow]
    DBOS --> CONT[Docker container]
    CONT -->|Claude Agent SDK| ANT[Anthropic API]
    PG -.->|LISTEN/NOTIFY| API
    API -->|SSE| SDK
```

## Configuration

| Name | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://hangar:hangar@postgres:5432/hangar` | Postgres connection string. |
| `HANGAR_ADMIN_TOKEN` | `dev-admin-token` | Required to create API keys via `POST /v1/api-keys`; `.env.example` sets `change-me` for local clones. |
| `ANTHROPIC_API_KEY` | (none) | Forwarded to the Claude Agent SDK inside session containers. Without it, Hangar uses a deterministic fallback harness. |
| `HANGAR_RUNTIME_MODE` | `docker` | Set to `fake` to skip Docker (used by tests). |
| `HANGAR_STORAGE` | (auto) | Set to `memory` to bypass Postgres entirely (used by tests). |
| `HANGAR_DOCKER_HOST_SESSIONS_ROOT` | `./.hangar/sessions` | Host path mounted into session containers as `/mnt/session/outputs`. |
| `HANGAR_USE_CLAUDE_AGENT_SDK` | `1` | Set to `0` to disable the SDK path and always use the fallback harness. |
| `HANGAR_ENABLE_DBOS` | `1` | Set to `0` to use the local asyncio runtime instead of DBOS. Local runtime loses durability across restarts. |
| `HANGAR_DBOS_LOG_LEVEL` | `WARNING` | Passed through to DBOS. |
| `HANGAR_RUN_COMPAT` | (unset) | Set to `1` to enable the Anthropic SDK compat test against a running stack. |
| `HANGAR_RUN_DURABILITY_E2E` | (unset) | Set to `1` to enable the docker-restart durability test. |
| `HANGAR_SESSION_BASE_IMAGE` | `python:3.12-slim` | Base image for session containers. |

## CLI usage

All CLI commands default to `--url http://localhost:8080` and `--api-key $HANGAR_API_KEY`, falling back to `hgr_test_key` for local development.

### Admin

```sh
hangar admin create-api-key --name dev
hangar admin health
hangar version
```

### Agents

```sh
hangar agent create --name "test-agent" --model "claude-opus-4-7" --system "Be brief."
hangar agent list
hangar agent get agent_xxx
hangar agent archive agent_xxx
```

### Environments

```sh
hangar env create --name "default-env"
hangar env list
hangar env get env_xxx
```

### Sessions

```sh
# Create your first agent and run a session
hangar agent create --name "test-agent" --model "claude-opus-4-7" \
    --system "Be brief."
hangar env create --name "default-env"
hangar session create --agent agent_xxx --env env_xxx
hangar session send ses_xxx --message "What is 2+2?"
hangar session stream ses_xxx
hangar session terminate ses_xxx
```

## Dashboard

A read-only web dashboard is available at `http://localhost:8080/dashboard/` once the stack is up.
Use it to watch session events stream in real time during local development.
The dashboard is observe-only - for mutations, use the CLI or API directly.
API key prompt appears on first load; the key is stored in browser localStorage.

## Limitations

- No vault primitive. Secrets must be passed via environment variables on the host.
- No networking enforcement. The `limited` networking config is accepted by the API but not yet enforced inside the container.
- Single-org only. No multi-tenant separation in v0.1 / v0.2.
- No agent-to-agent calls.
- No alternative sandbox runtimes (Firecracker, gVisor) yet - Docker containers only.
- The dashboard is observe-only. Use the CLI or API for any mutations.

## Contributing

See `AGENTS.md` for the architecture and code style enforced by contributors.
Open an issue before sending a PR for anything bigger than a typo.

## License

Apache 2.0. See `LICENSE`.
