#!/usr/bin/env bash
set -Eeuo pipefail

# Repository provenance reporting for installer logs. Keep Git inspection out of
# install_sidar.sh so the entrypoint remains an orchestration facade.
sidar_report_install_source_metadata() {
    local repo_dir="${1:-${SCRIPT_DIR:-.}}"
    local version="${INSTALL_SIDAR_VERSION:-0.0.0}"
    local branch="unavailable"
    local commit="unavailable"
    local dirty="unknown"
    local git_output=""

    if command -v git >/dev/null 2>&1 && git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git_output="$(git -C "$repo_dir" branch --show-current 2>/dev/null || true)"
        if [[ -n "$git_output" ]]; then
            branch="$git_output"
        else
            branch="detached"
        fi

        git_output="$(git -C "$repo_dir" rev-parse HEAD 2>/dev/null || true)"
        if [[ "$git_output" =~ ^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$ ]]; then
            commit="$git_output"
        fi

        git_output="$(git -C "$repo_dir" status --porcelain --untracked-files=normal 2>/dev/null || true)"
        if [[ -n "$git_output" ]]; then
            dirty="true"
        else
            dirty="false"
        fi
    fi

    printf 'Sidar version : %s\n' "$version"
    printf 'Git branch    : %s\n' "$branch"
    printf 'Git commit    : %s\n' "$commit"
    printf 'Git dirty     : %s\n' "$dirty"
}
