#!/usr/bin/env bash
set -euo pipefail

# Install OS-level packages required by Python deps in CI/local Linux hosts.
# Keeping this in a script provides environment parity between developer machines
# and GitHub Actions.

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer currently supports Debian/Ubuntu hosts (apt-get required)." >&2
  exit 1
fi

SUDO=""
if [[ "${EUID}" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "Root privileges are required (run as root or install sudo)." >&2
    exit 1
  fi
fi

${SUDO} apt-get update
${SUDO} DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  portaudio19-dev
