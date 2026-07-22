# CI Required Checks

## Main branch required status checks

GitHub branch protection / rulesets are the source of truth for required PR
checks. They are configured in GitHub repository settings, not in this file, but
the expected required contexts should mirror the release-critical jobs in
`.github/workflows/ci.yml`:

| Workflow job id | Required GitHub check name | Why it must be required |
| --- | --- | --- |
| `test` | `CI / Base quality gates (lint, smoke, unit, coverage, frontend)` | Runs the broad production-readiness quality gate, including the fail-closed benchmark baseline restore/compare flow and `make production-readiness`. |
| `installer-smoke` | `CI / Installer manifest and smoke gate` | Prevents raw installer, embedded manifest, module hash, and installer smoke drift from merging unnoticed. |
| `production-profile-dry-run` | `CI / Production-minimal runtime validation` | Release-blocking production-minimal gate: installer sync, FastAPI web boot smoke, Alembic DB migration smoke, and uploaded runtime evidence artifact. |
| `pg-stress` | `CI / PostgreSQL Connection Pool Stress Test` | Keeps PostgreSQL migration and connection-pool stress coverage blocking for merge readiness. |

The `seed-benchmark-baseline` / `Seed benchmark baseline cache` workflow path is
intentionally **not** a required PR check: it only runs via manual
`workflow_dispatch` bootstrap with `seed_benchmark_baseline=true`. Normal CI must
remain fail-closed when no reviewed `.benchmarks/*_baseline.json` cache/artifact
is restored.

The `gpu-inference-quality-gate` / `GPU Inference Quality Gate (TTFT<=200ms,
latency<=250ms)` job is also intentionally **not** a required PR check: it only
runs when the `ENABLE_GPU_BENCH_GATE` repo/org variable is `true` and a
`[self-hosted, linux, gpu]` runner is available, and it is not part of
`run_tests.sh`'s `production_ready` computation. A PR showing
`production_ready=true` says nothing about GPU inference latency. PRs that touch
the GPU inference/LLM latency path must be reviewed against this job's result
(when it ran) or against the scheduled `Nightly GPU Performance` /
`GPU Benchmark Suite` workflow instead — this is the reviewer-facing checklist
item in `.github/PULL_REQUEST_TEMPLATE.md`'s production readiness section.

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


## Autonomous/direct push guardrails

Branch protection remains the authoritative control for keeping red CI off
`main`, but local automation must also fail closed before it attempts a direct
push. The bundled `github_upload.py` flow therefore runs this synchronous
pre-push gate after creating any local commit and again before a retry push
following an automatic pull/merge:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest tests/unit -q --no-cov -x
```

If any command fails, the upload tool exits without calling `git push`. The full
unit package catches code/test contract drift before autonomous backup/deployment
loops can write directly to `main`; the broader GitHub required checks still cover
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

These hooks intentionally run in check mode. If a hook fails, run the sync
script(s), review the generated manifest changes, and commit them explicitly.

The `pytest-meta-contracts` hook also runs at `pre-push` and covers the script,
quality-gate, and dependency-profile contracts most likely to detect configuration
drift quickly. The direct-main `github_upload.py` path deliberately runs the full
`tests/unit` package rather than relying on this faster subset.

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
