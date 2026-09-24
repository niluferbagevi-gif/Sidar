# `core/config_dotenv_reload.py` — Dotenv Durum Logu ve Reload Zinciri

- **Kaynak dosya:** `core/config_dotenv_reload.py`
- **Not dosyası:** `docs/module-notes/core/config_dotenv_reload.py.md`

**Amaç:** `Config._log_dotenv_load_status()` ve `config._reload_dotenv_chain()`
gövdelerini `config.py` facade'ından ayırır. Değiştirilebilir dotenv kayıtları (yükleme
olayları, anahtar kaynakları, yönetilen anahtarlar, son loglanan zincir imzası)
facade'da kalır ve parametre olarak geçer; böylece `importlib.reload(config)` ve bu
globalleri değiştiren testler tek doğruluk kaynağını görmeye devam eder.

**Özellikler:**
- `log_dotenv_load_status(...)` — yüklenen dotenv zincirini loglar (zincir değiştiyse
  ilk yüklemede INFO, aksi hâlde DEBUG), hiç dosya yüklenmediyse uyarır, eksik opsiyonel
  dosyaları tek satırda birleştirip bekleyen bildirim listesini boşaltır, anahtar
  kaynaklarını değer göstermeden DEBUG'da listeler ve çözülemeyen kritik anahtarlar için
  yönlendirici uyarı verir. Bir sonraki çağrıda karşılaştırılacak zincir imzasını
  döndürür; hiç dosya yüklenmediyse önceki imza değişmeden döner.
- `reload_dotenv_chain(...)` — reload planını gerçek proses ortamından kurar,
  dotenv öncesi taban ortamı hesaplar, `.env` → `.env.advanced` → `.env.<profil>` →
  `DOTENV_FILE` → `SIDAR_KEYS_FILE` zincirini bellek içi bir ortamda yeniden uygular,
  boş HF önbellek yollarını düşürür ve sonucu `environ`'a tek adımda yazar. Artık hiçbir
  katmanın sağlamadığı, önceden dotenv tarafından yönetilen anahtarlar kaldırılır.
  Plan oluşturma, taban ortam ve katman yükleme adımları enjekte edilir.

**Testler:** `tests/unit/core/test_config_dotenv_reload.py`;
`tests/integration/api/test_config_dotenv_chain.py` ve `tests/unit/root/test_config.py`
(facade üzerinden).
