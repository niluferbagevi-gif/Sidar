"""Tests for the CHANGELOG.md [Unreleased] entry word-budget checker."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci import check_changelog_entry_budget as checker


def _write_baseline(path: Path, maximum: object) -> None:
    path.write_text(json.dumps({"maximum_words_per_entry": maximum}), encoding="utf-8")


def test_unreleased_entries_only_collects_bullets_inside_the_section() -> None:
    text = "\n".join(
        [
            "# Sürüm Geçmişi",
            "",
            "## [Unreleased]",
            "",
            "### Düzeltmeler",
            "- **Short entry one:** fixed it.",
            "- **Short entry two:** fixed it too.",
            "not a bullet line",
            "",
            "## [v1.0.0] - 2026-01-01",
            "- **Should not be collected:** this is a released-version entry.",
        ]
    )

    entries = checker.unreleased_entries(text)

    assert [line for _, line in entries] == [
        "- **Short entry one:** fixed it.",
        "- **Short entry two:** fixed it too.",
    ]


def test_unreleased_entries_returns_empty_without_an_unreleased_section() -> None:
    text = "\n".join(["# Sürüm Geçmişi", "", "## [v1.0.0] - 2026-01-01", "- **Entry:** x."])

    assert checker.unreleased_entries(text) == []


def test_word_count_counts_whitespace_delimited_tokens() -> None:
    assert checker.word_count("- **Kısa madde:** iki kelime daha.") == 6


def test_budget_passes_when_every_entry_is_within_budget(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    target = tmp_path / "CHANGELOG.md"
    target.write_text(
        "\n".join(
            [
                "## [Unreleased]",
                "- **Kısa madde:** iki üç kelime.",
                "",
                "## [v1.0.0] - 2026-01-01",
            ]
        ),
        encoding="utf-8",
    )
    _write_baseline(baseline, 10)

    assert checker.main(["--target", str(target), "--baseline", str(baseline)]) == 0


def test_budget_fails_closed_when_an_entry_exceeds_the_word_budget(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    target = tmp_path / "CHANGELOG.md"
    long_entry = "- **" + " ".join(f"kelime{i}" for i in range(20)) + ":** detay."
    target.write_text(
        "\n".join(["## [Unreleased]", long_entry, "", "## [v1.0.0]"]), encoding="utf-8"
    )
    _write_baseline(baseline, 10)

    assert checker.main(["--target", str(target), "--baseline", str(baseline)]) == 1


def test_budget_rejects_missing_target_file(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, 10)

    assert (
        checker.main(["--target", str(tmp_path / "missing.md"), "--baseline", str(baseline)]) == 2
    )


def test_budget_rejects_missing_baseline_key(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}", encoding="utf-8")

    assert checker.main(["--baseline", str(baseline)]) == 2


def test_budget_rejects_invalid_json(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("not json", encoding="utf-8")

    assert checker.main(["--baseline", str(baseline)]) == 2


def test_budget_rejects_non_positive_maximum(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, 0)

    assert checker.main(["--baseline", str(baseline)]) == 2


def test_budget_rejects_bool_maximum(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, True)

    assert checker.main(["--baseline", str(baseline)]) == 2


def test_committed_changelog_unreleased_section_is_within_budget() -> None:
    """The real CHANGELOG.md must stay within its own committed budget."""
    assert checker.main([]) == 0
