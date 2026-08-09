"""Build a read-only triage report for overlapping open pull requests."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HOTSPOTS = {"install_sidar.sh", "run_tests.sh", "uv.lock", "web_ui_react/package-lock.json"}
AUTOMATION_PREFIXES = ("claude/", "codex/", "dependabot/", "automation/")


def _github_json(url: str, token: str) -> Any:
    """Read one GitHub API JSON response using an optional workflow token."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "sidar-pr-audit"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        return json.load(response)


def fetch_open_prs(repository: str, token: str) -> list[dict[str, Any]]:
    """Fetch all open PRs and their changed paths from GitHub's API."""
    base = f"https://api.github.com/repos/{repository}"
    pulls: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _github_json(f"{base}/pulls?state=open&per_page=100&page={page}", token)
        if not isinstance(batch, list):
            raise ValueError("GitHub pull response must be a list")
        pulls.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    for pull in pulls:
        number = int(pull["number"])
        files: list[dict[str, Any]] = []
        file_page = 1
        while True:
            file_batch = _github_json(
                f"{base}/pulls/{number}/files?per_page=100&page={file_page}", token
            )
            if not isinstance(file_batch, list):
                raise ValueError("GitHub pull files response must be a list")
            files.extend(file_batch)
            if len(file_batch) < 100:
                break
            file_page += 1
        pull["changed_paths"] = sorted(
            str(item["filename"])
            for item in files
            if isinstance(item, dict) and item.get("filename")
        )
    return pulls


def analyze(pulls: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Group duplicate surfaces and rank high-conflict pull requests."""
    normalized: list[dict[str, Any]] = []
    path_to_prs: dict[str, list[int]] = defaultdict(list)
    signatures: dict[tuple[str, ...], list[int]] = defaultdict(list)
    branch_families: Counter[str] = Counter()

    for pull in pulls:
        paths = tuple(sorted(set(map(str, pull.get("changed_paths", [])))))
        number = int(pull["number"])
        head = str(pull.get("head", {}).get("ref", pull.get("head_ref", "")))
        updated = datetime.fromisoformat(str(pull["updated_at"]).replace("Z", "+00:00"))
        age_days = max(0, (now - updated).days)
        family = next(
            (
                prefix.rstrip("/")
                for prefix in AUTOMATION_PREFIXES
                if head.startswith(prefix)
            ),
            "human",
        )
        branch_families[family] += 1
        signatures[paths].append(number)
        for path in paths:
            path_to_prs[path].append(number)
        conflict_paths = sorted(path for path in paths if len(path_to_prs[path]) > 1)
        normalized.append(
            {
                "number": number,
                "title": str(pull.get("title", "")),
                "url": str(pull.get("html_url", pull.get("url", ""))),
                "head_ref": head,
                "family": family,
                "updated_at": str(pull["updated_at"]),
                "age_days": age_days,
                "changed_paths": list(paths),
                "conflict_paths": conflict_paths,
            }
        )

    # The first pass cannot know later path users, so calculate conflicts once globally.
    for pull in normalized:
        pull["conflict_paths"] = [
            path for path in pull["changed_paths"] if len(path_to_prs[path]) > 1
        ]
        pull["hotspots"] = sorted(set(pull["changed_paths"]) & HOTSPOTS)
        pull["risk_score"] = (
            len(pull["conflict_paths"])
            + 3 * len(pull["hotspots"])
            + (2 if pull["age_days"] >= 30 else 0)
        )

    duplicate_groups = [
        numbers for paths, numbers in signatures.items() if paths and len(numbers) > 1
    ]
    overlap_paths: list[dict[str, Any]] = [
        {"path": path, "pull_requests": numbers, "count": len(numbers)}
        for path, numbers in path_to_prs.items()
        if len(numbers) > 1
    ]
    overlap_paths.sort(key=lambda item: (-int(item["count"]), str(item["path"])))
    normalized.sort(key=lambda item: (-item["risk_score"], item["number"]))
    return {
        "generated_at": now.isoformat(),
        "open_count": len(normalized),
        "automation_count": sum(1 for pull in normalized if pull["family"] != "human"),
        "branch_families": dict(sorted(branch_families.items())),
        "duplicate_file_set_groups": sorted(duplicate_groups),
        "overlap_paths": overlap_paths,
        "pull_requests": normalized,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render an actionable, non-mutating PR hygiene report."""
    lines = [
        "# Open pull request hygiene report",
        "",
        f"- Open PRs: **{report['open_count']}**",
        f"- Automation-origin PRs: **{report['automation_count']}**",
        "- Exact changed-file-set duplicate groups: "
        f"**{len(report['duplicate_file_set_groups'])}**",
        "",
        "## Triage order",
        "",
        "1. Review exact changed-file-set groups; keep the newest valid implementation "
        "and close superseded PRs.",
        "2. Rebase and merge independent low-risk PRs in small batches.",
        "3. Serialize hotspot PRs; never batch changes to the same lockfile/installer/test gate.",
        "4. Close only after a maintainer confirms supersession; this audit never "
        "mutates GitHub state.",
        "",
        "## Exact changed-file-set groups",
        "",
    ]
    groups = report["duplicate_file_set_groups"]
    lines.extend(f"- {', '.join(f'#{number}' for number in group)}" for group in groups)
    if not groups:
        lines.append("- None")
    lines.extend(["", "## Highest-overlap paths", "", "| Path | Open PRs |", "|---|---:|"])
    for item in report["overlap_paths"][:25]:
        links = ", ".join(f"#{number}" for number in item["pull_requests"])
        lines.append(f"| `{item['path']}` | {links} |")
    lines.extend(
        [
            "",
            "## Highest-risk PRs",
            "",
            "| PR | Family | Score | Stale days | Hotspots |",
            "|---:|---|---:|---:|---|",
        ]
    )
    for pull in report["pull_requests"][:50]:
        hotspots = ", ".join(f"`{path}`" for path in pull["hotspots"]) or "—"
        lines.append(
            f"| [#{pull['number']}]({pull['url']}) | {pull['family']} | {pull['risk_score']} | "
            f"{pull['age_days']} | {hotspots} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    """Create JSON and Markdown artifacts from GitHub or a test fixture."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository", default=os.getenv("GITHUB_REPOSITORY", "niluferbagevi-gif/Sidar")
    )
    parser.add_argument("--input", type=Path, help="Read a captured PR fixture instead of GitHub")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/pr-hygiene"))
    parser.add_argument("--now", help="Deterministic ISO timestamp for tests")
    args = parser.parse_args()
    pulls = json.loads(args.input.read_text(encoding="utf-8")) if args.input else fetch_open_prs(
        args.repository, os.getenv("GITHUB_TOKEN", "")
    )
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    report = analyze(pulls, now)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    markdown = render_markdown(report)
    (args.output_dir / "report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
