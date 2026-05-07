from __future__ import annotations

import os
import shlex
import tarfile
import time
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
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
    name = f"hangar-{session_id}"
    outputs_path = _outputs_path(session_id)
    outputs_host_path = _outputs_host_path(session_id)
    Path(outputs_path).mkdir(parents=True, exist_ok=True)
    Path(outputs_host_path).mkdir(parents=True, exist_ok=True)

    packages = env_config.get("packages", {})
    pip_packages = [str(package) for package in packages.get("pip", [])]
    image = _ensure_session_image(client, pip_packages)

    try:
        existing = client.containers.get(name)
        existing.reload()
        _wait_for_container_ready(existing)
        return ContainerHandle(
            id=str(existing.id),
            name=name,
            outputs_host_path=outputs_host_path,
        )
    except docker.errors.NotFound:
        pass

    container = client.containers.run(
        image,
        command=["sleep", "infinity"],
        detach=True,
        name=name,
        mem_limit="2g",
        nano_cpus=1_000_000_000,
        environment={"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")},
        volumes={outputs_host_path: {"bind": "/mnt/session/outputs", "mode": "rw"}},
    )
    _wait_for_container_ready(container)
    return ContainerHandle(id=str(container.id), name=name, outputs_host_path=outputs_host_path)


def _ensure_session_image(client: Any, pip_packages: list[str]) -> str:
    base_image = os.environ.get("HANGAR_SESSION_BASE_IMAGE", "python:3.12-slim")
    install_packages = list(pip_packages)
    if base_image == "python:3.12-slim":
        install_packages.insert(0, "claude-agent-sdk==0.1.76")
    tag = _session_image_tag(base_image, install_packages)
    try:
        client.images.get(tag)
        return tag
    except docker.errors.ImageNotFound:
        pass

    context = _session_image_context(base_image, install_packages)
    client.images.build(
        fileobj=context,
        custom_context=True,
        tag=tag,
        rm=True,
        pull=base_image == "python:3.12-slim",
    )
    return tag


def _session_image_tag(base_image: str, install_packages: list[str]) -> str:
    digest = sha256((base_image + "\n" + "\n".join(sorted(install_packages))).encode()).hexdigest()[:16]
    return f"hangar-session:{digest}"


def _session_image_context(base_image: str, install_packages: list[str]) -> BytesIO:
    runner_path = Path(__file__).with_name("agent_runner.py")
    dockerfile_lines = [
        f"FROM {base_image}",
        "WORKDIR /opt/hangar",
        "COPY agent_runner.py /opt/hangar/agent_runner.py",
    ]
    if install_packages:
        dockerfile_lines.append(
            "RUN python -m pip install --no-cache-dir "
            + " ".join(shlex.quote(package) for package in install_packages)
        )
    dockerfile_lines.extend(["RUN mkdir -p /mnt/session/outputs && touch /tmp/hangar_ready", ""])
    dockerfile = "\n".join(dockerfile_lines)
    stream = BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        _add_tar_file(archive, "Dockerfile", dockerfile.encode())
        _add_tar_file(archive, "agent_runner.py", runner_path.read_bytes())
    stream.seek(0)
    return stream


def _add_tar_file(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    archive.addfile(info, BytesIO(content))


def _outputs_path(session_id: str) -> str:
    root = os.environ.get("HANGAR_SESSIONS_ROOT", "/var/lib/hangar/sessions")
    return str(Path(root) / session_id / "outputs")


def _outputs_host_path(session_id: str) -> str:
    root = os.environ.get("HANGAR_DOCKER_HOST_SESSIONS_ROOT")
    if root:
        return str(Path(root) / session_id / "outputs")
    return _outputs_path(session_id)


def _wait_for_container_ready(container: Any, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        container.reload()
        if container.status not in {"created", "running"}:
            raise RuntimeError(f"Session container exited during startup: {container.status}")
        result = container.exec_run(["sh", "-lc", "test -f /tmp/hangar_ready"])
        if result.exit_code == 0:
            return
        time.sleep(1)
    raise TimeoutError("Timed out waiting for session container packages to install")
