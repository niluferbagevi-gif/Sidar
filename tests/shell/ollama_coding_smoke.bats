#!/usr/bin/env bats

# Coverage for run_coding_model_smoke_prompt() in
# scripts/install_modules/phases/09_ollama_models.sh.
#
# Field report: on a borderline ~8 GiB VRAM card (RTX 3070 Ti Laptop), the
# `/api/generate` JSON smoke test failed with HTTP 500 (GPU VRAM OOM) at the
# default auto-tuned num_ctx, and the installer's auto-heal safely stopped
# after seeing the same failure signature twice. These tests cover the
# self-heal path added in response: on a VRAM-pressure-shaped failure, retry
# once with a reduced num_ctx/num_batch and, if that succeeds, persist the
# working values to .env instead of repeating the same failure.

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

# Mirrors run_ollama_snippet() in ollama_models.bats: source the full
# installer under SIDAR_INSTALL_TEST_MODE=1 so run_coding_model_smoke_prompt
# (phases/09_ollama_models.sh) and its utils/database_url.sh dependency
# (sidar_write_env_value) are all defined.
run_smoke_snippet() {
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

@test "run_coding_model_smoke_prompt succeeds outright on a healthy first attempt" {
  run_smoke_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    printf "OLLAMA_CODING_NUM_CTX=8192\nOLLAMA_NUM_BATCH=2048\n" > "$tmpdir/.env"

    step(){ :; }
    ok_msgs=""
    ok(){ ok_msgs+="$*"$"\n"; }
    info(){ :; }
    warn(){ :; }
    fail(){ echo "FAIL:$*"; exit 99; }

    curl(){
      # -o <file> -w %{http_code} ... write a 200 JSON body and print status.
      local out_file=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          -o) out_file="$2"; shift 2 ;;
          *) shift ;;
        esac
      done
      printf "%s" "{\"response\":\"{\\\"sidar_smoke\\\": true}\"}" > "$out_file"
      printf "200"
    }

    run_coding_model_smoke_prompt "qwen2.5-coder:7b" "http://localhost:11434"
    [[ "$ok_msgs" == *"başarılı"* ]]

    # No fallback needed: .env must be untouched.
    [[ "$(grep -c "^OLLAMA_CODING_NUM_CTX=" "$tmpdir/.env")" == "1" ]]
    grep -q "^OLLAMA_CODING_NUM_CTX=8192$" "$tmpdir/.env"
  '
  [ "$status" -eq 0 ]
}

@test "run_coding_model_smoke_prompt self-heals on HTTP 500 by retrying with a reduced context" {
  run_smoke_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    printf "OLLAMA_CODING_NUM_CTX=8192\nOLLAMA_NUM_BATCH=2048\n" > "$tmpdir/.env"

    step(){ :; }
    warn_msgs=""
    info_msgs=""
    ok_msgs=""
    warn(){ warn_msgs+="$*"$"\n"; }
    info(){ info_msgs+="$*"$"\n"; }
    ok(){ ok_msgs+="$*"$"\n"; }
    fail(){ echo "FAIL:$*"; exit 99; }

    # run_coding_model_smoke_prompt invokes _sidar_ollama_smoke_attempt via
    # $(...), a fresh subshell per attempt, so a plain shell variable
    # incremented inside curl() cannot survive across attempts. Use a file
    # as the call counter instead.
    curl_call_log="$tmpdir/curl_calls.log"
    : > "$curl_call_log"
    curl(){
      printf "x" >> "$curl_call_log"
      local call_number
      call_number=$(wc -c < "$curl_call_log")
      local out_file=""
      local payload_file=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          -o) out_file="$2"; shift 2 ;;
          --data-binary) payload_file="${2#@}"; shift 2 ;;
          *) shift ;;
        esac
      done
      if [[ "$call_number" -eq 1 ]]; then
        # Simulate a VRAM OOM: HTTP 500, empty/minimal body.
        grep -q "\"num_batch\": 2048" "$payload_file" || { echo "expected original num_batch=2048 in first attempt payload" >&2; return 9; }
        printf "%s" "{\"error\":\"an error was encountered while running the model\"}" > "$out_file"
        printf "500"
      else
        # Reduced-context retry succeeds. num_batch must be untouched: the
        # codebase deliberately does not scale num_batch down for VRAM (see
        # core/llm/ollama.py - shrinking it risks the llama.cpp
        # GGML_ASSERT(n_tokens_all <= cparams.n_batch) crash on long prompts
        # without actually reducing VRAM use, since ctx/KV-cache is what
        # drives that, not batch).
        grep -q "\"num_ctx\": 4096" "$payload_file" || { echo "expected reduced num_ctx=4096 in retry payload" >&2; return 9; }
        grep -q "\"num_batch\": 2048" "$payload_file" || { echo "expected num_batch to stay at 2048 (untouched) in retry payload" >&2; return 9; }
        printf "%s" "{\"response\":\"{\\\"sidar_smoke\\\": true}\"}" > "$out_file"
        printf "200"
      fi
    }

    run_coding_model_smoke_prompt "qwen2.5-coder:7b" "http://localhost:11434"

    [[ "$(wc -c < "$curl_call_log")" -eq 2 ]]
    [[ "$warn_msgs" == *"HTTP 500"* ]]
    [[ "$ok_msgs" == *"Düşük VRAM"* ]]

    # Only the working reduced ctx is persisted (so a re-run does not repeat
    # the same failure signature); num_batch is intentionally left alone.
    grep -q "^OLLAMA_CODING_NUM_CTX=4096$" "$tmpdir/.env"
    grep -q "^OLLAMA_NUM_BATCH=2048$" "$tmpdir/.env"
    [[ "$(grep -c "^OLLAMA_NUM_BATCH=" "$tmpdir/.env")" == "1" ]]
  '
  [ "$status" -eq 0 ]
}

