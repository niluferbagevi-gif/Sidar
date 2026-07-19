#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES_DIR = ROOT / "scripts/install_modules"
START_RE = r"read -r -d '' EMBEDDED_MODULE_HASHES_MANIFEST <<'SIDAR_MODULE_HASHES_EOF' \|\| true"
END_MARKER = "SIDAR_MODULE_HASHES_EOF"
SOURCE_COMMIT_RE = re.compile(
    r'^SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="([0-9a-fA-F]{40})"$', re.MULTILINE
)


def iter_modules() -> list[Path]:
    files = sorted(p for p in MODULES_DIR.rglob("*") if p.is_file() and p.suffix in {".sh", ".ps1"})
    return files


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_payload() -> str:
    lines = [f"{digest(p)}  {p.relative_to(ROOT).as_posix()}" for p in iter_modules()]
    return "\n".join(lines)


def _rewrite(content: str, payload: str) -> str:
    pattern = re.compile(rf"({START_RE}\n)(.*?)(\n{END_MARKER})", re.DOTALL)
    updated, count = pattern.subn(lambda m: f"{m.group(1)}{payload}{m.group(3)}", content, count=1)
    if count != 1:
        raise RuntimeError("Manifest bloğu bulunamadı")
    return updated


def update_target(target: Path) -> None:
    content = target.read_text(encoding="utf-8")
    payload = build_payload()
    updated = _rewrite(content, payload)
    target.write_text(updated, encoding="utf-8")


def _extract_embedded_payload(content: str) -> str | None:
    pattern = re.compile(rf"{START_RE}\n(.*?)\n{END_MARKER}", re.DOTALL)
    match = pattern.search(content)
    if match is None:
        return None
    return match.group(1)


def _extract_source_commit(content: str) -> str:
    match = SOURCE_COMMIT_RE.search(content)
    if match is None:
        raise RuntimeError(
            "SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT 40 karakter commit SHA olarak bulunamadı"
        )
    return match.group(1).lower()


def _parse_manifest_lines(payload: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw in payload.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        entries[parts[1]] = parts[0].lower()
    return entries


def _git_blob_sha256(commit: str, repo_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{repo_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


def diff_target(target: Path) -> list[tuple[str, str | None, str | None]]:
    """Return per-path drift entries: (path, embedded_hash, actual_hash).

    ``None`` on either side signals "missing from that manifest". The list is
    sorted by path for deterministic reporting.
    """
    embedded_raw = _extract_embedded_payload(target.read_text(encoding="utf-8"))
    if embedded_raw is None:
        raise RuntimeError(f"Manifest bloğu bulunamadı: {target}")
    embedded = _parse_manifest_lines(embedded_raw)
    actual = _parse_manifest_lines(build_payload())
    drift: list[tuple[str, str | None, str | None]] = []
    for path in sorted(set(embedded) | set(actual)):
        emb = embedded.get(path)
        act = actual.get(path)
        if emb != act:
            drift.append((path, emb, act))
    return drift


def diff_pinned_source_commit(target: Path) -> tuple[str, list[tuple[str, str, str | None]]]:
    """Return module hash drift between embedded manifest and pinned commit."""
    content = target.read_text(encoding="utf-8")
    embedded_raw = _extract_embedded_payload(content)
    if embedded_raw is None:
        raise RuntimeError(f"Manifest bloğu bulunamadı: {target}")
    source_commit = _extract_source_commit(content)
    embedded = _parse_manifest_lines(embedded_raw)
    drift: list[tuple[str, str, str | None]] = []
    for path, embedded_hash in sorted(embedded.items()):
        pinned_hash = _git_blob_sha256(source_commit, path)
        if embedded_hash != pinned_hash:
            drift.append((path, embedded_hash, pinned_hash))
    return source_commit, drift


def check_target(target: Path) -> bool:
    content = target.read_text(encoding="utf-8")
    payload = build_payload()
    updated = _rewrite(content, payload)
    if updated != content:
        return False
    _, pinned_drift = diff_pinned_source_commit(target)
    return not pinned_drift


def _format_drift_report(target: Path, drift: list[tuple[str, str | None, str | None]]) -> str:
    rel_target = target.relative_to(ROOT)

    def short(h: str | None) -> str:
        return (h or "yok").ljust(64)

    lines = [
        f"Manifest drift tespit edildi: {rel_target} içindeki gömülü modül hash bloğu",
        "scripts/install_modules altındaki gerçek dosyalarla uyumsuz.",
        "",
        f"Drift satırları ({len(drift)} adet):",
        f"  {'gömülü manifest':64}  {'gerçek dosya':64}  yol",
    ]
    for path, embedded_hash, actual_hash in drift:
        lines.append(f"  {short(embedded_hash)}  {short(actual_hash)}  {path}")
    lines.append("")
    lines.append("Düzeltmek için: scripts/sync_install_module_hashes.sh")
    return "\n".join(lines)


def _format_pinned_commit_drift_report(
    source_commit: str, drift: list[tuple[str, str, str | None]]
) -> str:
    def short(h: str | None) -> str:
        return (h or "pinlenen commit'te yok").ljust(64)

    lines = [
        "Installer pin drift tespit edildi: SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT",
        f"({source_commit}) içindeki modül içerikleri gömülü hash manifestiyle eşleşmiyor.",
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
    parser.add_argument(
        "--check",
        action="store_true",
        help="Manifest dosyayla veya pinlenen commit ile eşleşmiyorsa hedefi değiştirmeden non-zero ile çık.",
    )
    args = parser.parse_args()
    target = (ROOT / args.target).resolve()
    if args.check:
        drift = diff_target(target)
        if drift:
            print(_format_drift_report(target, drift), file=sys.stderr)
            return 1
        source_commit, pinned_drift = diff_pinned_source_commit(target)
        if pinned_drift:
            print(_format_pinned_commit_drift_report(source_commit, pinned_drift), file=sys.stderr)
            return 1
        return 0
    update_target(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
