# Hangar — agent context

## What this is
Hangar is an open-source, self-hostable, API-compatible drop-in for Anthropic's
Claude Managed Agents. Same four primitives (Agent, Environment, Session, Event),
same SSE shape. Runs on a single VPS via `docker compose up`.

## North Star
The compat test `tests/test_compat_anthropic_sdk.py` is the contract with the
outside world. The Anthropic Python SDK pointed at `http://localhost:8080`
with `api_key="hgr_test"` must run create-agent → create-env → create-session
→ stream events without modification. Never edit this test to make it pass.

## Build context
- Phase 1 only right now (MVP). Phase 2 (CLI polish, dashboard) and Phase 3
  (launch) are out of scope until I explicitly say so.
- Full spec lives in `hangar-project-spec.md` if attached. Read once at session
  start, then refer back to specific sections as needed.

## Architecture in one paragraph
FastAPI app on port 8080. DBOS-decorated workflow per session is the durable
agent loop. One Docker container per active session is the sandbox where tool
calls execute. Postgres holds agents, environments, sessions, and an append-only
event log. SSE streams events from Postgres LISTEN/NOTIFY. The Claude Agent SDK
(Python package) runs the actual model loop inside each session workflow step.

## Code style (enforce strictly)
- Python 3.12, full type annotations, `from __future__ import annotations` everywhere
- pydantic v2 for all request/response schemas
- async/await throughout — no sync FastAPI routes
- Ruff for lint, mypy strict for typecheck
- Tests in `tests/`, one file per route module + `tests/e2e/`
- Use standard-library `logging`; keep messages structured with `extra` where useful
- All API errors return `{"error": {"type": "...", "message": "..."}}` shape
  (matches Anthropic SDK error parsing)

## Workflow rules
- Run `make lint typecheck test` after any meaningful change
- Don't commit to main directly — branch per task: `phase1/task-1.6-sessions-provision`
- Every API response shape MUST match Section 4 of the Codex prompt verbatim
- The Anthropic SDK compat test is the source of truth; if it fails, code is wrong
- Use `apply_patch` for edits. One atomic change per tool call.

## Things to never do
- Don't reach for LangChain, LangGraph, CrewAI, AutoGen — Claude Agent SDK only
- Don't introduce a new database — Postgres is the only datastore for v1
- Don't use Celery, RQ, or any other queue — DBOS only
- Don't make MCP servers required — they're optional
- Don't add Hebbrix or any proprietary memory provider as default — flat log only
- Don't modify the compat test
- Don't use SQLite — DBOS needs Postgres

## Tests that must pass before declaring done
- `make lint` — zero ruff errors
- `make typecheck` — zero mypy errors in strict mode
- `make test` — all pytest tests, coverage > 70% on `src/hangar/api/`
- `make compat` — Anthropic SDK compat test, against running stack

## Useful commands
- `make dev` — `docker compose up -d`, tails logs
- `make test` — pytest
- `make compat` — pytest -k compat (requires stack running)
- `make lint typecheck` — ruff + mypy
- `make clean` — `docker compose down -v` (wipes db)

## When you're stuck, ask before guessing on
- Networking policy implementation (iptables vs egress proxy)
- Anything that diverges from the CMA API contract
- Adding a new dependency
