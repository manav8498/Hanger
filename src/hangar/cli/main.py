from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, cast

import click
import httpx
import typer
from httpx_sse import ServerSentEvent, connect_sse
from rich.console import Console
from typer.core import TyperArgument, TyperOption

from hangar.version import __version__

DEFAULT_URL = "http://localhost:8080"
DEFAULT_API_KEY = "hgr_test_key"
DEFAULT_ADMIN_TOKEN = "change-me"

JsonObject = dict[str, Any]


def _patch_typer_click_help() -> None:
    # Typer 0.13 calls make_metavar() without ctx; Click 8.3 requires ctx.
    def option_make_metavar(self: Any, ctx: click.Context | None = None) -> str:
        if ctx is not None:
            return str(click.Option.make_metavar(self, ctx))
        if self.metavar is not None:
            return str(self.metavar)
        metavar = str(self.type.name).upper()
        if self.nargs != 1:
            metavar += "..."
        return metavar

    def argument_make_metavar(self: Any, ctx: click.Context | None = None) -> str:
        if self.metavar is not None:
            return str(self.metavar)
        var = str(self.name or "").upper()
        if not self.required:
            var = f"[{var}]"
        type_var = self.type.get_metavar(param=self, ctx=ctx) if ctx is not None else self.type.name
        if type_var:
            var += f":{type_var}"
        if self.nargs != 1:
            var += "..."
        return var

    TyperOption.make_metavar = option_make_metavar  # type: ignore[method-assign]
    TyperArgument.make_metavar = argument_make_metavar  # type: ignore[method-assign]


_patch_typer_click_help()


@dataclass(frozen=True)
class CliConfig:
    url: str
    api_key: str


app = typer.Typer(help="Hangar control plane CLI.", rich_markup_mode=None)
agent_app = typer.Typer(help="Manage agents.", rich_markup_mode=None)
env_app = typer.Typer(help="Manage environments.", rich_markup_mode=None)
session_app = typer.Typer(help="Manage sessions.", rich_markup_mode=None)
admin_app = typer.Typer(help="Administrative commands.", rich_markup_mode=None)

app.add_typer(agent_app, name="agent")
app.add_typer(env_app, name="env")
app.add_typer(session_app, name="session")
app.add_typer(admin_app, name="admin")


@app.callback()
def configure(
    ctx: typer.Context,
    url: Annotated[
        str,
        typer.Option(
            "--url",
            envvar="HANGAR_URL",
            help="Hangar API base URL.",
            show_default=True,
        ),
    ] = DEFAULT_URL,
    api_key: Annotated[
        str,
        typer.Option(
            "--api-key",
            envvar="HANGAR_API_KEY",
            help="Hangar API key.",
            show_default=True,
        ),
    ] = DEFAULT_API_KEY,
) -> None:
    """Control a local Hangar runtime.

    Example: hangar --url http://localhost:8080 agent list
    """

    ctx.obj = CliConfig(url=url.rstrip("/"), api_key=api_key)


@agent_app.command("create")
def create_agent(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="Agent name.")],
    model: Annotated[str, typer.Option("--model", help="Claude model ID.")],
    system: Annotated[str | None, typer.Option("--system", help="System prompt.")] = None,
) -> None:
    """Create an agent.

    Example: hangar agent create --name test --model claude-opus-4-7 --system "Be brief."
    """

    body: JsonObject = {
        "name": name,
        "model": {"id": model},
        "tools": [{"type": "agent_toolset_20260401"}],
    }
    if system is not None:
        body["system"] = system
    _print_json(_request_json(ctx, "POST", "/v1/agents", json_body=body))


@agent_app.command("list")
def list_agents(ctx: typer.Context) -> None:
    """List agents.

    Example: hangar agent list
    """

    _print_json(_request_json(ctx, "GET", "/v1/agents"))


@agent_app.command("get")
def get_agent(ctx: typer.Context, agent_id: str) -> None:
    """Get an agent by ID.

    Example: hangar agent get agent_01abc
    """

    _print_json(_request_json(ctx, "GET", f"/v1/agents/{agent_id}"))


@agent_app.command("archive")
def archive_agent(ctx: typer.Context, agent_id: str) -> None:
    """Archive an agent.

    Example: hangar agent archive agent_01abc
    """

    _print_json(_request_json(ctx, "POST", f"/v1/agents/{agent_id}/archive"))


@env_app.command("create")
def create_environment(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="Environment name.")],
    env_type: Annotated[str, typer.Option("--type", help="Environment type.")] = "cloud",
) -> None:
    """Create an environment.

    Example: hangar env create --name dev-env
    """

    if env_type != "cloud":
        _fail("Only cloud environments are supported.")
    _print_json(
        _request_json(
            ctx,
            "POST",
            "/v1/environments",
            json_body={
                "name": name,
                "config": {"type": env_type, "networking": {"type": "unrestricted"}},
            },
        )
    )


@env_app.command("list")
def list_environments(ctx: typer.Context) -> None:
    """List environments.

    Example: hangar env list
    """

    _print_json(_request_json(ctx, "GET", "/v1/environments"))


