#!/usr/bin/env bash

extract_node_major_from_spec() {
    local version_spec="${1:-}"
    local extracted_major=""
    extracted_major="$(echo "$version_spec" | tr -d '[:space:]' | grep -oE '[0-9]+' | head -n1 || true)"
    if [[ "$extracted_major" =~ ^[0-9]+$ ]]; then
        echo "$extracted_major"
        return 0
    fi
    return 1
}

resolve_target_node_major() {
    local default_major="20"
    local nvmrc_path=""
    local nvmrc_spec=""
    local major=""
    local package_path=""
    local engines_node_spec=""

    for nvmrc_path in "$SCRIPT_DIR/.nvmrc" "$SCRIPT_DIR/web_ui_react/.nvmrc"; do
        if [[ -f "$nvmrc_path" ]]; then
            nvmrc_spec="$(sed -e 's/[[:space:]]*#.*$//' -e '/^[[:space:]]*$/d' "$nvmrc_path" | head -n1 || true)"
            major="$(extract_node_major_from_spec "$nvmrc_spec" || true)"
            if [[ -n "$major" ]]; then
                info "Hedef Node.js sürümü .nvmrc dosyasından algılandı: ${major}.x (${nvmrc_path})"
                echo "$major"
                return 0
            fi
        fi
    done

    for package_path in "$SCRIPT_DIR/package.json" "$SCRIPT_DIR/web_ui_react/package.json"; do
        if [[ -f "$package_path" ]]; then
            engines_node_spec="$(sed -n 's/.*"node"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$package_path" | head -n1 || true)"
            major="$(extract_node_major_from_spec "$engines_node_spec" || true)"
            if [[ -n "$major" ]]; then
                info "Hedef Node.js sürümü package.json engines.node alanından algılandı: ${major}.x (${package_path})"
                echo "$major"
                return 0
            fi
        fi
    done

    info ".nvmrc veya package.json engines.node bulunamadı; Node.js için varsayılan hedef sürüm kullanılacak: ${default_major}.x"
    echo "$default_major"
}

resolve_offline_packages_dir() {
    local -a candidates=(
        "${SCRIPT_DIR}/${OFFLINE_PACKAGES_DIR_DEFAULT_NAME}"
        "${ORIGINAL_SCRIPT_DIR}/${OFFLINE_PACKAGES_DIR_DEFAULT_NAME}"
        "${TARGET_DIR}/${OFFLINE_PACKAGES_DIR_DEFAULT_NAME}"
    )
    local candidate=""
    for candidate in "${candidates[@]}"; do
        if [[ -d "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

resolve_offline_package_file() {
    local relative_path="$1"
    local -a candidate_dirs=()
    local candidate_dir=""

    if [[ -n "${OFFLINE_PACKAGES_DIR:-}" && -d "${OFFLINE_PACKAGES_DIR:-}" ]]; then
        candidate_dirs+=("$OFFLINE_PACKAGES_DIR")
    fi

    while IFS= read -r candidate_dir; do
        [[ -n "$candidate_dir" ]] && candidate_dirs+=("$candidate_dir")
    done < <(resolve_offline_packages_dir || true)

    for candidate_dir in "${candidate_dirs[@]}"; do
        if [[ -f "${candidate_dir}/${relative_path}" ]]; then
            echo "${candidate_dir}/${relative_path}"
            return 0
        fi
    done
    return 1
}
