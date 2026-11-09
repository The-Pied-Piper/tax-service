"""Render the project scaffold, generated code, and per-tag stubs."""

from __future__ import annotations

import ast
import shutil
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .spec import Spec, resolve_property_names

TEMPLATES = Path(__file__).resolve().parent / "templates"

# The service package always has this name; Dockerfile, compose and Alembic rely on it.
PACKAGE = "app"

# Scaffold files: (template, destination relative to project root). "{pkg}" is the package dir.
# Written once by `init`; everything else in the repo is a plain file shipped by the template.
PROJECT_FILES: tuple[tuple[str, str], ...] = (
    ("project/README.md.j2", "README.md"),
    ("project/pkg/__init__.py.j2", "{pkg}/__init__.py"),
    ("project/pkg/main.py.j2", "{pkg}/main.py"),
    ("project/pkg/settings.py.j2", "{pkg}/settings.py"),
    ("project/pkg/domain/__init__.py.j2", "{pkg}/domain/__init__.py"),
    ("project/pkg/domain/errors.py.j2", "{pkg}/domain/errors.py"),
    ("project/pkg/adapters/__init__.py.j2", "{pkg}/adapters/__init__.py"),
    ("project/pkg/adapters/inbound/__init__.py.j2", "{pkg}/adapters/inbound/__init__.py"),
    ("project/pkg/adapters/inbound/http_errors.py.j2", "{pkg}/adapters/inbound/http_errors.py"),
    ("project/pkg/adapters/outbound/__init__.py.j2", "{pkg}/adapters/outbound/__init__.py"),
    ("project/pkg/adapters/outbound/db/__init__.py.j2", "{pkg}/adapters/outbound/db/__init__.py"),
    ("project/pkg/adapters/outbound/db/engine.py.j2", "{pkg}/adapters/outbound/db/engine.py"),
    ("project/pkg/adapters/outbound/db/health.py.j2", "{pkg}/adapters/outbound/db/health.py"),
    ("project/pkg/adapters/outbound/db/models.py.j2", "{pkg}/adapters/outbound/db/models.py"),
    ("project/pkg/application/__init__.py.j2", "{pkg}/application/__init__.py"),
    ("project/pkg/application/ports/__init__.py.j2", "{pkg}/application/ports/__init__.py"),
    ("project/pkg/application/ports/health.py.j2", "{pkg}/application/ports/health.py"),
    ("project/pkg/application/services/__init__.py.j2", "{pkg}/application/services/__init__.py"),
    ("project/tests/__init__.py.j2", "tests/__init__.py"),
    ("project/tests/conftest.py.j2", "tests/conftest.py"),
    ("project/tests/test_app.py.j2", "tests/test_app.py"),
)

# Per-tag stubs: created only if missing so business logic survives `sync`.
TAG_STUBS: tuple[tuple[str, str], ...] = (
    ("stubs/adapter.py.j2", "{pkg}/adapters/inbound/{tag}_adapter.py"),
    ("stubs/port.py.j2", "{pkg}/application/ports/{tag}_port.py"),
    ("stubs/service.py.j2", "{pkg}/application/services/{tag}_service.py"),
)

SPEC_DEST = "openapi/openapi.yml"


@dataclass
class Report:
    written: list[Path]
    skipped: list[Path]


class Renderer:
    def __init__(self, project_dir: Path, name: str, spec: Spec, template_repo: str = "") -> None:
        self.project_dir = project_dir
        self.name = name
        self.package = PACKAGE
        self.spec = spec
        self.template_repo = template_repo
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATES),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.report = Report(written=[], skipped=[])

    # -- public -------------------------------------------------------------

    def scaffold(self) -> None:
        """Write the one-time project scaffold (init only)."""
        for template, target in PROJECT_FILES:
            self._write(template, self._path(target), overwrite=True)

    def generate(self) -> None:
        """Regenerate everything under <pkg>/generated. Always overwrites."""
        generated = self.project_dir / self.package / "generated"
        handlers = generated / "handlers"
        if handlers.exists():
            shutil.rmtree(handlers)
        handlers.mkdir(parents=True)

        self._write("generated/__init__.py.j2", generated / "__init__.py", overwrite=True)
        self._write("generated/handlers/__init__.py.j2", handlers / "__init__.py", overwrite=True)
        for tag in self.spec.tags:
            dest = handlers / f"{tag.snake}.py"
            self._write("generated/handlers/tag.py.j2", dest, overwrite=True, tag=tag)
        self._generate_models(generated / "models.py")

    def stubs(self) -> None:
        """Create per-tag adapter/port/service stubs where they don't exist yet."""
        resolve_property_names(self.spec, self._model_fields())
        for tag in self.spec.tags:
            for template, target in TAG_STUBS:
                self._write(template, self._path(target, tag=tag.snake), overwrite=False, tag=tag)

    # -- internals ----------------------------------------------------------

    def _model_fields(self) -> dict[str, dict[str, str]]:
        """Read back what the model generator named each field: {class: {wire name: attribute}}."""
        models = self.project_dir / self.package / "generated" / "models.py"
        found: dict[str, dict[str, str]] = {}
        for node in ast.parse(models.read_text()).body:
            if not isinstance(node, ast.ClassDef):
                continue
            fields: dict[str, str] = {}
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    aliases = [
                        kw.value.value
                        for kw in ast.walk(item)
                        if isinstance(kw, ast.keyword)
                        and kw.arg == "alias"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ]
                    fields[aliases[0] if aliases else item.target.id] = item.target.id
            found[node.name] = fields
        return found

    def _path(self, target: str, **extra: str) -> Path:
        return self.project_dir / target.format(pkg=self.package, **extra)

    def _context(self, **extra: Any) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "name": self.name,
            "package": self.package,
            "spec": self.spec,
            "template_repo": self.template_repo,
        }
        if "tag" in extra:
            ctx["models"] = extra["tag"].referenced_models(self.spec.model_names)
        return {**ctx, **extra}

    def _write(self, template: str, dest: Path, *, overwrite: bool, **extra: Any) -> None:
        if dest.exists() and not overwrite:
            self.report.skipped.append(dest)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.env.get_template(template).render(self._context(**extra)))
        self.report.written.append(dest)

    def _generate_models(self, dest: Path) -> None:
        from datamodel_code_generator import DataModelType, InputFileType, PythonVersion, generate
        from datamodel_code_generator.format import Formatter

        spec_path = self.project_dir / SPEC_DEST
        if not self.spec.model_names:
            dest.write_text('"""No components/schemas in the spec; nothing to generate."""\n')
            self.report.written.append(dest)
            return
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            generate(
                spec_path,
                input_file_type=InputFileType.OpenAPI,
                output=dest,
                output_model_type=DataModelType.PydanticV2BaseModel,
                target_python_version=PythonVersion.PY_312,
                formatters=[Formatter.RUFF_CHECK, Formatter.RUFF_FORMAT],
                snake_case_field=True,
                allow_population_by_field_name=True,
                use_standard_collections=True,
                use_union_operator=True,
                use_annotated=True,
                field_constraints=True,
                use_schema_description=True,
                disable_timestamp=True,
            )
        self.report.written.append(dest)
