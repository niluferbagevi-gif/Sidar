"""Tests for the read-only open pull request hygiene inventory."""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.audit_open_pull_requests import analyze, render_markdown


def _pull(number: int, head: str, paths: list[str], updated: str = "2026-08-01T00:00:00Z"):
    return {
        "number": number,
        "title": f"PR {number}",
        "html_url": f"https://example.test/pull/{number}",
        "head": {"ref": head},
        "updated_at": updated,
        "changed_paths": paths,
    }


def test_analyze_finds_duplicate_sets_hotspots_and_automation_families() -> None:
    pulls = [
        _pull(1, "claude/review-a", ["run_tests.sh", "a.py"]),
        _pull(2, "codex/review-b", ["a.py", "run_tests.sh"]),
        _pull(3, "feature/manual", ["a.py"], "2026-06-01T00:00:00Z"),
    ]

    report = analyze(pulls, datetime(2026, 8, 9, tzinfo=UTC))

    assert report["open_count"] == 3
    assert report["automation_count"] == 2
    assert report["duplicate_file_set_groups"] == [[1, 2]]
    assert report["overlap_paths"][0] == {"path": "a.py", "pull_requests": [1, 2, 3], "count": 3}
    assert report["pull_requests"][0]["hotspots"] == ["run_tests.sh"]
    assert report["pull_requests"][0]["risk_score"] > 0


def test_markdown_makes_manual_close_policy_explicit() -> None:
    report = analyze([_pull(7, "dependabot/npm", ["uv.lock"])], datetime(2026, 8, 9, tzinfo=UTC))

    markdown = render_markdown(report)

    assert "this audit never mutates GitHub state" in markdown
    assert "[#7](https://example.test/pull/7)" in markdown
    assert "`uv.lock`" in markdown
