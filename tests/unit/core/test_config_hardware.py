"""Deterministic tests for hardware configuration policies."""

from __future__ import annotations

import builtins
import sys
from typing import Any
from unittest.mock import Mock

import pytest

from core.config_gpu_detect import HardwareInfo
from core.config_hardware import apply_vram_memory_fraction


def test_apply_vram_memory_fraction_handles_torch_import_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skip the optional VRAM policy cleanly when torch cannot be imported."""
    original_import = builtins.__import__

    def _missing_torch(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "torch":
            raise ImportError("torch unavailable")
        return original_import(name, *args, **kwargs)

    logger = Mock()
    unused_dependency = Mock(side_effect=AssertionError("VRAM policy must stop after import"))
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr(builtins, "__import__", _missing_torch)

    result = apply_vram_memory_fraction(
        HardwareInfo(has_cuda=True, gpu_name="Test GPU", gpu_count=1),
        is_wsl2_runtime=unused_dependency,
        stable_cuda_wheel_tags=("cu128",),
        recommended_cuda_install_command="uv sync --all-extras",
        get_float_env=unused_dependency,
        get_bool_env=unused_dependency,
        get_int_env=unused_dependency,
        normalize_gpu_memory_fractions=unused_dependency,
        log_first_load_info=unused_dependency,
        logger=logger,
        environ={},
    )

    assert result is None
    logger.debug.assert_called_once()
    assert logger.debug.call_args.args[0] == (
        "VRAM fraksiyon ayarı için torch yeniden açılamadı: %s"
    )
    assert isinstance(logger.debug.call_args.args[1], ImportError)
    unused_dependency.assert_not_called()
