"""End-to-end tests for `init` and `sync`.

The `project` fixture mimics "Use this template": it copies the template's plain
files into a temp dir, drops in the example spec, and runs `init` there.
"""

import importlib
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest
import yaml

from tools.service_gen.cli import main

HERE = Path(__file__).resolve().parent
TEMPLATE_ROOT = HERE.parent.parent.parent
EXAMPLE_SPEC = HERE / "widget-service.yml"

# Plain files a fresh template checkout ships; init writes app/ and tests/ next to them.
TEMPLATE_FILES = ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "alembic.ini")
TEMPLATE_DIRS = ("migrations",)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "widget-service"
    root.mkdir()
    for name in TEMPLATE_FILES:
        shutil.copyfile(TEMPLATE_ROOT / name, root / name)
    for name in TEMPLATE_DIRS:
        shutil.copytree(TEMPLATE_ROOT / name, root / name)
    (root / "openapi").mkdir()
    shutil.copyfile(EXAMPLE_SPEC, root / "openapi" / "openapi.yml")

    assert main(["--root", str(root), "init"]) == 0
    return root


def _fresh_import(project: Path, monkeypatch: pytest.MonkeyPatch, module: str):  # type: ignore[no-untyped-def]
    monkeypatch.syspath_prepend(str(project))
    for mod in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    return importlib.import_module(module)


def test_init_writes_expected_layout(project: Path) -> None:
    for rel in (
        "README.md",
        "app/main.py",
        "app/settings.py",
        "app/generated/models.py",
        "app/generated/handlers/__init__.py",
        "app/generated/handlers/widgets.py",
        "app/adapters/inbound/widgets_adapter.py",
        "app/application/ports/widgets_port.py",
        "app/application/services/widgets_service.py",
        "app/application/ports/health.py",
        "app/adapters/outbound/db/health.py",
        "app/domain/errors.py",
        "tests/test_app.py",
    ):
        assert (project / rel).exists(), rel
    assert "# widget-service" in (project / "README.md").read_text()


def test_init_refuses_to_overwrite(project: Path) -> None:
    assert main(["--root", str(project), "init"]) == 1
    assert main(["--root", str(project), "init", "--force"]) == 0


def test_init_needs_spec(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "init"]) == 1


def test_sync_needs_init(tmp_path: Path) -> None:
    (tmp_path / "openapi").mkdir()
    shutil.copyfile(EXAMPLE_SPEC, tmp_path / "openapi" / "openapi.yml")
    assert main(["--root", str(tmp_path), "sync"]) == 1


def test_generated_project_passes_its_own_tests(project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-W", "ignore"],
        cwd=project,
        env={"PATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_project_is_lint_and_type_clean(project: Path) -> None:
    for cmd in (
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "mypy", "."],
    ):
        result = subprocess.run(cmd, cwd=project, capture_output=True, text=True)
        assert result.returncode == 0, " ".join(cmd) + "\n" + result.stdout + result.stderr


def test_full_request_flow(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    main_mod = _fresh_import(project, monkeypatch, "app.main")
    handlers = importlib.import_module("app.generated.handlers")
    status_adapter = importlib.import_module("app.adapters.inbound.status_adapter")
    widgets_adapter = importlib.import_module("app.adapters.inbound.widgets_adapter")
    status_service = importlib.import_module("app.application.services.status_service")
    errors = importlib.import_module("app.domain.errors")
    health = importlib.import_module("app.application.ports.health")

    class FailingProbe:
        name = "fake"

        async def check(self) -> None:
            raise health.NotReadyError("fake: down")

    probes: list[object] = []

    class InMemoryWidgets:
        def __init__(self) -> None:
            self.store: dict[str, dict[str, object]] = {}

        async def list_widgets(self, page_size: int | None = None, cursor: str | None = None):  # type: ignore[no-untyped-def]
            return {"items": list(self.store.values()), "next_cursor": None}

        async def create_widget(self, body):  # type: ignore[no-untyped-def]
            widget = {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "name": body.name,
                "weight_grams": body.weight_grams or 0,
            }
            self.store[str(widget["id"])] = widget
            return widget

        async def get_widget(self, widget_id: UUID):  # type: ignore[no-untyped-def]
            assert isinstance(widget_id, UUID)
            if str(widget_id) not in self.store:
                raise errors.NotFoundError(widget_id)
            return self.store[str(widget_id)]

        async def delete_widget(self, widget_id: UUID):  # type: ignore[no-untyped-def]
            self.store.pop(str(widget_id), None)

    monkeypatch.setattr(
        main_mod,
        "build_adapters",
        lambda settings, engine: handlers.Adapters(
            status=status_adapter.StatusRequestAdapter(status_service.StatusService(probes)),
            widgets=widgets_adapter.WidgetsRequestAdapter(InMemoryWidgets()),
        ),
    )
    client = main_mod.create_app().test_client()
    base = "/api/v1"

    created = client.post(f"{base}/widgets", json={"name": "bolt", "weightGrams": 12})
    assert created.status_code == 201, created.text
    assert created.json()["weightGrams"] == 12
    widget_id = created.json()["id"]

    assert client.get(f"{base}/widgets/{widget_id}").json()["name"] == "bolt"
    assert len(client.get(f"{base}/widgets?pageSize=5").json()["items"]) == 1

    missing = client.get(f"{base}/widgets/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["title"] == "NotFoundError"

    malformed = client.get(f"{base}/widgets/not-a-uuid")
    assert malformed.status_code == 400, malformed.text
    assert "UUID" in malformed.json()["detail"]

    assert client.post(f"{base}/widgets", json={}).status_code == 400
    assert client.delete(f"{base}/widgets/{widget_id}").status_code == 204

    assert client.get(f"{base}/status/livez").json() == {"status": "ok"}
    assert client.get(f"{base}/status/readyz").status_code == 200
    probes.append(FailingProbe())
    not_ready = client.get(f"{base}/status/readyz")
    assert not_ready.status_code == 503
    assert not_ready.json()["detail"] == "fake: down"
    assert client.get(f"{base}/status/livez").status_code == 200


def test_sync_regenerates_but_keeps_user_code(project: Path) -> None:
    adapter = project / "app" / "adapters" / "inbound" / "widgets_adapter.py"
    adapter.write_text("# user edited\n")
    spec_path = project / "openapi" / "openapi.yml"
    spec = yaml.safe_load(spec_path.read_text())
    spec["paths"]["/ping"] = {
        "get": {
            "tags": ["Health"],
            "operationId": "ping",
            "responses": {"204": {"description": "pong"}},
        }
    }
    spec_path.write_text(yaml.safe_dump(spec))

    assert main(["--root", str(project), "sync"]) == 0

    assert adapter.read_text() == "# user edited\n"
    generated = project / "app" / "generated" / "handlers"
    assert (generated / "health.py").exists()
    assert (project / "app" / "adapters" / "inbound" / "health_adapter.py").exists()
    assert '"ping": health_handlers.ping' in (generated / "__init__.py").read_text()


def test_readme_names_the_template_address_only_when_given(tmp_path: Path) -> None:
    from tools.service_gen.render import Renderer
    from tools.service_gen.spec import load_spec

    spec = load_spec(HERE / "widget-service.yml")
    for index, given in enumerate(("git@example.org:m/t.git", "")):
        out = tmp_path / str(index)
        out.mkdir()
        Renderer(out, "widget-service", spec, given).scaffold()
        readme = (out / "README.md").read_text()
        assert ("service-template (`git@example.org:m/t.git`);" in readme) == bool(given)
        assert "service-template ()" not in readme
