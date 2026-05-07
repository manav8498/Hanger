from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from hangar.api.deps import get_store
from hangar.api.schemas import ApiKeyCreateRequest, ApiKeyCreateResponse
from hangar.auth.keys import create_api_key
from hangar.store import Store

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreateResponse)
async def create_key(
    request: ApiKeyCreateRequest,
    store: Annotated[Store, Depends(get_store)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> ApiKeyCreateResponse:
    expected = os.environ.get("HANGAR_ADMIN_TOKEN", "dev-admin-token")
    if x_admin_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")

    created = create_api_key(request.name)
    await store.create_api_key(created.id, request.name, created.hashed_key)
    await store.log_audit(
        action="api_key.create",
        target=created.id,
        outcome="ok",
        actor="admin",
    )
    return ApiKeyCreateResponse(id=created.id, name=request.name, key=created.raw_key)
