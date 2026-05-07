from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from hangar.api.health import collect_health

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, object]:
    return await collect_health(request.app)


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    body = await collect_health(request.app)
    status_code = 200 if body["status"] == "ok" else 503
    return JSONResponse(status_code=status_code, content=body)
