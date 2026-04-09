from __future__ import annotations

from types import SimpleNamespace

import pytest

import tests.smoke.test_gpu_inference as gpu_smoke


@pytest.mark.asyncio
async def test_gpu_smoke_skips_when_ollama_binary_missing(monkeypatch):
    monkeypatch.setattr(
        gpu_smoke.shutil,
        "which",
        lambda command: None if command == "ollama" else "/usr/bin/nvidia-smi",
    )

    with pytest.raises(pytest.skip.Exception, match="ollama"):
        await gpu_smoke.test_real_gpu_inference_smoke()


@pytest.mark.asyncio
async def test_gpu_smoke_skips_when_ollama_service_unreachable(monkeypatch):
    class _FakeClient:
        def __init__(self, _cfg):
            pass

        async def is_available(self):
            return False

    monkeypatch.setattr(gpu_smoke, "OllamaClient", _FakeClient)
    monkeypatch.setattr(gpu_smoke, "make_test_config", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(gpu_smoke.shutil, "which", lambda _command: "/usr/bin/mock")

    with pytest.raises(pytest.skip.Exception, match="Ollama servisine ulaşılamıyor"):
        await gpu_smoke.test_real_gpu_inference_smoke()


@pytest.mark.asyncio
async def test_gpu_smoke_success_path_returns_non_empty_response(monkeypatch):
    class _FakeClient:
        def __init__(self, _cfg):
            pass

        async def is_available(self):
            return True

        async def list_models(self):
            return ["qwen2.5-coder:1.5b"]

        async def chat(self, **kwargs):
            assert kwargs["model"] == "qwen2.5-coder:1.5b"
            return "GPU Çalışıyor"

    monkeypatch.setattr(gpu_smoke, "OllamaClient", _FakeClient)
    monkeypatch.setattr(gpu_smoke, "make_test_config", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(gpu_smoke.shutil, "which", lambda _command: "/usr/bin/mock")

    await gpu_smoke.test_real_gpu_inference_smoke()
