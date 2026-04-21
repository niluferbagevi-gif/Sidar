from __future__ import annotations

import subprocess
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
            return [gpu_smoke.MODEL_NAME]

        async def chat(self, **kwargs):
            assert kwargs["model"] == gpu_smoke.MODEL_NAME
            return "GPU Çalışıyor"

    monkeypatch.setattr(gpu_smoke, "OllamaClient", _FakeClient)
    monkeypatch.setattr(gpu_smoke, "make_test_config", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(gpu_smoke.shutil, "which", lambda _command: "/usr/bin/mock")

    await gpu_smoke.test_real_gpu_inference_smoke()


def test_env_int_falls_back_to_default_for_invalid_value(monkeypatch):
    monkeypatch.setenv("GPU_STRESS_CONCURRENCY", "invalid")
    assert gpu_smoke._env_int("GPU_STRESS_CONCURRENCY", 4, min_value=1, max_value=16) == 4


def test_env_int_clamps_value_to_bounds(monkeypatch):
    monkeypatch.setenv("GPU_STRESS_CONCURRENCY", "99")
    assert gpu_smoke._env_int("GPU_STRESS_CONCURRENCY", 4, min_value=1, max_value=16) == 16


def test_read_gpu_memory_used_mib_parses_all_devices(monkeypatch):
    monkeypatch.setattr(gpu_smoke, "is_gpu_available", lambda: True)
    monkeypatch.setattr(
        gpu_smoke.subprocess,
        "check_output",
        lambda *args, **kwargs: "120\n256\n",
    )
    assert gpu_smoke._read_gpu_memory_used_mib() == 376


def test_read_gpu_memory_used_mib_returns_none_when_command_fails(monkeypatch):
    monkeypatch.setattr(gpu_smoke, "is_gpu_available", lambda: True)

    def _raise(*_args, **_kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="nvidia-smi")

    monkeypatch.setattr(gpu_smoke.subprocess, "check_output", _raise)
    assert gpu_smoke._read_gpu_memory_used_mib() is None


@pytest.mark.asyncio
async def test_gpu_stress_skips_when_env_var_not_enabled():
    with pytest.raises(pytest.skip.Exception, match="RUN_GPU_STRESS=1"):
        await gpu_smoke.test_real_gpu_inference_stress_vram_and_concurrency()


@pytest.mark.asyncio
async def test_gpu_stress_skips_when_ollama_binary_missing(monkeypatch):
    monkeypatch.setenv("RUN_GPU_STRESS", "1")
    monkeypatch.setattr(
        gpu_smoke.shutil,
        "which",
        lambda command: None if command == "ollama" else "/usr/bin/nvidia-smi",
    )

    with pytest.raises(pytest.skip.Exception, match="ollama"):
        await gpu_smoke.test_real_gpu_inference_stress_vram_and_concurrency()


@pytest.mark.asyncio
async def test_gpu_stress_skips_when_ollama_service_unreachable(monkeypatch):
    class _FakeClient:
        def __init__(self, _cfg):
            pass

        async def is_available(self):
            return False

    monkeypatch.setenv("RUN_GPU_STRESS", "1")
    monkeypatch.setattr(gpu_smoke, "OllamaClient", _FakeClient)
    monkeypatch.setattr(gpu_smoke, "make_test_config", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(gpu_smoke.shutil, "which", lambda _command: "/usr/bin/mock")

    with pytest.raises(pytest.skip.Exception, match="Ollama servisine ulaşılamıyor"):
        await gpu_smoke.test_real_gpu_inference_stress_vram_and_concurrency()


@pytest.mark.asyncio
async def test_gpu_stress_skips_when_model_is_not_installed(monkeypatch):
    class _FakeClient:
        def __init__(self, _cfg):
            pass

        async def is_available(self):
            return True

        async def list_models(self):
            return ["some-other-model"]

    monkeypatch.setenv("RUN_GPU_STRESS", "1")
    monkeypatch.setattr(gpu_smoke, "OllamaClient", _FakeClient)
    monkeypatch.setattr(gpu_smoke, "make_test_config", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(gpu_smoke.shutil, "which", lambda _command: "/usr/bin/mock")

    with pytest.raises(pytest.skip.Exception, match="modeli yüklü değil"):
        await gpu_smoke.test_real_gpu_inference_stress_vram_and_concurrency()


@pytest.mark.asyncio
async def test_gpu_stress_success_path_without_real_gpu(monkeypatch):
    class _FakeClient:
        def __init__(self, _cfg):
            pass

        async def is_available(self):
            return True

        async def list_models(self):
            return [gpu_smoke.MODEL_NAME]

        async def chat(self, **kwargs):
            assert kwargs["model"] == gpu_smoke.MODEL_NAME
            assert kwargs["json_mode"] is False
            assert kwargs["messages"][0]["role"] == "user"
            return "ok"

    monkeypatch.setenv("RUN_GPU_STRESS", "1")
    monkeypatch.setenv("GPU_STRESS_CONCURRENCY", "1")
    monkeypatch.setenv("GPU_STRESS_ROUNDS", "1")
    monkeypatch.setenv("GPU_STRESS_PROMPT_REPEAT", "64")
    monkeypatch.setenv("GPU_STRESS_LATENCY_BUDGET", "10")
    monkeypatch.setattr(gpu_smoke, "OllamaClient", _FakeClient)
    monkeypatch.setattr(gpu_smoke, "make_test_config", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(gpu_smoke.shutil, "which", lambda _command: "/usr/bin/mock")

    gpu_memory_reads = iter([128, 256, None, 512])
    monkeypatch.setattr(
        gpu_smoke,
        "_read_gpu_memory_used_mib",
        lambda: next(gpu_memory_reads, 512),
    )

    await gpu_smoke.test_real_gpu_inference_stress_vram_and_concurrency()
