from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from hangar.api.deps import get_store, require_api_key
from hangar.api.schemas import AgentCreateRequest, AgentPatchRequest
from hangar.store import Store, render_agent
from hangar.utils.ids import new_id

router = APIRouter(
    prefix="/v1/agents",
    tags=["agents"],
    dependencies=[Depends(require_api_key)],
)


@router.post("")
async def create_agent(
    request: AgentCreateRequest,
    store: Annotated[Store, Depends(get_store)],
) -> dict[str, object]:
    row = await store.create_agent(
        {
            "id": new_id("agent"),
            "name": request.name,
            "description": request.description,
            "model": request.model.model_dump(),
            "system": request.system,
            "tools": [tool.model_dump(exclude_none=True) for tool in request.tools],
            "skills": request.skills,
            "mcp_servers": request.mcp_servers,
            "metadata": request.metadata,
        }
    )
    return render_agent(row)


@router.get("")
async def list_agents(
    store: Annotated[Store, Depends(get_store)],
    limit: int = Query(default=100, ge=1, le=1000),
    after: str | None = None,
) -> dict[str, object]:
    rows = await store.list_agents(limit=limit, after=after)
    return {"data": [render_agent(row) for row in rows], "has_more": False}


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    store: Annotated[Store, Depends(get_store)],
    version: int | None = None,
) -> dict[str, object]:
    row = await store.get_agent(agent_id, version=version)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return render_agent(row)


@router.patch("/{agent_id}")
async def patch_agent(
    agent_id: str,
    request: AgentPatchRequest,
    store: Annotated[Store, Depends(get_store)],
) -> dict[str, object]:
    patch = request.model_dump(exclude_unset=True, exclude_none=True)
    if "model" in patch:
        patch["model"] = request.model.model_dump() if request.model is not None else None
    if request.tools is not None:
        patch["tools"] = [tool.model_dump(exclude_none=True) for tool in request.tools]
    row = await store.patch_agent(agent_id, patch)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return render_agent(row)


@router.post("/{agent_id}/archive")
async def archive_agent(
    agent_id: str,
    store: Annotated[Store, Depends(get_store)],
) -> dict[str, object]:
    row = await store.archive_agent(agent_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return render_agent(row)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    store: Annotated[Store, Depends(get_store)],
) -> Response:
    deleted = await store.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
