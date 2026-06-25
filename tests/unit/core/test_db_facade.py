from __future__ import annotations

import importlib
import sys


def test_db_facade_skips_optional_submodule_import_errors(monkeypatch):
    original_import_module = importlib.import_module

    optional_error_seen = {"value": False}

    def flaky_import(name: str, package: str | None = None):
        if name == "core.db.metrics":
            optional_error_seen["value"] = True
            raise RuntimeError("optional metrics import failed")
        return original_import_module(name, package)

    from core.db import monolith

    monkeypatch.delattr(monolith, "metrics", raising=False)
    for name in ["core.db", "core.db.metrics"]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(importlib, "import_module", flaky_import)

    module = importlib.import_module("core.db")

    assert optional_error_seen["value"] is True
    assert module.Database is not None
