#!/usr/bin/env python3
"""Cross-check SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT against the embedded manifest.

`update_install_module_hash_manifest.py --check` only guarantees that the
embedded module hash manifest inside install_sidar.sh matches the *working
tree*. It says nothing about whether SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT
(the commit the raw single-file installer downloads scripts/install_modules/*
from at runtime) actually points at a tree with those same file contents.

When a commit touches scripts/install_modules/** without also advancing the
pin, the two drift apart: the manifest reflects the new files, but the pin
still resolves to the old ones. Anyone running the raw modular fallback
(`curl .../main/install_sidar.sh`) then downloads modules from the *old*
pinned commit, hashes them, compares against the *new* embedded manifest, and
install_sidar.sh's own hash-verification step (see fail() in
populate_remote_module_hashes_from_embedded_manifest's caller) aborts the
install. This script closes that gap by fetching the pinned commit's blobs
directly from git and comparing them against the embedded manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_install_module_hash_manifest import (  # noqa: E402
    ROOT,
    _extract_embedded_payload,
    _parse_manifest_lines,
)

PIN_RE = re.compile(
    r'^SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="([0-9a-fA-F]{40}|unknown)"$', re.MULTILINE
)


def extract_pin(content: str) -> str:
    match = PIN_RE.search(content)
    if match is None:
        raise RuntimeError("SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT tanımı bulunamadı")
    return match.group(1)


def _run_git(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True)


def ensure_commit_available(commit: str, remote: str) -> None:
    probe = _run_git(["cat-file", "-e", f"{commit}^{{commit}}"])
    if probe.returncode == 0:
        return
    fetch = _run_git(["fetch", "--depth", "1", remote, commit])
    if fetch.returncode != 0:
        raise RuntimeError(
            f"Pinlenen commit {commit} yerel git geçmişinde yok ve "
            f"'git fetch --depth 1 {remote} {commit}' başarısız oldu:\n"
            f"{fetch.stderr.decode(errors='replace')}"
        )


def blob_at_commit(commit: str, rel_path: str) -> bytes | None:
    result = _run_git(["show", f"{commit}:{rel_path}"])
    if result.returncode != 0:
        return None
    return result.stdout


def diff_pin(target: Path, remote: str) -> tuple[str, list[tuple[str, str, str | None]]]:
    """Return (pin_commit, drift) where drift entries are (path, expected_hash, pin_hash)."""
    content = target.read_text(encoding="utf-8")
    pin = extract_pin(content)
    if pin == "unknown":
        raise RuntimeError(
            'SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="unknown" pinlenmemiş; önce damgalayın.'
        )

    embedded_raw = _extract_embedded_payload(content)
    if embedded_raw is None:
        raise RuntimeError(f"Manifest bloğu bulunamadı: {target}")
    embedded = _parse_manifest_lines(embedded_raw)

    ensure_commit_available(pin, remote)

    drift: list[tuple[str, str, str | None]] = []
    for path, expected_hash in sorted(embedded.items()):
        blob = blob_at_commit(pin, path)
        if blob is None:
            drift.append((path, expected_hash, None))
            continue
        actual_hash = hashlib.sha256(blob).hexdigest()
        if actual_hash != expected_hash:
            drift.append((path, expected_hash, actual_hash))
    return pin, drift


def _format_drift_report(target: Path, pin: str, drift: list[tuple[str, str, str | None]]) -> str:
    rel_target = target.relative_to(ROOT)

    def short(h: str | None) -> str:
        return (h or "commit'te yok").ljust(64)

    lines = [
        f"Pin/manifest drift tespit edildi: {rel_target} içindeki SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT ({pin})",
        "gömülü modül hash manifestiyle uyumsuz. Raw tek dosya kurulum "
        "(curl .../main/install_sidar.sh) bu commit'ten modül indirir; indirilen "
        "içerik gömülü hash'lerle eşleşmeyeceği için kurulum hash doğrulamasında başarısız olur.",
        "",
        f"Drift satırları ({len(drift)} adet):",
        f"  {'gömülü manifest hash':64}  {'pinlenen commit hash':64}  yol",
    ]
    for path, expected_hash, pin_hash in drift:
        lines.append(f"  {short(expected_hash)}  {short(pin_hash)}  {path}")
    lines.append("")
    lines.append(
        "Düzeltmek için SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT'i, "
        "scripts/install_modules ağacı gömülü manifestle eşleşen bir commit'e "
        "(genellikle bu değişikliğin merge edildiği commit'e) ilerletin: "
        "scripts/sync_install_source_commit.sh"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="install_sidar.sh")
    parser.add_argument(
        "--remote", default="origin", help="Pinlenen commit yerelde yoksa fetch edilecek remote"
    )
    args = parser.parse_args()
    target = (ROOT / args.target).resolve()

    try:
        pin, drift = diff_pin(target, args.remote)
    except RuntimeError as exc:
        print(f"Pin doğrulaması yapılamadı: {exc}", file=sys.stderr)
        return 1

    if not drift:
        return 0
    print(_format_drift_report(target, pin, drift), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
