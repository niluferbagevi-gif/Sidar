"""Deterministic tests for the standalone GPU detection helpers."""

from __future__ import annotations

import builtins
import multiprocessing
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core import config_gpu_detect
from core.config_gpu_detect import HardwareInfo


class _Logger:
    def __init__(self) -> None:
        self.info_messages: list[str] = []
        self.warning_messages: list[str] = []

    def info(self, message: str, *_args: Any) -> None:
        self.info_messages.append(message)

    def warning(self, message: str, *_args: Any) -> None:
        self.warning_messages.append(message)


def _detect(logger: _Logger, *, enabled: bool = True) -> HardwareInfo:
    return config_gpu_detect.detect_gpu(
        get_bool_env=lambda *_args: enabled,
        get_int_env=lambda *_args: 0,
        get_float_env=lambda *_args: 0.0,
        logger=logger,
    )


def test_is_wsl2_handles_matching_and_unreadable_kernel_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: "WSL2-Microsoft")
    assert config_gpu_detect.is_wsl2() is True

    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")),
    )
    assert config_gpu_detect.is_wsl2() is False


def test_normalize_gpu_memory_fractions_covers_default_safe_and_scaled_budgets() -> None:
    assert config_gpu_detect.normalize_gpu_memory_fractions(0, 0)["llm"] == 0.4
    assert config_gpu_detect.normalize_gpu_memory_fractions(0.3, 0.2)["normalized"] is False
    scaled = config_gpu_detect.normalize_gpu_memory_fractions(4.0, 0.01, min_fraction=0.2)
    assert scaled["normalized"] is True
    assert scaled["total"] == 0.8


def test_detect_gpu_disabled_cuda_available_and_cuda_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = _Logger()
    monkeypatch.setattr(config_gpu_detect, "is_wsl2", lambda: True)
    disabled = _detect(logger, enabled=False)
    assert disabled.gpu_name == "Devre Dışı (Kullanıcı)"
    assert logger.info_messages

    torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 2,
            get_device_name=lambda _index: "Test GPU",
        ),
        version=SimpleNamespace(cuda="12.1"),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    available = _detect(_Logger())
    assert (
        available.has_cuda,
        available.gpu_count,
        available.gpu_name,
        available.cuda_version,
    ) == (
        True,
        2,
        "Test GPU",
        "12.1",
    )

    torch.cuda.is_available = lambda: False
    assert _detect(_Logger()).gpu_name == "CUDA Bulunamadı"


def test_detect_gpu_handles_missing_torch_and_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def _missing_torch(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "torch":
            raise ImportError("torch unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr(builtins, "__import__", _missing_torch)
    assert _detect(_Logger()).gpu_name == "PyTorch Yok"

    monkeypatch.setattr(builtins, "__import__", original_import)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: (_ for _ in ()).throw(RuntimeError("x")))
        ),
    )
    assert _detect(_Logger()).gpu_name == "Tespit Edilemedi"


def test_detect_gpu_uses_cpu_count_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        multiprocessing, "cpu_count", lambda: (_ for _ in ()).throw(RuntimeError("cpu"))
    )
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    )
    assert _detect(_Logger()).cpu_count == 1


def test_detect_gpu_skips_wsl_log_outside_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _Logger()
    monkeypatch.setattr(config_gpu_detect, "is_wsl2", lambda: False)
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    )

    assert _detect(logger).gpu_name == "CUDA Bulunamadı"
    assert not any("WSL2 ortamı" in message for message in logger.info_messages)
