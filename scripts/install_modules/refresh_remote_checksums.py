#!/usr/bin/env python3
"""Refresh reviewed SHA-256 pins for Sidar remote installer scripts."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from core.utils.trusted_urlopen import urlopen_trusted_request


@dataclass(frozen=True)
class RemoteScriptPin:
    """A remote installer script whose SHA-256 is pinned in the checksum env file."""

    env_var: str
    url: str
    label: str


TOOLCHAIN_FILE = Path(__file__).resolve().parents[1] / "toolchain.env"


def read_toolchain_uv_version(path: Path = TOOLCHAIN_FILE) -> str:
    """Return the pinned ``UV_VERSION`` from ``scripts/toolchain.env``.

    Raises:
        ValueError: If ``UV_VERSION`` is not declared exactly once.
    """
    matches = re.findall(r"^UV_VERSION=(\S+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"UV_VERSION must be declared exactly once in {path}")
    return matches[0]


# The uv installer is pinned to the immutable GitHub release asset for the
# toolchain version: https://astral.sh/uv/install.sh always serves the latest
# release, so its checksum pin went stale whenever upstream shipped a new uv.
UV_INSTALLER_URL = (
    "https://github.com/astral-sh/uv/releases/download/"
    f"{read_toolchain_uv_version()}/uv-installer.sh"
)

REMOTE_SCRIPT_PINS = (
    RemoteScriptPin("OLLAMA_INSTALL_SHA256", "https://ollama.com/install.sh", "Ollama installer"),
    RemoteScriptPin("UV_INSTALL_SHA256", UV_INSTALLER_URL, "uv installer"),
    RemoteScriptPin("VOLTA_INSTALL_SHA256", "https://get.volta.sh", "Volta installer"),
    RemoteScriptPin(
        "NVM_INSTALL_SHA256",
        "https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh",
        "NVM installer",
    ),
)


def fetch_remote_bytes(url: str) -> bytes:
    """Download a remote installer script without cache."""
    request = urllib.request.Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "Sidar remote checksum refresh/1.0",
        },
    )
    with urlopen_trusted_request(request, timeout=60) as response:
        return response.read()


def replace_pin(content: str, env_var: str, sha256: str) -> str:
    """Replace the pinned SHA-256 assignment for ``env_var``.

    Raises:
        ValueError: If the assignment is not found exactly once.
    """
    pattern = re.compile(rf'^: "\$\{{{re.escape(env_var)}:=.*\}}"$', re.MULTILINE)
    replacement = f': "${{{env_var}:={sha256}}}"'
    updated, count = pattern.subn(replacement, content)
    if count != 1:
        raise ValueError(f"{env_var} assignment not found exactly once")
    return updated


def build_pull_request_body(pins: dict[str, str]) -> str:
    """Build a suggested pull request body listing the refreshed pins."""
    lines = [
        "## Summary",
        "- Refreshed reviewed remote installer SHA-256 pins for Sidar install bootstrap.",
        "",
        "## Refreshed pins",
    ]
    for pin in REMOTE_SCRIPT_PINS:
        lines.append(f"- `{pin.env_var}` (`{pin.url}`): `{pins[pin.env_var]}`")
    lines.extend(
        [
            "",
            "## Validation",
            "- `python scripts/install_modules/refresh_remote_checksums.py --check`",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    """Refresh the pinned checksums, or with ``--check`` verify they are set.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file", type=Path, default=Path("scripts/install_modules/remote_checksums.env")
    )
    parser.add_argument(
        "--check", action="store_true", help="verify that all managed pins are non-empty"
    )
    parser.add_argument("--pr-body", type=Path, help="write a suggested pull request body")
    args = parser.parse_args()

    content = args.file.read_text(encoding="utf-8")
    pins: dict[str, str] = {}
    for pin in REMOTE_SCRIPT_PINS:
        if args.check:
            match = re.search(
                rf'^: "\$\{{{re.escape(pin.env_var)}:=([0-9a-f]{{64}})\}}"$', content, re.MULTILINE
            )
            if not match:
                print(f"{pin.env_var} is not pinned with a 64-character SHA-256", file=sys.stderr)
                return 1
            pins[pin.env_var] = match.group(1)
            continue
        payload = fetch_remote_bytes(pin.url)
        pins[pin.env_var] = hashlib.sha256(payload).hexdigest()
        print(f"{pin.env_var}={pins[pin.env_var]}  # {pin.label} ({pin.url})")
        content = replace_pin(content, pin.env_var, pins[pin.env_var])

    if not args.check:
        args.file.write_text(content, encoding="utf-8")
    if args.pr_body:
        args.pr_body.write_text(build_pull_request_body(pins), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
