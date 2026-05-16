#!/usr/bin/env bash
# Sidar installer phase: doctor and subcommand dispatch
# shellcheck shell=bash

run_doctor_phase() {
    step "Sidar Doctor"
    cd "$SCRIPT_DIR"
    mkdir -p artifacts/install
    local -a doctor_cmd=()
    if command -v uv &>/dev/null; then
        doctor_cmd=(uv run python -m core.doctor artifacts/install/doctor.json)
    elif command -v python3 &>/dev/null; then
        doctor_cmd=(python3 -m core.doctor artifacts/install/doctor.json)
    else
        fail "Doctor çalıştırmak için python3 veya uv bulunamadı."
    fi

    if "${doctor_cmd[@]}"; then
        ok "Doctor raporu üretildi: artifacts/install/doctor.json"
    else
        warn "Doctor raporu üretildi ancak bir veya daha fazla kontrol fail durumunda. Rapor: artifacts/install/doctor.json"
        return 1
    fi
}

prepare_offline_mode_if_needed() {
    if [[ "$OFFLINE_MODE" != true ]]; then
        return
    fi

    OFFLINE_PACKAGES_DIR="$(resolve_offline_packages_dir || true)"
    if [[ -n "$OFFLINE_PACKAGES_DIR" ]]; then
        info "Çevrimdışı/air-gapped mod etkin. Paket kaynağı: $OFFLINE_PACKAGES_DIR"
        verify_offline_bundle_manifest "$OFFLINE_PACKAGES_DIR"
    else
        fail "Çevrimdışı mod etkin ancak offline_packages dizini bulunamadı."
    fi
}

run_install_subcommand_if_requested() {
    case "$INSTALL_SUBCOMMAND" in
        full) return 1 ;;
        doctor)
            run_doctor_phase
            return 0
            ;;
        prepare-system)
            run_prepare_system_phase
            return 0
            ;;
        sync-deps)
            run_sync_deps_phase
            return 0
            ;;
        provision-models)
            run_provision_models_phase
            return 0
            ;;
        smoke)
            run_smoke_phase
            return 0
            ;;
    esac
    return 1
}
