from __future__ import annotations

from pathlib import Path

from core.config_runtime_paths import load_runtime_path_settings
from core.config_secret_hardening import (
    collect_missing_critical_runtime_keys,
    collect_unsafe_production_secret_keys,
)


class _FakeConfig:
    API_KEY = ""
    JWT_SECRET_KEY = ""
    _JWT_SECRET_KEY_EXPLICITLY_CONFIGURED = False
    DATABASE_URL = "postgresql://sidar:sidar@localhost/sidar"
    AI_PROVIDER = "gemini"
    GEMINI_API_KEY = ""
    MEMORY_ENCRYPTION_KEY = ""
    AUTONOMY_WEBHOOK_SECRET = ""
    SWARM_FEDERATION_SHARED_SECRET = ""
    GITHUB_WEBHOOK_SECRET = ""
    METRICS_TOKEN = ""

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
    assert "AUTONOMY_WEBHOOK_SECRET" in missing
    assert "SWARM_FEDERATION_SHARED_SECRET" in missing
    assert "GITHUB_WEBHOOK_SECRET" in missing
    assert "GRAFANA_ADMIN_PASSWORD" in missing
    assert "METRICS_TOKEN" in missing


def test_production_secret_hardening_rejects_weak_and_nonproduction_shared_values(
    monkeypatch, tmp_path: Path
) -> None:
    strong_values = {
        key: f"{index:02d}-N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh-{index:02d}"
        for index, key in enumerate(
            (
                "API_KEY",
                "JWT_SECRET_KEY",
                "MEMORY_ENCRYPTION_KEY",
                "AUTONOMY_WEBHOOK_SECRET",
                "SWARM_FEDERATION_SHARED_SECRET",
                "GITHUB_WEBHOOK_SECRET",
                "GRAFANA_ADMIN_PASSWORD",
                "METRICS_TOKEN",
            ),
            start=1,
        )
    }
    config_cls = type("ProductionConfig", (), {"BASE_DIR": tmp_path, **strong_values})
    (tmp_path / ".env.development").write_text(
        f"API_KEY={strong_values['API_KEY']}\n", encoding="utf-8"
    )
    monkeypatch.setenv("GRAFANA_ADMIN_PASSWORD", strong_values["GRAFANA_ADMIN_PASSWORD"])

    assert collect_unsafe_production_secret_keys(config_cls) == ["API_KEY"]

    config_cls.METRICS_TOKEN = "changeme"
    assert collect_unsafe_production_secret_keys(config_cls) == ["API_KEY", "METRICS_TOKEN"]
