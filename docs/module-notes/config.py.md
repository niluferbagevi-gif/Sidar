# 3.1 `config.py` — Merkezi yapılandırma facade'ı

## Güncel kaynak yerleşimi

`config.py` hâlâ projenin geriye dönük uyumlu ana import yüzeyidir; ancak ayar
sorumlulukları artık domain dosyalarına ayrılmıştır. Eski `from config import Config`
ve `import config` kalıpları desteklenmeye devam ederken, yeni yardımcılar aşağıdaki
modüllerden beslenir:

- `core/config_postgres.py`: PostgreSQL DSN üretimi, container DB URL'i ve pool
  varsayılanlarının canonical modülü; `config.py` bu helperları doğrudan re-export eder.
- `core/config_llm.py`: LLM provider/model ayarları (coding ve text model seçimi dahil),
  `LLMClientSettings` ve Ollama batch policy.
- `core/config_quality.py`: DLP/HITL/LLM-judge kalite kapısı ayarları (`QualityGateSettings`).
- `core/config_rag_defaults.py`: RAG chunk/top-k/semantic-cache varsayılanları.
- `core/config_security.py`: API/JWT/security secret ayarları ve production validation
  yardımcıları.
- `core/config_self_heal.py`, `core/config_gpu.py`: self-heal ve GPU varsayılanları.
  (`core/config_autonomy.py` ayrı bir modüldür: otonomi servisi webhook ayarları.)
- `core/config_app.py`: uygulama adı, sürüm, debug, log ve runtime dil ayarları.
- `core/config_dotenv.py`, `core/config_env_helpers.py`, `core/config_runtime_env.py`:
  dotenv zinciri, type-safe env okuma ve reload-time override akışları.
- `core/config_dirs.py`, `core/config_secrets.py`, `core/config_validators.py`,
  `core/config_observability.py`, `core/config_postgres.py`: dizin, secret,
  validasyon, telemetry ve PostgreSQL yardımcıları. `core/config_observability.py`
  artık yalnızca ayar yükleme değil, `Config.init_telemetry()`'nin gerçek
  OpenTelemetry enstrümantasyon mantığını da barındırır (bkz. aşağıdaki
  "Devam eden konsolidasyon" bölümü).
- `core/config_scoped_settings.py`: `core/config_llm.py` ve `core/config_quality.py`'nin
  paylaştığı, dotenv'e scoped `BaseSettings` alt sınıfı üreten `build_scoped_settings_type()`
  helper'ı — mypy `--strict` altında pydantic-settings'in `_env_file=...` dinamik
  init kwarg'ından kaçınmak için `type(...)` ile throwaway subclass üretir; bir
  arkadaş kod incelemesinde bu ~15 satırlık blok iki dosyada birebir kopyalanmış
  hâlde bulundu ve tek yere indirildi.

> Not (Doğrulama): Eski tek dosya satır sayısı notları artık mimari kalite ölçütü
> değildir. `config.py` facade yüzeyi büyük kalabilir; refactor başarısı eski import
> path'lerinin kırılmaması ve domain helper'larının testlerle korunması üzerinden
> değerlendirilmelidir.

## Devam eden konsolidasyon: kalan büyük mantık blokları (P2)

`config.py`'nin `Config.FOO` alias yüzeyi (yüzlerce satırlık class attribute
tanımı) kasıtlı olarak burada kalır — yukarıdaki not bunun bir mimari borç
olmadığını açıkça belirtir. Ama sınıfın bazı metodları hâlâ gerçek,
`core/config_*.py`'ye taşınabilecek iş mantığı taşıyordu; bunlar
`core/config_dotenv.py`/`core/config_hardware.py`/vb.'nin zaten kurduğu
desenle (saf fonksiyon + `cls.FOO` değerlerini açık keyword argüman olarak
geçiren ince `classmethod` sarmalayıcı) tek tek taşınıyor:

