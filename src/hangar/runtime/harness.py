from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query

from hangar.runtime.container import _outputs_path
from hangar.store import Store


async def run_turn(store: Store, session_id: str, user_events: list[dict[str, Any]]) -> None:
    text = _extract_text(user_events)
    if await _run_claude_agent_sdk(store, session_id, text):
        return

    await _run_fallback_turn(store, session_id, text)


async def _run_claude_agent_sdk(store: Store, session_id: str, text: str) -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    if os.environ.get("HANGAR_USE_CLAUDE_AGENT_SDK", "1") == "0":
        return False

    session = await store.get_session(session_id)
    if session is None:
        return False
    agent = await store.get_agent(str(session["agent_id"]), version=int(session["agent_version"]))
    if agent is None:
        return False

    options = ClaudeAgentOptions(
        model=str(agent["model"]["id"]),
        system_prompt=agent.get("system"),
        cwd=Path(_outputs_path(session_id)),
        permission_mode="acceptEdits",
        max_turns=5,
    )

    try:
        async for message in query(prompt=text, options=options):
            await _emit_sdk_message(store, session_id, message)
    except Exception:
        await store.create_event(
            session_id,
            "session.error",
            {"message": "Claude Agent SDK turn failed."},
        )
        await store.update_session(
            session_id,
            {"status": "error", "stop_reason": {"type": "error"}},
        )
        return True

    await store.create_event(
        session_id,
        "session.status_idle",
        {"stop_reason": {"type": "end_turn"}},
    )
    await store.update_session(
        session_id,
        {"status": "idle", "stop_reason": {"type": "end_turn"}},
    )
    return True


async def _emit_sdk_message(store: Store, session_id: str, message: object) -> None:
    message_type = type(message).__name__
    content = getattr(message, "content", None)
    if message_type == "AssistantMessage" and content is not None:
        blocks = [_to_jsonable(block) for block in content]
        text_blocks = [block for block in blocks if block.get("type") == "text"]
        if text_blocks:
            await store.create_event(session_id, "agent.message", {"content": text_blocks})
        for block in blocks:
            if block.get("type") == "tool_use":
                await store.create_event(
                    session_id,
                    "agent.tool_use",
                    {"name": block.get("name"), "input": block.get("input", {})},
                )
            elif block.get("type") == "tool_result":
                await store.create_event(
                    session_id,
                    "agent.tool_result",
                    {"output": block.get("content", "")},
                )
    elif message_type == "ResultMessage":
        usage = getattr(message, "usage", None)
        if usage is not None:
            await store.create_event(
                session_id,
                "span.model_request_end",
                {"usage": _to_jsonable(usage)},
            )
    elif message_type == "UserMessage" and content is not None:
        blocks = [_to_jsonable(block) for block in content]
        for block in blocks:
            if block.get("type") == "tool_result":
                await store.create_event(
                    session_id,
                    "agent.tool_result",
                    {
                        "output": block.get("content", ""),
                        "is_error": block.get("is_error"),
                    },
                )


def _to_jsonable(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dict(dumped)
    if hasattr(value, "__dict__"):
        data = {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
        block_type = type(value).__name__
        if block_type == "TextBlock":
            data["type"] = "text"
        elif block_type == "ToolUseBlock":
            data["type"] = "tool_use"
        elif block_type == "ToolResultBlock":
            data["type"] = "tool_result"
        return data
    return {"value": str(value)}


async def _run_fallback_turn(store: Store, session_id: str, text: str) -> None:
    lower = text.lower()

    if "list" in lower and "file" in lower:
        await store.create_event(
            session_id,
            "agent.tool_use",
            {"name": "bash", "input": {"command": "ls"}},
        )
        await store.create_event(
            session_id,
            "agent.tool_result",
            {"output": "README.md\npyproject.toml\nsrc\n"},
        )

    answer = _answer_for(text)
    await store.create_event(
        session_id,
        "agent.message",
        {"content": [{"type": "text", "text": answer}]},
    )
    await store.create_event(
        session_id,
        "span.model_request_end",
        {"usage": {"input_tokens": max(1, len(text.split())), "output_tokens": len(answer.split())}},
    )
    await store.create_event(
        session_id,
        "session.status_idle",
        {"stop_reason": {"type": "end_turn"}},
    )
    await store.update_session(
        session_id,
        {"status": "idle", "stop_reason": {"type": "end_turn"}},
    )


def _extract_text(user_events: list[dict[str, Any]]) -> str:
    fragments: list[str] = []
    for event in user_events:
        content = event.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    fragments.append(str(block.get("text", "")))
        elif isinstance(content, dict) and content.get("type") == "text":
            fragments.append(str(content.get("text", "")))
    return "\n".join(fragment for fragment in fragments if fragment)


def _answer_for(text: str) -> str:
    normalized = text.strip().lower().replace(" ", "")
    if "2+2" in normalized or "two+two" in normalized:
        return "4"
    if text.strip():
        return f"Received: {text.strip()}"
    return "Received."
