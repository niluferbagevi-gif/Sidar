# CI Required Checks

## Main branch required status checks

GitHub branch protection / rulesets are the source of truth for required PR
checks. They are configured in GitHub repository settings, not in this file, but
the expected required contexts should mirror the release-critical jobs in
`.github/workflows/ci.yml`:

| Workflow job id | Required GitHub check name | Why it must be required |
| --- | --- | --- |
| `test` | `CI / Base quality gates (lint, smoke, unit, coverage, frontend)` | Runs broad non-performance checks on GitHub-hosted infrastructure; performance is deliberately isolated in `benchmark-compare`. |
| `installer-smoke` | `CI / Installer manifest and smoke gate` | Prevents raw installer, embedded manifest, module hash, and installer smoke drift from merging unnoticed. |
| `production-profile-dry-run` | `CI / Production-minimal runtime validation` | Release-blocking production-minimal gate: installer sync, FastAPI web boot smoke, Alembic DB migration smoke, and uploaded runtime evidence artifact. |
| `gpu-inference-policy-gate` | `CI / GPU Inference Required Evidence Gate` | Fails closed unless the self-hosted GPU TTFT/latency benchmark is enabled and succeeds. |
| `production-readiness` | `CI / Production readiness aggregate` | Aggregates base quality, benchmark comparison, and the required GPU inference evidence policy. |
| `pg-stress` | `CI / PostgreSQL Connection Pool Stress Test` | Keeps PostgreSQL migration and connection-pool stress coverage blocking for merge readiness. |
| audit workflow | `Branch protection audit / Required release checks audit` | Verifies the live merge policy itself before a PR can merge. |

The `seed-benchmark-baseline` / `Seed benchmark baseline cache` workflow path is
intentionally **not** a required PR check: it only runs via manual
`workflow_dispatch` bootstrap with `seed_benchmark_baseline=true`. Normal CI must
remain fail-closed when no reviewed `.benchmarks/*_baseline.json` cache/artifact
is restored.

The release-blocking `benchmark-compare` job and both baseline seed paths require a
dedicated `[self-hosted, linux, benchmark]` runner. Its name is part of the benchmark
cache key, preventing a baseline produced on one hardware host from being restored on
another host. The pool therefore requires primary and warm-standby
`[self-hosted, linux, benchmark]` runners, with a reviewed baseline seeded separately for
each runner name. This preserves hardware-specific comparisons without accepting a single
runner as a release-critical point of failure. A runner rename still invalidates that host's
baseline by design and requires an explicit reseed.

The same reviewed comparison is mandatory in all three promotion paths: normal `main`
CI (`benchmark-compare`), the scheduled auth benchmark, and
`release-quality.yml` (`release-benchmark-compare`). Developer runs may still opt in to
comparison, but release and scheduled workflows fail closed when the baseline is absent.
The general CPU gate rejects a mean-latency regression above 10% (which is stricter than
the current 15% release objective and also protects inverse operations/second
throughput); auth P95/P99 budgets and the separate GPU latency/VRAM evidence gate cover
workload-specific latency and accelerator-memory limits.

`benchmark-baseline-keepalive.yml` (Mondays/Thursdays, plus manual `workflow_dispatch`)
exists specifically to restore-and-touch the reviewed default-branch baseline cache more
often than GitHub's ~7-day cache inactivity eviction window, without regenerating a
baseline. It **must** run on the same `[self-hosted, linux, benchmark]` runner pool and
use the exact same `benchmark-baseline-${{ runner.name }}-${{ runner.os }}-py311-...`
key prefix as `benchmark-compare`/the reusable seed job — `${{ runner.name }}` only resolves to
the value those jobs need on that runner pool. A version of this workflow once ran on
`ubuntu-latest` with a key that omitted `${{ runner.name }}` entirely; it "passed" every
scheduled run while silently restoring nothing, so the anti-eviction safety net did not
actually work. `tests/unit/scripts/test_run_tests_quality_gate.py::test_benchmark_baseline_cache_key_prefix_is_identical_everywhere`
guards all three files' cache-key declarations against drifting apart like that again — if
you touch any of them, keep the prefix identical or that test fails.

