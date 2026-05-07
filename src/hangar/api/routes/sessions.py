from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from hangar.api.deps import get_store, require_api_key
from hangar.api.schemas import SessionCreateRequest
from hangar.runtime.container import provision_container, terminate_container
from hangar.store import Store, render_session
from hangar.utils.ids import new_id
from hangar.utils.time import utc_now

router = APIRouter(
    prefix="/v1/sessions",
    tags=["sessions"],
    dependencies=[Depends(require_api_key)],
)


@router.post("")
async def create_session(
    request: Request,
    body: SessionCreateRequest,
    store: Annotated[Store, Depends(get_store)],
) -> dict[str, object]:
    agent_id, agent_version = _agent_ref(body.agent)
    agent = await store.get_agent(agent_id, version=agent_version)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.get("archived_at") is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent is archived")
    environment = await store.get_environment(body.environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    if environment.get("archived_at") is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Environment is archived")

    row = await store.create_session(
        {
            "id": new_id("ses"),
            "agent_id": agent["id"],
            "agent_version": agent["version"],
            "environment_id": environment["id"],
            "title": body.title,
        }
    )
    await store.create_event(
        row["id"],
        "session.status_starting",
        {"session_id": row["id"], "ts": utc_now().isoformat()},
    )
    _track_task(request, _provision_session(store, row["id"], environment["config"]))
    return render_session(row)


@router.get("")
async def list_sessions(
    store: Annotated[Store, Depends(get_store)],
    limit: int = 100,
) -> dict[str, object]:
    rows = await store.list_sessions(limit=limit)
    return {"data": [render_session(row) for row in rows], "has_more": False}


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    store: Annotated[Store, Depends(get_store)],
) -> dict[str, object]:
    row = await store.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return render_session(row)


@router.post("/{session_id}/terminate")
async def terminate_session(
    session_id: str,
    store: Annotated[Store, Depends(get_store)],
) -> dict[str, object]:
    row = await store.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await asyncio.to_thread(terminate_container, row.get("container_id"))
    updated = await store.update_session(
        session_id,
        {
            "status": "terminated",
            "stop_reason": {"type": "user_requested"},
            "terminated_at": utc_now(),
        },
    )
    await store.create_event(
        session_id,
        "session.status_terminated",
        {"stop_reason": {"type": "user_requested"}},
    )
    return render_session(updated or row)


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    store: Annotated[Store, Depends(get_store)],
) -> Response:
    row = await store.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await asyncio.to_thread(terminate_container, row.get("container_id"))
    await store.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _provision_session(
    store: Store,
    session_id: str,
    environment_config: dict[str, Any],
) -> None:
    try:
        handle = await provision_container(environment_config, session_id)
    except Exception as exc:
        await store.update_session(session_id, {"status": "error", "stop_reason": {"type": "error"}})
        await store.create_event(session_id, "session.error", {"message": str(exc)})
        return

    await store.update_session(
        session_id,
        {"status": "running", "container_id": handle.id},
    )
    await store.create_event(
        session_id,
        "session.status_running",
        {"session_id": session_id, "ts": utc_now().isoformat()},
    )


def _agent_ref(agent: str | dict[str, Any]) -> tuple[str, int | None]:
    if isinstance(agent, str):
        return agent, None
    return str(agent["id"]), int(agent["version"]) if "version" in agent else None


def _track_task(request: Request, coroutine: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coroutine)
    request.app.state.background_tasks.add(task)
    task.add_done_callback(request.app.state.background_tasks.discard)
