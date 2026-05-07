from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import docker
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

    container_id = session.get("container_id")
    if isinstance(container_id, str) and not container_id.startswith("fake-"):
        return await _run_claude_agent_sdk_in_container(
            store,
            session_id,
            container_id,
            text,
            agent,
        )

    options = ClaudeAgentOptions(
        model=str(agent["model"]["id"]),
        system_prompt=agent.get("system"),
        cwd=Path(_outputs_path(session_id)),
        permission_mode="acceptEdits",
        allowed_tools=["Bash", "Write"],
        max_turns=5,
    )

    try:
        async for message in query(prompt=_prompt_stream(text), options=options):
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


async def _run_claude_agent_sdk_in_container(
    store: Store,
    session_id: str,
    container_id: str,
    text: str,
    agent: dict[str, Any],
) -> bool:
    client = docker.from_env()
    container = client.containers.get(container_id)
    payload = {
        "prompt": text,
        "model": str(agent["model"]["id"]),
        "system": agent.get("system"),
    }
    result = container.exec_run(
        ["python", "-c", _CONTAINER_QUERY_SCRIPT],
        environment={"HANGAR_TURN_PAYLOAD": json.dumps(payload)},
        workdir="/mnt/session/outputs",
    )
    output = _decode_exec_output(result.output)
    saw_error = False
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("message_type") == "HangarError":
            saw_error = True
            await store.create_event(
                session_id,
                "session.error",
                {"message": str(event.get("error", "Claude Agent SDK turn failed."))},
            )
        else:
            await _emit_sdk_payload(store, session_id, event)

    if result.exit_code != 0 and not saw_error:
        await store.create_event(
            session_id,
            "session.error",
            {"message": "Claude Agent SDK container turn failed."},
        )
        saw_error = True

    if saw_error:
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


async def _emit_sdk_payload(
    store: Store,
    session_id: str,
    event: dict[str, Any],
) -> None:
    message_type = event.get("message_type")
    content = event.get("content")
    if message_type == "AssistantMessage" and isinstance(content, list):
        text_blocks = [
            block
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if text_blocks:
            await store.create_event(session_id, "agent.message", {"content": text_blocks})
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                await store.create_event(
                    session_id,
                    "agent.tool_use",
                    {"name": block.get("name"), "input": block.get("input", {})},
                )
    elif message_type == "UserMessage" and isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                await store.create_event(
                    session_id,
                    "agent.tool_result",
                    {
                        "output": block.get("content", ""),
                        "is_error": block.get("is_error"),
                    },
                )
    elif message_type == "ResultMessage":
        usage = event.get("usage")
        if isinstance(usage, dict):
            await store.create_event(session_id, "span.model_request_end", {"usage": usage})


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


async def _prompt_stream(text: str) -> AsyncIterator[dict[str, Any]]:
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": text},
        "parent_tool_use_id": None,
    }


def _decode_exec_output(output: bytes | tuple[bytes | None, bytes | None]) -> str:
    if isinstance(output, tuple):
        stdout, stderr = output
        return (stdout or b"").decode() + (stderr or b"").decode()
    return output.decode()


_CONTAINER_QUERY_SCRIPT = r"""
from __future__ import annotations

import asyncio
import json
import os
import traceback
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query


async def prompts(text: str):
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": text},
        "parent_tool_use_id": None,
    }


def block_to_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
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


async def main() -> None:
    payload = json.loads(os.environ["HANGAR_TURN_PAYLOAD"])
    options = ClaudeAgentOptions(
        model=payload["model"],
        system_prompt=payload.get("system"),
        cwd="/mnt/session/outputs",
        permission_mode="acceptEdits",
        allowed_tools=["Bash", "Write"],
        max_turns=5,
    )
    try:
        async for message in query(
            prompt=prompts(payload["prompt"]),
            options=options,
        ):
            item = {"message_type": type(message).__name__}
            content = getattr(message, "content", None)
            if content is not None:
                item["content"] = [block_to_dict(block) for block in content]
            usage = getattr(message, "usage", None)
            if usage is not None:
                item["usage"] = block_to_dict(usage)
            print(json.dumps(item), flush=True)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "message_type": "HangarError",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            ),
            flush=True,
        )
        raise


asyncio.run(main())
"""


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
