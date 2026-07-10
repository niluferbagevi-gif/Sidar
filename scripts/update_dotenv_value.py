"""Atomically update a single key in a dotenv-style file.

The new value is read from stdin so long secrets never become process argv.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_MAX_VALUE_BYTES = 256 * 1024


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path, help="Dotenv file to update")
    parser.add_argument("--key", required=True, help="Dotenv key to update")
    parser.add_argument(
        "--max-value-bytes",
        type=int,
        default=DEFAULT_MAX_VALUE_BYTES,
        help="Maximum accepted stdin value size",
    )
    return parser.parse_args()


def _read_value(max_value_bytes: int) -> str:
    raw = sys.stdin.buffer.read(max_value_bytes + 1)
    if len(raw) > max_value_bytes:
        raise ValueError(f"value exceeds {max_value_bytes} byte limit")
    if b"\x00" in raw:
        raise ValueError("value must not contain NUL bytes")
    value = raw.decode("utf-8")
    value = value.rstrip("\r\n")
    if "\n" in value or "\r" in value:
        raise ValueError("value must be a single line")
    if not value:
        raise ValueError("value must not be empty")
    return value


def _replace_or_append(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    replacement = f"{prefix}{value}\n"
    updated: list[str] = []
    replaced = False
    for line in lines:
        if not replaced and line.startswith(prefix):
            updated.append(replacement)
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and not updated[-1].endswith("\n"):
            updated[-1] += "\n"
        updated.append(replacement)
    return updated


def update_dotenv_value(path: Path, key: str, value: str) -> None:
    """Update ``key`` in ``path`` using a same-directory atomic replace."""

    if not KEY_RE.fullmatch(key):
        raise ValueError(f"invalid dotenv key: {key!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        mode = 0o600
        lines = []

    updated = _replace_or_append(lines, key, value)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode or 0o600)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        finally:
            raise


def main() -> int:
    args = _parse_args()
    try:
        value = _read_value(args.max_value_bytes)
        update_dotenv_value(args.file, args.key, value)
    except Exception as exc:  # noqa: BLE001 - CLI boundary prints actionable error
        print(f"update_dotenv_value: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
