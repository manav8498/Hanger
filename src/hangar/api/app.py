from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from hangar import __version__
from hangar.api.routes import agents, api_keys, environments, events, sessions
from hangar.db.models import Base
from hangar.db.session import make_engine, make_sessionmaker
from hangar.store import MemoryStore, PostgresStore, Store


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.background_tasks = set()
    app.state.engine = None
    app.state.store = await _make_store(app)
    await _resume_starting_sessions(app.state.store)
    yield
    for task in set(app.state.background_tasks):
        task.cancel()
    if app.state.engine is not None:
        await app.state.engine.dispose()


app = FastAPI(title="Hangar", version=__version__, lifespan=lifespan)
app.include_router(api_keys.router)
app.include_router(agents.router)
app.include_router(environments.router)
app.include_router(sessions.router)
app.include_router(events.router)


@app.get("/")
async def health() -> dict[str, str]:
    return {"hangar": "ok", "version": __version__}


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    message = str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"type": "http_error", "message": message}},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_request_error", "message": str(exc)}},
    )


async def _make_store(app: FastAPI) -> Store:
    if os.environ.get("HANGAR_STORAGE") == "memory" or "DATABASE_URL" not in os.environ:
        return MemoryStore()

    engine = make_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app.state.engine = engine
    return PostgresStore(make_sessionmaker(engine))


async def _resume_starting_sessions(store: Store) -> None:
    for session in await store.list_sessions(limit=1000):
        if session["status"] == "starting":
            await store.update_session(session["id"], {"status": "error"})
            await store.create_event(
                session["id"],
                "session.error",
                {"message": "Session was interrupted during startup."},
            )
