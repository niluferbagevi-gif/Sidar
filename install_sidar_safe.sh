#!/usr/bin/env bash
# Sidar safe installer wrapper
# This script fetches the original install_sidar.sh from the main branch,
# applies a safe sudo keep-alive fix for Ollama installation, and executes it.
# It avoids long-lived `while true` loops that can race with other sudo commands.

set -euo pipefail

# Download the original installer script from the main branch
ORIGINAL_URL="https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/main/install_sidar.sh"
echo "Downloading original installer from $ORIGINAL_URL"
original_script=$(curl -fsSL "$ORIGINAL_URL")

# Define a function to apply the sudo keep-alive fix.
# This uses sed to replace the specific keep-alive loop with a more defensive implementation.
apply_sudo_fix() {
  echo "$1" | sed -E \
    -e '/\(\s*while\s+true;\s*do\s*$/,/^\s*\)\s*\&\s*$/ {
        /sudo -n -v/ {
          # Replace the whole keep-alive loop with the defensive implementation
          c\
          # Refresh sudo timestamp once before background keep‑alive\n          sudo -v\n          (\n            # Keep sudo timestamp alive only while the parent process runs\n            while kill -0 $$ 2>/dev/null; do\n              sudo -n true 2>/dev/null\n              sleep 30\n            done\n          ) &\n          SUDO_KEEP_ALIVE_PID=$!\n          # Optional: log the keep-alive PID\n          info "Sudo timestamp keep-alive running (pid=${SUDO_KEEP_ALIVE_PID})."
        }
      }'
}

patched_script=$(apply_sudo_fix "$original_script")

# Execute the patched installer script
bash -s <<< "$patched_script"