If the self-hosted benchmark runner is renamed or replaced, the previous baseline cache is
orphaned by design (see above) and must be reseeded via `seed_benchmark_baseline=true`
regardless of keepalive; keepalive only prevents inactivity eviction of a still-valid
cache entry, it cannot survive a runner identity change.

**Baseline lifecycle controls:**

Ortak reusable seed workflow `.github/workflows/benchmark-baseline-reusable.yml`, hem
`ci.yml` içindeki manuel bootstrap job'ı hem de `benchmark-baseline-seed.yml` tarafından
çağrılır. Toolchain kurulumu, mevcut cache restore'u, pytest-benchmark seed komutu, manifest,
artifact retention ve cache-save anahtarı böylece tek bir implementasyonda tutulur; caller'lar
yalnız baseline adı, opsiyonel test filtresi ve retention değerini seçer.

`benchmark-baseline-keepalive.yml` baseline üretmez veya otomatik olarak güvenilmeyen yeni bir
ölçümü onaylamaz. Reviewed cache bulunamazsa fail-closed olur ve runner adına göre deduplicate
edilmiş bir GitHub issue oluşturur/günceller. Operatör reusable seed yolunu çalıştırmalı,
artifact'ı incelemeli ve strict compare'ı yeniden koşturmalıdır. Otomatik re-seed kasıtlı olarak
yapılmaz: donanım veya dependency drift'inden sonra yeni performans referansını insan incelemesi
olmadan kabul etmek regresyonu baseline'a gömebilir.

Do not replace this label set with `ubuntu-latest`: GitHub-hosted shared
runners have variable CPU, storage and scheduler contention and are unsuitable for a
strict latency comparison. An unavailable benchmark runner must leave readiness
blocked rather than silently falling back to shared hardware.

The hardware benchmark remains in `gpu-inference-quality-gate` / `GPU Inference
Quality Gate (TTFT<=200ms, latency<=250ms)` and requires a
`[self-hosted, linux, x64, gpu, cuda]` runner. The always-running
`gpu-inference-policy-gate` converts an unset `ENABLE_GPU_BENCH_GATE`, a skipped
hardware job, unavailable evidence, or a failed benchmark into a blocking
failure. `production-readiness` depends on that policy job, so its aggregate can
no longer become green without TTFT/latency evidence. Forks without an eligible
runner must provision one before claiming merge/release readiness; there is no
silent checklist-only bypass.

Bu donanım kapısı tek-host bağımlılığı olarak işletilmez. Primary ve farklı arıza alanındaki
warm-standby runner aynı `[self-hosted, linux, x64, gpu, cuda]` etiketlerini taşır; saatlik
`GPU Runner Capacity Watchdog` hem `ENABLE_GPU_BENCH_GATE=true` repository variable sözleşmesini
hem de en az iki online runner kapasitesini arar. Watchdog için repository runner
metadata okuma yetkili `GPU_RUNNER_MONITOR_TOKEN` secret'ı gerekir. Failover, RTO ve üç aylık
tatbikat adımları [`docs/runbooks/gpu-runner-continuity.md`](runbooks/gpu-runner-continuity.md)
içinde tanımlıdır. Watchdog erken uyarıdır; required GPU benchmark kanıtının yerine geçmez.

Repository administrators should periodically verify that the required check
names above are selected for protected `main`/`master` branches. This repository
now includes a scheduled/manual audit workflow (`Branch protection audit`) that
runs `scripts/ci/verify_required_checks.py` against GitHub's branch protection
API and compares the protected branch contexts with the release-critical job
`name:` values in `.github/workflows/ci.yml`. If a job `name:` changes, update
branch protection at the same time or this audit will fail; without that sync,
PRs may either be blocked forever by a stale required context or allowed to
merge without the intended release gate.

### Automated required-check audit

Run the same audit locally when reviewing CI job-name or branch-protection
changes:

```bash
uv run python scripts/ci/verify_required_checks.py --repo <owner>/<repo> --branch main
```

