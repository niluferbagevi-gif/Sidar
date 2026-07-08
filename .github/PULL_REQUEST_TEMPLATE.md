## Summary

- 

## Testing

- 

## Installer manifest checklist

If this PR touches `core/memory.py`, `core/multimodal.py`, `install_sidar.sh`,
`.sidar_manifest.txt`, or `scripts/install_modules/**`, confirm:

> Core installer changes require both manifest sync steps in order: first
> `scripts/sync_install_manifest.sh`, then `scripts/sync_install_module_hashes.sh`.
> The core sync updates `install_sidar.sh`; the module-hash sync keeps the raw
> installer hash gate aligned with the generated installer content.

- [ ] I ran `scripts/sync_install_manifest.sh` when core installer files changed.
- [ ] I ran `scripts/sync_install_module_hashes.sh` after core installer or installer module changes.
- [ ] I ran `make check-install-manifests`.
- [ ] I ran `make installer-shellcheck`.
- [ ] I ran `uv run python scripts/tools/update_core_install_manifest.py --check`.
- [ ] I ran `uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check`.
- [ ] Install manifest synced.
- [ ] I ran the installer smoke/raw-installer checks or confirmed the required `Installer manifest and smoke gate` CI job passed.

> `core/memory.py` and `core/multimodal.py` are part of the installer security chain; changing them without syncing the manifests can break clean installs from GitHub raw `install_sidar.sh`.
