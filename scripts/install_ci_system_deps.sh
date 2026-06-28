#!/usr/bin/env bash
set -euo pipefail

# Install OS-level packages required by Python deps in CI/local hosts.
# Keeping this in a script provides environment parity between developer machines
# and GitHub Actions. Use --check to report missing packages without installing.
#
# Optional Docker-based test flow:
#   - Build project image: docker build -t sidar:latest .
#   - Set DOCKER_TEST_IMAGE=sidar:latest so CodeManager runs pytest/mypy in the
#     project image where uv/pytest/mypy toolchain is available.
#   - Or opt into quality-gate image preparation with:
#     AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=sidar:latest bash run_tests.sh

CHECK_ONLY=false
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=true
  shift
fi
if [[ "$#" -gt 0 ]]; then
  echo "Usage: $0 [--check]" >&2
  exit 2
fi

PACKAGES=(portaudio19-dev shellcheck bats)
MANAGER=""
SUDO=()
MISSING_PACKAGES=()

if command -v apt-get >/dev/null 2>&1; then
  MANAGER="apt"
  PACKAGES=(portaudio19-dev shellcheck bats)
elif command -v dnf >/dev/null 2>&1; then
  MANAGER="dnf"
  PACKAGES=(portaudio-devel ShellCheck bats)
elif command -v zypper >/dev/null 2>&1; then
  MANAGER="zypper"
  PACKAGES=(portaudio-devel ShellCheck bats)
elif command -v pacman >/dev/null 2>&1; then
  MANAGER="pacman"
  PACKAGES=(portaudio shellcheck bats)
elif command -v brew >/dev/null 2>&1; then
  MANAGER="brew"
  PACKAGES=(portaudio shellcheck bats-core)
else
  echo "Supported package manager not found (apt-get, dnf, zypper, pacman, or brew required)." >&2
  exit 1
fi

package_installed() {
  local package="$1"
  case "$MANAGER" in
    apt) dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "ok installed" ;;
    dnf|zypper) rpm -q "$package" >/dev/null 2>&1 ;;
    pacman) pacman -Qi "$package" >/dev/null 2>&1 ;;
    brew) brew list --versions "$package" >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}

for package in "${PACKAGES[@]}"; do
  if ! package_installed "$package"; then
    MISSING_PACKAGES+=("$package")
  fi
done

if [[ "${#MISSING_PACKAGES[@]}" -eq 0 ]]; then
  echo "System dependencies already installed for ${MANAGER}: ${PACKAGES[*]}"
  exit 0
fi

if [[ "$CHECK_ONLY" == true ]]; then
  echo "Missing system dependencies for ${MANAGER}: ${MISSING_PACKAGES[*]}" >&2
  exit 1
fi

if [[ "$MANAGER" != "brew" && "${EUID}" -ne 0 ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Root privileges are required (run as root or install sudo)." >&2
    exit 1
  fi
  if ! sudo -n true >/dev/null 2>&1; then
    echo "Passwordless or cached sudo is required for non-interactive installation. Run 'sudo -v' first, run as root, or configure sudo -n access." >&2
    exit 1
  fi
  SUDO=(sudo -n)
fi

case "$MANAGER" in
  apt)
    "${SUDO[@]}" apt-get update
    "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${MISSING_PACKAGES[@]}"
    ;;
  dnf)
    "${SUDO[@]}" dnf install -y "${MISSING_PACKAGES[@]}"
    ;;
  zypper)
    "${SUDO[@]}" zypper --non-interactive install --no-recommends "${MISSING_PACKAGES[@]}"
    ;;
  pacman)
    "${SUDO[@]}" pacman -Sy --needed --noconfirm "${MISSING_PACKAGES[@]}"
    ;;
  brew)
    brew install "${MISSING_PACKAGES[@]}"
    ;;
esac

if command -v docker >/dev/null 2>&1; then
  echo "Docker detected. Recommended CI/runtime setting: DOCKER_TEST_IMAGE=sidar:latest"
  echo "Optional quality-gate preparation: AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=sidar:latest bash run_tests.sh"
else
  echo "Docker CLI not found; skip Docker image guidance in this environment."
fi
