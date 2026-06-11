#!/usr/bin/env bash
# Stable compatibility alias for the Sidar installer 03_runtime phase.
_sidar_install_alias_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../scripts/install_modules/phases/03_runtime.sh
source "${_sidar_install_alias_root}/scripts/install_modules/phases/03_runtime.sh"
