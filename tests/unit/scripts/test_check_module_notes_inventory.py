"""Tests for the docs/module-notes/INDEX.md inventory contract checker."""

from __future__ import annotations

import json

import pytest

from scripts.ci import check_module_notes_inventory as checker


def _make_repo(tmp_path, monkeypatch):
    """Point checker.ROOT at an isolated, empty repo root for the duration of a test."""
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    return tmp_path


def test_parse_index_extracts_source_note_pairs() -> None:
    text = "\n".join(
        [
            "# Module Notes Index",
            "",
            "- `main.py` → `docs/module-notes/main.py.md`",
            "- `core/db/` → `docs/module-notes/core/db.py.md`",
            "- `tests/*` → `docs/module-notes/tests.md`",
        ]
    )

    entries = checker.parse_index(text)

    assert entries == [
        ("main.py", "docs/module-notes/main.py.md"),
        ("core/db/", "docs/module-notes/core/db.py.md"),
        ("tests/*", "docs/module-notes/tests.md"),
    ]


def test_parse_index_rejects_empty_index() -> None:
    with pytest.raises(checker.InventoryError):
        checker.parse_index("# Module Notes Index\n\nNo bullets here.\n")


def test_check_sources_exist_flags_only_missing_paths(tmp_path, monkeypatch) -> None:
    _make_repo(tmp_path, monkeypatch)
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "db").mkdir()

    entries = [
        ("main.py", "docs/module-notes/main.py.md"),
        ("core/db/", "docs/module-notes/core/db.py.md"),
        ("gone.py", "docs/module-notes/gone.py.md"),
        ("tests/*", "docs/module-notes/tests.md"),
    ]

    assert checker.check_sources_exist(entries) == ["gone.py"]


def test_check_notes_exist_flags_only_missing_note_files(tmp_path, monkeypatch) -> None:
    _make_repo(tmp_path, monkeypatch)
    note_dir = tmp_path / "docs" / "module-notes"
    note_dir.mkdir(parents=True)
    (note_dir / "main.py.md").write_text("", encoding="utf-8")

    entries = [
        ("main.py", "docs/module-notes/main.py.md"),
        ("cli.py", "docs/module-notes/cli.py.md"),
    ]

    assert checker.check_notes_exist(entries) == ["docs/module-notes/cli.py.md"]


def test_check_orphan_notes_ignores_index_and_referenced_files(tmp_path, monkeypatch) -> None:
    _make_repo(tmp_path, monkeypatch)
    note_dir = tmp_path / "docs" / "module-notes"
    note_dir.mkdir(parents=True)
    (note_dir / "INDEX.md").write_text("", encoding="utf-8")
    (note_dir / "main.py.md").write_text("", encoding="utf-8")
    (note_dir / "orphan.md").write_text("", encoding="utf-8")

    index_text = (
        "- `main.py` → `docs/module-notes/main.py.md`\n"
        "- topical mention: `docs/module-notes/modularization.md`\n"
    )
    # modularization.md doesn't exist on disk, only main.py.md and orphan.md do.
    assert checker.check_orphan_notes(index_text) == ["docs/module-notes/orphan.md"]


def test_find_undocumented_production_modules_respects_exact_and_package_entries(
    tmp_path, monkeypatch
) -> None:
    _make_repo(tmp_path, monkeypatch)
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "agent" / "documented.py").write_text("", encoding="utf-8")
    (tmp_path / "agent" / "undocumented.py").write_text("", encoding="utf-8")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "rag").mkdir()
    (tmp_path / "core" / "rag" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "core" / "rag" / "facade.py").write_text("", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    pycache = tmp_path / "agent" / "__pycache__"
    pycache.mkdir()
    (pycache / "documented.cpython-311.pyc").write_text("", encoding="utf-8")

    entries = [
        ("agent/documented.py", "docs/module-notes/agent/documented.py.md"),
        ("core/rag/", "docs/module-notes/core/rag.py.md"),
        ("main.py", "docs/module-notes/main.py.md"),
    ]

    undocumented = checker.find_undocumented_production_modules(entries)

    assert undocumented == ["agent/__init__.py", "agent/undocumented.py"]


def _write_baseline(path, *, limit: int, require_exact: bool = False) -> None:
    path.write_text(
        json.dumps(
            {
                "maximum_undocumented_production_modules": limit,
                "require_exact_baseline": require_exact,
                "reduction_targets": (
                    []
                    if limit == 0
                    else [
                        {
                            "due_date": "2099-12-31",
                            "maximum_undocumented_production_modules": 0,
                        }
                    ]
                ),
            }
        ),
        encoding="utf-8",
    )


def _write_minimal_repo(tmp_path) -> None:
    (tmp_path / "docs" / "module-notes").mkdir(parents=True)
    (tmp_path / "docs" / "module-notes" / "main.py.md").write_text("", encoding="utf-8")
    (tmp_path / "agent").mkdir()
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    index_path = tmp_path / "INDEX.md"
    index_path.write_text("- `main.py` → `docs/module-notes/main.py.md`\n", encoding="utf-8")
    return index_path


def test_main_passes_when_undocumented_count_matches_baseline(tmp_path, monkeypatch) -> None:
    _make_repo(tmp_path, monkeypatch)
    index_path = _write_minimal_repo(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path, limit=0)

    assert checker.main(["--index", str(index_path), "--baseline", str(baseline_path)]) == 0


def test_main_fails_on_missing_source(tmp_path, monkeypatch, capsys) -> None:
    _make_repo(tmp_path, monkeypatch)
    index_path = _write_minimal_repo(tmp_path)
    index_path.write_text(
        index_path.read_text(encoding="utf-8") + "- `gone.py` → `docs/module-notes/gone.py.md`\n",
        encoding="utf-8",
    )
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path, limit=0)

    assert checker.main(["--index", str(index_path), "--baseline", str(baseline_path)]) == 1
    assert "gone.py" in capsys.readouterr().err


