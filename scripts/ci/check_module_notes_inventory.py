"""Validate that docs/module-notes/INDEX.md stays honest about the repo it describes.

``docs/module-notes/INDEX.md`` is a hand-written map from source files to their
``docs/module-notes/*.md`` notes. Because it is not generated, it silently rots as
files are renamed, removed, or added — and because Sidar's own RAG stack ingests
``docs/``, a stale note is not just inconvenient documentation debt, it is a wrong
answer the system can serve as fact. This script enforces four contracts:

1. Every source path listed in INDEX.md actually exists in the repo.
2. Every note file listed in INDEX.md actually exists on disk.
3. Every ``docs/module-notes/*.md`` file on disk is referenced somewhere in
   INDEX.md (as a source-mapped bullet, or under "Ek notlar" for topical notes
   that don't map to one file) -- an orphan note usually means its source moved
   or was deleted without the note following it.
4. The count of production Python modules with no INDEX.md entry never grows
   beyond a committed ratchet baseline (docs/module-notes/inventory-debt-baseline.json),
   mirroring scripts/ci/check_ruff_debt_baseline.py.

Checks 1-3 are zero-tolerance: any violation fails immediately. Check 4 is a
ratchet: it never blocks the large pre-existing backlog, but it blocks that
backlog from growing, and it must be tightened (via --update) as notes are added.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "docs" / "module-notes" / "INDEX.md"
DEFAULT_BASELINE = ROOT / "docs" / "module-notes" / "inventory-debt-baseline.json"

# Same production surface the coverage gate measures (see
# scripts/test_gates/coverage_helpers.sh's --cov=agent --cov=core --cov=managers
# --cov=plugins --cov=web), plus launcher/ and the handful of root entry-point
# scripts that ship as the CLI/web/upload surface.
PRODUCTION_DIRS = ("agent", "core", "managers", "plugins", "web", "launcher")
PRODUCTION_ROOT_FILES = (
    "main.py",
    "cli.py",
    "config.py",
    "web_server.py",
    "github_upload.py",
    "gui_launcher.py",
)

BULLET_RE = re.compile(r"^- `([^`]+)` → `([^`]+)`", re.MULTILINE)
NOTE_MENTION_RE = re.compile(r"`(docs/module-notes/[^`]+\.md)`")


class InventoryError(ValueError):
    """Raised when INDEX.md itself cannot be parsed into entries."""


def parse_index(index_text: str) -> list[tuple[str, str]]:
    """Return the ``(source, note)`` pairs from INDEX.md's source-mapped bullets."""
    entries = BULLET_RE.findall(index_text)
    if not entries:
        raise InventoryError("INDEX.md içinde hiçbir `kaynak` → `not` satırı bulunamadı")
    return entries


def check_sources_exist(entries: list[tuple[str, str]]) -> list[str]:
    """Return INDEX.md source paths that no longer exist on disk."""
    missing = []
    for source, _note in entries:
        if source == "tests/*":
            continue
        candidate = source.rstrip("/")
        if not (ROOT / candidate).exists() and not (ROOT / source).exists():
            missing.append(source)
    return missing


def check_notes_exist(entries: list[tuple[str, str]]) -> list[str]:
    """Return INDEX.md note paths that do not exist on disk."""
    return [note for _source, note in entries if not (ROOT / note).exists()]


def check_orphan_notes(index_text: str) -> list[str]:
    """Return docs/module-notes/*.md files never mentioned anywhere in INDEX.md."""
    referenced = set(NOTE_MENTION_RE.findall(index_text))
    on_disk = sorted(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "docs" / "module-notes").rglob("*.md")
        if p.name != "INDEX.md"
    )
    return [note for note in on_disk if note not in referenced]


def _documented_sources(entries: list[tuple[str, str]]) -> tuple[set[str], list[str]]:
    """Split INDEX.md sources into exact-file entries and package-dir prefixes."""
    exact: set[str] = set()
    package_prefixes: list[str] = []
    for source, _note in entries:
        if source == "tests/*":
            continue
        if source.endswith("/"):
            package_prefixes.append(source)
        else:
            exact.add(source)
    return exact, package_prefixes


def find_undocumented_production_modules(entries: list[tuple[str, str]]) -> list[str]:
    """Return production .py files covered by neither an exact nor a package entry."""
    exact, package_prefixes = _documented_sources(entries)

    production_files: set[str] = set()
    for directory in PRODUCTION_DIRS:
        for path in (ROOT / directory).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            production_files.add(path.relative_to(ROOT).as_posix())
    for filename in PRODUCTION_ROOT_FILES:
        if (ROOT / filename).exists():
            production_files.add(filename)

    undocumented = [
        path
        for path in production_files
        if path not in exact and not any(path.startswith(prefix) for prefix in package_prefixes)
    ]
    return sorted(undocumented)


