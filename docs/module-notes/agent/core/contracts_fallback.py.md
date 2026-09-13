# `agent/core/contracts_fallback.py` — Federasyon Sözleşmesi Geriye Uyumluluk Katmanı

- **Kaynak dosya:** `agent/core/contracts_fallback.py`
- **Not dosyası:** `docs/module-notes/agent/core/contracts_fallback.py.md`

**Amaç:** Daha önce `agent.federation.service`'teki import-sıra sorunlarını
aşmak için `FederationTaskEnvelope`/`ActionFeedback`'in elle bakımı yapılan
fallback kopyalarını taşırdı; canonical sözleşmeler artık federasyon
servisini import etmediği için bu katman artık alanları/prompt üretimini
tekrarlamak yerine canonical implementasyonları subclass'lar.

**Özellikler:**
- `FallbackFederationTaskEnvelope(FederationTaskEnvelope)`,
  `FallbackActionFeedback(ActionFeedback)` — geriye dönük uyumlu alt
  sınıflar.
- `bind_fallback_contracts(...)` — çağıranların
  `derive_correlation_id` gibi varsayılan yardımcıları override edebildiği
  bağlama fonksiyonu.
