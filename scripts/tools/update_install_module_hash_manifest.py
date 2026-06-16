#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import sys
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


def check_target(target: Path) -> bool:
    content = target.read_text(encoding="utf-8")
    payload = build_payload()
    updated = _rewrite(content, payload)
    return updated == content


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="install_sidar.sh")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Manifest dosyayla eşleşmiyorsa hedefi değiştirmeden non-zero ile çık.",
    )
    args = parser.parse_args()
    target = (ROOT / args.target).resolve()
    if args.check:
        if check_target(target):
            return 0
        print(
            f"Manifest drift tespit edildi: {target.relative_to(ROOT)} içindeki gömülü modül "
            "hash bloğu scripts/install_modules altındaki gerçek dosyalarla uyumsuz. "
            "Düzeltmek için: scripts/sync_install_module_hashes.sh",
            file=sys.stderr,
        )
        return 1
    update_target(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
