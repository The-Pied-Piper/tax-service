"""Where ./dev.sh upgrade fetches the template from, and how init records it.

init records the template's address in TEMPLATE_REPO: the --template-repo
argument if given, otherwise the template at the same host and scheme (SSH or
HTTPS) as the service's own `origin`, so access that works for the service
works for the template. upgrade uses, in order: the TEMPLATE_REPO environment
variable, then the TEMPLATE_REPO file; with neither it stops.

The scripts run from a copy in a temporary directory, with fake `git` and
`docker` commands that record what they were asked to do.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = (ROOT / "TEMPLATE_HOME").read_text().strip()

FAKE_GIT = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$1" in
  remote) [[ -n "${FAKE_ORIGIN:-}" ]] && echo "$FAKE_ORIGIN" || exit 2 ;;
  status) ;;            # clean working tree
  clone) exit 1 ;;      # stop the upgrade once it has chosen where to clone from
esac
"""
FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
"""


class Repo:
    """A copy of dev.sh and scripts/ with fake git and docker on PATH."""

    def __init__(self, root: Path) -> None:
        self.root = root / "service"
        self.root.mkdir()
        shutil.copy2(ROOT / "dev.sh", self.root / "dev.sh")
        shutil.copytree(ROOT / "scripts", self.root / "scripts")
        shutil.copy2(ROOT / "TEMPLATE_HOME", self.root / "TEMPLATE_HOME")
        self.bin = root / "bin"
        self.bin.mkdir()
        for name, body in (("git", FAKE_GIT), ("docker", FAKE_DOCKER)):
            tool = self.bin / name
            tool.write_text(body)
            tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
        self.log = root / "calls.log"

    def dev_sh(
        self,
        *args: str,
        origin: str | None,
        env_repo: str | None = None,
        env_path: str | None = None,
        in_container: bool,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"IN_APP_CONTAINER", "TEMPLATE_REPO", "TEMPLATE_PATH", "FAKE_ORIGIN"}
        }
        env["PATH"] = f"{self.bin}{os.pathsep}{env['PATH']}"
        env["FAKE_LOG"] = str(self.log)
        if origin is not None:
            env["FAKE_ORIGIN"] = origin
        if env_repo is not None:
            env["TEMPLATE_REPO"] = env_repo
        if env_path is not None:
            env["TEMPLATE_PATH"] = env_path
        if in_container:
            env["IN_APP_CONTAINER"] = "1"
        return subprocess.run(
            [str(self.root / "dev.sh"), *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )

    def calls(self, prefix: str) -> list[str]:
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return [line for line in lines if line.startswith(prefix)]

    def cloned_from(self) -> str:
        (clone,) = self.calls("clone")
        return clone.split()[-2]  # clone -q --depth 1 --branch REF URL DEST

    @property
    def recorded(self) -> str:
        return (self.root / "TEMPLATE_REPO").read_text().strip()


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


# --- upgrade: which address it fetches from ----------------------------------------


def test_upgrade_prefers_the_recorded_address(repo: Repo) -> None:
    (repo.root / "TEMPLATE_REPO").write_text("git@example.org:mirror/template.git\n")

    repo.dev_sh("upgrade", origin="https://github.com/Someone/svc.git", in_container=True)

    assert repo.cloned_from() == "git@example.org:mirror/template.git"


def test_upgrade_prefers_the_environment_over_everything(repo: Repo) -> None:
    (repo.root / "TEMPLATE_REPO").write_text("git@example.org:mirror/template.git\n")

    repo.dev_sh(
        "upgrade",
        origin="git@github.com:Someone/svc.git",
        env_repo="https://example.com/override.git",
        in_container=True,
    )

    assert repo.cloned_from() == "https://example.com/override.git"


def test_upgrade_without_any_recorded_address_says_so(repo: Repo) -> None:
    result = repo.dev_sh("upgrade", origin="https://github.com/Someone/svc.git", in_container=True)

    assert result.returncode != 0
    assert "the template's address is unknown" in result.stderr
    assert repo.calls("clone") == []


def test_upgrade_with_a_blank_recorded_address_says_so(repo: Repo) -> None:
    (repo.root / "TEMPLATE_REPO").write_text("\n")

    result = repo.dev_sh("upgrade", origin="https://github.com/Someone/svc.git", in_container=True)

    assert result.returncode != 0
    assert "the template's address is unknown" in result.stderr
    assert repo.calls("clone") == []


def test_init_with_an_explicit_address_needs_no_template_home(repo: Repo) -> None:
    (repo.root / "TEMPLATE_HOME").unlink()

    result = repo.dev_sh(
        "init", "--template-repo", "git@example.org:m/t.git", origin=None, in_container=False
    )

    assert result.returncode == 0, result.stderr
    assert repo.recorded == "git@example.org:m/t.git"


# --- init: what it records ---------------------------------------------------------


def test_init_records_the_template_at_the_origins_scheme(repo: Repo) -> None:
    result = repo.dev_sh("init", origin="git@github.com:Someone/svc.git", in_container=False)

    assert result.returncode == 0, result.stderr
    assert repo.recorded == f"git@github.com:{TEMPLATE_PATH}"


def test_init_takes_the_templates_path_from_the_environment(repo: Repo) -> None:
    result = repo.dev_sh(
        "init",
        origin="git@github.com:Someone/svc.git",
        env_path="Other/fork.git",
        in_container=False,
    )

    assert result.returncode == 0, result.stderr
    assert repo.recorded == "git@github.com:Other/fork.git"


def test_init_records_the_given_address(repo: Repo) -> None:
    result = repo.dev_sh(
        "init",
        "--template-repo",
        "git@example.org:mirror/template.git",
        "--name",
        "svc",
        origin="https://github.com/Someone/svc.git",
        in_container=False,
    )

    assert result.returncode == 0, result.stderr
    assert repo.recorded == "git@example.org:mirror/template.git"
    (generator,) = [c for c in repo.calls("docker compose run") if "service_gen" in c]
    assert generator.endswith(
        "init --name service --template-repo git@example.org:mirror/template.git --name svc"
    )


def test_init_requires_a_value_for_template_repo(repo: Repo) -> None:
    result = repo.dev_sh("init", "--template-repo", origin=None, in_container=False)

    assert result.returncode != 0
    assert "--template-repo needs a value" in result.stderr
    assert not (repo.root / "TEMPLATE_REPO").exists()
