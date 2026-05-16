#!/usr/bin/env bash
# Sidar installer phase: model provisioning
# shellcheck shell=bash

run_provision_models_phase() {
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    detect_gpu
    setup_env_file
    download_ollama_models
    ok "provision-models fazı tamamlandı."
}
