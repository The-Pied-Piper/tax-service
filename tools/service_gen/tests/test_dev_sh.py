"""dev.sh runs commands directly inside the app container, via Docker otherwise.

compose.yaml sets IN_APP_CONTAINER=1 on the app service, so a developer can use
the same ./dev.sh commands from the host or inside the dev container. A fake
`docker` on PATH records what would have been run, so no Docker is needed here.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def fake_docker(tmp_path: Path) -> Path:
    """A `docker` that records its arguments to calls.log instead of running."""
    log = tmp_path / "calls.log"
    docker = tmp_path / "bin" / "docker"
    docker.parent.mkdir()
    docker.write_text(
        "#!/usr/bin/env bash\n"
        # scripts/_lib.sh asks which Docker context is in use; that is not a recorded call.
        f'if [[ "$1" == context ]]; then echo "${{FAKE_DOCKER_CONTEXT:-default}}"; exit 0; fi\n'
        f'echo "$*" >> {log}\n'
    )
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    return log


def dev_sh(*args: str, fake_docker: Path, in_container: bool) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "IN_APP_CONTAINER"}
    env["PATH"] = f"{fake_docker.parent / 'bin'}{os.pathsep}{env['PATH']}"
    if in_container:
        env["IN_APP_CONTAINER"] = "1"
    return subprocess.run(
        [str(ROOT / "dev.sh"), *args], cwd=ROOT, env=env, capture_output=True, text=True
    )


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


# --- from the host: through a one-off app container --------------------------------


def test_host_runs_commands_in_an_app_container(fake_docker: Path) -> None:
    result = dev_sh("run", "echo", "hi", fake_docker=fake_docker, in_container=False)

    assert result.returncode == 0, result.stderr
    assert calls(fake_docker) == ["compose run --rm app echo hi"]


def test_host_runs_database_free_commands_without_the_database(fake_docker: Path) -> None:
    result = dev_sh("lint-spec", fake_docker=fake_docker, in_container=False)

    assert result.returncode == 0, result.stderr
    assert calls(fake_docker) == [
        "compose run --rm --no-deps app python -m openapi_spec_validator openapi/openapi.yml"
    ]


def test_host_manages_containers(fake_docker: Path) -> None:
    result = dev_sh("down", fake_docker=fake_docker, in_container=False)

    assert result.returncode == 0, result.stderr
    assert calls(fake_docker) == ["compose down"]


# --- inside the app container: directly, never through Docker ------------------------


def test_container_runs_commands_directly(fake_docker: Path) -> None:
    result = dev_sh("run", "echo", "hello", fake_docker=fake_docker, in_container=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "hello\n"
    assert calls(fake_docker) == []


def test_container_runs_database_free_commands_directly(fake_docker: Path) -> None:
    result = dev_sh("lint-spec", fake_docker=fake_docker, in_container=True)

    assert result.returncode == 0, result.stderr
    assert calls(fake_docker) == []


@pytest.mark.parametrize("command", ["up", "down", "build", "logs", "fresh", "psql", "init"])
def test_container_refuses_commands_that_manage_containers(fake_docker: Path, command: str) -> None:
    result = dev_sh(command, fake_docker=fake_docker, in_container=True)

    assert result.returncode != 0
    assert "run it from the host" in result.stderr
    assert calls(fake_docker) == []


# --- host conveniences: ssh agent and git identity ------------------------------------


def lib_env(fake_docker: Path | None = None, **extra: str) -> dict[str, str]:
    """What scripts/_lib.sh leaves exported, for a host with the given environment."""
    keep = ("PATH", "HOME")
    env = {k: v for k, v in os.environ.items() if k in keep}
    if fake_docker is not None:
        env["PATH"] = f"{fake_docker.parent / 'bin'}{os.pathsep}{env['PATH']}"
    env.update(extra)
    result = subprocess.run(
        ["bash", "-c", f"source {ROOT}/scripts/_lib.sh; env"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def agent_socket(tmp_path: Path) -> Path:
    sock_path = tmp_path / "agent.sock"
    with socket.socket(socket.AF_UNIX) as s:
        s.bind(str(sock_path))
    return sock_path


DOCKER_DESKTOP_SOCKET = "/run/host-services/ssh-auth.sock"


@pytest.mark.skipif(
    os.uname().sysname == "Darwin", reason="macOS always uses Docker Desktop's path"
)
def test_native_engine_gets_the_host_agent_socket(tmp_path: Path, fake_docker: Path) -> None:
    sock = agent_socket(tmp_path)

    env = lib_env(fake_docker, SSH_AUTH_SOCK=str(sock))

    assert env["SSH_AGENT_SOCKET"] == str(sock)


def test_docker_desktop_gets_its_own_agent_socket(tmp_path: Path, fake_docker: Path) -> None:
    env = lib_env(
        fake_docker,
        SSH_AUTH_SOCK=str(agent_socket(tmp_path)),
        FAKE_DOCKER_CONTEXT="desktop-linux",
    )

    assert env["SSH_AGENT_SOCKET"] == DOCKER_DESKTOP_SOCKET


@pytest.mark.skipif(
    os.uname().sysname == "Darwin", reason="macOS always uses Docker Desktop's path"
)
def test_no_ssh_agent_mounts_a_placeholder(fake_docker: Path) -> None:
    assert lib_env(fake_docker)["SSH_AGENT_SOCKET"] == "/dev/null"
    stale = lib_env(fake_docker, SSH_AUTH_SOCK="/nonexistent/agent.sock")
    assert stale["SSH_AGENT_SOCKET"] == "/dev/null"


def test_ssh_agent_sharing_can_be_turned_off(tmp_path: Path, fake_docker: Path) -> None:
    env = lib_env(
        fake_docker,
        SSH_AUTH_SOCK=str(agent_socket(tmp_path)),
        FAKE_DOCKER_CONTEXT="desktop-linux",
        DEV_SSH_AGENT="0",
    )

    assert env["SSH_AGENT_SOCKET"] == "/dev/null"


def test_an_explicit_agent_socket_is_kept(fake_docker: Path) -> None:
    env = lib_env(fake_docker, SSH_AGENT_SOCKET="/tmp/mine.sock", DEV_SSH_AGENT="0")

    assert env["SSH_AGENT_SOCKET"] == "/tmp/mine.sock"


def test_git_identity_comes_from_host_git_config(tmp_path: Path) -> None:
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = Ada Lovelace\n\temail = ada@example.com\n")
    env = lib_env(GIT_CONFIG_GLOBAL=str(config))

    assert env["GIT_AUTHOR_NAME"] == env["GIT_COMMITTER_NAME"] == "Ada Lovelace"
    assert env["GIT_AUTHOR_EMAIL"] == env["GIT_COMMITTER_EMAIL"] == "ada@example.com"


def has_docker_compose() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


@pytest.mark.skipif(not has_docker_compose(), reason="needs the docker CLI with compose")
@pytest.mark.parametrize(
    ("env", "source"),
    [
        ({}, "/dev/null"),
        ({"SSH_AUTH_SOCK": "/run/user/1000/gcr/ssh"}, "/dev/null"),
        ({"SSH_AGENT_SOCKET": "/tmp/a:b/agent.sock"}, "/tmp/a:b/agent.sock"),
    ],
)
def test_compose_mounts_the_agent_socket(env: dict[str, str], source: str) -> None:
    keep = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME")}
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        env={**keep, **env},
        capture_output=True,
        text=True,
        check=True,
    )
    volumes = json.loads(result.stdout)["services"]["app"]["volumes"]
    agent = next(v for v in volumes if v["target"] == "/tmp/ssh-agent.sock")
    assert agent["source"] == source
    assert agent["bind"]["create_host_path"] is False


@pytest.mark.skipif(not has_docker_compose(), reason="needs the docker CLI with compose")
def test_compose_passes_the_github_token_through() -> None:
    keep = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME")}
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        env={**keep, "GH_TOKEN": "t0ken"},
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout)["services"]["app"]["environment"]["GH_TOKEN"] == "t0ken"
