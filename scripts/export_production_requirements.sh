#!/usr/bin/env bash
set -euo pipefail

# Export Sidar's production dependency lock into a requirements.txt-compatible
# artifact without installing development/test extras. The default output path
# is intentionally generated (not hand-maintained) to keep uv.lock authoritative.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_FILE="${1:-${REPO_ROOT}/requirements-production.txt}"

cd "${REPO_ROOT}"

uv export \
  --frozen \
  --extra production \
  --no-dev \
  --no-editable \
  --no-emit-project \
  --format requirements.txt \
  --output-file "${OUTPUT_FILE}"

printf 'Production requirements exported to %s\n' "${OUTPUT_FILE}"
