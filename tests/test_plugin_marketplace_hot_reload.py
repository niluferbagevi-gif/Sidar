import asyncio
import json
from pathlib import Path

from tests.test_web_server_runtime import _load_web_server


def test_plugin_marketplace_catalog_install_reload_and_remove(tmp_path, monkeypatch):
    mod = _load_web_server()
    monkeypatch.chdir(tmp_path)

    catalog = asyncio.run(mod.plugin_marketplace_catalog(_user=object()))
    items = catalog.content["items"]
    plugin_ids = {item["plugin_id"] for item in items}
    assert {"aws_management", "slack_notifications"} <= plugin_ids

    request = mod._PluginMarketplaceInstallRequest(plugin_id="aws_management")
    installed = asyncio.run(mod.install_plugin_marketplace_item(request, _user=object()))
    assert installed.content["success"] is True
    assert installed.content["plugin"]["installed"] is True
    assert installed.content["agent"]["role_name"] == "aws_management"

    state_path = Path("plugins/.marketplace_state.json")
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "aws_management" in state

    reloaded = asyncio.run(mod.reload_plugin_marketplace_item(request, _user=object()))
    assert reloaded.content["success"] is True
    assert reloaded.content["plugin"]["live_registered"] is True

    removed = asyncio.run(mod.uninstall_plugin_marketplace_item("aws_management", _user=object()))
    assert removed.content["success"] is True
    assert removed.content["plugin"]["installed"] is False
    assert "aws_management" not in json.loads(state_path.read_text(encoding="utf-8"))


def test_plugin_marketplace_persisted_reload_and_spa_fallback(tmp_path, monkeypatch):
    mod = _load_web_server()
    monkeypatch.chdir(tmp_path)

    plugins_dir = Path("plugins")
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / ".marketplace_state.json").write_text(
        json.dumps({"slack_notifications": {"installed_at": "2026-03-21T00:00:00+00:00"}}),
        encoding="utf-8",
    )

    results = mod._reload_persisted_marketplace_plugins()
    assert results
    assert results[0]["plugin"]["plugin_id"] == "slack_notifications"

    spa_ok = asyncio.run(mod.spa_fallback("admin/plugins"))
    assert spa_ok.status_code == 200

    spa_missing = asyncio.run(mod.spa_fallback("assets/main.js"))
    assert spa_missing.status_code == 404


def test_react_plugin_marketplace_panel_is_wired():
    app_source = Path("web_ui_react/src/App.jsx").read_text(encoding="utf-8")
    panel_source = Path("web_ui_react/src/components/PluginMarketplacePanel.jsx").read_text(encoding="utf-8")

    assert "/admin/plugins" in app_source
    assert "Plugin Marketplace" in app_source
    assert "/api/plugin-marketplace/catalog" in panel_source
    assert "Anında Yükle" in panel_source
