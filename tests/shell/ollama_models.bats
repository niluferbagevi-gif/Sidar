#!/usr/bin/env bats

# Coverage for scripts/install_modules/utils/ollama_models.sh. This module is on
# the local-runtime critical path (phases/06_services.sh calls it), so a
# regression here breaks the first-install experience.

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

# Run a snippet inside a fully-sourced installer environment so the helper
# functions defined by install_sidar.sh (read_env_value_from_file,
# resolve_ollama_version_url, is_local_ollama_url, prompt_*) are available, and
# so ollama_models.sh has been loaded by sidar_source_install_utils.
run_ollama_snippet() {
  local snippet="$1"
  local root
  root="$(repo_root)"
  run bash -c '
    set -Eeuo pipefail
    repo_root="$1"
    test_snippet="$2"
    cd "$repo_root"
    export SIDAR_INSTALL_TEST_MODE=1
    set --
    source ./install_sidar.sh
    eval "$test_snippet"
  ' _ "$root" "$snippet"
}

@test "sidar_ollama_model_exists_in_tags matches exact, :latest fallback and rejects unknown" {
  run_ollama_snippet '
    payload='\''{"models":[{"name":"llama3.1:8b"},{"name":"qwen2.5-coder:7b"},{"name":"nomic-embed-text:latest"}]}'\''
    sidar_ollama_model_exists_in_tags "$payload" "llama3.1:8b"
    sidar_ollama_model_exists_in_tags "$payload" "qwen2.5-coder:7b"
    # Tag-less query should also match the :latest variant that ollama serve advertises.
    sidar_ollama_model_exists_in_tags "$payload" "nomic-embed-text"
    if sidar_ollama_model_exists_in_tags "$payload" "phi3:mini"; then
      echo "phi3:mini should not have matched"
      exit 1
    fi
    if sidar_ollama_model_exists_in_tags "" "llama3.1:8b"; then
      echo "empty payload should not match"
      exit 1
    fi
    if sidar_ollama_model_exists_in_tags "$payload" ""; then
      echo "empty model name should not match"
      exit 1
    fi
    if sidar_ollama_model_exists_in_tags "not-json" "llama3.1:8b"; then
      echo "malformed payload should not match"
      exit 1
    fi
  '
  [ "$status" -eq 0 ]
}

@test "sidar_ollama_count_models_from_tags counts entries with a non-empty name" {
  run_ollama_snippet '
    payload='\''{"models":[{"name":"a"},{"name":"b"},{"name":""},{"foo":"bar"}]}'\''
    [[ "$(sidar_ollama_count_models_from_tags "$payload")" == "2" ]]
    [[ "$(sidar_ollama_count_models_from_tags "{}")" == "0" ]]
    [[ "$(sidar_ollama_count_models_from_tags "not-json")" == "0" ]]
  '
  [ "$status" -eq 0 ]
}

@test "download_ollama_models exits early and warns when WSL .wslconfig was just changed" {
  run_ollama_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"

    warn_msgs=""
    info_msgs=""
    pull_invocations=""
    step(){ :; }
    info(){ info_msgs+="$*"$"\n"; }
    warn(){ warn_msgs+="$*"$"\n"; }
    ok(){ :; }
    fail(){ echo "FAIL:$*"; exit 99; }
    ollama(){ pull_invocations+="$*"$"\n"; }
    curl(){ return 1; }

    WSL2=true
    WSLCONFIG_CHANGED=true
    SKIP_MODELS=false
    NO_INTERACTION=true
    DOWNLOAD_MODELS=false

    download_ollama_models
    [[ "$warn_msgs" == *"WSL2 .wslconfig bu kurulumda güncellendi"* ]]
    [[ "$info_msgs" == *"--download-models"* ]]
    [[ -z "$pull_invocations" ]]
  '
  [ "$status" -eq 0 ]
}

