from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from hangar.store import Store


async def stream_session_events(
    store: Store,
    session_id: str,
    *,
    last_event_id: str | None,
) -> AsyncGenerator[dict[str, str], None]:
    cursor = int(last_event_id) if last_event_id else await store.max_event_id(session_id)

    while True:
        events = await store.wait_for_events(session_id, after_id=cursor, timeout=15)
        if not events:
            yield {"event": "ping", "data": "{}"}
            continue
        for event in events:
            cursor = int(event["id"])
            yield {
                "id": str(event["id"]),
                "event": str(event["type"]),
                "data": json.dumps(event["content"], separators=(",", ":")),
            }
