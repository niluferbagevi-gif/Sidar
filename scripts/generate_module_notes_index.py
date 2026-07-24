"""Generate docs/module-notes/INDEX.md from the tracked repo state.

The index used to be hand-maintained and drifted from reality (stale total
file counts, a `core/rag.py` mapping for a module that is now the `core/rag/`
package, etc.). This script recomputes the summary counters and the
source-to-note mapping from `git ls-files` plus the files actually present
under `docs/module-notes/`, so the index can no longer go stale silently.

Run with `--check` (as a CI gate) to fail when the committed INDEX.md does
not match what this script would generate.

Deliberately not included: a commit SHA. A file that is itself tracked in
git cannot describe "as of commit X" without going stale the moment it is
committed as part of X (the same reason install_sidar.sh pins its module
commit from a *separate*, already-landed commit).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from scripts.version_probe import resolve_pyproject_version

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTES_DIR = REPO_ROOT / "docs/module-notes"
INDEX_PATH = NOTES_DIR / "INDEX.md"

# Note files that do not map 1:1 onto a single still-existing source file:
# package facades documented under their pre-split filename, and meta notes
# that describe the module-notes system itself rather than one source file.
SOURCE_OVERRIDES: dict[str, str | None] = {
    "core/db.py.md": "core/db/",
    "core/rag.py.md": "core/rag/",
    "note.md": ".note",
    "modularization.md": None,
    "install_sidar_modularization.md": None,
    # Docs that moved under docs/ but kept their historical note filename.
    "CLAUDE.md.md": "docs/CLAUDE.md",
    "PROJE_RAPORU.md.md": "docs/PROJE_RAPORU.md",
    "RFC-MultiAgent.md.md": "docs/RFC-MultiAgent.md",
    "SIDAR.md.md": "docs/SIDAR.md",
    "environment.yml.md": "docs/archive/environment.yml",
    # docker/ was renamed to docker_setup/; note tree keeps the old path.
    "docker/grafana/dashboards/sidar-llm-overview.json.md": (
        "docker_setup/grafana/dashboards/sidar-llm-overview.json"
    ),
    "docker/grafana/provisioning/dashboards/dashboards.yml.md": (
        "docker_setup/grafana/provisioning/dashboards/dashboards.yml"
    ),
    "docker/grafana/provisioning/datasources/prometheus.yml.md": (
        "docker_setup/grafana/provisioning/datasources/prometheus.yml"
    ),
    "docker/prometheus/prometheus.yml.md": "docker_setup/prometheus/prometheus.yml",
    # Sources removed entirely; pytest config lives in pyproject.toml now and
    # compiled requirements files are no longer checked in.
    "pytest.ini.md": None,
    "requirements.txt.md": None,
    "requirements-dev.txt.md": None,
}


def _git_ls_files(*patterns: str) -> list[str]:
    return [
        line
        for line in subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "ls-files", *patterns],
            text=True,
        ).splitlines()
        if line
    ]


def source_for_note(relative_note_path: str, tracked_files: set[str]) -> str | None:
    """Return the tracked source path a module-notes file documents, or None."""
    if relative_note_path in SOURCE_OVERRIDES:
        return SOURCE_OVERRIDES[relative_note_path]
    if relative_note_path == "tests.md":
        return "tests/*"
    if not relative_note_path.endswith(".md"):
        return None
    candidate = relative_note_path[: -len(".md")]
    if candidate in tracked_files:
        return candidate
    # Note filenames strip the leading dot from dotfiles (`.gitignore` ->
    # `gitignore.md`, `data/.gitkeep` -> `data/gitkeep.md`); restore it.
    parent, _, basename = candidate.rpartition("/")
    dotted_candidate = f"{parent}/.{basename}" if parent else f".{basename}"
    if dotted_candidate in tracked_files:
        return dotted_candidate
    return None


def collect_note_mapping(tracked_files: set[str]) -> dict[str, str]:
    """Map tracked source path -> note file path, for every note under NOTES_DIR."""
    mapping: dict[str, str] = {}
    for note_path in sorted(NOTES_DIR.rglob("*.md")):
        relative_note_path = note_path.relative_to(NOTES_DIR).as_posix()
        if note_path.resolve() == INDEX_PATH.resolve():
            continue
        source = source_for_note(relative_note_path, tracked_files)
        if source is None:
            continue
        mapping[source] = f"docs/module-notes/{relative_note_path}"
    return mapping


def repo_metrics(tracked_files: list[str]) -> dict[str, int | str]:
    py_files = [f for f in tracked_files if f.endswith(".py")]
    test_files = [
        f for f in py_files if f.startswith("tests/") and Path(f).name.startswith("test_")
    ]
    production_python_files = [f for f in py_files if not f.startswith("tests/")]
    frontend_files = [f for f in tracked_files if f.startswith("web_ui_react/")]
    return {
        "project_version": resolve_pyproject_version(REPO_ROOT / "pyproject.toml"),
        "tracked_file_count": len(tracked_files),
        "production_python_count": len(production_python_files),
        "test_file_count": len(test_files),
        "frontend_file_count": len(frontend_files),
    }


def render_index(metrics: dict[str, int | str], mapping: dict[str, str]) -> str:
    lines = [
        "# Module Notes Index",
        "",
        "Bu dizin proje dosyalarının dokümantasyon notlarını içerir.",
        "",
        "> Bu dosya `scripts/generate_module_notes_index.py` tarafından otomatik üretilir;",
        "> elle düzenlenmemelidir. Güncellemek için betiği yeniden çalıştırın.",
        "",
        f"- **Proje sürümü:** {metrics['project_version']}",
        f"- **Toplam takipli dosya:** {metrics['tracked_file_count']}",
        f"- **Üretim Python dosyası (tests hariç):** {metrics['production_python_count']}",
        f"- **Test dosyası (`test_*.py`):** {metrics['test_file_count']}",
        f"- **Frontend dosyası (`web_ui_react/`):** {metrics['frontend_file_count']}",
        f"- **Ayrı not üretilen kaynak sayısı:** {len(mapping)}",
        "",
        "## Not dosyaları",
    ]
    for source in sorted(mapping):
        lines.append(f"- `{source}` → `{mapping[source]}`")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the committed INDEX.md differs from freshly generated content.",
    )
    args = parser.parse_args(argv)

    tracked_files = _git_ls_files()
    metrics = repo_metrics(tracked_files)
    mapping = collect_note_mapping(set(tracked_files))
    rendered = render_index(metrics, mapping)

    if args.check:
        current = INDEX_PATH.read_text(encoding="utf-8") if INDEX_PATH.exists() else ""
        if current != rendered:
            print(
                "docs/module-notes/INDEX.md is stale. Run "
                "`uv run python scripts/generate_module_notes_index.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"docs/module-notes/INDEX.md is up to date ({metrics['tracked_file_count']} files).")
        return 0

    INDEX_PATH.write_text(rendered, encoding="utf-8")
    try:
        display_path = INDEX_PATH.relative_to(REPO_ROOT)
    except ValueError:
        display_path = INDEX_PATH
    print(f"Wrote {display_path} ({metrics['tracked_file_count']} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
