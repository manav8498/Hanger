from __future__ import annotations

from typing import Any

from hangar.store import Store
from hangar.workflows.steps import run_agent_turn


async def session_workflow(
    store: Store,
    session_id: str,
    user_events: list[dict[str, Any]],
) -> None:
    await run_agent_turn(store, session_id, user_events)
