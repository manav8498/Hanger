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
