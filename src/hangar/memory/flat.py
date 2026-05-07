from __future__ import annotations

from hangar.store import Record


class FlatMemory:
    async def remember(self, session_id: str, event: Record) -> None:
        del session_id, event

    async def recall(self, session_id: str, query: str | None = None) -> list[Record]:
        del session_id, query
        return []
