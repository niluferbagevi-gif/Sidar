from __future__ import annotations

import ast
import asyncio
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def is_safe_literal_eval_candidate(text: str, *, max_len: int = 20000, max_depth: int = 80) -> bool:
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


def repair_json_text(text: str) -> Optional[str]:
    """Modelin bozduğu JSON benzeri çıktıyı mümkünse JSON nesnesine onarır."""
    candidate = (text or "").strip()
    if not candidate:
        return None
    # Aşırı iç içe/uzun payload'larda parse denemelerini erken durdur.
    if not is_safe_literal_eval_candidate(candidate):
        logger.debug("JSON onarımı atlandı: aday metin güvenli sınırları aşıyor.")
        return None

    def _json_dumps_if_valid(raw: str) -> Optional[str]:
        normalized = (raw or "").strip()
        if not normalized:
            return None
        try:
            obj = json.loads(normalized)
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            pass

        # En baştaki geçerli JSON nesnesini yakalamak için decoder tabanlı onarım.
        decoder = json.JSONDecoder()
        for i, ch in enumerate(normalized):
            if ch not in "{[":
                continue
            try:
                obj, _ = decoder.raw_decode(normalized[i:])
                return json.dumps(obj, ensure_ascii=False)
            except Exception:
                continue
        return None

    parsed = _json_dumps_if_valid(candidate)
    if parsed is not None:
        return parsed

    # Çoklu fenced markdown çıktılarında her bloğu sırayla dene.
    for fenced in re.finditer(
        r"(?ms)```(?:json)?[ \t]*\n(.*?)\n```",
        candidate,
        flags=re.IGNORECASE,
    ):
        parsed = _json_dumps_if_valid(fenced.group(1))
        if parsed is not None:
            return parsed

    # Satır sonu olmadan gelen fenced varyantları için gevşek fallback.
    for fenced in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", candidate, flags=re.IGNORECASE):
        parsed = _json_dumps_if_valid(fenced.group(1))
        if parsed is not None:
            return parsed

    return _literal_eval_dict_fallback(candidate)


def _literal_eval_dict_fallback(candidate: str) -> Optional[str]:
    try:
        obj = ast.literal_eval(candidate)
        if isinstance(obj, dict):
            return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None
    return None


async def repair_json_text_async(text: str) -> Optional[str]:
    """Asenkron akışlarda literal_eval fallback'ini worker thread'e taşıyan sürüm."""
    candidate = (text or "").strip()
    if not candidate:
        return None
    if not is_safe_literal_eval_candidate(candidate):
        logger.debug("JSON onarımı atlandı: aday metin güvenli sınırları aşıyor.")
        return None

    def _json_dumps_if_valid(raw: str) -> Optional[str]:
        normalized = (raw or "").strip()
        if not normalized:
            return None
        try:
            obj = json.loads(normalized)
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            pass

        decoder = json.JSONDecoder()
        for i, ch in enumerate(normalized):
            if ch not in "{[":
                continue
            try:
                obj, _ = decoder.raw_decode(normalized[i:])
                return json.dumps(obj, ensure_ascii=False)
            except Exception:
                continue
        return None

    parsed = _json_dumps_if_valid(candidate)
    if parsed is not None:
        return parsed

    for fenced in re.finditer(
        r"(?ms)```(?:json)?[ \t]*\n(.*?)\n```",
        candidate,
        flags=re.IGNORECASE,
    ):
        parsed = _json_dumps_if_valid(fenced.group(1))
        if parsed is not None:
            return parsed

    for fenced in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", candidate, flags=re.IGNORECASE):
        parsed = _json_dumps_if_valid(fenced.group(1))
        if parsed is not None:
            return parsed

    return await asyncio.to_thread(_literal_eval_dict_fallback, candidate)
