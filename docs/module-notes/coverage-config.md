# pyproject.toml coverage yapılandırması

- **Kaynak dosya:** `pyproject.toml`
- **Not dosyası:** `docs/module-notes/coverage-config.md`
- **Amaç:** Coverage.py run/report/html ayarlarını, günlük local `fail_under` baseline değerini ve coverage ratchet state'ini tek dosyada tutar.
- **Güncel baseline:** `[tool.coverage.report].fail_under = 5`
- **Durum:** Ayrı `.coveragerc` dosyası yoktur; eski `.coveragerc` referansları yalnızca tarihsel/audit bağlamında kalabilir. Aktif doğrulama `run_tests.sh`, `scripts/coverage_ratchet.py` ve CI profil override'ları üzerinden bu `pyproject.toml` değerini kullanır.

## Profil çözümleme özeti

- Local gate: `COVERAGE_FAIL_UNDER_LOCAL` verilmemişse `pyproject.toml` baseline (`%5`).
- CI gate: `COVERAGE_FAIL_UNDER_CI` verilmemişse aynı ratchet edilmiş `pyproject.toml` baseline (`%5` başlangıç); workflow varsayılan override set etmez.
- Coverage campaign: `COVERAGE_CAMPAIGN=1` veya `AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign` açıkken gate varsayılanı yine ratchet edilmiş `pyproject.toml` baseline (`%5` başlangıç); `COVERAGE_FAIL_UNDER_CAMPAIGN` yalnız açık override’dır.
- Açık `COVERAGE_FAIL_UNDER` tüm profillerin önüne geçer.
- `scripts/coverage_ratchet.py` bu baseline'ı yalnızca yukarı taşır; düşürmez.
