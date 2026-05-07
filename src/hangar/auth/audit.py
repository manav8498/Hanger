from __future__ import annotations

from hangar.store import Record, Store


async def log_audit(
    store: Store,
    *,
    action: str,
    target: str | None,
    outcome: str,
    actor: str | None = None,
    metadata: Record | None = None,
) -> None:
    await store.log_audit(
        action=action,
        target=target,
        outcome=outcome,
        actor=actor,
        metadata=metadata,
    )
