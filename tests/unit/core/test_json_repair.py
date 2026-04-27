from __future__ import annotations

import pytest

from core.utils.json_repair import (
    is_safe_literal_eval_candidate,
    repair_json_text,
    repair_json_text_async,
)


def test_is_safe_literal_eval_candidate_handles_escaped_quotes() -> None:
    payload = r'{"key": "kacisli \\\" veri", "single": "it\\\'s fine"}'

    assert is_safe_literal_eval_candidate(payload) is True


def test_repair_json_text_uses_loose_fence_fallback_without_newlines() -> None:
    payload = 'prefix ```json {"tool":"final_answer","argument":"ok","thought":"t"} ``` suffix'

    repaired = repair_json_text(payload)

    assert repaired == '{"tool": "final_answer", "argument": "ok", "thought": "t"}'


def test_repair_json_text_uses_loose_fence_fallback_for_non_json_fence() -> None:
    payload = '```{"value":1,"nested":{"k":"v"}}```'

    repaired = repair_json_text(payload)

    assert repaired == '{"value": 1, "nested": {"k": "v"}}'


@pytest.mark.asyncio
async def test_repair_json_text_async_returns_none_for_empty_text() -> None:
    assert await repair_json_text_async("   ") is None


@pytest.mark.asyncio
async def test_repair_json_text_async_short_circuits_on_unsafe_candidate() -> None:
    too_deep = "[" * 81 + "]" * 81

    assert await repair_json_text_async(too_deep) is None


@pytest.mark.asyncio
async def test_repair_json_text_async_repairs_valid_json_directly() -> None:
    repaired = await repair_json_text_async('{"ok": true, "n": 1}')

    assert repaired == '{"ok": true, "n": 1}'


@pytest.mark.asyncio
async def test_repair_json_text_async_repairs_embedded_json_with_decoder() -> None:
    repaired = await repair_json_text_async('Ön metin: {"a": 1, "b": [2, 3]} son')

    assert repaired == '{"a": 1, "b": [2, 3]}'


@pytest.mark.asyncio
async def test_repair_json_text_async_repairs_fenced_json() -> None:
    repaired = await repair_json_text_async('```json\n{"x":1}\n```')

    assert repaired == '{"x": 1}'


@pytest.mark.asyncio
async def test_repair_json_text_async_repairs_loose_fence_without_newline() -> None:
    repaired = await repair_json_text_async('```json {"x":1,"y":2} ```')

    assert repaired == '{"x": 1, "y": 2}'


@pytest.mark.asyncio
async def test_repair_json_text_async_uses_literal_eval_fallback_in_thread() -> None:
    repaired = await repair_json_text_async("{'k': 'v', 'n': 2}")

    assert repaired == '{"k": "v", "n": 2}'


@pytest.mark.asyncio
async def test_repair_json_text_async_returns_none_when_literal_eval_not_dict() -> None:
    assert await repair_json_text_async("('not', 'dict')") is None
