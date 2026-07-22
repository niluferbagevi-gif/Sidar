# 3.1 `config.py` — Merkezi yapılandırma facade'ı

## Güncel kaynak yerleşimi

`config.py` hâlâ projenin geriye dönük uyumlu ana import yüzeyidir; ancak ayar
sorumlulukları artık domain dosyalarına ayrılmıştır. Eski `from config import Config`
ve `import config` kalıpları desteklenmeye devam ederken, yeni yardımcılar aşağıdaki
modüllerden beslenir:

- `core/config_postgres.py`: PostgreSQL DSN üretimi, container DB URL'i ve pool
  varsayılanlarının canonical modülü; `config.py` bu helperları doğrudan re-export eder.
- `config_llm.py`: LLM provider/model ayarları, `LLMClientSettings` ve Ollama batch
  policy.
- `config_rag_defaults.py`: RAG chunk/top-k/semantic-cache varsayılanları; legacy `config_rag.py` yalnız backward-compatible shim olarak kalır.
- `config_security.py`: API/JWT/security secret ayarları ve production validation
  yardımcıları.
- `config_autonomy.py`, `config_gpu.py`: self-heal/otonomi ve GPU varsayılanları.
- `core/config_app.py`: uygulama adı, sürüm, debug, log ve runtime dil ayarları.
- `core/config_dotenv.py`, `core/config_env_helpers.py`, `core/config_runtime_env.py`:
  dotenv zinciri, type-safe env okuma ve reload-time override akışları.
- `core/config_dirs.py`, `core/config_secrets.py`, `core/config_validators.py`,
  `core/config_observability.py`, `core/config_postgres.py`: dizin, secret,
  validasyon, telemetry ve PostgreSQL yardımcıları.

> Not (Doğrulama): Eski tek dosya satır sayısı notları artık mimari kalite ölçütü
> değildir. `config.py` facade yüzeyi büyük kalabilir; refactor başarısı eski import
> path'lerinin kırılmaması ve domain helper'larının testlerle korunması üzerinden
> değerlendirilmelidir.

## God object değil, compatibility facade

`config.py` ilk bakışta geniş bir "god object" gibi görünebilir; güncel mimari
kararı bunun runtime ayarlarının tek doğruluk kaynağı olmasından değil, eski
`from config import Config` ve `import config` tüketicilerini kırmadan yaklaşık yirmi
domain ayar modülünü birleştiren compatibility facade olmasından kaynaklanır.
Tekrarlayan business logic bu dosyaya eklenmemelidir; yeni davranış önce
`config_llm.py`, `config_security.py`, `config_rag_defaults.py` veya `core/config_*.py`
modüllerindeki canonical helper/settings objesine konmalıdır.

Düşük riskli iyileştirmenin ilk adımı olarak `Config` artık canonical loader
sonuçlarını typed domain settings facade alias'larıyla da expose eder; tekil
`Config.FOO` alias'ları geriye dönük uyum için korunur. Devam eden hedefler:

- `Config.llm_settings` → `config_llm.LLM_SETTINGS` / `LLMClientSettings`
  tüketimini yeni kodda yaygınlaştırmak.
- `Config.security_settings` → `config_security.load_security_settings()`
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


## Kök/Core yerleşim kuralı

Config split modülleri için yerleşim kuralı:

- `core/config_*.py`: Runtime domain helperları, provider/domain-specific ayarlar ve
  başka modüller tarafından doğrudan tüketilebilen saf yardımcılar için canonical
  konumdur. PostgreSQL DSN/pool helperları bu nedenle `core/config_postgres.py`
  altında tutulur.
- Kök `config_*.py`: `config.py` facade'ına yakın, üst seviye orkestrasyon veya
  legacy import uyumluluğu gerektiren ayar grupları için kullanılır. Sıfır ek mantık
  içeren pass-through wrapper eklenmemelidir; facade doğrudan canonical core
  modülünden re-export etmelidir.

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
import config_llm
from core import config_env_helpers, config_postgres
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