@test "download_ollama_models warns and returns cleanly when .env is missing" {
  run_ollama_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"

    warn_msgs=""
    pull_invocations=""
    step(){ :; }
    info(){ :; }
    warn(){ warn_msgs+="$*"$"\n"; }
    ok(){ :; }
    fail(){ echo "FAIL:$*"; exit 99; }
    resolve_ollama_version_url(){ echo "http://127.0.0.1:11434/api/version"; }
    is_local_ollama_url(){ return 0; }
    ollama(){ pull_invocations+="$*"$"\n"; }
    # No ollama binary available - command -v ollama will fail because of the
    # function definition above. Override curl so version probe also fails.
    curl(){ return 1; }
    run_coding_model_smoke_prompt(){ :; }

    WSL2=false
    WSLCONFIG_CHANGED=false
    SKIP_MODELS=false
    NO_INTERACTION=true
    DOWNLOAD_MODELS=false

    download_ollama_models
    [[ "$warn_msgs" == *".env bulunamadı"* ]]
    [[ -z "$pull_invocations" ]]
  '
  [ "$status" -eq 0 ]
}

@test "download_ollama_models falls back to qwen2.5-coder:7b when CODING_MODEL is empty" {
  run_ollama_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    cat > "$tmpdir/.env" <<EOF
TEXT_MODEL=llama3.1:8b
CODING_MODEL=
VISION_MODEL=
ENABLE_MULTIMODAL=false
EOF

    warn_msgs=""
    info_msgs=""
    pull_invocations=""
    step(){ :; }
    info(){ info_msgs+="$*"$"\n"; }
    warn(){ warn_msgs+="$*"$"\n"; }
    ok(){ :; }
    fail(){ echo "FAIL:$*"; exit 99; }
    resolve_ollama_version_url(){ echo "http://127.0.0.1:11434/api/version"; }
    is_local_ollama_url(){ return 0; }
    # Ollama binary is present so the missing-model probe runs through, but no
    # network: curl returns empty so the tags branch is skipped and the
    # downstream skip-or-prompt logic decides whether to pull.
    ollama(){ pull_invocations+="$*"$"\n"; }
    curl(){ return 1; }
    run_coding_model_smoke_prompt(){ :; }

    WSL2=false
    WSLCONFIG_CHANGED=false
    SKIP_MODELS=false
    NO_INTERACTION=true
    DOWNLOAD_MODELS=false

    download_ollama_models
    [[ "$warn_msgs" == *"CODING_MODEL boş/geçersiz görünüyor"* ]]
    [[ "$warn_msgs" == *"qwen2.5-coder:7b"* ]]
    # NO_INTERACTION + !DOWNLOAD_MODELS keeps us from pulling anything during the
    # fallback path.
    [[ -z "$pull_invocations" ]]
  '
  [ "$status" -eq 0 ]
}

@test "download_ollama_models skips download when NO_INTERACTION=true and --download-models not supplied" {
  run_ollama_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    cat > "$tmpdir/.env" <<EOF
TEXT_MODEL=llama3.1:8b
CODING_MODEL=qwen2.5-coder:7b
VISION_MODEL=
ENABLE_MULTIMODAL=false
EOF

    info_msgs=""
    warn_msgs=""
    pull_invocations=""
    step(){ :; }
    info(){ info_msgs+="$*"$"\n"; }
    warn(){ warn_msgs+="$*"$"\n"; }
    ok(){ :; }
    fail(){ echo "FAIL:$*"; exit 99; }
    resolve_ollama_version_url(){ echo "http://127.0.0.1:11434/api/version"; }
    is_local_ollama_url(){ return 0; }
    # ollama binary is present (function shim) so command -v ollama succeeds.
    ollama(){ pull_invocations+="$*"$"\n"; }
    # Tags unreachable - mirrors the CI/headless case where the Ollama daemon
    # is not running yet. download_ollama_models should then fall through to
    # the prompt block and honour NO_INTERACTION=true by skipping pulls.
    curl(){ return 1; }
    run_coding_model_smoke_prompt(){ :; }

    WSL2=false
    WSLCONFIG_CHANGED=false
    SKIP_MODELS=false
    NO_INTERACTION=true
    DOWNLOAD_MODELS=false

    download_ollama_models
    [[ "$info_msgs" == *"--ci/--no-interaction etkin"* ]]
    [[ "$info_msgs" == *"--download-models"* ]]
    [[ -z "$pull_invocations" ]]
  '
  [ "$status" -eq 0 ]
}
