"""Reject unresolved debt markers in production source comments."""

from __future__ import annotations

import argparse
import io
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ("agent", "core", "managers", "web", "web_ui_react/src")
PYTHON_SUFFIXES = {".py"}
WEB_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}
DEBT_MARKER = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)

# This comment describes TodoManager's scanner rather than deferred work.
ALLOWED_COMMENTS = {
    ("managers/todo_manager.py", "TODO veya FIXME kelimesini içeren satırları yakala"),
}


@dataclass(frozen=True)
class Finding:
    """A debt marker found in a production source comment."""

    path: str
    line: int
    comment: str


def _python_comments(path: Path) -> list[tuple[int, str]]:
    """Return Python comments without matching strings or docstrings."""
    source = path.read_bytes()
    return [
        (token.start[0], token.string.removeprefix("#").strip())
        for token in tokenize.tokenize(io.BytesIO(source).readline)
        if token.type == tokenize.COMMENT
    ]


def _web_comments(path: Path) -> list[tuple[int, str]]:
    """Return JavaScript/TypeScript comments with their starting line."""
    source = path.read_text(encoding="utf-8")
    comments: list[tuple[int, str]] = []
    for match in re.finditer(r"//[^\r\n]*|/\*[\s\S]*?\*/", source):
        comment = match.group(0)
        content = comment[2:-2] if comment.startswith("/*") else comment[2:]
        comments.append((source.count("\n", 0, match.start()) + 1, content.strip()))
    return comments


def find_debt_markers(root: Path = ROOT) -> list[Finding]:
    """Find non-allowlisted debt markers in configured production roots."""
    findings: list[Finding] = []
    for source_root in SOURCE_ROOTS:
        directory = root / source_root
        if not directory.is_dir():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            if path.suffix in PYTHON_SUFFIXES:
                comments = _python_comments(path)
            elif path.suffix in WEB_SUFFIXES:
                comments = _web_comments(path)
            else:
                continue
            relative = path.relative_to(root).as_posix()
            for line, comment in comments:
                if not DEBT_MARKER.search(comment):
                    continue
                if (relative, comment) in ALLOWED_COMMENTS:
                    continue
                findings.append(Finding(relative, line, comment))
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run the production-source debt marker quality gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root to scan.")
    args = parser.parse_args(argv)

    findings = find_debt_markers(args.root.resolve())
    if findings:
        print("Unresolved production-source debt markers found:", file=sys.stderr)
        for finding in findings:
            print(
                f"- {finding.path}:{finding.line}: {finding.comment}",
                file=sys.stderr,
            )
        return 1
    print("Production-source debt marker gate passed (TODO/FIXME/HACK/XXX: 0).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
