#!/usr/bin/env bash
# Validate the repository-level GPU evidence policy after the hardware job finishes.

set -euo pipefail

gate_enabled="${GPU_GATE_ENABLED:-}"
gate_result="${GPU_GATE_RESULT:-}"

if [[ "$gate_enabled" != "true" && "$gate_enabled" != "false" ]]; then
  echo "::error title=Invalid GPU evidence policy::Repository variable ENABLE_GPU_BENCH_GATE must be an explicit boolean (true or false); current value='${gate_enabled:-<empty>}'." >&2
  exit 1
fi

if [[ "$gate_enabled" == "false" ]]; then
  echo "::error title=GPU inference evidence disabled::ENABLE_GPU_BENCH_GATE=false is a syntactically valid boolean (unlike an unset or non-boolean value, which fails the check above), but this repository's merge/release policy requires GPU TTFT/latency evidence unconditionally — there is no non-release exemption. Set ENABLE_GPU_BENCH_GATE=true and provision an eligible self-hosted GPU runner (see docs/runbooks/gpu-runner-continuity.md)." >&2
  exit 1
fi

if [[ "$gate_result" != "success" ]]; then
  echo "::error title=GPU inference gate failed::gpu-inference-quality-gate result=${gate_result:-<empty>}; expected success." >&2
  exit 1
fi

echo "GPU inference TTFT/latency evidence is present and passing."
