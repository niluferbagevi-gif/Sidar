# 3.20 `core/db.py` — Veritabanı ve Çoklu Kullanıcı Altyapısı

**Amaç:** Çoklu kullanıcı (multi-user) SaaS mimarisi için kullanıcı, oturum, mesaj ve yetkilendirme (token) verilerinin kalıcı ve izole olarak saklanmasını sağlar.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l core/db.py` çıktısına göre **989** olarak ölçülmüştür.

**Kriptografik Auth Altyapısı:**
- Parolalar PBKDF2-HMAC (`hashlib.pbkdf2_hmac`) + salt ile hashlenir; düz metin parola saklanmaz.
- Auth token üretimi `secrets` ile yapılır (`token_urlsafe` / güvenli karşılaştırma), token yaşam döngüsü DB'de izlenir.
- Kullanıcı/oturum/mesaj kimlikleri `uuid` tabanlı benzersiz anahtarlarla yönetilir.

**Asenkron ve Non-Blocking Veri Katmanı:**
- Tüm temel I/O yolu `async def` akışındadır (bağlantı, şema, CRUD, auth doğrulama).
- `DATABASE_URL`’e göre PostgreSQL (`asyncpg`) veya SQLite (`aiosqlite`) fallback desteği vardır.
- Çoklu ajan/kullanıcı eşzamanlılığında bloklamayı azaltmak için bağlantı ve sorgu yolları asenkron tasarlanmıştır.

**UTC / TTL Tabanlı Oturum Yönetimi:**
- Zaman alanları `datetime.now(timezone.utc)` ile UTC normalize edilir.
- Token süre sonları `timedelta` tabanlı hesaplanır (`_expires_in`), periyodik temizlik/süre kontrol akışlarıyla birlikte çalışır.
- `sessions`, `messages`, `auth_tokens` kayıtları zaman damgası ve kullanıcı kimliğiyle birlikte izlenir.

**Dataclass ile Katı Şema Temsili:**
- DB satırları `@dataclass` kayıt modellerine (`UserRecord`, `AuthTokenRecord`, `SessionRecord`, `MessageRecord`, vb.) dönüştürülür.
- Bu modelleme katmanı API tüketicilerinde tip güvenliği ve sözleşme tutarlılığı sağlar.

**Alembic / Şema Versiyonlama Uyum Notu:**
- `schema_versions` tablosu üzerinden uygulama tarafı şema sürümü izlenir.
- Migration kaynağı olarak Alembic zinciriyle uyumlu çalışacak biçimde tasarlanmıştır (`alembic.ini` + `migrations/`).

**Temel Tablolar ve İzolasyon:**
- Çekirdek tablolar: `users`, `auth_tokens`, `sessions`, `messages`, `daily_llm_usage`.
- Her oturum ve mesaj kaydı `user_id` bağlamına bağlıdır; tenant izolasyonu veri modelinde zorunludur.

---
