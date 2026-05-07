from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from collections.abc import AsyncIterator
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query


async def prompts(text: str) -> AsyncIterator[dict[str, Any]]:
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
            item: dict[str, Any] = {"message_type": type(message).__name__}
            content = getattr(message, "content", None)
            if content is not None:
                item["content"] = [block_to_dict(block) for block in content]
            usage = getattr(message, "usage", None)
            if usage is not None:
                item["usage"] = block_to_dict(usage)
            sys.stdout.write(json.dumps(item) + "\n")
            sys.stdout.flush()
    except Exception as exc:
        sys.stdout.write(
            json.dumps(
                {
                    "message_type": "HangarError",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            )
            + "\n"
        )
        sys.stdout.flush()
        raise


if __name__ == "__main__":
    asyncio.run(main())
