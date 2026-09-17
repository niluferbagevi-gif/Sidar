# `core/models.py` — SQLAlchemy Şema Modelleri (Alembic Kaynağı)

- **Kaynak dosya:** `core/models.py`
- **Not dosyası:** `docs/module-notes/core/models.py.md`

**Amaç:** Alembic autogenerate'in metadata kaynağı olan SQLAlchemy ORM
modelleri. Runtime kayıt DTO'ları, SQLAlchemy async Core/ORM'e
sorgu-bazlı geçiş tamamlanana kadar `core/db/` içinde kalmaya devam eder —
bu dosya yalnızca şema tanımıdır, runtime sorgu katmanı değildir.

**Özellikler:**
- `SidarUUID(TypeDecorator[str])`, `PGVector384(UserDefinedType[Any])` —
  özel sütun tipleri (Postgres/SQLite arası UUID uyumluluğu, pgvector 384
  boyutlu embedding sütunu).
- `Base(DeclarativeBase)` — tüm modellerin ortak taban sınıfı.
- `User`, `AuthToken`, `UserQuota`, `ProviderUsageDaily`, `Session`,
  `Message`, `SchemaVersion`, `PromptRegistry`, `AuditLog`,
  `MarketingCampaign`, `ContentAsset`, `OperationChecklist` — tablo
  modelleri.
