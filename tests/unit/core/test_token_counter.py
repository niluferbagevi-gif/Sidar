import math
import types

from core.utils import token_counter


def test_estimate_tokens_keeps_openai_models_unscaled(monkeypatch):
    token_counter.get_tiktoken_encoding.cache_clear()

    class _Encoding:
        def encode(self, text):
            return list(text)

    tiktoken_stub = types.ModuleType("tiktoken")
    tiktoken_stub.encoding_for_model = lambda _name: _Encoding()  # type: ignore[attr-defined]
    tiktoken_stub.get_encoding = lambda _name: _Encoding()  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "tiktoken", tiktoken_stub)

    assert token_counter.estimate_tokens("abcd", model="gpt-4o-mini") == 4


def test_estimate_tokens_applies_provider_multiplier(monkeypatch):
    token_counter.get_tiktoken_encoding.cache_clear()

    class _Encoding:
        def encode(self, text):
            return list(text)

    tiktoken_stub = types.ModuleType("tiktoken")
    tiktoken_stub.encoding_for_model = lambda _name: _Encoding()  # type: ignore[attr-defined]
    tiktoken_stub.get_encoding = lambda _name: _Encoding()  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "tiktoken", tiktoken_stub)

    # 4 token temel tahmin * 1.20 (Claude) => 4.8 -> yukarı yuvarla => 5
    assert token_counter.estimate_tokens("abcd", model="claude-3-7-sonnet") == 5


def test_estimate_tokens_uses_fallback_and_multiplier_without_tiktoken(monkeypatch):
    token_counter.get_tiktoken_encoding.cache_clear()
    # monkeypatching builtins import is fragile across modules; directly patch function for deterministic fallback.
    monkeypatch.setattr(
        token_counter,
        "get_tiktoken_encoding",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ImportError()),
    )

    base = int(math.ceil(len("1234567") / 3.5))  # 2
    expected = int(math.ceil(base * 1.10))  # 3
    assert token_counter.estimate_tokens("1234567", model="llama3.1:8b") == expected
