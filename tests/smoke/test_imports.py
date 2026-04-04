"""Smoke tests for critical imports."""

from importlib import import_module
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_critical_backend_imports() -> None:
    """Kritik backend modüllerinin import edilebildiğini doğrular."""
    module_names = (
        "agent",
        "agent.registry",
        "core",
        "config",
    )

    for module_name in module_names:
        imported = import_module(module_name)
        assert imported is not None
