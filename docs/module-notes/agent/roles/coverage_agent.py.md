# agent/roles/coverage_agent.py

- **Kaynak dosya:** `agent/roles/coverage_agent.py`
- **Not dosyası:** `docs/module-notes/agent/roles/coverage_agent.py.md`

## Amaç

`CoverageAgent(BaseAgent)` — `AgentCatalog.register(is_builtin=True)` ile
kayıtlı, pytest/coverage çıktısından eksik test senaryolarını bulup
deterministik pytest testleri üreten üretim ajanı. Gerçek araç
implementasyonları `agent/roles/coverage/` alt paketine (bkz.
`docs/module-notes/agent/roles/coverage.md`) devredilmiş; bu dosya ajan
kabuğunu, güvenlik/kalite kapılarını ve LLM'e sunulan sözleşmeyi taşıyor:

- **Coverage kaynağı ayrıştırma:** `_parse_coverage_xml` (`defusedxml` ile
  XXE'ye karşı güvenli), `_read_coveragerc`, `_parse_terminal_coverage_output`
  — üçü de coverage verisini ortak bir `{"missing_lines": ..., "missing_branches":
  ...}` şekline normalize eder.
- **Kapsam sınırlama:** `_normalize_exclude_files`/`_is_excluded_coverage_target`/
  `_cap_autonomous_finding_scope`, otonom modda hangi dosyaların
  dokunulabilir olduğunu daraltır.
- **Üretilen test kalite kapısı:** `_validate_generated_test_before_write` ve
  ona eşlik eden AST tabanlı sezgiler (`_is_tautological_mock_called_assertion`,
  `_has_runtime_behavior_signal`, `_is_import_only_assertion`,
  `_target_behavior_quality_reason`, `_candidate_rejection_reason`) LLM'in
  ürettiği testin gerçek davranış doğrulaması yaptığını, yalnızca
  import/mock-çağrıldı gibi anlamsız (tautolojik) assertion'lardan ibaret
  olmadığını statik olarak denetler — repo'ya yazılmadan önceki içerik kapısı.
  `_validate_candidate_with_isolated_pytest` ise çalışma zamanı kapısıdır
  (bkz. `coverage/generator.py`).
- **Deterministik şablon:** `_build_deterministic_test_template`, LLM
  fikri boşsa/reddedilirse düşülecek asgari, LLM'siz bir test iskeleti üretir.

## Test kapısı

`tests/unit/agent/roles/test_coverage_agent.py`.
