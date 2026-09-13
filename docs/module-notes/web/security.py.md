# `web/security.py` — FastAPI Güvenlik ve Kimlik Doğrulama Yardımcıları

- **Kaynak dosya:** `web/security.py`
- **Not dosyası:** `docs/module-notes/web/security.py.md`

**Amaç:** Sidar'ın FastAPI yüzeyi için framework-hafif güvenlik yardımcılarını
toplar; `web_server.py` router modülerleştirme sürecinde geriye dönük uyumlu
wrapper isimlerini korurken bu modüle delege eder.

**Özellikler:**
- `WebhookReplayGuard` — imzalı webhook teslimatları için TTL'li, thread-safe
  bir replay-önleme cache'i (`reject_replay()`; TTL dolan girdiler ve kapasite
  aşıldığında en eski girdi otomatik temizlenir).
- `verify_webhook_hmac_signature()` — HMAC-SHA256 webhook imza doğrulaması,
  isteğe bağlı replay-guard entegrasyonu ile.
- WebSocket alt-protokol sabitleri (`SIDAR_WS_CHAT_PROTOCOL` vb.) ve token
  formatı doğrulaması (`_WS_PROTOCOL_TOKEN_RE`).
- `/metrics` gibi servis path'lerinin ayrıcalıklı erişim listesi
  (`METRICS_SERVICE_PATHS`).
- `is_reserved_username()` gibi kimlik doğrulama yardımcıları — `web/routes/auth_admin.py`
  tarafından kullanıcı adı çakışmalarını engellemek için tüketilir.
