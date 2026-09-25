"""Fail when living Markdown docs point at repo files that no longer exist.

Sidar's docs are hand-written and routinely rot when modules move (``core/db.py``
became the ``core/db/`` package, the legacy ``web_ui/`` was removed, flat
``tests/test_*.py`` files moved under ``tests/unit/``...). Because Sidar's own
RAG stack ingests ``docs/``, a dead path is not just untidy, it is a wrong answer
the system can serve as fact. This script enforces two zero-tolerance contracts
over every tracked ``*.md`` file outside the historical record:

1. Every relative Markdown link ``[text](target)`` resolves to an existing file
   or directory (relative to the document; anchors and external URLs ignored).
2. Every backticked path that starts with a tracked top-level directory
   (``core/...``, ``tests/...``, ``docs/...``) exists in the working tree.
   Runtime/build outputs (``artifacts/``, ``web_ui_react/dist``...) are skipped.

Historical documents (CHANGELOG, archives, dated audit reports) intentionally
cite files as they were and are excluded. A living doc that deliberately names a
removed path (e.g. "``core/db.py`` artık yok") is listed in ``ALLOWED_MISSING``
with the file it appears in, so the exemption cannot spread to other docs. An
exemption that no longer matches anything also fails, so the list cannot rot.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Dated/historical records: they describe the repo as it was and must not be
# rewritten to match the current tree.
HISTORICAL_PREFIXES = (
    "CHANGELOG.md",
    "docs/archive/",
    "docs/audits/",
    "docs/AUDIT_REPORT",
    "docs/REFACTOR_PLAN",
    "docs/SIDAR_v5_",
    "docs/PROJE_RAPORU.md",
    "docs/TEST_OPTIMIZATION_PLAN",
    "reports/",
)

# Generated at runtime/build time, so legitimately absent from a clean checkout.
GENERATED_PREFIXES = (
    "artifacts/",
    "data/",
    "logs/",
    "web_ui_react/dist",
    "web_ui_react/node_modules",
    "web_ui_react/coverage",
    "web_ui_react/playwright-report",
)

# Living docs that intentionally name a removed path to explain a migration.
# Keyed by document so the exemption stays local to that document.
ALLOWED_MISSING: dict[str, frozenset[str]] = {
    # Skill directory layout (relative to a SKILL.md), not a repo path.
    "AGENTS.md": frozenset({"assets/templates"}),
    "README.md": frozenset({"core/db.py"}),
    "docs/TEKNIK_REFERANS.md": frozenset({"core/db.py"}),
    "docs/DEPENDENCY_PROFILE_PLAN.md": frozenset({"core/http_client.py"}),
    "docs/module-notes/core/db.py.md": frozenset({"core/db.py"}),
    "docs/module-notes/core/rag.py.md": frozenset({"core/rag.py"}),
    "docs/module-notes/install_sidar_modularization.md": frozenset(
        {"scripts/install_modules/bootstrap.sh"}
    ),
    "docs/module-notes/.github/workflows/migration-cutover-checks.yml.md": frozenset(
        {"tests/test_migration_assets.py"}
    ),
    "docs/module-notes/runbooks/production-cutover-playbook.md.md": frozenset(
        {"tests/test_migration_assets.py"}
    ),
    "docs/module-notes/scripts/install_host_sandbox.sh.md": frozenset(
        {"tests/test_host_sandbox_installer_assets.py"}
    ),
    "docs/module-notes/docker_setup/grafana/dashboards/sidar-llm-overview.json.md": frozenset(
        {"tests/test_grafana_dashboard_provisioning.py"}
    ),
    "docs/module-notes/docker_setup/grafana/provisioning/dashboards/dashboards.yml.md": (
        frozenset({"tests/test_grafana_dashboard_provisioning.py"})
    ),
    "docs/module-notes/docker_setup/grafana/provisioning/datasources/prometheus.yml.md": (
        frozenset({"tests/test_grafana_dashboard_provisioning.py"})
    ),
    "docs/project-report/02-guvenlik-kalite-ve-bagimliliklar.md": frozenset(
        {"core/db.py", "core/rag.py"}
    ),
    "docs/project-report/04-teknik-borc-ve-yapilandirma.md": frozenset({"core/rag.py"}),
}

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
BACKTICK_RE = re.compile(r"`([^`\s]+)`")


def tracked_files(root: Path) -> list[str]:
    """Return the repo-relative paths tracked by git under ``root``."""
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return [path for path in output.split("\0") if path]


def living_docs(files: list[str]) -> list[str]:
    """Return tracked Markdown files that are not part of the historical record."""
    return sorted(
        path for path in files if path.endswith(".md") and not path.startswith(HISTORICAL_PREFIXES)
    )


def top_level_dirs(files: list[str]) -> frozenset[str]:
    """Return the first path segment of every tracked file that lives in a directory."""
    return frozenset(path.split("/", 1)[0] for path in files if "/" in path)


def broken_links(doc: str, text: str) -> list[str]:
    """Return relative Markdown link targets in ``doc`` that do not resolve."""
    base = (ROOT / doc).parent
    missing = []
    for target in LINK_RE.findall(text):
        path = target.split("#", 1)[0]
        if not path or "://" in path or path.startswith(("mailto:", "/")):
            continue
        if not (base / path).exists():
            missing.append(target)
    return missing


def missing_paths(
    doc: str, text: str, top_dirs: frozenset[str], used: set[tuple[str, str]]
) -> list[str]:
    """Return backticked repo paths in ``doc`` that do not exist on disk.

    Exempted paths that are still missing are recorded in ``used`` so stale
    ``ALLOWED_MISSING`` entries can be reported.
    """
    allowed = ALLOWED_MISSING.get(doc, frozenset())
    missing = []
    for raw in BACKTICK_RE.findall(text):
        path = raw.split("::", 1)[0].rstrip("/.,:;")
        head, sep, _rest = path.partition("/")
        if not sep or head not in top_dirs or not re.fullmatch(r"[\w./-]+", path):
            continue
        if path.startswith(GENERATED_PREFIXES) or (ROOT / path).exists():
            continue
        if path in allowed:
            used.add((doc, path))
        else:
            missing.append(path)
    return missing


def find_problems(files: list[str]) -> list[str]:
    """Return one human-readable line per dead link or path across the living docs."""
    top_dirs = top_level_dirs(files)
    used: set[tuple[str, str]] = set()
    problems: list[str] = []
    for doc in living_docs(files):
        text = (ROOT / doc).read_text(encoding="utf-8")
        problems.extend(f"{doc}: kırık bağlantı -> {t}" for t in broken_links(doc, text))
        problems.extend(
            f"{doc}: var olmayan yol -> {p}" for p in missing_paths(doc, text, top_dirs, used)
        )
    problems.extend(
        f"{doc}: ALLOWED_MISSING girdisi artık gereksiz -> {path}"
        for doc, paths in sorted(ALLOWED_MISSING.items())
        for path in sorted(paths)
        if (doc, path) not in used
    )
    return problems


def main(argv: list[str] | None = None) -> int:
    """Run the living-docs link and path checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    try:
        files = tracked_files(ROOT)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"git ls-files çalıştırılamadı: {exc}", file=sys.stderr)
        return 2

    problems = find_problems(files)
    if problems:
        print(
            f"Dokümanlarda {len(problems)} eskimiş referans bulundu "
            "(dosya taşınmış/silinmiş olabilir):",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nReferansı güncel yola çevirin. Taşınma/silinmeyi bilerek anlatan bir cümleyse "
            "yolu scripts/ci/check_doc_links.py içindeki ALLOWED_MISSING'e o doküman için ekleyin.",
            file=sys.stderr,
        )
        return 1

    print(f"Doküman referansları güncel ({len(living_docs(files))} doküman tarandı).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
