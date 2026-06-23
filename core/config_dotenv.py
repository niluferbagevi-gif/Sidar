"""Dotenv precedence and diagnostics helpers for the Config facade."""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from copy import deepcopy
from pathlib import Path
from typing import Any


def parse_dotenv_source_values(path: Path) -> dict[str, str]:
    """Parse simple dotenv assignments for source attribution without logging values."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def record_dotenv_key_sources(
    *,
    environ: MutableMapping[str, str],
    managed_keys: set[str],
    original_env_values: dict[str, str],
    key_sources: dict[str, dict[str, Any]],
    label: str,
    path: Path,
    override: bool,
    parsed_values: dict[str, str],
    before_values: dict[str, str | None],
) -> None:
    """Track which dotenv file supplied each effective key without storing values."""
    for key in parsed_values:
        if key not in environ:
            continue
        if override or before_values.get(key) is None:
            if key not in managed_keys:
                original_value = before_values.get(key)
                if original_value is not None:
                    original_env_values[key] = original_value
            managed_keys.add(key)
            key_sources[key] = {"label": label, "path": str(path), "override": override}


def reset_dotenv_managed_environment(
    *,
    environ: MutableMapping[str, str],
    managed_keys: set[str],
    original_env_values: dict[str, str],
) -> None:
    """Restore pre-dotenv env values so reloads can observe changed dotenv files."""
    for key in tuple(managed_keys):
        original_value = original_env_values.get(key)
        if original_value is None:
            environ.pop(key, None)
        else:
            environ[key] = original_value
    managed_keys.clear()


def record_dotenv_event(
    *,
    load_events: list[dict[str, Any]],
    missing_file_notices: list[str],
    label: str,
    raw_path: str,
    resolved_path: Path | None,
    loaded: bool,
    override: bool,
    reason: str = "",
) -> None:
    """Record dotenv load attempts so runtime checks can explain env precedence."""
    load_events.append(
        {
            "label": label,
            "raw_path": raw_path,
            "path": str(resolved_path) if resolved_path is not None else "",
            "loaded": loaded,
            "override": override,
            "reason": reason,
        }
    )
    if not loaded and reason == "missing" and resolved_path is not None:
        missing_file_notices.append(f"{label}={resolved_path}")


def clone_dotenv_load_report(load_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a defensive copy of the ordered dotenv load attempts."""
    return deepcopy(load_events)


def clone_dotenv_key_source_report(key_sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return a defensive copy of key-to-source metadata."""
    return deepcopy(key_sources)


def resolve_dotenv_path(raw_path: str, *, base_dir: Path) -> Path:
    """Resolve repo-relative, absolute, or user-home dotenv file paths."""
    dotenv_path = Path(raw_path).expanduser()
    if not dotenv_path.is_absolute():
        dotenv_path = base_dir / dotenv_path
    return dotenv_path


def load_dotenv_if_exists(
    raw_path: str,
    *,
    base_dir: Path,
    environ: MutableMapping[str, str],
    load_events: list[dict[str, Any]],
    missing_file_notices: list[str],
    managed_keys: set[str],
    original_env_values: dict[str, str],
    key_sources: dict[str, dict[str, Any]],
    override: bool,
    label: str,
    record_missing: bool = True,
) -> Path | None:
    """Load a dotenv file when it exists and return the resolved path."""
    cleaned_path = raw_path.strip()
    if not cleaned_path:
        record_dotenv_event(
            load_events=load_events,
            missing_file_notices=missing_file_notices,
            label=label,
            raw_path=raw_path,
            resolved_path=None,
            loaded=False,
            override=override,
            reason="empty_path",
        )
        return None
    dotenv_path = resolve_dotenv_path(cleaned_path, base_dir=base_dir)
    if dotenv_path.exists():
        parsed_values = parse_dotenv_source_values(dotenv_path)
        before_values = {key: environ.get(key) for key in parsed_values}
        from dotenv import load_dotenv as current_load_dotenv

        current_load_dotenv(dotenv_path=dotenv_path, override=override)
        record_dotenv_event(
            load_events=load_events,
            missing_file_notices=missing_file_notices,
            label=label,
            raw_path=raw_path,
            resolved_path=dotenv_path,
            loaded=True,
            override=override,
        )
        record_dotenv_key_sources(
            environ=environ,
            managed_keys=managed_keys,
            original_env_values=original_env_values,
            key_sources=key_sources,
            label=label,
            path=dotenv_path,
            override=override,
            parsed_values=parsed_values,
            before_values=before_values,
        )
        return dotenv_path
    if record_missing:
        record_dotenv_event(
            load_events=load_events,
            missing_file_notices=missing_file_notices,
            label=label,
            raw_path=raw_path,
            resolved_path=dotenv_path,
            loaded=False,
            override=override,
            reason="missing",
        )
    return None


def dotenv_values_for_reload(path: Path) -> dict[str, str]:
    """Read dotenv assignments for reload-time effective env calculation."""
    from dotenv import dotenv_values

    values: dict[str, str] = {}
    for key, value in dotenv_values(path).items():
        if key and value is not None:
            values[key] = str(value)
    return values


def load_dotenv_into_effective_env(
    effective_env: dict[str, str],
    raw_path: str,
    *,
    base_dir: Path,
    load_events: list[dict[str, Any]],
    missing_file_notices: list[str],
    managed_keys: set[str],
    original_env_values: dict[str, str],
    key_sources: dict[str, dict[str, Any]],
    override: bool,
    label: str,
) -> Path | None:
    """Record and merge one dotenv file into an in-memory env without mutating os.environ."""
    cleaned_path = raw_path.strip()
    if not cleaned_path:
        record_dotenv_event(
            load_events=load_events,
            missing_file_notices=missing_file_notices,
            label=label,
            raw_path=raw_path,
            resolved_path=None,
            loaded=False,
            override=override,
            reason="empty_path",
        )
        return None

    dotenv_path = resolve_dotenv_path(cleaned_path, base_dir=base_dir)
    if not dotenv_path.exists():
        record_dotenv_event(
            load_events=load_events,
            missing_file_notices=missing_file_notices,
            label=label,
            raw_path=raw_path,
            resolved_path=dotenv_path,
            loaded=False,
            override=override,
            reason="missing",
        )
        return None

    parsed_values = dotenv_values_for_reload(dotenv_path)
    before_values = {key: effective_env.get(key) for key in parsed_values}
    for key, value in parsed_values.items():
        if override or key not in effective_env:
            effective_env[key] = value

    record_dotenv_event(
        load_events=load_events,
        missing_file_notices=missing_file_notices,
        label=label,
        raw_path=raw_path,
        resolved_path=dotenv_path,
        loaded=True,
        override=override,
    )
    record_dotenv_key_sources(
        environ=effective_env,
        managed_keys=managed_keys,
        original_env_values=original_env_values,
        key_sources=key_sources,
        label=label,
        path=dotenv_path,
        override=override,
        parsed_values=parsed_values,
        before_values=before_values,
    )
    return dotenv_path


def dotenv_reload_baseline_environment(
    *, environ: MutableMapping[str, str], managed_keys: set[str]
) -> dict[str, str]:
    """Return the pre-dotenv baseline for atomic reload without intermediate os.environ pops."""
    effective_env = dict(environ)
    for key in tuple(managed_keys):
        effective_env.pop(key, None)
    return effective_env


def skip_default_dotenv_layers(env: dict[str, str] | None = None) -> bool:
    """Return whether repository-local dotenv layers should be skipped."""
    values = os.environ if env is None else env
    return values.get("SIDAR_SKIP_DEFAULT_DOTENV", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
