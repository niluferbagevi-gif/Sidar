# Sidar v5.2.0 — Güncel Mimari

> **Durum:** Aktif mimari doğruluk kaynağı
>
> **Runtime/paket baseline:** `v5.2.0`
>
> **Tarihsel belgeler:** `SIDAR_v5_0_MIMARI_RAPORU.md` ve
> `SIDAR_v5_1_MIMARI_RAPORU.md` faz kararlarını korur; güncel dosya/API envanteri
> olarak kullanılmamalıdır.

## 1. Sistem sınırları

Sidar; CLI, FastAPI/WebSocket sunucusu ve React SPA üzerinden kullanılan, async-first
çok ajanlı bir AI çalışma platformudur. Güncel omurga şu katmanlardan oluşur:

1. **Giriş yüzeyleri:** `main.py`, `cli.py`, `web_server.py`, `web_ui_react/`.
2. **Ajan kontrol düzlemi:** `agent/sidar_agent.py`, `agent/core/supervisor.py`,
   `agent/swarm.py`, `agent/registry.py` ve `agent/roles/`.
3. **Domain servisleri:** self-heal için `agent/self_heal/`, dış olaylar için
   `agent/triggers.py`, CI teşhisi için `core/ci_remediation.py`.
4. **AI ve bilgi katmanı:** `core/llm_client.py`, `core/rag.py`, `core/memory.py`,
   `core/voice.py`, `core/vision.py`, `core/multimodal.py`.
5. **Veri katmanı:** `core/db/` facade'ı, `core/db_components/`, PostgreSQL/pgvector,
   Redis ve Alembic migrasyonları.
6. **Operasyon:** `run_tests.sh` + `scripts/test_gates/`, `autonomous_loop.sh` +
   `scripts/autonomous_modules/`, Docker Compose, Helm ve CI workflow'ları.

## 2. Ajan orkestrasyonu

- `SupervisorAgent` intent sınıflandırması, role delegasyonu, reviewer kalite kapısı ve
  sınırlı P2P yönlendirmeyi yönetir.
- `SwarmOrchestrator` tekil, paralel, pipeline ve dağıtık görev yürütme biçimlerini;
  retry, handoff ve loop-guard sınırlarıyla uygular.
- Yerleşik roller `AgentCatalog` üzerinden keşfedilir. Coder, Researcher, Reviewer,
  QA, Coverage ve Poyraz rolleri capability sözleşmeleriyle kayıtlıdır.
- Process içi/uzak olay yayını `AgentEventBus` üzerinden Redis, RabbitMQ veya Kafka
  backend stratejilerine yönlenir; uzak backend arızasında local fanout korunur.

## 3. Self-heal ve dış olay akışları

`SidarAgent` çekirdek bağlam ve facade rolünü korur. Uzun domain akışları artık ayrı
sahiplik sınırlarındadır:

- `agent/self_heal/orchestrator.py`: HITL, planlama, patch uygulama, validation ve
  rollback ile bounded remediation.
- `agent/self_heal/planner.py`: scope batch çözümleme ve normalize edilmiş patch planı.
- `agent/triggers.py`: dış trigger doğrulama, korelasyon ve swarm/supervisor handoff.
- `core/ci_remediation.py`: başarısız kalite kapılarından deterministik remediation
  loop ve doğrulama komutları üretimi.

Scope dışı patch, doğrulamasız uygulama ve onaysız riskli işlem fail-closed durur.

## 4. İstemci ve gerçek zamanlı protokoller

React SPA güncel kullanıcı arayüzüdür. REST sözleşmeleri `web_ui_react/src/lib/api.ts`,
chat WebSocket protokolü `useWebSocket.ts`, chat state machine `useChatStore.ts` ve
voice protokolü `useVoiceAssistant.ts` üzerinden tipli olarak tüketilir. Duplex voice
akışı `/ws/voice`, VAD/commit ve barge-in kararlarını backend `core/voice.py` sözleşmesiyle
birlikte uygular.

Legacy `web_ui/` yalnız geriye dönük fallback'tir; yeni özellik geliştirme hedefi değildir.

## 5. Yapılandırma ve donanım

`config.py` uyumluluk facade'ıdır. Odaklı politika modülleri şunlardır:

- `core/config_dotenv.py`: dotenv reload planı.
- `core/config_hardware.py`: WSL2 algılama, donanım kontrolü ve VRAM fraction politikası.
- `core/config_security.py`, `config_llm.py`, `config_gpu.py`, `config_quality.py`,
  `config_rag.py`, `config_autonomy.py`: domain ayarları.

Paket ve runtime sürüm doğruluk zinciri `pyproject.toml` ile `sidar_version.py`dır.

## 6. Veri, RAG ve güvenlik

- SQL değerleri parametreli gönderilir; dinamik identifier'lar ortak dialect
  doğrulayıcılarından geçirilir.
- PostgreSQL/pgvector kurumsal kalıcı veri omurgası, Redis cache/event koordinasyon
  katmanıdır; SQLite yalnız desteklenen lokal/uyumluluk senaryolarında kullanılır.
- RAG; vector, BM25 ve GraphRAG ilişkisel kanıtlarını ortak erişim politikaları altında
  birleştirir.
- Tenant/RBAC, DLP, audit trail, sandbox ve HITL kontrolleri dış girdiler ile yan etkili
  araçlar arasında savunma katmanlarıdır.

## 7. Kalite ve release kanıtı

- `run_tests.sh` yalnız gate sırası ve birleşik sonuç orkestrasyonunu tutar; uygulamalar
  `scripts/test_gates/` modüllerindedir.
- `autonomous_loop.sh` retry ve döngü politikasını tutar; CoverageAgent, static-analysis
  ve auto-heal domainleri `scripts/autonomous_modules/` altındadır.
- Yerel `production_ready=true` self-hosted GPU TTFT/latency kanıtı değildir.
  Merge/release için `GPU Inference Quality Gate`, `GPU Inference Required Evidence Gate`
  ve `Production readiness aggregate` güncel commit üzerinde geçmelidir.

## 8. Belge haritası

- Kapsamlı rapor bölümleri: [`PROJE_RAPORU.md`](PROJE_RAPORU.md)
- Teknik/operasyonel referans: [`TEKNIK_REFERANS.md`](TEKNIK_REFERANS.md)
- Test ve release gate'leri: [`TESTING.md`](TESTING.md)
- Required check sözleşmesi: [`CI_REQUIRED_CHECKS.md`](CI_REQUIRED_CHECKS.md)
- Multi-agent RFC: [`RFC-MultiAgent.md`](RFC-MultiAgent.md)
