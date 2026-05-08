"""Resource helpers for package-safe Sidar asset lookup.

Runtime code should resolve static files through this module instead of assuming
that the repository layout is present next to the Python modules. The helpers use
``importlib.resources.files('sidar_assets')`` for wheel/container installs and
fall back to repository paths during local development.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Final

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_ASSET_PACKAGE: Final = "sidar_assets"

_FALLBACKS: Final[dict[str, tuple[Path, ...]]] = {
    "web_ui_react/dist": (
        _REPO_ROOT / "web_ui_react" / "dist",
        _REPO_ROOT / "web_ui_react",
    ),
    "web_ui": (_REPO_ROOT / "web_ui",),
    "helm/sidar": (_REPO_ROOT / "helm" / "sidar",),
    "migrations": (_REPO_ROOT / "migrations",),
    "alembic.ini": (_REPO_ROOT / "alembic.ini",),
    "docker_setup": (_REPO_ROOT / "docker_setup",),
}


def _resource_path(relative_path: str) -> Path | None:
    traversable = resources.files(_ASSET_PACKAGE).joinpath(relative_path)
    if not (traversable.is_file() or traversable.is_dir()):
        return None
    try:
        return Path(str(traversable))
    except TypeError:
        return None


def asset_path(relative_path: str, *, require_exists: bool = False) -> Path:
    """Return the best filesystem path for a Sidar packaged asset.

    ``relative_path`` is relative to the ``sidar_assets`` package. If the asset is
    not bundled in the current environment, a repository-layout fallback is used
    when known.
    """

    normalized = relative_path.strip().strip("/")
    packaged = _resource_path(normalized)
    if packaged is not None and packaged.exists():
        return packaged

    fallback_candidates = _FALLBACKS.get(normalized, (_REPO_ROOT / normalized,))
    fallback = next((candidate for candidate in fallback_candidates if candidate.exists()), fallback_candidates[0])
    if require_exists and not fallback.exists():
        raise FileNotFoundError(f"Sidar asset not found: {normalized} (fallback={fallback})")
    return fallback


def web_dist_path() -> Path:
    return asset_path("web_ui_react/dist")


def helm_chart_path() -> Path:
    return asset_path("helm/sidar", require_exists=True)


def migrations_path() -> Path:
    return asset_path("migrations", require_exists=True)


def alembic_ini_path() -> Path:
    return asset_path("alembic.ini", require_exists=True)
