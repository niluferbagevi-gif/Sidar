# `core/test_fixture_policy.py` — Paylaşılan Pytest Fixture Politikası

- **Kaynak dosya:** `core/test_fixture_policy.py`
- **Not dosyası:** `docs/module-notes/core/test_fixture_policy.py.md`

**Amaç:** Otonom test üretim prompt'larının (QA ajanı, CI remediation)
projenin zaten var olan paylaşılan fixture'larını (yeniden icat etmek
yerine) kullanmasını sağlayan sabit fixture adı listesi.

**Özellikler:**
- `SHARED_PROJECT_FIXTURES` — `mock_config`, `fake_llm_response`,
  `fake_llm_error`, `fake_event_stream`, `fake_redis`, `fake_db_session`,
  `frozen_time`, `agent_factory`, `sidar_agent_factory`,
  `fake_coverage_code_manager`, `fake_coverage_db_class`,
  `fake_llm_tool_sequence`, `fake_web_search_result`, `fake_vector_store`,
  `respx_mock_router` gibi proje genelindeki fixture adlarının sabit demeti;
  `core/ci_remediation.py` ve `agent/roles/qa_agent.py` tarafından prompt
  rehberliğine gömülür.
