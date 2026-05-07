from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from hangar.api.deps import get_store, require_api_key
from hangar.api.schemas import EventsSendRequest
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
    user_events: list[dict[str, Any]] = []
    for incoming in body.events:
        content = incoming.content if incoming.content is not None else {}
        accepted.append({"type": incoming.type, "content": content})
        if incoming.type == "user.message":
            user_events.append({"type": incoming.type, "content": content})

    if user_events:
        await request.app.state.workflow_runtime.send_user_events(session_id, user_events)

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
