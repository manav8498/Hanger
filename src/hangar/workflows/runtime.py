from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Protocol, cast

from dbos import DBOS, DBOSConfig, SetWorkflowID

from hangar.db.session import database_url
from hangar.store import Store
from hangar.workflows.session import (
    USER_EVENTS_TOPIC,
    WORKFLOW_STATUSES,
    run_local_session_workflow,
    session_workflow,
)
from hangar.workflows.steps import configure_steps

logger = logging.getLogger(__name__)


class WorkflowRuntime(Protocol):
    async def start(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def start_session(self, session_id: str) -> None: ...
    async def send_user_events(self, session_id: str, events: list[dict[str, Any]]) -> None: ...
    async def resume_sessions(self) -> None: ...


class LocalWorkflowRuntime:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}

    async def start(self) -> None:
        configure_steps(self._store)

    async def shutdown(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def start_session(self, session_id: str) -> None:
        task = self._tasks.get(session_id)
        if task is not None and not task.done():
            return
        queue = self._queues.setdefault(session_id, asyncio.Queue())
        task = asyncio.create_task(run_local_session_workflow(session_id, queue.get))
        self._tasks[session_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(session_id, None))

    async def send_user_events(self, session_id: str, events: list[dict[str, Any]]) -> None:
        await self.start_session(session_id)
        await self._queues[session_id].put({"events": events})

    async def resume_sessions(self) -> None:
        for session in await self._store.list_sessions(limit=1000):
            if session["status"] in WORKFLOW_STATUSES:
                await self.start_session(str(session["id"]))


class DBOSWorkflowRuntime:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._launched = False

    async def start(self) -> None:
        configure_steps(self._store)
        config = cast(DBOSConfig, {
            "name": "hangar",
            "database_url": _dbos_database_url(database_url()),
            "run_admin_server": False,
            "disable_otlp": True,
            "log_level": os.environ.get("HANGAR_DBOS_LOG_LEVEL", "WARNING"),
        })
        await asyncio.to_thread(lambda: DBOS(config=config).launch())
        self._launched = True

    async def shutdown(self) -> None:
        if self._launched:
            await asyncio.to_thread(lambda: DBOS.destroy(workflow_completion_timeout_sec=2))
            self._launched = False

    async def start_session(self, session_id: str) -> None:
        def start() -> None:
            with SetWorkflowID(session_id):
                DBOS.start_workflow(session_workflow, session_id)

        try:
            await asyncio.to_thread(start)
        except Exception as exc:
            if "Conflicting workflow" not in str(exc):
                raise
            logger.info("Session workflow already exists", extra={"session_id": session_id})

    async def send_user_events(self, session_id: str, events: list[dict[str, Any]]) -> None:
        await self._ensure_workflow_receives(session_id)
        await DBOS.send_async(session_id, {"events": events}, USER_EVENTS_TOPIC)

    async def resume_sessions(self) -> None:
        for session in await self._store.list_sessions(limit=1000):
            if session["status"] in WORKFLOW_STATUSES:
                await self._ensure_workflow_receives(str(session["id"]))

    async def _ensure_workflow_receives(self, session_id: str) -> None:
        try:
            status = await DBOS.get_workflow_status_async(session_id)
            if status is None:
                await self.start_session(session_id)
                return
            await DBOS.resume_workflow_async(session_id)
        except Exception as exc:
            if "not found" in str(exc).lower():
                await self.start_session(session_id)
                return
            logger.info("Session workflow resume skipped", extra={"session_id": session_id})


def make_workflow_runtime(store: Store) -> WorkflowRuntime:
    if _dbos_enabled():
        return DBOSWorkflowRuntime(store)
    return LocalWorkflowRuntime(store)


def _dbos_enabled() -> bool:
    if os.environ.get("HANGAR_STORAGE") == "memory":
        return False
    if os.environ.get("HANGAR_ENABLE_DBOS", "1") == "0":
        return False
    return "DATABASE_URL" in os.environ


def _dbos_database_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
