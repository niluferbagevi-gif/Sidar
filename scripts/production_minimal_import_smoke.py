#!/usr/bin/env python3
"""Runtime import smoke test for the production-minimal dependency profile.

Imports the modules a production-minimal deploy actually boots (web app,
config, core facade, agent role catalog) with only ``sidar[postgres]``
installed (no ``dev`` extra). Any missing runtime dependency for code that
executes unconditionally on import surfaces here as a hard failure, instead
of silently passing because a fuller local/CI profile happened to install
the missing package via an unrelated extra.
"""

from __future__ import annotations

import importlib
import sys

MODULES = [
    "config",
    "core",
    "core.llm_client",
    "core.db",
    "managers.security",
    "managers.code_manager",
    "agent",
    "agent.roles",
    "web_server",
]


def main() -> int:
    failures: list[tuple[str, str]] = []
    for module_name in MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - report every import failure, not just the first
            failures.append((module_name, f"{type(exc).__name__}: {exc}"))

    if failures:
        print("❌ production-minimal runtime import smoke failed:")
        for module_name, reason in failures:
            print(f"   - {module_name}: {reason}")
        return 1

    print(f"✅ production-minimal runtime import smoke ok ({len(MODULES)} modules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
