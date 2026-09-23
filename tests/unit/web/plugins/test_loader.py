from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from web.plugins import loader
from web.plugins import sandbox as plugin_sandbox


def _unexpected_sandbox_run(_source: str, _label: str) -> dict[str, Any]:
    raise AssertionError("in-process sandbox must not run for the docker backend")


def test_load_plugin_agent_class_uses_isolated_proxy_for_docker_backend(monkeypatch):
    proxy = type("IsolatedPluginProxy", (), {})
    calls: list[tuple[str, str | None, str]] = []

    def _build_proxy(source: str, class_name: str | None, label: str) -> type:
        calls.append((source, class_name, label))
        return proxy

    monkeypatch.setattr(plugin_sandbox, "plugin_sandbox_backend", lambda: "docker")
    monkeypatch.setattr(plugin_sandbox, "build_isolated_plugin_proxy", _build_proxy)

    result = loader.load_plugin_agent_class(
        "class X: pass",
        "X",
        "mod",
        run_in_sandbox=_unexpected_sandbox_run,
        fallback_base=object,
    )

    assert result is proxy
    assert calls == [("class X: pass", "X", "mod")]


def test_load_plugin_agent_class_maps_docker_sandbox_error_to_503(monkeypatch):
    def _fail(*_args: Any) -> type:
        raise plugin_sandbox.PluginSandboxError("docker unavailable")

    monkeypatch.setattr(plugin_sandbox, "plugin_sandbox_backend", lambda: "docker")
    monkeypatch.setattr(plugin_sandbox, "build_isolated_plugin_proxy", _fail)

    with pytest.raises(HTTPException) as exc_info:
        loader.load_plugin_agent_class(
            "class X: pass",
            None,
            "mod",
            run_in_sandbox=_unexpected_sandbox_run,
            fallback_base=object,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "docker unavailable"


def test_load_plugin_agent_class_rejects_base_whose_subclass_check_fails(monkeypatch):
    class _BrokenCheckMeta(type):
        def __subclasscheck__(cls, subclass: type) -> bool:
            raise TypeError("subclass check failed")

    class _BrokenBase(metaclass=_BrokenCheckMeta):
        pass

    class Candidate:
        pass

    monkeypatch.setattr(plugin_sandbox, "plugin_sandbox_backend", lambda: "in_process")
    monkeypatch.delitem(__import__("sys").modules, "agent.base_agent", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        loader.load_plugin_agent_class(
            "",
            "Candidate",
            "mod",
            run_in_sandbox=lambda _s, _l: {"Candidate": Candidate},
            fallback_base=_BrokenBase,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Plugin BaseAgent doğrulanamadı"


def test_load_plugin_agent_class_ignores_classes_with_unrelated_bases(monkeypatch):
    class Unrelated:
        pass

    class Child(Unrelated):
        pass

    class FallbackBase:
        pass

    monkeypatch.setattr(plugin_sandbox, "plugin_sandbox_backend", lambda: "in_process")
    monkeypatch.delitem(__import__("sys").modules, "agent.base_agent", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        loader.load_plugin_agent_class(
            "",
            None,
            "mod",
            run_in_sandbox=lambda _s, _l: {"Child": Child},
            fallback_base=FallbackBase,
        )

    assert exc_info.value.status_code == 400
    assert "BaseAgent türevi" in exc_info.value.detail


def test_validate_and_persist_plugin_file_describes_source_for_docker_backend(
    monkeypatch, tmp_path
):
    described: list[tuple[str, str | None, str]] = []

    class _Backend:
        def describe(self, source: str, class_name: str | None, label: str) -> None:
            described.append((source, class_name, label))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(plugin_sandbox, "plugin_sandbox_backend", lambda: "docker")
    monkeypatch.setattr(plugin_sandbox, "DockerPluginSandboxBackend", _Backend)

    path = loader.validate_and_persist_plugin_file(
        "agent_plugin.py", "print('ok')", "mod", run_in_sandbox=_unexpected_sandbox_run
    )

    assert described == [("print('ok')", None, "mod")]
    assert path.name == "agent_plugin.py"
    assert (tmp_path / "plugins" / "agent_plugin.py").read_text(encoding="utf-8") == "print('ok')"


def test_validate_and_persist_plugin_file_maps_docker_sandbox_error_to_503(monkeypatch, tmp_path):
    class _Backend:
        def describe(self, *_args: Any) -> None:
            raise plugin_sandbox.PluginSandboxError("image missing")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(plugin_sandbox, "plugin_sandbox_backend", lambda: "docker")
    monkeypatch.setattr(plugin_sandbox, "DockerPluginSandboxBackend", _Backend)

    with pytest.raises(HTTPException) as exc_info:
        loader.validate_and_persist_plugin_file(
            "agent_plugin.py", "print('ok')", "mod", run_in_sandbox=_unexpected_sandbox_run
        )

    assert exc_info.value.status_code == 503
    assert not (tmp_path / "plugins").exists()
