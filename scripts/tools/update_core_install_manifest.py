#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import hashlib
import re

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


def main() -> int:
    entries = [f"{digest(rel)}  {rel.as_posix()}" for rel in TARGET_FILES]
    payload = "\n".join(entries) + "\n"
    MANIFEST_FILE.write_text(payload, encoding="utf-8")

    install_text = INSTALL_SCRIPT.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"({re.escape(START)}\n)(.*?)(\n{re.escape(END)})",
        re.DOTALL,
    )
    updated_text, count = pattern.subn(rf"\1{payload.rstrip()}\3", install_text, count=1)
    if count != 1:
        raise RuntimeError("install_sidar.sh içindeki çekirdek manifest heredoc bloğu bulunamadı.")
    INSTALL_SCRIPT.write_text(updated_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
