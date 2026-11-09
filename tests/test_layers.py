"""The layers point inward: domain imports nothing of ours, application only domain and ports."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
ALLOWED = {
    "domain": {"app.domain"},
    "application": {"app.domain", "app.application"},
}
OUTSIDE = {"connexion", "pydantic", "sqlalchemy", "starlette", "tax_engine", "asyncio"}


def imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_inner_layers_import_only_inward_and_no_outside_libraries() -> None:
    problems = []
    for layer, allowed in ALLOWED.items():
        for path in sorted((APP / layer).rglob("*.py")):
            for module in imports(path):
                ours = module == "app" or module.startswith("app.")
                if ours and not any(module == a or module.startswith(a + ".") for a in allowed):
                    problems.append(f"{path.relative_to(APP)} imports {module}")
                if module.split(".")[0] in OUTSIDE:
                    problems.append(f"{path.relative_to(APP)} imports {module}")
    assert problems == []
