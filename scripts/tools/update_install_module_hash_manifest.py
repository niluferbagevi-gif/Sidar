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

PIN_RE = re.compile(
    r'^SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="(?P<commit>[0-9a-fA-F]{40}|unknown)"$', re.MULTILINE
)


def extract_embedded_source_commit(content: str) -> str | None:
    match = PIN_RE.search(content)
    if match is None:
        return None
    return match.group("commit")


def sha256sum_git_show(commit: str, rel_path: str) -> str | None:
    """Return the SHA-256 digest for ``git show <commit>:<rel_path>``.

    This is the Python equivalent of the operator-facing verification command
    ``git show $SOURCE_COMMIT:<path> | sha256sum``. ``None`` means the pinned
    commit or path cannot be read from the local git object database.
    """
    result = subprocess.run(  # nosec B603 B607  # sabit "git" komutu; kullanıcı girdisi shell'e geçmiyor.
        ["git", "-C", str(ROOT), "show", f"{commit}:{rel_path}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


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


def _parse_manifest_lines(payload: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw in payload.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        entries[parts[1]] = parts[0]
    return entries


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


def diff_pinned_commit(target: Path) -> list[tuple[str, str | None, str | None]]:
    """Return manifest entries that do not match the embedded source commit.

    This protects the raw one-file installer path: when ``install_sidar.sh`` is
    downloaded before the repository exists, helper modules are fetched from
    ``SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT`` and verified against the embedded
    manifest. A manifest that matches the working tree but not that pinned
    commit would therefore break installation.
    """
    content = target.read_text(encoding="utf-8")
    commit = extract_embedded_source_commit(content)
    embedded_raw = _extract_embedded_payload(content)
    if embedded_raw is None:
        raise RuntimeError(f"Manifest bloğu bulunamadı: {target}")
    if not commit or commit == "unknown":
        return [("SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT", commit, "40 karakter commit SHA")]
    embedded = _parse_manifest_lines(embedded_raw)
    drift: list[tuple[str, str | None, str | None]] = []
    for path, expected_hash in sorted(embedded.items()):
        pinned_hash = sha256sum_git_show(commit, path)
        if expected_hash != pinned_hash:
            drift.append((path, expected_hash, pinned_hash))
    return drift


def stamp_embedded_source_commit(target: Path, commit: str) -> None:
    content = target.read_text(encoding="utf-8")
    updated, count = PIN_RE.subn(
        f'SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="{commit}"', content, count=1
    )
    if count != 1:
        raise RuntimeError("SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT satırı bulunamadı")
    target.write_text(updated, encoding="utf-8")


def _format_pin_drift_report(target: Path, drift: list[tuple[str, str | None, str | None]]) -> str:
    try:
        rel_target = target.relative_to(ROOT)
    except ValueError:
        rel_target = target

    def short(h: str | None) -> str:
        return (h or "yok").ljust(64)

    commit = extract_embedded_source_commit(target.read_text(encoding="utf-8")) or "yok"
    lines = [
        f"Pin drift tespit edildi: {rel_target} içindeki gömülü modül hash bloğu",
        f"SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT={commit} commitindeki dosyalarla uyumsuz.",
        "Raw tek dosya kurulumunda modüller bu committen indirildiği için kurulum kırılır.",
        "",
        f"Drift satırları ({len(drift)} adet):",
        f"  {'gömülü manifest':64}  {'pinlenen commit':64}  yol",
    ]
    for path, embedded_hash, pinned_hash in drift:
        lines.append(f"  {short(embedded_hash)}  {short(pinned_hash)}  {path}")
    lines.append("")
    lines.append(
        "Düzeltmek için: SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT değerini manifestteki "
        "dosyaları içeren bir commit SHA'sına damgalayın."
    )
    return "\n".join(lines)


def check_target(target: Path) -> bool:
    content = target.read_text(encoding="utf-8")
    payload = build_payload()
    updated = _rewrite(content, payload)
    return updated == content


def _format_drift_report(target: Path, drift: list[tuple[str, str | None, str | None]]) -> str:
    try:
        rel_target = target.relative_to(ROOT)
    except ValueError:
        rel_target = target

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="install_sidar.sh")
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Manifest dosyayla veya pinlenen commit ile eşleşmiyorsa hedefi "
            "değiştirmeden non-zero ile çık."
        ),
    )
    parser.add_argument(
        "--check-pin",
        action="store_true",
        help=(
            "Yalnız gömülü manifest hash'lerinin SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT "
            "ile eşleştiğini doğrula."
        ),
    )
    parser.add_argument(
        "--stamp-commit",
        help=(
            "SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT satırını verilen 40 karakter SHA ile güncelle."
        ),
    )
    args = parser.parse_args()
    target = (ROOT / args.target).resolve()
    if args.stamp_commit:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", args.stamp_commit):
            print("--stamp-commit 40 karakter commit SHA olmalı", file=sys.stderr)
            return 2
        stamp_embedded_source_commit(target, args.stamp_commit.lower())
    if args.check_pin and not args.check:
        pin_drift = diff_pinned_commit(target)
        if not pin_drift:
            return 0
        print(_format_pin_drift_report(target, pin_drift), file=sys.stderr)
        return 1
    if args.check:
        drift = diff_target(target)
        pin_drift = diff_pinned_commit(target)
        if not drift and not pin_drift:
            return 0
        if drift:
            print(_format_drift_report(target, drift), file=sys.stderr)
        if pin_drift:
            print(_format_pin_drift_report(target, pin_drift), file=sys.stderr)
        return 1
    if not args.stamp_commit:
        update_target(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
