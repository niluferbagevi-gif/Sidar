# Sidar Proje Raporu — Genel Bakış ve Mimari

> Aktif ürün baseline: **v5.2.0**. Bu dosya, [`PROJE_RAPORU.md`](../PROJE_RAPORU.md) indeksinin bölümüdür.

<a id="içindekiler"></a>
## Bu dosyadaki bölümler

- Bölüm 1
- Bölüm 2
- Bölüm 3
- Bölüm 4

---

## 1. Proje Genel Bakışı

[⬆ İçindekilere Dön](#içindekiler)

**Sidar**, ReAct (Reason + Act) döngüsüyle çalışan, async-first mimariye sahip bir yazılım mühendisi AI asistanıdır. Yerel LLM (Ollama) veya bulut tabanlı LLM'ler (Google Gemini, OpenAI, Anthropic ve LiteLLM Gateway/OpenRouter benzeri ara katmanlar) ile çalışabilir; CLI, FastAPI tabanlı Web UI ve opsiyonel Eel masaüstü launcher sunar.

### Temel Özellikler
- **Arayüzler:** CLI (`cli.py`), Web (`web_server.py` + `web_ui_react/dist` React SPA build'i; legacy `web_ui/` kaldırılmıştır) ve opsiyonel Eel launcher (`gui_launcher.py`)
- **Çoklu LLM sağlayıcı:** Ollama (yerel), Gemini, OpenAI, Anthropic ve LiteLLM Gateway (bulut/proxy)
- **Multi-Agent + P2P Delegasyon:** Supervisor orkestrasyonu ile görevleri uzman rollere (Coder, Researcher, Reviewer) dağıtır; `agent/core/contracts.py` ile ajanlar arası P2P görev sözleşmesi desteklenir.
- **Dinamik Ajan Pazaryeri (Plugin Marketplace) ve Swarm API:** Çalışma zamanında yeni plugin ajanlar kayıt defterine eklenebilir; `AgentRegistry` + `SwarmOrchestrator` ile paralel veya pipeline görev akışları işletilir (`agent/registry.py`, `agent/swarm.py`).
- **Dinamik Prompt Yönetimi (Prompt Registry):** Sistem prompt'ları statik kod yerine veritabanı destekli registry üzerinden sürümlenebilir, etkinleştirilebilir ve Admin UI üzerinden yönetilebilir.
- **Çoklu Kullanıcı (Multi-User) ve Veritabanı Altyapısı:** PostgreSQL/SQLite destekli kalıcı veri katmanı ile kullanıcı bazlı oturum izolasyonu ve kota yönetimi (`core/db/`).
- **Telemetri ve Bütçe İzleme:** Grafana ve Prometheus entegrasyonu ile LLM API maliyetleri (USD), token tüketimi ve gecikme (latency) takibi (`core/llm_metrics.py`). Semantic cache hit/miss Grafana dashboard'u (`grafana/dashboards/sidar_overview.json`).
- **Anlamsal Önbellekleme (Semantic Cache):** Redis tabanlı, cosine similarity ile benzer istemleri eşleştiren ve LRU eviction uygulayan önbellek katmanı; token maliyetini ve yanıt gecikmesini düşürür (`core/llm_client.py`).
- **Canlı Ajan Durum Akışı (Observability):** WebSocket tabanlı event stream ile düşünce adımları, araç çağrıları ve ajan durumları Web UI'da canlı izlenir (`agent/core/event_stream.py`).
- **Dağıtık İzlenebilirlik (Distributed Tracing):** OpenTelemetry span enstrümantasyonu ile tüm 5 LLM sağlayıcısı ve RAG akışları Jaeger/OTel Collector uyumlu biçimde uçtan uca waterfall görünümünde izlenebilir (`web_server.py`, `core/llm_client.py`, `core/rag/`).
- **Admin paneli ve operasyon yüzeyi:** Legacy Web UI admin paneli toplam kullanıcı, toplam API isteği, toplam token ve kullanıcı bazlı günlük kotaları gösterir; React tarafındaki Prompt Admin/Agent Manager ekranları backend ile entegredir, `TenantAdminPanel` ise şu an örnek/demo senaryo panelidir.
- **Tenant Bazlı RBAC ve Audit Trail:** Çok kiracılı erişim politikaları (`tenant_id`) uygulanır; tüm izin kararları audit log olarak kalıcı biçimde kaydedilir (`web_server.py`, `core/db/`).
- **QA ve Regresyon Sinyali:** Coder ajanı ile ortak çalışan, üretilen kodu test edip onaylayan/reddeden gelişmiş `ReviewerAgent` döngüsü.
- **GitHub Entegrasyonu:** Repo analizi, branch/PR ve issue akışları `managers/github_manager.py`; GitHub release bilgileri ise `managers/package_info.py` üzerinden ajan araç setine entegredir.
- **ReAct döngüsü:** LLM → Araç çağrısı → Gözlem → LLM (maks. `MAX_REACT_STEPS` adım)
- **Görev Takibi ve Proje Denetimi:** `managers/todo_manager.py` ile TODO yazma/okuma/güncelleme ve proje genelinde `scan_project_todos()` üzerinden TODO/FIXME taraması yapılır.
- **RAG + Reviewer Etki Analizi (Faz B Tamamlandı):** ChromaDB veya pgvector + BM25 + keyword hibrit arama (RRF destekli) akışına ek olarak GraphRAG, modül bağımlılık grafiği taraması, bağımlılık yolu açıklaması ve reviewer kalite kapısında kullanılan etki analizi raporlarını üretir (`core/rag/`, `agent/roles/reviewer_agent.py`).
- **Güvenlik:** OpenClaw 3 katmanlı erişim sistemi (restricted / sandbox / full)
- **Zero-Trust Sandbox:** Docker izolasyonuna ek olarak ağ kapatma, CPU/RAM sınırlandırma ve gVisor/Kata uyumluluğuna hazır çalışma modeliyle güvenli kod yürütme.
- **GPU desteği:** CUDA, FP16, çoklu GPU, WSL2 uyumu
- **Bellek:** Veritabanı destekli kalıcı konuşma belleği vardır; `MEMORY_ENCRYPTION_KEY` için yapılandırma/doğrulama desteği bulunur, ancak mevcut DB mesaj kayıtları ayrıca şifrelenmiş saklanmamaktadır.
- **DLP & PII Maskeleme:** Bulut LLM'lere gitmeden önce Bearer token, API key, TC kimlik no, e-posta, kredi kartı, JWT gibi hassas verileri otomatik maskeler (`core/dlp.py`).
- **Human-in-the-Loop (HITL) Onay Geçidi:** Kritik/yıkıcı işlemler öncesinde async polling tabanlı kullanıcı onayı; Web API üzerinden onay/ret akışı (`core/hitl.py`).
- **LLM-as-a-Judge Kalite Değerlendirmesi:** RAG alaka puanı ve halüsinasyon riski arka planda ölçülür; Prometheus metrikleri ve Grafana panellerine yansır (`core/judge.py`).
- **Cost-Aware Model Routing:** Sorgu karmaşıklığına + günlük bütçeye göre lokal/bulut model seçimi (`core/router.py`).
- **Entity/Persona Memory:** Kullanıcı başına kodlama stili, framework tercihi, verbosity gibi uzun vadeli kişiselleştirilmiş bellek; TTL + LRU eviction (`core/entity_memory.py`).
- **Active Learning + LoRA/QLoRA Fine-tuning:** Onaylanan çıktılardan veri seti oluşturma (jsonl/alpaca/sharegpt), SQLite/PG async FeedbackStore, PEFT entegrasyonu (`core/active_learning.py`).
- **Multimodal Vision Pipeline:** UI mockup/görsel → kod üretimi; OpenAI/Anthropic/Gemini/Ollama provider formatları, base64 görsel yükleme (`core/vision.py`).
- **Multimodal Perception + Duplex Voice (Tamamlandı / Faz B):** `core/multimodal.py`, `/ws/voice` ve `core/voice.py` ile medya ingestion, STT, assistant turn kimliği, duplex output buffer, VAD olayları ve barge-in destekli TTS segmentasyon akışı ürünleşmiş durumda.
- **İstemci Tarafı Ses Deneyimi (Faz C derinleşmesi):** `VoiceAssistantPanel.tsx` ve `useVoiceAssistant.ts`, mikrofon izni, `MediaRecorder` akışı, VAD durum takibi, transcript diyagnostiği ve kullanıcının SİDAR konuşmasını kesebilmesini React UI üzerinde görünür hale getirir.
- **Otonom Remediation / Self-Healing (Faz C):** `core/ci_remediation.py`, `agent/sidar_agent.py`, `agent/roles/reviewer_agent.py` ve `managers/code_manager.py` birlikte düşük riskli CI arızaları için patch planı üretir, sandbox'ta doğrular, gerekirse rollback yapar ve yüksek riskte HITL kapısına döner.
- **Nightly Memory Pruning / Konsolidasyon (Faz D):** Sistem idle kaldığında `ConversationMemory` eski oturumları özetleyip sıkıştırır, `DocumentStore` aynı oturumdaki düşük değerli RAG belgelerini `memory://nightly-digest` özetine konsolide eder ve `EntityMemory` TTL bakımını çalıştırır; böylece uzun soluklu projelerde hafıza bir insan gibi tazelenir.
- **Dynamic Browser Automation (Tamamlandı / v5.0-alpha):** `managers/browser_manager.py` Playwright/Selenium sağlayıcı soyutlaması, zorunlu HITL geçidi, audit trail ve reviewer/swarm akışına taşınabilen browser signal özetleri ile kontrollü tarayıcı oturumlarını yönetiyor.
- **Proaktif Otonomi + Swarm Federation (Tamamlandı / Faz B):** `web_server.py` içinde `/ws/voice`, `/api/autonomy/webhook/{source}`, `/api/swarm/federation`, `/api/swarm/federation/feedback` ve `ENABLE_AUTONOMOUS_CRON` tabanlı cron tetikleyicisi ile sistem reaktif modelden kontrollü proaktif/federe co-worker modeline genişliyor.
- **Canlı Operasyon Yüzeyi (Tamamlandı / Faz B):** `web_ui_react/src/components/SwarmFlowPanel.tsx`, `core/hitl.py` ve ilgili HITL API'leri ile görsel karar grafiği artık sadece izleme değil; seçili düğümden görev türetme, hedefli rerun ve bekleyen onayları yönetme yüzeyi olarak da çalışıyor.
- **Jira / Slack / Teams Entegrasyonu:** Jira Cloud REST API v3, Slack Bot SDK + Webhook fallback (Block Kit), Teams MessageCard + Adaptive Card v1.4 ve HITL onay kartı (`managers/jira_manager.py`, `managers/slack_manager.py`, `managers/teams_manager.py`).
- **Kök kontrol düzlemi doğrulaması (v5.0-alpha / Faz B):** `main.py` sihirbaz + quick-start başlatma katmanı, `cli.py` tek event-loop CLI oturumu, `web_server.py` geniş FastAPI kontrol düzlemi (mevcut dosyada **88** route/websocket decorator; **86** REST + **2** WebSocket), `config.py` bootstrap/telemetry yükleme yolu, `github_upload.py` güvenli `git ls-files` paketleme akışı ve `gui_launcher.py` Eel köprüsü mevcut repo durumu ile yeniden teyit edilmiştir.
- **Son doğrulama notu (v3.0.30):** `core/entity_memory.py`, `core/cache_metrics.py`, `core/judge.py`, `core/vision.py`, `core/active_learning.py`, `core/hitl.py`, `core/llm_client.py` ve `web_server.py` üzerindeki D-8..D-14 düzeltmeleri yeniden gözden geçirilmiş; incelenen modüllerde kritik açık bir bulguya rastlanmadığı rapora işlenmiştir.


### Mevcut Durum ve Tamamlanan Özellikler

- **Plugin Marketplace (Faz D):** `PluginMarketplacePanel.tsx` çalışma zamanında yüklenen ajan eklentilerini UI üzerinden görünür kılar; `tests/unit/web/routes/test_plugin_marketplace.py` ise marketplace eklentilerinin install/uninstall/reload zincirini, `tests/unit/root/test_web_server.py` de `reload_plugin_marketplace_item` üzerinden kesintisiz hot-reload akışını doğrular.
- **Multiplayer Collaboration Workspace (Faz D):** `AgentManagerPanel.tsx` ve `useWebSocket.ts`, çoklu operatörün aynı çalışma yüzeyini paylaşabildiği anlık durum senkronizasyonunu taşır; `tests/unit/web/routes/test_collaboration.py` bu çok kullanıcılı orkestrasyon davranışını regresyon güvencesine bağlar.
- **Nightly Memory Maintenance (Faz D):** `tests/unit/agent/maintenance/test_nightly.py` ile doğrulanan gece bakım döngüsü, PGVector/RAG belleğinin şişmesini önlemek için oturum özetleme, belge konsolidasyonu ve TTL temizliğini planlı biçimde uygular.
- **Chaos Engineering Hazırlığı (Faz D):** `runbooks/chaos_live_rehearsal.md` ve `tests/unit/managers/test_system_health.py`, PostgreSQL veya Redis kesintilerinde sistemin fail-safe davranmasını ve operasyon ekibinin tekrar prova edilebilir bir kurtarma akışı izlemesini sağlar.

### SİDAR'ın Geleceği: Otonom Şirket Simülasyonu

Faz E vizyonu artık SİDAR'ı yalnızca yazılım geliştiren bir AI yardımcı olmaktan çıkarıp yazılım, pazarlama, operasyon ve içerik üretimini tek bir otonom ekosistemde birleştiren **otonom şirket simülasyonu** katmanına taşımış durumdadır. Bu fazda devreye alınan yakın dönem odakları şunlardır:

- **Coverage Agent:** `agent/roles/coverage_agent.py` swarm rolü eklendi; ajan `CodeManager` üzerinden `pytest` komutlarını koşturuyor, pytest çıktısını analiz ediyor, eksik test adayları üretiyor, önerilen test dosyasını yazıyor ve bulguları `coverage_tasks` / `coverage_findings` yüzeyine kaydediyor. `%90` test kapsama kalite kapısı artık yalnızca statik eşik değil, aktif test üretim döngüsüyle de destekleniyor.
- **Poyraz (Dijital Pazarlama ve Operasyon Uzmanı):** `agent/roles/poyraz_agent.py` devreye alındı; `WebSearchManager`, `SocialMediaManager`, `DocumentStore` ve `core.multimodal.MultimodalPipeline` entegrasyonları ile Instagram/Facebook/WhatsApp yayınlama, landing page üretimi, kampanya kopyası hazırlama, video içgörüsü ingest etme ve operasyon checklist'i oluşturma akışları fiilen sisteme eklendi.
- **YouTube ve Genişletilmiş Multimodal Zeka:** `core/multimodal.py` hattı Poyraz içinde `ingest_video_insights` aracıyla kullanılmaya başlandı; dış video URL'lerinden çıkarılan sahne özeti ve ingest edilen içerik, pazarlama/operasyon çıktısına dönüştürülen aktif veri kaynağı olarak konumlandı.

---

## 2. Proje Dosya Yapısı

[⬆ İçindekilere Dön](#içindekiler)

<pre>
Sidar/
├── .github/workflows/              # 18 iş akışı: ci, release-quality, codeql, migration-cutover-checks, nightly/weekly GPU/benchmark/mutasyon
├── <a href="../module-notes/main.py.md">main.py</a>                         # Akıllı başlatıcı (launcher/ paketine delege eden TUI giriş noktası)
├── <a href="../module-notes/cli.py.md">cli.py</a>                          # CLI terminal arayüzü giriş noktası
├── <a href="../module-notes/web_server.py.md">web_server.py</a>                   # FastAPI web sunucusu giriş noktası (uygulama web/ paketinde)
├── <a href="../module-notes/config.py.md">config.py</a>                       # Merkezi yapılandırma facade'ı (ayrıntılar core/config_*.py modüllerinde)
├── sidar_version.py                # Sürüm çözümleme (pyproject.toml kaynaklı)
├── <a href="../module-notes/github_upload.py.md">github_upload.py</a>                # GitHub otomatik yükleme aracı (uploader/ paketine delege eder)
├── <a href="../module-notes/gui_launcher.py.md">gui_launcher.py</a>                 # Eel tabanlı masaüstü başlatıcı giriş noktası
├── <a href="../module-notes/Dockerfile.md">Dockerfile</a>                      # CPU + GPU (GPU_ENABLED build arg) çift mod imajı
├── Dockerfile.production           # Production imajı
├── <a href="../module-notes/docker-compose.yml.md">docker-compose.yml</a>              # Çekirdek yığın: redis, postgres, ollama, sidar-migrate, docker-socket-proxy, sidar-ai, sidar-web
├── <a href="../module-notes/docker-compose.gpu.yml.md">docker-compose.gpu.yml</a>          # GPU overlay: ollama-gpu, sidar-gpu, sidar-web-gpu
├── <a href="../module-notes/docker-compose.observability.yml.md">docker-compose.observability.yml</a> # Gözlemlenebilirlik: jaeger, prometheus, grafana, exporter'lar, cadvisor
├── docker-compose.production.yml   # Production compose profili
├── <a href="../module-notes/pyproject.toml.md">pyproject.toml</a>                  # Bağımlılık extras'ları, Ruff/Mypy/Pytest/Coverage (%100 fail_under) ayarları
├── uv.lock                         # uv paket yöneticisi kilit dosyası
├── <a href="../module-notes/alembic.ini.md">alembic.ini</a>                     # Veritabanı geçiş (migration) ayarları
├── Makefile                        # Geliştirici/CI hedefleri (make dev-full, production-readiness vb.)
├── <a href="../module-notes/run_tests.sh.md">run_tests.sh</a>                    # Kalite kapısı ve test çalıştırıcı betik
├── autonomous_loop.sh              # Otonom test/coverage/mutasyon iyileştirme döngüsü
├── <a href="../module-notes/install_sidar.sh.md">install_sidar.sh</a>                # Otomatik kurulum betiği (modülleri scripts/install_modules/ altında)
│
├── agent/
│   ├── <a href="../module-notes/agent/sidar_agent.py.md">sidar_agent.py</a>              # Ana ajan bağlayıcısı
│   ├── <a href="../module-notes/agent/base_agent.py.md">base_agent.py</a>               # BaseAgent soyut sınıfı (multi-agent iskeleti)
│   ├── <a href="../module-notes/agent/auto_handle.py.md">auto_handle.py</a>              # Anahtar kelime tabanlı hızlı yönlendirici (.heal vb.)
│   ├── <a href="../module-notes/agent/definitions.py.md">definitions.py</a>              # Sistem istemi ve ajan kimliği
│   ├── <a href="../module-notes/agent/tooling.py.md">tooling.py</a>                  # Araç kayıt + Pydantic şema yöneticisi
│   ├── <a href="../module-notes/agent/bootstrap.py.md">bootstrap.py</a>                # SidarAgent başlatma log yardımcıları
│   ├── <a href="../module-notes/agent/registry.py.md">registry.py</a>                 # AgentCatalog: dekoratör tabanlı rol/capability kaydı
│   ├── <a href="../module-notes/agent/swarm.py.md">swarm.py</a>                    # SwarmOrchestrator + TaskRouter (paralel/pipeline/P2P)
│   ├── <a href="../module-notes/agent/triggers.py.md">triggers.py</a>                 # Dış otonomi tetikleyicilerinin eşleştirilmesi ve işlenmesi
│   ├── <a href="../module-notes/agent/autonomy.md">autonomy/</a>                   # SidarAgent otonomi servisi
│   ├── <a href="../module-notes/agent/federation.md">federation/</a>                 # Ajan federasyon servisi
│   ├── <a href="../module-notes/agent/github.md">github/</a>                     # GitHub araç yardımcıları (smart_pr)
│   ├── <a href="../module-notes/agent/maintenance.md">maintenance/</a>                # Gece bakım işleri (nightly)
│   ├── <a href="../module-notes/agent/self_heal.md">self_heal/</a>                  # Self-healing: planner, executor, orchestrator
│   ├── <a href="../module-notes/agent/services.md">services/</a>                   # SidarAgent yanıt ve araç servisleri
│   ├── core/
│   │   ├── <a href="../module-notes/agent/core/supervisor.py.md">supervisor.py</a>           # Merkezi yönlendirici ve kalite kapısı
│   │   ├── <a href="../module-notes/agent/core/contracts.py.md">contracts.py</a>            # TaskEnvelope/TaskResult + P2P delegasyon sözleşmeleri
│   │   ├── <a href="../module-notes/agent/core/event_stream.py.md">event_stream.py</a>         # AgentEventBus: yerel fanout + uzak backend
│   │   ├── <a href="../module-notes/agent/core/memory_hub.py.md">memory_hub.py</a>           # Multi-agent bellek merkezi
│   │   ├── <a href="../module-notes/agent/core/registry.py.md">registry.py</a>             # ActiveAgentRegistry
│   │   ├── <a href="../module-notes/agent/core/circuit_breaker.py.md">circuit_breaker.py</a>      # Swarm/P2P koordinasyonu için devre kesiciler
│   │   └── event_backends/         # Redis / RabbitMQ / Kafka backend stratejileri
│   └── roles/
│       ├── <a href="../module-notes/agent/roles/coder_agent.py.md">coder_agent.py</a>          # Kod üretimi, dosya I/O, terminal
│       ├── <a href="../module-notes/agent/roles/researcher_agent.py.md">researcher_agent.py</a>     # Web + RAG araştırma
│       ├── <a href="../module-notes/agent/roles/reviewer_agent.py.md">reviewer_agent.py</a>       # Kod inceleme, güvenlik, kalite
│       ├── <a href="../module-notes/agent/roles/qa_agent.py.md">qa_agent.py</a>             # Test stratejisi ve CI remediation
│       ├── <a href="../module-notes/agent/roles/coverage_agent.py.md">coverage_agent.py</a>       # Coverage analizi + deterministik test üretimi
│       ├── <a href="../module-notes/agent/roles/poyraz_agent.py.md">poyraz_agent.py</a>         # Pazarlama, SEO, kampanya ve sosyal yayın
│       ├── <a href="../module-notes/agent/roles/coverage.md">coverage/</a>               # CoverageAgent araçları (analyzer, generator, batch_heal, config)
│       └── reviewer/               # ReviewerAgent yardımcıları (judge)
│
├── core/
│   ├── <a href="../module-notes/core/llm_client.py.md">llm_client.py</a>               # LLM facade'ı (sağlayıcı adaptörleri llm/ altında)
│   ├── <a href="../module-notes/core/llm.md">llm/</a>                        # Ollama / OpenAI / Anthropic / Gemini / LiteLLM adaptörleri, router, streaming
│   ├── <a href="../module-notes/core/llm_metrics.py.md">llm_metrics.py</a>              # Token, maliyet ve Prometheus metrikleri
│   ├── <a href="../module-notes/core/memory.py.md">memory.py</a>                   # Kalıcı çok oturumlu bellek (DB destekli)
│   ├── <a href="../module-notes/core/entity_memory.py.md">entity_memory.py</a>            # Entity/Persona belleği (TTL+LRU)
│   ├── <a href="../module-notes/core/db.py.md">db/</a>                         # Veritabanı paketi: bağlantı, kullanıcı, kota ve audit tabloları
│   ├── <a href="../module-notes/core/db_components.md">db_components/</a>              # core.db facade'ından ayrıştırılan dialect/migration yardımcıları
│   ├── <a href="../module-notes/core/rag.py.md">rag/</a>                        # pgvector/ChromaDB + BM25 + GraphRAG hibrit RAG paketi
│   ├── <a href="../module-notes/core/cache.md">cache/</a>                      # Semantic cache (semantic_cache.py)
│   ├── <a href="../module-notes/core/cache_metrics.py.md">cache_metrics.py</a>            # Cache hit/miss metrikleri
│   ├── doctor/                     # Kurulum/çalışma zamanı sağlık kontrolleri (checks/)
│   ├── config_*.py                 # 42 alan bazlı yapılandırma modülü (config.py tarafından birleştirilir)
│   ├── <a href="../module-notes/core/agent_metrics.py.md">agent_metrics.py</a>            # Ajan bazlı metrikler
│   ├── <a href="../module-notes/core/dlp.py.md">dlp.py</a>                      # DLP & PII maskeleme
│   ├── <a href="../module-notes/core/hitl.py.md">hitl.py</a>                     # Human-in-the-Loop onay geçidi
│   ├── <a href="../module-notes/core/judge.py.md">judge.py</a>                    # LLM-as-a-Judge: RAG alaka + halüsinasyon riski
│   ├── <a href="../module-notes/core/router.py.md">router.py</a>                   # Cost-aware model routing
│   ├── <a href="../module-notes/core/active_learning.py.md">active_learning.py</a>          # Active Learning + LoRA/QLoRA
│   ├── <a href="../module-notes/core/ci_remediation.py.md">ci_remediation.py</a>           # CI/self-heal remediation payload üretimi
│   ├── <a href="../module-notes/core/embeddings.py.md">embeddings.py</a>               # SentenceTransformer yükleme, önbellek ve cihaz seçimi
│   ├── <a href="../module-notes/core/models.py.md">models.py</a>                   # Migration'lar için SQLAlchemy şema modelleri
│   ├── <a href="../module-notes/core/vision.py.md">vision.py</a>                   # Vision pipeline: UI mockup → kod, görsel analiz
│   ├── <a href="../module-notes/core/multimodal.py.md">multimodal.py</a>               # Video/ses ingest, frame çıkarma, Whisper STT
│   ├── <a href="../module-notes/core/voice.py.md">voice.py</a>                    # TTS, VAD ve WebRTC ses akışı
│   ├── llm_pricing.py, logging_config.py, distributed_lock.py, test_fixture_policy.py ...
│   └── utils/                      # Ortak yardımcılar (trusted_subprocess vb.)
│
├── managers/
│   ├── <a href="../module-notes/managers/code_manager.py.md">code_manager.py</a>             # Dosya I/O + sandbox REPL + denetim (ayrıntılar code/ altında)
│   ├── <a href="../module-notes/managers/security.py.md">security.py</a>                 # OpenClaw erişim kontrolü
│   ├── <a href="../module-notes/managers/github_manager.py.md">github_manager.py</a>           # GitHub API entegrasyonu
│   ├── <a href="../module-notes/managers/system_health.py.md">system_health.py</a>            # CPU/RAM/GPU izleme
│   ├── <a href="../module-notes/managers/web_search.py.md">web_search.py</a>               # Tavily + Google + DuckDuckGo arama
│   ├── <a href="../module-notes/managers/package_info.py.md">package_info.py</a>             # PyPI + npm + GitHub Releases
│   ├── <a href="../module-notes/managers/todo_manager.py.md">todo_manager.py</a>             # Görev takibi
│   ├── <a href="../module-notes/managers/browser_manager.py.md">browser_manager.py</a>          # Playwright/Selenium + HITL korumalı tarayıcı otomasyonu
│   ├── <a href="../module-notes/managers/social_media_manager.py.md">social_media_manager.py</a>     # Instagram/Facebook/WhatsApp yayını (deneysel, opt-in)
│   ├── <a href="../module-notes/managers/youtube_manager.py.md">youtube_manager.py</a>          # YouTube transkript/medya
│   ├── <a href="../module-notes/managers/image_resolver.py.md">image_resolver.py</a>           # Docker imaj adı çözümleme ve GPU imaj tespiti
│   ├── <a href="../module-notes/managers/slack_manager.py.md">slack_manager.py</a>            # Slack Bot SDK + Webhook
│   ├── <a href="../module-notes/managers/jira_manager.py.md">jira_manager.py</a>             # Jira Cloud REST API v3
│   ├── <a href="../module-notes/managers/teams_manager.py.md">teams_manager.py</a>            # Teams MessageCard + Adaptive Card
│   └── code/                       # CodeManager alt modülleri
│
├── web/                            # FastAPI uygulaması (web_server.py bu paketi çalıştırır)
│   ├── app_factory.py, bootstrap.py, security.py, collaboration_service.py, autonomy_bridge.py, process_lifecycle.py
│   ├── routes/                     # REST + WebSocket (/ws/chat, /ws/voice) route'ları
│   ├── middleware/                 # Middleware zinciri
│   └── plugins/                    # Plugin marketplace API
│
├── launcher/                       # main.py başlatıcısının paketleri (preflight, wizard, doctor, ui ...)
├── uploader/                       # github_upload.py paketleri (gates, git_ops, github_api ...)
│
├── migrations/                     # Alembic veritabanı geçişleri
│   ├── <a href="../module-notes/migrations/env.py.md">env.py</a>
│   ├── <a href="../module-notes/migrations/script.py.mako.md">script.py.mako</a>
│   └── versions/
│       ├── <a href="../module-notes/migrations/versions/0001_baseline_schema.py.md">0001_baseline_schema.py</a> # Temel şema (users, sessions, messages, quotas)
│       ├── 0002_prompt_registry.py # Prompt registry
│       ├── 0003_audit_trail.py     # Tenant RBAC audit trail
│       ├── 0004_faz_e_tables.py    # Faz E kampanya/içerik/coverage tabloları
│       ├── 0005_pgvector_hnsw_index.py # pgvector HNSW indeksi
│       ├── 0006_access_control_schema.py # Erişim kontrol şeması
│       └── 0007_faz_e_defaults_parity.py # Faz E varsayılan değer paritesi
│
├── scripts/                        # Operasyon, CI, kurulum ve metrik betikleri
│   ├── auto_heal.py                # Yerel mypy self-heal köprüsü
│   ├── coverage_hotspots.py        # Düşük coverage dosyalarını listeler
│   ├── coverage_ratchet.py         # fail_under değerini yalnız yukarı taşır
│   ├── seed_rag.py                 # RAG deposunu proje dokümanlarıyla tohumlar
│   ├── check_env_parity.sh         # config.py ↔ .env.example parite doğrulaması
│   ├── <a href="../module-notes/scripts/install_host_sandbox.sh.md">install_host_sandbox.sh</a>     # Zero-trust sandbox (gVisor/Kata) hazırlığı
│   ├── <a href="../module-notes/scripts/load_test_db_pool.py.md">load_test_db_pool.py</a>        # DB bağlantı havuzu yük testi
│   ├── <a href="../module-notes/scripts/migrate_sqlite_to_pg.py.md">migrate_sqlite_to_pg.py</a>     # SQLite → PostgreSQL geçiş aracı
│   ├── doctor_production_readiness.py # Production hazırlık doktoru
│   ├── ci/                         # CI kapıları (check_doc_links.py, ruff/docstring ratchet, policy tarihleri ...)
│   ├── install_modules/            # install_sidar.sh modülleri
│   ├── test_gates/                 # run_tests.sh kapı yardımcıları
│   └── ...                         # diğer sync/audit/secret yardımcıları
│
├── runbooks/                       # Operasyonel kılavuzlar
│   ├── <a href="../module-notes/runbooks/production-cutover-playbook.md.md">production-cutover-playbook.md</a> # Kurumsal sürüme geçiş
│   ├── chaos_live_rehearsal.md     # Canlı kaos tatbikatı
│   ├── mypy_self_heal_strategy.md  # mypy self-heal stratejisi
│   ├── observability_simulation.md # Jaeger + Redis + PG izlenebilirlik demosu
│   ├── plugin_marketplace_demo.md  # Plugin yükleme + ajan çağırma demosu
│   └── tenant_rbac_scenarios.md    # Tenant A/B RBAC senaryoları
│
├── plugins/                        # Plugin / Marketplace ajanları
│   ├── <a href="../module-notes/plugins/manifest.py.md">manifest.py</a>                 # Plugin manifest doğrulaması
│   ├── <a href="../module-notes/plugins/crypto_price_agent.py.md">crypto_price_agent.py</a>       # CoinGecko fiyat sorgulama örneği
│   ├── <a href="../module-notes/plugins/aws_management_agent.py.md">aws_management_agent.py</a>     # AWS yönetim ajanı
│   ├── <a href="../module-notes/plugins/slack_notification_agent.py.md">slack_notification_agent.py</a> # Slack bildirim ajanı
│   └── <a href="../module-notes/plugins/upload_agent.py.md">upload_agent.py</a>             # Upload/entegrasyon şablon ajanı
│
├── web_ui_react/                   # React + TypeScript SPA (Vite)
│   ├── src/
│   │   ├── App.tsx                 # Uygulama kabuğu
│   │   ├── components/             # Chat, Swarm, Voice, Agent/Prompt/Tenant admin, Plugin marketplace, QA panelleri
│   │   ├── hooks/                  # useChatStore, useWebSocket, useVoiceAssistant, useSwarmFlowController ...
│   │   └── lib/                    # api.ts, swarmFlowGraph.ts, rehypeSidarHighlight.ts ...
│   ├── e2e/                        # Playwright uçtan uca testleri
│   ├── package.json                # npm bağımlılıkları ve script'ler
│   └── vite.config.js              # Vite build konfigürasyonu
│
├── launcher_gui/                   # Eel başlatıcı frontend'i (index.html, script.js, style.css)
├── grafana/                        # sidar_overview.json dashboard + provisioning
├── docker_setup/                   # Compose için grafana/, postgres/ (init), prometheus/ yapılandırması
├── helm/sidar/                     # Kubernetes Helm chart (values, values-staging, values-prod, templates/)
├── <a href="../module-notes/tests.md">tests/</a>                          # 301 test_*.py: unit/, integration/, smoke/, e2e/, shell/ (bats), quality/, performance/
├── <a href="../module-notes/data/gitkeep.md">data/</a>                           # RAG ve yerel depolama (çalışma zamanında dolar)
├── docs/                           # Proje belgeleri
│   ├── <a href="../module-notes/SIDAR.md.md">SIDAR.md</a>                    # Sistem promptları ve proje kuralları
│   ├── <a href="../module-notes/CLAUDE.md.md">CLAUDE.md</a>                   # Geliştirici rehberi
│   ├── <a href="../module-notes/PROJE_RAPORU.md.md">PROJE_RAPORU.md</a>             # Bu raporun dizini (bölümler project-report/ altında)
│   ├── <a href="../module-notes/RFC-MultiAgent.md.md">RFC-MultiAgent.md</a>           # Multi-agent mimari tasarımı
│   ├── ARCHITECTURE.md, TEKNIK_REFERANS.md, TESTING.md, runbooks/, archive/ ...
│   └── module-notes/               # Her modül için teknik not dosyaları (INDEX.md)
├── security/                       # pip-audit istisnaları ve güvenlik notları
├── <a href="../module-notes/env.example.md">.env.example</a>                    # Ortam değişkeni şablonu
├── AGENTS.md                       # Repo içi ajan mimarisi ve operasyonel standartlar
├── AI_CONTEXT.md                   # Yapay zekâ asistanları için kısa proje bağlamı
├── <a href="../module-notes/CHANGELOG.md.md">CHANGELOG.md</a>                    # Sürüm notları
└── <a href="../module-notes/README.md.md">README.md</a>                       # Proje tanıtım ve kurulum belgesi
</pre>

---

## 3. Modül Bazında Detaylı Analiz

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, v4.3.0 kod tabanındaki Faz 4 (kurumsal yetenekler) ve Faz 5 (multi-agent swarm + OTel) genişlemelerini yansıtacak şekilde sadeleştirilmiş bir dizin sunar. Ayrıntılı modül notu bulunan dosyalar `docs/module-notes/` altına bağlanmış, henüz ayrı notu olmayan yeni modüller için ise doğrudan kaynak dosya adı belirtilmiştir.

### 3.A Çekirdek Giriş Dosyaları

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.1 | `config.py` | [docs/module-notes/config.py.md](../module-notes/config.py.md) |
| 3.2 | `main.py` | [docs/module-notes/main.py.md](../module-notes/main.py.md) |
| 3.3 | `cli.py` | [docs/module-notes/cli.py.md](../module-notes/cli.py.md) |
| 3.4 | `web_server.py` | [docs/module-notes/web_server.py.md](../module-notes/web_server.py.md) |

### 3.B Çoklu Ajan (Multi-Agent Swarm) ve Dinamik Rol Mimarisi

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.5 | `agent/sidar_agent.py` | [docs/module-notes/agent/sidar_agent.py.md](../module-notes/agent/sidar_agent.py.md) |
| 3.6 | `agent/auto_handle.py` | [docs/module-notes/agent/auto_handle.py.md](../module-notes/agent/auto_handle.py.md) |
| 3.7 | `agent/definitions.py`, `agent/tooling.py`, `agent/base_agent.py` | [docs/module-notes/agent/definitions.py.md](../module-notes/agent/definitions.py.md) / [docs/module-notes/agent/tooling.py.md](../module-notes/agent/tooling.py.md) / [docs/module-notes/agent/base_agent.py.md](../module-notes/agent/base_agent.py.md) |
| 3.8 | `agent/core/supervisor.py`, `agent/swarm.py` | [docs/module-notes/agent/core/supervisor.py.md](../module-notes/agent/core/supervisor.py.md); [docs/module-notes/agent/swarm.py.md](../module-notes/agent/swarm.py.md) |
| 3.9 | `agent/registry.py`, `agent/core/registry.py` | [docs/module-notes/agent/core/registry.py.md](../module-notes/agent/core/registry.py.md); [docs/module-notes/agent/registry.py.md](../module-notes/agent/registry.py.md) |
| 3.10 | `agent/core/contracts.py`, `agent/core/event_stream.py`, `agent/core/memory_hub.py` | [docs/module-notes/agent/core/contracts.py.md](../module-notes/agent/core/contracts.py.md), [docs/module-notes/agent/core/event_stream.py.md](../module-notes/agent/core/event_stream.py.md), [docs/module-notes/agent/core/memory_hub.py.md](../module-notes/agent/core/memory_hub.py.md) |
| 3.11 | `agent/roles/coder_agent.py`, `researcher_agent.py`, `reviewer_agent.py`, `coverage_agent.py`, `poyraz_agent.py` | [docs/module-notes/agent/roles/coder_agent.py.md](../module-notes/agent/roles/coder_agent.py.md), [docs/module-notes/agent/roles/researcher_agent.py.md](../module-notes/agent/roles/researcher_agent.py.md), [docs/module-notes/agent/roles/reviewer_agent.py.md](../module-notes/agent/roles/reviewer_agent.py.md), [docs/module-notes/agent/roles/coverage_agent.py.md](../module-notes/agent/roles/coverage_agent.py.md), [docs/module-notes/agent/roles/poyraz_agent.py.md](../module-notes/agent/roles/poyraz_agent.py.md), [docs/module-notes/agent/roles/qa_agent.py.md](../module-notes/agent/roles/qa_agent.py.md) |
| 3.12 | `plugins/` (`crypto_price_agent.py`, `upload_agent.py`) | [docs/module-notes/plugins/crypto_price_agent.py.md](../module-notes/plugins/crypto_price_agent.py.md), [docs/module-notes/plugins/upload_agent.py.md](../module-notes/plugins/upload_agent.py.md); runtime plugin marketplace örnekleri |

### 3.C Core (Kurumsal Sistemler) ve Manager Katmanı

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.13 | `core/llm_client.py` | [docs/module-notes/core/llm_client.py.md](../module-notes/core/llm_client.py.md) |
| 3.14 | `core/router.py` | [docs/module-notes/core/router.py.md](../module-notes/core/router.py.md); maliyet/bağlam odaklı model yönlendirme katmanı |
| 3.15 | `core/dlp.py` | [docs/module-notes/core/dlp.py.md](../module-notes/core/dlp.py.md); DLP & PII maskeleme katmanı |
| 3.16 | `core/hitl.py` | [docs/module-notes/core/hitl.py.md](../module-notes/core/hitl.py.md); Human-in-the-Loop onay akışı |
| 3.17 | `core/judge.py`, `core/active_learning.py` | [docs/module-notes/core/judge.py.md](../module-notes/core/judge.py.md), [docs/module-notes/core/active_learning.py.md](../module-notes/core/active_learning.py.md); LLM-as-a-Judge + aktif öğrenme geri besleme döngüsü |
| 3.18 | `core/entity_memory.py`, `core/memory.py` | [docs/module-notes/core/memory.py.md](../module-notes/core/memory.py.md); [docs/module-notes/core/entity_memory.py.md](../module-notes/core/entity_memory.py.md) |
| 3.19 | `core/rag/` | [docs/module-notes/core/rag.py.md](../module-notes/core/rag.py.md) |
| 3.20 | `core/db/` | [docs/module-notes/core/db.py.md](../module-notes/core/db.py.md) |
| 3.21 | `core/llm_metrics.py`, `core/cache_metrics.py`, `core/agent_metrics.py` | [docs/module-notes/core/llm_metrics.py.md](../module-notes/core/llm_metrics.py.md), [docs/module-notes/core/cache_metrics.py.md](../module-notes/core/cache_metrics.py.md), [docs/module-notes/core/agent_metrics.py.md](../module-notes/core/agent_metrics.py.md) |
| 3.22 | `core/vision.py` | [docs/module-notes/core/vision.py.md](../module-notes/core/vision.py.md); multimodal mockup/görsel işleme hattı |
| 3.23 | `core/voice.py` | [docs/module-notes/core/voice.py.md](../module-notes/core/voice.py.md); TTS (Text-to-Speech) adaptörleri ve WebSocket ses segmentasyonu (v5.0-alpha) |
| 3.24 | `managers/security.py`, `managers/code_manager.py` | [docs/module-notes/managers/security.py.md](../module-notes/managers/security.py.md), [docs/module-notes/managers/code_manager.py.md](../module-notes/managers/code_manager.py.md) |
| 3.25 | `managers/github_manager.py`, `managers/package_info.py` | [docs/module-notes/managers/github_manager.py.md](../module-notes/managers/github_manager.py.md), [docs/module-notes/managers/package_info.py.md](../module-notes/managers/package_info.py.md) |
| 3.26 | `managers/system_health.py`, `managers/web_search.py`, `managers/todo_manager.py`, `managers/browser_manager.py` | [docs/module-notes/managers/system_health.py.md](../module-notes/managers/system_health.py.md), [docs/module-notes/managers/web_search.py.md](../module-notes/managers/web_search.py.md), [docs/module-notes/managers/todo_manager.py.md](../module-notes/managers/todo_manager.py.md), [docs/module-notes/managers/browser_manager.py.md](../module-notes/managers/browser_manager.py.md) |
| 3.27 | `managers/jira_manager.py`, `managers/slack_manager.py`, `managers/teams_manager.py` | [docs/module-notes/managers/jira_manager.py.md](../module-notes/managers/jira_manager.py.md), [docs/module-notes/managers/slack_manager.py.md](../module-notes/managers/slack_manager.py.md), [docs/module-notes/managers/teams_manager.py.md](../module-notes/managers/teams_manager.py.md); kurumsal iletişim ve iş akışı entegrasyonları |

### 3.D UI, Altyapı ve Operasyon

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.27 | `web_ui_react/`, `VoiceAssistantPanel.tsx`, `useVoiceAssistant.ts` | Legacy `web_ui/` kaldırılmıştır; React SPA için [web_ui_react/README.md](../../web_ui_react/README.md) rehberi esas alınır; duplex ses UX bileşenleri rapor içinde ayrıca belgelenmiştir |
| 3.28 | `github_upload.py`, `gui_launcher.py` | [docs/module-notes/github_upload.py.md](../module-notes/github_upload.py.md), [docs/module-notes/gui_launcher.py.md](../module-notes/gui_launcher.py.md) |
| 3.29 | `migrations/` (`0001`-`0007`), `scripts/` | [docs/module-notes/migrations/env.py.md](../module-notes/migrations/env.py.md) |
| 3.30 | `docker_setup/`, `runbooks/`, `helm/` | [docs/module-notes/docker_setup/prometheus/prometheus.yml.md](../module-notes/docker_setup/prometheus/prometheus.yml.md); `helm/` için ayrı modül notu henüz yok |

---

### 3.D.1 React İstemci Tarafı Ses Bileşenleri

- **`web_ui_react/src/components/VoiceAssistantPanel.tsx`:** Duplex ses oturumunun özet panelidir; mikrofonu başlat/durdur, aktif TTS oynatmasını kes, son transcript'i görüntüle ve VAD / buffer / turn bilgisini operatöre görünür kılar.
- **`web_ui_react/src/hooks/useVoiceAssistant.ts`:** `MediaRecorder`, `getUserMedia`, `AnalyserNode` ve `/ws/voice` WebSocket akışını tek yerde yöneten istemci orkestrasyon katmanıdır. Hook; VAD threshold/silence takibi, base64 ses paketleme, diagnostics halkası ve barge-in sırasında oynatmayı sonlandırma davranışını yönetir.
- **Backend uyumu:** Bu iki modül `core/voice.py` ve `web_server.py` içindeki `/ws/voice` akışına bağlanarak transcript, assistant turn metadata, `voice_state`, `voice_interruption` ve TTS paketleriyle tam çift yönlü bir UX sunar.
- **Operasyonel değer:** Sesli kod inceleme, hızlı incident triage ve hands-free debugging oturumları artık yalnızca backend capability değil, React SPA üzerinde gözlemlenebilir bir kullanıcı deneyimi haline gelmiştir.

---

## 4. Mimari Değerlendirme

[⬆ İçindekilere Dön](#içindekiler)

**Mimari özeti:** Proje mimarisi v4 sürümüyle birlikte tekil ajanlı daha basit bir RAG düzeninden; çoklu ajan (Swarm) destekli, OpenTelemetry ile tam gözlemlenebilir, anlamsal önbelleğe sahip ve çok kiracılı kurumsal bir orkestrasyon motoruna dönüşmüştür.

### 4.1 Güçlü Yönler

| Alan | Değerlendirme |
|------|---------------|
| **Asenkron Mimari** | `async/await` ve `asyncio.to_thread` tutarlı kullanımı; event loop bloklanmadan yüksek eşzamanlılık sağlanıyor |
| **Event-Driven Ajan Akışı** | `agent/core/event_stream.py` ile ajan düşünce/adım/araç olayları yayınlanıyor; WebSocket tarafında canlı izleme mümkün |
| **Kurumsal Kimlik ve İzolasyon** | Bearer token + DB tabanlı kullanıcı doğrulama ile oturum/mesaj verileri kullanıcı bazında izole tutuluyor |
| **DB Tabanlı Bellek + Fail-Closed** | `core/memory.py` bellek kalıcılığını DB'ye taşıyor; doğrulanmamış bağlamlar `MemoryAuthError` ile reddediliyor |
| **Zero-Trust Sandbox** | `network_mode="none"`, `mem_limit`, `nano_cpus` ve mikro-VM runtime uyumu (`runsc`/`kata-runtime`) ile güvenli kod yürütme |
| **QA Devre Kesici** | Coder ↔ Reviewer geri besleme döngüsünde `MAX_QA_RETRIES=3` sınırıyla sonsuz döngü ve maliyet patlaması riski kontrol ediliyor |
| **Yapısal LLM Çıktısı** | Sağlayıcı bazlı structured output + Pydantic doğrulaması ile tool çağrılarında format kararlılığı |
| **Hata Toleransı** | ChromaDB/BM25/keyword fallback zinciri ve araç seviyesinde hata yakalama ile operasyon sürekliliği |
| **Konfigürasyon Merkeziyeti** | `Config` üzerinden DB, güvenlik, sandbox ve tracing parametrelerinin tek merkezden yönetimi |
| **Telemetry-First Gözlemlenebilirlik** | OpenTelemetry span'leri + Prometheus/Grafana + `/api/budget` ile LLM, RAG ve ajan görevlerinin latency/token/maliyet akışı canlı izlenir |
| **Hiyerarşik / Paralel Swarm Orkestrasyonu** | Supervisor ve `SwarmOrchestrator`, görevleri alt parçalara ayırıp Coder/Researcher/Reviewer ajanlarına paralel veya pipeline modunda dağıtır |
| **Kurumsal Veri Düzlemi** | PostgreSQL + pgvector, ChromaDB, Redis semantic cache ve tenant bazlı RBAC/audit trail birlikte çalışarak kurumsal veri erişim katmanı oluşturur |
| **Gateway Güvenlik Katmanı** | DLP maskeleme ve HITL onay döngüsü, LLM çağrıları ile kritik araç aksiyonlarının giriş/çıkışında ek güvenlik bariyeri sağlar |
| **Çoklu LLM Ekosistemi** | Ollama, Gemini, OpenAI, Anthropic ve LiteLLM istemcileri ortak sözleşmeyle birlikte çalışır |

### 4.2 Kısıtlamalar

| Alan | Durum |
|------|-------|
| **Rate Limiting Altyapısı** | Redis gerektirir; Redis kesintisinde local fallback devreye girer ve dağıtık tutarlılık geçici düşebilir |
| **Docker Bağımlılığı** | `execute_code` tam işlevsellik için Docker daemon erişimi gerektirir |
| **BM25 Bellek Maliyeti** | Büyük doküman korpuslarında BM25 token verisinin RAM tüketimi artar |
| **LLM Maliyet/Limit Baskısı** | Bulut sağlayıcılarda token maliyeti ve provider rate-limit yönetimi zorunludur |
| **QA Overhead** | Reviewer doğrulama adımları kaliteyi artırırken ek LLM çağrısı/latency maliyeti üretir |
| **Operasyonel Karmaşıklık** | PostgreSQL + Redis + Prometheus/Grafana + Jaeger/OTel Collector + migration süreçleri kurulum/işletim maliyetini yükseltir |

### 4.3 v4.0 Kurumsal Mimari Sütunlar (Enterprise Lens)

#### 4.3.1 Asenkron + Event-Driven Çekirdek
- Servisler `asyncio` temelli non-blocking çalışma modeline geçirilmiş; LLM, web ve DB katmanında eşzamanlılık ölçeklenebilirliği artırılmıştır.
- `AgentEventBus`/event stream yaklaşımı ile ajan durumları olay olarak yayınlanır; WebSocket tüketicileri bu akışı gerçek zamanlı izler.

#### 4.3.2 Dayanıklılık (Resilience) ve Hata Toleransı
- Ağ/sağlayıcı dalgalanmalarına karşı retry/backoff stratejileri ile çağrı başarım sürekliliği hedeflenir.
- Araç zincirlerinde fallback şelalesi (örn. Tavily → Google → DuckDuckGo) ile tek noktadan hata kaynaklı servis kesintisi azaltılır.
- Kod yazma akışlarında disk öncesi sözdizimi/AST doğrulama ve güvenli yazım politikaları ile bozuk çıktıların kalıcılaşması engellenir.

#### 4.3.3 Thread-Safety ve Tip Güvenliği
- Multi-agent eşzamanlı erişim noktalarında `threading.Lock`/`RLock` tabanlı kritik bölge koruması benimsenmiştir.
- `@dataclass` tabanlı kayıt modelleri (DB, todo, vb.) ile veri taşıma nesneleri tipli ve denetlenebilir bir kontrata bağlanmıştır.

#### 4.3.4 Zero-Trust Güvenlik ve İzolasyon
- Kod çalıştırma akışları Docker sandbox izolasyonu, kaynak limitleri ve ağ kapatma ilkeleriyle sınırlandırılır.
- Path traversal/symlink denetimleri, hassas dosya blacklist kuralları ve fail-closed güvenlik kontrolleri kurumsal güvenlik çizgisini güçlendirir.

#### 4.3.5 Telemetry-First Gözlemlenebilirlik
- OpenTelemetry izleri ile her LLM isteği, RAG sorgusu ve uygun akışlarda swarm görevi span seviyesinde izlenebilir; bu hat Jaeger/OTel Collector ve Prometheus/Grafana panolarına beslenir.
- Mimaride gözlemlenebilirlik yalnızca log toplamadan ibaret değildir; waterfall analizleri, token/maliyet sayaçları ve provider bazlı performans görünürlüğü operasyonun birinci sınıf girdisidir.

#### 4.3.6 Kurumsal Veri Düzlemi ve Ölçeklenebilir Bellek
- SQLite kökenli tekil modelden, async pool destekli PostgreSQL veri katmanı ve multi-tenant kullanıcı izolasyonuna geçiş mimari olgunluk seviyesini yükseltir.
- RAG tarafında ChromaDB ile pgvector birlikte desteklenir; Redis tabanlı semantic cache maliyet/latency optimizasyonu sağlarken, tenant RBAC ve audit trail erişim yüzeyini kurumsal seviyeye taşır.

#### 4.3.7 Dinamik Swarm ve Plugin Mimarisi
- Mimari kalp artık yalnızca `sidar_agent.py` döngüsü değildir; Supervisor/Swarm katmanı görevleri analiz eder, alt görevlere böler ve bunları uzman ajanlara paralel veya pipeline biçiminde dağıtır.
- `web_server.py` üzerindeki `/api/agents/register` ve `/api/agents/register-file` uç noktaları ile dış kaynak plugin ajanları çalışma zamanında sisteme alınır; `_register_plugin_agent` akışı bunları `AgentRegistry` üstünden canlı ajan envanterine kaydeder.

#### 4.3.8 Single Page Application (Vite/React) Arayüzü
- Sunum katmanı yalnız `web_ui_react/dist` React build çıktısını statik olarak servis eder; legacy `web_ui/` fallback'i kaldırılmıştır.
- `web_ui_react/src/App.tsx` içinde P2PDialoguePanel ve SwarmFlowPanel bileşenleriyle canlı ajan diyaloğu ve görev akışı görünürlüğü SPA deneyiminde sunulur.

#### 4.3.9 Tenant Bazlı Erişim Kontrol Listeleri (ACL) ve Audit Trail
- `access_policy_middleware` ve `_resolve_policy_from_request` ile rota/aksiyon bazlı kaynak sınıflandırması yapılarak tenant düzeyinde ince taneli yetkilendirme uygulanır.
- `/admin/policies` uç noktaları üzerinden policy CRUD/inceleme yüzeyleri açılır; izin kararları audit trail olarak kalıcı biçimde kaydedilerek RBAC modeli operasyonel yönetim katmanına taşınır.

#### 4.3.10 DLP + HITL Güvenlik Geçidi
- DLP katmanı, LLM'e çıkmadan önce hassas verileri (PII, token, kart numarası vb.) maskeleyerek mimarinin giriş/çıkışında veri sızıntısı riskini düşürür.
- HITL döngüsü, üretim etkili veya yıkıcı işlemlerde insan onayı bekleyerek swarm/araç katmanının güvenli şekilde karar vermesini sağlar.

---
