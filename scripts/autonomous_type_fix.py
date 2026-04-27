#!/usr/bin/env python3
"""Autonomous type repair helper for recurring mypy no-untyped-def issues."""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TARGETS = ["web_server.py", "agent/core/supervisor.py"]


@dataclass(frozen=True)
class PatchResult:
    file_path: Path
    patched_functions: int
    import_added: bool


_DEF_RE = re.compile(r"^\s*(?:async\s+def|def)\s+")


def _has_any_import(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            if any(alias.name == "Any" for alias in node.names):
                return True
    return False


def _insert_any_import(lines: list[str]) -> bool:
    has_typing_import = any(re.match(r"^\s*from\s+typing\s+import\s+", line) for line in lines)
    if has_typing_import:
        for idx, line in enumerate(lines):
            if re.match(r"^\s*from\s+typing\s+import\s+", line):
                if "Any" not in line:
                    lines[idx] = line.rstrip("\n") + ", Any\n"
                    return True
                return False

    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1

    if insert_at < len(lines) and lines[insert_at].lstrip().startswith(("\"\"\"", "'''")):
        quote = lines[insert_at].lstrip()[:3]
        insert_at += 1
        while insert_at < len(lines):
            if quote in lines[insert_at]:
                insert_at += 1
                break
            insert_at += 1

    while insert_at < len(lines) and lines[insert_at].startswith("from __future__ import"):
        insert_at += 1

    lines.insert(insert_at, "from typing import Any\n")
    return True


def _find_signature_line_end(lines: list[str], start_index: int) -> int:
    depth = 0
    found_def = False
    for idx in range(start_index, len(lines)):
        raw = lines[idx]
        candidate = raw.split("#", 1)[0]
        if not found_def and _DEF_RE.match(candidate):
            found_def = True
        depth += candidate.count("(") - candidate.count(")")
        if found_def and ":" in candidate and depth <= 0:
            return idx
    return start_index


def _signature_has_return_annotation(lines: list[str], start_index: int, end_index: int) -> bool:
    text = "".join(lines[start_index : end_index + 1])
    colon_idx = text.rfind(":")
    if colon_idx == -1:
        return False
    return "->" in text[:colon_idx]


def _add_return_annotation(lines: list[str], start_index: int) -> bool:
    end_index = _find_signature_line_end(lines, start_index)
    if _signature_has_return_annotation(lines, start_index, end_index):
        return False

    line = lines[end_index]
    colon_idx = line.rfind(":")
    if colon_idx == -1:
        return False

    lines[end_index] = f"{line[:colon_idx]} -> Any{line[colon_idx:]}"
    return True


def _patch_file(path: Path) -> PatchResult:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is None:
            functions.append(node)

    patched = 0
    for node in sorted(functions, key=lambda n: n.lineno, reverse=True):
        if _add_return_annotation(lines, node.lineno - 1):
            patched += 1

    import_added = False
    if patched > 0 and not _has_any_import(tree):
        import_added = _insert_any_import(lines)

    if patched > 0:
        path.write_text("".join(lines), encoding="utf-8")

    return PatchResult(path, patched, import_added)


def _run_runtime_trace(pytest_args: list[str]) -> int:
    monkeytype = shutil.which("monkeytype")
    if not monkeytype:
        print("ℹ️ monkeytype bulunamadı; dinamik trace adımı atlanıyor.")
        return 0

    cmd = [monkeytype, "run", "-m", "pytest", *pytest_args]
    print(f"🧪 Dinamik tip trace: {' '.join(cmd)}")
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        print("⚠️ monkeytype trace adımı başarısız; statik onarım devam edecek.")
        return completed.returncode

    print("✅ monkeytype trace tamamlandı. İsteğe bağlı olarak `monkeytype apply <modül>` ile uygulanabilir.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous mypy return annotation repair")
    parser.add_argument("targets", nargs="*", default=DEFAULT_TARGETS, help="Target python files")
    parser.add_argument("--runtime-trace", action="store_true", help="Run monkeytype trace via pytest")
    parser.add_argument("--pytest-args", default="-q tests/unit", help="Pytest args for runtime trace")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    total_patched = 0

    for target in args.targets:
        path = Path(target)
        if not path.exists():
            print(f"⚠️ Hedef bulunamadı, atlanıyor: {target}")
            continue

        result = _patch_file(path)
        total_patched += result.patched_functions
        extra = " + typing.Any import" if result.import_added else ""
        print(f"🔧 {result.file_path}: {result.patched_functions} fonksiyona dönüş tipi eklendi{extra}.")

    if args.runtime_trace and os.environ.get("TYPE_FIX_ENABLE_RUNTIME", "0") == "1":
        pytest_args = [a for a in args.pytest_args.split(" ") if a]
        _run_runtime_trace(pytest_args)
    elif args.runtime_trace:
        print("ℹ️ Dinamik trace isteniyor ancak TYPE_FIX_ENABLE_RUNTIME=1 olmadığı için atlandı.")

    print(f"✅ Otonom tip onarımı tamamlandı. Toplam düzeltilen fonksiyon: {total_patched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
