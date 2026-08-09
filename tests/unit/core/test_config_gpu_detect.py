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
    gray_zone = config_gpu_detect.normalize_gpu_memory_fractions(0.6, 0.3)
    assert gray_zone["normalized"] is True
    assert gray_zone["original_total"] == 0.9
    assert gray_zone["total"] == 0.8
    scaled = config_gpu_detect.normalize_gpu_memory_fractions(4.0, 0.01, min_fraction=0.2)
    assert scaled["normalized"] is True
    assert scaled["total"] == 0.8


def test_resolve_adaptive_gpu_pool_size_uses_env_and_hardware_budget() -> None:
    logger = _Logger()
    info = HardwareInfo(
        has_cuda=True,
        gpu_name="Ada",
        gpu_count=1,
        cpu_count=12,
        gpu_vram_mb=24 * 1024,
    )

    assert (
        config_gpu_detect.resolve_adaptive_gpu_pool_size(
            info,
            get_int_env=lambda *_args: 0,
            logger=logger,
        )
        == 4
    )
    assert logger.info_messages

    assert (
        config_gpu_detect.resolve_adaptive_gpu_pool_size(
            info,
            get_int_env=lambda *_args: 20,
            logger=_Logger(),
        )
        == 16
    )
    assert (
        config_gpu_detect.resolve_adaptive_gpu_pool_size(
            HardwareInfo(has_cuda=False, gpu_name="cpu"),
            get_int_env=lambda *_args: 0,
            logger=_Logger(),
        )
        == 1
    )


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
            get_device_properties=lambda _index: SimpleNamespace(total_memory=12 * 1024**3),
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
        available.gpu_vram_mb,
    ) == (
        True,
        2,
        "Test GPU",
        "12.1",
        12288,
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


@pytest.mark.parametrize(
    ("vram_mb", "expected"),
    [
        (16 * 1024, 3),
        (8 * 1024, 2),
        (8 * 1024 - 1, 1),
    ],
)
def test_resolve_adaptive_gpu_pool_size_vram_thresholds(vram_mb: int, expected: int) -> None:
    info = HardwareInfo(
        has_cuda=True,
        gpu_name="threshold-gpu",
        gpu_count=1,
        cpu_count=16,
        gpu_vram_mb=vram_mb,
    )

    assert (
        config_gpu_detect.resolve_adaptive_gpu_pool_size(
            info, get_int_env=lambda *_args: 0, logger=_Logger()
        )
        == expected
    )


def test_detect_gpu_sets_zero_vram_when_device_properties_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config_gpu_detect, "is_wsl2", lambda: False)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            cuda=SimpleNamespace(
                is_available=lambda: True,
                device_count=lambda: 1,
                get_device_name=lambda _index: "Fallback GPU",
                get_device_properties=lambda _index: (_ for _ in ()).throw(
                    RuntimeError("properties unavailable")
                ),
            ),
            version=SimpleNamespace(cuda="12.2"),
        ),
    )

    info = _detect(_Logger())

    assert info.has_cuda is True
    assert info.gpu_name == "Fallback GPU"
    assert info.gpu_vram_mb == 0
