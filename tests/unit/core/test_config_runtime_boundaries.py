from __future__ import annotations

from pathlib import Path

from core.config_runtime_paths import load_runtime_path_settings
from core.config_secret_hardening import collect_missing_critical_runtime_keys


class _FakeConfig:
    API_KEY = ""
    JWT_SECRET_KEY = ""
    _JWT_SECRET_KEY_EXPLICITLY_CONFIGURED = False
    DATABASE_URL = "postgresql://sidar:sidar@localhost/sidar"
    AI_PROVIDER = "gemini"
    GEMINI_API_KEY = ""
    MEMORY_ENCRYPTION_KEY = ""

    @staticmethod
    def _is_test_env() -> bool:
        return False


def test_runtime_path_settings_resolve_repo_relative_rag_dir(tmp_path: Path) -> None:
    paths = load_runtime_path_settings(
        base_dir=tmp_path,
        environ={"RAG_DIR": "custom/rag"},
    )

    assert paths.base_dir == tmp_path
    assert paths.temp_dir == tmp_path / "temp"
    assert paths.logs_dir == tmp_path / "logs"
    assert paths.data_dir == tmp_path / "data"
    assert paths.memory_file == tmp_path / "data" / "memory.json"
    assert paths.required_dirs == [tmp_path / "temp", tmp_path / "logs", tmp_path / "data"]
    assert paths.rag_dir == tmp_path / "custom/rag"


def test_runtime_path_settings_preserve_absolute_rag_dir(tmp_path: Path) -> None:
    absolute_rag_dir = tmp_path / "absolute-rag"

    paths = load_runtime_path_settings(
        base_dir=tmp_path / "repo",
        environ={"RAG_DIR": str(absolute_rag_dir)},
    )

    assert paths.rag_dir == absolute_rag_dir


def test_secret_hardening_boundary_collects_security_and_provider_keys(monkeypatch) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")
    monkeypatch.setenv("POSTGRES_PASSWORD", "sidar")

    missing = collect_missing_critical_runtime_keys(
        _FakeConfig,
        provider_required_settings={"gemini": ("GEMINI_API_KEY",)},
        get_int_env=lambda _key, default: default,
    )

    assert "API_KEY" in missing
    assert "JWT_SECRET_KEY" in missing
    assert "POSTGRES_PASSWORD" in missing
    assert "GEMINI_API_KEY" in missing
    assert "MEMORY_ENCRYPTION_KEY" in missing
