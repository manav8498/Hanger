# API Compatibility

Hangar targets the Claude Managed Agents API surface used by the official Anthropic Python SDK. The goal is SDK drop-in compatibility for agents, environments, sessions, event send, and event streaming. Hangar also exposes a few self-hosting routes for API-key administration, health checks, and the local dashboard.

## CMA Compatibility Matrix

| CMA area | Upstream-style operation | Hangar endpoint | Status | Notes |
|---|---|---|---|---|
| Agent | Create agent | `POST /v1/agents` | full | Returns the CMA agent shape, including `model.speed = "standard"`. |
| Agent | List agents | `GET /v1/agents` | full | Supports `limit` and `after`; `has_more` is currently always `false`. |
| Agent | Retrieve agent | `GET /v1/agents/{agent_id}` | full | Supports optional `version` query. |
| Agent | Patch agent | `PATCH /v1/agents/{agent_id}` | full | Creates a new version when fields change. |
| Agent | Archive agent | `POST /v1/agents/{agent_id}/archive` | full | Archived agents cannot be used for new sessions. |
| Agent | Delete agent | `DELETE /v1/agents/{agent_id}` | full | Returns `204 No Content`. |
| Environment | Create environment | `POST /v1/environments` | full | Supports `cloud` config. |
| Environment | List environments | `GET /v1/environments` | full | Supports `limit`; `has_more` is currently always `false`. |
| Environment | Retrieve environment | `GET /v1/environments/{environment_id}` | full | Returns the stored environment config. |
| Environment | Archive environment | `POST /v1/environments/{environment_id}/archive` | full | Archived environments cannot be used for new sessions. |
| Environment | Delete environment | `DELETE /v1/environments/{environment_id}` | full | Returns `204 No Content`; active sessions can block deletion. |
| Session | Create session | `POST /v1/sessions` | full | Returns immediately with provisioning in the background. |
| Session | List sessions | `GET /v1/sessions` | full | Supports `limit`; `has_more` is currently always `false`. |
| Session | Retrieve session | `GET /v1/sessions/{session_id}` | full | Returns the current session status. |
| Session | Terminate session | `POST /v1/sessions/{session_id}/terminate` | full | Emits `session.status_terminated`. |
| Session | Delete session | `DELETE /v1/sessions/{session_id}` | full | Terminates the container if present, then deletes the row. |
| Event | Send events | `POST /v1/sessions/{session_id}/events` | full | Accepts `user.message` events and forwards them to the workflow runtime. |
| Event | List events | `GET /v1/sessions/{session_id}/events` | full | Supports `after_id` and `limit`. |
| Event | Stream events | `GET /v1/sessions/{session_id}/events/stream` | full | SSE stream with `Last-Event-ID` resume support. |
| Vault | Secret storage | - | not yet | No vault primitive exists in Hangar v0.2. |
| Networking restrictions | Enforce limited networking | accepted, not enforced | partial | The API accepts limited networking config, but containers do not enforce egress policy yet. |
| Custom tool action pause | `requires_action` event flow | - | partial | `session.status_idle` with `end_turn` is supported; custom-tool result pause/resume is not complete in v0.2. |

## Hangar-Only Routes

| Purpose | Endpoint | Auth | Notes |
|---|---|---|---|
| Simple root check | `GET /` | none | Returns `{"hangar": "ok", "version": "..."}`. |
| Health check | `GET /healthz` | none | Returns component status for database, DBOS/runtime, and Docker. |
| Readiness check | `GET /readyz` | none | Same body as `/healthz`; returns `503` when status is not `ok`. |
| Create API key | `POST /v1/api-keys` | admin token | Requires `x-admin-token`. |
| Dashboard redirect | `GET /dashboard` | none | Redirects to `/dashboard/`. |
| Dashboard app | `GET /dashboard/` | none | Serves the static dashboard shell; API calls still require an API key. |

## Headers

The following HTTP headers are accepted on requests:

| Header | Status | Notes |
|---|---|---|
| `Authorization: Bearer <key>` | accepted | The Anthropic Python SDK uses this by default. |
| `x-api-key: <key>` | accepted | Either header works; Hangar checks both. |
| `anthropic-beta: managed-agents-2026-04-01` | accepted, ignored | Hangar always behaves as if the beta header were set. |
| `Last-Event-ID: <int>` | accepted | On `/v1/sessions/{id}/events/stream` for SSE resume. |
| `x-admin-token: <token>` | accepted | Required only for `POST /v1/api-keys`. |

## Response shapes

All Hangar endpoints return JSON with the same field shapes
as the documented Anthropic Claude Managed Agents API. Errors
use the Anthropic envelope:

```json
{"error": {"type": "...", "message": "..."}}
```

The Anthropic Python SDK's error parser unwraps this envelope
correctly. Hangar response shapes are also exercised by the
SDK in `tests/test_compat_anthropic_sdk.py`, which fails if
any field is missing or mistyped.

## What's not compatible

- The Anthropic vault primitive is not implemented. Pass
  secrets via host environment variables instead.
- The `limited` networking config is accepted on environment
  create but not enforced inside session containers - sessions
  currently get unrestricted egress regardless of the config
  value.
- The `requires_action` event flow for custom-tool result
  pause/resume is not yet supported. Sessions that complete
  normally with `end_turn` work; sessions that would otherwise
  pause for a custom tool result do not currently round-trip.
- Anthropic-hosted spans, traces, and analytics are not
  mirrored.

## Verifying compatibility yourself

The compat test that gates every release is
`tests/test_compat_anthropic_sdk.py`. It uses the unmodified
Anthropic Python SDK and runs the full lifecycle. To run it
against your own Hangar instance:

```sh
HANGAR_RUN_COMPAT=1 HANGAR_URL=http://localhost:8080 \
  HANGAR_API_KEY=hgr_test_key make compat
```

Three tests run: `test_create_agent`, `test_create_environment`,
`test_full_session_lifecycle`. All three must pass before any
Hangar release is tagged.
