#!/usr/bin/env bash
# Validate the repository-level GPU evidence policy after the hardware job finishes.

set -euo pipefail

gate_enabled="${GPU_GATE_ENABLED:-}"
gate_result="${GPU_GATE_RESULT:-}"

# Best-effort: mirror the actionable parts of an ::error:: annotation into the
# job's Summary tab too. Annotations are easy to miss (collapsed under "View
# details", truncated in the PR checks list); the Summary tab is the first
# thing a reviewer sees and survives copy/paste better than a log line. A
# missing/false ENABLE_GPU_BENCH_GATE is a repo-admin control-plane gap, not
# something the PR author can fix by pushing code, so it gets called out
# explicitly instead of just repeating the annotation text. No-op outside
# GitHub Actions (e.g. under the unit tests in
# tests/unit/scripts/test_check_gpu_evidence.py) since GITHUB_STEP_SUMMARY is
# unset there.
summarize() {
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    { printf '%s\n' "$@"; } >>"$GITHUB_STEP_SUMMARY"
  fi
}

if [[ "$gate_enabled" != "true" && "$gate_enabled" != "false" ]]; then
  echo "::error title=Invalid GPU evidence policy::Repository variable ENABLE_GPU_BENCH_GATE must be an explicit boolean (true or false); current value='${gate_enabled:-<empty>}'." >&2
  summarize \
    "### ❌ GPU Inference Required Evidence Gate: repository not configured" \
    "" \
    "\`ENABLE_GPU_BENCH_GATE\` is unset or not an explicit boolean (current value: \`${gate_enabled:-<empty>}\`)." \
    "This is a **repository admin action**, not something fixable from this PR's diff." \
    "" \
    "1. GitHub → Settings → Secrets and variables → Actions → Variables → set \`ENABLE_GPU_BENCH_GATE\` = \`true\`" \
    "   (\`false\` is also rejected — this repo's release policy has no non-release exemption, see below)." \
    "2. Provision/confirm an online \`[self-hosted, linux, x64, gpu, cuda]\` runner." \
    "" \
    "See [\`docs/runbooks/gpu-runner-continuity.md\`](../../docs/runbooks/gpu-runner-continuity.md) for the exact \`gh variable set\` command and runner failover procedure."
  exit 1
fi

if [[ "$gate_enabled" == "false" ]]; then
  echo "::error title=GPU inference evidence disabled::ENABLE_GPU_BENCH_GATE=false is a syntactically valid boolean (unlike an unset or non-boolean value, which fails the check above), but this repository's merge/release policy requires GPU TTFT/latency evidence unconditionally — there is no non-release exemption. Set ENABLE_GPU_BENCH_GATE=true and provision an eligible self-hosted GPU runner (see docs/runbooks/gpu-runner-continuity.md)." >&2
  summarize \
    "### ❌ GPU Inference Required Evidence Gate: evidence disabled" \
    "" \
    "\`ENABLE_GPU_BENCH_GATE=false\` is syntactically valid but is not accepted: this repository's" \
    "merge/release policy requires GPU TTFT/latency evidence unconditionally, with no" \
    "non-release exemption. This is a **repository admin action**, not something fixable from" \
    "this PR's diff — set \`ENABLE_GPU_BENCH_GATE=true\` (GitHub → Settings → Secrets and" \
    "variables → Actions → Variables) and provision an eligible self-hosted GPU runner." \
    "" \
    "See [\`docs/runbooks/gpu-runner-continuity.md\`](../../docs/runbooks/gpu-runner-continuity.md)."
  exit 1
fi

if [[ "$gate_result" != "success" ]]; then
  echo "::error title=GPU inference gate failed::gpu-inference-quality-gate result=${gate_result:-<empty>}; expected success." >&2
  summarize \
    "### ❌ GPU Inference Required Evidence Gate: benchmark job did not pass" \
    "" \
    "\`gpu-inference-quality-gate\` result=\`${gate_result:-<empty>}\` (expected \`success\`)." \
    "\`ENABLE_GPU_BENCH_GATE=true\` is set correctly; this is a real TTFT/latency result (or" \
    "runner availability) failure from the hardware job itself — see its logs above, not a" \
    "control-plane configuration gap."
  exit 1
fi

echo "GPU inference TTFT/latency evidence is present and passing."
summarize "### ✅ GPU Inference Required Evidence Gate: passing" "" "GPU inference TTFT/latency evidence is present and passing."
