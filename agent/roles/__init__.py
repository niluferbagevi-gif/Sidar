"""Multi-agent role paketleri."""

from importlib import import_module
from typing import Any

__all__ = ["ResearcherAgent", "CoderAgent", "ReviewerAgent", "PoyrazAgent", "QAAgent", "CoverageAgent"]

_ROLE_MODULES = {
    "ResearcherAgent": ".researcher_agent",
    "CoderAgent": ".coder_agent",
    "ReviewerAgent": ".reviewer_agent",
    "PoyrazAgent": ".poyraz_agent",
    "QAAgent": ".qa_agent",
    "CoverageAgent": ".coverage_agent",
}


def __getattr__(name: str) -> Any:
    module_path = _ROLE_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_path, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
