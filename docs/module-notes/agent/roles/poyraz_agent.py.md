# `agent/roles/poyraz_agent.py` — Poyraz (Pazarlama/Operasyon) Ajanı

- **Kaynak dosya:** `agent/roles/poyraz_agent.py`
- **Not dosyası:** `docs/module-notes/agent/roles/poyraz_agent.py.md`

**Amaç:** Pazarlama ve dijital operasyon odaklı uzman ajan; `web/routes/operations.py`'nin
kampanya/içerik/landing-page üretim uç noktalarının arkasındaki ajan mantığı.
`core/hitl.py`'nin onay kapısını, `managers/social_media_manager.py` ve
`managers/web_search.py`'yi, `core/rag.py`'nin `DocumentStore`'unu kullanır.

**Özellikler:**
- `_resolve_multimodal_pipeline_class()` — görsel/çoklu-medya üretim
  pipeline'ını lazy olarak çözer (import zamanında ağır bağımlılık
  yüklemez).
- `PoyrazAgent(BaseAgent)` — kampanya kopyası, landing page taslağı, sosyal
  medya/pazarlama araç çağrılarını yürüten ana ajan sınıfı; riskli/dış-etkili
  aksiyonlar `core/hitl.py` üzerinden onaya tabi tutulabilir.
