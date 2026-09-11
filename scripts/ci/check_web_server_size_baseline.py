"""Fail closed when web_server.py grows past its committed line-count budget.

web_server.py is documented (see docs/module-notes/web_server.py.md and
web/routes/plugin_marketplace.py's own module docstring) as a thin,
backward-compatible facade over web/routes/*'s already-modular route
factories -- not a place for new route/middleware/plugin logic. Unlike that
prose, nothing previously stopped the file from quietly growing anyway: this
check turns the documented intent into an enforced, one-way budget. New
features belong in a new or existing ``web/routes/*.py`` module, not in
``web_server.py`` itself.

Deliberately simpler than the bandit-suppression and module-notes ratchets
(no ``--update`` flag): a real reduction here means logic actually moved out
of the file, which is a reviewed, deliberate change -- the baseline should be
edited by hand as part of that same PR, not auto-ratcheted by a script.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET_PATH = ROOT / "web_server.py"
DEFAULT_BASELINE = ROOT / "scripts" / "ci" / "web-server-size-baseline.json"


def count_lines(path: Path) -> int:
    """Return the number of lines in ``path`` (0 if it does not exist)."""
    if not path.is_file():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def main(argv: list[str] | None = None) -> int:
    """Compare web_server.py's current line count with the committed one-way budget."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=TARGET_PATH)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args(argv)

    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        maximum = baseline["maximum_lines"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"web_server.py size baseline is invalid: {args.baseline}: {exc}")
        return 2
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
        print("maximum_lines must be a non-negative integer")
        return 2

    current = count_lines(args.target)
    print(f"web_server.py satır sayısı: {current} (maximum={maximum})")
    if current <= maximum:
        return 0

    print(
        f"web_server.py boyut bütçesi aşıldı: {current} > {maximum}. "
        "Yeni route/middleware/plugin mantığı web_server.py'ye değil, "
        "web/routes/ altındaki bir modüle eklenmelidir "
        "(bkz. docs/module-notes/web_server.py.md)."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
