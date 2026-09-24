# `web/middleware/auth.py` — Bearer Token Kimlik Doğrulama Middleware'i

- **Kaynak dosya:** `web/middleware/auth.py`
- **Not dosyası:** `docs/module-notes/web/middleware/auth.py.md`

**Amaç:** `web_server.basic_auth_middleware`'in gövdesi. Açık path'leri
(`/`, `/health*`, `/docs`, `/auth/login` vb.), statik varlıkları ve imzayla
doğrulanan webhook POST'larını geçirir; diğer istekler için `Authorization:
Bearer <token>` zorunludur. Önce metrik servis kimliğini, sonra JWT/DB tabanlı
kullanıcıyı çözer, `request.state.user`'ı doldurur ve istek süresince LLM metrik
kullanıcı bağlamını ayarlar.

**Özellikler:**
- `basic_auth_middleware_impl(request, call_next, *, config, ...)` — tüm
  işbirlikçiler (token çözümleyici, ajan çözümleyici, metrik bağlam
  ayarlayıcıları) `web_server.py` tarafından çağrı anında enjekte edilir; bu
  sayede `web_server` üzerindeki monkeypatch'ler etkisini korur.
