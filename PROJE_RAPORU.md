
# SİDAR Projesi — Kapsamlı Kod Analiz Raporu (Güncel)

> ---
> 📋 **Durum Akışı:** Sürüm farkları için **[CHANGELOG.md](CHANGELOG.md)**, ayrıntılı çözüm geçmişi için **[docs/archive/](docs/archive/)** dizinine bakınız.
> _(Ana rapor yalnızca aktif durum özeti ve stratejik kurumsal görünüm için referans noktasıdır.)_
> ---

> **Rapor Tarihi:** 2026-03-21
> **Son Güncelleme:** 2026-03-26 (v5.1.0 belge senkronizasyonu: Faz C, D ve E kapsamındaki kod tabanı güncellemeleri rapor metniyle hizalandı.)
> **Önceki Güncelleme:** 2026-03-19 (v3.2.0 — Autonomous LLMOps özellik turu tamamlandı: Active Learning/LoRA (`core/active_learning.py`), Vision Pipeline (`core/vision.py`), Cost-Aware routing (`core/router.py`) ve Slack/Jira/Teams tabanlı dış sistem orkestrasyonu birlikte değerlendirilerek Faz 4 teslimatının ürünleştiği teyit edildi.)
> **Proje Sürümü:** v5.1.0
> **Sürüm Notu:** Paket yöneticisi düzeyinde (`pyproject.toml`) ve çalışma zamanı (`config.py`) sürümü `5.1.0` olarak hizalanmıştır.
> **İleri Yol Haritası / Faz Durumu:** Faz A, Faz B, Faz D ve Faz E ajan teslimatları belge-bazında senkronize edildi; aktif geliştirme odağı Faz E'nin YouTube/dış video ingest genişlemesi ve v5.x derinleştirme eksenidir.

> **Önceki Kayıt:** 3.0.30
> **Derin Teknik Kılavuz:** API/DB/Operasyon detayları için `TEKNIK_REFERANS.md` dosyasına bakınız.
> **Analiz Kapsamı:** Tüm takipli kaynak dosyaları 2026-03-26 tarihinde `scripts/collect_repo_metrics.sh` ve `scripts/audit_metrics.sh` ile yeniden ölçülmüştür. Güncel ölçümde üretim Python hacmi **32.936** satır (**70** takipli `.py` dosyası; `tests/` hariç), test havuzu **65.729** satır (**213** `test_*.py` modülü; `tests/*.py` toplamı **215** dosya), tüm takipli Python toplamı **98.665** satır (**285** dosya) olarak doğrulanmıştır. Takipli Markdown havuzu **10.148** satır (**102** dosya), toplam ölçüm yüzeyi ise **116.053** satır (**408** dosya; `.py/.js/.css/.html/.md` kapsamı) seviyesindedir. Modern frontend tarafında `web_ui_react/` **38** takipli dosya / **10.792** satır, legacy `web_ui/` ise **7** takipli dosya / **4.769** satır üretmektedir. Bu revizyonda özellikle `main.py` launcher sertleştirmeleri, `tests/test_missing_edge_case_coverage_final.py` ile son edge-case coverage kapanışı, Faz D enterprise ölçekleme yüzeyleri (`web_ui_react/src/components/PluginMarketplacePanel.jsx`, `web_ui_react/src/components/AgentManagerPanel.jsx`, `web_ui_react/src/hooks/useWebSocket.js`, `tests/test_plugin_marketplace_hot_reload.py`, `tests/test_collaboration_workspace.py`, `tests/test_nightly_memory_maintenance.py`, `tests/test_system_health_dependency_checks.py`, `runbooks/chaos_live_rehearsal.md`) ve Faz E devreye alınan ajan yüzeyleri (`agent/roles/coverage_agent.py`, `agent/roles/poyraz_agent.py`, `agent/tooling.py`, `core/multimodal.py`, `managers/code_manager.py`, `core/db.py`) yeniden doğrulanmıştır.

---

