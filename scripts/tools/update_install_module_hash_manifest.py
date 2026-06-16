#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES_DIR = ROOT / "scripts/install_modules"
START_RE = r"read -r -d '' EMBEDDED_MODULE_HASHES_MANIFEST <<'SIDAR_MODULE_HASHES_EOF' \|\| true"
END_MARKER = "SIDAR_MODULE_HASHES_EOF"


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


def manifest_pattern() -> re.Pattern[str]:
    return re.compile(rf"({START_RE}\n)(.*?)(\n{END_MARKER})", re.DOTALL)


def read_manifest_payload(target: Path) -> str:
    content = target.read_text(encoding="utf-8")
    match = manifest_pattern().search(content)
    if match is None:
        raise RuntimeError(f"Manifest bloğu bulunamadı: {target}")
    return match.group(2).strip("\n")


def update_target(target: Path) -> None:
    content = target.read_text(encoding="utf-8")
    payload = build_payload()
    updated, count = manifest_pattern().subn(lambda m: f"{m.group(1)}{payload}{m.group(3)}", content, count=1)
    if count != 1:
        raise RuntimeError(f"Manifest bloğu bulunamadı: {target}")
    target.write_text(updated, encoding="utf-8")


def check_target(target: Path) -> int:
    current = read_manifest_payload(target)
    expected = build_payload()
    if current == expected:
        print(f"OK: {target.relative_to(ROOT)} modül hash manifesti güncel.")
        return 0
    print(f"Manifest drift tespit edildi: {target.relative_to(ROOT)}")
    current_lines = set(current.splitlines())
    expected_lines = set(expected.splitlines())
    for line in sorted(expected_lines - current_lines):
        print(f"+{line}")
    for line in sorted(current_lines - expected_lines):
        print(f"-{line}")
    print("Düzeltme: ./scripts/sync_install_module_hashes.sh")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="install_sidar.sh")
    parser.add_argument("--check", action="store_true", help="Manifesti değiştirmeden drift kontrolü yapar.")
    args = parser.parse_args()
    target = (ROOT / args.target).resolve()
    if args.check:
        return check_target(target)
    update_target(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