@test "run_coding_model_smoke_prompt fails with actionable guidance when the reduced retry also fails" {
  run_smoke_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    printf "OLLAMA_CODING_NUM_CTX=8192\nOLLAMA_NUM_BATCH=2048\n" > "$tmpdir/.env"

    step(){ :; }
    info(){ :; }
    warn(){ :; }
    ok(){ :; }
    # The real fail() calls exit unconditionally, so any assertion placed
    # AFTER run_coding_model_smoke_prompt below would be dead code (the
    # process is gone before it runs, and the EXIT trap would delete
    # $tmpdir first anyway). Assert from inside the fail() mock instead,
    # before it exits, and fail with a distinct code (77) so an assertion
    # failure here is never confused with the expected exit 99.
    fail(){
      local msg="$*"
      [[ "$msg" == *"HTTP 500"* ]] || { echo "expected HTTP 500 in fail message: $msg" >&2; exit 77; }
      [[ "$msg" == *"OLLAMA_CODING_NUM_CTX=2048"* ]] || { echo "expected remediation hint in fail message: $msg" >&2; exit 77; }
      # .env must NOT have been rewritten on a failed retry.
      grep -q "^OLLAMA_CODING_NUM_CTX=8192$" "$tmpdir/.env" || { echo ".env was unexpectedly rewritten" >&2; exit 77; }
      echo "FAIL:$*"
      exit 99
    }

    curl(){
      local out_file=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          -o) out_file="$2"; shift 2 ;;
          *) shift ;;
        esac
      done
      printf "%s" "{\"error\":\"cuda error: out of memory\"}" > "$out_file"
      printf "500"
    }

    run_coding_model_smoke_prompt "qwen2.5-coder:7b" "http://localhost:11434"
  '
  [ "$status" -eq 99 ]
}

@test "run_coding_model_smoke_prompt does not retry a non-VRAM failure (e.g. 404 unknown model)" {
  run_smoke_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    printf "OLLAMA_CODING_NUM_CTX=8192\nOLLAMA_NUM_BATCH=2048\n" > "$tmpdir/.env"

    step(){ :; }
    info(){ :; }
    warn(){ :; }
    ok(){ :; }
    # See the comment in the "reduced retry also fails" test above: assert
    # from inside fail() itself, since the real fail() exits unconditionally
    # and would otherwise skip any check placed after the call below.
    curl_call_log="$tmpdir/curl_calls.log"
    : > "$curl_call_log"
    fail(){
      local msg="$*"
      [[ "$(wc -c < "$curl_call_log")" -eq 1 ]] || { echo "expected exactly one curl call for a non-VRAM failure" >&2; exit 77; }
      [[ "$msg" == *"HTTP 404"* ]] || { echo "expected HTTP 404 in fail message: $msg" >&2; exit 77; }
      echo "FAIL:$*"
      exit 99
    }

    curl(){
      printf "x" >> "$curl_call_log"
      local out_file=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          -o) out_file="$2"; shift 2 ;;
          *) shift ;;
        esac
      done
      printf "%s" "{\"error\":\"model not found\"}" > "$out_file"
      printf "404"
    }

    run_coding_model_smoke_prompt "qwen2.5-coder:7b" "http://localhost:11434"
  '
  [ "$status" -eq 99 ]
}
