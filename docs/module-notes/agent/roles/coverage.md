# agent/roles/coverage/

- **Kaynak dizini:** `agent/roles/coverage/` (`__init__.py`, `analyzer.py`,
  `batch_heal.py`, `config.py`, `generator.py`)
- **Not dosyası:** `docs/module-notes/agent/roles/coverage.md`

## Amaç

`agent/roles/coverage_agent.py::CoverageAgent`'ın (bkz.
`docs/module-notes/agent/roles/coverage_agent.py.md`) araç implementasyonlarını
tuttuğu modüller. Araç fonksiyonları ilk parametre olarak `agent: CoverageAgent`
alır (bağımlılık `TYPE_CHECKING` altında, döngüsel import'u önler);
`CoverageAgent`'ın kendi `_tool_*` metotları bu fonksiyonlara ince birer
delegasyon.

- **`analyzer.py`:** Salt okunur analiz araçları —
  `tool_run_pytest` (pytest'i çalıştırıp XML/terminal çıktısını toplar),
  `tool_analyze_pytest_output`, `tool_analyze_coverage_report` (coverage
  yapılandırması + `coverage.xml`'i ayrıştırıp eksik satır/dal listesi çıkarır),
  `tool_analyze_test_artifacts`.
- **`config.py::read_coverage_config`:** Coverage yapılandırmasını okur.
  Açık bir INI dosyası (`.coveragerc`, `setup.cfg` `[coverage:*]`) varsa onu,
  varsayılan `.coveragerc` yoksa yanındaki `pyproject.toml`
  `[tool.coverage.run]`/`[tool.coverage.report]` tablolarını kullanır (repo
  ayarları buradadır). `CoverageAgent._read_coveragerc` ve
  `QAAgent._coverage_config_summary` bu yardımcıya delege eder; böylece ajanlar
  gerçek `fail_under`/`omit` değerlerini görür.
- **`generator.py`:** Eksik test üretim/yazma yolu —
  `generate_test_candidate` (LLM'e hedef dosya + pytest çıktısını göstererek
  aday test ister), `tool_generate_missing_tests`, `tool_write_missing_tests`
  ve `validate_candidate_with_isolated_pytest` (üretilen testi izole bir
  pytest çalıştırmasıyla doğrular — repo'ya yazılmadan önceki son kapı).
- **`batch_heal.py::run_autonomous_coverage_batch`/`tool_autonomous_batch_heal`:**
  `analyzer`+`generator`'ı bir araya getiren otonom döngü — coverage
  raporundan bulunan eksiklikleri `batch_size` kadar toplu işleyip her adayı
  izole doğrulamadan geçirir.

## Test kapısı

`tests/unit/agent/roles/test_coverage_agent.py` (`analyzer`, `generator` ve
`batch_heal` modüllerini `CoverageAgent` üzerinden dolaylı olarak kapsıyor) ve
`tests/unit/agent/roles/test_coverage_config.py` (`config.py`).