<a id="içindekiler"></a>
## İçindekiler
- [1. Proje Genel Bakışı](#1-proje-genel-bakışı)
  - [Temel Özellikler](#temel-özellikler)
  - [Mevcut Durum ve Tamamlanan Özellikler](#mevcut-durum-ve-tamamlanan-özellikler)
  - [SİDAR'ın Geleceği: Otonom Şirket Simülasyonu](#sidarın-geleceği-otonom-şirket-simülasyonu)
- [2. Proje Dosya Yapısı](#2-proje-dosya-yapısı)
- [3. Modül Bazında Detaylı Analiz](#3-modül-bazında-detaylı-analiz)
  - [3.A Çekirdek Giriş Dosyaları](#3a-çekirdek-giriş-dosyaları)
  - [3.B Agent Katmanı](#3b-agent-katmanı)
  - [3.C Core ve Manager Katmanı](#3c-core-ve-manager-katmanı)
  - [3.D UI, Altyapı ve Operasyon](#3d-ui-altyapı-ve-operasyon)
- [4. Mimari Değerlendirme](#4-mimari-değerlendirme)
  - [4.1 Güçlü Yönler](#41-güçlü-yönler)
  - [4.2 Kısıtlamalar](#42-kısıtlamalar)
  - [4.3 v4.0 Kurumsal Mimari Sütunlar (Enterprise Lens)](#43-v40-kurumsal-mimari-sütunlar-enterprise-lens)
- [5. Güvenlik Analizi](#5-güvenlik-analizi)
  - [5.1 Güvenlik Kontrolleri Özeti](#51-güvenlik-kontrolleri-özeti)
  - [5.2 Güvenlik Seviyeleri Davranışı](#52-güvenlik-seviyeleri-davranışı)
  - [5.3 Kurumsal Zero-Trust Savunma Sütunları (v3.0)](#53-kurumsal-zero-trust-savunma-sütunları-v30)
- [6. Test Kapsamı](#6-test-kapsamı)
  - [6.1 CI/CD Pipeline Durumu](#61-cicd-pipeline-durumu)
  - [6.2 Coverage Hard Gate (%100)](#62-coverage-hard-gate-100)
  - [6.3 Test Havuzu ve Modüler Senaryolar](#63-test-havuzu-ve-modüler-senaryolar)
  - [6.4 Asenkron Test Altyapısı](#64-asenkron-test-altyapısı)
- [7. Temel Bağımlılıklar](#7-temel-bağımlılıklar)
  - [7.1 Asenkron Altyapı ve Uygulama Çekirdeği](#71-asenkron-altyapı-ve-uygulama-çekirdeği)
  - [7.2 Veritabanı, Migrasyon ve Telemetri](#72-veritabanı-migrasyon-ve-telemetri)
  - [7.3 Güvenlik, Sandbox ve Donanım Gözlemlenebilirliği](#73-güvenlik-sandbox-ve-donanım-gözlemlenebilirliği)
  - [7.4 AI Sağlayıcıları ve RAG Katmanı](#74-ai-sağlayıcıları-ve-rag-katmanı)
  - [7.5 Test ve Kalite Kapıları (Dev Bağımlılıkları)](#75-test-ve-kalite-kapıları-dev-bağımlılıkları)
- [8. Kod Satır Sayısı Özeti](#8-kod-satır-sayısı-özeti)
  - [8.1 Çekirdek Modüller (Güncel)](#81-çekirdek-modüller-güncel)
  - [8.2 Multi-Agent Çekirdek ve Roller](#82-multi-agent-çekirdek-ve-roller)
  - [8.3 Migration / Operasyon / Altyapı](#83-migration-operasyon-altyapı)
  - [8.4 Frontend ve Test Özeti](#84-frontend-ve-test-özeti)
  - [8.5 Dizin Bazlı Hacim Özeti](#85-dizin-bazlı-hacim-özeti)
- [9. Modül Bağımlılık Haritası](#9-modül-bağımlılık-haritası)
  - [9.1 Statik Bağımlılık Matrisi (Import Grafı)](#91-statik-bağımlılık-matrisi-import-grafı)
  - [9.2 Olay Güdümlü Pub/Sub Omurgası (AgentEventBus)](#92-olay-güdümlü-pubsub-omurgası-agenteventbus)
  - [9.3 Güvenlik Zinciri: CodeManager → SecurityManager (Hard Coupling)](#93-güvenlik-zinciri-codemanager--securitymanager-hard-coupling)
  - [9.4 DB Merkezli Bellek ve Kimlik Hiyerarşisi](#94-db-merkezli-bellek-ve-kimlik-hiyerarşisi)
  - [9.5 P2P Delegasyon Köprüsü (Supervisor + Contracts)](#95-p2p-delegasyon-köprüsü-supervisor--contracts)
- [10. Veri Akış Diyagramı](#10-veri-akış-diyagramı)
  - [10.1 Bir Chat Mesajının Ömrü](#101-bir-chat-mesajının-ömrü)
  - [10.2 Bellek Yazma Yolu (Ortak Bellek Havuzu)](#102-bellek-yazma-yolu-ortak-bellek-havuzu)
  - [10.3 RAG Belge Ekleme Yolu (Ortak Erişim)](#103-rag-belge-ekleme-yolu-ortak-erişim)
  - [10.4 Kurumsal v3.0 Uçtan Uca Veri Hattı (5 Faz)](#104-kurumsal-v30-uçtan-uca-veri-hattı-5-faz)
  - [10.5 Proaktif Otonomi: Cron Wake + Webhook Tepki Döngüsü](#105-proaktif-otonomi-cron-wake--webhook-tepki-döngüsü)
- [11. Mevcut Sorunlar ve Teknik Borç](#11-mevcut-sorunlar-ve-teknik-borç)
  - [11.1 Durum Özeti Paneli](#111-durum-özeti-paneli)
  - [11.2 Arşiv ve Yönlendirme](#112-arşiv-ve-yönlendirme)
  - [11.3 v5.0 Faz-6 Coverage Kapanışı](#113-v50-faz-6-coverage-kapanışı)
  - [11.4 Operasyonel İzleme Başlıkları](#114-operasyonel-i̇zleme-başlıkları)
  - [11.5 Gelecek İyileştirmeler (Continuous Improvement)](#115-gelecek-i̇yileştirmeler-continuous-improvement)
- [12. `.env` Tam Değişken Referansı](#12-env-tam-değişken-referansı)
  - [12.1 AI Sağlayıcı](#121-ai-sağlayıcı)
  - [12.2 Güvenlik ve Erişim](#122-güvenlik-ve-erişim)
  - [12.3 GPU / Donanım](#123-gpu-donanım)
  - [12.4 Web Arayüzü](#124-web-arayüzü)
  - [12.5 Web Arama](#125-web-arama)
  - [12.6 RAG](#126-rag)
  - [12.7 Hafıza ve ReAct](#127-hafıza-ve-react)
  - [12.8 Loglama](#128-loglama)
  - [12.9 Rate Limiting](#129-rate-limiting)
  - [12.10 Veritabanı ve Auth (Kurumsal)](#1210-veritabanı-ve-auth-kurumsal)
  - [12.11 Telemetri ve Zero-Trust Sandbox](#1211-telemetri-ve-zero-trust-sandbox)
  - [12.12 Çeşitli](#1212-çeşitli)
  - [12.13 Docker Compose Override Değişkenleri](#1213-docker-compose-override-değişkenleri)
- [13. v4.0 Kurumsal Sürüm İyileştirmeleri (Tamamlandı)](#13-v40-kurumsal-sürüm-i̇yileştirmeleri-tamamlandı)
- [14. Geliştirme Yol Haritası](#14-geliştirme-yol-haritası)
- [15. Özellik-Gereksinim Matrisi](#15-özellik-gereksinim-matrisi)
  - [15.1 Çekirdek Özellikler (Her Zaman Zorunlu)](#151-çekirdek-özellikler-her-zaman-zorunlu)
  - [15.2 Arama ve Web](#152-arama-ve-web)
  - [15.3 RAG (Belge Deposu)](#153-rag-belge-deposu)
  - [15.4 Sistem İzleme ve GPU](#154-sistem-i̇zleme-ve-gpu)
  - [15.5 Kod Yürütme](#155-kod-yürütme)
  - [15.6 Özellik Profilleri](#156-özellik-profilleri)
  - [15.7 v3.0 Vizyon Gereksinimleri (Planlanan)](#157-v30-vizyon-gereksinimleri-planlanan)
- [16. Gözlemlenebilirlik (Observability), Loglama ve Hata Yönetimi](#16-gözlemlenebilirlik-observability-loglama-ve-hata-yönetimi)
  - [16.1 Dağıtık İzlenebilirlik (Distributed Tracing)](#161-dağıtık-i̇zlenebilirlik-distributed-tracing)
  - [16.2 Metrik Toplama ve Uyarı Sistemleri (Prometheus & Grafana)](#162-metrik-toplama-ve-uyarı-sistemleri-prometheus--grafana)
  - [16.3 Sürü (Swarm) İçi Hata Toleransı ve Otomatik Telafi (Fallback)](#163-sürü-swarm-i̇çi-hata-toleransı-ve-otomatik-telafi-fallback)
  - [16.4 Kurumsal Denetim İzleri (Audit Logging)](#164-kurumsal-denetim-i̇zleri-audit-logging)
- [17. Yaygın Sorunlar ve Çözümleri (Troubleshooting)](#17-yaygın-sorunlar-ve-çözümleri-troubleshooting)
  - [17.1 Redis / Anlamsal Önbellek (Semantic Cache) Bağlantı Hatası](#171-redis-anlamsal-önbellek-semantic-cache-bağlantı-hatası)
  - [17.2 PostgreSQL ve pgvector Hataları](#172-postgresql-ve-pgvector-hataları)
  - [17.3 Modern React (SPA) Arayüzüne Bağlanamama](#173-modern-react-spa-arayüzüne-bağlanamama)
  - [17.4 HTTP 429 Too Many Requests (Hız Limitleri)](#174-http-429-too-many-requests-hız-limitleri)
  - [17.5 Sistem Donması / Ajanların Tepki Vermemesi (HITL Beklemesi)](#175-sistem-donması-ajanların-tepki-vermemesi-hitl-beklemesi)
  - [17.6 OpenTelemetry (OTel) Gecikme Uyarıları](#176-opentelemetry-otel-gecikme-uyarıları)
- [18. Geliştirme Geçmişi ve Final Doğrulama Raporu](#18-geliştirme-geçmişi-ve-final-doğrulama-raporu)

---

## 1. Proje Genel Bakışı

[⬆ İçindekilere Dön](#içindekiler)

**Sidar**, ReAct (Reason + Act) döngüsüyle çalışan, async-first mimariye sahip bir yazılım mühendisi AI asistanıdır. Yerel LLM (Ollama) veya bulut tabanlı LLM'ler (Google Gemini, OpenAI, Anthropic ve LiteLLM Gateway/OpenRouter benzeri ara katmanlar) ile çalışabilir; CLI, FastAPI tabanlı Web UI ve opsiyonel Eel masaüstü launcher sunar.

### Temel Özellikler
- **Arayüzler:** CLI (`cli.py`), Web (`web_server.py` + `web_ui/` veya build varsa `web_ui_react/dist`) ve opsiyonel Eel launcher (`gui_launcher.py`)
- **Çoklu LLM sağlayıcı:** Ollama (yerel), Gemini, OpenAI, Anthropic ve LiteLLM Gateway (bulut/proxy)
- **Multi-Agent + P2P Delegasyon:** Supervisor orkestrasyonu ile görevleri uzman rollere (Coder, Researcher, Reviewer) dağıtır; `agent/core/contracts.py` ile ajanlar arası P2P görev sözleşmesi desteklenir.
- **Dinamik Ajan Pazaryeri (Plugin Marketplace) ve Swarm API:** Çalışma zamanında yeni plugin ajanlar kayıt defterine eklenebilir; `AgentRegistry` + `SwarmOrchestrator` ile paralel veya pipeline görev akışları işletilir (`agent/registry.py`, `agent/swarm.py`).
- **Dinamik Prompt Yönetimi (Prompt Registry):** Sistem prompt'ları statik kod yerine veritabanı destekli registry üzerinden sürümlenebilir, etkinleştirilebilir ve Admin UI üzerinden yönetilebilir.
- **Çoklu Kullanıcı (Multi-User) ve Veritabanı Altyapısı:** PostgreSQL/SQLite destekli kalıcı veri katmanı ile kullanıcı bazlı oturum izolasyonu ve kota yönetimi (`core/db.py`).
- **Telemetri ve Bütçe İzleme:** Grafana ve Prometheus entegrasyonu ile LLM API maliyetleri (USD), token tüketimi ve gecikme (latency) takibi (`core/llm_metrics.py`). Semantic cache hit/miss Grafana dashboard'u (`grafana/dashboards/sidar_overview.json`).
- **Anlamsal Önbellekleme (Semantic Cache):** Redis tabanlı, cosine similarity ile benzer istemleri eşleştiren ve LRU eviction uygulayan önbellek katmanı; token maliyetini ve yanıt gecikmesini düşürür (`core/llm_client.py`).
- **Canlı Ajan Durum Akışı (Observability):** WebSocket tabanlı event stream ile düşünce adımları, araç çağrıları ve ajan durumları Web UI'da canlı izlenir (`agent/core/event_stream.py`).
- **Dağıtık İzlenebilirlik (Distributed Tracing):** OpenTelemetry span enstrümantasyonu ile tüm 5 LLM sağlayıcısı ve RAG akışları Jaeger/OTel Collector uyumlu biçimde uçtan uca waterfall görünümünde izlenebilir (`web_server.py`, `core/llm_client.py`, `core/rag.py`).
- **Admin paneli ve operasyon yüzeyi:** Legacy Web UI admin paneli toplam kullanıcı, toplam API isteği, toplam token ve kullanıcı bazlı günlük kotaları gösterir; React tarafındaki Prompt Admin/Agent Manager ekranları backend ile entegredir, `TenantAdminPanel` ise şu an örnek/demo senaryo panelidir.
- **Tenant Bazlı RBAC ve Audit Trail:** Çok kiracılı erişim politikaları (`tenant_id`) uygulanır; tüm izin kararları audit log olarak kalıcı biçimde kaydedilir (`web_server.py`, `core/db.py`).
- **QA ve Regresyon Sinyali:** Coder ajanı ile ortak çalışan, üretilen kodu test edip onaylayan/reddeden gelişmiş `ReviewerAgent` döngüsü.
- **GitHub Entegrasyonu:** Repo analizi, branch/PR ve issue akışları `managers/github_manager.py`; GitHub release bilgileri ise `managers/package_info.py` üzerinden ajan araç setine entegredir.
- **ReAct döngüsü:** LLM → Araç çağrısı → Gözlem → LLM (maks. `MAX_REACT_STEPS` adım)
- **Görev Takibi ve Proje Denetimi:** `managers/todo_manager.py` ile TODO yazma/okuma/güncelleme ve proje genelinde `scan_project_todos()` üzerinden TODO/FIXME taraması yapılır.
- **RAG + Reviewer Etki Analizi (Faz B Tamamlandı):** ChromaDB veya pgvector + BM25 + keyword hibrit arama (RRF destekli) akışına ek olarak GraphRAG, modül bağımlılık grafiği taraması, bağımlılık yolu açıklaması ve reviewer kalite kapısında kullanılan etki analizi raporlarını üretir (`core/rag.py`, `agent/roles/reviewer_agent.py`).
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
- **İstemci Tarafı Ses Deneyimi (Faz C derinleşmesi):** `VoiceAssistantPanel.jsx` ve `useVoiceAssistant.js`, mikrofon izni, `MediaRecorder` akışı, VAD durum takibi, transcript diyagnostiği ve kullanıcının SİDAR konuşmasını kesebilmesini React UI üzerinde görünür hale getirir.
- **Otonom Remediation / Self-Healing (Faz C):** `core/ci_remediation.py`, `agent/sidar_agent.py`, `agent/roles/reviewer_agent.py` ve `managers/code_manager.py` birlikte düşük riskli CI arızaları için patch planı üretir, sandbox'ta doğrular, gerekirse rollback yapar ve yüksek riskte HITL kapısına döner.
- **Nightly Memory Pruning / Konsolidasyon (Faz D):** Sistem idle kaldığında `ConversationMemory` eski oturumları özetleyip sıkıştırır, `DocumentStore` aynı oturumdaki düşük değerli RAG belgelerini `memory://nightly-digest` özetine konsolide eder ve `EntityMemory` TTL bakımını çalıştırır; böylece uzun soluklu projelerde hafıza bir insan gibi tazelenir.
- **Dynamic Browser Automation (Tamamlandı / v5.0-alpha):** `managers/browser_manager.py` Playwright/Selenium sağlayıcı soyutlaması, zorunlu HITL geçidi, audit trail ve reviewer/swarm akışına taşınabilen browser signal özetleri ile kontrollü tarayıcı oturumlarını yönetiyor.
- **Proaktif Otonomi + Swarm Federation (Tamamlandı / Faz B):** `web_server.py` içinde `/ws/voice`, `/api/autonomy/webhook/{source}`, `/api/swarm/federation`, `/api/swarm/federation/feedback` ve `ENABLE_AUTONOMOUS_CRON` tabanlı cron tetikleyicisi ile sistem reaktif modelden kontrollü proaktif/federe co-worker modeline genişliyor.
- **Canlı Operasyon Yüzeyi (Tamamlandı / Faz B):** `web_ui_react/src/components/SwarmFlowPanel.jsx`, `core/hitl.py` ve ilgili HITL API'leri ile görsel karar grafiği artık sadece izleme değil; seçili düğümden görev türetme, hedefli rerun ve bekleyen onayları yönetme yüzeyi olarak da çalışıyor.
- **Jira / Slack / Teams Entegrasyonu:** Jira Cloud REST API v3, Slack Bot SDK + Webhook fallback (Block Kit), Teams MessageCard + Adaptive Card v1.4 ve HITL onay kartı (`managers/jira_manager.py`, `managers/slack_manager.py`, `managers/teams_manager.py`).
- **Kök kontrol düzlemi doğrulaması (v5.0-alpha / Faz B):** `main.py` sihirbaz + quick-start başlatma katmanı, `cli.py` tek event-loop CLI oturumu, `web_server.py` geniş FastAPI kontrol düzlemi (mevcut dosyada **66** route/websocket decorator; **64** REST + **2** WebSocket), `config.py` bootstrap/telemetry yükleme yolu, `github_upload.py` güvenli `git ls-files` paketleme akışı ve `gui_launcher.py` Eel köprüsü mevcut repo durumu ile yeniden teyit edilmiştir.
- **Son doğrulama notu (v3.0.30):** `core/entity_memory.py`, `core/cache_metrics.py`, `core/judge.py`, `core/vision.py`, `core/active_learning.py`, `core/hitl.py`, `core/llm_client.py` ve `web_server.py` üzerindeki D-8..D-14 düzeltmeleri yeniden gözden geçirilmiş; incelenen modüllerde kritik açık bir bulguya rastlanmadığı rapora işlenmiştir.


### Mevcut Durum ve Tamamlanan Özellikler

- **Plugin Marketplace (Faz D):** `PluginMarketplacePanel.jsx` çalışma zamanında yüklenen ajan eklentilerini UI üzerinden görünür kılar; `tests/test_plugin_marketplace_hot_reload.py` ise `aws_management_agent.py` ve `slack_notification_agent.py` benzeri ajanların kesintisiz hot-reload zincirini doğrular.
- **Multiplayer Collaboration Workspace (Faz D):** `AgentManagerPanel.jsx` ve `useWebSocket.js`, çoklu operatörün aynı çalışma yüzeyini paylaşabildiği anlık durum senkronizasyonunu taşır; `tests/test_collaboration_workspace.py` bu çok kullanıcılı orkestrasyon davranışını regresyon güvencesine bağlar.
- **Nightly Memory Maintenance (Faz D):** `tests/test_nightly_memory_maintenance.py` ile doğrulanan gece bakım döngüsü, PGVector/RAG belleğinin şişmesini önlemek için oturum özetleme, belge konsolidasyonu ve TTL temizliğini planlı biçimde uygular.
- **Chaos Engineering Hazırlığı (Faz D):** `runbooks/chaos_live_rehearsal.md` ve `tests/test_system_health_dependency_checks.py`, PostgreSQL veya Redis kesintilerinde sistemin fail-safe davranmasını ve operasyon ekibinin tekrar prova edilebilir bir kurtarma akışı izlemesini sağlar.

### SİDAR'ın Geleceği: Otonom Şirket Simülasyonu

Faz E vizyonu artık SİDAR'ı yalnızca yazılım geliştiren bir AI yardımcı olmaktan çıkarıp yazılım, pazarlama, operasyon ve içerik üretimini tek bir otonom ekosistemde birleştiren **otonom şirket simülasyonu** katmanına taşımış durumdadır. Bu fazda devreye alınan yakın dönem odakları şunlardır:

- **Coverage Agent:** `agent/roles/coverage_agent.py` swarm rolü eklendi; ajan `CodeManager` üzerinden `pytest` komutlarını koşturuyor, pytest çıktısını analiz ediyor, eksik test adayları üretiyor, önerilen test dosyasını yazıyor ve bulguları `coverage_tasks` / `coverage_findings` yüzeyine kaydediyor. `%100` test kapsama kültürü artık yalnızca statik kalite kapısı değil, aktif test üretim döngüsüyle destekleniyor.
- **Poyraz (Dijital Pazarlama ve Operasyon Uzmanı):** `agent/roles/poyraz_agent.py` devreye alındı; `WebSearchManager`, `SocialMediaManager`, `DocumentStore` ve `core.multimodal.MultimodalPipeline` entegrasyonları ile Instagram/Facebook/WhatsApp yayınlama, landing page üretimi, kampanya kopyası hazırlama, video içgörüsü ingest etme ve operasyon checklist'i oluşturma akışları fiilen sisteme eklendi.
- **YouTube ve Genişletilmiş Multimodal Zeka:** `core/multimodal.py` hattı Poyraz içinde `ingest_video_insights` aracıyla kullanılmaya başlandı; dış video URL'lerinden çıkarılan sahne özeti ve ingest edilen içerik, pazarlama/operasyon çıktısına dönüştürülen aktif veri kaynağı olarak konumlandı.

---

## 2. Proje Dosya Yapısı

[⬆ İçindekilere Dön](#içindekiler)

<pre>
sidar_project/
├── .github/workflows/         # CI/CD süreçleri (ci.yml, migration-cutover-checks.yml)
├── <a href="docs/module-notes/main.py.md">main.py</a>                    # Akıllı Başlatıcı (Ultimate Launcher - TUI entegre)
├── <a href="docs/module-notes/cli.py.md">cli.py</a>                     # CLI terminal arayüzü giriş noktası
├── <a href="docs/module-notes/web_server.py.md">web_server.py</a>              # FastAPI web sunucusu (WebSocket streaming)
├── <a href="docs/module-notes/config.py.md">config.py</a>                  # Merkezi yapılandırma (v5.0.0-alpha runtime)
├── <a href="docs/module-notes/github_upload.py.md">github_upload.py</a>           # GitHub otomatik yükleme aracı
├── <a href="docs/module-notes/gui_launcher.py.md">gui_launcher.py</a>            # Eel tabanlı masaüstü başlatıcı giriş noktası
├── <a href="docs/module-notes/Dockerfile.md">Dockerfile</a>                 # CPU + GPU çift mod Dockerfile
├── <a href="docs/module-notes/docker-compose.yml.md">docker-compose.yml</a>         # 7 servis (redis, sidar-ai, sidar-gpu, sidar-web, sidar-web-gpu, prometheus, grafana)
├── <a href="docs/module-notes/environment.yml.md">environment.yml</a>            # Conda bağımlılıkları
├── <a href="docs/module-notes/requirements-dev.txt.md">requirements-dev.txt</a>       # Geliştirme ve test bağımlılıkları (-e .[rag,postgres,telemetry,dev])
├── uv.lock                    # uv paket yöneticisi kilit dosyası
├── <a href="docs/module-notes/pyproject.toml.md">pyproject.toml</a>             # Ruff + Mypy kalite standartları
├── <a href="docs/module-notes/pytest.ini.md">pytest.ini</a>                 # Pytest konfigürasyonu
├── <a href="docs/module-notes/alembic.ini.md">alembic.ini</a>                # Veritabanı geçiş (migration) ayarları
├── <a href="docs/module-notes/run_tests.sh.md">run_tests.sh</a>               # Kapsam ve test çalıştırıcı betik
├── <a href="docs/module-notes/install_sidar.sh.md">install_sidar.sh</a>           # Otomatik kurulum betiği
│
├── agent/
│   ├── <a href="docs/module-notes/agent/__init__.py.md">__init__.py</a>
│   ├── <a href="docs/module-notes/agent/sidar_agent.py.md">sidar_agent.py</a>         # Ana ajan bağlayıcısı
│   ├── <a href="docs/module-notes/agent/base_agent.py.md">base_agent.py</a>          # BaseAgent soyut sınıfı (multi-agent iskeleti)
│   ├── <a href="docs/module-notes/agent/auto_handle.py.md">auto_handle.py</a>         # Anahtar kelime tabanlı hızlı yönlendirici
│   ├── <a href="docs/module-notes/agent/definitions.py.md">definitions.py</a>         # Sistem istemi ve ajan kimliği
│   ├── <a href="docs/module-notes/agent/tooling.py.md">tooling.py</a>             # Araç kayıt + Pydantic şema yöneticisi
│   ├── registry.py            # AgentRegistry + @register dekoratörü (plugin marketplace, dinamik ajan kaydı)
│   ├── swarm.py               # SwarmOrchestrator: parallel/pipeline modları, TaskRouter (çoklu ajan koordinasyonu)
│   ├── core/
│   │   ├── <a href="docs/module-notes/agent/core/__init__.py.md">__init__.py</a>
│   │   ├── <a href="docs/module-notes/agent/core/supervisor.py.md">supervisor.py</a>      # Yönlendirici ve orkestrasyon ajanı
│   │   ├── <a href="docs/module-notes/agent/core/contracts.py.md">contracts.py</a>       # TaskEnvelope/TaskResult + P2P delegasyon sözleşmeleri
│   │   ├── <a href="docs/module-notes/agent/core/event_stream.py.md">event_stream.py</a>    # Ajan olay veriyolu (canlı durum akışı)
│   │   ├── <a href="docs/module-notes/agent/core/memory_hub.py.md">memory_hub.py</a>      # Multi-agent bellek yönetim merkezi
│   │   └── <a href="docs/module-notes/agent/core/registry.py.md">registry.py</a>        # Ajan ve yetenek kayıt defteri
│   └── roles/
│       ├── <a href="docs/module-notes/agent/roles/__init__.py.md">__init__.py</a>
│       ├── <a href="docs/module-notes/agent/roles/coder_agent.py.md">coder_agent.py</a>     # Dosya/kod odaklı uzman ajan
│       ├── <a href="docs/module-notes/agent/roles/researcher_agent.py.md">researcher_agent.py</a> # Web + RAG odaklı uzman ajan
│       ├── <a href="docs/module-notes/agent/roles/reviewer_agent.py.md">reviewer_agent.py</a>  # Test koşturan, kod kalitesini denetleyen QA ajanı
│       ├── coverage_agent.py      # Coverage açığını kapatmak için pytest analizi + test üretimi yapan ajan
│       └── poyraz_agent.py        # Pazarlama, sosyal medya ve operasyon akışlarını yürüten ajan
│
├── core/
│   ├── <a href="docs/module-notes/core/__init__.py.md">__init__.py</a>
│   ├── <a href="docs/module-notes/core/db.py.md">db.py</a>                  # Veritabanı bağlantısı, kullanıcı ve kota tabloları
│   ├── <a href="docs/module-notes/core/llm_client.py.md">llm_client.py</a>          # Ollama + Gemini + OpenAI + Anthropic asenkron istemci
│   ├── <a href="docs/module-notes/core/llm_metrics.py.md">llm_metrics.py</a>         # Token, maliyet ve Prometheus metrik toplayıcısı
│   ├── <a href="docs/module-notes/core/memory.py.md">memory.py</a>              # Kalıcı çok oturumlu bellek (DB destekli)
│   ├── <a href="docs/module-notes/core/rag.py.md">rag.py</a>                 # ChromaDB + BM25 hibrit RAG motoru
│   ├── agent_metrics.py       # Ajan bazlı metrik toplayıcı (YENİ — v3.0.x+)
│   ├── dlp.py                 # DLP & PII maskeleme: token, key, TC kimlik no, JWT vb. (YENİ — v3.0.21+)
│   ├── hitl.py                # Human-in-the-Loop onay geçidi: async polling, web API (YENİ — v3.0.21+)
│   ├── judge.py               # LLM-as-a-Judge: RAG alaka puanı + halüsinasyon riski (YENİ — v3.0.21+)
│   ├── router.py              # Cost-Aware Model Routing: karmaşıklık skoru + bütçe eşiği (YENİ — v3.0.22+)
│   ├── entity_memory.py       # Entity/Persona Memory: kullanıcı bazlı TTL+LRU kişisel bellek (YENİ — v3.0.22+)
│   ├── cache_metrics.py       # Semantic cache hit/miss sayaçları + Prometheus metrikleri (YENİ — v3.0.22+)
│   ├── active_learning.py     # Active Learning + LoRA/QLoRA: FeedbackStore, DatasetExporter, LoRATrainer (YENİ — v3.0.23+)
│   ├── vision.py              # Multimodal Vision Pipeline: UI mockup → kod, provider formatları (YENİ — v3.0.23+)
│   ├── multimodal.py          # Video frame + STT tabanlı medya bağlamı oluşturma
│   └── voice.py               # TTS adaptörleri ve WebSocket ses segmentasyonu
│
├── docker/                    # Gözlemlenebilirlik (observability) ayarları
│   ├── grafana/               # Dashboard ve provisioning dosyaları
│   └── prometheus/            # Scrape yapılandırması
│
├── managers/
│   ├── <a href="docs/module-notes/managers/__init__.py.md">__init__.py</a>
│   ├── <a href="docs/module-notes/managers/code_manager.py.md">code_manager.py</a>        # Dosya I/O + Docker REPL + denetim
│   ├── <a href="docs/module-notes/managers/security.py.md">security.py</a>            # OpenClaw erişim kontrol sistemi
│   ├── <a href="docs/module-notes/managers/github_manager.py.md">github_manager.py</a>      # GitHub API entegrasyonu
│   ├── <a href="docs/module-notes/managers/system_health.py.md">system_health.py</a>       # CPU/RAM/GPU izleme
│   ├── <a href="docs/module-notes/managers/web_search.py.md">web_search.py</a>          # Tavily + Google + DuckDuckGo arama
│   ├── <a href="docs/module-notes/managers/package_info.py.md">package_info.py</a>        # PyPI + npm + GitHub Releases
│   ├── <a href="docs/module-notes/managers/todo_manager.py.md">todo_manager.py</a>        # Görev takip yöneticisi
│   ├── browser_manager.py     # Playwright/Selenium + HITL korumalı tarayıcı otomasyonu
│   ├── slack_manager.py       # Slack Bot SDK + Webhook fallback, Block Kit (YENİ — v3.0.24+)
│   ├── jira_manager.py        # Jira Cloud REST API v3, Basic Auth / Bearer (YENİ — v3.0.24+)
│   └── teams_manager.py       # Teams MessageCard + Adaptive Card v1.4, HITL onay kartı (YENİ — v3.0.24+)
│
├── migrations/                # Alembic veritabanı geçiş dosyaları
│   ├── <a href="docs/module-notes/migrations/env.py.md">env.py</a>
│   ├── <a href="docs/module-notes/migrations/script.py.mako.md">script.py.mako</a>
│   └── versions/
│       ├── 0001_baseline_schema.py     # Temel şema (users, sessions, messages, quotas)
│       ├── 0002_prompt_registry.py     # Prompt registry tablosu (v3.0.9+)
│       ├── 0003_audit_trail.py         # Tenant RBAC audit trail geçişi
│       └── 0004_faz_e_tables.py        # Faz E kampanya/içerik/coverage tabloları
│
├── scripts/                   # Operasyon, test ve metrik betikleri
│   ├── <a href="docs/module-notes/scripts/audit_metrics.sh.md">audit_metrics.sh</a>       # Kod satır sayısı ve audit metrikleri üretici
│   ├── <a href="docs/module-notes/scripts/check_empty_test_artifacts.sh.md">check_empty_test_artifacts.sh</a> # CI kalite kapısı kontrolleri
│   ├── <a href="docs/module-notes/scripts/collect_repo_metrics.sh.md">collect_repo_metrics.sh</a>
│   ├── <a href="docs/module-notes/scripts/install_host_sandbox.sh.md">install_host_sandbox.sh</a> # Zero-trust sandbox (gVisor/Kata) hazırlığı
│   ├── <a href="docs/module-notes/scripts/load_test_db_pool.py.md">load_test_db_pool.py</a>   # DB bağlantı havuzu yük testi
│   └── <a href="docs/module-notes/scripts/migrate_sqlite_to_pg.py.md">migrate_sqlite_to_pg.py</a> # SQLite'tan PostgreSQL'e geçiş aracı
│
├── runbooks/                  # Operasyonel kılavuzlar
│   ├── <a href="docs/module-notes/runbooks/production-cutover-playbook.md.md">production-cutover-playbook.md</a>  # Kurumsal sürüme geçiş yönergeleri
│   ├── observability_simulation.md                                           # Jaeger + Redis + PG izlenebilirlik demo rehberi (YENİ)
│   ├── plugin_marketplace_demo.md                                            # Plugin API yükleme + ajan çağırma demo (YENİ)
│   └── tenant_rbac_scenarios.md                                              # Tenant A/B RBAC senaryo uçtan uca rehberi (YENİ)
│
├── plugins/                   # Plugin / Marketplace ajanları (YENİ — v3.0.12+)
│   ├── crypto_price_agent.py  # CryptoPriceAgent: CoinGecko API üzerinden BTC/ETH/SOL fiyat sorgulama örnek plugin (49 satır)
│   └── upload_agent.py        # UploadAgent: temel upload/entegrasyon şablon ajanı (10 satır)
│
├── launcher_gui/              # Eel tabanlı masaüstü başlatıcı frontend
│   ├── index.html             # Başlatıcı arayüzü
│   ├── script.js              # Başlatıcı mantığı
│   └── style.css              # Başlatıcı stilleri
│
├── web_ui_react/              # Modern React SPA arayüzü (Vite tabanlı)
│   ├── src/                     # React bileşenleri, hook'lar ve API yardımcıları
│   │   ├── components/VoiceAssistantPanel.jsx   # Duplex voice oturumu, transcript ve VAD paneli
│   │   ├── components/SwarmFlowPanel.jsx        # Canlı swarm karar grafiği ve operasyon yüzeyi
│   │   └── hooks/useVoiceAssistant.js           # MediaRecorder + WebSocket + VAD istemci hook'u
│   ├── package.json             # npm bağımlılıkları ve script'ler
│   └── vite.config.js           # Vite build konfigürasyonu
│
├── web_ui/                      # Legacy / fallback Web UI
│   ├── <a href="docs/module-notes/web_ui/index.html.md">index.html</a>
│   ├── <a href="docs/module-notes/web_ui/style.css.md">style.css</a>
│   ├── <a href="docs/module-notes/web_ui/chat.js.md">chat.js</a>                # WebSocket streaming, canlı durum akışı
│   ├── <a href="docs/module-notes/web_ui/sidebar.js.md">sidebar.js</a>          # Oturum yönetimi
│   ├── <a href="docs/module-notes/web_ui/rag.js.md">rag.js</a>                  # RAG belge UI
│   └── <a href="docs/module-notes/web_ui/app.js.md">app.js</a>                  # Uygulama başlatma, auth, bütçe yönetimi
│
├── grafana/                   # Grafana dashboard + provisioning (YENİ — v3.0.22+)
│   ├── dashboards/sidar_overview.json      # Cache Hit Rate gauge + Hit/Miss Trend + LLM Cost panelleri
│   └── provisioning/                       # Dashboards + Prometheus datasource YAML
│
├── scripts/
│   ├── check_env_parity.sh    # config.py ↔ .env.example parite doğrulama (YENİ — v3.0.21+)
│   └── (diğer betikler — audit_metrics.sh, collect_repo_metrics.sh vb.)
│
├── <a href="docs/module-notes/tests.md">tests/</a>                     # Kapsamlı test paketi (142 test_*.py modülü / 142 tests/*.py dosyası)
├── <a href="docs/module-notes/data/gitkeep.md">data/</a>                      # RAG ve varsayılan yerel depolama dosyaları
├── docs/                      # Proje belgeleri ve modül notları
│   └── module-notes/          # Her modül için ayrıntılı teknik not dosyaları
├── helm/                      # Kubernetes Helm chart (v4.3.0 gözlemlenebilirlik genişletmeleri)
│   └── sidar/
│       ├── Chart.yaml          # Helm chart meta verisi
│       ├── values.yaml         # Varsayılan Helm değerleri
│       ├── values-staging.yaml # Staging ortamı değerleri
│       ├── values-prod.yaml    # Prod ortamı değerleri
│       └── templates/          # Kubernetes kaynak şablonları
│           ├── _helpers.tpl, NOTES.txt
│           ├── deployment-web.yaml, deployment-ai-worker.yaml
│           ├── deployment-otel-collector.yaml, deployment-jaeger.yaml, deployment-zipkin.yaml
│           ├── configmap-otel-collector.yaml, configmap-grafana-slo-dashboard.yaml
│           ├── service-web.yaml, service-postgresql.yaml, service-redis.yaml
│           ├── service-otel-collector.yaml, service-jaeger.yaml, service-zipkin.yaml
│           ├── statefulset-postgresql.yaml, statefulset-redis.yaml
│           ├── hpa-web.yaml, pdb-web.yaml, networkpolicy-web.yaml
│           └── secret-postgresql.yaml
├── <a href="docs/module-notes/coveragerc.md">.coveragerc</a>                # Coverage kalite kapısı kuralları (%100 eşik)
├── <a href="docs/module-notes/env.example.md">.env.example</a>               # Ortam değişkeni şablonu
├── AUDIT_REPORT_v5.0.md       # v5.0 kurumsal geçiş + coverage kapanışı denetim raporu
├── <a href="docs/module-notes/CHANGELOG.md.md">CHANGELOG.md</a>               # Sürüm notları ve değişiklik geçmişi
├── <a href="docs/module-notes/CLAUDE.md.md">CLAUDE.md</a>                  # Geliştirici rehberi
├── <a href="docs/module-notes/PROJE_RAPORU.md.md">PROJE_RAPORU.md</a>            # Ana mimari ve denetim raporu
├── <a href="docs/module-notes/README.md.md">README.md</a>                  # Proje tanıtım ve kurulum belgesi
├── <a href="docs/module-notes/RFC-MultiAgent.md.md">RFC-MultiAgent.md</a>          # Multi-agent mimari tasarım dokümanı
└── <a href="docs/module-notes/SIDAR.md.md">SIDAR.md</a>                   # Sistem promptları ve proje kuralları
</pre>

---

## 3. Modül Bazında Detaylı Analiz

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, v4.3.0 kod tabanındaki Faz 4 (kurumsal yetenekler) ve Faz 5 (multi-agent swarm + OTel) genişlemelerini yansıtacak şekilde sadeleştirilmiş bir dizin sunar. Ayrıntılı modül notu bulunan dosyalar `docs/module-notes/` altına bağlanmış, henüz ayrı notu olmayan yeni modüller için ise doğrudan kaynak dosya adı belirtilmiştir.

### 3.A Çekirdek Giriş Dosyaları

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.1 | `config.py` | [docs/module-notes/config.py.md](docs/module-notes/config.py.md) |
| 3.2 | `main.py` | [docs/module-notes/main.py.md](docs/module-notes/main.py.md) |
| 3.3 | `cli.py` | [docs/module-notes/cli.py.md](docs/module-notes/cli.py.md) |
| 3.4 | `web_server.py` | [docs/module-notes/web_server.py.md](docs/module-notes/web_server.py.md) |

### 3.B Çoklu Ajan (Multi-Agent Swarm) ve Dinamik Rol Mimarisi

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.5 | `agent/sidar_agent.py` | [docs/module-notes/agent/sidar_agent.py.md](docs/module-notes/agent/sidar_agent.py.md) |
| 3.6 | `agent/auto_handle.py` | [docs/module-notes/agent/auto_handle.py.md](docs/module-notes/agent/auto_handle.py.md) |
| 3.7 | `agent/definitions.py`, `agent/tooling.py`, `agent/base_agent.py` | [docs/module-notes/agent/definitions.py.md](docs/module-notes/agent/definitions.py.md) / [docs/module-notes/agent/tooling.py.md](docs/module-notes/agent/tooling.py.md) / [docs/module-notes/agent/base_agent.py.md](docs/module-notes/agent/base_agent.py.md) |
| 3.8 | `agent/core/supervisor.py`, `agent/swarm.py` | [docs/module-notes/agent/core/supervisor.py.md](docs/module-notes/agent/core/supervisor.py.md); `agent/swarm.py` için ayrı modül notu henüz yok |
| 3.9 | `agent/registry.py`, `agent/core/registry.py` | [docs/module-notes/agent/core/registry.py.md](docs/module-notes/agent/core/registry.py.md); `agent/registry.py` için ayrı modül notu henüz yok |
| 3.10 | `agent/core/contracts.py`, `agent/core/event_stream.py`, `agent/core/memory_hub.py` | [docs/module-notes/agent/core/contracts.py.md](docs/module-notes/agent/core/contracts.py.md), [docs/module-notes/agent/core/event_stream.py.md](docs/module-notes/agent/core/event_stream.py.md), [docs/module-notes/agent/core/memory_hub.py.md](docs/module-notes/agent/core/memory_hub.py.md) |
| 3.11 | `agent/roles/coder_agent.py`, `researcher_agent.py`, `reviewer_agent.py`, `coverage_agent.py`, `poyraz_agent.py` | [docs/module-notes/agent/roles/coder_agent.py.md](docs/module-notes/agent/roles/coder_agent.py.md), [docs/module-notes/agent/roles/researcher_agent.py.md](docs/module-notes/agent/roles/researcher_agent.py.md), [docs/module-notes/agent/roles/reviewer_agent.py.md](docs/module-notes/agent/roles/reviewer_agent.py.md); Faz E rolleri için ayrı modül notu henüz yok |
| 3.12 | `plugins/` (`crypto_price_agent.py`, `upload_agent.py`) | Ayrı modül notu henüz yok; runtime plugin marketplace örnekleri |

### 3.C Core (Kurumsal Sistemler) ve Manager Katmanı

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.13 | `core/llm_client.py` | [docs/module-notes/core/llm_client.py.md](docs/module-notes/core/llm_client.py.md) |
| 3.14 | `core/router.py` | Ayrı modül notu henüz yok; maliyet/bağlam odaklı model yönlendirme katmanı |
| 3.15 | `core/dlp.py` | Ayrı modül notu henüz yok; DLP & PII maskeleme katmanı |
| 3.16 | `core/hitl.py` | Ayrı modül notu henüz yok; Human-in-the-Loop onay akışı |
| 3.17 | `core/judge.py`, `core/active_learning.py` | Ayrı modül notu henüz yok; LLM-as-a-Judge + aktif öğrenme geri besleme döngüsü |
| 3.18 | `core/entity_memory.py`, `core/memory.py` | [docs/module-notes/core/memory.py.md](docs/module-notes/core/memory.py.md); `entity_memory.py` için ayrı modül notu henüz yok |
| 3.19 | `core/rag.py` | [docs/module-notes/core/rag.py.md](docs/module-notes/core/rag.py.md) |
| 3.20 | `core/db.py` | [docs/module-notes/core/db.py.md](docs/module-notes/core/db.py.md) |
| 3.21 | `core/llm_metrics.py`, `core/cache_metrics.py`, `core/agent_metrics.py` | [docs/module-notes/core/llm_metrics.py.md](docs/module-notes/core/llm_metrics.py.md); diğer metrik modülleri için ayrı not henüz yok |
| 3.22 | `core/vision.py` | Ayrı modül notu henüz yok; multimodal mockup/görsel işleme hattı |
| 3.23 | `core/voice.py` | Ayrı modül notu henüz yok; TTS (Text-to-Speech) adaptörleri ve WebSocket ses segmentasyonu (v5.0-alpha) |
| 3.24 | `managers/security.py`, `managers/code_manager.py` | [docs/module-notes/managers/security.py.md](docs/module-notes/managers/security.py.md), [docs/module-notes/managers/code_manager.py.md](docs/module-notes/managers/code_manager.py.md) |
| 3.25 | `managers/github_manager.py`, `managers/package_info.py` | [docs/module-notes/managers/github_manager.py.md](docs/module-notes/managers/github_manager.py.md), [docs/module-notes/managers/package_info.py.md](docs/module-notes/managers/package_info.py.md) |
| 3.26 | `managers/system_health.py`, `managers/web_search.py`, `managers/todo_manager.py`, `managers/browser_manager.py` | [docs/module-notes/managers/system_health.py.md](docs/module-notes/managers/system_health.py.md), [docs/module-notes/managers/web_search.py.md](docs/module-notes/managers/web_search.py.md), [docs/module-notes/managers/todo_manager.py.md](docs/module-notes/managers/todo_manager.py.md); `browser_manager.py` için ayrı modül notu henüz yok |
| 3.27 | `managers/jira_manager.py`, `managers/slack_manager.py`, `managers/teams_manager.py` | Ayrı modül notu henüz yok; kurumsal iletişim ve iş akışı entegrasyonları |

### 3.D UI, Altyapı ve Operasyon

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.27 | `web_ui/`, `web_ui_react/`, `VoiceAssistantPanel.jsx`, `useVoiceAssistant.js` | [docs/module-notes/web_ui/index.html.md](docs/module-notes/web_ui/index.html.md); React SPA için ayrı modül notu henüz yok, ancak duplex ses UX bileşenleri rapor içinde ayrıca belgelenmiştir |
| 3.28 | `github_upload.py`, `gui_launcher.py` | [docs/module-notes/github_upload.py.md](docs/module-notes/github_upload.py.md); `gui_launcher.py` için ayrı modül notu henüz yok |
| 3.29 | `migrations/` (`0001`-`0004`), `scripts/` | [docs/module-notes/migrations/env.py.md](docs/module-notes/migrations/env.py.md) |
| 3.30 | `docker/`, `runbooks/`, `helm/` | [docs/module-notes/docker/prometheus/prometheus.yml.md](docs/module-notes/docker/prometheus/prometheus.yml.md); `helm/` için ayrı modül notu henüz yok |

---

### 3.D.1 React İstemci Tarafı Ses Bileşenleri

- **`web_ui_react/src/components/VoiceAssistantPanel.jsx`:** Duplex ses oturumunun özet panelidir; mikrofonu başlat/durdur, aktif TTS oynatmasını kes, son transcript'i görüntüle ve VAD / buffer / turn bilgisini operatöre görünür kılar.
- **`web_ui_react/src/hooks/useVoiceAssistant.js`:** `MediaRecorder`, `getUserMedia`, `AnalyserNode` ve `/ws/voice` WebSocket akışını tek yerde yöneten istemci orkestrasyon katmanıdır. Hook; VAD threshold/silence takibi, base64 ses paketleme, diagnostics halkası ve barge-in sırasında oynatmayı sonlandırma davranışını yönetir.
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
- Sunum katmanı, React build'i mevcutsa `web_ui_react/dist` dizinini otomatik önceliklendiren akıllı statik servisleme modeline geçirilmiştir.
- `web_ui_react/src/App.jsx` içinde P2PDialoguePanel ve SwarmFlowPanel bileşenleriyle canlı ajan diyaloğu ve görev akışı görünürlüğü SPA deneyiminde sunulur.

#### 4.3.9 Tenant Bazlı Erişim Kontrol Listeleri (ACL) ve Audit Trail
- `access_policy_middleware` ve `_resolve_policy_from_request` ile rota/aksiyon bazlı kaynak sınıflandırması yapılarak tenant düzeyinde ince taneli yetkilendirme uygulanır.
- `/admin/policies` uç noktaları üzerinden policy CRUD/inceleme yüzeyleri açılır; izin kararları audit trail olarak kalıcı biçimde kaydedilerek RBAC modeli operasyonel yönetim katmanına taşınır.

#### 4.3.10 DLP + HITL Güvenlik Geçidi
- DLP katmanı, LLM'e çıkmadan önce hassas verileri (PII, token, kart numarası vb.) maskeleyerek mimarinin giriş/çıkışında veri sızıntısı riskini düşürür.
- HITL döngüsü, üretim etkili veya yıkıcı işlemlerde insan onayı bekleyerek swarm/araç katmanının güvenli şekilde karar vermesini sağlar.

---

## 5. Güvenlik Analizi

[⬆ İçindekilere Dön](#içindekiler)

### 5.1 Güvenlik Kontrolleri Özeti

| Kontrol | Durum | Konum |
|---------|-------|-------|
| Path traversal engelleme | ✓ Aktif | `managers/security.py` |
| Symlink koruması | ✓ Aktif | `managers/security.py` |
| Hassas yol engelleme | ✓ Aktif | `managers/security.py` |
| Bearer Token Auth | ✓ Aktif (DB tabanlı) | `web_server.py` — `basic_auth_middleware`, `/auth/login`, `/auth/register`, `/auth/me` |
| Çoklu Kullanıcı (Tenant) İzolasyonu | ✓ Aktif (`user_id` tabanlı) | `core/db.py` — `users`, `auth_tokens`, `sessions`, `messages`, `provider_usage_daily`, `user_quotas` |
| WebSocket zorunlu Auth Handshake | ✓ Aktif (policy violation `1008`) | `web_server.py` — `/ws/chat`, `_ws_close_policy_violation()` |
| Fail-Closed Bellek Erişimi | ✓ Aktif (`MemoryAuthError`) | `core/memory.py` — `_require_active_user()` |
| Zero-Trust Docker Sandbox | ✓ Aktif (`network_mode="none"`, `mem_limit`, `nano_cpus`) | `managers/code_manager.py` — `execute_code()` |
| Mikro-VM Runtime Uyum Katmanı | ✓ Aktif (`runsc` / `kata-runtime` çözümleme) | `managers/code_manager.py` — `_resolve_runtime()` |
| DDoS koruması | ✓ Aktif (IP başına hız sınırı) | `web_server.py` — `ddos_rate_limit_middleware` |
| CORS kısıtlaması | ✓ Aktif (allowlist) | `web_server.py` — CORS middleware |
| Rate limiting | ✓ Aktif (HTTP + WS + Redis fallback) | `web_server.py` |
| DLP / PII Maskeleme | ✓ Aktif (`[MASKED]` temelli) | `core/dlp.py`, `core/llm_client.py` |
| HITL Onay Geçidi | ✓ Aktif (yüksek riskli eylemler için duraklatma/onay) | `core/hitl.py`, `web_server.py` |
| Tenant RBAC | ✓ Aktif (tenant + resource/action policy) | `web_server.py`, `core/db.py` |
| Audit Trail | ✓ Aktif (DB kalıcılığı) | `migrations/versions/0003_audit_trail.py`, `core/db.py`, `web_server.py` |
| LLM QA Devre Kesici | ✓ Aktif (`MAX_QA_RETRIES=3`) | `agent/sidar_agent.py` |
| GitHub binary engelleme | ✓ Aktif | `managers/github_manager.py` |
| Git upload blacklist | ✓ Aktif | `github_upload.py` |
| Bilinmeyen erişim seviyesi | ✓ Sandbox'a normalize | `managers/security.py` |
| Branch adı enjeksiyon koruması | ✓ Regex `_BRANCH_RE` | `managers/github_manager.py` |
| GitHub Webhook İmzası | ✓ Aktif (HMAC-SHA256) | `web_server.py` — `/api/webhook` |
| Büyük Dosya Okuma Limit | ✓ Aktif (boyut limiti) | `web_server.py` — `/file-content` |
| K8s Network Policy İzolasyonu | ✓ Aktif (Helm şablonu mevcut) | `helm/sidar/templates/networkpolicy-web.yaml` |
| K8s Secret Yönetimi | ✓ Aktif (Helm şablonu mevcut) | `helm/sidar/templates/secret-postgresql.yaml` |

### 5.2 Güvenlik Seviyeleri Davranışı

```
RESTRICTED → yalnızca okuma + analiz (yazma/çalıştırma/shell YOK)
SANDBOX    → okuma + /temp yazma + Docker Python REPL
FULL       → tam erişim (shell, git, npm, proje geneli yazma)
```

**QA ve Kod Onay Bariyeri (ReviewerAgent Süzgeci):** Hangi erişim seviyesinde (Sandbox veya Full) çalışılırsa çalışılsın, CoderAgent çıktıları ReviewerAgent doğrulamasından geçer. Ek olarak `MAX_QA_RETRIES=3` sınırı ile Coder ↔ Reviewer geri besleme zinciri fail-safe biçimde sonlandırılır; sonsuz döngü ve maliyet artışı engellenir.

**HITL Güvenlik Freni:** Yüksek riskli işlemler ayrıca Human-in-the-Loop kapısına alınabilir; sistem işlemi duraklatır ve admin/kullanıcı onayı olmadan kritik aksiyonu tamamlamaz.

### 5.3 Kurumsal Zero-Trust Savunma Sütunları (v3.0)

#### 5.3.1 Path Traversal + Blacklist + Symlink Koruması
- `SecurityManager`, ham yol girdilerinde `../` ve kritik sistem dizinlerini (`/etc`, `/proc`, `/sys`, `C:\Windows`, `Program Files`) `_DANGEROUS_PATH_RE` ile reddeder.
- `.env`, `.git`, `sessions`, `__pycache__` gibi hassas yollar `_BLOCKED_PATTERNS` ile ek katmanda engellenir; bu kural FULL seviyede dahi güvenlik zeminini korur.
- `Path.resolve()` + `relative_to(base_dir)` kontrolleri ile symlink üzerinden kök dizin dışına kaçış girişimleri fail-closed biçimde bloklanır.

#### 5.3.2 Docker Sandbox İzolasyonu (Kod Çalıştırma)
- `execute_code` akışı, kodu izole Docker konteynerinde çalıştırır; `network_mode="none"`, `mem_limit` ve `nano_cpus` ile ağ/kaynak sınırları uygulanır.
- Sandbox katmanı erişilemezse politika seviyesine göre kontrollü davranış devreye girer (SANDBOX modunda reddetme, FULL modda sınırlı fallback).

#### 5.3.3 Kriptografik Kimlik/Oturum Güvenliği (Güncellendi)
- Parola doğrulama akışı `PBKDF2-HMAC-SHA256` + salt + sabit-zamanlı karşılaştırma (`secrets.compare_digest`) ile uygulanır.
- **[ÖNEMLİ] Kriptografik Güçlendirme:** Parola türetme algoritmasındaki iterasyon sayısının (önceki: `120000`) güncel OWASP standartlarına (min `600000`) uygun hale getirilmesi teknik bir borç olarak işaretlenmiştir. Yeni nesil GPU'ların kırabilme kapasitesine karşı kurumsal sistemlerde bu değerin artırılması zorunludur.
- Oturum belirteçleri `secrets.token_urlsafe(...)` ile üretilir; kullanıcı/oturum anahtarlarında UUID kullanımı tahmin edilebilirlik riskini azaltır.
- WebSocket kanalında `auth` handshake zorunludur; geçersiz/eksik token durumunda bağlantı policy violation ile kapatılır.

#### 5.3.4 OOM/Binary ve Rate-Limit Savunmaları
- GitHub dosya okuma katmanında güvenli uzantı/uzantısız whitelist uygulanır; binary/uygunsuz dosya tipleri decode edilmeden reddedilir.
- API yüzeyinde DDoS/rate-limit middleware'leri ve Redis destekli limit mekanizmasıyla ani yüklenmelerde servis kararlılığı korunur.
- Büyük dosya okuma limitleri ve güvenli metin odaklı işleme yaklaşımı, bellek şişmesi (OOM) riskini azaltan uygulama savunması sağlar.

#### 5.3.5 Web UI XSS Sertleştirmesi
- `marked` ile üretilen HTML, istemci tarafında `sanitizeRenderedHtml(...)` süzgecinden geçirilir.
- `script/iframe/object/embed/form/meta/link` etiketleri ve `javascript:` gibi tehlikeli URL şemaları temizlenerek içerik render edilir.

#### 5.3.6 DLP (Veri Sızıntısı Önleme / PII Maskeleme)
- `core/dlp.py`, kullanıcı girdilerindeki kredi kartı, TC kimlik, e-posta, telefon, bearer token ve benzeri hassas desenleri regex/desen tanıma ile tespit eder.
- Bu katman, içerik üçüncü parti LLM sağlayıcılarına gitmeden önce verileri `[MASKED]` benzeri güvenli temsillere dönüştürerek hassas veri sızıntısı riskini azaltır.

#### 5.3.7 HITL (Human-in-the-Loop) Onay Katmanı
- `core/hitl.py` ve Web API yüzeyi, yüksek riskli işlemleri doğrudan yürütmek yerine bekleme durumuna alır ve açık kullanıcı/onaycı kararı bekler.
- Bu model; dosya silme, veritabanı değişikliği, yıkıcı komutlar veya üretim etkili eylemlerde ajan otonomisini kontrollü biçimde sınırlar.

#### 5.3.8 Multi-Tenant RBAC ve Audit Trail
- Çok kiracılı veri modeli ile kullanıcı/policy kayıtları tenant bağlamında değerlendirilir; `access_policy_middleware` rota, kaynak ve aksiyon bazlı karar üretir.
- Kritik izin kararları ile policy değişiklikleri, `0003_audit_trail` migrasyonu sonrası kalıcı audit log tablosuna yazılarak denetlenebilirlik sağlanır.

#### 5.3.9 Altyapı Ağ İzolasyonu ve Sırlar
- Helm chart içindeki `networkpolicy-web.yaml`, Kubernetes pod'ları arasında yalnızca gerekli trafik yollarını açık bırakan sıkı ağ izolasyonu yaklaşımını belgeler.
- Hassas bağlantı bilgileri ve veritabanı sırları, `secret-postgresql.yaml` ve ortam değişkenleri üzerinden izole edilerek uygulama katmanının dışında da savunma derinliği oluşturulur.

---

## 6. Test Kapsamı

[⬆ İçindekilere Dön](#içindekiler)

Güncel depoda test envanteri kurumsal kalite kapılarına göre agresif biçimde genişletilmiştir:

- **`test_*.py` modül sayısı:** **213**
- **`tests/*.py` toplamı (`conftest.py` + `__init__.py` dahil):** **215**
- **Toplam test satırı (`tests/*.py`):** **65.729**
- **Kapsama politikası:** `.coveragerc`, `pytest.ini`, `run_tests.sh` ve CI hattı ile yönetilen **%100 hard gate**

**Öne çıkan test kategorileri (v5.0.0-alpha):**
- **Coverage / Sert kalite kapısı:** `test_quick_100.py`, `test_ultimate_coverage.py`, `pytest-cov`, `.coveragerc`, `run_tests.sh`
- **Kurumsal izolasyon ve RBAC:** `test_tenant_rbac_scenarios.py`, `test_rbac_policy_runtime.py`, `test_db_postgresql_branches.py`
- **Güvenlik (DLP & HITL):** `test_dlp_masking.py`, `test_hitl_approval.py`, `test_github_webhook.py`, `test_web_ui_security_improvements.py`
- **Semantic Cache / Redis:** `test_semantic_cache_runtime.py`, `test_llm_client_retry_helpers.py`
- **Çoklu ajan ve Swarm:** `test_swarm_orchestrator.py`, `test_supervisor_agent.py`, `test_reviewer_agent.py`, `test_event_stream_runtime.py`
- **Plugin Marketplace:** `test_plugin_marketplace_flow.py` — dinamik ajan yükleme, `AgentRegistry` kaydı ve çağrı akışı doğrulaması
- **Observability / OTel:** `test_otel_rag_spans.py`, `test_observability_stack_compose.py`, `test_llm_metrics_runtime.py`, `test_grafana_dashboard_provisioning.py`
- **LLM-as-a-Judge ve Active Learning:** `test_llm_judge.py`, `test_active_learning.py`
- **Altyapı ve migration:** `test_migration_assets.py`, `test_migration_ci_guards.py`, `test_observability_stack_compose.py`, `test_sandbox_runtime_profiles.py`

> Not: Önceki audit notlarında geçen 0 bayt test artifact uyarıları tarihsel kayıt niteliğindedir; güncel pipeline `find tests -type f -size 0` kontrolüyle bu durumu bloklayıcı kalite kapısı olarak yönetir.

### 6.1 CI/CD Pipeline Durumu

| Kalite Kapısı | Durum | Kaynak |
|---|---|---|
| Tüm testleri çalıştır (`run_tests.sh`) | ✅ Aktif | `.github/workflows/ci.yml`, `run_tests.sh` |
| Coverage Quality Gate (`fail_under=100`) | ✅ Zorunlu | `.coveragerc`, `run_tests.sh`, `.github/workflows/ci.yml` |
| Ayrı coverage adımı (`--cov-fail-under=100`) | ✅ Aktif | `.github/workflows/ci.yml` |
| Boş test artifact engeli (`find tests -size 0`) | ✅ Zorunlu | `.github/workflows/ci.yml`, `scripts/check_empty_test_artifacts.sh` |
| `pg_stress` izolasyonu | ✅ Aktif | `.github/workflows/ci.yml`, `tests/test_db_postgresql_branches.py` |
| Sandbox/Reviewer sertleştirme testi | ✅ Aktif | `tests/test_sandbox_runtime_profiles.py`, `tests/test_reviewer_agent.py` |
| Swarm + Active Learning hedefli regresyon dilimi | ✅ Aktif | `.github/workflows/ci.yml`, `tests/test_swarm_orchestrator.py`, `tests/test_active_learning.py` |
| Production cutover rehearsal genişletmesi | ✅ Aktif | `.github/workflows/migration-cutover-checks.yml`, `tests/test_migration_ci_guards.py`, `tests/test_swarm_orchestrator.py`, `tests/test_active_learning.py` |

Bu yapı ile test disiplini yalnızca birim test sayısına değil, **coverage barajı + artifact hijyeni + enterprise senaryo regresyonları** üzerine kurulu kurumsal bir kalite modeline taşınmıştır. Swarm orkestrasyonu ile Active Learning hattı da artık bu model içinde açık isimli hedefli regresyon dilimi olarak ayrı görünürlük kazanmıştır.

### 6.2 Coverage Hard Gate (%100)

- `.coveragerc` içinde `fail_under = 100` ve `show_missing = True` ayarları zorunlu kalite kapısı olarak tanımlıdır.
- `pytest.ini`, `python_files = test_*.py` ve `asyncio_mode = auto` ayarlarıyla aynı test evrenini deterministik biçimde çalıştırır.
- CI hattı (`.github/workflows/ci.yml`) coverage eşiğinden hemen önce `tests/test_swarm_orchestrator.py` ve `tests/test_active_learning.py` için hedefli bir regresyon dilimi koşturur; ardından ayrı bir adımda `python -m pytest -q --cov=. --cov-report=term-missing --cov-fail-under=100` komutu ile coverage eşiğini uygular.
- `run_tests.sh` betiği de `COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-100}"` değişkeniyle aynı eşiği yerelde tekrarlar.
- `migration-cutover-checks.yml` production rehearsal hattı da aynı Swarm + Active Learning dilimini `tests/test_migration_ci_guards.py` guard testi ile birlikte çalıştırarak veri migrasyonu, connection pool smoke ve öğrenme/orkestrasyon omurgasını tek cutover zincirinde toplar.
- Depoda `test_quick_100.py` ve `test_ultimate_coverage.py` gibi agresif kapsama odaklı testler bulunur; bu yaklaşım, "test çalıştı" seviyesinin ötesinde **ölçülebilir kapsam** zorunluluğu getirir.

### 6.3 Test Havuzu ve Modüler Senaryolar

- Güncel depoda `test_*.py` desenine uyan **213 test modülü** bulunur; `tests/*.py` toplamı (yardımcı dosyalar dahil) **215** adettir.
- Test havuzu yalnızca klasik unit testlerden oluşmaz; tenant veri izolasyonu, RBAC policy enforcement, DLP maskeleme, HITL onay akışı, semantic cache eviction/benzerlik mantığı, swarm görev dağıtımı ve plugin marketplace gibi enterprise senaryoları kapsar.
- Örnek yüksek değerli senaryolar: `test_tenant_rbac_scenarios.py`, `test_dlp_masking.py`, `test_hitl_approval.py`, `test_semantic_cache_runtime.py`, `test_swarm_orchestrator.py`, `test_plugin_marketplace_flow.py`, `test_otel_rag_spans.py`, `test_llm_judge.py`, `test_active_learning.py`.

### 6.4 Asenkron Test Altyapısı

- `pytest.ini` içinde `python_files = test_*.py`, `asyncio_mode = auto` ve `asyncio_default_fixture_loop_scope = session` ayarları ile tüm async testler otomatik olarak session kapsamlı event loop'ta çalışır.
- `tests/conftest.py` standart `pytest-asyncio` mimarisine geçirilmiştir: deprecated `event_loop` override kaldırılmış, session kapsamlı event loop yönetimi `pytest.ini` üzerinden yapılandırılmıştır.
- `pytest.ini`'ye `slow` ve `pg_stress` marker'ları eklenmiştir; PostgreSQL bağlantı havuzu stres testleri `-m pg_stress` ile izole çalıştırılabilir.
- CI (`.github/workflows/ci.yml`) üzerinde ayrı `pg-stress` job'ı yer alır; PostgreSQL 16 service container, Alembic migration ve `tests/test_db_postgresql_branches.py` üstünden bağlantı havuzu yük testi otomatik olarak çalışır.

---

## 7. Temel Bağımlılıklar

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, güncel `pyproject.toml`, `requirements-dev.txt`, `environment.yml` ve `web_ui_react/package.json` dosyalarına göre v5.0.0-alpha bağımlılık setini kurumsal kategorilerle özetler. (`requirements.txt` diskte bulunmaz; Python bağımlılıkları `pyproject.toml` PEP 621 standardında, React SPA bağımlılıkları ise `web_ui_react/package.json` içinde yönetilir.)

### 7.1 Asenkron Altyapı ve Uygulama Çekirdeği

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `fastapi` + `uvicorn[standard]` | ✓ Zorunlu | Web API + WebSocket katmanı |
| `httpx` | ✓ Zorunlu | Asenkron HTTP istemcisi (LLM/web entegrasyonları) |
| `python-dotenv`, `pydantic`, `cachetools`, `anyio` | ✓ Zorunlu | Konfigürasyon, doğrulama, rate-limit yardımcıları |
| `redis` | Opsiyonel (önerilen) | Dağıtık/persist rate-limit altyapısı |

### 7.2 Veritabanı, Önbellek, Migrasyon ve Telemetri

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `SQLAlchemy` + `asyncpg` | `SQLAlchemy` çekirdek; `asyncpg` opsiyonel (`[project.optional-dependencies].postgres`) | Async PostgreSQL veri katmanı |
| `redis` | Çekirdek bağımlılık | Semantic cache ve dağıtık rate-limit altyapısı |
| `alembic` | ✓ Zorunlu | Şema sürümleme ve migration zinciri |
| `prometheus-client` | ✓ Zorunlu | `/metrics` ve LLM telemetri export |
| `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp` | Opsiyonel (`[project.optional-dependencies].telemetry`) | Distributed tracing + OTLP export |
| `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-httpx` | Opsiyonel (`telemetry`) | FastAPI/HTTPX span enstrümantasyonu |
| `tiktoken` | ✓ Zorunlu | Token ölçümü ve özetleme eşikleri |

#### 7.2.1 Performans ve Ölçeklenebilirlik Notu (SQLite)
- **SQLite Concurrency Yönetimi:** SQLite modunda çalışırken, ASGI (FastAPI) eşzamanlılığında thread çakışmalarını önlemek için global bağlantı kullanımı yerine sıralı erişim/izolasyon stratejisi zorunlu kabul edilir. Kurumsal ölçekte önerilen hedef mimari doğrudan PostgreSQL (`asyncpg` pool) işletimidir; SQLite yalnızca edge/dev senaryolarında düşünülmelidir.
- **pgvector / psycopg2 Notu:** Kod tabanı pgvector backend desteği içerir; ancak mevcut `pyproject.toml` içinde `pgvector` veya `psycopg2` ayrı pinli bağımlılık olarak yer almaz. Kurumsal PostgreSQL kurulumunda bu destek ek runtime paketleri ile etkinleştirilir.

### 7.3 Güvenlik, Sandbox ve Donanım Gözlemlenebilirliği

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `docker` | Kritik/opsiyonel | Zero-Trust REPL sandbox çalıştırma |
| `nvidia-ml-py` + `psutil` | Opsiyonel | GPU/CPU/RAM donanım metrikleri |
| `cryptography` | Opsiyonel | Fernet tabanlı şifreleme yardımcıları |
| `python-multipart`, `packaging`, `pyyaml` | ✓ Zorunlu | Yardımcı runtime bileşenleri |

### 7.4 AI Sağlayıcıları, Gateway Desteği ve RAG Katmanı

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `anthropic`, `google-generativeai` | Opsiyonel (sağlayıcıya göre) | Sağlayıcıya özel resmi SDK entegrasyonları |
| `openai` | Ayrı paket pinli değil | OpenAI ve OpenAI-uyumlu uç noktalar mevcut kodda `httpx` tabanlı istemci üzerinden kullanılır |
| `litellm` | Ayrı paket pinli değil | LiteLLM Gateway desteği vardır; ancak mevcut repo bunu `litellm` Python SDK yerine HTTP/OpenAI-uyumlu gateway sözleşmesiyle tüketir |
| `chromadb` + `sentence-transformers` | Opsiyonel (`[project.optional-dependencies].rag`) | Vektör tabanlı RAG ve embedding |
| `rank-bm25` | Çekirdek bağımlılık | BM25 tabanlı hibrit arama uyumluluğu |
| `duckduckgo-search` + `beautifulsoup4` + `bleach` + `PyGithub` | Opsiyonel/çekirdek karışık kullanım | Web/GitHub entegrasyonları ve HTML sanitizasyonu |
| `torch` + `torchvision` | Opsiyonel (`[project.optional-dependencies].rag`) | Embedding ve GPU hızlandırmalı iş yükleri |

**Geçiş Notu (v4.0 hazırlığı):** `torch`, `torchvision` ve `sentence-transformers` bağımlılıkları `pyproject.toml` altında `rag` extras grubuna taşınmıştır; minimal CLI kurulumları artık ağır GPU/RAG paketlerini zorunlu çekmez.

#### 7.4.1 Frontend (React / Node.js) Paketleri

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `react`, `react-dom` | ✓ Zorunlu (`web_ui_react/package.json`) | Modern React SPA çekirdeği |
| `react-router-dom` | ✓ Zorunlu | Route tabanlı SPA navigasyonu |
| `react-markdown`, `remark-gfm`, `rehype-highlight` | ✓ Zorunlu | Sohbet/RAG çıktılarının zengin render edilmesi |
| `zustand` | ✓ Zorunlu | React durum yönetimi |
| `vite`, `@vitejs/plugin-react` | ✓ Zorunlu (frontend build) | Geliştirme sunucusu ve üretim build zinciri |
| `eslint` | ✓ Zorunlu (frontend QA) | React UI lint/kalite kapısı |

### 7.5 Test ve Kalite Kapıları (Dev Bağımlılıkları)

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-benchmark` | ✓ Zorunlu (CI/QA) | Test yürütme, async test, coverage gate, benchmark |
| `ruff`, `mypy`, `black`, `flake8` | ✓ Zorunlu (CI/QA) | Lint, statik analiz, format kalite kapıları |
| `uv` | Ortam/araç bağımlılığı | `environment.yml` ve `uv.lock` ile hızlı kilit/paket yönetimi iş akışı |

**Geçiş Notu (v3.0):**
- `requests` bağımlılığı doğrudan runtime listesinde yer almamaktadır; ana HTTP akışı `httpx` ile asenkron modele taşınmıştır.
- `rank-bm25` bağımlılığı ise mevcut bağımlılık dosyalarında hâlen tanımlıdır; hibrit RAG/BM25 uyumluluğu için opsiyonel katmanda korunmaktadır.
- `chardet` şu an doğrudan bağımlılık listesinde pinlenmemiştir; encoding fallback davranışı uygulama katmanında güvenli decode stratejileriyle yönetilmektedir.

**Auth Notu (v3.0):** Güncel kod tabanında kimlik doğrulama bearer token + DB tabanlı oturum modeli ile yürütülür. Şifre doğrulama `core/db.py` içinde PBKDF2-HMAC akışıyla yapılır; **`PyJWT~=2.9.0`** `pyproject.toml` çekirdek bağımlılıkları arasında yer alır ve `web_server.py` içinde stateless JWT token üretimi/doğrulaması için kullanılır.

---

## 8. Kod Satır Sayısı Özeti

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, 2026-03-26 tarihinde `scripts/collect_repo_metrics.sh` ve `scripts/audit_metrics.sh` ile takipli depo içeriği için yeniden üretilen `wc -l` ölçümlerini içerir.

**Hacimsel özet (yönetici görünümü):** 2026-03-26 ölçümünde takipli depo yüzeyi **408 dosya / 116.053 satır** seviyesindedir (`.py/.js/.css/.html/.md`). Python tarafında üretim kodu **32.936 satır / 70 dosya**, test havuzu **65.729 satır / 213 `test_*.py` modülü**, toplam Python hacmi ise **98.665 satır / 285 dosya** olarak doğrulanmıştır; ayrıca takipli Markdown havuzu **10.148 satır / 102 dosya** ile kurumsal dokümantasyon yükünü net biçimde göstermektedir. `web_ui_react/` altındaki **38** takipli dosya / **10.792** satırlık SPA hacmi ve `web_ui/` altındaki **4.769** satırlık legacy yüzey birlikte değerlendirildiğinde, Coverage/Poyraz ajanlarıyla genişleyen Faz E yüzeyi artık ölçülebilir ürün olgunluğunun parçası haline gelmiştir.

- **Test ağırlığı:** Python kod hacminin en büyük payı `tests/` altındaki unit, integration ve enterprise senaryo testlerinden gelir.
- **Backend + Swarm çekirdeği:** `core/`, `agent/`, `managers/` ve giriş dosyaları projenin ana motorunu oluşturan binlerce satırlık Python iş mantığını barındırır.
- **Modern frontend katmanı:** Legacy `web_ui/` korunurken `web_ui_react/` altındaki React/Vite SPA projeye ek JavaScript/JSX/CSS hacmi kazandırır.
- **Altyapı ve dokümantasyon:** Helm chart'ları, Docker/Grafana/Prometheus dosyaları, CI akışları ve runbook'lar üretim işletimini kod olarak tanımlar.

**Ölçüm notu (standart):** Kurumsal tekrar üretilebilirlik için satır sayısı raporları `scripts/audit_metrics.sh` ve `scripts/collect_repo_metrics.sh` ile otomatik üretilmelidir. Her iki betik de Git deposu içinde varsayılan olarak yalnızca takipli dosyaları ölçer.

### 8.1 Çekirdek Modüller (Güncel)

| Dosya | Satır |
|---|---:|
| `config.py` | 885 |
| `main.py` | 382 |
| `cli.py` | 290 |
| `web_server.py` | 3.213 |
| `agent/sidar_agent.py` | 689 |
| `agent/auto_handle.py` | 613 |
| `agent/definitions.py` | 169 |
| `agent/tooling.py` | 127 |
| `agent/base_agent.py` | 112 |
| `agent/registry.py` | 187 |
| `agent/swarm.py` | 541 |
| `core/llm_client.py` | 1.388 |
| `core/memory.py` | 301 |
| `core/rag.py` | 1.685 |
| `core/db.py` | 1.861 |
| `core/llm_metrics.py` | 282 |
| `core/agent_metrics.py` | 118 |
| `core/dlp.py` | 320 |
| `core/hitl.py` | 287 |
| `core/judge.py` | 476 |
| `core/router.py` | 211 |
| `core/entity_memory.py` | 281 |
| `core/cache_metrics.py` | 189 |
| `core/active_learning.py` | 772 |
| `core/vision.py` | 294 |
| `core/voice.py` | 310 |
| `managers/security.py` | 291 |
| `managers/code_manager.py` | 1.529 |
| `managers/github_manager.py` | 645 |
| `managers/system_health.py` | 538 |
| `managers/web_search.py` | 388 |
| `managers/package_info.py` | 344 |
| `managers/todo_manager.py` | 452 |
| `managers/slack_manager.py` | 234 |
| `managers/jira_manager.py` | 245 |
| `managers/teams_manager.py` | 234 |
| `managers/browser_manager.py` | 718 |
| `github_upload.py` | 295 |
| `gui_launcher.py` | 98 |

### 8.2 Multi-Agent Çekirdek ve Roller

| Dosya | Satır |
|---|---:|
| `agent/core/supervisor.py` | 291 |
| `agent/core/contracts.py` | 256 |
| `agent/core/event_stream.py` | 218 |
| `agent/core/memory_hub.py` | 55 |
| `agent/core/registry.py` | 30 |
| `agent/roles/coder_agent.py` | 168 |
| `agent/roles/researcher_agent.py` | 80 |
| `agent/roles/reviewer_agent.py` | 707 |
| `agent/roles/coverage_agent.py` | 262 |
| `agent/roles/poyraz_agent.py` | 498 |

### 8.3 Migration / Operasyon / Altyapı

| Dosya | Satır |
|---|---:|
| `migrations/env.py` | 66 |
| `migrations/versions/0001_baseline_schema.py` | 99 |
| `migrations/versions/0002_prompt_registry.py` | 53 |
| `migrations/versions/0003_audit_trail.py` | 38 |
| `migrations/versions/0004_faz_e_tables.py` | 144 |
| `scripts/migrate_sqlite_to_pg.py` | 92 |
| `scripts/load_test_db_pool.py` | 74 |
| `scripts/audit_metrics.sh` | 84 |
| `scripts/collect_repo_metrics.sh` | 35 |
| `scripts/install_host_sandbox.sh` | 201 |
| `docker/prometheus/prometheus.yml` | 8 |
| `docker/grafana/provisioning/datasources/prometheus.yml` | 9 |
| `docker/grafana/provisioning/dashboards/dashboards.yml` | 11 |
| `docker/grafana/dashboards/sidar-llm-overview.json` | 1.004 |
| `runbooks/production-cutover-playbook.md` | 182 |
| `runbooks/observability_simulation.md` | 87 |
| `runbooks/plugin_marketplace_demo.md` | 32 |
| `runbooks/tenant_rbac_scenarios.md` | 66 |
| `plugins/crypto_price_agent.py` | 50 |
| `plugins/upload_agent.py` | 11 |
| `Dockerfile` | 104 |
| `docker-compose.yml` | 264 |

### 8.4 Frontend ve Test Özeti

| Kapsam | Değer |
|---|---:|
| `web_ui/index.html` | 640 |
| `web_ui/style.css` | 1.685 |
| `web_ui/chat.js` | 711 |
| `web_ui/sidebar.js` | 413 |
| `web_ui/rag.js` | 132 |
| `web_ui/app.js` | 819 |
| **Web UI Toplamı (`web_ui/` + `web_ui_react/`)** | **15.561** |
| **Legacy UI (`web_ui/` toplam takipli satır)** | **4.769** |
| **React UI (`web_ui_react/` toplam takipli satır)** | **10.792** |
| **Voice UI alt kümesi (`VoiceAssistantPanel.jsx` + `useVoiceAssistant.js`)** | **711** |
| **Test modülü (`tests/test_*.py`)** | **213** |
| **`tests/*.py` toplam satır** | **65.729** |

### 8.5 Dizin Bazlı Hacim Özeti

| Dizin/Kapsam | Ölçüm | Değer |
|---|---|---:|
| `tests/` | `test_*.py` modül sayısı | 213 |
| `tests/` | `*.py` toplam dosya | 215 |
| `tests/` | `*.py` toplam satır | 65.729 |
| `web_ui_react/` | toplam takipli satır | 10.792 |
| `scripts/` | dosya sayısı | 7 |
| `scripts/` | toplam satır | 613 |
| `migrations/` | `.py` dosya sayısı (env.py + 4 versions) | 5 |
| `migrations/` | `*.py` toplam satır | 396 |
| `helm/sidar/` | şablon dosyası sayısı (templates/ dahil) | 25 |
| `helm/sidar/` | toplam satır | 913 |
| `docker/` | metin tabanlı stack dosyası sayısı (`*.yml`, `*.json`) | 4 |
| `docker/` | ilgili telemetri dosyaları toplam satır | 1.032 |


## 9. Modül Bağımlılık Haritası

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm artık yalnızca doğrusal import ilişkilerini değil; v4.3.0 ile belirginleşen **katmanlı Swarm mimarisini**, **güvenlik/middleware akışını**, **veri + LLM servis katmanını** ve tüm sistemi saran **observability omurgasını** birlikte açıklar.

### 9.1 Katmanlı Swarm Bağımlılık ve Veri Akışı Haritası

Aşağıdaki şema, güncel çalışma zamanındaki ana bağımlılık yönünü ve katmanlar arası akışı özetler:

```
[ 1. Arayüz Katmanı (Frontend & Entry) ]
  ├── web_server.py (FastAPI, WebSocket) <---> web_ui_react/ (React SPA)
  ├── cli.py (Terminal)
  └── gui_launcher.py (Masaüstü başlatıcı)

                 | (istekler / oturum / ws akışı)
                 v

[ 2. Güvenlik ve Yönlendirme Katmanı (Middleware) ]
  ├── core/dlp.py (Hassas veri / PII maskeleme)
  ├── core/router.py (Maliyet / model yönlendirme)
  ├── core/hitl.py (Kritik eylemler için insan onayı)
  └── managers/security.py (Dosya / komut / erişim seviyesi kontrolleri)

                 | (onaylanmış görevler)
                 v

[ 3. Orkestrasyon Katmanı (Multi-Agent Swarm) ]
  ├── agent/swarm.py (SwarmOrchestrator)
  ├── agent/core/supervisor.py (Görev dağıtıcı / handoff kararları)
  ├── agent/registry.py + agent/core/registry.py (ajan kayıt defteri)
  ├── agent/core/contracts.py (delegasyon sözleşmeleri)
  ├── agent/core/event_stream.py (canlı event bus)
  ├── agent/roles/coder_agent.py (yazılım geliştirme)
  ├── agent/roles/researcher_agent.py (araştırma & RAG)
  ├── agent/roles/reviewer_agent.py (kod inceleme / QA)
  └── plugins/ (dinamik ajan pazaryeri / runtime eklentiler)

                 | (LLM, bellek ve veri ihtiyacı)
                 v

[ 4. Çekirdek AI ve Veri Servisleri ]
  ├── core/llm_client.py (Ollama, Gemini, Anthropic, OpenAI-uyumlu, LiteLLM gateway)
  ├── core/rag.py (pgvector, ChromaDB, BM25 hibrit arama)
  ├── core/memory.py + core/entity_memory.py (kalıcı oturum + persona belleği)
  ├── core/db.py (oturum, kullanıcı, kota, prompt, policy, audit)
  └── redis (semantic cache / rate-limit altyapısı)

                 | (araçlar ve dış dünya eylemleri)
                 v

[ 5. Dış Entegrasyonlar ve Tooling ]
  ├── managers/code_manager.py, managers/github_manager.py
  ├── managers/jira_manager.py, managers/slack_manager.py, managers/teams_manager.py
  ├── managers/web_search.py, managers/package_info.py, managers/todo_manager.py
  └── managers/system_health.py

======================================================================
[ Çapraz Kesen Katman: Gözlemlenebilirlik (Observability) ]
  * core/llm_metrics.py, core/agent_metrics.py, core/cache_metrics.py
  * OpenTelemetry span/metric export → Jaeger / OTLP / Prometheus / Grafana
  * web_server.py ve event stream üzerinden canlı durum + bütçe / metrik yüzeyleri
```

### 9.2 Olay Güdümlü Pub/Sub Omurgası (AgentEventBus)

- `agent/core/event_stream.py` içindeki `AgentEventBus`, `subscribe()/publish()/unsubscribe()` modeliyle process-içi pub/sub omurgası sağlar.
- `SupervisorAgent` çalışma adımlarında `events.publish(...)` çağrılarıyla ajan durumlarını event olarak üretir.
- `web_server.py` bu bus’a abone olup WebSocket kanalına canlı durum akışı taşır; böylece UI tarafı ajanları doğrudan çağırmadan gözlem yapar (loose coupling).

<a id="93-güvenlik-zinciri-codemanager--securitymanager-hard-coupling"></a>
### 9.3 Güvenlik Zinciri: CodeManager → SecurityManager (Hard Coupling)

- `managers/code_manager.py`, kurulumda zorunlu `SecurityManager` instance’ı alır (`CodeManager(security=...)`).
- Dosya okuma/yazma ve yürütme öncesi güvenlik kararları `SecurityManager` denetimlerinden geçirilir.
- Bu nedenle yöneticiler genel olarak modüler olsa da, **kod yürütme hattında güvenlik açısından bilinçli bir hard-coupling** vardır.

### 9.4 DB Merkezli Bellek ve Kimlik Hiyerarşisi

- `core/memory.py` içindeki `ConversationMemory`, kalıcılık için doğrudan `core/db.py::Database` katmanına bağlıdır.
- Web katmanı (`web_server.py`) token tabanlı kimlik doğrulama/oturum çözümlemesinde DB kayıtlarını kullanır.
- `agent/core/memory_hub.py` ise DB yerine kısa ömürlü role/global notlar tutan hafif bir orchestrasyon belleğidir; DB merkezli uzun ömürlü oturum belleğinin yerini almaz, onu tamamlar.

<a id="95-p2p-delegasyon-köprüsü-supervisor--contracts"></a>
### 9.5 P2P Delegasyon Köprüsü (Supervisor + Contracts)

- `agent/core/contracts.py` içinde `P2PMessage` ve `DelegationRequest`/`DelegationResult` sözleşmeleri, ajanlar arası nokta-atışı görev devri için veri modelini tanımlar; `protocol`, `meta.reason` ve `handoff_depth` alanları direct handoff zincirinin kurumsal izlenebilirliğini standardize eder.
- `agent/core/supervisor.py::_route_p2p(...)`, delegasyon isteklerini hedef ajanlara hop kontrollü (`max_hops`) biçimde taşır; sender/receiver/protocol bağlamını koruyarak fail-closed yönlendirme yapar.
- `agent/swarm.py::_direct_handoff(...)`, aynı P2P sözleşmesini supervisor dışındaki orchestrator yoluna da taşır; böylece coder/reviewer/researcher rolleri arasında doğrudan handoff mümkün hale gelir.
- Coder/Reviewer geri besleme döngüsü ve gerektiğinde araştırma/kod delegasyonu bu sözleşmeler üzerinden ilerleyerek QA odaklı P2P iş akışını kurar.

**Döngüsel bağımlılık:** Tespit edilmedi. `config.py` hâlâ bağımlılık ağacının kökü konumundadır.

**Ortak Kullanım Notu (Multi-Agent):** `Supervisor` ve rol ajanları; araç dispatch için `agent/tooling.py`, kalıcı konuşma verisi için `core/memory.py` + `core/db.py`, canlı durum akışı için `agent/core/event_stream.py`, maliyet/telemetri için `core/llm_metrics.py` katmanlarını birlikte kullanır.

---

## 10. Veri Akış Diyagramı

[⬆ İçindekilere Dön](#içindekiler)

### 10.1 Bir Chat Mesajının Ömrü (v4.x Katmanlı Akış)

```
[Kullanıcı]
    │ mesaj gönderir (React SPA / CLI / GUI)
    ▼
[web_server.py / CLI Entry]
    │ HTTP Bearer token / WS auth handshake
    ▼
[DLP Katmanı]
    │ hassas veri / PII maskeleme
    ▼
[Semantic Cache Kontrolü]
    │ Redis + cosine similarity
    ├─► HIT varsa → önbellekten erken yanıt (early exit)
    └─► MISS ise → orkestrasyon hattına devam
    ▼
[Supervisor / Swarm]
    │ intent analizi + alt görevlere bölme
    ├─► ResearcherAgent → RAG / web / entity memory bağlamı
    ├─► CoderAgent      → code_manager / github / tools
    ├─► ReviewerAgent   → QA / güvenlik / revizyon döngüsü
    └─► Plugin Agent    → marketplace üzerinden dinamik görevler
    ▼
[Router + LLM Client]
    │ maliyet/karmaşıklık yönlendirmesi + sağlayıcı seçimi
    ▼
[HITL / Action Gate]
    │ yüksek riskli işlem varsa onay bekle
    ▼
[Streaming + Persistence]
    ├─► AgentEventBus → WebSocket canlı durum akışı
    ├─► ConversationMemory / DB → oturum + mesaj kalıcılığı
    ├─► Metrics / OTel → latency, token, cost, span export
    └─► Nihai yanıt kullanıcıya döner
```

### 10.2 Bellek Yazma Yolu (Ortak Bellek Havuzu)

```
ConversationMemory.aadd(role, content)
    │
    ├─► _require_active_user()
    │      ├─► user_id var  → devam
    │      └─► yok          → MemoryAuthError (fail-closed)
    │
    ├─► active_session yoksa acreate_session("Yeni Sohbet")
    │
    ├─► in-memory turns güncelle (RLock korumalı)
    │
    └─► core/db.py.add_message(...)
           ├─► `sessions` tablosu (oturum meta)
           └─► `messages` tablosu (kalıcı konuşma)
                 (tenant izolasyonu: user_id zorunlu)
```

> Not: v3.0 mimarisinde bellek kalıcılığı JSON dosya yerine DB katmanına taşınmıştır.

### 10.3 RAG Belge Ekleme Yolu (Ortak Erişim)

```
docs_add / docs_add_file
    │
    ├─► güvenlik doğrulaması (path + erişim seviyesi)
    ├─► içerik normalize + chunking
    ├─► ChromaDB upsert (vektör katmanı)
    ├─► BM25/keyword indeks güncelleme
    │
    ├─► AgentEventBus.publish("RAG güncelleniyor...")
    │      └─► Web UI canlı durum akışı
    │
    └─► arama sırasında hibrit birleştirme
           ├─► vector sonuçları
           ├─► BM25 sonuçları
           └─► RRF ile final sıralama
```

> RAG yolu tüm uzman ajanlar tarafından ortak kullanılır; erişim kontrolü ve gözlemlenebilirlik katmanlarıyla birlikte çalışır.

### 10.4 Adım Adım Veri Yaşam Döngüsü (v4.x Kurumsal Akış)

1. **İstek Karşılama ve Güvenlik Filtresi (Auth + DLP):**
   - Kullanıcının React SPA, CLI veya GUI üzerinden gönderdiği mesaj sisteme ulaşır.
   - Web tarafında HTTP bearer token / WebSocket auth handshake uygulanır; içerik ardından `core/dlp.py` katmanından geçerek kredi kartı, TC kimlik, e-posta, telefon ve benzeri hassas veriler maskelenir.

2. **Anlamsal Önbellek (Semantic Cache) Kontrolü:**
   - Maskelenmiş sorgu Redis tabanlı semantic cache hattına girer.
   - Kosinüs benzerliği ile anlamca yakın bir kayıt bulunursa akış burada tamamlanır ve önbellekten yanıt dönülür; bulunamazsa maliyetli orkestrasyon/LLM yoluna geçilir.

3. **Swarm Supervisor ve Görev Bölüşümü:**
   - Gelen görev `agent/swarm.py` ve `agent/core/supervisor.py` tarafından analiz edilir.
   - İhtiyaca göre alt görevlere ayrılan iş; Coder, Researcher, Reviewer veya plugin ajanlarına paralel ya da pipeline modunda dağıtılır.

4. **RAG, Bellek ve Bağlam Zenginleştirme:**
   - Bilgi yoğun görevlerde Researcher hattı pgvector + ChromaDB + BM25 hibrit arama yapar; sonuçlar RRF ile birleştirilir.
   - `core/memory.py` oturum geçmişini, `core/entity_memory.py` ise kullanıcı/persona çıkarımlarını bağlama ekler; böylece ajanlar daha zengin context ile çalışır.

5. **Router ve LLM Üretim Katmanı:**
   - `core/router.py`, görev karmaşıklığı ve maliyet sinyaline göre uygun model/sağlayıcı yolunu seçer.
   - `core/llm_client.py`, Ollama/Gemini/Anthropic/OpenAI-uyumlu/LiteLLM gateway yollarından uygun olanına isteği iletir ve gerekirse structured output / retry / fallback mantığını uygular.

6. **HITL, Yayın ve Kalıcılık:**
   - Üretilen eylem planı sistem bütünlüğünü etkiliyorsa `core/hitl.py` devreye girer ve akış açık onay gelene kadar duraklar.
   - Onaylanan işlem veya standart yanıt; `AgentEventBus` üzerinden canlı durum olarak yayınlanır, `ConversationMemory` + `core/db.py` ile kalıcı yazılır ve WebSocket/HTTP akışıyla kullanıcıya döner.

> **Not:** Bu 6 adımın tamamı boyunca OpenTelemetry ve metrik toplayıcıları (`core/llm_metrics.py`, `core/agent_metrics.py`, `core/cache_metrics.py`) arka planda span, maliyet, gecikme ve cache davranışını Jaeger / OTLP / Prometheus yüzeylerine aktarır.

### 10.5 Proaktif Otonomi: Cron Wake + Webhook Tepki Döngüsü

```
[Zamanlayıcı / Dış Olay]
    │
    ├─► ENABLE_AUTONOMOUS_CRON=true
    │      └─► _autonomous_cron_loop periyodik uyanır
    │
    └─► /api/autonomy/webhook/{source}
           └─► CI/CD, log, alert veya harici sistem olayı gelir
                ▼
[Doğrulama + Güvenlik]
    │ webhook secret / allowlist / rate limit
    ▼
[Otonomi Girdi Normalizasyonu]
    │ olay türü, payload özeti, önem derecesi, tenant bağı çıkarılır
    ▼
[SidarAgent Wake-Up]
    │ sistem promptu + otonom görev şablonu ile yeni iş başlatılır
    ├─► CI log analizi
    ├─► hata kök neden araştırması
    ├─► reviewer/coder/researcher swarm delegasyonu
    └─► gerekirse browser / GitHub / RAG araçları çağrılır
    ▼
[HITL / Audit / Bildirim]
    │ yüksek riskli aksiyonlarda insan onayı beklenir
    ├─► audit trail + telemetry kaydı
    └─► PR taslağı, özet rapor veya iyileştirme önerisi üretilir
    ▼
[Kurumsal Tepki Çıkışı]
    ├─► kullanıcıya / dashboard'a bildirim
    ├─► issue / PR / yorum oluşturma
    └─► sonraki cron döngüsü için bağlamın belleğe yazılması
```

- **Cron tabanlı proaktif uyanma:** `ENABLE_AUTONOMOUS_CRON` açıkken sistem belirli aralıklarla kendi kendine uyanır, CI/CD kırıkları, log anomalileri veya bekleyen görev sinyallerini dış istem olmadan tarar.
- **Webhook tabanlı anlık tepki:** `/api/autonomy/webhook/{source}` rotası, dış kaynaklardan gelen olayları doğrulayıp otonom görev başlatma zarfına dönüştürür.
- **Swarm + güvenlik birleşimi:** Otonom başlatılan işlerde de aynı DLP, HITL, audit trail ve telemetry katmanları korunur; yani proaktiflik güvenlikten ödün vermez.
- **Kurumsal denetim izi:** Her kendi kendine uyanma döngüsü, kaynak olay, alınan karar ve üretilen çıktı bakımından izlenebilir olacak şekilde tasarlanmıştır.

---

## 11. Mevcut Sorunlar ve Teknik Borç

> **Güncel Durum (2026-03-19 — v5.0.0-alpha):** Kritik mimari, güvenlik ve coverage borçları kapalıdır. Bu bölüm artık aktif kusur listesinden ziyade, sürdürülen operasyonel izleme başlıklarını ve arşiv yönlendirmesini özetler.

### 11.1 Durum Özeti Paneli

| Gösterge | Durum |
|---|---|
| Aktif Kritik Bulgu | **0** |
| Aktif Sorun | **0 — açık ürün/bloklayıcı kusur yok** |
| Açık Teknik Borç | **0 — v5.0-alpha coverage borcu kapatıldı** |
| Denetim Durumu | **Production Ready (Alpha) / Zero Debt korunuyor** |
| Son Arşivleme Notu | **v4.3.0 ile tarihsel çözüm listeleri `docs/archive/` altına taşındı; v5.0-alpha coverage kapanışı CHANGELOG ve test dosyalarıyla teyit edildi** |

- **Stratejik özet:** Ana rapor aktif riskleri izlemek için kullanılır; kapanmış bulgular operasyonel hafıza olarak arşivde tutulur.
- **Versiyon durumu:** `v5.0.0-alpha` itibarıyla kritik güvenlik/mimari borç bulunmamaktadır; ses, browser ve launcher kapsamındaki coverage kapanışı repo içindeki test dosyalarıyla doğrulanmıştır.

### 11.2 Arşiv ve Yönlendirme

Geçmişte çözülen teknik borçlar ve denetim bulgularının detaylı listesi için `docs/archive/` dizinindeki belgelere bakınız:

- [`docs/archive/resolved_issues_v3.md`](docs/archive/resolved_issues_v3.md) — v3.0 serisindeki teknik borç, kalite ve hata kapanışları.
- [`docs/archive/audit_history.md`](docs/archive/audit_history.md) — v4.0 öncesi denetim geçmişi, kapanan kritik bulgular ve audit faz özetleri.
- [`CHANGELOG.md`](CHANGELOG.md) — yalnızca sürümler arası farklar, kısa düzeltme notları ve “Teknik Borç Kapanışı” özetleri.

> Yönlendirme ilkesi: Ana rapor “mevcut risk ve kurumsal durum”, arşiv belgeleri ise “geçmiş çözüm hafızası” için kullanılmalıdır.

### 11.3 v5.0 Faz-6 Coverage Kapanışı

- `core/voice.py`, `web_ui_react` duplex ses akışı, `managers/browser_manager.py`, `main.py`, `core/rag.py`, `agent/core/contracts.py`, `core/ci_remediation.py` ve event-driven federation/webhook zinciri için beklenen regresyon kapsamı `tests/test_voice_pipeline.py`, `tests/test_web_server_voice.py`, `tests/test_browser_manager.py`, `tests/test_main_launcher_improvements.py`, `tests/test_rag_graph.py`, `tests/test_contracts_federation.py`, `tests/test_ci_remediation.py` ve `tests/test_web_server_autonomy.py` ile repoda mevcuttur.
- Opsiyonel `pyttsx3` bağımlılığı, HITL onay akışları ve launcher alt süreç davranışı için mocking/fake adapter stratejileri test dosyalarında uygulanmış durumdadır; bu başlık artık aktif borç değil, sürdürülen regresyon korumasıdır.

### 11.4 Operasyonel İzleme Başlıkları

Aktif yazılım kusuru bulunmamakla birlikte aşağıdaki başlıklar operasyonel olarak düzenli izlenmelidir:

- **LLM kota ve hız limitleri:** Paralel multi-agent çağrıları dış sağlayıcı RPM/TPM sınırlarını etkileyebilir.
- **Gateway / dış ağ erişimi:** LiteLLM gateway veya sağlayıcı erişim sorunları toplam yanıt süresini uzatabilir.
- **Yerel model donanım sınırları:** Ollama, embedding ve vision akışlarında CPU/GPU/VRAM kapasitesi throughput'u belirler.
- **Vektör veri katmanı ölçeği:** pgvector/ChromaDB indeks davranışı tenant ve belge hacmi arttıkça izlenmelidir.
- **Redis bağımlılıkları:** Semantic cache ve event-stream yüzeyleri Redis kesintilerinde fail-safe çalışsa da gecikme profili değişebilir.

### 11.5 Gelecek İyileştirmeler (Continuous Improvement)

Aktif teknik borç yalnızca v5.0-alpha test kapsamı başlığında toplanmıştır; bunun dışındaki iyileştirme alanları kapasite ve görünürlük eksenindedir:

- **Gelişmiş telemetri görselleştirmesi:** Ajanlar arası delegasyon sürelerinin Grafana panellerinde daha ayrıntılı kırılımlarla izlenmesi.
- **Kurumsal kapasite planlama notları:** pgvector indeks stratejileri, Redis kapasitesi ve uzun dönem maliyet trendlerinin düzenli arşivlenmesi.
- **Arşiv hijyeni:** Yeni kapanan bulguların ana rapora yığılmadan doğrudan `docs/archive/` altında versiyonlu biçimde tutulması.



## 12. `.env` Tam Değişken Referansı (v5.0.0-alpha Kurumsal Sürüm)

[⬆ İçindekilere Dön](#içindekiler)

Sistemin davranışını kontrol eden çevre değişkenleri artık birkaç API anahtarından ibaret değildir; çalışma zamanı yapılandırması `config.py` tarafından merkezi olarak okunur ve güvenlik, gözlemlenebilirlik, semantic cache, çoklu ajan orkestrasyonu ve entegrasyon katmanları mantıksal modüller halinde yönetilir.

> **Önemli doğruluk notu:** Güncel kod tabanında `DEBUG` yerine `DEBUG_MODE`, `ENABLE_TELEMETRY` yerine `ENABLE_TRACING`, `OTEL_EXPORTER_OTLP_ENDPOINT` yerine `OTEL_EXPORTER_ENDPOINT`, `LITELLM_BASE_URL` yerine `LITELLM_GATEWAY_URL`, `OLLAMA_BASE_URL` yerine `OLLAMA_URL` kullanılmaktadır. Ayrıca ayrı bir `DEFAULT_TENANT_ID` değişkeni yoktur; tenant varsayılanı auth/DB katmanında çalışma zamanında `default` olarak uygulanır. Bunun yanında bazı ileri seviye anahtarlar (`DATABASE_URL`, `DB_SCHEMA_VERSION_TABLE`, `DOCKER_MEM_LIMIT`, `DOCKER_MICROVM_MODE`) `config.py` tarafından desteklenir ancak mevcut `.env.example` şablonunda ön tanımlı satır olarak henüz yer almaz.

### 12.1 Temel Sistem Ayarları (Core Runtime)

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `SIDAR_ENV` | `development` (`.env.example`) / `""` (`config.py` fallback) | Ortam profili seçimi; varsa `.env.<profil>` dosyasını temel `.env` üzerine yükler |
| `DEBUG_MODE` | `false` | Ayrıntılı debug davranışlarını ve yapılandırma özetini açar |
| `LOG_LEVEL` | `INFO` | Uygulama geneli log seviyesi (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `RESPONSE_LANGUAGE` | `tr` | Nihai yanıt dili |
| `REVIEWER_TEST_COMMAND` | `python -m pytest` | ReviewerAgent doğrulama safhasında koşturulan test komutu |
| `AI_PROVIDER` | `ollama` | Birincil LLM sağlayıcı seçimi: `ollama`, `gemini`, `openai`, `anthropic`, `litellm` |

### 12.2 Yapay Zeka Sağlayıcıları ve Gateway

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_TIMEOUT` | `""` / `gpt-4o-mini` / `60` | OpenAI sağlayıcısı için kimlik bilgisi, model ve timeout |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `ANTHROPIC_TIMEOUT` | `""` / `claude-3-5-sonnet-latest` / `60` | Anthropic/Claude sağlayıcısı için ayarlar |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | `""` / `gemini-2.5-flash` | Google Gemini sağlayıcı ayarları |
| `OLLAMA_URL` / `OLLAMA_TIMEOUT` | `http://localhost:11434/api` / `30` | Yerel Ollama API adresi ve timeout |
| `CODING_MODEL` / `TEXT_MODEL` | `qwen2.5-coder:7b` / `gemma2:9b` | Yerel görevlerde kullanılan varsayılan kod ve metin modeli |
| `LITELLM_GATEWAY_URL` / `LITELLM_API_KEY` | `http://localhost:4000` / `""` | LiteLLM/OpenRouter benzeri merkezi gateway erişimi |
| `LITELLM_MODEL` / `LITELLM_FALLBACK_MODELS` / `LITELLM_TIMEOUT` | `gpt-4o-mini` / `gpt-4o-mini,claude-3-haiku-20240307` / `60` | Gateway üzerinden kullanılacak birincil model, fallback listesi ve timeout |
| `LLM_MAX_RETRIES` / `LLM_RETRY_BASE_DELAY` / `LLM_RETRY_MAX_DELAY` | `2` / `0.4` / `4.0` | Sağlayıcı çağrılarında retry/backoff politikası |

### 12.3 Veritabanı, RAG ve Vektör Bellek

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/sidar.db` | Kalıcı bellek, kullanıcı, tenant-policy, audit ve pgvector için ana DB bağlantısı |
| `DB_POOL_SIZE` / `DB_SCHEMA_VERSION_TABLE` / `DB_SCHEMA_TARGET_VERSION` | `5` / `schema_versions` / `1` | Bağlantı havuzu ve şema sürümleme ayarları |
| `RAG_DIR` | `data/rag` | Yerel belge deposu dizini; Chroma tabanlı kurulumlarda veri kökü olarak kullanılır |
| `RAG_TOP_K` / `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` / `RAG_FILE_THRESHOLD` | `3` / `1000` / `200` / `20000` | Hibrit arama ve chunking ayarları |
| `RAG_VECTOR_BACKEND` | `chroma` | Vektör arka ucu: `chroma` veya `pgvector` |
| `PGVECTOR_TABLE` / `PGVECTOR_EMBEDDING_DIM` / `PGVECTOR_EMBEDDING_MODEL` | `rag_embeddings` / `384` / `all-MiniLM-L6-v2` | PostgreSQL/pgvector tarafında embedding tablo ve model ayarları |
| `MEMORY_ENCRYPTION_KEY` | `""` | Bellek kayıtlarını Fernet ile şifrelemek için opsiyonel anahtar |

> **RAG notu:** Güncel yapılandırmada ayrı bir `CHROMADB_PATH` değişkeni yoktur; Chroma tarafı `RAG_DIR` ve belge deposu düzeni üzerinden yönetilir. `DATABASE_URL` ve şema versiyon anahtarları çalışma zamanı ile `.env.example` şablonunda senkronize tutulur.

### 12.4 Anlamsal Önbellek, Redis ve Event Bus

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ENABLE_SEMANTIC_CACHE` | `false` | Redis tabanlı semantic cache'i aktif eder |
| `SEMANTIC_CACHE_THRESHOLD` | `0.95` | Cache HIT kabulü için kosinüs benzerlik eşiği |
| `SEMANTIC_CACHE_TTL` / `SEMANTIC_CACHE_MAX_ITEMS` | `3600` / `500` | Cache ömrü ve LRU kapasitesi |
| `REDIS_URL` | `.env.example`: `redis://redis:6379/0`, `config.py` fallback: `redis://localhost:6379/0` | Semantic cache, rate limiting ve event-stream katmanının Redis bağlantısı |
| `SIDAR_EVENT_BUS_CHANNEL` / `SIDAR_EVENT_BUS_GROUP` | `sidar:agent_events` / `sidar:agent_events:cg` | Swarm/event bus için Redis Streams kanal ve consumer group adları |
| `RATE_LIMIT_WINDOW` / `RATE_LIMIT_CHAT` / `RATE_LIMIT_MUTATIONS` / `RATE_LIMIT_GET_IO` | `60` / `20` / `60` / `30` | API rate-limiting penceresi ve endpoint bazlı limitler |
| `TRUSTED_PROXIES` | `""` | Güvenilir ters proxy IP listesi; boşsa proxy başlıkları güvenilmez sayılır |
| `MAX_RAG_UPLOAD_BYTES` | `52428800` | RAG dosya yükleme üst limiti (50 MB) |

### 12.5 Güvenlik, Kimlik Doğrulama, Tenant, DLP ve HITL

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ACCESS_LEVEL` | `.env.example`: `sandbox`, `config.py` fallback: `full` | Araç/yürütme erişim seviyesi: `restricted`, `sandbox`, `full` |
| `API_KEY` | `""` | Web/API için opsiyonel ek anahtar tabanlı koruma |
| `JWT_SECRET_KEY` / `JWT_ALGORITHM` / `JWT_TTL_DAYS` | `""` / `HS256` / `7` | SPA/API oturumları için JWT imzalama ve yaşam süresi ayarları |
| `DLP_ENABLED` / `DLP_LOG_DETECTIONS` | `true` / `false` | PII/hassas veri maskeleme ve maskeleme loglama davranışı |
| `HITL_ENABLED` / `HITL_TIMEOUT_SECONDS` | `false` / `120` | Yıkıcı işlemler öncesi human-in-the-loop onay kapısı ve bekleme süresi |
| `METRICS_TOKEN` | `""` | `/metrics`, `/metrics/llm`, `/api/budget` gibi operasyonel endpoint'ler için statik bearer token |

> **Tenant notu:** Çoklu kiracı desteği runtime ve DB katmanında `tenant_id` alanı ile uygulanır; ancak yapılandırmada ayrı bir `DEFAULT_TENANT_ID` env değişkeni bulunmaz. Varsayılan tenant değeri auth ve veritabanı akışında `default` olarak üretilir.

### 12.6 Gözlemlenebilirlik (Observability & OTel)

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ENABLE_TRACING` | `false` | OpenTelemetry tracing'i açar/kapatır |
| `OTEL_EXPORTER_ENDPOINT` | `.env.example`: `http://localhost:4317`, `config.py` fallback: `http://jaeger:4317` | OTLP exporter/collector/Jaeger adresi |
| `OTEL_SERVICE_NAME` | `sidar` | Telemetri panellerinde servisin görünen adı |
| `OTEL_INSTRUMENT_FASTAPI` / `OTEL_INSTRUMENT_HTTPX` | `true` / `true` | FastAPI ve HTTPX otomatik enstrümantasyon anahtarları |
| `GRAFANA_URL` | `http://localhost:3000` | Web admin panelindeki Grafana bağlantı hedefi |

### 12.7 Dış Entegrasyonlar, Managers ve Plugin Yüzeyleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `GITHUB_TOKEN` / `GITHUB_REPO` / `GITHUB_WEBHOOK_SECRET` | `""` / `""` / `""` | GitHub repo erişimi, varsayılan repo ve webhook doğrulama ayarları |
| `SLACK_TOKEN` / `SLACK_WEBHOOK_URL` / `SLACK_DEFAULT_CHANNEL` | `""` / `""` / `""` | Slack API veya webhook tabanlı bildirim ayarları |
| `JIRA_URL` / `JIRA_TOKEN` / `JIRA_EMAIL` / `JIRA_DEFAULT_PROJECT` | `""` / `""` / `""` / `""` | Jira entegrasyonu ve varsayılan proje bilgileri |
| `TEAMS_WEBHOOK_URL` | `""` | Microsoft Teams webhook bildirimi |
| `SEARCH_ENGINE` / `TAVILY_API_KEY` / `GOOGLE_SEARCH_API_KEY` / `GOOGLE_SEARCH_CX` | `auto` / `""` / `""` / `""` | Web arama sağlayıcı seçimi ve harici arama API ayarları |
| `WEB_SEARCH_MAX_RESULTS` / `WEB_FETCH_TIMEOUT` / `WEB_FETCH_MAX_CHARS` / `WEB_SCRAPE_MAX_CHARS` | `5` / `15` / `12000` / `12000` | Web içerik toplama ve scrape sınırları |
| `PACKAGE_INFO_TIMEOUT` / `PACKAGE_INFO_CACHE_TTL` | `12` / `1800` | Paket metadata sorguları için timeout ve cache süresi |

### 12.8 Donanım, Yerel Çalışma, Sandbox ve Gelişmiş Yetenekler

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `USE_GPU` / `GPU_DEVICE` / `MULTI_GPU` | `false` (`.env.example`) / `0` / `false` | GPU kullanımı, cihaz seçimi ve çoklu GPU modu |
| `GPU_MEMORY_FRACTION` / `LLM_GPU_MEMORY_FRACTION` / `RAG_GPU_MEMORY_FRACTION` | `0.8` / `0.8` / `0.3` | Yerel LLM ve RAG için VRAM bütçe ayarları |
| `GPU_MIXED_PRECISION` | `false` | FP16/mixed precision ile VRAM optimizasyonu |
| `DOCKER_PYTHON_IMAGE` / `DOCKER_EXEC_TIMEOUT` / `DOCKER_REQUIRED` | `python:3.11-alpine` / `10` / `false` | Kod çalıştırma sandbox'ının temel Docker davranışı |
| `DOCKER_RUNTIME` / `DOCKER_ALLOWED_RUNTIMES` / `DOCKER_MICROVM_MODE` | `""` / `,runc,runsc,kata-runtime` / `off` | Zero-trust sandbox runtime ve mikro-VM hazırlık seçenekleri |
| `DOCKER_MEM_LIMIT` / `DOCKER_NETWORK_DISABLED` / `DOCKER_NANO_CPUS` | `256m` / `true` / `1000000000` | Sandbox konteyner kaynak kısıtları |
| `SANDBOX_MEMORY` / `SANDBOX_CPUS` / `SANDBOX_NETWORK` / `SANDBOX_PIDS_LIMIT` / `SANDBOX_TIMEOUT` | `256m` / `0.5` / `none` / `64` / `10` | `config.py::SANDBOX_LIMITS` sözlüğüne beslenen detaylı çalışma kotaları |
| `WEB_HOST` / `WEB_PORT` / `WEB_GPU_PORT` | `0.0.0.0` / `7860` / `7861` | Web sunucusunun bind adresi ve portları |
| `HF_TOKEN` / `HF_HUB_OFFLINE` | `""` / `0/false` | HuggingFace model erişimi ve offline cache davranışı |
| `JUDGE_ENABLED` / `JUDGE_MODEL` / `JUDGE_PROVIDER` / `JUDGE_SAMPLE_RATE` | `false` / `""` / `ollama` / `0.2` | LLM-as-a-Judge kalite değerlendirme hattı |
| `ENABLE_COST_ROUTING` ve `COST_ROUTING_*` | `false` / eşik ve model varsayılanları | Basit/karmaşık sorgular için maliyet odaklı model yönlendirmesi |
| `ENABLE_ENTITY_MEMORY` / `ENTITY_MEMORY_TTL_DAYS` / `ENTITY_MEMORY_MAX_PER_USER` | `true` / `90` / `100` | Entity/persona memory kalıcılığı |
| `ENABLE_ACTIVE_LEARNING`, `AL_MIN_RATING_FOR_TRAIN`, `ENABLE_LORA_TRAINING`, `LORA_*` | çeşitli | Geri bildirim toplama ve LoRA/QLoRA fine-tuning hazırlıkları |
| `ENABLE_CONTINUOUS_LEARNING` | `false` | Judge/feedback sinyallerinden sürekli öğrenme (continuous learning) bundle'ı üretilmesini aktifleştirir. (v6.0 hazırlığı) |
| `CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES` | `20` | Sürekli öğrenme için gereken minimum SFT (Supervised Fine-Tuning) örnek sayısı. |
| `CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES` | `10` | RLHF/DPO için gereken minimum tercih (preference) örnek sayısı. |
| `CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS` | `5000` | İşlenmeyi bekleyen maksimum sinyal kapasitesi. |
| `CONTINUOUS_LEARNING_COOLDOWN_SECONDS` | `3600` | İki ardışık sürekli öğrenme döngüsü arasındaki bekleme süresi (saniye). |
| `CONTINUOUS_LEARNING_OUTPUT_DIR` | `data/continuous_learning` | Sürekli öğrenme veri setlerinin dışa aktarılacağı dizin. |
| `CONTINUOUS_LEARNING_SFT_FORMAT` | `alpaca` | Supervised Fine-Tuning formatı (örn. alpaca, sharegpt). |
| `ENABLE_VISION` / `VISION_MAX_IMAGE_BYTES` | `true` / `10485760` | Çok modlu görsel girdi yetenekleri |
| `ENABLE_MULTIMODAL` / `MULTIMODAL_MAX_FILE_BYTES` / `VOICE_STT_PROVIDER` / `WHISPER_MODEL` / `VOICE_WS_MAX_BYTES` | `true` / `52428800` / `whisper` / `base` / `10485760` | Medya ingestion, ses işleme ve `/ws/voice` limiti |
| `VOICE_TTS_PROVIDER` / `VOICE_TTS_VOICE` / `VOICE_TTS_SEGMENT_CHARS` / `VOICE_TTS_BUFFER_CHARS` | `auto` / `""` / `48` / `96` | Duplex TTS sağlayıcısı, ses seçimi, segment boyu ve düşük gecikmeli buffer limiti |
| `VOICE_VAD_ENABLED` / `VOICE_VAD_MIN_SPEECH_BYTES` / `VOICE_DUPLEX_ENABLED` / `VOICE_VAD_INTERRUPT_MIN_BYTES` | `true` / `1024` / `true` / `384` | VAD tabanlı speech algılama, duplex akış ve barge-in interrupt eşikleri |
| `BROWSER_PROVIDER` / `BROWSER_HEADLESS` / `BROWSER_TIMEOUT_MS` / `BROWSER_ALLOWED_DOMAINS` | `auto` / `true` / `15000` / `[]` | Browser automation sağlayıcısı, görünüm modu, timeout ve domain allowlist |
| `ENABLE_LSP` / `LSP_TIMEOUT_SECONDS` / `LSP_MAX_REFERENCES` / `PYTHON_LSP_SERVER` / `TYPESCRIPT_LSP_SERVER` | `true` / `15` / `200` / `pyright-langserver` / `typescript-language-server` | LSP tabanlı anlamsal analiz/refactor ayarları |
| `ENABLE_AUTONOMOUS_CRON` / `AUTONOMOUS_CRON_INTERVAL_SECONDS` / `AUTONOMOUS_CRON_PROMPT` | `false` / `900` / varsayılan otonom prompt | Proaktif cron tetikleyicisinin açılması, periyodu ve sistem promptu |
| `ENABLE_NIGHTLY_MEMORY_PRUNING` / `NIGHTLY_MEMORY_INTERVAL_SECONDS` / `NIGHTLY_MEMORY_IDLE_SECONDS` / `NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS` / `NIGHTLY_MEMORY_SESSION_MIN_MESSAGES` / `NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS` | `false` / `86400` / `1800` / `2` / `12` / `2` | Idle-gece döngüsü ile konuşma özetleme, RAG pruning ve hafıza konsolidasyonu ayarları |
| `ENABLE_EVENT_WEBHOOKS` / `AUTONOMY_WEBHOOK_SECRET` / `ENABLE_SWARM_FEDERATION` / `SWARM_FEDERATION_SHARED_SECRET` | `true` / `""` / `true` / `""` | Otonom webhook ve dış swarm federation güvenlik ayarları |
| `ENABLE_GRAPH_RAG` / `GRAPH_RAG_MAX_FILES` | `true` / `5000` | GraphRAG indeksleme aktivasyonu ve tarama üst sınırı |

### 12.9 Docker Compose Override Değişkenleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `SIDAR_CPU_LIMIT` | `2.0` | `sidar-ai` servisi için CPU limiti (`docker-compose.yml`) |
| `SIDAR_MEM_LIMIT` | `4g` | `sidar-ai` servisi için bellek limiti |
| `SIDAR_GPU_CPU_LIMIT` | `4.0` | `sidar-gpu` servisi için CPU limiti |
| `SIDAR_GPU_MEM_LIMIT` | `8g` | `sidar-gpu` servisi için bellek limiti |
| `SIDAR_WEB_CPU_LIMIT` | `2.0` | `sidar-web` servisi için CPU limiti |
| `SIDAR_WEB_MEM_LIMIT` | `4g` | `sidar-web` servisi için bellek limiti |
| `SIDAR_WEB_GPU_CPU_LIMIT` | `4.0` | `sidar-web-gpu` servisi için CPU limiti |
| `SIDAR_WEB_GPU_MEM_LIMIT` | `8g` | `sidar-web-gpu` servisi için bellek limiti |
| `HOST_GATEWAY` | `host-gateway` | Konteynerden host Ollama erişimi için `extra_hosts` gateway değeri |
| `WEB_PORT` / `WEB_GPU_PORT` | `7860` / `7861` | Compose port publish değerleri |
| `NVIDIA_VISIBLE_DEVICES` | `all` | GPU konteynerlerinde görünür cihaz seçimi |
| `NVIDIA_DRIVER_CAPABILITIES` | `compute,utility` | NVIDIA sürücü yetenek seti |

> **Not:** Bu değişkenler uygulama `Config` sınıfından çok, doğrudan container orkestrasyon katmanında (Compose) etkilidir.

---

<a id="13-v4x-kurumsal-enterprise-ve-swarm-mimarisi-evrimi-tamamlandı"></a>
## 13. v4.x Kurumsal (Enterprise) ve Swarm Mimarisi Evrimi (Tamamlandı)

[⬆ İçindekilere Dön](#içindekiler)

Bu proje, v4.x serisi ile birlikte “kişisel asistan” ölçeğinden çıkarak **kurumsal otonom operasyon merkezi** niteliğine ulaşmıştır. `CHANGELOG.md` içindeki `4.0.0`, `v4.2.0`, `v4.2.1` ve `4.3.0` kilometre taşları; güncel kod tabanında aynı omurga üzerinde birleşen dört ana dönüşümü doğrular: **kurumsal veri düzlemi**, **çoklu-ajan swarm orkestrasyonu**, **dağıtık gözlemlenebilirlik** ve **modern React SPA yönetim yüzeyi**.

> **Kısa özet:** v4.0 ile güvenlik/veri temeli kuruldu; v4.2 ile Supervisor destekli Swarm, plugin marketplace ve OTel izlenebilirliği operasyonel hale geldi; v4.3.0 ile React SPA, sürüm/dokümantasyon senkronizasyonu ve sıfır borç kalitesini koruyan CI politikaları aynı baseline üzerinde birleştirildi.

### 13.1 v4.0 – v4.1: Güvenlik ve Kurumsal Veri Katmanı

Bu bant, sistemin tek kullanıcı/tek ajan yardımcı uygulama sınırlarını aşarak çok kiracılı, denetlenebilir ve veri yönetişimi güçlü bir platforma dönüşmesini temsil eder:

- **Çok kiracılı veri izolasyonu ve RBAC:** `tenant_id` tabanlı kullanıcı/politika yapısı, `access_policy_middleware` üzerinden enforcement ve `audit_logs` tablosu ile kurumsal erişim izi tamamlandı. Böylece yetki kararı yalnızca uygulanmıyor, aynı zamanda denetlenebilir biçimde kaydediliyor.
- **Kurumsal veri düzlemi:** SQLite fallback korunurken PostgreSQL + `pgvector` + Chroma hibrit modeli ve migration zinciri v4 omurgasına taşındı; RAG artık kurumsal veri erişim katmanı olarak konumlandı.
- **Semantic cache ile maliyet/latency optimizasyonu:** Redis tabanlı `_SemanticCacheManager` tekrar eden semantik sorguları önbellekten cevaplayarak LLM maliyetini ve gecikmesini düşüren ilk kurumsal performans katmanını sağladı.
- **DLP ve HITL güvenlik duvarları:** `core/dlp.py` prompt seviyesinde PII maskelemesini, `core/hitl.py` ise yıkıcı işlemler öncesi insan onayını devreye alarak sistemin otonomisini güvenlik kontrol noktalarıyla dengeledi.

### 13.2 v4.2: Zeki Sürü (Swarm) Orkestrasyonu ve Gözlemlenebilirlik

Bu bantta proje, tekli ajan akışından kurumsal **Supervisor + Swarm** mimarisine evrilmiştir:

- **Supervisor destekli çoklu-ajan yürütme:** `agent/swarm.py`, `agent/core/supervisor.py` ve uzman roller (Coder, Researcher, Reviewer) ile görevler alt uzmanlıklara bölünüp paralel/pipeline olarak yürütülebilir hale geldi.
- **Dinamik AgentRegistry ve plugin marketplace:** Runtime kayıt mekanizması, `/api/agents/register*` uç noktaları ve plugin agent akışı ile sistem artık yeni uzmanlıkları çalışma anında genişletebilen bir platform davranışı gösterir.
- **Direct P2P handoff ve event bus:** `p2p.v1` delegasyon sözleşmesi, Redis Streams tabanlı event bus ve audit doğrulamaları sayesinde ajanlar arası el değiştirme, replay/ack ve orchestration görünürlüğü kurumsal standarda taşındı.
- **OTel / Jaeger / Prometheus-Grafana telemetri yığını:** OpenTelemetry span enstrümantasyonu, Jaeger/OTel Collector Helm şablonları ve Prometheus/Grafana yüzeyleri ile swarm görevleri, LLM çağrıları ve RAG akışları waterfall mantığında izlenebilir hale geldi.

### 13.3 v4.3: Arayüz Modernizasyonu, Sürüm Senkronizasyonu ve Sıfır Borç Disiplini

Bu bant, v4 mimarisinin yalnızca backend kabiliyeti olarak kalmayıp ürün seviyesinde operasyonel bir yüz kazanmasını temsil eder:

- **Modern React SPA geçişi:** `web_ui_react/` artık standart kullanıcı deneyimidir; `web_server.py` derlenmiş React dağıtımını önceliklendirir, yönetim panelleri (Prompt Admin, Agent Manager, Swarm Flow, tenant ekranları) aynı SPA kabuğunda birleşir.
- **Dokümantasyon/sürüm tekilleştirmesi:** `CHANGELOG.md`, `README.md`, `config.py`, teknik referanslar ve proje raporu `v4.3.0` çizgisine hizalanarak operasyonda tek bir sürüm gerçeği oluşturuldu.
- **CI/CD ile korunan sıfır borç disiplini:** Kapsama hard gate'i `%100` olarak kodlanmıştır; test, audit ve metrik betikleri artık takip dışı dosyaları saymadan gerçek repo ölçümleri üzerinden kalite kapısı üretir.
- **Kurumsal kapanış yorumu:** Bu aşamada React SPA, swarm, semantic cache, OTel, tenant RBAC/audit, DLP/HITL ve kurumsal deployment yüzeyleri aynı sistem üzerinde bir araya gelmiş; v4.x serisi “özellik ekleme” aşamasını tamamlayıp **operasyonel enterprise platform** seviyesine ulaşmıştır.

### 13.4 v4.x Tamamlanan Evrim Özeti

| Sürüm Bandı | Tamamlanan Dönüşüm | Kurumsal Sonuç |
|---|---|---|
| **v4.0 – v4.1** | Multi-tenant RBAC, audit trail, pgvector/Redis veri düzlemi, DLP + HITL | Güvenli, denetlenebilir ve kurumsal veri yönetişimine uygun çekirdek |
| **v4.2** | Supervisor/Swarm, AgentRegistry marketplace, direct P2P handoff, OTel/Jaeger/Prometheus-Grafana | Paralel uzman ajan yürütmesi ve uçtan uca gözlemlenebilirlik |
| **v4.3** | React SPA, sürüm/dokümantasyon senkronizasyonu, agresif CI kalite kapıları | Ürünleşmiş yönetim deneyimi ve sürdürülebilir sıfır borç operasyonu |

> **Son değerlendirme:** v4.x serisinin sonunda Sidar; sadece komut yanıtlayan bir asistan değil, tenant izoleli veri düzlemi, swarm orkestrasyonu, güvenlik kontrol kapıları, OTel tabanlı izlenebilirlik ve modern web yönetimi olan bir **kurumsal otonom platform** hâline gelmiştir.

---

## 14. Gelecek Vizyonu ve Geliştirme Yol Haritası (Faz 6 / v5.x)

[⬆ İçindekilere Dön](#içindekiler)

Projenin temel kurumsal altyapısı, swarm mimarisi, güvenlik kontrol noktaları ve arayüz modernizasyonu v4.x serisi ile tamamlanmıştır. Bu nedenle gelecek sürümlerin odağı artık “eksik temel özellikleri tamamlama” değil; **ileri Ar-Ge, dağıtık ölçeklenme ve otonomi derinleştirmesi** olacaktır.

> **Yön belirleyici ilke:** v5.x serisi, mevcut enterprise omurgayı koruyarak Sidar'ı daha güçlü akıl yürütme, dağıtık çalışma, sürekli öğrenme, kurumsal takım işbirliği ve gerçek zamanlı çoklu modalite eksenlerinde ileri taşıyan Faz 6 yol haritasıdır.

### 14.1 GraphRAG ve Bilgi Grafikleri (Knowledge Graphs)

- Mevcut `pgvector` + BM25 + keyword hibrit aramasına, varlıklar ve ilişkiler arasındaki bağlantıları modelleyen **graph tabanlı bellek katmanı** eklenecektir.
- Bu katman; entity memory, prompt registry ve RAG akışlarını yalnızca benzerlik aramasıyla değil, **ilişki/topoloji tabanlı çıkarım** ile zenginleştirecektir.
- Orta vadede `pgvector` retrieval yüzeyi, varlık/ilişki çıkarımı yapan bir Knowledge Graph katmanı ile birlikte çalışacak şekilde genişletilecek; böylece çok adımlı ve kompleks problemlerde yalnızca benzer belgeleri değil, düğümler arası bağımlılık zincirlerini de çözümleme akışına taşıyabilecektir.
- Olası teknoloji yönü; Neo4j benzeri bir grafik veri katmanı veya PostgreSQL üzerinde graph-benzeri ilişki indeksleriyle hibrit yaklaşım kurulmasıdır.
- Beklenen kazanım: çok adımlı reasoning, kurumsal bilgi keşfi ve belge/kişi/sistem bağıntılarının daha doğru modellenmesi.

### 14.2 Dağıtık Sürü Orkestrasyonu (Distributed Swarm via Message Brokers)

- Bugünkü Supervisor + Swarm akışı tek bir Python runtime içinde güçlü biçimde çalışsa da, Faz 6 hedefi ajanların bağımsız worker servislerine ayrılmasıdır.
- Hazırlık fazında ajan çalışma modeli tek süreç içi Python yürütümünden uzaklaştırılarak Kubernetes pod seviyesinde izole edilen servis sınırlarına ayrılacak; uzman roller RabbitMQ, Kafka veya benzeri broker'lar üzerinden görev/payload alışverişi yapan dağıtık bir swarm topolojisine evrilecektir.
- Bu dönüşüm; görevlerin kuyruklanması, yatay ölçekleme, izolasyon, yeniden deneme politikaları ve tenancy sınırlarının pod seviyesinde sertleştirilmesini sağlayacaktır.
- Beklenen kazanım: daha büyük swarm'ların Kubernetes üzerinde bölgesel ve tenant bazlı ölçeklenebilmesi.

### 14.3 Sürekli Öğrenme ve RLHF/DPO Boru Hattı

- `core/judge.py`, aktif öğrenme ve kullanıcı geri bildirimi modüllerinin ürettiği kalite sinyalleri, düzenli model iyileştirme döngülerine bağlanacaktır.
- Hedef; yerel modeller için LoRA/QLoRA altyapısını yalnızca manuel fine-tuning aracı olmaktan çıkarıp **sürekli öğrenen RLHF/DPO pipeline**'ının parçası hâline getirmektir.
- Reviewer, HITL ve judge sinyalleri birlikte değerlendirilerek hangi örneklerin eğitim veri setine alınacağı otomatikleştirilecektir.
- Beklenen kazanım: zaman içinde kurumsal stile uyum sağlayan, daha isabetli ve daha düşük maliyetli yerel model davranışı.

### 14.4 Gerçek Zamanlı Çoklu Modalite (Realtime WebRTC)

- Bugünkü `core/vision.py` yetenekleri görsel tabanlı üretimi desteklemektedir; Faz 6 hedefi bunun **gerçek zamanlı ses + video + ekran akışı** katmanına genişletilmesidir.
- WebRTC tabanlı çift yönlü iletişim ile ajanların yalnızca metin ve yüklenmiş dosyalarla değil, canlı konuşma ve canlı görüntü üzerinden de etkileşime girmesi amaçlanmaktadır.
- Bu genişleme, React SPA tarafında streaming UI, düşük gecikmeli medya taşıma ve olay bazlı swarm kararlarının eşzamanlı görselleştirilmesini gerektirecektir.
- Beklenen kazanım: Sidar'ın chat tabanlı bir asistandan, gerçek zamanlı çok modlu bir AI co-worker/ağ operatörü deneyimine dönüşmesi.

### 14.5 Faz 6 Yol Haritası Özeti

| Faz 6 Alanı | Teknik Yön | Hedef Çıktı |
|---|---|---|
| **GraphRAG** | Knowledge graph + entity relation memory | Çok adımlı reasoning ve kurumsal bilgi keşfi |
| **Distributed Swarm** | Broker tabanlı mikroservis ajanlar | Yatay ölçeklenen, pod-seviyesinde izole swarm |
| **Continuous Learning** | Judge + feedback + LoRA/QLoRA + RLHF/DPO | Sürekli iyileşen yerel model kalitesi |
| **Realtime Multimodality** | WebRTC + vision + streaming SPA | Ses/video destekli gerçek zamanlı ajan etkileşimi |

### 14.6 Faz E: Otonom İş Ekosistemi

- **Coverage Agent:** `agent/roles/coverage_agent.py` ile coverage raporlarından eksik satırları okuyup `pytest` koşturan, bulgu analizi yapan, test adayı üreten ve çıktıları `coverage_tasks` / `coverage_findings` yüzeyine yazan otonom QA swarm birimi sisteme eklendi; `tests/test_missing_edge_case_coverage_final.py` ile doğrulanan `%100` baseline bu ajanın çalışma standardı olarak kullanılmaktadır.
- **Poyraz:** `agent/roles/poyraz_agent.py` ile SİDAR'ın pazarlama ve operasyon kolu aktif hale geldi; sosyal medya yönetimi, web sitesi/landing page taslakları, kampanya içerikleri, WhatsApp iletişimi ve tenant-aware operasyon checklist'leri tek ajan rolünde yürütülüyor.
- **Platformdan beslenen multimodal içerik zekâsı:** `core/multimodal.py` hattı artık Poyraz'ın `ingest_video_insights` aracı üzerinden dış video kaynaklarını analiz edip bu veriyi içerik, kampanya ve operasyon aksiyonlarına dönüştüren fiili bir veri kaynağı olarak kullanılmaktadır.

> **Sonuç:** v4.x serisi Sidar'ın enterprise temelini tamamlamıştır; v5.x/Faz 6 bu temelin üstüne **daha derin akıl yürütme, daha dağıtık yürütme, daha güçlü öğrenme, daha otonom kurumsal iş akışları ve daha doğal insan-makine etkileşimi** katmanlarını fiilen ekleyen çalışma evresi olarak ilerlemektedir.

---
## 15. Özellik-Gereksinim Matrisi (v5.0.0-alpha Güncel Durum)

[⬆ İçindekilere Dön](#içindekiler)

Aşağıdaki matris, sistemin sahip olduğu kurumsal yeteneklerin hangi teknik gereksinimler ve modüller ile karşılandığını haritalandırmaktadır. Bu bölüm artık erken dönem RAG/LLM çekirdeğini değil, v4.3.0 baz çizgisi üzerinde başlayan **enterprise + swarm + observability + v5.0 geçiş** yüzeyini özetler.

| Özellik (Feature) | Teknik Gereksinim / İlgili Modül | Durum |
|---|---|---|
| **Çoklu-Ajan (Swarm) Orkestrasyonu** | Supervisor otonomisi, uzman ajan delegasyonu ve orchestration akışı (`agent/swarm.py`, `agent/core/supervisor.py`, `agent/registry.py`) | ✅ Tamamlandı |
| **Dağıtık İzlenebilirlik (Observability)** | OpenTelemetry span'leri, LLM metrikleri, Jaeger/OTel Collector ve Prometheus yüzeyi (`web_server.py`, `core/llm_metrics.py`, `managers/system_health.py`, `helm/sidar/`) | ✅ Tamamlandı |
| **Maliyet Optimizasyonu (Semantic Cache)** | Redis tabanlı semantic cache, cosine similarity eşleşmesi, TTL/LRU davranışı ve cache metrikleri (`core/llm_client.py`, `core/cache_metrics.py`) | ✅ Tamamlandı |
| **Veri Güvenliği ve İzolasyon (DLP)** | LLM çağrısından önce hassas verilerin maskelenmesi (`core/dlp.py`) | ✅ Tamamlandı |
| **Güvenli Otonomi (HITL)** | Yıkıcı eylemler öncesi insan onayı bekleyen asenkron karar kapısı (`core/hitl.py`, `web_server.py`) | ✅ Tamamlandı |
| **Çoklu-Kiracı (Multi-Tenant) & RBAC** | Tenant tabanlı kullanıcı/politika modeli, access policy enforcement ve audit trail (`core/db.py`, `web_server.py`, `migrations/versions/0003_audit_trail.py`) | ✅ Tamamlandı |
| **Modern Asenkron Arayüz (SPA)** | React + Vite + WebSocket/event-driven sunum katmanı (`web_ui_react/`, `web_server.py`) | ✅ Tamamlandı |
| **Model Ağ Geçidi (LLM Gateway)** | OpenAI/Anthropic/Ollama/LiteLLM yollarını tekleştiren sağlayıcı soyutlama katmanı (`core/llm_client.py`, `core/router.py`) | ✅ Tamamlandı |
| **Dinamik Genişletilebilirlik** | Runtime kayıt edilen ajan pazaryeri ve plugin yükleme akışı (`agent/registry.py`, `plugins/`, `web_server.py`) | ✅ Tamamlandı |
| **Sıfır Borç Kalite Kapısı** | Agresif test envanteri, CI kalite kapıları ve `%100` coverage hard gate (`.github/workflows/ci.yml`, `run_tests.sh`, `.coveragerc`, `tests/`) | ✅ Tamamlandı |
| **Varlık Belleği (Entity Memory)** | Persona/ilişki odaklı kalıcı kullanıcı belleği (`core/entity_memory.py`, `web_server.py`) | ✅ Tamamlandı |
| **Prompt Registry ve Yönetim Denetimi** | DB tabanlı prompt versiyonlama ve admin paneli (`migrations/versions/0002_prompt_registry.py`, `web_server.py`, `web_ui_react/src/components/PromptAdminPanel.jsx`) | ✅ Tamamlandı |
| **Multimodal Perception + Duplex Voice** | Medya ingestion, frame/audio çıkarma, `/ws/voice`, assistant turn metadata'sı, duplex buffer ve VAD/barge-in olayları (`core/multimodal.py`, `core/voice.py`, `web_server.py`) | ✅ Tamamlandı |
| **Dynamic Browser Automation** | Playwright/Selenium tabanlı, HITL ve audit trail ile kontrollü tarayıcı yönetimi (`managers/browser_manager.py`) | ✅ Tamamlandı |
| **GraphRAG + Reviewer Impact Gate** | Modül bağımlılık grafiği, etki analizi ve LSP diagnostics birleşik reviewer kalite kapısı (`core/rag.py`, `agent/roles/reviewer_agent.py`) | ✅ Tamamlandı |
| **Swarm Decision Graph + Live Operation Surface** | Node/edge tabanlı handoff görselleştirmesi, canlı karar görünürlüğü ve seçili node üzerinden operatör müdahalesi (`agent/swarm.py`, `web_ui_react/src/components/SwarmFlowPanel.jsx`, `core/hitl.py`) | ✅ Tamamlandı |

> **Not:** Kullanıcı isteğinde geçen “%100 Test Kapsaması” ifadesi artık repo kültüründeki hedefin ötesinde, `.coveragerc`, `run_tests.sh` ve CI üzerinde **resmî kalite kapısı** olarak da uygulanmaktadır.

---
## 16. Gözlemlenebilirlik (Observability), Loglama ve Hata Yönetimi

[⬆ İçindekilere Dön](#içindekiler)

Projenin v4.3.0 kurumsal sürümü ile birlikte geleneksel metin tabanlı loglama stratejisi genişletilerek **"Telemetry-First" gözlemlenebilirlik mimarisine** geçilmiştir. Bu yapı yalnızca konsola hata yazan bir uygulama modeli değil; LLM çağrıları, RAG akışları, ajan delegasyonları, oran sınırlama (rate limit) olayları ve denetim izlerini aynı operasyon yüzeyinde ilişkilendiren bütüncül bir işletim modelidir. `web_server.py`, `core/llm_client.py`, `agent/core/supervisor.py`, `core/llm_metrics.py`, `core/agent_metrics.py`, `core/cache_metrics.py`, `managers/system_health.py`, `helm/sidar/` ve `docker/` altındaki gözlemlenebilirlik bileşenleri bu katmanı birlikte oluşturur.

### 16.1 Dağıtık İzlenebilirlik (Distributed Tracing)

Basit `print` veya salt metin logları yerine; LLM API istekleri, FastAPI girişleri, `httpx` tabanlı dış servis çağrıları, RAG erişimleri ve Supervisor merkezli swarm görev delegasyonları OpenTelemetry (OTel) span'leri ile izlenir. `web_server.py` içindeki telemetry başlatma hattı ve `core/llm_client.py` ile `agent/core/supervisor.py` içindeki opsiyonel tracer kullanımı sayesinde hata, gecikme (latency) ve görev zinciri ilişkileri tek bir iz (trace) üzerinde toplanır.

Bu yaklaşımın operasyonel çıktısı Jaeger/OTel Collector hattıdır: bir kullanıcı isteğinin hangi role neden yönlendirildiği, hangi alt görevin ne kadar sürdüğü, hangi LLM veya araç çağrısının yavaşladığı ve hatanın tam olarak hangi span üzerinde üretildiği waterfall görünümünde milisaniye ayrıntısıyla incelenebilir. Böylece hata analizi artık yalnızca log satırı arama işi değil, dağıtık yürütümün uçtan uca izlenmesi haline gelmiştir.

### 16.2 Metrik Toplama ve Uyarı Sistemleri (Prometheus & Grafana)

Sistem sağlığı yalnızca exception sayımıyla değil, sürekli ölçülen metriklerle yönetilir. `core/llm_metrics.py`, `core/agent_metrics.py`, `core/cache_metrics.py` ve `managers/system_health.py`; LLM maliyet/latency verilerini, ajan delegasyon sürelerini, semantic cache hit-miss oranlarını, Redis hata sayılarını, API başarısızlıklarını ve servis sağlığı göstergelerini Prometheus uyumlu formatta dışarı açar. `web_server.py` üzerindeki metrics endpoint'leri bu verileri toplu biçimde yayınlar.

Bu metrik yüzeyi özellikle hata durumlarının görünürlüğünü artırır: 429 rate limit olayları, 5xx sınıfı sağlayıcı hataları, cache redis hataları, ajan bazlı başarısız delegasyonlar ve yanıt süresi bozulmaları gerçek zamanlı olarak izlenir. `docker/grafana/dashboards/sidar-llm-overview.json`, `docker/grafana/provisioning/` ve `helm/sidar/templates/configmap-grafana-slo-dashboard.yaml` dosyaları sayesinde Prometheus tarafından toplanan veriler Grafana panellerine, SLO göstergelerine ve operasyonel alarm yüzeylerine dönüştürülür.

### 16.3 Sürü (Swarm) İçi Hata Toleransı ve Otomatik Telafi (Fallback)

Kurumsal hata yönetimi tek bir ajan veya tek bir model başarısız olduğunda tüm sistemi durdurmamak üzerine kuruludur. **Model düzeyinde** `core/llm_client.py` ve `core/router.py`, sağlayıcı veya LiteLLM gateway tarafında 429/5xx sınıfı sorunlar, timeout'lar ya da bütçe/rate-limit kısıtları oluştuğunda alternatif modele veya yerel fallback akışına geçerek hizmet sürekliliğini korur.

**Ajan düzeyinde** ise Supervisor merkezli swarm mimarisi hatayı izole eder. `agent/core/supervisor.py`, alt görevleri role ajanlara bölerek delegasyon yapar; bir uzman ajan hata verdiğinde başarısızlık ilgili görev sınırları içinde tutulur, metriklere ve trace'lere işlenir, ardından görev aynı veya farklı bir ajana yeniden yönlendirilebilir. Bu graceful degradation yaklaşımı sayesinde tek bir Coder/Researcher/Reviewer ajanının çökmesi tüm kullanıcı isteğinin kontrolsüz biçimde düşmesine neden olmaz; sistem ölçülebilir şekilde kısmi sonuç, fallback veya yeniden deneme davranışı üretir.

**Chaos engineering referansı (Faz D):** `runbooks/chaos_live_rehearsal.md` ve `tests/test_system_health_dependency_checks.py`, bu fallback anlatısını prova edilebilir operasyon senaryolarına dönüştürür. Canlı prova akışında Redis kesildiğinde `/healthz` yolunun yaşam belirtisi olarak **200** üretmeye devam etmesi, buna karşılık `/readyz` çıktısının **503** dönerek `dependencies.redis.healthy=false` durumunu açığa vurması beklenir; böylece pod gereksiz restart olmadan trafikten çekilir. PostgreSQL kopmasında da aynı desen korunur: liveness ayakta kalır, readiness başarısız olur ve orchestrator yalnızca trafiği uzaklaştırır. Event bus tarafında ise bozuk/ack edilemeyen payload'lar DLQ hattına veya yerel buffer'a düşürülerek olay kaybı yerine kontrollü karantina sağlanır. Böylece swarm içi otomatik telafi, hem kod düzeyinde fallback hem de platform düzeyinde degrade-but-alive işletim modeli olarak belgelenmiş olur.

### 16.4 Kurumsal Denetim İzleri (Audit Logging)

Gözlemlenebilirlik katmanı yalnızca teknik hata ayıklama için değil, çok kiracılı (multi-tenant) kurumsal denetlenebilirlik için de tasarlanmıştır. `web_server.py` içindeki `_schedule_access_audit_log(...)` akışı ve `core/db.py` içindeki `audit_logs` şeması; kullanıcı, tenant, kaynak, aksiyon, IP adresi ve allow/deny sonucunu kalıcı denetim izi olarak kaydeder.

Bu audit trail yaklaşımı, güvenlik kararlarının sonradan yeniden üretilebilmesini sağlar. İnsan onayı gerektiren işlemler için `core/hitl.py` ve ilgili API uçları üzerinden yürüyen Human-in-the-Loop (HITL) süreçlerinde reddedilen veya zaman aşımına uğrayan eylemler de görünür kalır. Sonuç olarak hata yönetimi, loglama ve observability katmanı; operasyonel arıza teşhisi, güvenlik denetimi ve tenant izolasyonu için ortak bir kurumsal kayıt sistemi haline gelmiştir.
---

## 17. Yaygın Sorunlar ve Çözümleri (Troubleshooting)

[⬆ İçindekilere Dön](#içindekiler)

Uygulama dağıtık (distributed) ve çoklu-ajanlı bir mimariye geçtiği için karşılaşılabilecek yaygın sorunlar artık çoğunlukla servisler arası iletişim, veri düzlemi bağımlılıkları ve orkestrasyon darboğazlarından kaynaklanmaktadır. Aşağıdaki maddeler v4.3.0 kurumsal mimarisindeki gerçek çalışma yüzeyine göre güncellenmiştir.

### 17.1 Redis / Anlamsal Önbellek (Semantic Cache) Bağlantı Hatası

**Sorun:** Konsolda `Connection refused` benzeri Redis hataları görülür, semantic cache metrikleri üretilmez veya uygulama ilk açılışta cache erişimi yüzünden kararsız davranır.

**Neden:** `USE_SEMANTIC_CACHE=true` iken Redis servisinin çalışmıyor olması ya da uygulamanın Redis'e erişebileceği host/port bilgisinin yanlış yapılandırılması. Kod tabanı semantic cache ve agent event stream tarafında Redis kullandığı için bu katman devre dışı kaldığında cache ve bazı canlı akış senaryoları fallback moduna düşer.

**Çözüm:** Docker tabanlı ortamda `docker compose up -d redis` komutuyla Redis'i başlatın. Yerel geliştirme sırasında Redis kullanmayacaksanız `.env` içinde `USE_SEMANTIC_CACHE=false` yaparak semantic cache'i geçici olarak kapatın. Dağıtık ortamda ayrıca Redis URL/host ayarlarının deployment dosyaları ile uyumlu olduğundan emin olun.

### 17.2 PostgreSQL ve pgvector Hataları

**Sorun:** RAG vektör aramaları sırasında çökme, `relation does not exist` hatası veya pgvector backend açılırken başlatma başarısızlığı görülür.

**Neden:** `RAG_VECTOR_BACKEND=pgvector` seçildiği halde PostgreSQL erişimi hazır değildir, `vector` eklentisi yüklenmemiştir veya Alembic migration'ları çalıştırılmadığı için temel tablolar ve audit trail şemaları oluşmamıştır.

**Çözüm:** Veritabanına bağlanıp `CREATE EXTENSION IF NOT EXISTS vector;` komutunu çalıştırın. Ardından repo kökünde `alembic upgrade head` komutu ile migration'ları uygulayın. Özellikle PostgreSQL/pgvector ve audit log kullanan kurulumlarda `DATABASE_URL` değerinin doğru olduğundan ve migration zincirinin tam geçtiğinden emin olun.

### 17.3 Modern React (SPA) Arayüzüne Bağlanamama

**Sorun:** Web arayüzü beyaz ekranda kalır, SPA hiç açılmaz veya WebSocket akışı sürekli kopuyor gibi görünür.

**Neden:** Güncel mimaride backend (`web_server.py` / FastAPI) ile frontend (`web_ui_react/` / React + Vite) ayrı geliştirme süreçleri olarak çalışır. Yalnızca backend'i ayağa kaldırmak geliştirme modundaki SPA'yı otomatik başlatmaz; ayrıca tarayıcının yanlış porttan açılması ya da Vite proxy zincirinin çalışmaması bağlantı sorunlarına yol açar.

**Çözüm:** Ayrı bir terminalde `cd web_ui_react && npm install && npm run dev` komutlarını çalıştırın ve geliştirme sırasında tarayıcıdan FastAPI portu yerine Vite sunucusuna (varsayılan `http://localhost:5173`) gidin. Production benzeri kullanımda `npm run build` sonrası oluşan `web_ui_react/dist/` klasörünün `web_server.py` tarafından otomatik servis edildiğini unutmayın.

### 17.4 HTTP 429 Too Many Requests (Hız Limitleri)

**Sorun:** Çoklu-ajan (swarm) senaryolarında veya yoğun LLM kullanımında sistem sık sık `429 Too Many Requests` yanıtları üretir.

**Neden:** Supervisor/swarm katmanı alt görevlere paralel yürütüm verdiğinde hem uygulama içi rate-limit middleware'i hem de dış LLM sağlayıcılarının RPM/TPM kotaları aynı anda baskı oluşturabilir. Özellikle `/api/swarm/execute` yolunda `max_concurrency` artırıldığında, OpenAI/Anthropic/LiteLLM geçidi tarafındaki limitler daha görünür hale gelir.

**Çözüm:** Swarm görevlerinde eşzamanlılık düzeyini düşürün; UI veya API payload'ında `max_concurrency` değerini azaltın. LLM gateway kullanıyorsanız `LITELLM_GATEWAY_URL` ve fallback model ayarlarını gözden geçirerek yükü birden fazla model/anahtar arasında dağıtın. Gerekirse uygulama tarafındaki rate-limit eşiklerini ve sağlayıcı kota ayarlarını birlikte yeniden dengeleyin.

### 17.5 Sistem Donması / Ajanların Tepki Vermemesi (HITL Beklemesi)

**Sorun:** Ajanlar bir kod veya veri işlemi sırasında aniden durmuş gibi görünür; UI akışı ilerlemez ve son kullanıcı yeni çıktı alamaz.

**Neden:** Sistem tehlikeli veya yıkıcı kabul edilen bir işlemi `Human-in-the-Loop (HITL)` onay kapısına göndermiş olabilir. Bu durumda yürütüm aslında tamamen çökmemiştir; `pending` durumundaki bir insan onayı beklemektedir.

**Çözüm:** Yönetim yüzeyinden veya API üzerinden bekleyen işlemleri kontrol edin. `GET /api/hitl/pending` ile bekleyen istekleri listeleyin; uygun kararı vermek için `POST /api/hitl/respond/{request_id}` uç noktasını kullanarak işlemi approve/reject edin. Operasyonel olarak bu tür beklemeleri izlemek için admin paneli, audit kayıtları ve HITL bildirim akışlarının açık tutulması önerilir.

### 17.6 OpenTelemetry (OTel) Gecikme Uyarıları

**Sorun:** Jaeger veya OTel Collector hattında span süreleri anormal derecede uzun görünür; örneğin bazı LLM veya RAG span'leri 15-20 saniyeyi aşar.

**Neden:** Sorun çoğu zaman tracing altyapısından değil, trace edilen iş yükünün kendisinden kaynaklanır. Yavaş internet bağlantısı, ağır model seçimi, fazla büyük prompt bağlamı veya RAG tarafından LLM'e gereğinden fazla belge taşınması toplam span süresini yükseltir.

**Çözüm:** Önce model ve ağ gecikmesini kontrol edin; ardından RAG yükünü azaltmak için `RAG_TOP_K` değerini düşürün ve gereksiz uzun bağlamları daraltın. Böylece hem LLM'e gönderilen içerik küçülür hem de Jaeger üzerinde görülen span gecikmeleri daha yönetilebilir seviyeye iner.

## 18. Geliştirme Geçmişi ve Final Doğrulama Raporu

[⬆ İçindekilere Dön](#içindekiler)

Proje, başlangıçtaki basit CLI tabanlı kişisel asistan vizyonundan çıkarak `v4.3.0` itibarıyla **otonom, denetlenebilir ve kurumsal çoklu-ajan (Enterprise Swarm) platformu** düzeyine ulaşmıştır. Bu kapanış bölümü artık erken dönem audit günlüklerinin arşivi değil; tamamlanan fazların, ürünleşen mimarinin ve sıfır borç disiplininin özetidir.

### Kilometre Taşları

- **Faz 1-3 — Temel Altyapı:** CLI akışı, ilk web yüzeyi, temel RAG/ChromaDB omurgası ve yerel/bulut LLM entegrasyonları ile ürünün çekirdek çalışma modeli kuruldu.
- **Faz 4 — Kurumsal Dönüşüm ve Güvenlik:** PostgreSQL + `pgvector` veri katmanı, Alembic migration zinciri, Redis semantic cache, tenant RBAC/audit trail, DLP maskeleme ve Human-in-the-Loop güvenlik kapıları ile sistem kurumsal veri yönetişimine taşındı.
- **Faz 5 — Zeki Sürü ve Gözlemlenebilirlik:** Supervisor liderliğinde uzman rollere bölünen swarm orkestrasyonu, AgentRegistry/plugin marketplace, direct `p2p.v1` handoff protokolü ve OpenTelemetry + Jaeger + Prometheus/Grafana hattı ile tekil ajan yapısı kurumsal observability-first çalışma modeline evrildi.
- **Faz 5.5 — Arayüz Modernizasyonu:** Legacy statik web yüzeyi geri uyumluluk için korunurken, `web_ui_react/` altında React + Vite + WebSocket tabanlı modern SPA kullanıcı deneyimi varsayılan yönetim ve operasyon yüzeyi haline geldi.
- **v4.3.0 — Sürüm ve Ölçüm Senkronizasyonu:** Runtime, paket metadata'sı, Helm chart ve üst seviye dokümantasyon aynı sürüm çizgisine taşındı; repo metrikleri yalnızca Git takipli dosyalar üzerinden yeniden doğrulanarak üretim ölçümleri güvenilir hale getirildi.

### Final Doğrulama ve Sıfır Teknik Borç Durumu

Bu rapor itibarıyla proje yalnızca özellik eklemiş bir prototip değil; test, audit ve operasyon yüzeyleri birbirini doğrulayan olgun bir sistemdir. CI hattı `.github/workflows/ci.yml` üzerinden **%100 coverage hard gate** uygular; bu değer depo kültüründeki tam kapsama hedefinin repo içinde gerçekten kodlanmış karşılığıdır.

Son doğrulama turlarında migration akışları, swarm delegasyonları, audit trail kayıtları, observability hattı, HITL güvenlik kapıları, Redis/PostgreSQL veri düzlemi ve React SPA/REST/WebSocket yüzeyleri birlikte yeniden kontrol edilmiştir. `CHANGELOG.md`, `AUDIT_REPORT_v5.0.md` ve bu rapor aynı temel sonucu teyit eder: **açık kritik, yüksek, orta veya düşük öncelikli majör teknik borç kalmamıştır**; sistem kurumsal rollout ve production dağıtımı için hazır durumdadır.

### Güncel Kapanış Özeti (v5.0.0-alpha)

- **Güncel baz çizgisi:** 62 üretim Python dosyası / 26.261 satır, 167 test dosyası / 46.874 satır, toplam 229 takipli Python dosyası / 73.135 satır ve takipli ölçüm yüzeyi 343 dosya / 87.576 satır.
- **Operasyonel durum:** Güvenlik/operasyon puanı `10.0/10`; açık bulgu yok; audit trail, observability ve swarm orkestrasyonu birlikte doğrulanmış durumda.
- **Kurumsal sonuç:** Sidar artık yalnızca “kod yazan ajan” değil; React SPA, PostgreSQL/pgvector, Redis semantic cache, DLP/HITL güvenlik duvarı, Supervisor-first swarm ve telemetry-first observability katmanlarını tek üründe birleştiren üretim adayı bir platformdur.

> **Arşiv Notu:** Satır satır sürüm günlüğü, kapanan teknik borç kalemleri ve ara denetim turları için `CHANGELOG.md` ve `AUDIT_REPORT_v5.0.md` dosyalarına başvurulmalıdır.
