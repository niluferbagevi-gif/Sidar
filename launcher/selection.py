"""Launcher launch-selection helpers: safe value normalization and merging.

Extracted from ``main.py``. ``cfg`` is threaded through explicitly (rather
than imported from main.py) so callers resolve their own current config —
including main.py's ``cfg`` global, which is reassigned on env reload and
monkeypatched directly in tests — at call time.
"""

from __future__ import annotations

import argparse
from typing import Any


def safe_choice(value: object, default: str, allowed: set[str]) -> str:
    """Config/env kökenli seçimleri normalize eder; geçersizde default döner."""
    if not isinstance(value, str):
        return default

    normalized = value.strip().lower()
    if not normalized or normalized not in allowed:
        return default
    return normalized


def safe_text(value: object, default: str) -> str:
    """Config/env kökenli metinleri normalize eder; boş/geçersizde default döner."""
    if value is None:
        return default

    normalized = str(value).strip()
    return normalized or default


def safe_port(value: object, default: str = "7860") -> str:
    """Config/env kökenli port değerlerini güvenli biçimde doğrular."""
    normalized = safe_text(value, default)
    try:
        port = int(normalized)
    except (TypeError, ValueError):
        return default
    return str(port) if 1 <= port <= 65535 else default


def safe_host(value: object, default: str = "127.0.0.1") -> str:
    """Config/env kökenli host değerlerini `ipaddress` tabanlı doğrulayıcıdan geçirir.

    Geçersiz veya üretim profilinde reddedilen değerlerde güvenli yerel
    fallback (`127.0.0.1`) döner; böylece `# nosec B104` ile bypass yapmak
    yerine politika tek bir noktada uygulanır.
    """
    from core.utils.network_validation import validate_bind_host

    candidate = safe_text(value, default)
    try:
        return validate_bind_host(candidate)
    except ValueError:
        try:
            return validate_bind_host(default)
        except ValueError:
            return "127.0.0.1"


def normalize_launch_selection(selection: dict[str, object], *, cfg: Any) -> dict[str, Any]:
    """Cache/varsayılan kaynaklı launcher seçimlerini güvenli değerlere normalize eder."""
    mode = safe_choice(selection.get("mode"), "web", {"web", "cli"})
    provider = safe_choice(
        selection.get("provider"),
        safe_choice(
            getattr(cfg, "AI_PROVIDER", "ollama"),
            "ollama",
            {"ollama", "gemini", "openai", "anthropic"},
        ),
        {"ollama", "gemini", "openai", "anthropic"},
    )
    level = safe_choice(
        selection.get("level"),
        safe_choice(
            getattr(cfg, "ACCESS_LEVEL", "full"), "full", {"restricted", "sandbox", "full"}
        ),
        {"restricted", "sandbox", "full"},
    )
    log_level = safe_choice(selection.get("log"), "info", {"info", "debug", "warning", "error"})

    raw_extra_args = selection.get("extra_args")
    extra_args = raw_extra_args if isinstance(raw_extra_args, dict) else {}
    normalized_extra_args = {
        "model": safe_text(
            extra_args.get("model"),
            safe_text(getattr(cfg, "CODING_MODEL", "qwen2.5-coder:7b"), "qwen2.5-coder:7b"),
        ),
        "host": safe_host(extra_args.get("host", getattr(cfg, "WEB_HOST", "127.0.0.1"))),
        "port": safe_port(extra_args.get("port", getattr(cfg, "WEB_PORT", 7860)), "7860"),
    }
    return {
        "mode": mode,
        "provider": provider,
        "level": level,
        "log": log_level,
        "extra_args": normalized_extra_args,
    }


def default_launch_selection(*, cfg: Any) -> dict[str, Any]:
    """--skip-wizard için config/default değerlerinden çalıştırılabilir seçim üretir."""
    return normalize_launch_selection(
        {
            "mode": "web",
            "provider": getattr(cfg, "AI_PROVIDER", "ollama"),
            "level": getattr(cfg, "ACCESS_LEVEL", "full"),
            "log": "info",
            "extra_args": {
                "model": getattr(cfg, "CODING_MODEL", "qwen2.5-coder:7b"),
                "host": getattr(cfg, "WEB_HOST", "127.0.0.1"),
                "port": getattr(cfg, "WEB_PORT", 7860),
            },
        },
        cfg=cfg,
    )


def apply_cli_overrides(
    selection: dict[str, Any], args: argparse.Namespace, *, cfg: Any
) -> dict[str, Any]:
    """--skip-wizard akışında config/default seçime açık CLI override'larını uygular."""
    merged = dict(selection)
    extra_args = dict(selection.get("extra_args", {}))
    if args.provider:
        merged["provider"] = args.provider
    if args.level:
        merged["level"] = args.level
    if args.log:
        merged["log"] = str(args.log).lower()
    if args.model:
        extra_args["model"] = args.model
    if args.host:
        extra_args["host"] = args.host
    if args.port:
        extra_args["port"] = args.port
    merged["extra_args"] = extra_args
    return normalize_launch_selection(merged, cfg=cfg)


__all__ = [
    "apply_cli_overrides",
    "default_launch_selection",
    "normalize_launch_selection",
    "safe_choice",
    "safe_host",
    "safe_port",
    "safe_text",
]
