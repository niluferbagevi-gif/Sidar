#!/usr/bin/env bash
# Sidar installer phase: local Python/uv dependency synchronization
# shellcheck shell=bash

run_sync_deps_phase() {
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    select_runtime_mode_early
    detect_gpu
    setup_uv
    setup_python_env
    install_python_deps
    install_pyright_lsp_tool
    verify_torch_cuda
    ok "sync-deps fazı tamamlandı."
}
