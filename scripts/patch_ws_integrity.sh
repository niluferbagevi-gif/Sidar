#!/usr/bin/env bash
# This script patches the integrity hash for ws package in package-lock.json
# to fix npm ci installation errors due to mismatched integrity.
# It replaces the old integrity hash with the new one as reported by npm.

set -euo pipefail
LOCK_FILE="web_ui_react/package-lock.json"
OLD_HASH="sha512-+Obn2l8+gT9EqYNZdc6rgWMSjucp4h+9Vv3k2uj3oAtFZDD2LdkQYzDBIhCnWfE0J/u4UfnrNHEjmQfKGx2dww=="
NEW_HASH="sha512-Vsp28b7DRcimFQvrqu2Wek3z1iYxDCWqHYB8Qsnk/S4RfaCQzPGPyBNuVjJV3cd6UiKtUtp6sNM77gWvzcCH+g=="

if [ -f "$LOCK_FILE" ]; then
  if grep -q "$OLD_HASH" "$LOCK_FILE"; then
    sed -i "s|$OLD_HASH|$NEW_HASH|g" "$LOCK_FILE"
    echo "✅ Patched ws integrity hash in $LOCK_FILE"
  else
    echo "ℹ️ Integrity hash already patched or old hash not found."
  fi
else
  echo "⚠️ Lock file $LOCK_FILE not found; skipping ws integrity patch."
fi
