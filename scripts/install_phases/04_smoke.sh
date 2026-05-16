#!/usr/bin/env bash
# Sidar installer phase: migration, smoke and audit checks
# shellcheck shell=bash

run_smoke_phase() {
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    detect_gpu
    prepare_docker_for_migrations
    run_migrations
    run_smoke_tests
    run_test_artifact_audit
    run_doctor_phase || true
    ok "smoke fazı tamamlandı."
}
