"""End-to-end tests for `init` and `sync`.

The `project` fixture mimics "Use this template": it copies the template's plain
files into a temp dir, drops in the example spec, and runs `init` there.
"""

import ast
import importlib
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
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
        "app/adapters/inbound/http_errors.py",
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


def test_generated_project_is_lint_type_and_layer_clean(project: Path) -> None:
    for cmd in (
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "mypy", "."],
        [str(Path(sys.executable).parent / "lint-imports")],
    ):
        result = subprocess.run(cmd, cwd=project, capture_output=True, text=True)
        assert result.returncode == 0, " ".join(cmd) + "\n" + result.stdout + result.stderr


def test_main_registers_error_handling_but_does_not_define_it(project: Path) -> None:
    tree = ast.parse((project / "app" / "main.py").read_text())
    called: set[str] = set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    assert "register_error_handlers" in called
    assert "add_error_handler" not in called
    assert not {name for name in imported if name.startswith("connexion.problem")}


def test_full_request_flow(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    main_mod = _fresh_import(project, monkeypatch, "app.main")
    handlers = importlib.import_module("app.generated.handlers")
    status_adapter = importlib.import_module("app.adapters.inbound.status_adapter")
    widgets_adapter = importlib.import_module("app.adapters.inbound.widgets_adapter")
    status_service = importlib.import_module("app.application.services.status_service")
    errors = importlib.import_module("app.domain.errors")
    health = importlib.import_module("app.application.ports.health")
    models = importlib.import_module("app.generated.models")

    class FailingProbe:
        name = "fake"

        async def check(self) -> None:
            raise health.NotReadyError("fake: down")

    probes: list[object] = []

    class InMemoryWidgets:
        def __init__(self) -> None:
            self.store: dict[str, SimpleNamespace] = {}
            self.listed: list[tuple[int, object]] = []

        async def list_widgets(self, limit: int, cursor=None):  # type: ignore[no-untyped-def]
            self.listed.append((limit, cursor))
            return SimpleNamespace(items=[vars(w) for w in self.store.values()])

        async def create_widget(self, name, weight_grams=None):  # type: ignore[no-untyped-def]
            widget = SimpleNamespace(
                id="3fa85f64-5717-4562-b3fc-2c963f66afa6", name=name, weight_grams=weight_grams or 0
            )
            self.store[widget.id] = widget
            return widget

        async def get_widget(self, widget_id: UUID):  # type: ignore[no-untyped-def]
            assert isinstance(widget_id, UUID)
            if str(widget_id) not in self.store:
                raise errors.NotFoundError(widget_id)
            return self.store[str(widget_id)]

        async def delete_widget(self, widget_id: UUID):  # type: ignore[no-untyped-def]
            self.store.pop(str(widget_id), None)

    class PagingWidgetsAdapter(widgets_adapter.WidgetsRequestAdapter):  # type: ignore[name-defined,misc]
        """An author who maps the optional next_page_token, here as an explicit None."""

        async def list_widgets(self, page_size=None, page_token=None):  # type: ignore[no-untyped-def]
            page = await super().list_widgets(page_size, page_token)
            return models.WidgetPage(items=page.items, next_page_token=None)

    widgets_service = InMemoryWidgets()
    monkeypatch.setattr(
        main_mod,
        "build_adapters",
        lambda settings, engine: handlers.Adapters(
            status=status_adapter.StatusRequestAdapter(status_service.StatusService(probes)),
            widgets=PagingWidgetsAdapter(widgets_service),
        ),
    )
    client = main_mod.create_app().test_client()
    base = "/api/v1"

    created = client.post(f"{base}/widgets", json={"name": "bolt", "weightGrams": 12})
    assert created.status_code == 201, created.text
    assert created.json()["weightGrams"] == 12
    # An optional property that was not set is left out of the response, not sent as null.
    assert "note" not in created.json()
    widget_id = created.json()["id"]

    # The 404 declares application/problem+json next to the 200's application/json.
    fetched = client.get(f"{base}/widgets/{widget_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.headers["content-type"].startswith("application/json")
    assert fetched.json()["name"] == "bolt"
    page = client.get(f"{base}/widgets?pageSize=5").json()
    assert len(page["items"]) == 1
    # A property the adapter passed as None stays null: the browser tells null from absent.
    assert page["nextPageToken"] is None
    # The application gets a plain limit and a cursor, never the page size or token.
    assert client.get(f"{base}/widgets").status_code == 200
    assert widgets_service.listed == [(5, None), (20, None)]

    missing = client.get(f"{base}/widgets/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["title"] == "NotFoundError"
    assert missing.headers["content-type"].startswith("application/problem+json")

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
    errors = project / "app" / "adapters" / "inbound" / "http_errors.py"
    errors.write_text("# user edited\n")
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
    assert errors.read_text() == "# user edited\n"
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


# One planted violation per forbidden module and direction of every layer rule:
# (contract id, file to touch, line to add). A file that does not exist is created, with
# the package folders it needs. Weaken a contract (drop a module, flip a direction, clear
# `exhaustive`) and the matching plant stops failing, which fails the test below.
CORE_FORBIDDEN = (
    "connexion pydantic pydantic_core pydantic_settings sqlalchemy asyncpg alembic httpx "
    "fastapi jsonschema starlette app.generated app.settings"
).split()
OUTBOUND_FORBIDDEN = "connexion fastapi jsonschema pydantic starlette app.generated".split()
INBOUND_FORBIDDEN = "sqlalchemy asyncpg alembic app.settings".split()
MAIN_FORBIDDEN = (
    "pydantic pydantic_core app.domain.errors app.application.ports.health app.generated.models"
).split()
GENERATED_FORBIDDEN = (
    "app.application.ports.health app.domain.errors app.adapters.outbound.db.health "
    "app.settings app.main"
).split()
SETTINGS_FORBIDDEN = (
    "app.domain.errors app.application.ports.health app.adapters.inbound.http_errors "
    "app.generated.models app.main"
).split()
SERVICES = "app.application.services.status_service"

PLANTED_VIOLATIONS = [
    # Layers point inward, and every module is placed.
    ("layers", "app/domain/errors.py", "import app.adapters.inbound.http_errors"),
    ("layers", "app/domain/errors.py", "import app.application.ports.health"),
    ("layers", "app/application/plant.py", "import app.adapters.inbound.http_errors"),
    ("layers", "app/utils.py", "import os"),
    ("layers", "app/helpers/plant.py", "import os"),
    *[("core-framework-free", "app/domain/plant.py", f"import {m}") for m in CORE_FORBIDDEN],
    ("core-framework-free", "app/application/plant.py", "import httpx"),
    # Indirect chains: a violation reached through another module is still a violation.
    ("core-framework-free", "app/domain/plant.py", "import app.adapters.outbound.db.engine"),
    ("adapters-depend-on-ports-only", "app/adapters/inbound/plant.py", "import app.main"),
    (
        "inbound-no-persistence",
        "app/adapters/inbound/plant.py",
        "import app.adapters.outbound.db.engine",
    ),
    *[
        ("outbound-wire-free", "app/adapters/outbound/plant.py", f"import {m}")
        for m in OUTBOUND_FORBIDDEN
    ],
    ("adapters-sides", "app/adapters/other/plant.py", "import os"),
    ("adapters-sides", "app/adapters/helper.py", "import os"),
    ("adapters-sides", "app/adapters/inbound/plant.py", "import app.adapters.outbound.db.health"),
    ("adapters-sides", "app/adapters/outbound/plant.py", "import app.adapters.inbound.http_errors"),
    ("adapters-depend-on-ports-only", "app/adapters/inbound/plant.py", f"import {SERVICES}"),
    ("adapters-depend-on-ports-only", "app/adapters/outbound/plant.py", f"import {SERVICES}"),
    ("adapters-depend-on-ports-only", "app/generated/plant.py", f"import {SERVICES}"),
    ("application-sublayers", "app/application/ports/plant.py", f"import {SERVICES}"),
    ("application-sublayers", "app/application/dto.py", "import os"),
    ("application-sublayers", "app/application/usecases/plant.py", "import os"),
    *[
        ("generated-is-wire-only", "app/generated/plant.py", f"import {m}")
        for m in GENERATED_FORBIDDEN
    ],
    *[("settings-is-a-leaf", "app/settings.py", f"import {m}") for m in SETTINGS_FORBIDDEN],
    ("settings-is-a-leaf", "app/settings.py", "import app.adapters.outbound.db.engine"),
    *[
        ("inbound-no-persistence", "app/adapters/inbound/plant.py", f"import {m}")
        for m in INBOUND_FORBIDDEN
    ],
    *[("main-wires-concretes-only", "app/main.py", f"import {m}") for m in MAIN_FORBIDDEN],
]


def _lint_imports(project: Path, contract: str | None = None) -> subprocess.CompletedProcess[str]:
    exe = str(Path(sys.executable).parent / "lint-imports")
    args = ["--contract", contract] if contract else []
    return subprocess.run([exe, *args], cwd=project, capture_output=True, text=True)


def test_each_layer_rule_catches_its_planted_violation(project: Path) -> None:
    # Each contract exists and holds on the clean project, so a failure below is its own.
    for rule in sorted({rule for rule, _, _ in PLANTED_VIOLATIONS}):
        assert _lint_imports(project, rule).returncode == 0, rule
    missed = []
    for rule, rel, line in PLANTED_VIOLATIONS:
        path = project / rel
        original = path.read_text() if path.exists() else None
        created = [p for p in path.parents if p != project and not p.exists()]
        path.parent.mkdir(parents=True, exist_ok=True)
        for folder in created:
            (folder / "__init__.py").touch()
        path.write_text((original or "") + f"\n{line}  # noqa\n")
        try:
            result = _lint_imports(project, rule)
            if result.returncode == 0 or "BROKEN" not in result.stdout:
                missed.append((rule, rel, line))
        finally:
            if original is None:
                path.unlink()
                for folder in created:
                    shutil.rmtree(folder, ignore_errors=True)
            else:
                path.write_text(original)
    assert not missed, missed


def test_a_folder_without_init_is_flagged_because_import_linter_cannot_see_it(
    project: Path,
) -> None:
    folder = project / "app" / "helpers"
    folder.mkdir()
    (folder / "plant.py").write_text("import os\n\nvalue = os\n")

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "app"], cwd=project, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "INP001" in result.stdout
