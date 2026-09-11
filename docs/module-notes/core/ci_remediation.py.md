# `core/ci_remediation.py` — Proaktif CI Remediation Yardımcıları

- **Kaynak dosya:** `core/ci_remediation.py`
- **Not dosyası:** `docs/module-notes/core/ci_remediation.py.md`

**Amaç:** CI pipeline başarısızlıklarını webhook tetiklerinden çıkarır,
ajanlar için teşhis/remediation prompt'u üretir ve PR taslağı oluşturur;
`agent/roles/qa_agent.py` ve `agent/triggers.py`'nin CI hata giderme
mantığının merkezi kaynağı. Çalıştırılabilir doğrulama/autofix komutları
(`ruff --fix` vb.) yalnızca allowlist'ten (`_is_allowed_ruff_command`,
`_is_allowed_validation_command`) geçenler önerilir (keyfi komut
enjeksiyonuna karşı fail-closed).

**Özellikler:**
- `_normalize_ruff_rule_selectors(...)`, `_configured_ruff_unsafe_selectors()`,
  `build_ruff_autofix_command(...)`, `build_scoped_ruff_autofix_command(paths)`
  — ruff autofix komutlarını güvenli, izin verilen kurallarla kurar.
- `_is_allowed_ruff_command(parts)`, `_is_allowed_validation_command(command)`
  — komut allowlist doğrulaması.
- `_summarize_mypy_log(...)`, `_extract_suspected_targets(...)`,
  `_extract_root_cause_line(...)`, `_resolve_module_to_repo_path(...)`,
  `_collect_cross_file_context_paths(...)` — hata log'larından teşhis
  bağlamı çıkarır.
- `_extract_failed_job_names(data)` — webhook payload'ından başarısız job
  adlarını çıkarır.
- `core/test_fixture_policy.py`'deki `SHARED_TEST_FIXTURE_GUIDANCE`'ı
  remediation prompt'larına gömer.
