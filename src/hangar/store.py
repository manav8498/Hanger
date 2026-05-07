from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any, Protocol

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hangar.db import models
from hangar.utils.time import format_ts, utc_now

Record = dict[str, Any]
ORG_ID = "org_default"


class Store(Protocol):
    async def create_api_key(self, key_id: str, name: str, hashed_key: str) -> Record: ...
    async def list_api_keys(self) -> list[Record]: ...
    async def touch_api_key(self, key_id: str) -> None: ...
    async def log_audit(
        self,
        *,
        action: str,
        target: str | None,
        outcome: str,
        actor: str | None = None,
        metadata: Record | None = None,
    ) -> None: ...
    async def count_audit_events(self) -> int: ...
    async def create_agent(self, data: Record) -> Record: ...
    async def get_agent(self, agent_id: str, version: int | None = None) -> Record | None: ...
    async def list_agents(self, limit: int = 100, after: str | None = None) -> list[Record]: ...
    async def patch_agent(self, agent_id: str, patch: Record) -> Record | None: ...
    async def archive_agent(self, agent_id: str) -> Record | None: ...
    async def delete_agent(self, agent_id: str) -> bool: ...
    async def create_environment(self, data: Record) -> Record: ...
    async def get_environment(self, env_id: str) -> Record | None: ...
    async def list_environments(self, limit: int = 100) -> list[Record]: ...
    async def archive_environment(self, env_id: str) -> Record | None: ...
    async def delete_environment(self, env_id: str) -> bool: ...
    async def create_session(self, data: Record) -> Record: ...
    async def get_session(self, session_id: str) -> Record | None: ...
    async def list_sessions(self, limit: int = 100) -> list[Record]: ...
    async def update_session(self, session_id: str, patch: Record) -> Record | None: ...
    async def delete_session(self, session_id: str) -> bool: ...
    async def create_event(
        self,
        session_id: str,
        event_type: str,
        content: Record,
        *,
        dedupe_key: str | None = None,
    ) -> Record: ...
    async def list_events(
        self,
        session_id: str,
        *,
        after_id: int | None = None,
        limit: int = 100,
    ) -> list[Record]: ...
    async def max_event_id(self, session_id: str) -> int: ...
    async def wait_for_events(
        self,
        session_id: str,
        *,
        after_id: int,
        timeout: float,
    ) -> list[Record]: ...


