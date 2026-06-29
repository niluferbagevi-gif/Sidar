"""Sidar ürün sürümü için tek doğruluk kaynağı.

Runtime bileşenleri sürümü bu modülden okur. Öncelik paket metadata'sıdır;
editable olmayan kaynak ağaçlarında ise `pyproject.toml` okunur. Böylece
`config.py`, ajan karşılama ekranı ve paket sürümü birbirinden ayrışmaz.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
from pathlib import Path

from scripts.version_probe import resolve_pyproject_version

PACKAGE_NAME = "sidar"
_FALLBACK_VERSION = "0.0.0"
PackageNotFoundError = importlib_metadata.PackageNotFoundError
package_version = importlib_metadata.version


def _read_pyproject_version() -> str:
    pyproject_path = Path(__file__).resolve().parent / "pyproject.toml"
    return resolve_pyproject_version(pyproject_path)


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