For deterministic tests or dry-runs, pass `--required-context` values instead of
calling GitHub. The script intentionally fails closed when a release-critical job
from `.github/workflows/ci.yml` is absent from branch protection, or when the
GitHub API cannot be reached/authorized during the scheduled audit.

The scheduled workflow prefers the repository secret
`BRANCH_PROTECTION_AUDIT_TOKEN`. Configure it as a fine-grained personal access
token or GitHub App installation token scoped to this repository with
**Administration: read** permission. The built-in `github.token` is retained only
as a fallback and can receive HTTP 403 for branch-protection metadata; a 403 means
the live configuration was **not verified**, not that required checks are present.
The script fails closed and prints this remediation instead of treating the local
workflow contract as proof of GitHub Settings.

The live audit reads the complete branch-protection payload rather than checking
status contexts alone. In addition to the table above, it fails when pull-request
reviews are not required, required checks are not strict/up-to-date, administrator
enforcement is disabled, or force pushes/branch deletion are enabled. Keep bypass
access limited to explicitly controlled emergency actors; GitHub ruleset bypass
actors still require periodic review in **Settings → Rules → Rulesets**, because
their actor list is not represented by the classic branch-protection payload.

Keep `Branch protection audit / Required release checks audit` selected as a
required `main` check as well. The workflow runs for every pull request via
`pull_request_target`, using only the trusted default-branch workflow and never
checking out PR code, so protection drift is detected before merge without exposing
the administration-read secret to contributed code. It also runs immediately after
every `main` push while retaining the weekly schedule and manual dispatch. Scheduled,
manual, and post-push failures create or update a deduplicated GitHub issue; PR failures
remain visible as a blocking check without generating an issue comment on every commit.


## Autonomous/direct push guardrails

