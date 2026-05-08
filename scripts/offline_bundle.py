"""Create and verify Sidar air-gapped installation manifests.

Expected bundle layout::

  offline_packages/
    manifest.json
    wheels/*.whl
    npm/cache/**
    ollama/models/**
    system/*.deb
    uv/install.sh

The manifest stores relative file paths and SHA256 digests so the installer can
fail closed before using untrusted offline artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
DEFAULT_SECTIONS = ("wheels", "npm", "ollama", "system", "uv")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_bundle_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for section in DEFAULT_SECTIONS:
        section_root = root / section
        if not section_root.exists():
            continue
        files.extend(path for path in section_root.rglob("*") if path.is_file())
    return sorted(files)


def build_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    files = []
    for path in iter_bundle_files(root):
        rel = path.relative_to(root).as_posix()
        files.append({"path": rel, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return {"schema_version": 1, "files": files}


def verify_manifest(root: Path) -> list[str]:
    root = root.resolve()
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"missing manifest: {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"invalid manifest JSON: {exc}"]

    errors: list[str] = []
    entries = manifest.get("files")
    if not isinstance(entries, list):
        return ["manifest.files must be a list"]
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("manifest entry must be an object")
            continue
        rel = str(entry.get("path", "")).strip()
        expected = str(entry.get("sha256", "")).strip().lower()
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            errors.append(f"unsafe path in manifest: {rel!r}")
            continue
        if len(expected) != 64:
            errors.append(f"invalid sha256 for {rel}: {expected!r}")
            continue
        path = root / rel
        if not path.is_file():
            errors.append(f"missing file: {rel}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            errors.append(f"sha256 mismatch for {rel}: expected={expected} actual={actual}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Build/verify Sidar offline bundle manifest")
    parser.add_argument("command", choices=("create", "verify"))
    parser.add_argument("bundle_dir", nargs="?", default="offline_packages")
    args = parser.parse_args()

    root = Path(args.bundle_dir)
    if args.command == "create":
        manifest = build_manifest(root)
        root.mkdir(parents=True, exist_ok=True)
        (root / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {root / MANIFEST_NAME} ({len(manifest['files'])} files)")
        return 0

    errors = verify_manifest(root)
    if errors:
        print("offline manifest verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"offline manifest verified: {root / MANIFEST_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
