# 3.20 `core/db` — Veritabanı package facade ve çoklu kullanıcı altyapısı

## Güncel kaynak yerleşimi

`core.db` artık tek dosyalık `core/db.py` modülü değil, geriye dönük uyumlu bir
package facade'dır. Eski geniş uygulama `core/db/monolith.py` içine taşınmıştır;
`core/db/__init__.py` ise `from core.db import Database` gibi mevcut importları
kırmamak için runtime'da monolith modülünü facade olarak alias'lar.

Güncel sorumluluk dağılımı:

- `core/db/__init__.py`: public facade, `__all__` yüzeyi ve legacy import uyumu.
- `core/db/monolith.py`: eski `core/db.py` davranışının ana gövdesi ve `Database`
  uygulaması.
- `core/db/auth.py`, `session.py`, `sessions.py`, `audit.py`, `metrics.py`,
  `prompt_registry.py`, `coverage.py`: aşamalı ayrıştırılmış domain yardımcıları.
- `core/db/models.py`, `engine.py`, `multitenant.py`, `alembic_runner.py`: yeni
  kodun daha dar import sınırlarına yönelebileceği facade/alias modülleri.
- `core/db_components/`: düşük seviye dialect ve migration yardımcıları için geçiş
  namespace'i.

> Not (Doğrulama): Eski `wc -l core/db.py` ölçümü artık geçerli değildir; depoda
> `core/db.py` yoktur. Satır veya coverage değerlendirmeleri package path'leri
> üzerinden yapılmalıdır (`core/db/__init__.py`, `core/db/monolith.py`, vb.).

## Import uyumluluk sözleşmesi

Mevcut testler ve uygulama kodu `import core.db as core_db` veya
`from core.db import Database, UserRecord, SessionRecord` kalıplarını kullanmaya
devam edebilir. Bu, facade tarafından bilinçli olarak korunur. Yeni kod ise mümkün
olduğunda domain modüllerini doğrudan hedeflemelidir:

```python
from core.db import Database              # geriye dönük uyumlu public facade
from core.db.auth import UserRecord       # yeni domain import sınırı
from core.db.session import SessionRecord # yeni domain import sınırı
```

Test importları için kural: `tests/unit/core/test_db.py` gibi legacy kapsamlı testler
`core.db` facade'ını kullanabilir; domain-spesifik yeni testler ise
`tests/unit/core/db/` altında ilgili alt modülü (`core.db.auth`, `core.db.audit`,
`core.db.prompt_registry`, vb.) doğrudan import etmelidir. `core.db.monolith` yalnız
refactor/facade kontrat testlerinde veya taşınmamış legacy davranışı doğrulanırken
kullanılmalıdır.

## Korunan davranışlar

**Kriptografik Auth Altyapısı:**
- Yeni parolalar Argon2id + salt ile hashlenir; legacy PBKDF2-HMAC kayıtları
  doğrulanmaya devam eder ve düz metin parola saklanmaz.
- Auth token üretimi `secrets` ile yapılır (`token_urlsafe` / güvenli karşılaştırma),
  token yaşam döngüsü DB'de izlenir.
- Kullanıcı/oturum/mesaj kimlikleri `uuid` tabanlı benzersiz anahtarlarla yönetilir.

**Asenkron ve Non-Blocking Veri Katmanı:**
- Temel I/O yolu `async def` akışındadır (bağlantı, şema, CRUD, auth doğrulama).
- `DATABASE_URL`’e göre PostgreSQL (`asyncpg`) veya SQLite (`aiosqlite`) fallback
  desteği vardır.
- Çoklu ajan/kullanıcı eşzamanlılığında bloklamayı azaltmak için bağlantı ve sorgu
  yolları asenkron tasarlanmıştır.

**UTC / TTL Tabanlı Oturum Yönetimi:**
- Zaman alanları `datetime.now(timezone.utc)` ile UTC normalize edilir.
- Token süre sonları `timedelta` tabanlı hesaplanır (`_expires_in`), periyodik
  temizlik/süre kontrol akışlarıyla birlikte çalışır.
- `sessions`, `messages`, `auth_tokens` kayıtları zaman damgası ve kullanıcı kimliğiyle
  birlikte izlenir.

**Dataclass ile Katı Şema Temsili:**
- DB satırları `@dataclass` kayıt modellerine (`UserRecord`, `AuthTokenRecord`,
  `SessionRecord`, `MessageRecord`, vb.) dönüştürülür.
- Bu modelleme katmanı API tüketicilerinde tip güvenliği ve sözleşme tutarlılığı sağlar.

**Alembic / Şema Versiyonlama Uyum Notu:**
- `schema_versions` tablosu üzerinden uygulama tarafı şema sürümü izlenir.
- Migration kaynağı olarak Alembic zinciriyle uyumlu çalışacak biçimde tasarlanmıştır
  (`alembic.ini` + `migrations/`).

**Temel Tablolar ve İzolasyon:**
- Çekirdek tablolar: `users`, `auth_tokens`, `sessions`, `messages`,
  `daily_llm_usage`.
- Her oturum ve mesaj kaydı `user_id` bağlamına bağlıdır; tenant izolasyonu veri
  modelinde zorunludur.

## Refactor takip notu

Facade dönemi bitene kadar yeni extraction PR'ları şu iki güvenceyi birlikte
korumalıdır:

1. `core/db/__init__.py` public export yüzeyi, mevcut `from core.db import ...`
   çağrılarını kırmamalıdır.
2. Taşınan domain davranışı için `tests/unit/core/db/` altında alt modül odaklı test
   eklenmeli; legacy `tests/unit/core/test_db.py` yalnız facade/monolith davranışını
   kapsayan regresyonlar için genişletilmelidir.
