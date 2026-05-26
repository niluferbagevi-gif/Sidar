#!/usr/bin/env bash
set -euo pipefail

# Install OS-level packages required by Python deps in CI/local Linux hosts.
# Keeping this in a script provides environment parity between developer machines
# and GitHub Actions.
#
# Optional Docker-based test flow:
#   - Build project image: docker build -t sidar:latest .
#   - Set DOCKER_TEST_IMAGE=sidar:latest so CodeManager runs pytest/mypy in the
#     project image where uv/pytest/mypy toolchain is available.

PACKAGES=(portaudio19-dev shellcheck bats)

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer currently supports Debian/Ubuntu hosts (apt-get required)." >&2
  exit 1
fi

MISSING_PACKAGES=()
for package in "${PACKAGES[@]}"; do
  if ! dpkg-query -W -f='${Status}' "${package}" 2>/dev/null | grep -q "ok installed"; then
    MISSING_PACKAGES+=("${package}")
  fi
done

if [[ "${#MISSING_PACKAGES[@]}" -eq 0 ]]; then
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
${SUDO} env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${MISSING_PACKAGES[@]}"

if command -v docker >/dev/null 2>&1; then
  echo "Docker detected. Recommended CI/runtime setting: DOCKER_TEST_IMAGE=sidar:latest"
else
  echo "Docker CLI not found; skip Docker image guidance in this environment."
fi
