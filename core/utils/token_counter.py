from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

_MODEL_TOKEN_MULTIPLIERS: tuple[tuple[tuple[str, ...], float], ...] = (
    (("claude", "anthropic"), 1.20),
    (("gemini",), 1.12),
    (("llama", "ollama", "mistral", "qwen", "deepseek"), 1.10),
)


def _token_estimate_multiplier(model: str = "") -> float:
    normalized = (model or "").strip().lower()
    if not normalized:
        return 1.0
    if normalized.startswith(("gpt", "o1", "o3", "text-embedding")):
        return 1.0
    for aliases, multiplier in _MODEL_TOKEN_MULTIPLIERS:
        if any(alias in normalized for alias in aliases):
            return multiplier
    return 1.0


def estimate_tokens(text: str, *, model: str = "") -> int:
    normalized = text or ""
    if not normalized:
        return 0
    try:
        encoding = get_tiktoken_encoding(model)
        base_tokens = max(0, len(encoding.encode(normalized)))
    except Exception:
        # Heuristik fallback: Unicode/kod yoğun içeriklerde 4 yerine 3.5 ortalaması daha güvenli.
        base_tokens = max(0, int(math.ceil(len(normalized) / 3.5)))
    multiplier = _token_estimate_multiplier(model)
    return max(0, int(math.ceil(base_tokens * multiplier)))


@lru_cache(maxsize=64)
def get_tiktoken_encoding(model: str = "") -> Any:
    import tiktoken  # type: ignore

    model_name = (model or "").strip()
    try:
        return (
            tiktoken.encoding_for_model(model_name)
            if model_name
            else tiktoken.get_encoding("cl100k_base")
        )
    except Exception:
        return tiktoken.get_encoding("cl100k_base")
