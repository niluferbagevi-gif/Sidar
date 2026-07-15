"""Pure reviewer judging and prompt helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping


def coerce_review_approved(raw_approved: object) -> bool:
    """Safely coerce LLM reviewer approval variants into a bool."""

    if isinstance(raw_approved, bool):
        return raw_approved
    if isinstance(raw_approved, int | float):
        return bool(raw_approved)
    approved_text = str(raw_approved or "").strip().lower()
    if approved_text in {"true", "yes", "evet", "approved", "approve", "1"}:
        return True
    if approved_text in {"false", "no", "hayır", "hayir", "rejected", "reject", "0"}:
        return False
    return False


def coerce_review_weaknesses(raw_weaknesses: object) -> list[str]:
    """Normalize LLM reviewer weakness signals into a visible string list."""

    if isinstance(raw_weaknesses, list):
        return [str(item).strip() for item in raw_weaknesses if str(item).strip()]
    weakness_text = str(raw_weaknesses or "").strip()
    return [weakness_text] if weakness_text else []


def derive_review_weaknesses_from_reason(reason: str | None) -> list[str]:
    """Use a concrete rejection reason as a fallback weakness signal."""

    normalized = " ".join(str(reason or "").split())
    if not normalized:
        return []
    return [normalized[:240]]


def normalize_test_candidate_verdict(verdict: object) -> dict[str, object]:
    """Reduce direct or tool-wrapped reviewer JSON into the verdict contract."""

    if not isinstance(verdict, dict):
        return {}

    verdict_keys = {"approved", "reason", "weaknesses"}
    if verdict_keys & set(verdict):
        return verdict

    tool_name = str(verdict.get("tool") or "").strip().lower()
    argument = verdict.get("argument")
    if tool_name == "json" or argument is not None:
        if isinstance(argument, str):
            try:
                parsed_argument = json.loads(argument)
            except json.JSONDecodeError:
                return verdict
            if isinstance(parsed_argument, dict) and verdict_keys & set(parsed_argument):
                return parsed_argument
        elif isinstance(argument, dict) and verdict_keys & set(argument):
            return argument

    return verdict


def candidate_preview(candidate: str, *, max_lines: int = 3) -> str:
    """Build a compact one-line preview for reviewer-gate logging."""

    lines = [line.rstrip() for line in str(candidate or "").splitlines()[:max_lines]]
    return " | ".join(line for line in lines if line.strip())[:500] or "<empty>"


def build_test_candidate_review_prompt(
    candidate: str,
    finding: Mapping[str, object],
    *,
    shared_test_fixture_guidance: str,
    retry: bool = False,
) -> str:
    """Build the JSON-constrained semantic reviewer prompt for a coverage test candidate."""

    retry_clause = (
        "\nÖNEMLİ: Önceki reviewer çıktısı geçersizdi çünkü approved=false iken reason boştu. "
        "Bu tekrar değerlendirmesinde red veriyorsan reason alanını mutlaka somut, "
        "insan-okunur en az bir cümleyle doldur; weaknesses alanına 1-2 sinyal ekle. "
        if retry
        else ""
    )
    return (
        "Aşağıdaki pytest test önerisini anlamsal kalite açısından incele. "
        "Özellikle 'assert True' gibi anlamsız assertion, zayıf doğrulama, "
        "yan etkili/deterministik olmayan kullanım, eksik exception path'i veya "
        "tautolojik mock kontrolü var mı değerlendir. "
        "Yanıt yalnızca ve yalnızca şu şemada tek JSON nesnesi olmalı; markdown, "
        "thought/tool/argument sarmalı veya ek anahtar kullanma: "
        '{"approved": bool, "reason": str (red ise mutlaka somut neden, '
        'en az 1 cümle), "weaknesses": [str]}. '
        f"{shared_test_fixture_guidance} "
        f"{retry_clause}\n\n"
        f"[COVERAGE_FINDING]\n{json.dumps(dict(finding), ensure_ascii=False)}\n\n"
        f"[TEST_CANDIDATE]\n{str(candidate or '')[:6000]}"
    )
