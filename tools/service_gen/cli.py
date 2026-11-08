"""service-gen: scaffold and re-sync a hexagonal Connexion service from an OpenAPI spec.

Runs inside a service repository created from the service-template:

  init   one-time, in place: writes app/ (composition root, generated code, stubs) and tests/
  sync   after editing openapi/openapi.yml: regenerates app/generated/, adds stubs for new tags
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .render import PACKAGE, SPEC_DEST, Renderer
from .spec import SpecError, load_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service-gen", description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("."), help="repository root (default: cwd)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="scaffold the service in this repository")
    init.add_argument("--name", help="service name for the README (default: directory name)")
    init.add_argument("--template-repo", default="", help="address of the template, for the README")
    init.add_argument("--force", action="store_true", help=f"overwrite an existing {PACKAGE}/")
    init.set_defaults(func=cmd_init)

    sync = sub.add_parser("sync", help="regenerate models/handlers; add stubs for new operations")
    sync.set_defaults(func=cmd_sync)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (SpecError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def cmd_init(args: argparse.Namespace) -> int:
    root: Path = args.root.resolve()
    name = _validate_name(args.name or root.name)
    if (root / PACKAGE).exists() and not args.force:
        raise ValueError(f"{root / PACKAGE} already exists (use --force to overwrite)")

    renderer = Renderer(root, name, load_spec(_spec_path(root)), args.template_repo)
    renderer.scaffold()
    renderer.generate()
    renderer.stubs()
    _print_report(renderer, root)
    print("\nNext: ./dev.sh up")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    root: Path = args.root.resolve()
    if not (root / PACKAGE).is_dir():
        raise FileNotFoundError(f"{root / PACKAGE} not found; run `init` first")

    renderer = Renderer(root, root.name, load_spec(_spec_path(root)))
    renderer.generate()
    renderer.stubs()
    _print_report(renderer, root)
    new_stubs = [p for p in renderer.report.written if "_adapter.py" in p.name]
    if new_stubs:
        print(f"\nNew request adapters were created; wire them into {PACKAGE}/main.py.")
    return 0


def _spec_path(root: Path) -> Path:
    spec = root / SPEC_DEST
    if not spec.exists():
        raise FileNotFoundError(f"{spec} not found; put your OpenAPI document there")
    return spec


def _validate_name(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", name):
        raise ValueError("--name must start with a letter and contain only [a-zA-Z0-9_-]")
    return name


def _print_report(renderer: Renderer, root: Path) -> None:
    for path in renderer.report.written:
        print(f"  wrote   {path.relative_to(root)}")
    for path in renderer.report.skipped:
        print(f"  kept    {path.relative_to(root)}")


if __name__ == "__main__":
    sys.exit(main())
