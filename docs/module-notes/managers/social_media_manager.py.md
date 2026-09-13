# `managers/social_media_manager.py` — Sosyal Medya Yöneticisi

- **Kaynak dosya:** `managers/social_media_manager.py`
- **Not dosyası:** `docs/module-notes/managers/social_media_manager.py.md`

**Amaç:** Meta Graph API ve WhatsApp Business API tabanlı, Instagram/
Facebook/WhatsApp gönderimlerini tek noktadan yöneten istemci; Poyraz
ajanının kampanya/içerik yayınlama akışlarının altyapısı.

**Özellikler:**
- `SocialMediaManager.__init__(...)` — Graph API token'ı, Instagram
  business account ID, Facebook sayfa ID'si ve WhatsApp telefon numarası
  ID'si ile kurulur; `http_client_factory` test edilebilirlik için
  `httpx.AsyncClient`'ı override edebilir.
- `is_available(platform)` — belirli bir platform (veya herhangi biri)
  için gerekli kimlik bilgilerinin yapılandırılıp yapılandırılmadığını
  kontrol eder.
- `publish_instagram_post()`, `publish_facebook_post()`,
  `send_whatsapp_message()` — platforma özel gönderim uç noktaları;
  hepsi ortak `_post()` yardımcısı üzerinden Graph API'ye istek atar.
- `publish_content()` — platform adına göre yukarıdaki üç metottan
  birine yönlendiren tek giriş noktası.
- `build_content_preview()` — gönderim öncesi UI'da gösterilecek özet
  metni üretir.

## İlgili modüller

`agent/roles/poyraz_agent.py`, `web/routes/operations.py`.
