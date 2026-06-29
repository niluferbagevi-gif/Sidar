# 3.1 `config.py` — Merkezi yapılandırma facade'ı

## Güncel kaynak yerleşimi

`config.py` hâlâ projenin geriye dönük uyumlu ana import yüzeyidir; ancak ayar
sorumlulukları artık domain dosyalarına ayrılmıştır. Eski `from config import Config`
ve `import config` kalıpları desteklenmeye devam ederken, yeni yardımcılar aşağıdaki
modüllerden beslenir:

- `config_database.py`: PostgreSQL/SQLite DSN üretimi, container DB URL'i ve pool
  varsayılanları.
- `config_llm.py`: LLM provider/model ayarları, `LLMClientSettings` ve Ollama batch
  policy.
- `config_rag.py`: RAG chunk/top-k/semantic-cache varsayılanları.
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
import config_database
import config_llm
from core import config_env_helpers
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
  `SIDAR_RATE_LIMIT_GET_IO`, `SIDAR_REDIS_URL` ve legacy alias'lar.
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
