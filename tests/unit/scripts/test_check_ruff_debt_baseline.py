"""Tests for the Ruff docstring and ASYNC240 debt baseline checker."""

from __future__ import annotations

from scripts.ci import check_ruff_debt_baseline as checker


def test_count_diagnostics_fills_missing_debt_codes_with_zero() -> None:
    """Diagnostic counts include every tracked code even when Ruff omits a rule."""
    counts = checker._count_diagnostics(
        [
            {"code": "D200"},
            {"code": "D200"},
            {"code": "ASYNC240"},
            {"code": "F401"},
        ]
    )

    assert counts["D200"] == 2
    assert counts["ASYNC240"] == 1
    assert counts["D417"] == 0
    assert "F401" not in counts


def test_format_counts_uses_stable_campaign_code_order() -> None:
    """Formatted CI output keeps the campaign rule order deterministic."""
    rendered = checker._format_counts({"E501": 4, "D200": 1, "D202": 2, "ASYNC240": 3})

    assert rendered.startswith("E501=4, D200=1, D202=2, D205=0")
    assert rendered.endswith("D417=0, ASYNC240=3")
