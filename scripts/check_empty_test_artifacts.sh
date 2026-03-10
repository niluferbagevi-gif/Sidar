#!/usr/bin/env bash
set -euo pipefail

empty_files=$(find tests -type f -size 0 -print)
if [[ -n "$empty_files" ]]; then
  echo "❌ Empty test artifact(s) found:"
  echo "$empty_files"
  exit 1
fi

echo "✅ No empty test artifacts found"
