"""Plugin marketplace catalog, install-state persistence, and (un)install orchestration.

State management for the plugin marketplace lived directly in web_server.py
alongside route registration and dozens of unrelated subsystems. This module
holds the catalog data, the on-disk install-state persistence, and the
install/uninstall/reload orchestration; web_server.py keeps thin wrapper
functions so existing monkeypatch-based tests (which patch individual
collaborators like `_read_plugin_marketplace_state` or `_register_plugin_agent`
on web_server itself) keep observing the same names — every cross-function
call a caller might want to override is threaded through as an explicit
parameter rather than resolved via a module-internal reference.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)

PLUGIN_SOURCE_DIR = Path(__file__).resolve().parent.parent.parent / "plugins"

PLUGIN_MARKETPLACE_CATALOG: dict[str, dict[str, Any]] = {
    "aws_management": {
        "plugin_id": "aws_management",
        "name": "AWS Operations Agent",
        "summary": "EC2, S3 ve CloudWatch keşfi için hot-load edilebilen AWS operasyon ajanı.",
        "description": (
            "AWS CLI veya boto3 kuruluysa temel envanter ve operasyon komutlarını "
            "yerinde çalıştırır; yoksa gerekli kurulum adımlarını açıklar."
        ),
        "role_name": "aws_management",
        "class_name": "AWSManagementAgent",
        "capabilities": ["aws_management", "cloud_ops", "infra_observability"],
        "version": "1.0.0",
        "category": "Cloud",
        "entrypoint": PLUGIN_SOURCE_DIR / "aws_management_agent.py",
    },
    "slack_notifications": {
        "plugin_id": "slack_notifications",
        "name": "Slack Notification Agent",
        "summary": "Webhook veya bot token ile Slack bildirimleri gönderen ajan.",
        "description": (
            "Slack webhook/bot ayarlarını kullanarak anlık durum güncellemesi, "
            "incident bildirimi ve kanal mesajı akışlarını tetikler."
        ),
        "role_name": "slack_notifications",
        "class_name": "SlackNotificationAgent",
        "capabilities": ["slack_notification", "notifications", "ops_alerting"],
        "version": "1.0.0",
        "category": "Collaboration",
        "entrypoint": PLUGIN_SOURCE_DIR / "slack_notification_agent.py",
    },
}


def plugin_marketplace_state_path() -> Path:
    plugins_dir = Path("plugins")
    plugins_dir.mkdir(parents=True, exist_ok=True)
    return plugins_dir / ".marketplace_state.json"


def read_plugin_marketplace_state(*, logger_obj: Any = logger) -> dict[str, Any]:
    path = plugin_marketplace_state_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger_obj.warning("Plugin marketplace state JSON olarak okunamadı: %s (%s)", path, exc)
        return {}
    except OSError as exc:
        logger_obj.warning("Plugin marketplace state dosyası okunamadı: %s (%s)", path, exc)
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def write_plugin_marketplace_state(state: dict[str, Any]) -> None:
    path = plugin_marketplace_state_path()
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


def get_plugin_marketplace_entry(
    plugin_id: str, *, catalog: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    normalized = (plugin_id or "").strip().lower()
    entry = catalog.get(normalized)
    if not entry:
        raise HTTPException(status_code=404, detail="Plugin marketplace girdisi bulunamadı")
    return entry


def serialize_marketplace_plugin(
    plugin_id: str,
    *,
    catalog: dict[str, dict[str, Any]],
    agent_registry: Any,
    read_state: Callable[[], dict[str, Any]],
    installed_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = get_plugin_marketplace_entry(plugin_id, catalog=catalog)
    state = installed_state or read_state().get(plugin_id, {})
    spec = agent_registry.get(str(entry["role_name"]))
    installed = bool(state)
    entrypoint = Path(entry["entrypoint"])
    return {
        "plugin_id": str(entry["plugin_id"]),
        "id": str(entry["plugin_id"]),
        "name": str(entry["name"]),
        "summary": str(entry["summary"]),
        "description": str(entry["description"]),
        "category": str(entry["category"]),
        "role_name": str(entry["role_name"]),
        "class_name": str(entry["class_name"]),
        "capabilities": list(entry.get("capabilities", []) or []),
        "version": str(entry["version"]),
        "entrypoint": str(entrypoint),
        "entrypoint_exists": bool(entrypoint.exists()),
        "installed": installed,
        "installed_at": str(state.get("installed_at", "") or ""),
        "last_reloaded_at": str(state.get("last_reloaded_at", "") or ""),
        "live_registered": spec is not None,
        "agent": None
        if spec is None
        else {
            "role_name": str(getattr(spec, "role_name", entry["role_name"])),
            "description": str(getattr(spec, "description", entry["description"])),
            "capabilities": list(
                getattr(spec, "capabilities", entry.get("capabilities", [])) or []
            ),
            "version": str(getattr(spec, "version", entry["version"])),
            "is_builtin": bool(getattr(spec, "is_builtin", False)),
        },
    }


def install_marketplace_plugin(
    plugin_id: str,
    *,
    catalog: dict[str, dict[str, Any]],
    agent_registry: Any,
    register_plugin_agent: Callable[..., dict[str, Any]],
    read_state: Callable[[], dict[str, Any]],
    write_state: Callable[[dict[str, Any]], None],
    serialize: Callable[..., dict[str, Any]],
    persist: bool = True,
) -> dict[str, Any]:
    entry = get_plugin_marketplace_entry(plugin_id, catalog=catalog)
    source_path = Path(entry["entrypoint"])
    if not source_path.exists():
        raise HTTPException(status_code=500, detail=f"Plugin kaynağı bulunamadı: {source_path}")
    source_code = source_path.read_text(encoding="utf-8")
    agent_registry.unregister(str(entry["role_name"]))
    agent_meta = register_plugin_agent(
        role_name=str(entry["role_name"]),
        source_code=source_code,
        class_name=str(entry["class_name"]),
        capabilities=list(entry.get("capabilities", []) or []),
        description=str(entry["description"]),
        version=str(entry["version"]),
    )
    if persist:
        state = read_state()
        now = datetime.now(UTC).isoformat()
        previous = dict(state.get(plugin_id, {}) or {})
        previous.update(
            {
                "installed_at": previous.get("installed_at") or now,
                "last_reloaded_at": now,
                "role_name": str(entry["role_name"]),
                "entrypoint": str(source_path),
            }
        )
        state[plugin_id] = previous
        write_state(state)
    return {
        "success": True,
        "plugin": serialize(plugin_id),
        "agent": agent_meta,
    }


def uninstall_marketplace_plugin(
    plugin_id: str,
    *,
    catalog: dict[str, dict[str, Any]],
    agent_registry: Any,
    read_state: Callable[[], dict[str, Any]],
    write_state: Callable[[dict[str, Any]], None],
    serialize: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    entry = get_plugin_marketplace_entry(plugin_id, catalog=catalog)
    removed = agent_registry.unregister(str(entry["role_name"]))
    state = read_state()
    state.pop(plugin_id, None)
    write_state(state)
    return {
        "success": True,
        "removed": removed,
        "plugin": serialize(plugin_id),
    }


def reload_persisted_marketplace_plugins(
    *,
    catalog: dict[str, dict[str, Any]],
    read_state: Callable[[], dict[str, Any]],
    install: Callable[[str], dict[str, Any]],
    logger_obj: Any = logger,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for plugin_id in list(read_state().keys()):
        if plugin_id not in catalog:
            continue
        try:
            results.append(install(plugin_id))
        except HTTPException as exc:
            logger_obj.warning(
                "Marketplace plugin '%s' yeniden yüklenemedi: %s", plugin_id, exc.detail
            )
        except Exception as exc:
            logger_obj.warning("Marketplace plugin '%s' yeniden yüklenemedi: %s", plugin_id, exc)
    return results
