"""Repository-level guardrails for test file naming hygiene."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

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


def test_no_adhoc_test_files_passes_when_no_forbidden_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forbidden pattern eşleşmesi yoksa test guardrail'i geçmelidir."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_valid_name.py").write_text("", encoding="utf-8")

    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "TESTS_ROOT", tmp_path / "tests")

    test_no_adhoc_test_files_in_repo()


def test_no_adhoc_test_files_fails_when_forbidden_file_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forbidden pattern eşleşmesinde ihlal listesi assert mesajına yansımalıdır."""
    (tmp_path / "tests").mkdir()
    forbidden = tmp_path / "tests" / "test_quick_regression.py"
    forbidden.write_text("", encoding="utf-8")

    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "TESTS_ROOT", tmp_path / "tests")

    with pytest.raises(AssertionError, match=r"test_quick_regression\.py"):
        test_no_adhoc_test_files_in_repo()
