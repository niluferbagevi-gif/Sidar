from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Testlerin gerçek ortam anahtarları/URL'leriyle çalışmasını engeller."""
    sensitive_env_vars = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    )
    for var_name in sensitive_env_vars:
        monkeypatch.delenv(var_name, raising=False)

    # Varsayılanı lokal, izole SQLite test DB'si yapıyoruz.
    # PostgreSQL gereken testler bu değeri kendi fixture'larında override edebilir.
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'sidar_test.db'}")


@pytest.fixture(autouse=True)
def mock_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """config.Config için test bazlı güvenli varsayılanlar sağlar."""
    base_dir = tmp_path / "sidar_test_workspace"
    temp_dir = base_dir / "temp"
    logs_dir = base_dir / "logs"
    data_dir = base_dir / "data"

    monkeypatch.setattr("config.Config.AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr("config.Config.ACCESS_LEVEL", "full", raising=False)
    monkeypatch.setattr("config.Config.WEB_HOST", "127.0.0.1", raising=False)
    monkeypatch.setattr("config.Config.WEB_PORT", 7860, raising=False)
    monkeypatch.setattr("config.Config.BASE_DIR", base_dir, raising=False)
    monkeypatch.setattr("config.Config.TEMP_DIR", temp_dir, raising=False)
    monkeypatch.setattr("config.Config.LOGS_DIR", logs_dir, raising=False)
    monkeypatch.setattr("config.Config.DATA_DIR", data_dir, raising=False)
    monkeypatch.setattr("config.Config.REQUIRED_DIRS", [temp_dir, logs_dir, data_dir], raising=False)
    monkeypatch.setattr("config.Config.DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'sidar_test.db'}", raising=False)

    monkeypatch.setattr("config.Config.initialize_directories", staticmethod(lambda: True), raising=False)


@pytest.fixture
def mock_llm_client(monkeypatch: pytest.MonkeyPatch):
    """LLMClient.chat çağrılarını test içinde deterministik hale getirir."""

    async def _mock_chat(*args, **kwargs) -> str:
        _ = args, kwargs
        return "Bu otomatik bir test yanıtıdır."

    monkeypatch.setattr("core.llm_client.LLMClient.chat", _mock_chat, raising=False)
    return _mock_chat


@pytest.fixture
def fake_llm_response() -> dict[str, str]:
    """Ortak, deterministik sahte LLM yanıtı."""
    return {
        "tool": "final_answer",
        "thought": "fixture",
        "argument": "Bu fixture tabanlı sahte yanıttır.",
    }


@pytest.fixture
def fake_db_connection() -> dict[str, str | bool]:
    """Ortak sahte veritabanı bağlantı tanımı."""
    return {"dsn": "sqlite:///:memory:", "connected": True}


@pytest.fixture(autouse=True)
def restore_contracts_module_after_test() -> None:
    """Testler `agent.core.contracts` modülünü stub'ladığında state sızıntısını temizler."""
    yield

    module = sys.modules.get("agent.core.contracts")
    required = ("TaskEnvelope", "TaskResult", "DelegationRequest", "is_delegation_request")
    is_healthy = module is not None and all(hasattr(module, name) for name in required)
    if is_healthy and getattr(module, "DelegationRequest", object) is not object:
        return

    module_path = Path(__file__).resolve().parents[1] / "agent" / "core" / "contracts.py"
    spec = importlib.util.spec_from_file_location("agent.core.contracts", module_path)
    if spec is None or spec.loader is None:
        return
    repaired = importlib.util.module_from_spec(spec)
    sys.modules["agent.core.contracts"] = repaired
    spec.loader.exec_module(repaired)
    importlib.invalidate_caches()
