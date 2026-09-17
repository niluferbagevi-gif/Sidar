"""Shared dotenv-scoped pydantic-settings subclass builder for Sidar config.

Several ``config_*.py`` domain modules (``config_llm.py``, ``config_quality.py``)
need to build a settings instance that reads a *specific* dotenv file (the
resolved ``ENV_PATH``/``.env.advanced`` chain computed by ``config.py``)
instead of pydantic-settings' own default dotenv discovery. pydantic-settings
supports this per-instance via a private ``_env_file=...`` init kwarg, but its
declared type (``DotenvType | None``) is loose enough that passing it under
``mypy --strict`` produces an untyped-call warning at every call site. Building
a throwaway subclass with a scoped ``model_config`` instead keeps every call
site a plain, fully-typed ``SettingsClass()`` with zero dynamic init kwargs --
see ``test_load_llm_settings_reads_scoped_dotenv_without_dynamic_init_kwargs``
and its quality-gate counterpart in ``tests/unit/root/test_config.py``.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic_settings import BaseSettings, SettingsConfigDict

SettingsT = TypeVar("SettingsT", bound=BaseSettings)


def build_scoped_settings_type(
    settings_cls: type[SettingsT],
    *,
    env_file: str,
    env_ignore_empty: bool = False,
) -> type[SettingsT]:
    """Return a subclass of ``settings_cls`` scoped to ``env_file``.

    ``env_ignore_empty`` defaults to ``False`` (pydantic-settings' own
    default) so callers that never set it behave exactly as before this
    helper existed; pass ``True`` for settings classes that ship blank
    (``KEY=``) placeholders meant to fall back to the field default (see
    ``config_llm.LLMClientSettings`` / ``OLLAMA_CODING_NUM_CTX``).
    """
    scoped_settings_type: type[SettingsT] = type(
        f"Scoped{settings_cls.__name__}",
        (settings_cls,),
        {
            "__module__": settings_cls.__module__,
            "model_config": SettingsConfigDict(
                env_file=env_file,
                env_file_encoding="utf-8",
                extra="ignore",
                env_ignore_empty=env_ignore_empty,
            ),
        },
    )
    return scoped_settings_type
