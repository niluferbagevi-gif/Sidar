from __future__ import annotations

import runpy

import pytest

import core.doctor as doctor


def test_python_m_core_doctor_entrypoint_delegates_to_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover the ``python -m core.doctor`` entry point without running real checks."""

    calls = []

    def fake_main() -> int:
        calls.append("main")
        return 7

    monkeypatch.setattr(doctor, "main", fake_main)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("core.doctor.__main__", run_name="__main__")

    assert exc_info.value.code == 7
    assert calls == ["main"]
