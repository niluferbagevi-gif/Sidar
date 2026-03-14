# 3.1 `config.py` — Merkezi Yapılandırma (589 satır)

**Amaç:** Tüm sistem ayarlarını tek noktada toplar; `.env` dosyasını yükler, donanım tespiti yapar ve v3.0 kurumsal çalışma profillerini merkezi olarak yönetir.

**Kritik Bileşenler:**

| Bileşen | Açıklama |
|---------|----------|
| `get_bool_env / get_int_env / get_float_env / get_list_env` | Type-safe ortam değişkeni okuma yardımcıları |
| `HardwareInfo` (dataclass) | CUDA/WSL2 donanım tespiti sonuçlarını tutar |
| `Config` (sınıf) | Tüm sistem parametrelerini sınıf attribute olarak toplar |
| `validate_critical_settings()` | Sağlayıcı anahtarları, şifreleme anahtarı ve kritik ayar doğrulamaları |

**`Config` Sınıfı Parametre Grupları (v3.0):**

- **AI Sağlayıcı:** `AI_PROVIDER`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, model seçim parametreleri
- **Veritabanı:** `DATABASE_URL`, `DB_POOL_SIZE`, `DB_SCHEMA_VERSION_TABLE`, `DB_SCHEMA_TARGET_VERSION`
- **Güvenlik:** `ACCESS_LEVEL`, `MEMORY_ENCRYPTION_KEY`
- **Docker Zero-Trust Sandbox:** `DOCKER_NETWORK_DISABLED`, `DOCKER_MEM_LIMIT`, `DOCKER_NANO_CPUS`, `DOCKER_MICROVM_MODE`, `DOCKER_ALLOWED_RUNTIMES`, `DOCKER_RUNTIME`, `DOCKER_EXEC_TIMEOUT`
- **Observability:** `ENABLE_TRACING`, `OTEL_EXPORTER_ENDPOINT`
- **Rate Limiting:** `RATE_LIMIT_CHAT`, `RATE_LIMIT_MUTATIONS`, `RATE_LIMIT_GET_IO`, `REDIS_URL`
- **RAG:** `RAG_DIR`, `RAG_TOP_K`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_FILE_THRESHOLD`
- **Mimari:** `ENABLE_MULTI_AGENT`, `REVIEWER_TEST_COMMAND`

**Dikkat Noktaları:**
- Donanım bilgisi lazy-load yaklaşımıyla alınır; import anında ağır GPU yan etkisi oluşturmaz.
- v3.0 ile DB ve sandbox parametreleri tek merkezden yönetildiği için runtime profiller arasında sapma riski düşürülmüştür.

---