def _load_baseline(path: Path) -> tuple[int, bool]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    limit = payload.get("maximum_undocumented_production_modules")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError(
            "maximum_undocumented_production_modules negatif olmayan bir integer olmalıdır"
        )
    require_exact = payload.get("require_exact_baseline")
    if not isinstance(require_exact, bool):
        raise ValueError("require_exact_baseline boolean olmalıdır")
    return limit, require_exact


def _write_baseline(path: Path, count: int) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["maximum_undocumented_production_modules"] = count
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run the module-notes inventory contract checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite the committed ratchet baseline to the current undocumented count and exit.",
    )
    parser.add_argument(
        "--allow-stale-baseline",
        action="store_true",
        help="Do not fail when the undocumented count is lower than the committed baseline.",
    )
    args = parser.parse_args(argv)

    try:
        index_text = args.index.read_text(encoding="utf-8")
        entries = parse_index(index_text)
    except (OSError, InventoryError) as exc:
        print(f"docs/module-notes/INDEX.md okunamadı/parse edilemedi: {exc}", file=sys.stderr)
        return 2

    missing_sources = check_sources_exist(entries)
    missing_notes = check_notes_exist(entries)
    orphan_notes = check_orphan_notes(index_text)
    undocumented = find_undocumented_production_modules(entries)

    hard_failures = False
    if missing_sources:
        hard_failures = True
        print(
            f"INDEX.md {len(missing_sources)} kaynak dosya için var olmayan bir yola işaret "
            "ediyor (taşınmış/silinmiş olabilir):",
            file=sys.stderr,
        )
        for source in missing_sources:
            print(f"  - {source}", file=sys.stderr)

    if missing_notes:
        hard_failures = True
        print(f"INDEX.md {len(missing_notes)} eksik not dosyasına işaret ediyor:", file=sys.stderr)
        for note in missing_notes:
            print(f"  - {note}", file=sys.stderr)

    if orphan_notes:
        hard_failures = True
        print(
            f"{len(orphan_notes)} not dosyası docs/module-notes/ altında var ama INDEX.md "
            "içinde hiç referans edilmiyor (kaynağı taşınmış/silinmiş olabilir):",
            file=sys.stderr,
        )
        for note in orphan_notes:
            print(f"  - {note}", file=sys.stderr)

    if hard_failures:
        print(
            "\nBu üç kontrol sıfır toleranslıdır: INDEX.md'yi gerçek dosya sistemiyle "
            "eşleşecek şekilde güncelleyin (yol düzeltme, not dosyası ekleme/kaldırma).",
            file=sys.stderr,
        )
        return 1

    try:
        limit, require_exact = _load_baseline(args.baseline)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Module-notes envanter baseline geçersiz: {exc}", file=sys.stderr)
        return 2

    count = len(undocumented)
    if args.update:
        _write_baseline(args.baseline, count)
        print(f"Module-notes envanter ratchet baseline güncellendi: {count}")
        return 0

    print(f"Dokümante edilmemiş production modül sayısı: {count} (baseline={limit})")

    if count > limit:
        print(
            f"Dokümante edilmemiş production modül sayısı arttı: {count} > {limit}. "
            "Yeni dosya için docs/module-notes/ altına bir not ekleyip INDEX.md'ye "
            "kaydedin, ya da bilinçli bir borç kabulü ise "
            "`uv run python scripts/ci/check_module_notes_inventory.py --update` ile "
            "baseline'ı inceletin. Örnek dosyalar (en fazla 20):",
            file=sys.stderr,
        )
        for path in undocumented[:20]:
            print(f"  - {path}", file=sys.stderr)
        return 1

    if require_exact and count < limit:
        print(
            f"Module-notes envanter borcu azaldı: {count} < {limit}. Azaltımı kalıcılaştırmak "
            "için `--update` ile baseline'ı düşürün.",
            file=sys.stderr,
        )
        return 1

    if count < limit and not args.allow_stale_baseline:
        print(
            f"Module-notes envanter baseline'ı sıkılaştırılabilir: {count} < {limit}. Çalıştırın: "
            "uv run python scripts/ci/check_module_notes_inventory.py --update",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
