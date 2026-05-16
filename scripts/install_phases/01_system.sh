#!/usr/bin/env bash
# Sidar installer phase: system and repository preparation
# shellcheck shell=bash

run_prepare_system_phase() {
    install_system_dependencies
    sync_repo
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    select_runtime_mode_early
    detect_gpu
    setup_nvidia_docker
    create_directories
    setup_env_file
    ok "prepare-system fazı tamamlandı."
}
