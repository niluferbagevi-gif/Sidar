from __future__ import annotations

import re
import subprocess
import tomllib
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.ci import check_nosec_inventory

_INLINE_NOSEC_PROSE = re.compile(r"#\s*nosec\s+B\d{3}\s+[-–—]")
_REPO_ROOT = Path(__file__).resolve().parents[2]


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


def test_nosec_inventory_has_no_drift() -> None:
    """Regression guard: every real `# nosec` in the tree is registered, current,
    unexpired, and within the ratchet ceiling in security/nosec_inventory.tsv."""
    failures = check_nosec_inventory.check_nosec_inventory(_REPO_ROOT)
    assert failures == []


def test_ci_runs_nosec_inventory_check() -> None:
    workflow = (_REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Check nosec suppression inventory ratchet" in workflow
    assert "uv run python scripts/ci/check_nosec_inventory.py" in workflow


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def _stage_all(root: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def test_nosec_inventory_flags_unregistered_suppression(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "mod.py").write_text("x = 1  # nosec B608\n", encoding="utf-8")
    _stage_all(tmp_path)
    inventory = tmp_path / "nosec_inventory.tsv"
    inventory.write_text(
        "# path\tline\tbandit_rule\treason\towner\treview_by\treplacement_plan\n# ratchet_max_entries: 0\n",
        encoding="utf-8",
    )

    failures = check_nosec_inventory.check_nosec_inventory(tmp_path, inventory)

    assert any("unregistered nosec" in failure and "mod.py:1" in failure for failure in failures)


def test_nosec_inventory_flags_stale_entry(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _stage_all(tmp_path)
    inventory = tmp_path / "nosec_inventory.tsv"
    inventory.write_text(
        "# path\tline\tbandit_rule\treason\towner\treview_by\treplacement_plan\n"
        "# ratchet_max_entries: 1\n"
        "mod.py\t1\tB608\treason\t@owner\t2099-01-01\tN/A\n",
        encoding="utf-8",
    )

    failures = check_nosec_inventory.check_nosec_inventory(tmp_path, inventory)

    assert any("stale nosec entry" in failure and "mod.py:1" in failure for failure in failures)


def test_nosec_inventory_flags_rule_mismatch(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "mod.py").write_text("x = 1  # nosec B105\n", encoding="utf-8")
    _stage_all(tmp_path)
    inventory = tmp_path / "nosec_inventory.tsv"
    inventory.write_text(
        "# path\tline\tbandit_rule\treason\towner\treview_by\treplacement_plan\n"
        "# ratchet_max_entries: 1\n"
        "mod.py\t1\tB608\treason\t@owner\t2099-01-01\tN/A\n",
        encoding="utf-8",
    )

    failures = check_nosec_inventory.check_nosec_inventory(tmp_path, inventory)

    assert any("nosec rule mismatch" in failure for failure in failures)


def test_nosec_inventory_flags_expired_review_by(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "mod.py").write_text("x = 1  # nosec B608\n", encoding="utf-8")
    _stage_all(tmp_path)
    inventory = tmp_path / "nosec_inventory.tsv"
    expired = (date.today() - timedelta(days=1)).isoformat()
    inventory.write_text(
        "# path\tline\tbandit_rule\treason\towner\treview_by\treplacement_plan\n"
        "# ratchet_max_entries: 1\n"
        f"mod.py\t1\tB608\treason\t@owner\t{expired}\tN/A\n",
        encoding="utf-8",
    )

    failures = check_nosec_inventory.check_nosec_inventory(tmp_path, inventory)

    assert any("expired nosec review" in failure for failure in failures)


def test_nosec_inventory_flags_ratchet_exceeded(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1  # nosec B608\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 1  # nosec B608\n", encoding="utf-8")
    _stage_all(tmp_path)
    inventory = tmp_path / "nosec_inventory.tsv"
    inventory.write_text(
        "# path\tline\tbandit_rule\treason\towner\treview_by\treplacement_plan\n"
        "# ratchet_max_entries: 1\n"
        "a.py\t1\tB608\treason\t@owner\t2099-01-01\tN/A\n"
        "b.py\t1\tB608\treason\t@owner\t2099-01-01\tN/A\n",
        encoding="utf-8",
    )

    failures = check_nosec_inventory.check_nosec_inventory(tmp_path, inventory)

    assert any("nosec ratchet exceeded" in failure for failure in failures)


def test_nosec_inventory_requires_ratchet_header(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _stage_all(tmp_path)
    inventory = tmp_path / "nosec_inventory.tsv"
    inventory.write_text(
        "# path\tline\tbandit_rule\treason\towner\treview_by\treplacement_plan\n", encoding="utf-8"
    )

    failures = check_nosec_inventory.check_nosec_inventory(tmp_path, inventory)

    assert any("ratchet_max_entries" in failure for failure in failures)


def test_nosec_inventory_ignores_prose_mentioning_nosec(tmp_path: Path) -> None:
    """A `#`-comment that merely talks about nosec (no real suppression) must not
    be treated as an unregistered suppression."""
    _init_git_repo(tmp_path)
    (tmp_path / "mod.py").write_text(
        '# instead of a bare "trust me" nosec comment, validate the identifier.\nx = 1\n',
        encoding="utf-8",
    )
    _stage_all(tmp_path)
    inventory = tmp_path / "nosec_inventory.tsv"
    inventory.write_text(
        "# path\tline\tbandit_rule\treason\towner\treview_by\treplacement_plan\n# ratchet_max_entries: 0\n",
        encoding="utf-8",
    )

    failures = check_nosec_inventory.check_nosec_inventory(tmp_path, inventory)

    assert failures == []


def test_update_ratchet_tightens_header_to_current_count(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "mod.py").write_text("x = 1  # nosec B608\n", encoding="utf-8")
    _stage_all(tmp_path)
    inventory = tmp_path / "nosec_inventory.tsv"
    inventory.write_text(
        "# path\tline\tbandit_rule\treason\towner\treview_by\treplacement_plan\n"
        "# ratchet_max_entries: 5\n"
        "mod.py\t1\tB608\treason\t@owner\t2099-01-01\tN/A\n",
        encoding="utf-8",
    )

    new_ceiling = check_nosec_inventory.update_ratchet(inventory)

    assert new_ceiling == 1
    assert "# ratchet_max_entries: 1" in inventory.read_text(encoding="utf-8")


def test_parse_inventory_rejects_malformed_row(tmp_path: Path) -> None:
    inventory = tmp_path / "nosec_inventory.tsv"
    inventory.write_text(
        "# path\tline\tbandit_rule\treason\towner\treview_by\treplacement_plan\n"
        "# ratchet_max_entries: 1\n"
        "mod.py\t1\tB608\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected 7 tab-separated fields"):
        check_nosec_inventory.parse_inventory(inventory)
