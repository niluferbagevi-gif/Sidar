# `agent/triggers.py` — Dış Otonomi Tetikleyici Korelasyonu

- **Kaynak dosya:** `agent/triggers.py`
- **Not dosyası:** `docs/module-notes/agent/triggers.py.md`

**Amaç:** Dış sistemlerden gelen otonomi tetikleyicilerinin (`ExternalTrigger`)
korelasyon kimliğini kurar ve CI hata giderme bağlamını
(`core/ci_remediation.py`) işleyerek ajan katmanına iletir;
`web/routes/autonomy.py`'nin webhook/wake rotalarının arkasındaki servis
katmanı.

**Özellikler:**
- `build_trigger_correlation(...)` — `agent.federation.service`'in
  `derive_correlation_id`'ini kullanarak tetikleyiciye korelasyon kimliği
  atar.
- `handle_external_trigger(...)` (async) — CI hatası/webhook gibi dış
  tetikleyicileri işleyip uygun ajan görevine dönüştürür.
