"""Read the coverage.py configuration the repo actually uses.

Sidar keeps its coverage settings in ``pyproject.toml`` (``[tool.coverage.run]`` /
``[tool.coverage.report]``); there is no ``.coveragerc``. The coverage and QA
agents historically read only ``.coveragerc`` and silently saw an empty config
(``fail_under=0``, no ``omit``), so their prompts and plans ignored the real
%100 gate. This helper keeps honoring an explicit INI file when one exists and
otherwise falls back to the sibling ``pyproject.toml``, mirroring coverage.py's
own lookup order for the default ``.coveragerc`` name.
"""

from __future__ import annotations

import configparser
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_COVERAGERC = ".coveragerc"
PYPROJECT_NAME = "pyproject.toml"


def _stringify(value: Any) -> str:
    """Render a TOML value in the string shape ``configparser`` would return."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def _read_ini(path: Path) -> dict[str, dict[str, str]]:
    """Read ``[run]``/``[report]`` (or setup.cfg-style ``[coverage:*]``) sections."""
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    sections: dict[str, dict[str, str]] = {}
    for name in ("run", "report"):
        for section in (name, f"coverage:{name}"):
            if parser.has_section(section):
                sections[name] = dict(parser.items(section))
                break
        else:
            sections[name] = {}
    return sections


def _read_pyproject(path: Path) -> dict[str, dict[str, str]] | None:
    """Return ``[tool.coverage]`` run/report tables, or ``None`` when absent/invalid."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    coverage = data.get("tool", {}).get("coverage")
    if not isinstance(coverage, dict):
        return None
    sections: dict[str, dict[str, str]] = {}
    for name in ("run", "report"):
        table = coverage.get(name, {})
        items = table.items() if isinstance(table, dict) else ()
        sections[name] = {key: _stringify(value) for key, value in items}
    return sections


def read_coverage_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Return ``{"path", "exists", "run", "report"}`` for the coverage configuration.

    Args:
        config_path: An INI file (``.coveragerc``/``setup.cfg``) or a ``.toml``
            file. Empty/``None`` means ``.coveragerc`` in the working directory.
            When the requested file is a missing ``.coveragerc``, the sibling
            ``pyproject.toml`` ``[tool.coverage]`` tables are used instead.

    Returns:
        ``run``/``report`` map option names to strings (lists are newline
        joined, booleans are ``"true"``/``"false"``), matching ``configparser``
        output so callers need not care which file format was read.
    """
    path = Path(str(config_path or "").strip() or DEFAULT_COVERAGERC)
    if path.is_file():
        if path.suffix == ".toml":
            sections = _read_pyproject(path)
            if sections is not None:
                return {"path": str(path), "exists": True, **sections}
        else:
            return {"path": str(path), "exists": True, **_read_ini(path)}
    elif path.name == DEFAULT_COVERAGERC:
        pyproject = path.with_name(PYPROJECT_NAME)
        sections = _read_pyproject(pyproject) if pyproject.is_file() else None
        if sections is not None:
            return {"path": str(pyproject), "exists": True, **sections}
    return {"path": str(path), "exists": False, "run": {}, "report": {}}
