"""Sidar Project - Manager Modülleri"""
from .browser_manager import BrowserManager
from .code_manager import CodeManager
from .github_manager import GitHubManager
from .jira_manager import JiraManager
from .package_info import PackageInfoManager
from .security import SecurityManager
from .slack_manager import SlackManager
from .system_health import SystemHealthManager
from .teams_manager import TeamsManager
from .todo_manager import TodoManager
from .web_search import WebSearchManager
from .youtube_manager import YouTubeManager

# Tek kaynak: Export edilecek manager sınıfları bu tuple'da tutulur.
# __all__ bu listedan türetildiği için manuel drift riski azaltılır.
_EXPORTED_MANAGERS = (
    BrowserManager,
    CodeManager,
    SystemHealthManager,
    GitHubManager,
    JiraManager,
    SlackManager,
    TeamsManager,
    SecurityManager,
    WebSearchManager,
    YouTubeManager,
    PackageInfoManager,
    TodoManager,
)

__all__ = [cls.__name__ for cls in _EXPORTED_MANAGERS]
