#!/usr/bin/env python3
"""Verify the raw installer module pin matches its embedded hash manifest."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMIT_RE = re.compile(r'^SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="([0-9a-fA-F]{40})"$', re.MULTILINE)
START_RE = r"read -r -d '' EMBEDDED_MODULE_HASHES_MANIFEST <<'SIDAR_MODULE_HASHES_EOF' \|\| true"
END_MARKER = "SIDAR_MODULE_HASHES_EOF"


def _read_target(target: Path) -> str:
    return target.read_text(encoding="utf-8")


def extract_pin(content: str) -> str:
    match = COMMIT_RE.search(content)
    if match is None:
        raise RuntimeError("SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT 40 karakter commit SHA olarak bulunamadı")
    return match.group(1).lower()


def parse_manifest(content: str) -> dict[str, str]:
    pattern = re.compile(rf"{START_RE}\n(.*?)\n{END_MARKER}", re.DOTALL)
    match = pattern.search(content)
    if match is None:
        raise RuntimeError("Gömülü modül hash manifest bloğu bulunamadı")
    entries: dict[str, str] = {}
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            entries[parts[1]] = parts[0].lower()
    return entries


def git_blob_sha256(commit: str, repo_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{repo_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


def find_drift(commit: str, manifest: dict[str, str]) -> list[tuple[str, str, str | None]]:
    drift: list[tuple[str, str, str | None]] = []
    for repo_path, embedded_hash in sorted(manifest.items()):
        pinned_hash = git_blob_sha256(commit, repo_path)
        if pinned_hash != embedded_hash:
            drift.append((repo_path, embedded_hash, pinned_hash))
    return drift


def format_drift(commit: str, drift: list[tuple[str, str, str | None]]) -> str:
    def short(value: str | None) -> str:
        return (value or "pinlenen commit'te yok").ljust(64)

    lines = [
        "Installer pin drift tespit edildi: SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT",
        f"({commit}) içindeki modül içerikleri gömülü hash manifestiyle eşleşmiyor.",
        "Raw tek dosya kurulumda indirilen modüller bu pin'den geldiği için kurulum kırılır.",
        "",
        f"Drift satırları ({len(drift)} adet):",
        f"  {'gömülü manifest':64}  {'pinlenen commit':64}  yol",
    ]
    for path, embedded_hash, pinned_hash in drift:
        lines.append(f"  {short(embedded_hash)}  {short(pinned_hash)}  {path}")
    lines.extend(
        [
            "",
            "Düzeltmek için: scripts/sync_install_module_hashes.sh çalıştırın ve",
            "SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT değerini manifestteki modül ağacını içeren",
            "40 karakterlik commit SHA'ya güncelleyin.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="install_sidar.sh")
    args = parser.parse_args()
    target = (ROOT / args.target).resolve()
    content = _read_target(target)
    commit = extract_pin(content)
    manifest = parse_manifest(content)
    drift = find_drift(commit, manifest)
    if drift:
        print(format_drift(commit, drift), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
