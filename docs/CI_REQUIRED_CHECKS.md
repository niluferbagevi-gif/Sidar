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