@env_app.command("get")
def get_environment(ctx: typer.Context, env_id: str) -> None:
    """Get an environment by ID.

    Example: hangar env get env_01abc
    """

    _print_json(_request_json(ctx, "GET", f"/v1/environments/{env_id}"))


@session_app.command("create")
def create_session(
    ctx: typer.Context,
    agent: Annotated[str, typer.Option("--agent", help="Agent ID.")],
    env: Annotated[str, typer.Option("--env", help="Environment ID.")],
    title: Annotated[str | None, typer.Option("--title", help="Session title.")] = None,
) -> None:
    """Create a session.

    Example: hangar session create --agent agent_01abc --env env_01abc --title "Quick check"
    """

    body: JsonObject = {"agent": agent, "environment_id": env}
    if title is not None:
        body["title"] = title
    _print_json(_request_json(ctx, "POST", "/v1/sessions", json_body=body))


@session_app.command("list")
def list_sessions(ctx: typer.Context) -> None:
    """List sessions.

    Example: hangar session list
    """

    _print_json(_request_json(ctx, "GET", "/v1/sessions"))


@session_app.command("get")
def get_session(ctx: typer.Context, session_id: str) -> None:
    """Get a session by ID.

    Example: hangar session get ses_01abc
    """

    _print_json(_request_json(ctx, "GET", f"/v1/sessions/{session_id}"))


@session_app.command("terminate")
def terminate_session(ctx: typer.Context, session_id: str) -> None:
    """Terminate a session.

    Example: hangar session terminate ses_01abc
    """

    _print_json(_request_json(ctx, "POST", f"/v1/sessions/{session_id}/terminate"))


@session_app.command("send")
def send_session_message(
    ctx: typer.Context,
    session_id: str,
    message: Annotated[str, typer.Option("--message", help="Text to send.")],
) -> None:
    """Send a user message to a session.

    Example: hangar session send ses_01abc --message "What is 2+2?"
    """

    _print_json(
        _request_json(
            ctx,
            "POST",
            f"/v1/sessions/{session_id}/events",
            json_body={
                "events": [
                    {
                        "type": "user.message",
                        "content": [{"type": "text", "text": message}],
                    }
                ]
            },
        )
    )


@session_app.command("stream")
def stream_session(
    ctx: typer.Context,
    session_id: str,
    follow: Annotated[bool, typer.Option("--follow", help="Keep streaming after idle.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print full event JSON.")] = False,
) -> None:
    """Stream session events.

    Example: hangar session stream ses_01abc
    """

    config = _config(ctx)
    with _make_client(config) as client:
        last_id, saw_idle = _print_event_history(client, config, session_id, verbose=verbose)
        if saw_idle and not follow:
            return

        headers = _auth_headers(config)
        if last_id is not None:
            headers["Last-Event-ID"] = str(last_id)

        try:
            with connect_sse(
                client,
                "GET",
                f"/v1/sessions/{session_id}/events/stream",
                headers=headers,
            ) as event_source:
                for event in event_source.iter_sse():
                    if event.event == "ping":
                        continue
                    _print_sse_event(event, verbose=verbose)
                    if event.event == "session.status_idle" and not follow:
                        break
        except httpx.HTTPStatusError as exc:
            _handle_http_error(exc.response)
        except httpx.RequestError as exc:
            _fail(f"API request failed: {exc}")


