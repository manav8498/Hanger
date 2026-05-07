# Changelog

## v0.2.0

- Added the HTTP-backed `hangar` CLI for agents, environments, sessions, streaming, admin key creation, health, and version checks.
- Added `/healthz` and `/readyz` with database, DBOS/runtime, and Docker component status.
- Added a read-only static dashboard at `/dashboard/` for local instance health, resource tables, and live session event streams.
- Added `scripts/install.sh` for one-command local installation with Docker Compose, `.env` generation, health waiting, and next-step output.
- Expanded the README with quickstart, API compatibility, architecture, configuration, CLI usage, dashboard notes, and limitations.
- Removed Alembic runtime setup in favor of `Base.metadata.create_all` for v0.1/v0.2 schema creation.
- Moved cold Docker session provisioning work off the FastAPI event loop.

## v0.1.0-alpha

- Implemented the Phase 1 Claude Managed Agents compatibility surface: Agent, Environment, Session, and Event primitives.
- Added Anthropic Python SDK compatibility for local `base_url` usage without SDK monkey-patching.
- Added Postgres-backed storage, DBOS-backed session workflow runtime, and Docker container provisioning for sessions.
- Added SSE event streaming at `/v1/sessions/{id}/events/stream` with `Last-Event-ID` resume support.
- Added API-key authentication, admin API-key creation, audit logging, and a deterministic `hgr_test_key` local-development path.
- Added fallback harness behavior for test and no-API-key development paths.
