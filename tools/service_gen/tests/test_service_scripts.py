"""./dev.sh runs scripts/<cmd>.sh, else service_scripts/<cmd>.sh; help lists both.

service_scripts/ belongs to the service: upgrade must never replace it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _script(path: Path, help_text: str, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n# {help_text}\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def service(tmp_path: Path) -> Path:
    root = tmp_path / "service"
    root.mkdir()
    shutil.copy2(ROOT / "dev.sh", root / "dev.sh")
    shutil.copytree(ROOT / "scripts", root / "scripts")
    (root / "service_scripts").mkdir()
    return root


def dev(service: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(service / "dev.sh"), *args], capture_output=True, text=True, check=False
    )


def test_runs_a_service_script_with_its_arguments(service: Path) -> None:
    _script(service / "service_scripts" / "hi.sh", "Say hi.", 'echo "hi $*"')
    result = dev(service, "hi", "a", "b")
    assert result.returncode == 0
    assert result.stdout == "hi a b\n"


def test_template_script_wins_on_a_name_clash(service: Path) -> None:
    _script(service / "scripts" / "same.sh", "Template.", "echo template")
    _script(service / "service_scripts" / "same.sh", "Service.", "echo service")
    assert dev(service, "same").stdout == "template\n"
    assert "Service." not in dev(service, "help").stdout


def test_help_lists_both_groups(service: Path) -> None:
    _script(service / "service_scripts" / "hi.sh", "Say hi.", "true")
    _script(service / "service_scripts" / "_helper.sh", "Not a command.", "true")
    out = dev(service, "help").stdout
    head, _, own = out.partition("service_scripts/")
    assert "check" in head
    assert re.search(r"\bhi\s+Say hi\.", own)
    assert "_helper" not in out


def test_help_without_service_scripts_has_no_service_group(service: Path) -> None:
    assert "service_scripts" not in dev(service, "help").stdout


def test_unknown_and_underscore_commands_fail(service: Path) -> None:
    _script(service / "service_scripts" / "_helper.sh", "x", "echo ran")
    for cmd in ("nope", "_helper"):
        result = dev(service, cmd)
        assert f"unknown command: {cmd}" in result.stderr


def test_upgrade_does_not_replace_service_scripts() -> None:
    upgrade = (ROOT / "scripts" / "upgrade.sh").read_text()
    owned = re.search(r"^owned=\((.*)\)$", upgrade, re.M)
    assert owned is not None
    assert "service_scripts" not in owned.group(1)


def test_help_hides_what_dev_sh_would_not_run(service: Path) -> None:
    folder = service / "service_scripts"
    _script(folder / "_a.sh", "Helper.", "true")
    _script(folder / "scripts_clash.sh", "x", "true")
    _script(service / "scripts" / "scripts_clash.sh", "Template.", "true")
    (folder / "noexec.sh").write_text("#!/usr/bin/env bash\n# No exec bit.\n")
    (folder / "dir.sh").mkdir()
    out = dev(service, "help").stdout
    assert "service_scripts" not in out  # nothing runnable, so no empty group
    assert "noexec" not in out
    assert "dir " not in out