@admin_app.command("create-api-key")
def create_admin_api_key(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="API key name.")],
    admin_token: Annotated[
        str | None,
        typer.Option(
            "--admin-token",
            envvar="HANGAR_ADMIN_TOKEN",
            help="Admin token.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Create an API key.

    Example: hangar admin create-api-key --name dev
    """

    response = _request_json(
        ctx,
        "POST",
        "/v1/api-keys",
        json_body={"name": name},
        headers={"x-admin-token": admin_token or _default_admin_token()},
        authenticated=False,
    )
    key = response.get("key")
    if not isinstance(key, str):
        _fail("API response did not include a key.")
    _out().print(key)


@admin_app.command("health")
def admin_health(ctx: typer.Context) -> None:
    """Read the API health endpoint.

    Example: hangar admin health
    """

    _print_json(_request_json(ctx, "GET", "/", authenticated=False))


@app.command("version")
def version() -> None:
    """Print the Hangar version.

    Example: hangar version
    """

    _out().print(__version__)


def _request_json(
    ctx: typer.Context,
    method: str,
    path: str,
    *,
    json_body: JsonObject | None = None,
    headers: dict[str, str] | None = None,
    authenticated: bool = True,
) -> JsonObject:
    config = _config(ctx)
    request_headers = _auth_headers(config) if authenticated else {}
    if headers:
        request_headers.update(headers)
    with _make_client(config) as client:
        try:
            response = client.request(method, path, json=json_body, headers=request_headers)
        except httpx.RequestError as exc:
            _fail(f"API request failed: {exc}")
    if response.status_code >= 400:
        _handle_http_error(response)
    if response.status_code == 204 or not response.content:
        return {}
    data = response.json()
    if not isinstance(data, dict):
        _fail("API response was not a JSON object.")
    return cast(JsonObject, data)


def _print_event_history(
    client: httpx.Client,
    config: CliConfig,
    session_id: str,
    *,
    verbose: bool,
) -> tuple[int | None, bool]:
    try:
        response = client.get(f"/v1/sessions/{session_id}/events", headers=_auth_headers(config))
    except httpx.RequestError as exc:
        _fail(f"API request failed: {exc}")
    if response.status_code >= 400:
        _handle_http_error(response)
    data = response.json()
    events = data.get("data") if isinstance(data, dict) else None
    if not isinstance(events, list):
        _fail("API response did not include an event list.")
    typed_events = cast(list[Any], events)

    last_id: int | None = None
    saw_idle = False
    for raw_event in typed_events:
        if not isinstance(raw_event, dict):
            continue
        event_id = raw_event.get("id")
        if isinstance(event_id, int):
            last_id = event_id
        elif isinstance(event_id, str) and event_id.isdigit():
            last_id = int(event_id)
        event_type = str(raw_event.get("type", "event"))
        content = _json_object(raw_event.get("content"))
        _print_event_line(
            event_type,
            content,
            created_at=_optional_string(raw_event.get("created_at")),
            verbose=verbose,
        )
        if event_type == "session.status_idle":
            saw_idle = True
    return last_id, saw_idle


def _print_sse_event(event: ServerSentEvent, *, verbose: bool) -> None:
    content = _parse_event_data(event.data)
    _print_event_line(event.event, content, created_at=_event_created_at(content), verbose=verbose)


def _print_event_line(
    event_type: str,
    content: JsonObject,
    *,
    created_at: str | None,
    verbose: bool,
) -> None:
    summary = _truncate(_event_summary(event_type, content))
    _out().print(f"[{_time_label(created_at)}] {event_type}: {summary}")
    if verbose:
        _out().print_json(data=content)


def _event_summary(event_type: str, content: JsonObject) -> str:
    if event_type == "agent.message":
        text = _content_text(content)
        return text or json.dumps(content, separators=(",", ":"))
    if event_type == "session.status_idle":
        stop_reason = content.get("stop_reason")
        if isinstance(stop_reason, dict):
            reason_type = stop_reason.get("type")
            if isinstance(reason_type, str):
                return reason_type
    if event_type.startswith("session.status_"):
        return event_type.removeprefix("session.status_")
    if event_type == "session.error":
        message = content.get("message")
        if isinstance(message, str):
            return message
    if event_type == "span.model_request_end":
        usage = content.get("usage")
        if isinstance(usage, dict):
            return json.dumps(usage, separators=(",", ":"))
    return json.dumps(content, separators=(",", ":"))


def _content_text(content: JsonObject) -> str:
    blocks = content.get("content")
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(str(block["text"]))
    return "".join(parts)


def _time_label(created_at: str | None) -> str:
    if created_at:
        try:
            return datetime.fromisoformat(created_at.replace("Z", "+00:00")).strftime("%H:%M:%S")
        except ValueError:
            pass
    return datetime.now().strftime("%H:%M:%S")


def _event_created_at(content: JsonObject) -> str | None:
    return _optional_string(content.get("created_at")) or _optional_string(content.get("ts"))


def _truncate(value: str, limit: int = 80) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _parse_event_data(data: str) -> JsonObject:
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {"data": data}
    return _json_object(parsed)


def _json_object(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _handle_http_error(response: httpx.Response) -> None:
    if response.status_code == 401:
        _fail(
            "API request rejected (401). Check your API key. You can create one with: "
            "hangar admin create-api-key --name NAME"
        )
    message = response.text
    try:
        data = response.json()
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                message = str(error["message"])
    except ValueError:
        pass
    _fail(f"API request failed ({response.status_code}): {message}")


def _print_json(data: JsonObject) -> None:
    _out().print_json(data=data)


def _auth_headers(config: CliConfig) -> dict[str, str]:
    return {"x-api-key": config.api_key}


def _make_client(config: CliConfig) -> httpx.Client:
    return httpx.Client(base_url=config.url, timeout=None)


def _default_admin_token() -> str:
    env_token = os.environ.get("HANGAR_ADMIN_TOKEN")
    if env_token:
        return env_token
    try:
        with open(".env", encoding="utf-8") as env_file:
            for line in env_file:
                key, separator, value = line.strip().partition("=")
                if separator and key == "HANGAR_ADMIN_TOKEN":
                    return value
    except OSError:
        pass
    return DEFAULT_ADMIN_TOKEN


def _config(ctx: typer.Context) -> CliConfig:
    if not isinstance(ctx.obj, CliConfig):
        _fail("CLI context was not initialized.")
    return cast(CliConfig, ctx.obj)


def _out() -> Console:
    return Console(color_system=None, highlight=False)


def _err() -> Console:
    return Console(stderr=True, color_system=None, highlight=False)


def _fail(message: str) -> None:
    _err().print(f"[red]Error: {message}[/red]")
    raise typer.Exit(1)
