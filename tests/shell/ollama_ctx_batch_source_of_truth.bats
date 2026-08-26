#!/usr/bin/env bats

# Coverage for the num_ctx/num_batch resolution in
# scripts/install_modules/utils/ollama_models.sh
# (sidar_ollama_runtime_num_ctx, sidar_ollama_runtime_num_batch,
# sidar_ollama_python_effective_ctx_batch).
#
# Review bulgusu (b): the installer used to read only the .env file's
# OLLAMA_NUM_CTX/OLLAMA_NUM_BATCH (fixed 8192/2048 in the shipped example
# files) - a source completely independent of config.py's
# OLLAMA_CODING_NUM_CTX VRAM auto-tune, which is what
# core/llm/ollama.py's real chat() call actually uses at runtime. These
# tests cover the fix: an explicit .env override still wins, but the
# "unset" default now asks Python for the value production will actually
# use instead of falling straight to an independent, possibly-stale bash
# constant.

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

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
    # sidar_ollama_runtime_num_ctx/_num_batch deliberately check the process
    # environment before falling back to the target .env file (real 12-factor
    # override behavior) - so if the calling shell already has these exported
    # (e.g. install_sidar.sh itself exports them earlier in the very same
    # run via sidar_ollama_export_runtime_defaults(), and this bats file
    # then runs as a child process of that run - see "CI Tam Doğrulama" /
    # `make dev-full` at the end of install_sidar.sh), every fixture below
    # would be silently shadowed by that leaked value instead of exercising
    # the tmpdir/.env this test actually constructs. Force a clean slate so
    # these tests are hermetic regardless of caller.
    unset OLLAMA_NUM_CTX OLLAMA_NUM_BATCH OLLAMA_CODING_NUM_CTX
    eval "$test_snippet"
  ' _ "$root" "$snippet"
}

@test "sidar_ollama_runtime_num_ctx/_num_batch prefer an explicit .env override and never invoke uv" {
  run_ollama_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    printf "OLLAMA_NUM_CTX=16384\nOLLAMA_NUM_BATCH=1024\n" > "$tmpdir/.env"

    # If the resolver consults Python at all here, it is a bug: an explicit
    # override must short-circuit before uv is ever invoked.
    command(){
      if [[ "$1" == "-v" && "$2" == "uv" ]]; then
        echo "uv should not be probed when .env has an explicit override" >&2
        exit 1
      fi
      builtin command "$@"
    }

    [[ "$(sidar_ollama_runtime_num_ctx "$tmpdir/.env")" == "16384" ]]
    [[ "$(sidar_ollama_runtime_num_batch "$tmpdir/.env")" == "1024" ]]
  '
  [ "$status" -eq 0 ]
}

@test "sidar_ollama_runtime_num_ctx/_num_batch consult the Python-computed value when .env is blank" {
  run_ollama_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    printf "OLLAMA_NUM_CTX=\nOLLAMA_NUM_BATCH=\nOLLAMA_CODING_NUM_CTX=\n" > "$tmpdir/.env"

    # Simulate config.py auto-tuning ctx down to 4096 for an edge-case VRAM
    # card, and OLLAMA_BATCH_POLICY resolving batch to 2048.
    uv(){
      if [[ "$1" == "run" && "$2" == "python" ]]; then
        printf "4096\n2048\n"
        return 0
      fi
      return 1
    }

    [[ "$(sidar_ollama_runtime_num_ctx "$tmpdir/.env")" == "4096" ]]
    [[ "$(sidar_ollama_runtime_num_batch "$tmpdir/.env")" == "2048" ]]
  '
  [ "$status" -eq 0 ]
}

@test "sidar_ollama_runtime_num_batch accepts a Python-computed 0 as a valid auto-batch result" {
  run_ollama_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    printf "OLLAMA_NUM_CTX=\nOLLAMA_NUM_BATCH=\nOLLAMA_CODING_NUM_CTX=\n" > "$tmpdir/.env"

    # config_llm.OLLAMA_BATCH_POLICY.auto_batch_for_context() legitimately
    # returns 0 at the context floor (meaning "omit num_batch, let Ollama
    # use its own default") - this must NOT be treated as "Python failed".
    uv(){
      if [[ "$1" == "run" && "$2" == "python" ]]; then
        printf "2048\n0\n"
        return 0
      fi
      return 1
    }

    [[ "$(sidar_ollama_runtime_num_ctx "$tmpdir/.env")" == "2048" ]]
    [[ "$(sidar_ollama_runtime_num_batch "$tmpdir/.env")" == "0" ]]
  '
  [ "$status" -eq 0 ]
}

