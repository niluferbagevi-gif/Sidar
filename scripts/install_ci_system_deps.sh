#!/usr/bin/env bash
set -euo pipefail

# Install OS-level packages required by Python deps in CI/local Linux hosts.
# Keeping this in a script provides environment parity between developer machines
# and GitHub Actions.

PACKAGES=(portaudio19-dev)

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer currently supports Debian/Ubuntu hosts (apt-get required)." >&2
  exit 1
fi

if dpkg-query -W -f='${Status}' "${PACKAGES[@]}" 2>/dev/null | grep -q "ok installed"; then
  echo "System dependencies already installed: ${PACKAGES[*]}"
  exit 0
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
${SUDO} DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${PACKAGES[@]}"