class MemoryStore:
    def __init__(self) -> None:
        self.api_keys: dict[str, Record] = {}
        self.audit_events: list[Record] = []
        self.agents: dict[str, list[Record]] = {}
        self.environments: dict[str, Record] = {}
        self.sessions: dict[str, Record] = {}
        self.events: list[Record] = []
        self._event_id = 0
        self._condition = asyncio.Condition()

    async def create_api_key(self, key_id: str, name: str, hashed_key: str) -> Record:
        row = {
            "id": key_id,
            "organization_id": ORG_ID,
            "name": name,
            "hashed_key": hashed_key,
            "last_used_at": None,
            "created_at": utc_now(),
            "revoked_at": None,
        }
        self.api_keys[key_id] = row
        return dict(row)

    async def list_api_keys(self) -> list[Record]:
        return [dict(row) for row in self.api_keys.values() if row["revoked_at"] is None]

    async def touch_api_key(self, key_id: str) -> None:
        if key_id in self.api_keys:
            self.api_keys[key_id]["last_used_at"] = utc_now()

    async def log_audit(
        self,
        *,
        action: str,
        target: str | None,
        outcome: str,
        actor: str | None = None,
        metadata: Record | None = None,
    ) -> None:
        self.audit_events.append(
            {
                "id": len(self.audit_events) + 1,
                "ts": utc_now(),
                "organization_id": ORG_ID,
                "actor": actor,
                "action": action,
                "target": target,
                "outcome": outcome,
                "metadata": metadata or {},
            }
        )

    async def count_audit_events(self) -> int:
        return len(self.audit_events)

    async def create_agent(self, data: Record) -> Record:
        row = dict(data)
        row.update(
            {
                "organization_id": ORG_ID,
                "version": 1,
                "is_latest": True,
                "archived_at": None,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        self.agents[row["id"]] = [row]
        return dict(row)

    async def get_agent(self, agent_id: str, version: int | None = None) -> Record | None:
        versions = self.agents.get(agent_id, [])
        if version is None:
            for row in reversed(versions):
                if row["is_latest"]:
                    return dict(row)
            return None
        for row in versions:
            if row["version"] == version:
                return dict(row)
        return None

    async def list_agents(self, limit: int = 100, after: str | None = None) -> list[Record]:
        rows = [
            versions[-1]
            for agent_id, versions in sorted(self.agents.items())
            if versions and (after is None or agent_id > after)
        ]
        return [dict(row) for row in rows[:limit]]

    async def patch_agent(self, agent_id: str, patch: Record) -> Record | None:
        latest = await self.get_agent(agent_id)
        if latest is None:
            return None
        comparable = {key: latest.get(key) for key in patch}
        if comparable == patch:
            return latest

        versions = self.agents[agent_id]
        versions[-1]["is_latest"] = False
        row = dict(latest)
        row.update(patch)
        row["version"] = latest["version"] + 1
        row["is_latest"] = True
        row["created_at"] = latest["created_at"]
        row["updated_at"] = utc_now()
        versions.append(row)
        return dict(row)

    async def archive_agent(self, agent_id: str) -> Record | None:
        latest = await self.get_agent(agent_id)
        if latest is None:
            return None
        versions = self.agents[agent_id]
        versions[-1]["archived_at"] = utc_now()
        versions[-1]["updated_at"] = utc_now()
        return dict(versions[-1])

    async def delete_agent(self, agent_id: str) -> bool:
        return self.agents.pop(agent_id, None) is not None

    async def create_environment(self, data: Record) -> Record:
        row = dict(data)
        row.update(
            {
                "organization_id": ORG_ID,
                "archived_at": None,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        self.environments[row["id"]] = row
        return dict(row)

    async def get_environment(self, env_id: str) -> Record | None:
        row = self.environments.get(env_id)
        return dict(row) if row is not None else None

    async def list_environments(self, limit: int = 100) -> list[Record]:
        return [dict(row) for row in list(self.environments.values())[:limit]]

    async def archive_environment(self, env_id: str) -> Record | None:
        row = self.environments.get(env_id)
        if row is None:
            return None
        row["archived_at"] = utc_now()
        row["updated_at"] = utc_now()
        return dict(row)

    async def delete_environment(self, env_id: str) -> bool:
        active = any(
            session["environment_id"] == env_id
            and session["status"] not in {"terminated", "error"}
            for session in self.sessions.values()
        )
        if active:
            return False
        return self.environments.pop(env_id, None) is not None

    async def create_session(self, data: Record) -> Record:
        row = dict(data)
        row.update(
            {
                "organization_id": ORG_ID,
                "status": "starting",
                "stop_reason": None,
                "container_id": None,
                "workflow_id": row["id"],
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "terminated_at": None,
            }
        )
        self.sessions[row["id"]] = row
        return dict(row)

    async def get_session(self, session_id: str) -> Record | None:
        row = self.sessions.get(session_id)
        return dict(row) if row is not None else None

    async def list_sessions(self, limit: int = 100) -> list[Record]:
        return [dict(row) for row in list(self.sessions.values())[:limit]]

    async def update_session(self, session_id: str, patch: Record) -> Record | None:
        row = self.sessions.get(session_id)
        if row is None:
            return None
        row.update(patch)
        row["updated_at"] = utc_now()
        return dict(row)

    async def delete_session(self, session_id: str) -> bool:
        return self.sessions.pop(session_id, None) is not None

    async def create_event(
        self,
        session_id: str,
        event_type: str,
        content: Record,
        *,
        dedupe_key: str | None = None,
    ) -> Record:
        async with self._condition:
            if dedupe_key is not None:
                for existing in self.events:
                    if existing.get("dedupe_key") == dedupe_key:
                        return dict(existing)
            self._event_id += 1
            row = {
                "id": self._event_id,
                "session_id": session_id,
                "type": event_type,
                "content": content,
                "dedupe_key": dedupe_key,
                "processed_at": None,
                "created_at": utc_now(),
            }
            self.events.append(row)
            self._condition.notify_all()
            return dict(row)

    async def list_events(
        self,
        session_id: str,
        *,
        after_id: int | None = None,
        limit: int = 100,
    ) -> list[Record]:
        floor = after_id or 0
        rows = [
            row
            for row in self.events
            if row["session_id"] == session_id and row["id"] > floor
        ]
        return [dict(row) for row in rows[:limit]]

    async def max_event_id(self, session_id: str) -> int:
        ids = [row["id"] for row in self.events if row["session_id"] == session_id]
        return max(ids, default=0)

    async def wait_for_events(
        self,
        session_id: str,
        *,
        after_id: int,
        timeout: float,
    ) -> list[Record]:
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(
                        lambda: any(
                            row["session_id"] == session_id and row["id"] > after_id
                            for row in self.events
                        )
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                return []
        return await self.list_events(session_id, after_id=after_id)


class PostgresStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create_api_key(self, key_id: str, name: str, hashed_key: str) -> Record:
        async with self._sessionmaker() as session:
            row = models.ApiKey(
                id=key_id,
                organization_id=ORG_ID,
                name=name,
                hashed_key=hashed_key,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _api_key_row(row)

    async def list_api_keys(self) -> list[Record]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                select(models.ApiKey).where(models.ApiKey.revoked_at.is_(None))
            )
            return [_api_key_row(row) for row in rows]

    async def touch_api_key(self, key_id: str) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(models.ApiKey)
                .where(models.ApiKey.id == key_id)
                .values(last_used_at=utc_now())
            )
            await session.commit()

    async def log_audit(
        self,
        *,
        action: str,
        target: str | None,
        outcome: str,
        actor: str | None = None,
        metadata: Record | None = None,
    ) -> None:
        async with self._sessionmaker() as session:
            session.add(
                models.AuditEvent(
                    organization_id=ORG_ID,
                    actor=actor,
                    action=action,
                    target=target,
                    outcome=outcome,
                    metadata_=metadata or {},
                )
            )
            await session.commit()

    async def count_audit_events(self) -> int:
        async with self._sessionmaker() as session:
            result = await session.execute(text("select count(*) from audit_events"))
            return int(result.scalar_one())

    async def create_agent(self, data: Record) -> Record:
        async with self._sessionmaker() as session:
            row = models.Agent(
                id=data["id"],
                organization_id=ORG_ID,
                name=data["name"],
                description=data.get("description"),
                version=1,
                is_latest=True,
                model=data["model"],
                system_prompt=data.get("system"),
                tools=data["tools"],
                mcp_servers=data["mcp_servers"],
                skills=data["skills"],
                metadata_=data["metadata"],
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _agent_row(row)

    async def get_agent(self, agent_id: str, version: int | None = None) -> Record | None:
        async with self._sessionmaker() as session:
            statement = select(models.Agent).where(models.Agent.id == agent_id)
            if version is None:
                statement = statement.where(models.Agent.is_latest.is_(True))
            else:
                statement = statement.where(models.Agent.version == version)
            row = await session.scalar(statement)
            return _agent_row(row) if row is not None else None

    async def list_agents(self, limit: int = 100, after: str | None = None) -> list[Record]:
        async with self._sessionmaker() as session:
            statement = (
                select(models.Agent)
                .where(models.Agent.is_latest.is_(True))
                .order_by(models.Agent.id)
                .limit(limit)
            )
            if after is not None:
                statement = statement.where(models.Agent.id > after)
            rows = await session.scalars(statement)
            return [_agent_row(row) for row in rows]

    async def patch_agent(self, agent_id: str, patch: Record) -> Record | None:
        latest = await self.get_agent(agent_id)
        if latest is None:
            return None
        if {key: latest.get(key) for key in patch} == patch:
            return latest
        async with self._sessionmaker() as session:
            await session.execute(
                update(models.Agent)
                .where(models.Agent.id == agent_id, models.Agent.is_latest.is_(True))
                .values(is_latest=False)
            )
            row = models.Agent(
                id=agent_id,
                organization_id=ORG_ID,
                name=patch.get("name", latest["name"]),
                description=patch.get("description", latest.get("description")),
                version=latest["version"] + 1,
                is_latest=True,
                model=patch.get("model", latest["model"]),
                system_prompt=patch.get("system", latest.get("system")),
                tools=patch.get("tools", latest["tools"]),
                mcp_servers=patch.get("mcp_servers", latest["mcp_servers"]),
                skills=patch.get("skills", latest["skills"]),
                metadata_=patch.get("metadata", latest["metadata"]),
                created_at=latest["created_at"],
                updated_at=utc_now(),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _agent_row(row)

    async def archive_agent(self, agent_id: str) -> Record | None:
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(models.Agent).where(
                    models.Agent.id == agent_id,
                    models.Agent.is_latest.is_(True),
                )
            )
            if row is None:
                return None
            row.archived_at = utc_now()
            row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
            return _agent_row(row)

    async def delete_agent(self, agent_id: str) -> bool:
        if await self.get_agent(agent_id) is None:
            return False
        async with self._sessionmaker() as session:
            await session.execute(delete(models.Agent).where(models.Agent.id == agent_id))
            await session.commit()
            return True

    async def create_environment(self, data: Record) -> Record:
        async with self._sessionmaker() as session:
            row = models.Environment(
                id=data["id"],
                organization_id=ORG_ID,
                name=data["name"],
                config=data["config"],
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _environment_row(row)

    async def get_environment(self, env_id: str) -> Record | None:
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(models.Environment).where(models.Environment.id == env_id)
            )
            return _environment_row(row) if row is not None else None

    async def list_environments(self, limit: int = 100) -> list[Record]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(select(models.Environment).limit(limit))
            return [_environment_row(row) for row in rows]

    async def archive_environment(self, env_id: str) -> Record | None:
        async with self._sessionmaker() as session:
            row = await session.get(models.Environment, env_id)
            if row is None:
                return None
            row.archived_at = utc_now()
            row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
            return _environment_row(row)

    async def delete_environment(self, env_id: str) -> bool:
        async with self._sessionmaker() as session:
            active = await session.scalar(
                select(models.Session).where(
                    models.Session.environment_id == env_id,
                    models.Session.status.not_in(["terminated", "error"]),
                )
            )
            if active is not None:
                return False
            row = await session.get(models.Environment, env_id)
            if row is None:
                return False
            await session.execute(delete(models.Environment).where(models.Environment.id == env_id))
            await session.commit()
            return True

    async def create_session(self, data: Record) -> Record:
        async with self._sessionmaker() as session:
            row = models.Session(
                id=data["id"],
                organization_id=ORG_ID,
                agent_id=data["agent_id"],
                agent_version=data["agent_version"],
                environment_id=data["environment_id"],
                status="starting",
                title=data.get("title"),
                workflow_id=data["id"],
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _session_row(row)

    async def get_session(self, session_id: str) -> Record | None:
        async with self._sessionmaker() as session:
            row = await session.get(models.Session, session_id)
            return _session_row(row) if row is not None else None

    async def list_sessions(self, limit: int = 100) -> list[Record]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(select(models.Session).limit(limit))
            return [_session_row(row) for row in rows]

    async def update_session(self, session_id: str, patch: Record) -> Record | None:
        async with self._sessionmaker() as session:
            row = await session.get(models.Session, session_id)
            if row is None:
                return None
            for key, value in patch.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
            return _session_row(row)

    async def delete_session(self, session_id: str) -> bool:
        if await self.get_session(session_id) is None:
            return False
        async with self._sessionmaker() as session:
            await session.execute(delete(models.Session).where(models.Session.id == session_id))
            await session.commit()
            return True

    async def create_event(
        self,
        session_id: str,
        event_type: str,
        content: Record,
        *,
        dedupe_key: str | None = None,
    ) -> Record:
        async with self._sessionmaker() as session:
            if dedupe_key is not None:
                existing = await session.scalar(
                    select(models.Event).where(models.Event.dedupe_key == dedupe_key)
                )
                if existing is not None:
                    return _event_row(existing)
            row = models.Event(
                session_id=session_id,
                type=event_type,
                content=content,
                dedupe_key=dedupe_key,
            )
            session.add(row)
            await session.flush()
            await session.execute(
                text("select pg_notify('hangar_events', :payload)"),
                {"payload": json.dumps({"session_id": session_id, "event_id": row.id})},
            )
            await session.commit()
            await session.refresh(row)
            return _event_row(row)

    async def list_events(
        self,
        session_id: str,
        *,
        after_id: int | None = None,
        limit: int = 100,
    ) -> list[Record]:
        async with self._sessionmaker() as session:
            statement = (
                select(models.Event)
                .where(models.Event.session_id == session_id)
                .order_by(models.Event.id)
                .limit(limit)
            )
            if after_id is not None:
                statement = statement.where(models.Event.id > after_id)
            rows = await session.scalars(statement)
            return [_event_row(row) for row in rows]

    async def max_event_id(self, session_id: str) -> int:
        async with self._sessionmaker() as session:
            result = await session.execute(
                text("select coalesce(max(id), 0) from events where session_id = :session_id"),
                {"session_id": session_id},
            )
            return int(result.scalar_one())

    async def wait_for_events(
        self,
        session_id: str,
        *,
        after_id: int,
        timeout: float,
    ) -> list[Record]:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            events = await self.list_events(session_id, after_id=after_id)
            if events:
                return events
            await asyncio.sleep(0.1)
        return []


def _agent_row(row: models.Agent) -> Record:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "name": row.name,
        "description": row.description,
        "version": row.version,
        "is_latest": row.is_latest,
        "model": row.model,
        "system": row.system_prompt,
        "tools": _list(row.tools),
        "mcp_servers": _list(row.mcp_servers),
        "skills": _list(row.skills),
        "metadata": dict(row.metadata_),
        "archived_at": row.archived_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _environment_row(row: models.Environment) -> Record:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "name": row.name,
        "config": row.config,
        "archived_at": row.archived_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _session_row(row: models.Session) -> Record:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "agent_id": row.agent_id,
        "agent_version": row.agent_version,
        "environment_id": row.environment_id,
        "status": row.status,
        "stop_reason": row.stop_reason,
        "title": row.title,
        "container_id": row.container_id,
        "workflow_id": row.workflow_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "terminated_at": row.terminated_at,
    }


def _event_row(row: models.Event) -> Record:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "type": row.type,
        "content": row.content,
        "processed_at": row.processed_at,
        "created_at": row.created_at,
    }


def _api_key_row(row: models.ApiKey) -> Record:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "name": row.name,
        "hashed_key": row.hashed_key,
        "last_used_at": row.last_used_at,
        "created_at": row.created_at,
        "revoked_at": row.revoked_at,
    }


def _list(value: Sequence[Record]) -> list[Record]:
    return [dict(item) for item in value]


def render_agent(row: Record) -> Record:
    return {
        "id": row["id"],
        "type": "agent",
        "name": row["name"],
        "model": row["model"],
        "system": row.get("system"),
        "description": row.get("description"),
        "tools": row["tools"],
        "skills": row["skills"],
        "mcp_servers": row["mcp_servers"],
        "metadata": row["metadata"],
        "version": row["version"],
        "created_at": format_ts(row["created_at"]),
        "updated_at": format_ts(row["updated_at"]),
        "archived_at": _optional_ts(row.get("archived_at")),
    }


def render_environment(row: Record) -> Record:
    return {
        "id": row["id"],
        "type": "environment",
        "name": row["name"],
        "config": row["config"],
        "archived_at": _optional_ts(row.get("archived_at")),
        "created_at": format_ts(row["created_at"]),
        "updated_at": format_ts(row["updated_at"]),
    }


def render_session(row: Record) -> Record:
    return {
        "id": row["id"],
        "type": "session",
        "agent_id": row["agent_id"],
        "agent_version": row["agent_version"],
        "environment_id": row["environment_id"],
        "title": row.get("title"),
        "status": row["status"],
        "stop_reason": row.get("stop_reason"),
        "created_at": format_ts(row["created_at"]),
        "updated_at": format_ts(row["updated_at"]),
    }


def render_event(row: Record) -> Record:
    return {
        "id": str(row["id"]),
        "type": row["type"],
        "session_id": row["session_id"],
        "content": row["content"],
        "created_at": format_ts(row["created_at"]),
        "processed_at": _optional_ts(row.get("processed_at")),
    }


def _optional_ts(value: Any) -> str | None:
    return format_ts(value) if value is not None else None
