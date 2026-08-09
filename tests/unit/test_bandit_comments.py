from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

_INLINE_NOSEC_PROSE = re.compile(r"#\s*nosec\s+B\d{3}\s+[-–—]")
_NOSEC_B608_RE = re.compile(r"#\s*nosec\s+B608\b")
_SQL_IDENTIFIER_VALIDATOR_MODULES = {"core.db.dialect", "core.db_components.dialect"}
_SQL_IDENTIFIER_VALIDATOR_NAMES = {"assert_safe_sql_identifier", "is_safe_sql_identifier"}


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
    core/active_learning.py, scripts/migrate_sqlite_to_pg.py). A blanket skip
    would silently hide a real SQL injection risk introduced in new code that
    never gets a `# nosec` review.
    """
    root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert "B608" not in pyproject["tool"]["bandit"]["skips"]


def _imports_sql_identifier_validator(source: str) -> bool:
    """Return whether ``source`` imports a safe-identifier validator by name.

    Walks the AST rather than grepping so aliased imports (``as``) are still
    recognized correctly -- ``alias.name`` is the original imported name
    regardless of any local rebinding.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module in _SQL_IDENTIFIER_VALIDATOR_MODULES
            and {alias.name for alias in node.names} & _SQL_IDENTIFIER_VALIDATOR_NAMES
        ):
            return True
    return False


def test_router_and_pgvector_nosec_b608_usage_keeps_the_identifier_validator_import() -> None:
    """Guard the safe-identifier import backing router.py/pgvector.py's nosec.

    core/router.py and core/rag/backends/pgvector.py's `# nosec B608` f-string
    SQL is safe specifically because every interpolated table/column identifier
    is validated at the call site via `core.db.dialect`'s
    `assert_safe_sql_identifier`/`is_safe_sql_identifier` (canonical
    implementation: `core/db_components/dialect.py`) before it reaches the
    query string; real data values always go through bind parameters. A
    friend code review confirmed this and suggested a lightweight guard
    against the validator import silently disappearing while the `# nosec`
    markers stay behind -- this AST-based check pins it for exactly the two
    files reviewed (the other `# nosec B608` sites use different, individually
    reviewed safe patterns -- module-level constants, a hardcoded table
    allowlist, enumerated bind-parameter names -- not this validator, so they
    are intentionally out of scope here).
    """
    for relative_path in ("core/router.py", "core/rag/backends/pgvector.py"):
        root = Path(__file__).resolve().parents[2]
        source = (root / relative_path).read_text(encoding="utf-8")

        assert _NOSEC_B608_RE.search(source), f"{relative_path} no longer has '# nosec B608'"
        assert _imports_sql_identifier_validator(source), (
            f"{relative_path} has '# nosec B608' but no longer imports a safe-identifier "
            "validator (assert_safe_sql_identifier/is_safe_sql_identifier) from "
            "core.db.dialect/core.db_components.dialect"
        )
