from __future__ import annotations

import json
from pathlib import Path


def test_project_report_is_a_small_index_over_topic_sections() -> None:
    index_path = Path("docs/PROJE_RAPORU.md")
    index = index_path.read_text(encoding="utf-8")
    sections = sorted(Path("docs/project-report").glob("*.md"))

    assert index_path.stat().st_size < 10_000
    assert len(sections) == 6
    assert "yeniden monolitik rapora dönüştürülmemelidir" in index
    for section in sections:
        assert section.name in index
        assert section.stat().st_size < 50_000


def test_v52_architecture_is_canonical_and_versioned_reports_are_historical() -> None:
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    report_index = Path("docs/PROJE_RAPORU.md").read_text(encoding="utf-8")
    v50 = Path("docs/SIDAR_v5_0_MIMARI_RAPORU.md").read_text(encoding="utf-8")
    v51 = Path("docs/SIDAR_v5_1_MIMARI_RAPORU.md").read_text(encoding="utf-8")

    assert "Aktif mimari doğruluk kaynağı" in architecture
    assert "v5.2.0" in architecture
    assert "agent/self_heal/orchestrator.py" in architecture
    assert "scripts/autonomous_modules/" in architecture
    assert "web_ui_react/src/lib/api.ts" in architecture
    assert "ARCHITECTURE.md" in report_index
    assert "Tarihsel v5.0 vizyon/faz kaydıdır" in v50
    assert "Tarihsel Faz C–E evrim kaydıdır" in v51


def test_readme_repo_tree_docs_entries_are_nested_under_docs() -> None:
    """README's top-level repo-tree diagram must point at real paths.

    A friend code review of docs/ bloat found `ARCHITECTURE.md`,
    `PROJE_RAPORU.md`, `project-report/`, `AUDIT_REPORT_v5.0.md` and
    `TEKNIK_REFERANS.md` listed as repo-root entries in README.md's tree
    diagram, even though all five live under `docs/` and none exist at
    repo root -- `docs/` itself never even appeared in the tree.
    """
    readme = Path("README.md").read_text(encoding="utf-8")
    tree_start = readme.index("```\nSidar/\n")
    tree_end = readme.index("```", tree_start + 4)
    tree_lines = readme[tree_start:tree_end].splitlines()

    top_level_names = {line.split()[1] for line in tree_lines if line.startswith(("├── ", "└── "))}

    assert "docs/" in top_level_names

    docs_only_entries = (
        "ARCHITECTURE.md",
        "PROJE_RAPORU.md",
        "project-report/",
        "AUDIT_REPORT_v5.0.md",
        "module-notes/",
        "TEKNIK_REFERANS.md",
    )
    for entry in docs_only_entries:
        assert entry not in top_level_names, (
            f"{entry!r} listed as a repo-root entry but actually lives under docs/"
        )
        bare_name = entry.rstrip("/")
        assert (Path("docs") / bare_name).exists()
        assert not Path(bare_name).exists()


def test_main_and_cli_docstrings_cross_reference_the_naming_split() -> None:
    """`main.py`/`cli.py` naming is confusing without an explicit pointer.

    A friend code review flagged that `main.py` is actually the launcher/
    setup wizard while `cli.py` -- whose own docstring says it was
    "previously named main.py" -- is the real agent REPL entry point.
    Both files' module docstrings, and their docs/module-notes/*.md
    companions, must say so explicitly so a reader of either file
    understands the split without outside context.
    """
    main_py = Path("main.py").read_text(encoding="utf-8")
    cli_py = Path("cli.py").read_text(encoding="utf-8")
    main_notes = Path("docs/module-notes/main.py.md").read_text(encoding="utf-8")
    cli_notes = Path("docs/module-notes/cli.py.md").read_text(encoding="utf-8")

    assert "ajan REPL'i değildir" in main_py
    assert "tamamen farklı bir modül" in cli_py
    assert "docs/module-notes/cli.py.md" in main_notes
    assert "docs/module-notes/main.py.md" in cli_notes


def test_project_report_distinguishes_debt_from_future_product_phases() -> None:
    """The report must not hide tracked campaigns behind an absolute zero-debt claim."""
    debt = Path("docs/project-report/04-teknik-borc-ve-yapilandirma.md").read_text(encoding="utf-8")
    roadmap = Path("docs/project-report/05-mimari-evrim-ve-yol-haritasi.md").read_text(
        encoding="utf-8"
    )
    ts_baseline = json.loads(
        Path("web_ui_react/typescript-migration-baseline.json").read_text(encoding="utf-8")
    )

    assert "Açık Kritik Teknik Borç | **0" in debt
    assert "İzlenen Mühendislik Kampanyaları | **Var" in debt
    assert "mutlak “zero debt” iddiası kullanılmıyor" in debt
    assert "TypeScript migrasyonu" in debt
    assert "D100-D107" in debt
    assert f"en fazla {ts_baseline['maximum_untyped_files']} untyped" in debt
    assert f"en az {ts_baseline['minimum_typed_files']} typed" in debt
    final_milestone = ts_baseline["milestones"][-1]
    assert final_milestone["deadline"] in debt
    assert (
        f"{final_milestone['maximum_untyped_files']}/"
        f"{final_milestone['minimum_typed_files']}" in debt
    )
    assert "npm run typecheck:inventory" in debt
    assert "yol haritası kalemleri açık teknik kusur sayılmaz" in roadmap
    assert "Harici graph backend'i" in roadmap
    assert "RLHF/DPO orkestrasyonu" in roadmap
    assert "fail_under = 100" in roadmap
    assert "%90" not in roadmap
