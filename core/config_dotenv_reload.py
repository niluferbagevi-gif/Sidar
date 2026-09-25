"""Dotenv load-chain status logging and in-process reload for the Config facade.

`config.Config._log_dotenv_load_status()` and `config._reload_dotenv_chain()`
delegate here. The facade keeps owning the mutable dotenv bookkeeping (load
events, key sources, managed keys, the last logged chain signature) and passes
it in, so `importlib.reload(config)` and tests that swap those globals keep
seeing one source of truth.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any

from core import config_dotenv

ChainSignature = tuple[tuple[str, str], ...]


def log_dotenv_load_status(
    *,
    load_events: list[dict[str, Any]],
    missing_file_notices: list[str],
    key_sources: dict[str, dict[str, Any]],
    last_chain_signature: ChainSignature | None,
    missing_keys: list[str] | None,
    logger: logging.Logger,
    log_first_load_info: Callable[..., None],
) -> ChainSignature | None:
    """Log the effective dotenv chain and missing-key guidance.

    Returns:
        The chain signature to remember for the next call. It only changes when
        at least one dotenv file was loaded; otherwise ``last_chain_signature``
        is returned unchanged.
    """
    loaded = [event for event in load_events if event.get("loaded")]
    missing_files = [
        event
        for event in load_events
        if not event.get("loaded") and event.get("reason") == "missing"
    ]
    if loaded:
        chain_text = " -> ".join(f"{event['label']}={event['path']}" for event in loaded)
        chain_signature = tuple(
            (str(event.get("label", "")), str(event.get("path", ""))) for event in loaded
        )
        chain_changed = chain_signature != last_chain_signature
        last_chain_signature = chain_signature
        if chain_changed:
            log_first_load_info("Runtime env yükleme zinciri: %s", chain_text)
        else:
            logger.debug(
                "Runtime env yükleme zinciri: %s",
                chain_text,
            )
    else:
        logger.warning(
            "Hiçbir dotenv dosyası yüklenmedi; varsayılanlar ve proses ortam değişkenleri "
            "kullanılacak."
        )

    missing_notice_items = [
        f"{event['label']}={event['path']}" for event in missing_files if event.get("path")
    ]
    if missing_file_notices:
        for notice in missing_file_notices:
            if notice not in missing_notice_items:
                missing_notice_items.append(notice)
        missing_file_notices.clear()
    if missing_notice_items:
        logger.info(
            "Opsiyonel dotenv dosyaları bulunamadı: %s",
            ", ".join(missing_notice_items),
        )

    if key_sources:
        logger.debug(
            "Runtime env anahtar kaynakları: %s",
            ", ".join(
                f"{key}->{source['label']}={source['path']}"
                for key, source in sorted(key_sources.items())
            ),
        )

    if missing_keys:
        logger.warning(
            "Kritik ortam anahtarları çözülemedi: %s. Yükleme zinciri: .env, .env.advanced, "
            ".env.${SIDAR_ENV}, DOTENV_FILE, SIDAR_KEYS_FILE. Proses ortam değişkenleri "
            "korunur; SIDAR_KEYS_FILE en son yüklenir. "
            "Eksik değerleri .env, DOTENV_FILE veya SIDAR_KEYS_FILE (varsayılan "
            "~/.sidar_keys.env) içine ekleyin.",
            ", ".join(missing_keys),
        )
    return last_chain_signature


def reload_dotenv_chain(
    *,
    profile: str | None,
    environ: MutableMapping[str, str],
    base_dir: Path,
    managed_keys: set[str],
    load_events: list[dict[str, Any]],
    key_sources: dict[str, dict[str, Any]],
    build_dotenv_reload_plan: Callable[..., config_dotenv.DotenvReloadPlan],
    dotenv_reload_baseline_environment: Callable[..., dict[str, str]],
    load_dotenv_into_effective_env: Callable[..., Path | None],
) -> None:
    """Re-run the dotenv precedence chain and apply the result to ``environ`` in one step."""
    previous_managed_keys = set(managed_keys)
    # Snapshot before the collections below are cleared -- needed to decide,
    # per key, whether its supplying layer is still active this round
    # (see config_dotenv.dotenv_reload_baseline_environment's docstring).
    previous_key_sources = {key: dict(value) for key, value in key_sources.items()}
    # Resolve the plan (SIDAR_SKIP_DEFAULT_DOTENV/DOTENV_FILE/SIDAR_KEYS_FILE)
    # from the *real*, unmodified process environment -- never from a
    # baseline that may have already popped a previously dotenv-managed
    # control variable, or a direct override of one of these three keys
    # would be invisible to this reload's own plan.
    plan = build_dotenv_reload_plan(dict(environ), profile=profile)
    effective_env = dotenv_reload_baseline_environment(
        managed_keys=previous_managed_keys, key_sources=previous_key_sources, plan=plan
    )
    managed_keys.clear()
    load_events.clear()
    key_sources.clear()

    if not plan.skip_default_layers:
        load_dotenv_into_effective_env(
            effective_env, str(plan.base_path), override=False, label="base"
        )
        load_dotenv_into_effective_env(
            effective_env, str(plan.advanced_path), override=False, label="advanced"
        )

        selected_profile = config_dotenv.DotenvReloadPlan(
            profile=profile or effective_env.get("SIDAR_ENV", ""),
            base_path=plan.base_path,
            advanced_path=plan.advanced_path,
            explicit_path=plan.explicit_path,
            sidar_keys_file=plan.sidar_keys_file,
            skip_default_layers=plan.skip_default_layers,
        ).profile
        if selected_profile:
            effective_env["SIDAR_ENV"] = selected_profile
            load_dotenv_into_effective_env(
                effective_env,
                str(base_dir / f".env.{selected_profile}"),
                override=True,
                label=f"environment:{selected_profile}",
            )

    load_dotenv_into_effective_env(
        effective_env, plan.explicit_path, override=True, label="explicit:DOTENV_FILE"
    )
    load_dotenv_into_effective_env(
        effective_env, plan.sidar_keys_file, override=True, label="secret:SIDAR_KEYS_FILE"
    )
    config_dotenv.drop_empty_path_overrides(effective_env)

    removed_managed_keys = previous_managed_keys - set(effective_env)
    for key in removed_managed_keys:
        environ.pop(key, None)
    environ.update(effective_env)
