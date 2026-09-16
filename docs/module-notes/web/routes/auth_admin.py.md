# `web/routes/auth_admin.py` — Kimlik Doğrulama/Admin Rotaları

- **Kaynak dosya:** `web/routes/auth_admin.py`
- **Not dosyası:** `docs/module-notes/web/routes/auth_admin.py.md`

**Amaç:** Kullanıcı kaydı/kimlik doğrulama ve admin işlemleri için FastAPI
rotalarını `web/routes/LegacyExportRouter` deseniyle dışa aktarır;
`web/security.py`'deki `is_reserved_username()` ile kullanıcı adı
çakışmalarını (rezerve isimler) engeller.

**Özellikler:**
- `_normalize_register_payload()` — kayıt isteğindeki alternatif alan
  adlarını (`userName`/`user_name` → `username`, `passWord` → `password`,
  `tenantId`/`tenant` → `tenant_id`) kanonik isimlere eşler; farklı istemci
  konvansiyonlarına (camelCase/snake_case) tolerans sağlar.
- `_parse_payload()` — Pydantic modeli varsa `model_validate()`, yoksa dict
  unpacking ile payload'ı esnek biçimde ayrıştırır.
