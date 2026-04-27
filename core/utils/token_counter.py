from __future__ import annotations

import math
from functools import lru_cache


def estimate_tokens(text: str, *, model: str = "") -> int:
    normalized = text or ""
    if not normalized:
        return 0
    try:
        encoding = get_tiktoken_encoding(model)
        return max(0, len(encoding.encode(normalized)))
    except Exception:
        # Heuristik fallback: Unicode/kod yoğun içeriklerde 4 yerine 3.5 ortalaması daha güvenli.
        return max(0, int(math.ceil(len(normalized) / 3.5)))


@lru_cache(maxsize=64)
def get_tiktoken_encoding(model: str = ""):
    import tiktoken  # type: ignore

    model_name = (model or "").strip()
    try:
        return tiktoken.encoding_for_model(model_name) if model_name else tiktoken.get_encoding("cl100k_base")
    except Exception:
        return tiktoken.get_encoding("cl100k_base")
