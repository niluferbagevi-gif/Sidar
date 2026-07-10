## Summary

- 

## Testing

- 

## Production readiness / merge gate

> `make dev-full` veya development `bash run_tests.sh --stage all` geçse bile release onayı değildir.
> Merge/release öncesinde `artifacts/test-summary.json` içindeki `production_ready` alanı
> `true` olmalı veya production-readiness CI job sonucu açıkça geçmelidir.

- [ ] `artifacts/test-summary.json` içinde `production_ready=true` doğrulandı.
- [ ] `production_readiness_detail.required_command` kanonik komutla eşleşiyor:
  `TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all`.
- [ ] `production_ready=false`, `summary-code=10` veya `summary-code=20` görüldüyse bu PR merge/release için bloke edildi.


## Benchmark baseline bootstrap

> CI'da benchmark baseline missing görülürse bu tek başına test hatası değildir;
> fail-closed production-readiness davranışıdır. Önce GitHub Actions → CI → Run workflow
> → `seed_benchmark_baseline=true` çalıştırın, seed artifact/cache oluştuktan sonra normal
> CI veya `make production-readiness` gate'ini tekrar koşun. Yerel bootstrap için
> `make benchmark-seed` kullanın. Seed artifact retention süresi 30 gündür; cache düşerse
> aynı bootstrap prosedürünü tekrar uygulayın.

- [ ] CI benchmark baseline cache/artifact mevcut veya `seed_benchmark_baseline=true` ile yeniden seed edildi.
- [ ] Baseline seed sonrası normal CI / production-readiness gate tekrar çalıştırıldı.

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
