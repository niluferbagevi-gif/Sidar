from __future__ import annotations

from pathlib import Path

import pytest

from scripts import generate_module_notes_index as gen


def test_source_for_note_strips_md_suffix_for_plain_files() -> None:
    tracked = {"agent/tooling.py", "README.md"}

    assert gen.source_for_note("agent/tooling.py.md", tracked) == "agent/tooling.py"
    assert gen.source_for_note("README.md.md", tracked) == "README.md"


def test_source_for_note_restores_leading_dot_for_dotfiles() -> None:
    tracked = {".gitignore", "data/.gitkeep"}

    assert gen.source_for_note("gitignore.md", tracked) == ".gitignore"
    assert gen.source_for_note("data/gitkeep.md", tracked) == "data/.gitkeep"


def test_source_for_note_uses_tests_aggregate_and_package_overrides() -> None:
    tracked: set[str] = set()

    assert gen.source_for_note("tests.md", tracked) == "tests/*"
    assert gen.source_for_note("core/db.py.md", tracked) == "core/db/"
    assert gen.source_for_note("core/rag.py.md", tracked) == "core/rag/"
    assert gen.source_for_note("note.md", tracked) == ".note"


def test_source_for_note_returns_none_for_removed_sources() -> None:
    tracked: set[str] = set()

    assert gen.source_for_note("pytest.ini.md", tracked) is None
    assert gen.source_for_note("requirements.txt.md", tracked) is None
    assert gen.source_for_note("modularization.md", tracked) is None


def test_source_for_note_returns_none_when_candidate_is_not_tracked() -> None:
    assert gen.source_for_note("some/deleted_module.py.md", set()) is None


def test_render_index_is_deterministic_and_lists_mapping_sorted() -> None:
    metrics = {
        "source_commit": "deadbeef",
        "project_version": "9.9.9",
        "tracked_file_count": 3,
        "production_python_count": 1,
        "test_file_count": 1,
        "frontend_file_count": 0,
    }
    mapping = {"b.py": "docs/module-notes/b.py.md", "a.py": "docs/module-notes/a.py.md"}

    first = gen.render_index(metrics, mapping)
    second = gen.render_index(metrics, mapping)

    assert first == second
    assert first.index("`a.py`") < first.index("`b.py`")
    assert "deadbeef" in first
    assert "9.9.9" in first
    assert "- **Ayrı not üretilen kaynak sayısı:** 2" in first


def test_repo_metrics_reports_current_project_version() -> None:
    from scripts.version_probe import resolve_pyproject_version

    tracked_files = gen._git_ls_files()

    metrics = gen.repo_metrics(tracked_files)

    assert metrics["tracked_file_count"] == len(tracked_files)
    assert metrics["production_python_count"] > 0
    assert metrics["test_file_count"] > 0
    assert metrics["frontend_file_count"] > 0
    assert metrics["project_version"] == resolve_pyproject_version(gen.REPO_ROOT / "pyproject.toml")


def test_collect_note_mapping_resolves_package_facades_not_stale_single_files() -> None:
    tracked_files = set(gen._git_ls_files())

    mapping = gen.collect_note_mapping(tracked_files)

    # These were the exact stale entries the friend's review flagged: core/rag.py and
    # core/db.py no longer exist as single files, they are packages now.
    assert mapping["core/rag/"].endswith("core/rag.py.md")
    assert mapping["core/db/"].endswith("core/db.py.md")
    assert "core/rag.py" not in mapping
    assert "core/db.py" not in mapping


def test_generated_index_matches_committed_index_check_passes() -> None:
    """Regression guard: INDEX.md must be produced by the generator, not hand-edited."""
    assert gen.main(["--check"]) == 0


def test_check_fails_when_index_is_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stale_index = tmp_path / "INDEX.md"
    stale_index.write_text("stale content\n", encoding="utf-8")
    monkeypatch.setattr(gen, "INDEX_PATH", stale_index)

    assert gen.main(["--check"]) == 1


def test_check_passes_once_regenerated_into_isolated_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_index = tmp_path / "INDEX.md"
    monkeypatch.setattr(gen, "INDEX_PATH", isolated_index)

    assert gen.main([]) == 0
    assert isolated_index.exists()
    assert gen.main(["--check"]) == 0
