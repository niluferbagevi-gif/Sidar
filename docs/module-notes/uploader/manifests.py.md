# `uploader/manifests.py` — Installer Manifest Senkronu

- **Kaynak dosya:** `uploader/manifests.py`
- **Not dosyası:** `docs/module-notes/uploader/manifests.py.md`

**Amaç:** Commit öncesi installer manifest/hash senkronu ve commit sonrası pin damgalama.

**Özellikler:**
- `sync_install_manifests_before_commit`.
- `stamp_install_manifest_pin_after_commit` — pin'i gerçek commit SHA'sına damgalar, gerekirse fixup commit'i oluşturur.
- `ensure_full_git_history_for_manifest_checks` — shallow clone'larda `--check-pin` yanlış pozitifini önler.
