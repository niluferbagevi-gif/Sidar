"""Sidar Project - Manager Modülleri.

Manager sınıfları ağır/opsiyonel bağımlılıklara (örn. httpx, browser stack)
sahip olabildiği için package-level eager import yapılmaz.
Gerektiğinde `from managers import CodeManager` benzeri erişimler __getattr__
üzerinden lazy olarak çözülür.
"""

from __future__ import annotations

from importlib import import_module

_MANAGER_IMPORT_MAP = {
    "BrowserManager": "managers.browser_manager",
    "CodeManager": "managers.code_manager",
    "GitHubManager": "managers.github_manager",
    "JiraManager": "managers.jira_manager",
    "PackageInfoManager": "managers.package_info",
    "SecurityManager": "managers.security",
    "SlackManager": "managers.slack_manager",
    "SocialMediaManager": "managers.social_media_manager",
    "SystemHealthManager": "managers.system_health",
    "TeamsManager": "managers.teams_manager",
    "TodoManager": "managers.todo_manager",
    "WebSearchManager": "managers.web_search",
    "YouTubeManager": "managers.youtube_manager",
}


__all__ = list(_MANAGER_IMPORT_MAP.keys())


def __getattr__(name: str):
    # 1. Sınıf isimleri için (Örn: CodeManager)
    module_path = _MANAGER_IMPORT_MAP.get(name)
    if module_path is not None:
        module = import_module(module_path)
        value = getattr(module, name)
        globals()[name] = value
        return value

    # 2. Pytest monkeypatch ve doğrudan modül erişimleri için (Örn: managers.package_info)
    for path in _MANAGER_IMPORT_MAP.values():
        if path.endswith(f".{name}"):
            module = import_module(path)
            globals()[name] = module
            return module

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
