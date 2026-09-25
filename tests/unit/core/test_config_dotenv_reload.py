"""Unit tests for core.config_dotenv_reload (dotenv chain status + reload)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core import config_dotenv, config_dotenv_reload

_LOGGER = logging.getLogger("test.config_dotenv_reload")


def _log_status(
    load_events: list[dict[str, Any]],
    *,
    notices: list[str] | None = None,
    key_sources: dict[str, dict[str, Any]] | None = None,
    last_signature: config_dotenv_reload.ChainSignature | None = None,
    missing_keys: list[str] | None = None,
    first_load_calls: list[tuple[Any, ...]] | None = None,
) -> config_dotenv_reload.ChainSignature | None:
    first_calls = first_load_calls if first_load_calls is not None else []
    return config_dotenv_reload.log_dotenv_load_status(
        load_events=load_events,
        missing_file_notices=notices if notices is not None else [],
        key_sources=key_sources or {},
        last_chain_signature=last_signature,
        missing_keys=missing_keys,
        logger=_LOGGER,
        log_first_load_info=lambda *args: first_calls.append(args),
    )


def test_changed_chain_is_logged_via_first_load_info_and_returned() -> None:
    first_calls: list[tuple[Any, ...]] = []
    events = [
        {"label": "base", "path": "/repo/.env", "loaded": True},
        {"label": "advanced", "path": "/repo/.env.advanced", "loaded": False, "reason": "skip"},
    ]

    signature = _log_status(events, first_load_calls=first_calls)

    assert signature == (("base", "/repo/.env"),)
    assert first_calls == [("Runtime env yükleme zinciri: %s", "base=/repo/.env")]


def test_unchanged_chain_is_logged_at_debug_only(caplog) -> None:
    first_calls: list[tuple[Any, ...]] = []
    events = [{"label": "base", "path": "/repo/.env", "loaded": True}]

    with caplog.at_level(logging.DEBUG, logger=_LOGGER.name):
        signature = _log_status(
            events, last_signature=(("base", "/repo/.env"),), first_load_calls=first_calls
        )

    assert signature == (("base", "/repo/.env"),)
    assert first_calls == []
    assert "Runtime env yükleme zinciri: base=/repo/.env" in caplog.text


def test_no_loaded_files_warns_and_keeps_previous_signature(caplog) -> None:
    previous = (("base", "/old/.env"),)

    with caplog.at_level(logging.WARNING, logger=_LOGGER.name):
        signature = _log_status([], last_signature=previous)

    assert signature is previous
    assert "Hiçbir dotenv dosyası yüklenmedi" in caplog.text


def test_missing_files_and_notices_are_merged_once_and_notices_cleared(caplog) -> None:
    events = [
        {"label": "base", "path": "/repo/.env", "loaded": True},
        {"label": "advanced", "path": "/repo/.env.advanced", "loaded": False, "reason": "missing"},
        {"label": "explicit", "path": "", "loaded": False, "reason": "missing"},
    ]
    notices = ["advanced=/repo/.env.advanced", "secret=~/.sidar_keys.env"]

    with caplog.at_level(logging.INFO, logger=_LOGGER.name):
        _log_status(events, notices=notices)

    assert notices == []
    assert (
        "Opsiyonel dotenv dosyaları bulunamadı: advanced=/repo/.env.advanced, "
        "secret=~/.sidar_keys.env"
    ) in caplog.text


def test_key_sources_and_missing_keys_are_reported(caplog) -> None:
    key_sources = {
        "B_KEY": {"label": "advanced", "path": "/repo/.env.advanced"},
        "A_KEY": {"label": "base", "path": "/repo/.env"},
    }

    with caplog.at_level(logging.DEBUG, logger=_LOGGER.name):
        _log_status(
            [{"label": "base", "path": "/repo/.env", "loaded": True}],
            key_sources=key_sources,
            missing_keys=["JWT_SECRET_KEY", "API_KEY"],
        )

    assert (
        "Runtime env anahtar kaynakları: A_KEY->base=/repo/.env, "
        "B_KEY->advanced=/repo/.env.advanced"
    ) in caplog.text
    assert "Kritik ortam anahtarları çözülemedi: JWT_SECRET_KEY, API_KEY." in caplog.text


def _plan(tmp_path: Path, *, skip_default_layers: bool = False) -> config_dotenv.DotenvReloadPlan:
    return config_dotenv.DotenvReloadPlan(
        base_path=tmp_path / ".env",
        advanced_path=tmp_path / ".env.advanced",
        explicit_path="explicit.env",
        sidar_keys_file="~/keys.env",
        skip_default_layers=skip_default_layers,
    )


def _reload(
    tmp_path: Path,
    environ: dict[str, str],
    *,
    profile: str | None,
    plan: config_dotenv.DotenvReloadPlan,
    layers: dict[str, dict[str, str]],
    managed_keys: set[str],
    loaded_labels: list[str],
) -> dict[str, Any]:
    load_events: list[dict[str, Any]] = [{"label": "stale"}]
    key_sources: dict[str, dict[str, Any]] = {"OLD": {"label": "base", "path": "x"}}
    seen: dict[str, Any] = {}

    def build_plan(env: dict[str, str], *, profile: str | None) -> config_dotenv.DotenvReloadPlan:
        seen["plan_env"] = dict(env)
        seen["plan_profile"] = profile
        return plan

    def baseline(**kwargs: Any) -> dict[str, str]:
        seen["baseline_kwargs"] = kwargs
        return {key: value for key, value in environ.items() if key not in kwargs["managed_keys"]}

    def load_into(
        effective_env: dict[str, str], raw_path: str, *, override: bool, label: str
    ) -> Path | None:
        loaded_labels.append(label)
        for key, value in layers.get(label, {}).items():
            if override or key not in effective_env:
                effective_env[key] = value
                managed_keys.add(key)
        return None

    config_dotenv_reload.reload_dotenv_chain(
        profile=profile,
        environ=environ,
        base_dir=tmp_path,
        managed_keys=managed_keys,
        load_events=load_events,
        key_sources=key_sources,
        build_dotenv_reload_plan=build_plan,
        dotenv_reload_baseline_environment=baseline,
        load_dotenv_into_effective_env=load_into,
    )
    seen["load_events"] = load_events
    seen["key_sources"] = key_sources
    return seen


def test_reload_applies_full_chain_with_profile_and_drops_removed_keys(tmp_path) -> None:
    environ = {"KEEP": "process", "REMOVED": "old-dotenv", "SIDAR_ENV": ""}
    managed_keys = {"REMOVED"}
    loaded_labels: list[str] = []

    seen = _reload(
        tmp_path,
        environ,
        profile="Staging",
        plan=_plan(tmp_path),
        layers={
            "base": {"FROM_BASE": "1", "KEEP": "dotenv-loses"},
            "environment:staging": {"FROM_PROFILE": "1"},
            "secret:SIDAR_KEYS_FILE": {"HF_HOME": ""},
        },
        managed_keys=managed_keys,
        loaded_labels=loaded_labels,
    )

    assert loaded_labels == [
        "base",
        "advanced",
        "environment:staging",
        "explicit:DOTENV_FILE",
        "secret:SIDAR_KEYS_FILE",
    ]
    assert seen["plan_profile"] == "Staging"
    assert seen["plan_env"]["REMOVED"] == "old-dotenv"
    assert seen["baseline_kwargs"]["managed_keys"] == {"REMOVED"}
    assert seen["baseline_kwargs"]["key_sources"] == {"OLD": {"label": "base", "path": "x"}}
    assert seen["load_events"] == []
    assert seen["key_sources"] == {}
    assert "REMOVED" not in environ
    assert environ["KEEP"] == "process"
    assert environ["FROM_BASE"] == "1"
    assert environ["FROM_PROFILE"] == "1"
    assert environ["SIDAR_ENV"] == "staging"
    # Empty HF cache path overrides are dropped before reaching the process env.
    assert "HF_HOME" not in environ


def test_reload_without_profile_skips_environment_layer(tmp_path) -> None:
    environ = {"SIDAR_ENV": ""}
    loaded_labels: list[str] = []

    _reload(
        tmp_path,
        environ,
        profile=None,
        plan=_plan(tmp_path),
        layers={},
        managed_keys=set(),
        loaded_labels=loaded_labels,
    )

    assert loaded_labels == [
        "base",
        "advanced",
        "explicit:DOTENV_FILE",
        "secret:SIDAR_KEYS_FILE",
    ]


def test_reload_with_skipped_default_layers_only_loads_explicit_and_secret(tmp_path) -> None:
    environ = {"SIDAR_ENV": "production"}
    loaded_labels: list[str] = []

    _reload(
        tmp_path,
        environ,
        profile="production",
        plan=_plan(tmp_path, skip_default_layers=True),
        layers={"explicit:DOTENV_FILE": {"FROM_EXPLICIT": "1"}},
        managed_keys=set(),
        loaded_labels=loaded_labels,
    )

    assert loaded_labels == ["explicit:DOTENV_FILE", "secret:SIDAR_KEYS_FILE"]
    assert environ["FROM_EXPLICIT"] == "1"