- ✅ **Taşındı:** `Config.init_telemetry()` (~95 satır) →
  `core/config_observability.init_telemetry()`. `Config.init_telemetry`
  artık yalnızca `cls.ENABLE_TRACING`/`cls.OTEL_*` değerlerini (testlerin
  doğrudan monkeypatch ettiği canlı class attribute'lar) çözüp saf
  fonksiyona geçiren ~20 satırlık bir sarmalayıcı.
- ✅ **Taşındı (2026-09, 1.801 → 1.475 satır):**
  - `Config.validate_critical_settings()` ve `Config._validate_ai_provider_settings()` →
    `core/config_validation.py` (`validate_critical_settings`,
    `validate_ai_provider_settings`; Fernet anahtar kontrolü ve Ollama `/api/tags`
    probu kendi yardımcılarına ayrıldı).
  - `Config._log_dotenv_load_status()` ve modül seviyesindeki `_reload_dotenv_chain()` →
    `core/config_dotenv_reload.py` (`log_dotenv_load_status`, `reload_dotenv_chain`).
    Değiştirilebilir dotenv kayıtları (`_DOTENV_LOAD_EVENTS`, `_DOTENV_KEY_SOURCES`,
    `_DOTENV_MANAGED_KEYS`, `_LAST_DOTENV_LOAD_CHAIN_SIGNATURE`) `config.py`'de kalır ve
    her çağrıda parametre olarak geçirilir; böylece `importlib.reload(config)` ve bu
    globalleri değiştiren testler tek doğruluk kaynağını görmeye devam eder.
  - `Config._autoselect_ollama_coding_ctx_window()` içindeki VRAM kademe tablosu ve
    saha raporu gerekçesi → `core/config_gpu.py::ollama_coding_ctx_for_vram()`.
    Env override ve `USE_GPU` kontrolü facade'da kalır.
  - `Config.get_system_info()` / `Config.print_config_summary()` →
    `core/config_summary.py` (`build_system_info`, `print_config_summary`). Donanım
    bilgisinin lazy yüklenmesi facade'da kalır.

  Plandaki "yalnız değerleri geçir, `cls`'i alt modüle verme" hedefi bu dört blokta
  uygulanmadı: doğrulama akışı `cls._ensure_hardware_info_loaded()`,
  `cls._validate_ai_provider_settings()` gibi facade kancalarını çağırıyor ve
  `cls.AI_PROVIDER`'ı normalize ederek yeniden atıyor; özet görünümleri ise 30'dan fazla
  alan okuyor. Bu yüzden `core/config_secret_hardening.py` ve
  `core/config_runtime_env.py`'nin zaten izlediği desen kullanıldı: `Config` sınıfı
  parametre olarak geçer, facade kancaları hâlâ `cls` üzerinden çağrılır. Böylece
  `monkeypatch.setattr(config.Config, ...)` ile yazılmış testler davranışı birebir
  korur. `logger`, `_log_once_env` ve `localized_log_message` her çağrıda `config.py`
  globallerinden okunup açık keyword argüman olarak geçirilir. `PRODUCTION_SECRET_KEYS`
  ve `config_postgres.postgres_password_drift_messages` ise parametre olarak
  geçirilmez; `core/config_validation.py` onları çağrı anında kendi modüllerinden okur.
  CodeQL (`py/clear-text-logging-sensitive-data`) bu iki log satırını, `config.py`'deki
  hâlleri gibi, "hassas veri loglama" olarak işaretler: kaynak olarak
  `PRODUCTION_SECRET_KEYS` içindeki "SECRET" geçen anahtar adı sabitlerini ve drift
  kontrolündeki parola karşılaştırmasını görür. Loglanan şey değer değil, anahtar adı
  ve uyuşmayan URL açıklamasıdır; bu uyarılar false positive olarak kapatılır.

## God object değil, compatibility facade

`config.py` ilk bakışta geniş bir "god object" gibi görünebilir; güncel mimari
kararı bunun runtime ayarlarının tek doğruluk kaynağı olmasından değil, eski
`from config import Config` ve `import config` tüketicilerini kırmadan yaklaşık yirmi
domain ayar modülünü birleştiren compatibility facade olmasından kaynaklanır.
Tekrarlayan business logic bu dosyaya eklenmemelidir; yeni davranış önce
ilgili `core/config_*.py` modülündeki canonical helper/settings objesine konmalıdır.

Düşük riskli iyileştirmenin ilk adımı olarak `Config` artık canonical loader
sonuçlarını typed domain settings facade alias'larıyla da expose eder; tekil
`Config.FOO` alias'ları geriye dönük uyum için korunur. Devam eden hedefler:

- `Config.llm_settings` → `core.config_llm.LLM_SETTINGS` / `LLMClientSettings`
  tüketimini yeni kodda yaygınlaştırmak.
- `Config.security_settings` → `core.config_security.load_security_settings()`
  sonucunu yeni güvenlik tüketicilerinde tercih etmek.
- `Config.sandbox_settings`, `Config.observability_settings`,
  `Config.rate_limit_settings`, `Config.event_bus_settings` ve
  `Config.rag_store_settings` gibi domain objelerini yeni kodda canonical
  `core/config_*.py` loader sonuçları olarak tüketmek.
- Legacy `Config.FOO` alias'larını bir release boyunca koruyup yeni kodda domain
  objesi kullanımını tercih etmek.

Bu çalışma davranış değişikliği değil, facade yüzeyini küçültme kampanyasıdır;
her adım `tests/unit/root/test_config.py` içindeki import contract testleriyle
korunmalıdır.


## Yerleşim kuralı

Tüm config split modülleri tek pakette, `core/config_*.py` altında durur. Kök
dizinde yalnız `config.py` facade'ı bulunur; kökte yeni `config_*.py` modülü
eklenmemelidir (`tests/unit/root/test_config.py` bunu doğrular). Sıfır ek mantık
içeren pass-through wrapper eklenmemelidir; facade doğrudan canonical core
modülünden re-export etmelidir.

Eski kök modüller `core/` altına taşınmıştır: `config_gpu.py`, `config_llm.py`,
`config_quality.py`, `config_rag_defaults.py`, `config_security.py` aynı adla;
kök `config_autonomy.py` (self-heal varsayılanları) mevcut `core/config_autonomy.py`
ile çakışmaması için `core/config_self_heal.py` adıyla. Tüketicisi kalmayan legacy
`config_rag.py` shim'i kaldırılmıştır.

## Import uyumluluk sözleşmesi

Korunan legacy import örnekleri:

```python
import config
from config import Config, get_config, OLLAMA_BATCH_POLICY, SANDBOX_LIMITS
```

Bu yüzey `tests/unit/root/test_config.py` içinde korunur. Yeni kod, yalnızca `Config`
üzerindeki public ayarları tüketiyorsa `from config import Config` kullanabilir;
domain helper'a ihtiyaç duyuyorsa doğrudan split modülü tercih etmelidir:

```python
from core import config_env_helpers, config_llm, config_postgres
```

Yeni split modül eklendiğinde iki güvence birlikte sağlanmalıdır:

1. Eski `config.py` import path'iyle kullanılan public isimler kırılmamalıdır.
2. Yeni helper'ın canonical modülü ve `config.py` üzerindeki re-export davranışı
   `tests/unit/root/test_config.py` içinde doğrulanmalıdır.

## `Config` sınıfının ana parametre grupları

- **AI Sağlayıcı:** `AI_PROVIDER`, `GEMINI_API_KEY`, `OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, model seçim parametreleri.
- **Veritabanı:** `DATABASE_URL`, `DB_POOL_SIZE`, `DB_SCHEMA_VERSION_TABLE`,
  `DB_SCHEMA_TARGET_VERSION`.
- **Güvenlik:** `ACCESS_LEVEL`, `MEMORY_ENCRYPTION_KEY`, JWT/API key ayarları.
- **Docker Zero-Trust Sandbox:** `DOCKER_NETWORK_DISABLED`, `DOCKER_MEM_LIMIT`,
  `DOCKER_NANO_CPUS`, `DOCKER_MICROVM_MODE`, `DOCKER_ALLOWED_RUNTIMES`,
  `DOCKER_RUNTIME`, `DOCKER_EXEC_TIMEOUT`.
- **Observability:** `ENABLE_TRACING`, `OTEL_EXPORTER_ENDPOINT`, Prometheus/Grafana
  bağlantıları.
- **Rate Limiting:** `SIDAR_RATE_LIMIT_CHAT`, `SIDAR_RATE_LIMIT_MUTATIONS`,
  `SIDAR_RATE_LIMIT_GET_IO`, `SIDAR_RATE_LIMIT_WS_CONNECTIONS`, `SIDAR_REDIS_URL`
  ve legacy alias'lar.
- **RAG:** `RAG_DIR`, `RAG_TOP_K`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`,
  `RAG_FILE_THRESHOLD`.
- **Mimari:** `ENABLE_MULTI_AGENT`, `REVIEWER_TEST_COMMAND`, swarm/supervisor ve
  self-heal ayarları.

## Dikkat noktaları

- Donanım bilgisi lazy-load yaklaşımıyla alınır; import anında ağır GPU yan etkisi
  oluşturulmamalıdır.
- `reload_environment(...)` sonrası cached config referanslarını senkron tutmak için
  `register_config_reload_callback(...)` yüzeyi korunmalıdır.
- `get_config()` process-wide singleton döndürür; yeni kod gereksiz `Config()`
  üretmek yerine bu helper'ı tercih etmelidir.
- Split modüller `config.py` facade'ını import ederek döngü yaratmamalı; bağımlılık
  yönü domain helper → core helper veya `config.py` → domain helper şeklinde kalmalıdır.
