"""``core.utils.json_repair`` modülü için unit testler."""

from __future__ import annotations

import pytest

from core.utils.json_repair import (
    MAX_JSON_REPAIR_ATTEMPTS,
    _json_dumps_if_valid,
    _RepairBudget,
    is_safe_literal_eval_candidate,
    repair_json_text,
    repair_json_text_async,
)


def test_json_decoder_attempts_are_bounded_before_late_payload() -> None:
    """Json decoder attempts are bounded before late payload."""
    payload = " ".join("{" for _ in range(MAX_JSON_REPAIR_ATTEMPTS + 5)) + ' {"late": true}'
    budget = _RepairBudget()

    assert _json_dumps_if_valid(payload, budget=budget) is None
    assert budget.remaining == 0


def test_json_dumps_returns_none_when_repair_budget_starts_exhausted() -> None:
    """Json dumps returns none when repair budget starts exhausted."""
    budget = _RepairBudget(remaining=0)

    assert _json_dumps_if_valid('{"valid": true}', budget=budget) is None
    assert budget.remaining == 0


def test_repair_budget_prevents_literal_eval_after_parser_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repair budget prevents literal eval after parser budget is exhausted."""
    calls = []
    monkeypatch.setattr(
        "core.utils.json_repair.ast.literal_eval",
        lambda value: calls.append(value) or {"unexpected": True},
    )

    budget = _RepairBudget(remaining=0)
    from core.utils.json_repair import _literal_eval_dict_fallback

    assert _literal_eval_dict_fallback("{'k': 'v'}", budget=budget) is None
    assert calls == []


def test_is_safe_literal_eval_candidate_handles_escaped_quotes() -> None:
    """Is safe literal eval candidate handles escaped quotes."""
    payload = r'{"key": "kacisli \\\" veri", "single": "it\\\'s fine"}'

    assert is_safe_literal_eval_candidate(payload) is True


def test_repair_json_text_uses_loose_fence_fallback_without_newlines() -> None:
    """Repair json text uses loose fence fallback without newlines."""
    payload = 'prefix ```json {"tool":"final_answer","argument":"ok","thought":"t"} ``` suffix'

    repaired = repair_json_text(payload)

    assert repaired == '{"tool": "final_answer", "argument": "ok", "thought": "t"}'


def test_repair_json_text_uses_loose_fence_fallback_for_non_json_fence() -> None:
    """Repair json text uses loose fence fallback for non json fence."""
    payload = '```{"value":1,"nested":{"k":"v"}}```'

    repaired = repair_json_text(payload)

    assert repaired == '{"value": 1, "nested": {"k": "v"}}'


def test_repair_json_text_skips_empty_strict_fence_then_parses_next_strict_fence() -> None:
    """Repair json text skips empty strict fence then parses next strict fence."""
    payload = '```json\n\n```\n```json\n"ok"\n```'

    repaired = repair_json_text(payload)

    assert repaired == '"ok"'


def test_repair_json_text_uses_strict_fence_after_decoder_cannot_parse() -> None:
    """Repair json text uses strict fence after decoder cannot parse."""
    payload = '```json\n"strict-fence"\n```'

    repaired = repair_json_text(payload)

    assert repaired == '"strict-fence"'


def test_repair_json_text_uses_loose_fence_after_decoder_cannot_parse() -> None:
    """Repair json text uses loose fence after decoder cannot parse."""
    payload = 'prefix ```json "loose-fence"``` suffix'

    repaired = repair_json_text(payload)

    assert repaired == '"loose-fence"'


def test_repair_json_text_skips_invalid_loose_fence_then_parses_next_loose_fence() -> None:
    """Repair json text skips invalid loose fence then parses next loose fence."""
    payload = '```json {not-valid} ``` trailing ```json {"ok":true} ```'

    repaired = repair_json_text(payload)

    assert repaired == '{"ok": true}'


def test_repair_json_text_skips_first_invalid_brace_then_parses_later_json_object() -> None:
    """Repair json text skips first invalid brace then parses later json object."""
    payload = 'Burada rastgele bir süslü parantez var { ama asıl JSON burada: {"anahtar": "deger"}'

    repaired = repair_json_text(payload)

    assert repaired == '{"anahtar": "deger"}'


def test_repair_json_text_continues_after_malformed_brace_prefix_then_parses_valid_json() -> None:
    """Repair json text continues after malformed brace prefix then parses valid json."""
    payload = (
        'Metin baslangici { bu bozuk kisim \n {"thought": "test", "tool": "x", "argument": "y"}'
    )

    repaired = repair_json_text(payload)

    assert repaired == '{"thought": "test", "tool": "x", "argument": "y"}'


def test_repair_json_text_returns_none_for_irreparable_malformed_json() -> None:
    """Repair json text returns none for irreparable malformed json."""
    payload = "prefix ```json {broken: [1,2,} ``` middle {still not valid"

    assert repair_json_text(payload) is None


def test_repair_json_text_skips_unicode_error_fence_then_parses_next_fence() -> None:
    """Repair json text skips unicode error fence then parses next fence."""
    payload = '```json\n"\\ud800"\n```\n```json\n{"ok": true}\n```'

    repaired = repair_json_text(payload)

    assert repaired == '{"ok": true}'


@pytest.mark.asyncio
async def test_repair_json_text_async_returns_none_for_empty_text() -> None:
    """Repair json text async returns none for empty text."""
    assert await repair_json_text_async("   ") is None


@pytest.mark.asyncio
async def test_repair_json_text_async_short_circuits_on_unsafe_candidate() -> None:
    """Repair json text async short circuits on unsafe candidate."""
    too_deep = "[" * 81 + "]" * 81

    assert await repair_json_text_async(too_deep) is None


@pytest.mark.asyncio
async def test_repair_json_text_async_repairs_valid_json_directly() -> None:
    """Repair json text async repairs valid json directly."""
    repaired = await repair_json_text_async('{"ok": true, "n": 1}')

    assert repaired == '{"ok": true, "n": 1}'


@pytest.mark.asyncio
async def test_repair_json_text_async_repairs_embedded_json_with_decoder() -> None:
    """Repair json text async repairs embedded json with decoder."""
    repaired = await repair_json_text_async('Ön metin: {"a": 1, "b": [2, 3]} son')

    assert repaired == '{"a": 1, "b": [2, 3]}'


@pytest.mark.asyncio
async def test_repair_json_text_async_repairs_fenced_json() -> None:
    """Repair json text async repairs fenced json."""
    repaired = await repair_json_text_async('```json\n{"x":1}\n```')

    assert repaired == '{"x": 1}'


@pytest.mark.asyncio
async def test_repair_json_text_async_repairs_loose_fence_without_newline() -> None:
    """Repair json text async repairs loose fence without newline."""
    repaired = await repair_json_text_async('```json {"x":1,"y":2} ```')

    assert repaired == '{"x": 1, "y": 2}'


@pytest.mark.asyncio
async def test_repair_json_text_async_skips_empty_strict_fence_then_parses_next_strict_fence() -> (
    None
):
    """Repair json text async skips empty strict fence then parses next strict fence."""
    payload = '```json\n\n```\n```json\n"ok"\n```'

    repaired = await repair_json_text_async(payload)

    assert repaired == '"ok"'


@pytest.mark.asyncio
async def test_repair_json_text_async_uses_strict_fence_after_decoder_cannot_parse() -> None:
    """Repair json text async uses strict fence after decoder cannot parse."""
    payload = '```json\n"strict-fence"\n```'

    repaired = await repair_json_text_async(payload)

    assert repaired == '"strict-fence"'


@pytest.mark.asyncio
async def test_repair_json_text_async_uses_loose_fence_after_decoder_cannot_parse() -> None:
    """Repair json text async uses loose fence after decoder cannot parse."""
    payload = 'prefix ```json "loose-fence"``` suffix'

    repaired = await repair_json_text_async(payload)

    assert repaired == '"loose-fence"'


@pytest.mark.asyncio
async def test_repair_json_text_async_skips_invalid_loose_fence_then_parses_next_loose_fence() -> (
    None
):
    """Repair json text async skips invalid loose fence then parses next loose fence."""
    payload = '```json {not-valid} ``` trailing ```json {"ok":true} ```'

    repaired = await repair_json_text_async(payload)

    assert repaired == '{"ok": true}'


@pytest.mark.asyncio
async def test_repair_json_text_async_skips_first_invalid_brace_then_parses_later_json_object() -> (
    None
):
    """Repair json text async skips first invalid brace then parses later json object."""
    payload = 'Burada rastgele bir süslü parantez var { ama asıl JSON burada: {"anahtar": "deger"}'

    repaired = await repair_json_text_async(payload)

    assert repaired == '{"anahtar": "deger"}'


@pytest.mark.asyncio
async def test_repair_json_text_async_continues_after_bad_brace_prefix_then_parses_json() -> None:
    """Repair json text async continues after bad brace prefix then parses json."""
    payload = (
        'Metin baslangici { bu bozuk kisim \n {"thought": "test", "tool": "x", "argument": "y"}'
    )

    repaired = await repair_json_text_async(payload)

    assert repaired == '{"thought": "test", "tool": "x", "argument": "y"}'


@pytest.mark.asyncio
async def test_repair_json_text_async_skips_unicode_error_fence_then_parses_next_fence() -> None:
    """Repair json text async skips unicode error fence then parses next fence."""
    payload = '```json\n"\\ud800"\n```\n```json\n{"ok": true}\n```'

    repaired = await repair_json_text_async(payload)

    assert repaired == '{"ok": true}'


@pytest.mark.asyncio
async def test_repair_json_text_async_uses_literal_eval_fallback_in_thread() -> None:
    """Repair json text async uses literal eval fallback in thread."""
    repaired = await repair_json_text_async("{'k': 'v', 'n': 2}")

    assert repaired == '{"k": "v", "n": 2}'


@pytest.mark.asyncio
async def test_repair_json_text_async_returns_none_when_literal_eval_not_dict() -> None:
    """Repair json text async returns none when literal eval not dict."""
    assert await repair_json_text_async("('not', 'dict')") is None
