"""The layers point inward, and the two kinds of adapter never see each other.

Only app/main.py (the composition root) and app/generated may see both sides.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
FRAMEWORKS = {"connexion", "pydantic", "sqlalchemy", "starlette"}
RULES: dict[str, dict[str, set[str]]] = {
    # layer: {"ours": app modules it may import, "never": top-level or app modules it may not}
    "domain": {"ours": {"app.domain"}, "never": FRAMEWORKS | {"tax_engine", "asyncio"}},
    "application": {
        "ours": {"app.domain", "app.application"},
        "never": FRAMEWORKS | {"tax_engine", "asyncio"},
    },
    "adapters/inbound": {
        "ours": {"app.domain", "app.application", "app.generated.models", "app.adapters.inbound"},
        "never": {"tax_engine", "sqlalchemy", "app.adapters.outbound"},
    },
    "adapters/outbound": {
        "ours": {"app.domain", "app.application", "app.adapters.outbound", "app.settings"},
        "never": {"connexion", "pydantic", "starlette", "app.generated", "app.adapters.inbound"},
    },
}


def imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def within(module: str, names: set[str]) -> bool:
    return any(module == name or module.startswith(name + ".") for name in names)


def test_every_layer_imports_only_what_it_may() -> None:
    problems = []
    for layer, rule in RULES.items():
        for path in sorted((APP / layer).rglob("*.py")):
            for module in imports(path):
                if within(module, rule["never"]):
                    problems.append(f"{path.relative_to(APP)} imports {module}")
                elif within(module, {"app"}) and not within(module, rule["ours"]):
                    problems.append(f"{path.relative_to(APP)} imports {module}")
    assert problems == []
