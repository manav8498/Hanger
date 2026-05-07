from __future__ import annotations

from typing import Protocol

from hangar.store import Record


class MemoryProvider(Protocol):
    async def remember(self, session_id: str, event: Record) -> None: ...

    async def recall(self, session_id: str, query: str | None = None) -> list[Record]: ...
