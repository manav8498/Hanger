from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import datetime
from types import TracebackType
from typing import Any, Literal, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hangar.api.app import app as api_app
from hangar.cli import main as cli


class ClientProxy:
    def __init__(self, client: TestClient) -> None:
        self._client = client

    def __enter__(self) -> ClientProxy:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        return False

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return self._client.request(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._client.get(url, **kwargs)

    def stream(self, method: str, url: str, **kwargs: Any) -> Any:
        return self._client.stream(method, url, **kwargs)


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> Iterator[CliRunner]:
    with TestClient(api_app, base_url="http://test") as client:
        proxy = ClientProxy(client)

        def make_client(_config: cli.CliConfig) -> ClientProxy:
            return proxy

        monkeypatch.setattr(cli, "_make_client", make_client)
        yield CliRunner()


def test_help_lists_command_groups(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "agent" in result.output
    assert "env" in result.output
    assert "session" in result.output
    assert "admin" in result.output
    assert "version" in result.output


def test_version(runner: CliRunner) -> None:
    result = _invoke(runner, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0-dev"


def test_admin_create_api_key_and_health(runner: CliRunner) -> None:
    created = _invoke(runner, ["admin", "create-api-key", "--name", "dev"])
    health = _invoke(runner, ["admin", "health"])

    assert created.exit_code == 0
    assert created.output.strip().startswith("hgr_")
    assert "Hangar 0.1.0-dev" in health.output
    assert "database" in health.output
    assert "dbos" in health.output
    assert "docker" in health.output


def test_agent_commands(runner: CliRunner) -> None:
    created = _json(
        _invoke(
            runner,
            [
                "agent",
                "create",
                "--name",
                "test-agent",
                "--model",
                "claude-opus-4-7",
                "--system",
                "Be brief.",
            ],
        )
    )
    agent_id = str(created["id"])

    listed = _json(_invoke(runner, ["agent", "list"]))
    fetched = _json(_invoke(runner, ["agent", "get", agent_id]))
    archived = _json(_invoke(runner, ["agent", "archive", agent_id]))

    assert listed["data"][0]["id"] == agent_id
    assert fetched["id"] == agent_id
    assert archived["archived_at"] is not None


def test_environment_commands(runner: CliRunner) -> None:
    created = _json(_invoke(runner, ["env", "create", "--name", "dev-env"]))
    env_id = str(created["id"])

    listed = _json(_invoke(runner, ["env", "list"]))
    fetched = _json(_invoke(runner, ["env", "get", env_id]))

    assert listed["data"][0]["id"] == env_id
    assert fetched["id"] == env_id


def test_session_commands_send_and_stream(runner: CliRunner) -> None:
    agent = _json(_invoke(runner, ["agent", "create", "--name", "test", "--model", "claude-opus-4-7"]))
    environment = _json(_invoke(runner, ["env", "create", "--name", "dev-env"]))
    session = _json(
        _invoke(
            runner,
            [
                "session",
                "create",
                "--agent",
                str(agent["id"]),
                "--env",
                str(environment["id"]),
                "--title",
                "CLI test",
            ],
        )
    )
    session_id = str(session["id"])

    running = _wait_for_running(runner, session_id)
    listed = _json(_invoke(runner, ["session", "list"]))
    sent = _json(_invoke(runner, ["session", "send", session_id, "--message", "What is 2+2?"]))
    streamed = _invoke(runner, ["session", "stream", session_id])
    terminated = _json(_invoke(runner, ["session", "terminate", session_id]))

    assert running["status"] == "running"
    assert listed["data"][0]["id"] == session_id
    assert sent["events"][0]["type"] == "user.message"
    assert "agent.message" in streamed.output
    assert "4" in streamed.output
    assert "session.status_idle" in streamed.output
    assert terminated["status"] == "terminated"


def test_auth_failure_prints_401(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["--url", "http://test", "--api-key", "bad", "agent", "list"])

    assert result.exit_code != 0
    assert "401" in _combined_output(result)


def test_time_label_converts_utc_timestamp_to_local_time() -> None:
    known = "2026-05-07T19:58:53.000Z"
    expected = datetime.fromisoformat(known.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")

    assert cli._time_label(known) == expected


def _wait_for_running(runner: CliRunner, session_id: str) -> dict[str, Any]:
    for _ in range(20):
        session = _json(_invoke(runner, ["session", "get", session_id]))
        if session["status"] == "running":
            return session
        time.sleep(0.05)
    raise AssertionError("session did not reach running")


def _invoke(runner: CliRunner, args: list[str]) -> Any:
    result = runner.invoke(cli.app, ["--url", "http://test", *args])
    assert result.exit_code == 0, _combined_output(result)
    return result


def _json(result: Any) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(result.output))


def _combined_output(result: Any) -> str:
    stderr = getattr(result, "stderr", "")
    return str(result.output) + str(stderr)
