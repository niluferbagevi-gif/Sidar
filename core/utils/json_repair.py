from __future__ import annotations

import ast
import asyncio
import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)
STRICT_FENCE_PATTERN = r"(?ms)```(?:json)?[ \t]*\n(.*?)\n```"
LOOSE_FENCE_PATTERN = r"```(?:json)?\s*([\s\S]*?)\s*```"
MAX_JSON_REPAIR_INPUT_CHARS = 20_000
MAX_JSON_REPAIR_NESTING = 80
MAX_JSON_REPAIR_ATTEMPTS = 32


@dataclass(slots=True)
class _RepairBudget:
    """Bound parser work across direct, decoder, fenced and literal repair paths."""

    remaining: int = MAX_JSON_REPAIR_ATTEMPTS

    def consume(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def is_safe_literal_eval_candidate(
    text: str,
    *,
    max_len: int = MAX_JSON_REPAIR_INPUT_CHARS,
    max_depth: int = MAX_JSON_REPAIR_NESTING,
) -> bool:
    candidate = (text or "").strip()
    if not candidate or len(candidate) > max_len:
        return False

    depth = 0
    in_string = False
    string_quote = ""
    escaped = False

    for ch in candidate:
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == string_quote:
                in_string = False
            continue

        if ch in {"'", '"'}:
            in_string = True
            string_quote = ch
            continue

        if ch in "{[(":
            depth += 1
            if depth > max_depth:
                return False
        elif ch in "}])":
            depth = max(0, depth - 1)

    return True


def _json_dumps_if_valid(raw: str, *, budget: _RepairBudget) -> str | None:
    normalized = (raw or "").strip()
    if not normalized:
        return None
    if not budget.consume():
        return None
    try:
        obj = json.loads(normalized)
        return json.dumps(obj, ensure_ascii=False)
    except Exception as exc:
        logger.debug("Geçerli JSON doğrudan parse edilemedi: %s", exc)

    # En baştaki geçerli JSON nesnesini yakalamak için decoder tabanlı onarım.
    decoder = json.JSONDecoder()
    for i, ch in enumerate(normalized):
        if ch not in "{[":
            continue
        if not budget.consume():
            logger.debug("JSON onarımı durduruldu: maksimum parse denemesi aşıldı.")
            return None
        try:
            obj, _ = decoder.raw_decode(normalized[i:])
            return json.dumps(obj, ensure_ascii=False)
        except Exception as exc:
            logger.debug("JSON raw_decode denemesi başarısız (offset=%s): %s", i, exc)
            continue
    return None


def _repair_json_candidate(candidate: str, *, budget: _RepairBudget) -> str | None:
    parsed = _json_dumps_if_valid(candidate, budget=budget)
    if parsed is not None:
        return parsed

    # Çoklu fenced markdown çıktılarında her bloğu sırayla dene.
    for fenced in re.finditer(
        STRICT_FENCE_PATTERN,
        candidate,
        flags=re.IGNORECASE,
    ):
        parsed = _json_dumps_if_valid(fenced.group(1), budget=budget)
        if parsed is not None:
            return parsed

    # Satır sonu olmadan gelen fenced varyantları için gevşek fallback.
    for fenced in re.finditer(LOOSE_FENCE_PATTERN, candidate, flags=re.IGNORECASE):
        parsed = _json_dumps_if_valid(fenced.group(1), budget=budget)
        if parsed is not None:
            return parsed

    return None


def repair_json_text(text: str) -> str | None:
    """Modelin bozduğu JSON benzeri çıktıyı mümkünse JSON nesnesine onarır."""
    candidate = (text or "").strip()
    if not candidate:
        return None
    # Aşırı iç içe/uzun payload'larda parse denemelerini erken durdur.
    if not is_safe_literal_eval_candidate(candidate):
        logger.debug("JSON onarımı atlandı: aday metin güvenli sınırları aşıyor.")
        return None

    budget = _RepairBudget()
    parsed = _repair_json_candidate(candidate, budget=budget)
    if parsed is not None:
        return parsed

    return _literal_eval_dict_fallback(candidate, budget=budget)


def _literal_eval_dict_fallback(
    candidate: str, *, budget: _RepairBudget | None = None
) -> str | None:
    if budget is not None and not budget.consume():
        return None
    try:
        obj = ast.literal_eval(candidate)
        if isinstance(obj, dict):
            return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None
    return None


async def repair_json_text_async(text: str) -> str | None:
    """Asenkron akışlarda literal_eval fallback'ini worker thread'e taşıyan sürüm."""
    candidate = (text or "").strip()
    if not candidate:
        return None
    if not is_safe_literal_eval_candidate(candidate):
        logger.debug("JSON onarımı atlandı: aday metin güvenli sınırları aşıyor.")
        return None

    budget = _RepairBudget()
    parsed = _repair_json_candidate(candidate, budget=budget)
    if parsed is not None:
        return parsed

    return await asyncio.to_thread(_literal_eval_dict_fallback, candidate, budget=budget)
