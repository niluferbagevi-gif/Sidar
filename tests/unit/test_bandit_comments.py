from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

import pytest

from scripts.ci import check_bandit_suppression_baseline as suppression_baseline

_INLINE_NOSEC_PROSE = re.compile(r"#\s*nosec\s+B\d{3}\s+[-–—]")
_NOSEC_B608_RE = re.compile(r"#\s*nosec\s+B608\b")
_NOSEC_B608_WITH_RATIONALE_RE = re.compile(r"#\s*nosec\s+B608\b\s+#\s*\S")
_BARE_NOSEC_RE = re.compile(r"#\s*nosec\s*(?:$|#)")
_SQL_IDENTIFIER_VALIDATOR_MODULES = {"core.db.dialect", "core.db_components.dialect"}
_SQL_IDENTIFIER_VALIDATOR_NAMES = {"assert_safe_sql_identifier", "is_safe_sql_identifier"}
_REVIEWED_B608_FILES = (
    "core/db/monolith.py",
    "core/active_learning.py",
    "core/db/prompt_registry.py",
    "core/rag/backends/pgvector.py",
    "core/router.py",
)
_B608_RATCHET_MAX = 20


def test_bandit_suppression_baseline_matches_current_scan_and_quality_gates() -> None:
    """Keep the global nosec ratchet in both local and CI security gates."""
    root = Path(__file__).resolve().parents[2]
    baseline = json.loads((root / "bandit-suppression-baseline.json").read_text(encoding="utf-8"))
    local_gate = (root / "scripts/test_gates/backend_helpers.sh").read_text(encoding="utf-8")
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert baseline["maximum_skipped_tests"] == 50
    assert [target["maximum_skipped_tests"] for target in baseline["reduction_targets"]] == [
        40,
        20,
        0,
    ]
    assert suppression_baseline._reduction_targets(root / "bandit-suppression-baseline.json")
    assert suppression_baseline._requires_exact_baseline(root / "bandit-suppression-baseline.json")
    owner, review_order = suppression_baseline._debt_plan(root / "bandit-suppression-baseline.json")
    assert owner == "security-review"
    assert review_order == (
        "scripts/ci/verify_required_checks.py",
        "github_upload.py",
    )
    for relative_path in review_order:
        assert "# nosec" in (root / relative_path).read_text(encoding="utf-8")
    command = "uv run python scripts/ci/check_bandit_suppression_baseline.py"
    assert command in local_gate
    assert command in ci


def test_bandit_suppression_report_parser_fails_closed(tmp_path: Path) -> None:
    """Malformed or missing Bandit suppression metrics must never pass the ratchet."""
    report = tmp_path / "bandit.json"
    report.write_text('{"metrics":{"_totals":{"skipped_tests":72}}}', encoding="utf-8")
    assert suppression_baseline._skipped_tests(report) == 72

    report.write_text('{"metrics":{"_totals":{}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="skipped_tests"):
        suppression_baseline._skipped_tests(report)


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


def test_production_nosec_directives_always_name_bandit_rules() -> None:
    """Reject broad production suppressions that hide unrelated Bandit findings."""
    root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if any(
            part in {".git", ".venv", "node_modules", "tests", "web_ui_react"}
            for part in path.parts
        ):
            continue
        if path == Path(__file__).resolve():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _BARE_NOSEC_RE.search(line):
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


def test_reviewed_core_b608_suppressions_do_not_exceed_ratchet() -> None:
    """Prevent dynamic-SQL suppressions from returning after expression migration."""
    root = Path(__file__).resolve().parents[2]
    occurrences = sum(
        len(_NOSEC_B608_RE.findall((root / relative_path).read_text(encoding="utf-8")))
        for relative_path in _REVIEWED_B608_FILES
    )

    assert occurrences <= _B608_RATCHET_MAX


def test_all_b608_suppressions_include_reviewable_rationale() -> None:
    """Require every dynamic-SQL exception to state why interpolation is safe."""
    root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if any(part in {".git", ".venv", "node_modules"} for part in path.parts):
            continue
        if path == Path(__file__).resolve():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _NOSEC_B608_RE.search(line) and not _NOSEC_B608_WITH_RATIONALE_RE.search(line):
                offenders.append(f"{path.relative_to(root)}:{line_number}")

    assert offenders == []


def test_reduction_targets_must_strictly_decrease(tmp_path: Path) -> None:
    """Reject roadmaps that merely preserve or increase the current debt ceiling."""
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "maximum_skipped_tests": 72,
                "reduction_targets": [{"due_date": "2026-10-31", "maximum_skipped_tests": 72}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="kesin azalmalıdır"):
        suppression_baseline._reduction_targets(baseline)


def test_exact_baseline_policy_must_be_explicit_boolean(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"require_exact_baseline": "yes"}), encoding="utf-8")

    with pytest.raises(ValueError, match="boolean"):
        suppression_baseline._requires_exact_baseline(baseline)


def test_bandit_debt_plan_requires_unique_python_hotspots(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "debt_plan": {
                    "owner": "security-review",
                    "review_order": ["core/db.py", "core/db.py"],
                    "rule": "Do not bulk-remove suppressions.",
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="benzersiz Python dosyaları"):
        suppression_baseline._debt_plan(baseline)


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


def test_pgvector_uses_audited_builder_without_b608_suppressions() -> None:
    """Keep pgvector dynamic identifiers on the central validated SQL sink."""
    root = Path(__file__).resolve().parents[2]
    source = (root / "core/rag/backends/pgvector.py").read_text(encoding="utf-8")

    assert not _NOSEC_B608_RE.search(source)
    assert _imports_sql_identifier_validator(source)
    assert "render_sql_identifier_template" in source


def test_db_monolith_uses_audited_builder_without_b608_suppressions() -> None:
    """Keep schema-version SQL on the central validated composition sink."""
    root = Path(__file__).resolve().parents[2]
    source = (root / "core/db/monolith.py").read_text(encoding="utf-8")

    assert not _NOSEC_B608_RE.search(source)
    assert "from core.db.dialect import render_sql_identifier_template" in source
