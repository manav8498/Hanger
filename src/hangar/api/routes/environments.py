from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from hangar.api.deps import get_store, require_api_key
from hangar.api.schemas import EnvironmentCreateRequest
from hangar.store import Store, render_environment
from hangar.utils.ids import new_id

router = APIRouter(
    prefix="/v1/environments",
    tags=["environments"],
    dependencies=[Depends(require_api_key)],
)


@router.post("")
async def create_environment(
    request: EnvironmentCreateRequest,
    store: Annotated[Store, Depends(get_store)],
) -> dict[str, object]:
    row = await store.create_environment(
        {
            "id": new_id("env"),
            "name": request.name,
            "config": request.config.model_dump(),
        }
    )
    return render_environment(row)


@router.get("")
async def list_environments(
    store: Annotated[Store, Depends(get_store)],
    limit: int = 100,
) -> dict[str, object]:
    rows = await store.list_environments(limit=limit)
    return {"data": [render_environment(row) for row in rows], "has_more": False}


@router.get("/{environment_id}")
async def get_environment(
    environment_id: str,
    store: Annotated[Store, Depends(get_store)],
) -> dict[str, object]:
    row = await store.get_environment(environment_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    return render_environment(row)


@router.post("/{environment_id}/archive")
async def archive_environment(
    environment_id: str,
    store: Annotated[Store, Depends(get_store)],
) -> dict[str, object]:
    row = await store.archive_environment(environment_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    return render_environment(row)


@router.delete("/{environment_id}")
async def delete_environment(
    environment_id: str,
    store: Annotated[Store, Depends(get_store)],
) -> Response:
    deleted = await store.delete_environment(environment_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Environment not found or has active sessions",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