Branch protection remains the authoritative control for keeping red CI off
`main`. The bundled `github_upload.py` now pushes a timestamped `sidar/upload-*`
branch and opens a PR by default; direct `main` push requires the explicit
`SIDAR_GITHUB_UPLOAD_DIRECT_MAIN=1` opt-in. Both flows run this synchronous
pre-push gate after creating any local commit and again before a retry push
following an automatic pull/merge:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest tests/unit -q --no-cov -x
```

If any command fails, the upload tool exits without calling `git push`. The full
unit package catches code/test contract drift before autonomous backup/deployment
loops can publish a branch; the broader GitHub required checks still cover
production-readiness, installer smoke, dependency-profile, PostgreSQL stress, and
benchmark compare behavior. Repository administrators should still periodically
inspect GitHub branch protection/rulesets and confirm the required contexts in the
table above are selected for `main`; the local guard is a defense in depth, not a
replacement for required status checks.

## Installer manifest and smoke gate

GitHub branch protection for `main`/`master` should require the CI job named
`Installer manifest and smoke gate` before a pull request can merge.

This job is intentionally separate from the broad backend `test` job so installer
manifest drift is visible as its own required status check. It must remain required
for changes touching any of these release-critical paths:

- `install_sidar.sh`
- `.sidar_manifest.txt`
- `core/memory.py`
- `core/multimodal.py`
- `scripts/install_modules/**`
- `scripts/sync_install_manifest.sh`
- `scripts/tools/update_core_install_manifest.py`
- `scripts/tools/update_install_module_hash_manifest.py`
- `tests/smoke/test_install_verification.py`

Repository administrators must also keep these `main` branch protection or ruleset
settings enabled in GitHub Settings:

- **Require status checks to pass before merging** with
  `Installer manifest and smoke gate` selected as a required check.
- **Do not allow force pushes** so a forced update cannot bypass a previously failed
  installer manifest gate.
- **Require linear history** so the protected branch has an auditable, non-merge-bubble
  release history for raw installer artifacts.

These settings are intentionally documented next to the job contract because the
workflow can detect manifest drift, but only GitHub branch protection can prevent
merging or force-pushing a ref when the required status check is red.

The gate runs the embedded manifest sync test directly:

```bash
uv run pytest -q --no-cov tests/smoke/test_install_verification.py::test_install_sidar_embedded_manifests_in_sync
```

It also runs direct manifest checks:

```bash
sha256sum -c .sidar_manifest.txt
uv run python scripts/tools/update_core_install_manifest.py --check
uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check
uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check-pin
```

Because `install_sidar.sh` is distributed directly through GitHub raw URLs, the
same required gate treats the raw installer as a release artifact before merge:

```bash
bash -n install_sidar.sh
SIDAR_INSTALL_TEST_MODE=1 SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY=1 bash install_sidar.sh
```

The bundle producer still keeps its own fail-closed pre-bundle checks, but those
checks are not sufficient by themselves for the raw `main/install_sidar.sh`
distribution path. Raw installer verification must therefore remain in the PR
merge gate.

The installer smoke suite also includes a wget-style clean-install simulation
(`test_install_sidar_wget_raw_direct_module_download_smoke`) that downloads
`install_sidar.sh` from a branch-local raw HTTP URL, runs `chmod +x`, and then
executes it with `SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY=1`. The raw installer
now verifies the local `scripts/install_modules` tree first and downloads the
pinned modules directly before falling back to any git clone/re-exec path. This avoids testing
stale `main` from pull requests while still matching the documented end-user
`wget ... && chmod +x ... && ./install_sidar.sh` flow.


For local installer runs, the pre-service smoke gate in local runtime mode can be bypassed only as an explicit operator escape hatch:

```bash
SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0 ./install_sidar.sh --runtime-mode=local
```

Keep the bypass off for normal development and CI; it exists for diagnosing installer or environment breakage before Docker services start.

If this gate fails, synchronize the manifests before merging. For core installer
changes (`core/memory.py`, `core/multimodal.py`, `.sidar_manifest.txt`, or the
`SIDAR_INSTALL_MANIFEST_EOF` block in `install_sidar.sh`), run both commands in
this order so the generated core manifest and the raw-installer hash gate stay
reviewable in the same PR:

```bash
scripts/sync_install_manifest.sh
scripts/sync_install_module_hashes.sh
# İlk manifest/hash commit'inden sonra:
make finalize-install-module-pin
```

For changes limited to `scripts/install_modules/**`, the module hash sync is the
required generator; running both is still safe and keeps the checklist uniform.

The core manifest intentionally covers only the current raw-installer security
boundary, `core/memory.py` and `core/multimodal.py`. If another file becomes
bootstrap-critical, add it to `TARGET_FILES` in
`scripts/tools/update_core_install_manifest.py` in the same PR as the manifest
sync output.

The same drift checks are also wired into `.pre-commit-config.yaml` for both
`pre-commit` and `pre-push` stages:

```bash
make check-install-manifests
make installer-shellcheck
uv run python scripts/tools/update_core_install_manifest.py --check
uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check
uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check-pin
```

These hooks intentionally run in check mode. Module değişikliği için standart akış iki
fazlıdır: sync çıktısını önce commit edin, ardından `make finalize-install-module-pin`
çalıştırın. Bu hedef gerçek HEAD SHA'sını damgalar, `--check-pin` ile yerelde doğrular ve
küçük pin fixup commit'ini otomatik oluşturur. Yalnız diff üretmek için
`scripts/finalize_install_module_pin.sh --no-commit` kullanılabilir.

The `pytest-meta-contracts` hook also runs at `pre-push` and covers the script,
quality-gate, and dependency-profile contracts most likely to detect configuration
drift quickly. `github_upload.py` deliberately runs the full `tests/unit` package
before publishing either a PR branch or the explicitly opted-in direct-main path.

## PR visibility for core installer files

`core/memory.py` and `core/multimodal.py` are part of the installer security
chain. Any PR touching either file must treat the change as installer-impacting,
not only as a normal Python unit-test change. The PR template therefore includes
an installer manifest checklist covering:

- unit/smoke coverage,
- `scripts/sync_install_manifest.sh`,
- `make check-install-manifests`,
- `make installer-shellcheck`,
- direct core/module manifest `--check` commands,
- raw installer smoke verification or the required `Installer manifest and smoke gate`.

`.github/CODEOWNERS` also marks the core installer files, manifest files, sync
scripts, manifest tools, and `scripts/install_modules/**` as installer-security
review paths.
