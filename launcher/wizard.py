"""Interactive launcher wizard option tables and default-key resolution.

Extracted from ``main.run_wizard``. The prompts themselves (``ask_choice`` /
``ask_text``) stay in ``main.py`` because tests monkeypatch them there.
"""

from __future__ import annotations

from typing import Any

from launcher.selection import safe_choice

MODE_OPTIONS: dict[str, tuple[str, str]] = {
    "1": ("Web Arayüzü Sunucusu (FastAPI + UI)", "web"),
    "2": ("CLI Terminal Arayüzü", "cli"),
}
PROVIDER_OPTIONS: dict[str, tuple[str, str]] = {
    "1": ("Ollama (Yerel LLM)", "ollama"),
    "2": ("Gemini (Bulut LLM)", "gemini"),
    "3": ("OpenAI (Bulut LLM)", "openai"),
    "4": ("Anthropic Claude (Bulut LLM)", "anthropic"),
}
LEVEL_OPTIONS: dict[str, tuple[str, str]] = {
    "1": ("Full (Sınırsız Sistem Erişimi)", "full"),
    "2": ("Sandbox (Docker İzolasyonlu Sınırlandırılmış Erişim)", "sandbox"),
    "3": ("Restricted (Sadece Okuma ve Sohbet)", "restricted"),
}
LOG_OPTIONS: dict[str, tuple[str, str]] = {
    "1": ("INFO (Standart)", "info"),
    "2": ("DEBUG (Detaylı Geliştirici Logları)", "debug"),
    "3": ("WARNING (Sadece Uyarılar ve Hatalar)", "warning"),
}

_PROVIDER_KEYS = {"ollama": "1", "gemini": "2", "openai": "3", "anthropic": "4"}
_LOG_KEYS = {"info": "1", "debug": "2", "warning": "3", "error": "3"}


def wizard_default_keys(last_selection: dict[str, Any] | None, *, cfg: Any) -> dict[str, str]:
    """Return the default menu key for each wizard question.

    The last saved selection wins; otherwise config values (or safe defaults) are used.
    """
    mode_key = "1"
    if last_selection is not None:
        mode_key = "2" if last_selection.get("mode") == "cli" else "1"

    provider_source = (
        last_selection.get("provider")
        if last_selection is not None
        else getattr(cfg, "AI_PROVIDER", "ollama")
    )
    provider_value = safe_choice(
        provider_source, "ollama", {"ollama", "gemini", "openai", "anthropic"}
    )

    level_source = (
        last_selection.get("level")
        if last_selection is not None
        else getattr(cfg, "ACCESS_LEVEL", "full")
    )
    level_value = safe_choice(level_source, "full", {"restricted", "sandbox", "full"})
    level_key = "1" if level_value == "full" else "2" if level_value == "sandbox" else "3"

    log_source = last_selection.get("log") if last_selection is not None else "info"
    log_key = _LOG_KEYS.get(
        safe_choice(log_source, "info", {"info", "debug", "warning", "error"}), "1"
    )
    return {
        "mode": mode_key,
        "provider": _PROVIDER_KEYS.get(provider_value, "1"),
        "level": level_key,
        "log": log_key,
    }


def last_extra_args(last_selection: dict[str, Any] | None) -> dict[str, Any]:
    """Return the saved ``extra_args`` mapping, or ``{}`` when there is none."""
    if last_selection is None:
        return {}
    saved = last_selection.get("extra_args")
    return saved if isinstance(saved, dict) and saved else {}
