"""Sidar ürün sürümü için tek doğruluk kaynağı.

Runtime bileşenleri sürümü bu modülden okur. Öncelik paket metadata'sıdır;
editable olmayan kaynak ağaçlarında ise `pyproject.toml` okunur. Böylece
`config.py`, ajan karşılama ekranı ve paket sürümü birbirinden ayrışmaz.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import version as package_version
from pathlib import Path

PACKAGE_NAME = "sidar"
_FALLBACK_VERSION = "0.0.0"


def _read_pyproject_version() -> str:
    pyproject_path = Path(__file__).resolve().parent / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as file_obj:
            project = tomllib.load(file_obj).get("project", {})
    except (OSError, tomllib.TOMLDecodeError):
        return _FALLBACK_VERSION
    raw_version = str(project.get("version", "")).strip()
    return raw_version or _FALLBACK_VERSION


def resolve_version() -> str:
    """Paket metadata'sından, yoksa `pyproject.toml` dosyasından ürün sürümünü çöz."""

    try:
        resolved = package_version(PACKAGE_NAME).strip()
    except Exception:
        resolved = ""
    return resolved or _read_pyproject_version()


PRODUCT_VERSION = resolve_version()
__version__ = PRODUCT_VERSION

__all__ = ["PACKAGE_NAME", "PRODUCT_VERSION", "__version__", "resolve_version"]
