# CI Required Checks

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
(`test_install_sidar_wget_raw_bootstrap_clone_smoke`) that downloads
`install_sidar.sh` from a branch-local raw HTTP URL, runs `chmod +x`, and then
executes it with `SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY=1`. This avoids testing
stale `main` from pull requests while still matching the documented end-user
`wget ... && chmod +x ... && ./install_sidar.sh` flow.


For local installer runs, the pre-service smoke gate in local runtime mode can be bypassed only as an explicit operator escape hatch:

```bash
SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0 ./install_sidar.sh --runtime-mode=local
```

Keep the bypass off for normal development and CI; it exists for diagnosing installer or environment breakage before Docker services start.

If this gate fails, synchronize the manifests before merging:

```bash
scripts/sync_install_manifest.sh
scripts/sync_install_module_hashes.sh
```

The same drift checks are also wired into `.pre-commit-config.yaml` for both
`pre-commit` and `pre-push` stages:

```bash
uv run python scripts/tools/update_core_install_manifest.py --check
uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check
```

These hooks intentionally run in check mode. If a hook fails, run the sync
script(s), review the generated manifest changes, and commit them explicitly.

## PR visibility for core installer files

`core/memory.py` and `core/multimodal.py` are part of the installer security
chain. Any PR touching either file must treat the change as installer-impacting,
not only as a normal Python unit-test change. The PR template therefore includes
an installer manifest checklist covering:

- unit/smoke coverage,
- `scripts/sync_install_manifest.sh`,
- direct core/module manifest `--check` commands,
- raw installer smoke verification or the required `Installer manifest and smoke gate`.

`.github/CODEOWNERS` also marks the core installer files, manifest files, sync
scripts, manifest tools, and `scripts/install_modules/**` as installer-security
review paths.
