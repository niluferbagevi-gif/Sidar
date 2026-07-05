from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from web.routes import plugin_marketplace


class _FakeAgentRegistry:
    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}
        self.unregistered: list[str] = []

    def get(self, role_name: str) -> Any:
        return self.registered.get(role_name)

    def unregister(self, role_name: str) -> bool:
        self.unregistered.append(role_name)
        return self.registered.pop(role_name, None) is not None


def _catalog(entrypoint: Path) -> dict[str, dict[str, Any]]:
    return {
        "demo": {
            "plugin_id": "demo",
            "name": "Demo Plugin",
            "summary": "s",
            "description": "d",
            "category": "c",
            "role_name": "demo_role",
            "class_name": "DemoAgent",
            "capabilities": ["x"],
            "version": "1.0.0",
            "entrypoint": entrypoint,
        }
    }


def test_get_plugin_marketplace_entry_raises_for_unknown_plugin() -> None:
    with pytest.raises(HTTPException):
        plugin_marketplace.get_plugin_marketplace_entry("missing", catalog={})


def test_read_plugin_marketplace_state_tolerates_missing_and_malformed_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    assert plugin_marketplace.read_plugin_marketplace_state() == {}

    plugin_marketplace.write_plugin_marketplace_state({"demo": {"installed_at": "now"}})
    assert plugin_marketplace.read_plugin_marketplace_state() == {"demo": {"installed_at": "now"}}

    state_path = plugin_marketplace.plugin_marketplace_state_path()
    state_path.write_text("{not-json", encoding="utf-8")

    class _RecordingLogger:
        def __init__(self) -> None:
            self.warnings: list[str] = []

        def warning(self, message: str, *args: object) -> None:
            self.warnings.append(message % args if args else message)

    recorder = _RecordingLogger()
    assert plugin_marketplace.read_plugin_marketplace_state(logger_obj=recorder) == {}
    assert recorder.warnings


def test_serialize_marketplace_plugin_reports_installed_and_live_state(tmp_path: Path) -> None:
    entrypoint = tmp_path / "demo.py"
    entrypoint.write_text("x = 1", encoding="utf-8")
    catalog = _catalog(entrypoint)
    registry = _FakeAgentRegistry()
    registry.registered["demo_role"] = type(
        "Spec",
        (),
        {
            "role_name": "demo_role",
            "description": "desc",
            "capabilities": ["x", "y"],
            "version": "9.9.9",
            "is_builtin": False,
        },
    )()

    payload = plugin_marketplace.serialize_marketplace_plugin(
        "demo",
        catalog=catalog,
        agent_registry=registry,
        read_state=lambda: {},
        installed_state={"installed_at": "t1"},
    )

    assert payload["installed"] is True
    assert payload["entrypoint_exists"] is True
    assert payload["agent"]["role_name"] == "demo_role"
    assert payload["live_registered"] is True


def test_install_uninstall_and_reload_marketplace_plugins_round_trip(tmp_path: Path) -> None:
    entrypoint = tmp_path / "demo_plugin.py"
    entrypoint.write_text("print('ok')", encoding="utf-8")
    catalog = _catalog(entrypoint)
    registry = _FakeAgentRegistry()
    state: dict[str, Any] = {}

    def _register_plugin_agent(**kwargs: Any) -> dict[str, Any]:
        registry.registered[kwargs["role_name"]] = object()
        return {"role_name": kwargs["role_name"], "version": kwargs["version"]}

    def _serialize(plugin_id: str) -> dict[str, Any]:
        return {"plugin_id": plugin_id}

    def _write_state(new_state: dict[str, Any]) -> None:
        state.clear()
        state.update(new_state)

    installed = plugin_marketplace.install_marketplace_plugin(
        "demo",
        catalog=catalog,
        agent_registry=registry,
        register_plugin_agent=_register_plugin_agent,
        read_state=lambda: dict(state),
        write_state=_write_state,
        serialize=_serialize,
        persist=True,
    )
    assert installed["success"] is True
    assert "demo" in state
    assert "demo_role" in registry.registered

    removed = plugin_marketplace.uninstall_marketplace_plugin(
        "demo",
        catalog=catalog,
        agent_registry=registry,
        read_state=lambda: dict(state),
        write_state=_write_state,
        serialize=_serialize,
    )
    assert removed["success"] is True
    assert "demo" not in state
    assert "demo_role" not in registry.registered


def test_reload_persisted_marketplace_plugins_tolerates_failures() -> None:
    calls: list[str] = []

    def _install(plugin_id: str) -> dict[str, Any]:
        calls.append(plugin_id)
        if plugin_id == "known-http":
            raise HTTPException(status_code=400, detail="bad plugin")
        raise RuntimeError("unexpected")

    class _RecordingLogger:
        def __init__(self) -> None:
            self.warnings: list[str] = []

        def warning(self, message: str, *args: object) -> None:
            self.warnings.append(message % args if args else message)

    recorder = _RecordingLogger()
    results = plugin_marketplace.reload_persisted_marketplace_plugins(
        catalog={"known-http": {}, "known-generic": {}},
        read_state=lambda: {"known-http": {}, "known-generic": {}, "unknown": {}},
        install=_install,
        logger_obj=recorder,
    )

    assert results == []
    assert calls == ["known-http", "known-generic"]
    assert any("known-http" in item for item in recorder.warnings)
    assert any("known-generic" in item for item in recorder.warnings)


def test_module_logger_is_a_real_logger() -> None:
    assert isinstance(plugin_marketplace.logger, logging.Logger)
