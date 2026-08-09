"""Fail when release-facing version declarations drift from Sidar's canonical version."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import sidar_version
from scripts.version_probe import resolve_pyproject_version

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


def _canonical_version() -> str:
    pyproject_version = resolve_pyproject_version(ROOT / "pyproject.toml")
    runtime_version = sidar_version.resolve_version()
    if pyproject_version != runtime_version:
        raise ValueError(
            "sidar_version.py resolved version does not match pyproject.toml: "
            f"{runtime_version!r} != {pyproject_version!r}"
        )
    if not VERSION_RE.match(pyproject_version):
        raise ValueError(f"Canonical pyproject version is invalid: {pyproject_version!r}")
    return pyproject_version


def _read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _expect(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _check_dockerfile(version: str, errors: list[str]) -> None:
    dockerfile = _read_text("Dockerfile")
    _expect(
        f"ARG SIDAR_VERSION={version}" in dockerfile,
        f"Dockerfile ARG SIDAR_VERSION must default to {version}",
        errors,
    )
    _expect(
        'LABEL version="${SIDAR_VERSION}"' in dockerfile,
        "Dockerfile LABEL version must reference ${SIDAR_VERSION}",
        errors,
    )
    _expect(
        'org.opencontainers.image.version="${SIDAR_VERSION}"' in dockerfile,
        "Dockerfile OCI version label must reference ${SIDAR_VERSION}",
        errors,
    )
    forbidden_literals = {"5.3.1", "5.1.0", "4.3.0"} - {version}
    for literal in sorted(forbidden_literals):
        _expect(
            literal not in dockerfile, f"Dockerfile still contains stale version {literal}", errors
        )


def _check_chart(relative_path: str, version: str, errors: list[str]) -> None:
    text = _read_text(relative_path)
    version_match = re.search(r"^version:\s*([^\n#]+)", text, flags=re.MULTILINE)
    app_version_match = re.search(r"^appVersion:\s*['\"]?([^'\"\n#]+)", text, flags=re.MULTILINE)
    found_version = version_match.group(1).strip().strip("\"'") if version_match else ""
    found_app_version = app_version_match.group(1).strip() if app_version_match else ""
    _expect(
        found_version == version,
        f"{relative_path} version={found_version!r}, expected {version}",
        errors,
    )
    _expect(
        found_app_version == version,
        f"{relative_path} appVersion={found_app_version!r}, expected {version}",
        errors,
    )


def _check_docs(version: str, errors: list[str]) -> None:
    docs = _read_text("docs/CLAUDE.md")
    _expect(
        "sidar_version.py" in docs, "docs/CLAUDE.md must cite sidar_version.py as source", errors
    )
    _expect(f"v{version}" in docs, f"docs/CLAUDE.md must mention current v{version}", errors)
    for stale in ("v4.3.0", "v5.1.0", "v5.3.1"):
        if stale != f"v{version}":
            _expect(stale not in docs, f"docs/CLAUDE.md still contains stale {stale}", errors)


def main() -> int:
    version = _canonical_version()
    errors: list[str] = []
    _check_dockerfile(version, errors)
    _check_chart("helm/sidar/Chart.yaml", version, errors)
    _check_chart("sidar_assets/helm/sidar/Chart.yaml", version, errors)
    _check_docs(version, errors)
    if errors:
        print("Release version consistency check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Release version consistency OK: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