def test_main_fails_on_orphan_note(tmp_path, monkeypatch, capsys) -> None:
    _make_repo(tmp_path, monkeypatch)
    index_path = _write_minimal_repo(tmp_path)
    (tmp_path / "docs" / "module-notes" / "orphan.md").write_text("", encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path, limit=0)

    assert checker.main(["--index", str(index_path), "--baseline", str(baseline_path)]) == 1
    assert "orphan.md" in capsys.readouterr().err


def test_main_fails_when_undocumented_count_regresses(tmp_path, monkeypatch, capsys) -> None:
    _make_repo(tmp_path, monkeypatch)
    index_path = _write_minimal_repo(tmp_path)
    (tmp_path / "agent" / "new_module.py").write_text("", encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path, limit=0)

    assert checker.main(["--index", str(index_path), "--baseline", str(baseline_path)]) == 1
    err = capsys.readouterr().err
    assert "arttı" in err
    assert "agent/new_module.py" in err


def test_main_fails_on_stale_baseline_unless_allowed(tmp_path, monkeypatch) -> None:
    _make_repo(tmp_path, monkeypatch)
    index_path = _write_minimal_repo(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path, limit=5)

    assert checker.main(["--index", str(index_path), "--baseline", str(baseline_path)]) == 1
    assert (
        checker.main(
            [
                "--index",
                str(index_path),
                "--baseline",
                str(baseline_path),
                "--allow-stale-baseline",
            ]
        )
        == 0
    )


def test_main_update_ratchets_baseline_to_current_count(tmp_path, monkeypatch, capsys) -> None:
    _make_repo(tmp_path, monkeypatch)
    index_path = _write_minimal_repo(tmp_path)
    (tmp_path / "agent" / "new_module.py").write_text("", encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path, limit=2)

    assert (
        checker.main(["--index", str(index_path), "--baseline", str(baseline_path), "--update"])
        == 0
    )

    updated = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert updated["maximum_undocumented_production_modules"] == 1
    assert "güncellendi" in capsys.readouterr().out


def test_main_update_refuses_to_raise_baseline(tmp_path, monkeypatch, capsys) -> None:
    _make_repo(tmp_path, monkeypatch)
    index_path = _write_minimal_repo(tmp_path)
    (tmp_path / "agent" / "new_module.py").write_text("", encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path, limit=0)

    assert (
        checker.main(["--index", str(index_path), "--baseline", str(baseline_path), "--update"])
        == 2
    )
    assert "borcunu yükseltemez" in capsys.readouterr().err


def test_reduction_targets_must_strictly_decrease(tmp_path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "maximum_undocumented_production_modules": 10,
                "reduction_targets": [
                    {
                        "due_date": "2027-01-01",
                        "maximum_undocumented_production_modules": 10,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="kesin azalmalıdır"):
        checker._reduction_targets(baseline_path)


def test_committed_inventory_roadmap_and_registry_note_are_ratchet_protected() -> None:
    baseline = json.loads(checker.DEFAULT_BASELINE.read_text(encoding="utf-8"))
    index = checker.INDEX_PATH.read_text(encoding="utf-8")

    assert baseline["maximum_undocumented_production_modules"] == 177
    assert baseline["require_exact_baseline"] is True
    assert [
        target["maximum_undocumented_production_modules"]
        for target in baseline["reduction_targets"]
    ] == [150, 100, 50, 0]
    assert "`agent/registry.py` → `docs/module-notes/agent/registry.py.md`" in index
    assert (checker.ROOT / "docs/module-notes/agent/registry.py.md").is_file()


def test_main_rejects_invalid_baseline(tmp_path, monkeypatch, capsys) -> None:
    _make_repo(tmp_path, monkeypatch)
    index_path = _write_minimal_repo(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"maximum_undocumented_production_modules": -1}))

    assert checker.main(["--index", str(index_path), "--baseline", str(baseline_path)]) == 2
    assert "geçersiz" in capsys.readouterr().err
