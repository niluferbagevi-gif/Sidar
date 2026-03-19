#!/usr/bin/env bash
set -euo pipefail

root="${1:-.}"

python - "$root" <<'PY'
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
try:
    files = subprocess.check_output(['git', '-C', str(root), 'ls-files'], text=True).splitlines()
except subprocess.CalledProcessError:
    files = [str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '.git' not in p.parts]

py_files = [f for f in files if f.endswith('.py')]
md_files = [f for f in files if f.endswith('.md')]
test_files = [f for f in files if f.startswith('tests/test_') and f.endswith('.py')]
production_py = [f for f in py_files if not f.startswith('tests/')]

def line_count(rel_paths):
    total = 0
    for rel in rel_paths:
        with (root / rel).open(encoding='utf-8') as fh:
            total += sum(1 for _ in fh)
    return total

print(f'python_files={len(py_files)}')
print(f'markdown_files={len(md_files)}')
print(f'python_lines={line_count(py_files)}')
print(f'test_files={len(test_files)}')
print(f'production_python_files={len(production_py)}')
print(f'production_python_lines={line_count(production_py)}')
PY
