# `core/config_memory_security.py` — Bellek Şifrelemesi Ayarları

- **Kaynak dosya:** `core/config_memory_security.py`
- **Not dosyası:** `docs/module-notes/core/config_memory_security.py.md`

**Amaç:** `config.py`'deki `# ─── Bellek Şifrelemesi ───` bloğunun 2 alanını
(`MEMORY_ENCRYPTION_KEY`, `MEMORY_ENCRYPTION_KEY_PREVIOUS`)
`MemorySecuritySettings` frozen dataclass'ı olarak yükler; `config.Config`
bunu `memory_security_settings` olarak expose eder ve aynı 2 alanı geriye
dönük uyumlu `Config.FOO` class attribute'larına delege eder
(`docs/REFACTOR_PLAN.md`'nin `config.py` maddesinde web arayüzü bind
diliminden sonra işaretlenen sıradaki düşük riskli dilim). Konuşma
geçmişi Fernet şifrelemesi için kullanılan bu anahtar çifti,
`Config.validate_critical_settings(...)` içindeki
`cls.MEMORY_ENCRYPTION_KEY`/`cls.MEMORY_ENCRYPTION_KEY_PREVIOUS` tabanlı
Fernet ön doğrulaması, `core/config_secret_hardening.py`'nin production
zorunluluğu kontrolü ve `agent/sidar_agent.py`'nin
`getattr(cfg, "MEMORY_ENCRYPTION_KEY", "")` gibi mevcut alan adlarıyla
tüketmesi değişmeden korunur.

**Özellikler:**
- `MemorySecuritySettings` — `memory_encryption_key`,
  `memory_encryption_key_previous`.
- `load_memory_security_settings()` — her alanı kendi ortam
  değişkeninden okur; `MEMORY_ENCRYPTION_KEY_PREVIOUS` virgülle ayrılmış
  birden fazla eski anahtarı ham string olarak taşır (ayrıştırma
  `Config.validate_critical_settings(...)` tarafında yapılır, bu modülde
  değil).
