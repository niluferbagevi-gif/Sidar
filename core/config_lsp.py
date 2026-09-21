"""Language Server Protocol (LSP) integration settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env, get_int_env


@dataclass(frozen=True)
class LspSettings:
    """``managers/code_manager.py`` LSP client integration settings."""

    enable_lsp: bool
    lsp_timeout_seconds: int
    lsp_max_references: int
    python_lsp_server: str
    typescript_lsp_server: str


def load_lsp_settings() -> LspSettings:
    """Load LSP integration settings from environment variables."""
    return LspSettings(
        enable_lsp=get_bool_env("ENABLE_LSP", True),
        lsp_timeout_seconds=get_int_env("LSP_TIMEOUT_SECONDS", 15),
        lsp_max_references=get_int_env("LSP_MAX_REFERENCES", 200),
        python_lsp_server=os.getenv("PYTHON_LSP_SERVER", "pyright-langserver"),
        typescript_lsp_server=os.getenv("TYPESCRIPT_LSP_SERVER", "typescript-language-server"),
    )
