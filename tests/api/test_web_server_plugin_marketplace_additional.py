from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

import web_server


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    web_server.app.dependency_overrides[web_server._require_admin_user] = lambda: SimpleNamespace(role="admin")
    with TestClient(web_server.app, raise_server_exceptions=False) as test_client:
        yield test_client
    web_server.app.dependency_overrides.clear()


def test_validate_plugin_role_name_rejects_invalid_values() -> None:
    assert web_server._validate_plugin_role_name("  My_Role-01  ") == "my_role-01"
    with pytest.raises(web_server.HTTPException) as exc:
        web_server._validate_plugin_role_name("x")
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "source_code,class_name,detail_part",
    [
        ("def broken(\n", None, "derlenemedi"),
        ("class Something: pass", "Missing", "bulunamadı"),
        ("class NotAgent: pass", "NotAgent", "BaseAgent"),
        ("x = 1", None, "BaseAgent türevi"),
    ],
)
def test_load_plugin_agent_class_error_paths(source_code: str, class_name: str | None, detail_part: str) -> None:
    with pytest.raises(web_server.HTTPException) as exc:
        web_server._load_plugin_agent_class(source_code, class_name, "sidar_plugin_test")
    assert exc.value.status_code == 400
    assert detail_part in str(exc.value.detail)


def test_load_plugin_agent_class_auto_discovers_baseagent_subclass() -> None:
    source_code = """
from agent.base_agent import BaseAgent

class DemoPlugin(BaseAgent):
    ROLE_NAME = "demo"

    async def process_task(self, message, context=None):
        return message
"""
    cls = web_server._load_plugin_agent_class(source_code, None, "sidar_plugin_demo")
    assert cls.__name__ == "DemoPlugin"


def test_persist_and_import_plugin_file_valid_and_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    plugin_path = web_server._persist_and_import_plugin_file(
        filename="custom-plugin",
        data=b"from agent.base_agent import BaseAgent\nclass X(BaseAgent):\n async def process_task(self, message, context=None):\n  return message\n",
        module_label="sidar_plugin_upload",
    )

    assert plugin_path.name == "custom-plugin.py"
    assert plugin_path.exists()

    with pytest.raises(web_server.HTTPException) as exc:
        web_server._persist_and_import_plugin_file(
            filename="bad.py",
            data=b"raise RuntimeError('boom')",
            module_label="sidar_plugin_bad",
        )
    assert exc.value.status_code == 400
    assert "import edilemedi" in str(exc.value.detail)


def test_plugin_marketplace_state_read_write_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert web_server._read_plugin_marketplace_state() == {}

    state_path = Path("plugins/.marketplace_state.json")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("[]", encoding="utf-8")
    assert web_server._read_plugin_marketplace_state() == {}

    state_path.write_text("{broken", encoding="utf-8")
    assert web_server._read_plugin_marketplace_state() == {}

    web_server._write_plugin_marketplace_state({"aws_management": {"installed_at": "now"}})
    payload = web_server._read_plugin_marketplace_state()
    assert payload["aws_management"]["installed_at"] == "now"


def test_install_uninstall_reload_marketplace_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entrypoint = tmp_path / "plugins" / "dummy_plugin.py"
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    entrypoint.write_text("class X: pass", encoding="utf-8")

    monkeypatch.setattr(
        web_server,
        "PLUGIN_MARKETPLACE_CATALOG",
        {
            "dummy": {
                "plugin_id": "dummy",
                "name": "Dummy",
                "summary": "S",
                "description": "D",
                "category": "C",
                "role_name": "dummy_role",
                "class_name": "DummyAgent",
                "capabilities": ["one"],
                "version": "1.0.0",
                "entrypoint": entrypoint,
            }
        },
    )

    calls: dict[str, object] = {"state": {}}

    monkeypatch.setattr(web_server.AgentRegistry, "unregister", lambda role: role == "dummy_role")
    monkeypatch.setattr(
        web_server,
        "_register_plugin_agent",
        lambda **kwargs: {"role_name": kwargs["role_name"], "class_name": kwargs["class_name"]},
    )
    monkeypatch.setattr(web_server, "_read_plugin_marketplace_state", lambda: dict(calls["state"]))
    monkeypatch.setattr(web_server, "_write_plugin_marketplace_state", lambda state: calls.__setitem__("state", dict(state)))
    monkeypatch.setattr(
        web_server,
        "_serialize_marketplace_plugin",
        lambda plugin_id, installed_state=None: {"plugin_id": plugin_id, "installed_state": installed_state or {}},
    )

    installed = web_server._install_marketplace_plugin("dummy")
    assert installed["success"] is True
    assert installed["agent"]["role_name"] == "dummy_role"
    assert "dummy" in calls["state"]

    uninstalled = web_server._uninstall_marketplace_plugin("dummy")
    assert uninstalled["success"] is True
    assert uninstalled["removed"] is True
    assert calls["state"] == {}

    calls["state"] = {"dummy": {"installed_at": "x"}, "unknown": {"installed_at": "y"}}
    reloaded = web_server._reload_persisted_marketplace_plugins()
    assert len(reloaded) == 1
    assert reloaded[0]["success"] is True


def test_plugin_marketplace_endpoints(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server, "PLUGIN_MARKETPLACE_CATALOG", {"zeta": {"plugin_id": "zeta"}})
    monkeypatch.setattr(web_server, "_read_plugin_marketplace_state", lambda: {"zeta": {"installed_at": "now"}})
    monkeypatch.setattr(
        web_server,
        "_serialize_marketplace_plugin",
        lambda plugin_id, installed_state=None: {"plugin_id": plugin_id, "installed": bool(installed_state)},
    )
    monkeypatch.setattr(web_server, "_install_marketplace_plugin", lambda plugin_id: {"success": True, "plugin_id": plugin_id})
    monkeypatch.setattr(web_server, "_uninstall_marketplace_plugin", lambda plugin_id: {"success": True, "removed": plugin_id})

    catalog = client.get("/api/plugin-marketplace/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["items"] == [{"plugin_id": "zeta", "installed": True}]

    install = client.post("/api/plugin-marketplace/install", json={"plugin_id": "zeta"})
    reload_resp = client.post("/api/plugin-marketplace/reload", json={"plugin_id": "zeta"})
    uninstall = client.delete("/api/plugin-marketplace/install/zeta")

    assert install.json() == {"success": True, "plugin_id": "zeta"}
    assert reload_resp.json() == {"success": True, "plugin_id": "zeta"}
    assert uninstall.json() == {"success": True, "removed": "zeta"}