@test "sidar_ollama_runtime_num_ctx/_num_batch fall back to bash defaults when uv is unavailable" {
  run_ollama_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    printf "OLLAMA_NUM_CTX=\nOLLAMA_NUM_BATCH=\nOLLAMA_CODING_NUM_CTX=\n" > "$tmpdir/.env"

    command(){
      if [[ "$1" == "-v" && "$2" == "uv" ]]; then
        return 1
      fi
      builtin command "$@"
    }

    [[ "$(sidar_ollama_runtime_num_ctx "$tmpdir/.env")" == "$SIDAR_OLLAMA_DEFAULT_NUM_CTX" ]]
    [[ "$(sidar_ollama_runtime_num_batch "$tmpdir/.env")" == "$SIDAR_OLLAMA_DEFAULT_NUM_BATCH" ]]
  '
  [ "$status" -eq 0 ]
}

@test "sidar_ollama_runtime_num_ctx/_num_batch fall back to bash defaults when the Python probe fails" {
  run_ollama_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    printf "OLLAMA_NUM_CTX=\nOLLAMA_NUM_BATCH=\nOLLAMA_CODING_NUM_CTX=\n" > "$tmpdir/.env"

    # uv is on PATH but the Python import/computation itself fails (e.g. a
    # broken venv) - must fail closed to the old bash constants, not crash
    # the installer.
    uv(){ return 1; }

    [[ "$(sidar_ollama_runtime_num_ctx "$tmpdir/.env")" == "$SIDAR_OLLAMA_DEFAULT_NUM_CTX" ]]
    [[ "$(sidar_ollama_runtime_num_batch "$tmpdir/.env")" == "$SIDAR_OLLAMA_DEFAULT_NUM_BATCH" ]]
  '
  [ "$status" -eq 0 ]
}

@test "an explicit OLLAMA_CODING_NUM_CTX override is honored by the ctx resolver without invoking uv" {
  run_ollama_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    printf "OLLAMA_CODING_NUM_CTX=12288\n" > "$tmpdir/.env"

    command(){
      if [[ "$1" == "-v" && "$2" == "uv" ]]; then
        echo "uv should not be probed when OLLAMA_CODING_NUM_CTX is explicit" >&2
        exit 1
      fi
      builtin command "$@"
    }

    [[ "$(sidar_ollama_runtime_num_ctx "$tmpdir/.env")" == "12288" ]]
  '
  [ "$status" -eq 0 ]
}

@test "sidar_ollama_python_effective_ctx_batch prints exactly two clean digit lines against the real config.py" {
  command -v uv &>/dev/null || skip "uv not available in this environment"

  # Regression coverage for a real bug the mocked tests above cannot catch:
  # config.py imports core.config_logging_setup at import time, which points
  # the root logger at sys.stdout - a plain "import config" used to print an
  # INFO banner line to STDOUT ahead of the two print()s this function's
  # callers parse positionally, corrupting the result. This runs the actual
  # function against the real repo (no uv/curl mocking) and asserts stdout
  # is exactly two lines of digits, nothing else.
  run_ollama_snippet '
    output="$(sidar_ollama_python_effective_ctx_batch "$SCRIPT_DIR/.env" 2>/tmp/sidar_ctx_batch_stderr.$$)" || {
      echo "sidar_ollama_python_effective_ctx_batch failed (uv/python/config.py issue?)" >&2
      cat /tmp/sidar_ctx_batch_stderr.$$ >&2
      rm -f /tmp/sidar_ctx_batch_stderr.$$
      exit 1
    }
    rm -f /tmp/sidar_ctx_batch_stderr.$$

    line_count="$(printf "%s\n" "$output" | wc -l)"
    [[ "$line_count" -eq 2 ]] || { echo "expected exactly 2 lines, got $line_count: $output" >&2; exit 1; }

    ctx_line="$(printf "%s\n" "$output" | sed -n 1p)"
    batch_line="$(printf "%s\n" "$output" | sed -n 2p)"
    [[ "$ctx_line" =~ ^[0-9]+$ ]] || { echo "line 1 is not a plain digit string: $ctx_line" >&2; exit 1; }
    [[ "$batch_line" =~ ^[0-9]+$ ]] || { echo "line 2 is not a plain digit string: $batch_line" >&2; exit 1; }
  '
  [ "$status" -eq 0 ]
}
