"""Runtime path inference helpers for the Config facade."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimePathSettings:
    """Resolved runtime path defaults derived from the repository base directory."""

    base_dir: Path
    temp_dir: Path
    logs_dir: Path
    data_dir: Path
    memory_file: Path
    required_dirs: list[Path]
    rag_dir: Path


def _resolve_base_relative_path(base_dir: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    return base_dir / candidate


def load_runtime_path_settings(
    *,
    base_dir: Path,
    environ: Mapping[str, str] | None = None,
) -> RuntimePathSettings:
    """Resolve Config runtime paths outside the large Config class body."""

    env = os.environ if environ is None else environ
    temp_dir = base_dir / "temp"
    logs_dir = base_dir / "logs"
    data_dir = base_dir / "data"
    return RuntimePathSettings(
        base_dir=base_dir,
        temp_dir=temp_dir,
        logs_dir=logs_dir,
        data_dir=data_dir,
        memory_file=data_dir / "memory.json",
        required_dirs=[temp_dir, logs_dir, data_dir],
        rag_dir=_resolve_base_relative_path(base_dir, env.get("RAG_DIR", "data/rag")),
    )


def apply_reload_runtime_paths(
    config_cls: Any, *, base_dir: Path, environ: Mapping[str, str] | None = None
) -> None:
    """Apply reload-time path overrides while preserving Config's legacy attributes."""

    paths = load_runtime_path_settings(base_dir=base_dir, environ=environ)
    config_cls.BASE_DIR = paths.base_dir
    config_cls.TEMP_DIR = paths.temp_dir
    config_cls.LOGS_DIR = paths.logs_dir
    config_cls.DATA_DIR = paths.data_dir
    config_cls.MEMORY_FILE = paths.memory_file
    config_cls.REQUIRED_DIRS = paths.required_dirs
    config_cls.RAG_DIR = paths.rag_dir
