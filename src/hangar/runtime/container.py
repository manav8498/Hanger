from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docker


@dataclass(frozen=True)
class ContainerHandle:
    id: str
    name: str
    outputs_host_path: str


async def provision_container(env_config: dict[str, Any], session_id: str) -> ContainerHandle:
    if os.environ.get("HANGAR_RUNTIME_MODE") == "fake":
        return ContainerHandle(
            id=f"fake-{session_id}",
            name=f"hangar-{session_id}",
            outputs_host_path=_outputs_path(session_id),
        )
    return _provision_container_sync(env_config, session_id)


def terminate_container(container_id: str | None) -> None:
    if not container_id or container_id.startswith("fake-"):
        return
    client = docker.from_env()
    try:
        container = client.containers.get(container_id)
        container.remove(force=True)
    except docker.errors.NotFound:
        return


def _provision_container_sync(env_config: dict[str, Any], session_id: str) -> ContainerHandle:
    client = docker.from_env()
    image = "python:3.12-slim"
    name = f"hangar-{session_id}"
    outputs_path = _outputs_path(session_id)
    outputs_host_path = _outputs_host_path(session_id)
    Path(outputs_path).mkdir(parents=True, exist_ok=True)
    Path(outputs_host_path).mkdir(parents=True, exist_ok=True)

    packages = env_config.get("packages", {})
    pip_packages = packages.get("pip", [])
    install_command = ""
    if pip_packages:
        quoted = " ".join(str(package) for package in pip_packages)
        install_command = f"python -m pip install {quoted} && "
    command = f"/bin/sh -lc '{install_command}sleep infinity'"

    try:
        existing = client.containers.get(name)
        existing.reload()
        return ContainerHandle(
            id=str(existing.id),
            name=name,
            outputs_host_path=outputs_host_path,
        )
    except docker.errors.NotFound:
        pass

    container = client.containers.run(
        image,
        command=command,
        detach=True,
        name=name,
        mem_limit="2g",
        nano_cpus=1_000_000_000,
        volumes={outputs_host_path: {"bind": "/mnt/session/outputs", "mode": "rw"}},
    )
    return ContainerHandle(id=str(container.id), name=name, outputs_host_path=outputs_host_path)


def _outputs_path(session_id: str) -> str:
    root = os.environ.get("HANGAR_SESSIONS_ROOT", "/var/lib/hangar/sessions")
    return str(Path(root) / session_id / "outputs")


def _outputs_host_path(session_id: str) -> str:
    root = os.environ.get("HANGAR_DOCKER_HOST_SESSIONS_ROOT")
    if root:
        return str(Path(root) / session_id / "outputs")
    return _outputs_path(session_id)
