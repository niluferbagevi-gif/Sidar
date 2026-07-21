from __future__ import annotations

import re
import tomllib
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


def test_bandit_does_not_globally_skip_dynamic_sql_check() -> None:
    """Regression test: B608 (dynamic SQL) must stay enabled project-wide.

    Only individually reviewed occurrences may suppress it via a line-level
    `# nosec B608  # <gerekçe>` comment (see core/router.py, core/db/monolith.py,
    core/db/prompt_registry.py, core/rag/backends/pgvector.py,
    scripts/migrate_sqlite_to_pg.py). A blanket skip would silently hide a real
    SQL injection risk introduced in new code that never gets a `# nosec` review.
    """
    root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert "B608" not in pyproject["tool"]["bandit"]["skips"]
