"""dev.sh runs commands directly inside the app container, via Docker otherwise.

compose.yaml sets IN_APP_CONTAINER=1 on the app service, so a developer can use
the same ./dev.sh commands from the host or inside the dev container. A fake
`docker` on PATH records what would have been run, so no Docker is needed here.
"""

from __future__ import annotations

import os
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
    docker.write_text(f'#!/usr/bin/env bash\necho "$*" >> {log}\n')
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
