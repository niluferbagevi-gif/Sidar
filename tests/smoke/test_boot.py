from __future__ import annotations

import importlib

import pytest


@pytest.mark.smoke
def test_main_module_boots() -> None:
    module = importlib.import_module("main")
    assert hasattr(module, "main")
