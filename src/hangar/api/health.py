from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import docker
from fastapi import FastAPI
from sqlalchemy import text

from hangar.utils.time import format_ts, utc_now
from hangar.workflows.runtime import DBOSWorkflowRuntime, LocalWorkflowRuntime

ComponentHealth = dict[str, Any]
HealthBody = dict[str, Any]

CHECK_TIMEOUT_SECONDS = 0.5
SESSION_CONTAINER_PREFIX = "hangar-"
COMPOSE_CONTAINER_PREFIXES = ("hangar-api-", "hangar-postgres-")


async def check_database(app: FastAPI) -> ComponentHealth:
    engine = app.state.engine
    if engine is None:
        return {"status": "skipped", "reason": "memory store"}

    started = time.perf_counter()
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        return {"status": "error", "reason": _exception_reason(exc)}
    latency_ms = round((time.perf_counter() - started) * 1000)
    return {"status": "ok", "latency_ms": latency_ms}


async def check_dbos(app: FastAPI) -> ComponentHealth:
    runtime = app.state.workflow_runtime
    if isinstance(runtime, LocalWorkflowRuntime):
        return {"status": "skipped", "reason": "local runtime"}
    if not isinstance(runtime, DBOSWorkflowRuntime):
        return {"status": "skipped", "reason": "unknown runtime"}

    try:
        sessions = await app.state.store.list_sessions(limit=1000)
    except Exception as exc:
        return {"status": "error", "reason": _exception_reason(exc)}
    active = sum(1 for session in sessions if session.get("status") in {"running", "idle"})
    return {"status": "ok", "active_workflows": active}


async def check_docker() -> ComponentHealth:
    if os.environ.get("HANGAR_RUNTIME_MODE") == "fake":
        return {"status": "skipped", "reason": "fake mode"}

    try:
        container_count = await asyncio.to_thread(_count_session_containers)
    except docker.errors.DockerException:
        return {"status": "error", "reason": "docker daemon unreachable"}
    return {"status": "ok", "container_count": container_count}


async def collect_health(app: FastAPI) -> HealthBody:
    component_results = await asyncio.gather(
        _run_check("database", check_database(app)),
        _run_check("dbos", check_dbos(app)),
        _run_check("docker", check_docker()),
    )
    components = dict(component_results)
    return {
        "status": _aggregate_status(components),
        "version": app.version,
        "components": components,
        "checked_at": format_ts(utc_now()),
    }


async def _run_check(name: str, check: Any) -> tuple[str, ComponentHealth]:
    try:
        result = await asyncio.wait_for(check, timeout=CHECK_TIMEOUT_SECONDS)
    except TimeoutError:
        return name, {"status": "degraded", "reason": "timeout"}
    except Exception as exc:
        return name, {"status": "error", "reason": _exception_reason(exc)}
    return name, result


def _aggregate_status(components: dict[str, ComponentHealth]) -> str:
    statuses = [
        str(component.get("status"))
        for component in components.values()
        if component.get("status") != "skipped"
    ]
    if "error" in statuses:
        return "error"
    if "degraded" in statuses:
        return "degraded"
    return "ok"


def _count_session_containers() -> int:
    client = docker.from_env()
    containers = client.containers.list(all=True)
    return sum(1 for container in containers if _is_session_container(str(container.name)))


def _is_session_container(name: str) -> bool:
    return name.startswith(SESSION_CONTAINER_PREFIX) and not name.startswith(COMPOSE_CONTAINER_PREFIXES)


def _exception_reason(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {exc}"
