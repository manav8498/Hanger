from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from hangar.api.deps import get_store, require_api_key
from hangar.api.schemas import EventsSendRequest
from hangar.runtime.harness import run_turn
from hangar.store import Store, render_event
from hangar.streaming.sse import stream_session_events

router = APIRouter(
    prefix="/v1/sessions/{session_id}",
    tags=["events"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/events")
async def send_events(
    request: Request,
    session_id: str,
    body: EventsSendRequest,
    store: Annotated[Store, Depends(get_store)],
) -> dict[str, object]:
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    accepted: list[dict[str, object]] = []
    user_events: list[dict[str, object]] = []
    for incoming in body.events:
        content = incoming.content if incoming.content is not None else {}
        content_object = {"content": content} if isinstance(content, list) else content
        row = await store.create_event(session_id, incoming.type, content_object)
        accepted.append(render_event(row))
        if incoming.type == "user.message":
            user_events.append({"type": incoming.type, "content": content})

    if user_events:
        await store.update_session(session_id, {"status": "running", "stop_reason": None})
        _track_task(request, run_turn(store, session_id, user_events))

    return {"events": accepted}


@router.get("/events")
async def list_events(
    session_id: str,
    store: Annotated[Store, Depends(get_store)],
    after_id: int | None = None,
    limit: int = 100,
) -> dict[str, object]:
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    rows = await store.list_events(session_id, after_id=after_id, limit=limit)
    return {"data": [render_event(row) for row in rows], "has_more": False}


@router.get("/stream")
async def stream_events_spec_path(
    session_id: str,
    store: Annotated[Store, Depends(get_store)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    return await _stream(session_id, store, last_event_id)


@router.get("/events/stream")
async def stream_events_sdk_path(
    session_id: str,
    store: Annotated[Store, Depends(get_store)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    return await _stream(session_id, store, last_event_id)


async def _stream(
    session_id: str,
    store: Store,
    last_event_id: str | None,
) -> EventSourceResponse:
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return EventSourceResponse(
        stream_session_events(store, session_id, last_event_id=last_event_id),
        ping=15,
    )


def _track_task(request: Request, coroutine: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coroutine)
    request.app.state.background_tasks.add(task)
    task.add_done_callback(request.app.state.background_tasks.discard)
