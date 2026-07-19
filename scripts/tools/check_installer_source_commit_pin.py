#!/usr/bin/env python3
"""Verify the embedded installer source-commit pin matches its module manifest.

Root cause this guards against: update_install_module_hash_manifest.py keeps
the embedded hash manifest in sync with the *working tree*, but nothing
verified that SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT -- the commit the raw
single-file installer downloads scripts/install_modules/* from when no local
repo exists yet -- is actually the commit those hashes came from. Once a
later commit changes a module without the pin being bumped in lockstep, the
raw installer fallback downloads stale file content that fails hash
verification and the install aborts for anyone who only downloaded
install_sidar.sh on its own.
"""

from __future__ import annotations

import re
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = ROOT / "install_sidar.sh"
COMMIT_RE = re.compile(r'SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="([^"]*)"')
MANIFEST_START_RE = (
    r"read -r -d '' EMBEDDED_MODULE_HASHES_MANIFEST <<'SIDAR_MODULE_HASHES_EOF' \|\| true"
)
MANIFEST_END = "SIDAR_MODULE_HASHES_EOF"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _extract_commit_pin(content: str) -> str:
    match = COMMIT_RE.search(content)
    if match is None:
        raise RuntimeError("SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT bulunamadı")
    return match.group(1)


def _extract_manifest(content: str) -> dict[str, str]:
    pattern = re.compile(rf"{MANIFEST_START_RE}\n(.*?)\n{MANIFEST_END}", re.DOTALL)
    match = pattern.search(content)
    if match is None:
        raise RuntimeError("EMBEDDED_MODULE_HASHES_MANIFEST bloğu bulunamadı")
    entries: dict[str, str] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        entries[parts[1]] = parts[0]
    return entries


def _ensure_commit_available(commit: str) -> bool:
    probe = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True,
    )
    if probe.returncode == 0:
        return True
    fetch = subprocess.run(
        ["git", "-C", str(ROOT), "fetch", "--depth=1", "origin", commit],
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        print(
            f"⚠️  Pinlenen commit {commit} origin'den fetch edilemedi: {fetch.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    probe = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True,
    )
    return probe.returncode == 0


def _hash_at_commit(commit: str, rel_path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:{rel_path}"],
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return sha256(result.stdout).hexdigest()


def main() -> int:
    content = INSTALL_SCRIPT.read_text(encoding="utf-8")
    commit = _extract_commit_pin(content)

    if not _SHA_RE.match(commit):
        print(
            f"ℹ️   SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT bir commit SHA değil ({commit!r}); "
            "runtime GitHub API üzerinden mutable ref çözümlemesine düşecek. "
            "Statik pin doğrulaması atlandı."
        )
        return 0

    manifest = _extract_manifest(content)
    if not manifest:
        print("ℹ️   Gömülü modül hash manifesti boş; pin doğrulaması atlandı.")
        return 0

    if not _ensure_commit_available(commit):
        print(
            f"❌  Pinlenen commit {commit} yerel depoda bulunamadı ve fetch edilemedi; "
            "doğrulama yapılamadı.",
            file=sys.stderr,
        )
        return 1

    drift: list[tuple[str, str, str | None]] = []
    for rel_path, expected_hash in sorted(manifest.items()):
        actual_hash = _hash_at_commit(commit, rel_path)
        if actual_hash != expected_hash:
            drift.append((rel_path, expected_hash, actual_hash))

    if not drift:
        print(
            f"✅  SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT ({commit}) gömülü modül "
            "manifestiyle uyumlu."
        )
        return 0

    print(
        f"❌  SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT ({commit}) gömülü modül manifestiyle "
        f"UYUMSUZ. Tek dosya raw installer fallback'i {commit} commit'inden indirdiğinde "
        "hash doğrulaması başarısız olacak ve kurulum durur.",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    print(f"  {'pinlenen commit hash':64}  {'gömülü manifest hash':64}  yol", file=sys.stderr)
    for rel_path, expected_hash, actual_hash in drift:
        print(
            f"  {(actual_hash or 'YOK').ljust(64)}  {expected_hash.ljust(64)}  {rel_path}",
            file=sys.stderr,
        )
    print("", file=sys.stderr)
    print(
        "Düzeltmek için: install_sidar.sh içindeki SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT "
        "değerini, scripts/install_modules altında bu manifestle eşleşen bir commit'e "
        "(genellikle HEAD) ilerletin.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
