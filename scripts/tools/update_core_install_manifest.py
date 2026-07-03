#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET_FILES = [Path("core/memory.py"), Path("core/multimodal.py")]
MANIFEST_FILE = ROOT / ".sidar_manifest.txt"
INSTALL_SCRIPT = ROOT / "install_sidar.sh"

START = "cat <<'SIDAR_INSTALL_MANIFEST_EOF' > \"$manifest_path\""
END = "SIDAR_INSTALL_MANIFEST_EOF"


def digest(rel: Path) -> str:
    h = hashlib.sha256()
    with (ROOT / rel).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_payload() -> str:
    entries = [f"{digest(rel)}  {rel.as_posix()}" for rel in TARGET_FILES]
    return "\n".join(entries) + "\n"


def _parse_manifest_payload(payload: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in payload.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(maxsplit=1)
        if len(parts) == 2:
            entries[parts[1]] = parts[0]
    return entries


def _describe_entry_drift(label: str, actual_payload: str, expected_payload: str) -> list[str]:
    actual_entries = _parse_manifest_payload(actual_payload)
    expected_entries = _parse_manifest_payload(expected_payload)
    details: list[str] = []

    for rel in [target.as_posix() for target in TARGET_FILES]:
        expected_hash = expected_entries.get(rel, "<eksik>")
        actual_hash = actual_entries.get(rel, "<eksik>")
        if actual_hash != expected_hash:
            details.append(f"- {label}: {rel} beklenen={expected_hash} mevcut={actual_hash}")
    return details


def _rewrite_install_script(install_text: str, payload: str) -> str:
    pattern = re.compile(
        rf"({re.escape(START)}\n)(.*?)(\n{re.escape(END)})",
        re.DOTALL,
    )
    body = payload.rstrip()
    updated_text, count = pattern.subn(
        lambda m: f"{m.group(1)}{body}{m.group(3)}", install_text, count=1
    )
    if count != 1:
        raise RuntimeError("install_sidar.sh içindeki çekirdek manifest heredoc bloğu bulunamadı.")
    return updated_text


def _extract_install_manifest_payload(install_text: str) -> str:
    pattern = re.compile(
        rf"{re.escape(START)}\n(.*?)\n{re.escape(END)}",
        re.DOTALL,
    )
    match = pattern.search(install_text)
    if not match:
        return ""
    return f"{match.group(1).rstrip()}\n"


def _check() -> int:
    payload = _expected_payload()
    actual_manifest = MANIFEST_FILE.read_text(encoding="utf-8") if MANIFEST_FILE.exists() else ""
    install_text = INSTALL_SCRIPT.read_text(encoding="utf-8")
    rewritten = _rewrite_install_script(install_text, payload)

    drift = []
    if actual_manifest != payload:
        drift.append(".sidar_manifest.txt")
    if rewritten != install_text:
        drift.append("install_sidar.sh (SIDAR_INSTALL_MANIFEST_EOF heredoc)")
    if drift:
        joined = ", ".join(drift)
        print(
            f"Çekirdek install manifest drift tespit edildi: {joined}. "
            "Düzeltmek için: scripts/sync_install_manifest.sh",
            file=sys.stderr,
        )
        install_payload = _extract_install_manifest_payload(install_text)
        details = [
            *_describe_entry_drift(".sidar_manifest.txt", actual_manifest, payload),
            *_describe_entry_drift("install_sidar.sh heredoc", install_payload, payload),
        ]
        if details:
            print("Uyumsuz çekirdek manifest girdileri:", file=sys.stderr)
            for detail in details:
                print(detail, file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Manifest dosyalarıyla eşleşmiyorsa hedefleri değiştirmeden non-zero ile çık.",
    )
    args = parser.parse_args()

    if args.check:
        return _check()

    payload = _expected_payload()
    MANIFEST_FILE.write_text(payload, encoding="utf-8")
    install_text = INSTALL_SCRIPT.read_text(encoding="utf-8")
    updated_text = _rewrite_install_script(install_text, payload)
    INSTALL_SCRIPT.write_text(updated_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
