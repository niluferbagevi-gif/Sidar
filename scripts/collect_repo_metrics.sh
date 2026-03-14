#!/usr/bin/env bash
# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

set -euo pipefail

root="${1:-.}"

py_files=$(find "$root" -type f -name "*.py" | wc -l | tr -d ' ')
md_files=$(find "$root" -type f -name "*.md" | wc -l | tr -d ' ')
py_lines=$(find "$root" -type f -name "*.py" -print0 | xargs -0 cat | wc -l | tr -d ' ')
test_files=$(find "$root/tests" -type f -name "test_*.py" 2>/dev/null | wc -l | tr -d ' ')

echo "python_files=$py_files"
echo "markdown_files=$md_files"
echo "python_lines=$py_lines"
echo "test_files=$test_files"