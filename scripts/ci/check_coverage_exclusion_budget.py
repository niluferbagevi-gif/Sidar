"""Fail closed when production ``pragma: no cover`` exclusions increase."""

from __future__ import annotations

import argparse
import io
import json
import tokenize
from pathlib import Path

EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "migrations",
    "node_modules",
    "site-packages",
    "temp",
    "templates",
    "tests",
    "third_party",
    "venv",
    "web_ui_react",
}
MARKER = "# pragma: no cover"


def collect_exclusions(root: Path) -> dict[str, int]:
    """Return production Python files containing coverage exclusions and their counts."""
    inventory: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        source = path.read_text(encoding="utf-8")
        count = sum(
            MARKER in token.string
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.COMMENT
        )
        if count:
            inventory[relative.as_posix()] = count
    return inventory


def main(argv: list[str] | None = None) -> int:
    """Compare the current exclusion count with the committed one-way budget."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("scripts/ci/coverage-exclusion-baseline.json"),
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    baseline_path = args.baseline
    if not baseline_path.is_absolute():
        baseline_path = root / baseline_path

    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        maximum = baseline["maximum_production_exclusions"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"Coverage exclusion baseline is invalid: {baseline_path}: {exc}")
        return 2
    if not isinstance(maximum, int) or maximum < 0:
        print("maximum_production_exclusions must be a non-negative integer")
        return 2

    inventory = collect_exclusions(root)
    total = sum(inventory.values())
    print(
        "Production coverage exclusion inventory: "
        f"pragma_no_cover={total}, maximum={maximum}, files={len(inventory)}"
    )
    if total <= maximum:
        return 0

    print(f"Coverage exclusion budget exceeded: {total} > {maximum}")
    for path, count in sorted(inventory.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {path}: {count}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
