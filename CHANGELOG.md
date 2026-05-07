# Changelog

All notable changes to Hangar are documented in this file.
Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-05-08

### Added
- One-line install via `scripts/install.sh` (`curl -fsSL ... | sh`).
- Read-only web dashboard at `/dashboard/` for live session
  observation. Vanilla JS, dark mode, hash-routed across five
  views, live SSE event stream with `Last-Event-ID` resume.
- `/healthz` and `/readyz` endpoints with concurrent component
  checks (database, dbos, docker) and 500ms per-check timeouts.
- Full HTTP-backed CLI: `hangar agent|env|session|admin|version`
  with global `--url` and `--api-key` flags.
- `hangar admin health` command for component-level status.
- `docs/api-compat.md` documenting the 25-row endpoint
  compatibility matrix.

### Changed
- README rewritten with Quickstart, Anthropic SDK drop-in
  example, configuration table, and architecture diagram.
- `HANGAR_SESSION_BASE_IMAGE` default corrected from a
  placeholder image tag to `python:3.12-slim`.
- Cold Docker session provisioning moved off the FastAPI
  event loop via `asyncio.to_thread`.

### Removed
- Alembic dependency and `migrations/` directory. DBOS owns
  schema management; the FastAPI lifespan calls
  `Base.metadata.create_all` for v0.1/v0.2 schema bootstrap.

## [0.1.0-alpha] - 2026-05-06

### Added
- Initial four-primitive API surface (Agent, Environment,
  Session, Event) compatible with Anthropic's Claude Managed
  Agents.
- Anthropic Python SDK drop-in compatibility, verified by
  `tests/test_compat_anthropic_sdk.py`.
- DBOS-backed durable session workflow with deterministic
  replay across API restarts.
- SSE event stream at `/v1/sessions/{id}/events/stream` with
  `Last-Event-ID` resume.
- Argon2-hashed API key auth via `Authorization: Bearer` or
  `X-API-Key` headers.
- `hgr_test_key` local-development bypass, gated by the
  `HANGAR_ACCEPT_TEST_KEY` environment variable.
- Dual storage: in-memory for tests, Postgres for production.
- Audit logging for authentication and admin events.
- Deterministic fallback harness when `ANTHROPIC_API_KEY` is
  unset.
