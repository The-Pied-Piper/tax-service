"""The pinned generator requirements ship with the template and ./dev.sh upgrade supplies them.

tools/service_gen/ is template-owned, so upgrade replaces it wholesale, pinned
requirements.txt included. The test runs upgrade on a service that lacks the file, with
a fake `git clone` that supplies the current template and a fake `docker`.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PINNED = "tools/service_gen/requirements.txt"

FAKE_GIT = f"""#!/usr/bin/env bash
case "$1" in
  clone) cp -R "{ROOT}/." "${{@: -1}}" ;;   # the current template, as the clone
  rev-parse) echo abc1234 ;;
  remote) exit 2 ;;
  *) ;;                                     # status: a clean working tree
esac
"""
FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
"""

DOCKERFILE = f"""FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt ./
FROM base AS dev
COPY requirements-dev.txt ./
COPY {PINNED} tools/service_gen/
RUN pip install -r requirements-dev.txt
"""
REQUIREMENTS_DEV = f"-r requirements.txt\n-r {PINNED}\npytest>=8.3\n"


def make_service(tmp_path: Path) -> Path:
    service = tmp_path / "service"
    service.mkdir()
    shutil.copy2(ROOT / "dev.sh", service / "dev.sh")
    shutil.copytree(ROOT / "scripts", service / "scripts")
    (service / "tools").mkdir()
    (service / "TEMPLATE_REPO").write_text("https://example.org/template.git\n")
    (service / "requirements.txt").write_text("alembic>=1.13\n")
    (service / "Dockerfile").write_text(DOCKERFILE)
    (service / "requirements-dev.txt").write_text(REQUIREMENTS_DEV)
    return service


def upgrade(
    tmp_path: Path, service: Path, template_repo: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ./dev.sh upgrade with fake git and docker on PATH (CI has no git)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "git").write_text(FAKE_GIT)
    for tool in bin_dir.iterdir():
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    env = {k: v for k, v in os.environ.items() if k != "IN_APP_CONTAINER"}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["FAKE_LOG"] = str(tmp_path / "calls.log")
    env.pop("TEMPLATE_REPO", None)
    if template_repo is not None:
        env["TEMPLATE_REPO"] = template_repo
    return subprocess.run(
        [str(service / "dev.sh"), "upgrade"],
        cwd=service,
        env=env,
        capture_output=True,
        text=True,
    )


def test_the_template_ships_the_pinned_generator_requirements() -> None:
    lines = (ROOT / PINNED).read_text().splitlines()
    pins = [line for line in lines if line and not line.startswith(("#", " "))]
    assert pins and all("==" in line for line in pins)


def pins(path: Path) -> dict[str, str]:
    lines = path.read_text().splitlines()
    return dict(
        line.split("==")
        for line in lines
        if line and not line.startswith(("#", " ")) and "==" in line
    )


def test_generator_pins_agree_with_the_dev_pins() -> None:
    dev = pins(ROOT / "requirements-dev.txt")
    for name, version in pins(ROOT / PINNED).items():
        assert dev.get(name) == version, f"{name}: {version} here, {dev.get(name)} in dev"


def test_upgrade_does_not_record_a_template_address(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    (service / "TEMPLATE_REPO").unlink()

    result = upgrade(tmp_path, service, template_repo="https://example.org/template.git")

    assert result.returncode == 0, result.stderr
    assert not (service / "TEMPLATE_REPO").exists()


def test_upgrade_supplies_the_file_the_dockerfile_copies(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    assert not (service / PINNED).exists()

    result = upgrade(tmp_path, service)

    assert result.returncode == 0, result.stderr
    sources = re.findall(r"^COPY (\S*tools/\S+) ", (service / "Dockerfile").read_text(), re.M)
    assert sources == [PINNED]
    assert (service / PINNED).read_text() == (ROOT / PINNED).read_text()
    assert "docker compose build app" in (tmp_path / "calls.log").read_text()
