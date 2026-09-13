# `agent/roles/qa_agent.py` — QA/Coverage Otomasyon Ajanı

- **Kaynak dosya:** `agent/roles/qa_agent.py`
- **Not dosyası:** `docs/module-notes/agent/roles/qa_agent.py.md`

**Amaç:** Test coverage üretimi ve CI hata giderme (remediation) odaklı
uzman ajan; `web/routes/coverage_ops.py`'nin arkasındaki ajan mantığı.
`core/ci_remediation.py`'deki CI hata payload üretimini ve
`core/test_fixture_policy.py`'deki paylaşılan test fixture rehberliğini
kullanır.

**Özellikler:**
- `QAAgent(BaseAgent)` — `managers/code_manager.py` üzerinden coverage
  analiz/üretim/toplu (batch) görevlerini yürütür; `configparser`/`re` ile
  mevcut coverage konfigürasyonunu ayrıştırır.
