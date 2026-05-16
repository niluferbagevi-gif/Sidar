from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_secret_strength():
    module_path = Path("scripts/secret_strength.py")
    spec = importlib.util.spec_from_file_location("secret_strength", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secret_strength_rejects_common_medium_weak_passwords() -> None:
    secret_strength = _load_secret_strength()

    for value in (
        "Password1",
        "test123",
        "qwerty1234567890qwerty1234567890",
        "Password1Password1Password1",
    ):
        assert secret_strength.is_weak_secret(value)


def test_secret_strength_accepts_high_entropy_generated_tokens() -> None:
    secret_strength = _load_secret_strength()

    assert not secret_strength.is_weak_secret("N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh")
    assert not secret_strength.is_weak_secret("f3a1c9e8b7d6a5c4f2e0d9b8a7c6e5f413579bdf2468ace0")
