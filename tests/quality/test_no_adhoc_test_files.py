"""Repository-level guardrails for test file naming hygiene."""

from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"

FORBIDDEN_FILENAME_PATTERNS = (
    re.compile(r"^test_.*_improvements\.py$"),
    re.compile(r"^test_.*_runtime\.py$"),
    re.compile(r"^test_quick_.*\.py$"),
    re.compile(r"^test_.*_coverage.*\.py$"),
)


def test_no_adhoc_test_files_in_repo() -> None:
    """`docs/TEST_OPTIMIZATION_PLAN.md` kuralını otomatik doğrular."""
    violations: list[str] = []

    for path in TESTS_ROOT.rglob("test_*.py"):
        if any(pattern.match(path.name) for pattern in FORBIDDEN_FILENAME_PATTERNS):
            violations.append(path.relative_to(REPO_ROOT).as_posix())

    assert not violations, (
        "Ad-hoc test dosyaları tespit edildi. Dosyaları ilgili ana modül testlerine taşıyın: "
        + ", ".join(sorted(violations))
    )
