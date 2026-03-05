"""Sidar Project - Manager Modülleri"""
from .code_manager import CodeManager
from .github_manager import GitHubManager
from .package_info import PackageInfoManager
from .security import SecurityManager
from .system_health import SystemHealthManager
from .todo_manager import TodoManager
from .web_search import WebSearchManager

# Tek kaynak: Export edilecek manager sınıfları bu tuple'da tutulur.
# __all__ bu listedan türetildiği için manuel drift riski azaltılır.
_EXPORTED_MANAGERS = (
    CodeManager,
    SystemHealthManager,
    GitHubManager,
    SecurityManager,
    WebSearchManager,
    PackageInfoManager,
    TodoManager,
)

__all__ = [cls.__name__ for cls in _EXPORTED_MANAGERS]