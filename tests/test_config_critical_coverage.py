from __future__ import annotations

from types import SimpleNamespace

import config


def test_check_hardware_handles_missing_torch(monkeypatch) -> None:
    original_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(config, "_is_wsl2", lambda: False)
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr("builtins.__import__", _fake_import)

    info = config.check_hardware()
    assert info.gpu_name == "PyTorch Yok"
    assert info.has_cuda is False


def test_validate_critical_settings_requires_provider_keys(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "gemini", raising=False)
    monkeypatch.setattr(config.Config, "GEMINI_API_KEY", "", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    assert config.Config.validate_critical_settings() is False



def test_validate_critical_settings_litellm_gateway_required(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "litellm", raising=False)
    monkeypatch.setattr(config.Config, "LITELLM_GATEWAY_URL", "", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_invalid_memory_key(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "not-a-fernet-key", raising=False)

    class _BadFernet:
        def __init__(self, _raw: bytes) -> None:
            raise ValueError("bad key")

    fake_fernet_module = SimpleNamespace(Fernet=_BadFernet)
    monkeypatch.setitem(__import__("sys").modules, "cryptography.fernet", fake_fernet_module)

    assert config.Config.validate_critical_settings() is False
