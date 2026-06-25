from __future__ import annotations

import re
from pathlib import Path

_INLINE_NOSEC_PROSE = re.compile(r"#\s*nosec\s+B\d{3}\s+[-–—]")


def test_nosec_comments_keep_explanatory_prose_outside_bandit_directive() -> None:
    """Keep Bandit from parsing explanatory words as test IDs."""
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in root.rglob("*.py"):
        if any(part in {".git", ".venv", "node_modules", "web_ui_react"} for part in path.parts):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _INLINE_NOSEC_PROSE.search(line):
                offenders.append(f"{path.relative_to(root)}:{line_number}")

    assert offenders == []
