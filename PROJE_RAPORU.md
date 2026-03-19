
# SİDAR Projesi — Kapsamlı Kod Analiz Raporu (Güncel)

> ---
> 📋 **CHANGELOG:** Tüm çözülen bulgular, sürüm geçmişi ve teknik borç kapanışları için → **[CHANGELOG.md](CHANGELOG.md)**
> _(Her denetim sonrası §11 bulgu tablosu buraya aktarılır. Rapor yalnızca aktif/açık bulgular için referans noktasıdır.)_
> ---

> **Rapor Tarihi:** 2026-03-14
> **Son Güncelleme:** 2026-03-19 (v4.3.0 — Sürüm ve metrik senkronizasyonu tamamlandı. `scripts/audit_metrics.sh` ve `scripts/collect_repo_metrics.sh` Git-takipli dosyaları esas alacak şekilde düzeltilerek `.venv` / `node_modules` kaynaklı şişkin ölçümler elimine edildi; ardından `config.py`, paket metadata'sı, Helm chart ve üst seviye raporlar aynı sürüm çizgisine taşındı. Güncel takipli ölçümler: üretim Python **20.582** satır (**58** dosya), test havuzu **39.147** satır (**149** test modülü / **151** Python test dosyası), toplam takipli Python **59.729** satır (**209** dosya), Web UI toplamı **6.105** satır ve runbook kümesi **367** satır. Mevcut kod durumunda **60** REST endpoint, açık kritik/yüksek/orta/düşük bulgu bulunmadığı ve API/DB/env sözleşmelerinde yeni delta olmadığı yeniden teyit edildi.)
> **Önceki Güncelleme:** 2026-03-19 (v3.2.0 — Autonomous LLMOps özellik turu tamamlandı: Active Learning/LoRA (`core/active_learning.py`), Vision Pipeline (`core/vision.py`), Cost-Aware routing (`core/router.py`) ve Slack/Jira/Teams tabanlı dış sistem orkestrasyonu birlikte değerlendirilerek Faz 4 teslimatının ürünleştiği teyit edildi.)
> **Proje Sürümü:** 4.3.0

> **Önceki Kayıt:** 3.0.30
> **Derin Teknik Kılavuz:** API/DB/Operasyon detayları için `TEKNIK_REFERANS.md` dosyasına bakınız.
> **Analiz Kapsamı:** Tüm takipli kaynak dosyaları satır satır yeniden ölçülmüştür. Güncel üretim Python hacmi **20.582** satır (**58** takipli `.py` dosyası; `tests/` hariç), test havuzu **39.147** satır (**149** test modülü / **151** Python test dosyası dahil yardımcı dosyalar), tüm takipli Python toplamı **59.729** satırdır. Web UI toplamı (`web_ui/` + `web_ui_react/`) **6.105** satır, runbook kümesi **4** dosya / **367** satırdır. Bu revizyonda özellikle root giriş dosyaları (`main.py`, `cli.py`, `web_server.py`, `config.py`, `github_upload.py`, `gui_launcher.py`) ve metrik betikleri (`scripts/audit_metrics.sh`, `scripts/collect_repo_metrics.sh`) yeniden doğrulanmış; başlatma, CLI oturum yönetimi, web kontrol düzlemi, konfigürasyon bootstrap'i ve güvenli ölçüm akışları raporlarla senkronize edilmiştir.

---

<a id="içindekiler"></a>
## İçindekiler
- [1. Proje Genel Bakışı](#1-proje-genel-bakışı)
  - [Temel Özellikler](#temel-özellikler)
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
  - [6.2 Coverage Hard Gate (%99.9)](#62-coverage-hard-gate-999)
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
- [11. Mevcut Sorunlar ve Teknik Borç (Sıfır Borç Durumu)](#11-mevcut-sorunlar-ve-teknik-borç-sıfır-borç-durumu)
  - [11.1 Ödenmiş Teknik Borçlar (Resolved)](#111-ödenmiş-teknik-borçlar-resolved)
  - [11.2 Gelecek İyileştirmeler (Continuous Improvement)](#112-gelecek-iyileştirmeler-continuous-improvement)
  - [11.3 2026-03-16 v3.0.6 Doğrulama Turu — Operasyonel Uyumsuzluklar](#113-2026-03-16-v306-doğrulama-turu--operasyonel-uyumsuzluklar)
  - [11.4 2026-03-16 v3.0.7 Doğrulama Turu — Yeni Bulgular ve Kapatma Durumu](#114-2026-03-16-v307-doğrulama-turu--yeni-bulgular-ve-kapatma-durumu)
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
- [16. Hata Yönetimi ve Loglama Stratejisi](#16-hata-yönetimi-ve-loglama-stratejisi)
  - [16.1 Hata Yönetimi Kalıpları](#161-hata-yönetimi-kalıpları)
  - [16.2 Loglama Stratejisi](#162-loglama-stratejisi)
  - [16.3 Asenkron Hata Yönetimi](#163-asenkron-hata-yönetimi)
  - [16.4 Bozuk Veri Karantinası](#164-bozuk-veri-karantinası)
- [17. Yaygın Sorunlar ve Çözümleri](#17-yaygın-sorunlar-ve-çözümleri)
  - [17.1 Ollama Bağlantı Sorunları](#171-ollama-bağlantı-sorunları)
  - [17.2 GPU / CUDA Sorunları](#172-gpu-cuda-sorunları)
  - [17.3 ChromaDB / RAG Sorunları](#173-chromadb-rag-sorunları)
  - [17.4 Docker REPL Sorunları](#174-docker-repl-sorunları)
  - [17.5 Bellek / Şifreleme Sorunları](#175-bellek-şifreleme-sorunları)
  - [17.6 GitHub Entegrasyon Sorunları](#176-github-entegrasyon-sorunları)
  - [17.7 Web Sunucu Sorunları](#177-web-sunucu-sorunları)
  - [17.8 `.env` Dosyası Sorunları](#178-env-dosyası-sorunları)
  - [17.9 Bulut LLM 429 (Rate Limit) Hatası](#179-bulut-llm-429-rate-limit-hatası)
  - [17.10 Ajan Döngüsü / JSON Parse Hataları](#1710-ajan-döngüsü-json-parse-hataları)
  - [17.11 Supervisor Devreye Girmiyor (Tekli Ajan Davranışı)](#1711-supervisor-devreye-girmiyor-tekli-ajan-davranışı)
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
- **RAG (Vektör Bellek):** ChromaDB veya pgvector + BM25 + keyword hibrit arama (RRF destekli) akışıyla çalışır (`core/rag.py`).
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
- **Jira / Slack / Teams Entegrasyonu:** Jira Cloud REST API v3, Slack Bot SDK + Webhook fallback (Block Kit), Teams MessageCard + Adaptive Card v1.4 ve HITL onay kartı (`managers/jira_manager.py`, `managers/slack_manager.py`, `managers/teams_manager.py`).
- **Kök kontrol düzlemi doğrulaması (v3.0.29):** `main.py` sihirbaz + quick-start başlatma katmanı, `cli.py` tek event-loop CLI oturumu, `web_server.py` geniş FastAPI kontrol düzlemi (mevcut dosyada 61 route/websocket decorator), `config.py` bootstrap/telemetry yükleme yolu, `github_upload.py` güvenli `git ls-files` paketleme akışı ve `gui_launcher.py` Eel köprüsü mevcut repo durumu ile yeniden teyit edilmiştir.
- **Son doğrulama notu (v3.0.30):** `core/entity_memory.py`, `core/cache_metrics.py`, `core/judge.py`, `core/vision.py`, `core/active_learning.py`, `core/hitl.py`, `core/llm_client.py` ve `web_server.py` üzerindeki D-8..D-14 düzeltmeleri yeniden gözden geçirilmiş; incelenen modüllerde kritik açık bir bulguya rastlanmadığı rapora işlenmiştir.

---

## 2. Proje Dosya Yapısı

[⬆ İçindekilere Dön](#içindekiler)

<pre>
sidar_project/
├── .github/workflows/         # CI/CD süreçleri (ci.yml, migration-cutover-checks.yml)
├── <a href="docs/module-notes/main.py.md">main.py</a>                    # Akıllı başlatıcı (wizard + --quick mod)
├── <a href="docs/module-notes/cli.py.md">cli.py</a>                     # CLI terminal arayüzü giriş noktası
├── <a href="docs/module-notes/web_server.py.md">web_server.py</a>              # FastAPI web sunucusu (WebSocket streaming)
├── <a href="docs/module-notes/config.py.md">config.py</a>                  # Merkezi yapılandırma (v4.3.0)
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
│       └── <a href="docs/module-notes/agent/roles/reviewer_agent.py.md">reviewer_agent.py</a>  # Test koşturan, kod kalitesini denetleyen QA ajanı
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
│   └── vision.py              # Multimodal Vision Pipeline: UI mockup → kod, provider formatları (YENİ — v3.0.23+)
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
│       └── 0003_audit_trail.py         # Tenant RBAC audit trail geçişi
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
├── <a href="docs/module-notes/coveragerc.md">.coveragerc</a>                # Coverage kalite kapısı kuralları (%99.9 eşik)
├── <a href="docs/module-notes/env.example.md">.env.example</a>               # Ortam değişkeni şablonu
├── AUDIT_REPORT_v4.0.md       # v4.0 kurumsal geçiş denetim raporu
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
| 3.11 | `agent/roles/coder_agent.py`, `researcher_agent.py`, `reviewer_agent.py` | [docs/module-notes/agent/roles/coder_agent.py.md](docs/module-notes/agent/roles/coder_agent.py.md), [docs/module-notes/agent/roles/researcher_agent.py.md](docs/module-notes/agent/roles/researcher_agent.py.md), [docs/module-notes/agent/roles/reviewer_agent.py.md](docs/module-notes/agent/roles/reviewer_agent.py.md) |
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
| 3.23 | `managers/security.py`, `managers/code_manager.py` | [docs/module-notes/managers/security.py.md](docs/module-notes/managers/security.py.md), [docs/module-notes/managers/code_manager.py.md](docs/module-notes/managers/code_manager.py.md) |
| 3.24 | `managers/github_manager.py`, `managers/package_info.py` | [docs/module-notes/managers/github_manager.py.md](docs/module-notes/managers/github_manager.py.md), [docs/module-notes/managers/package_info.py.md](docs/module-notes/managers/package_info.py.md) |
| 3.25 | `managers/system_health.py`, `managers/web_search.py`, `managers/todo_manager.py` | [docs/module-notes/managers/system_health.py.md](docs/module-notes/managers/system_health.py.md), [docs/module-notes/managers/web_search.py.md](docs/module-notes/managers/web_search.py.md), [docs/module-notes/managers/todo_manager.py.md](docs/module-notes/managers/todo_manager.py.md) |
| 3.26 | `managers/jira_manager.py`, `managers/slack_manager.py`, `managers/teams_manager.py` | Ayrı modül notu henüz yok; kurumsal iletişim ve iş akışı entegrasyonları |

### 3.D UI, Altyapı ve Operasyon

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.27 | `web_ui/`, `web_ui_react/` | [docs/module-notes/web_ui/index.html.md](docs/module-notes/web_ui/index.html.md); React SPA için ayrı modül notu henüz yok |
| 3.28 | `github_upload.py`, `gui_launcher.py` | [docs/module-notes/github_upload.py.md](docs/module-notes/github_upload.py.md); `gui_launcher.py` için ayrı modül notu henüz yok |
| 3.29 | `migrations/`, `scripts/` | [docs/module-notes/migrations/env.py.md](docs/module-notes/migrations/env.py.md) |
| 3.30 | `docker/`, `runbooks/`, `helm/` | [docs/module-notes/docker/prometheus/prometheus.yml.md](docs/module-notes/docker/prometheus/prometheus.yml.md); `helm/` için ayrı modül notu henüz yok |

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

- **`test_*.py` modül sayısı:** **149**
- **`tests/*.py` toplamı (`conftest.py` + `__init__.py` dahil):** **151**
- **Toplam test satırı (`tests/*.py`):** **39.148**
- **Kapsama politikası:** `.coveragerc`, `pytest.ini`, `run_tests.sh` ve CI hattı ile yönetilen **%99.9 hard gate**

**Öne çıkan test kategorileri (v4.3.0):**
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
| Coverage Quality Gate (`fail_under=99.9`) | ✅ Zorunlu | `.coveragerc`, `run_tests.sh`, `.github/workflows/ci.yml` |
| Ayrı coverage adımı (`--cov-fail-under=99.9`) | ✅ Aktif | `.github/workflows/ci.yml` |
| Boş test artifact engeli (`find tests -size 0`) | ✅ Zorunlu | `.github/workflows/ci.yml`, `scripts/check_empty_test_artifacts.sh` |
| `pg_stress` izolasyonu | ✅ Aktif | `.github/workflows/ci.yml`, `tests/test_db_postgresql_branches.py` |
| Sandbox/Reviewer sertleştirme testi | ✅ Aktif | `tests/test_sandbox_runtime_profiles.py`, `tests/test_reviewer_agent.py` |

Bu yapı ile test disiplini yalnızca birim test sayısına değil, **coverage barajı + artifact hijyeni + enterprise senaryo regresyonları** üzerine kurulu kurumsal bir kalite modeline taşınmıştır.

### 6.2 Coverage Hard Gate (%99.9)

- `.coveragerc` içinde `fail_under = 99.9` ve `show_missing = True` ayarları zorunlu kalite kapısı olarak tanımlıdır.
- `pytest.ini`, `python_files = test_*.py` ve `asyncio_mode = auto` ayarlarıyla aynı test evrenini deterministik biçimde çalıştırır.
- CI hattı (`.github/workflows/ci.yml`) ayrı bir adımda `python -m pytest -q --cov=. --cov-report=term-missing --cov-fail-under=99.9` komutu ile coverage eşiğini uygular.
- `run_tests.sh` betiği de `COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-99.9}"` değişkeniyle aynı eşiği yerelde tekrarlar.
- Depoda `test_quick_100.py` ve `test_ultimate_coverage.py` gibi agresif kapsama odaklı testler bulunur; bu yaklaşım, "test çalıştı" seviyesinin ötesinde **ölçülebilir kapsam** zorunluluğu getirir.

### 6.3 Test Havuzu ve Modüler Senaryolar

- Güncel depoda `test_*.py` desenine uyan **149 test modülü** bulunur; `tests/*.py` toplamı (yardımcı dosyalar dahil) **151** adettir.
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

Bu bölüm, güncel `pyproject.toml`, `requirements-dev.txt`, `environment.yml` ve `web_ui_react/package.json` dosyalarına göre v4.3.0 bağımlılık setini kurumsal kategorilerle özetler. (`requirements.txt` diskte bulunmaz; Python bağımlılıkları `pyproject.toml` PEP 621 standardında, React SPA bağımlılıkları ise `web_ui_react/package.json` içinde yönetilir.)

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

Bu bölüm, `v4.3.0` senkronizasyon turunda takipli depo içeriği için yeniden üretilen `wc -l` ölçümlerini içerir.

**Hacimsel özet (yönetici görünümü):** Kod tabanı artık küçük bir monolit değildir; test havuzu Python ekosisteminin en büyük payını oluştururken, `core/`, `agent/` ve `managers/` altında kurumsal backend/sürü orkestrasyonu; `web_ui_react/` ile modern SPA katmanı; `helm/`, `docker/`, Grafana dashboard'ları ve runbook'lar ile de ciddi bir Infrastructure-as-Code / operasyon dokümantasyonu hacmi oluşmuştur.

- **Test ağırlığı:** Python kod hacminin en büyük payı `tests/` altındaki unit, integration ve enterprise senaryo testlerinden gelir.
- **Backend + Swarm çekirdeği:** `core/`, `agent/`, `managers/` ve giriş dosyaları projenin ana motorunu oluşturan binlerce satırlık Python iş mantığını barındırır.
- **Modern frontend katmanı:** Legacy `web_ui/` korunurken `web_ui_react/` altındaki React/Vite SPA projeye ek JavaScript/JSX/CSS hacmi kazandırır.
- **Altyapı ve dokümantasyon:** Helm chart'ları, Docker/Grafana/Prometheus dosyaları, CI akışları ve runbook'lar üretim işletimini kod olarak tanımlar.

**Ölçüm notu (standart):** Kurumsal tekrar üretilebilirlik için satır sayısı raporları `scripts/audit_metrics.sh` ve `scripts/collect_repo_metrics.sh` ile otomatik üretilmelidir. Her iki betik de Git deposu içinde varsayılan olarak yalnızca takipli dosyaları ölçer.

### 8.1 Çekirdek Modüller (Güncel)

| Dosya | Satır |
|---|---:|
| `config.py` | 843 |
| `main.py` | 382 |
| `cli.py` | 290 |
| `web_server.py` | 2.532 |
| `agent/sidar_agent.py` | 588 |
| `agent/auto_handle.py` | 613 |
| `agent/definitions.py` | 169 |
| `agent/tooling.py` | 113 |
| `agent/base_agent.py` | 112 |
| `agent/registry.py` | 187 |
| `agent/swarm.py` | 504 |
| `core/llm_client.py` | 1.388 |
| `core/memory.py` | 301 |
| `core/rag.py` | 1.143 |
| `core/db.py` | 1.861 |
| `core/llm_metrics.py` | 282 |
| `core/agent_metrics.py` | 118 |
| `core/dlp.py` | 320 |
| `core/hitl.py` | 287 |
| `core/judge.py` | 469 |
| `core/router.py` | 211 |
| `core/entity_memory.py` | 281 |
| `core/cache_metrics.py` | 189 |
| `core/active_learning.py` | 505 |
| `core/vision.py` | 294 |
| `managers/security.py` | 291 |
| `managers/code_manager.py` | 1.011 |
| `managers/github_manager.py` | 645 |
| `managers/system_health.py` | 538 |
| `managers/web_search.py` | 388 |
| `managers/package_info.py` | 344 |
| `managers/todo_manager.py` | 452 |
| `managers/slack_manager.py` | 234 |
| `managers/jira_manager.py` | 245 |
| `managers/teams_manager.py` | 234 |
| `github_upload.py` | 295 |
| `gui_launcher.py` | 98 |

### 8.2 Multi-Agent Çekirdek ve Roller

| Dosya | Satır |
|---|---:|
| `agent/core/supervisor.py` | 291 |
| `agent/core/contracts.py` | 99 |
| `agent/core/event_stream.py` | 218 |
| `agent/core/memory_hub.py` | 55 |
| `agent/core/registry.py` | 30 |
| `agent/roles/coder_agent.py` | 168 |
| `agent/roles/researcher_agent.py` | 80 |
| `agent/roles/reviewer_agent.py` | 247 |

### 8.3 Migration / Operasyon / Altyapı

| Dosya | Satır |
|---|---:|
| `migrations/env.py` | 66 |
| `migrations/versions/0001_baseline_schema.py` | 99 |
| `migrations/versions/0002_prompt_registry.py` | 53 |
| `migrations/versions/0003_audit_trail.py` | 38 |
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
| **Web UI Toplamı (`web_ui/` + `web_ui_react/`)** | **6.105** |
| **Test modülü (`tests/test_*.py`)** | **149** |
| **`tests/*.py` toplam dosya** | **151** |
| **`tests/*.py` toplam satır** | **39.148** |

### 8.5 Dizin Bazlı Hacim Özeti

| Dizin/Kapsam | Ölçüm | Değer |
|---|---|---:|
| `tests/` | `test_*.py` modül sayısı | 149 |
| `tests/` | `*.py` toplam dosya | 151 |
| `tests/` | `*.py` toplam satır | 39.148 |
| `scripts/` | dosya sayısı | 7 |
| `scripts/` | toplam satır | 613 |
| `migrations/` | `.py` dosya sayısı (env.py + 3 versions) | 4 |
| `migrations/` | `*.py` toplam satır | 256 |
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

---

## 11. Mevcut Sorunlar ve Teknik Borç (Sıfır Borç Durumu)

> **Güncel Durum (2026-03-19 — v4.3.0):** Bu sürümde kod tabanı için “aktif teknik borç” ifadesi, klasik anlamda açık bug/backlog değil; CI kalite kapıları, telemetri ve agresif regresyon testleriyle sürekli bastırılan bir risk kategorisidir. Bu nedenle bu bölüm artık “hangi borçlar açık?” sorusundan çok, **sıfır borç durumunun nasıl korunduğunu** ve **hangi sınırların koddan değil işletim ortamından kaynaklandığını** belgelendirir.

### 11.1 Sürdürülebilir Sıfır Borcun Matematiksel Kanıtı

✅ **Sıfır teknik borç durumu bir söylem değil, otomatik kalite kapısıdır.** Repository’deki zorlayıcı kalite zinciri yeni kodun kapsama dışı kalmasını pratikte engeller:

- **CI doğrulaması zorunludur:** `.github/workflows/ci.yml` ana test işinde önce `run_tests.sh`, ardından ayrıca açık bir “Enforce coverage quality gate (99.9%)” adımı ile `python -m pytest -q --cov=. --cov-report=term-missing --cov-fail-under=99.9` komutu çalıştırılır. Kapsamayı düşüren bir PR bu kapıda otomatik olarak reddedilir.
- **Aynı eşik depo içinde de sabittir:** `.coveragerc` ve `run_tests.sh` aynı `99.9` kalite eşiğini tekrarlar; yani kural yalnızca CI ekranında değil, depo içindeki test komutlarının kendisinde de kodlanmıştır.
- **Pytest keşfi merkezileştirilmiştir:** `pytest.ini` tüm `tests/` ağacını standart `test_*.py` deseniyle toplar; `pg_stress` gibi marker'lar ayrı altyapı gerektiren testleri kontrollü ama görünür biçimde çalıştırır. Böylece “test edilmeyen yeni yüzey” ihtimali minimize edilir.
- **Kalite politikasının kendisi de test edilir:** `tests/test_coverage_policy.py` doğrudan `pytest.ini`, `run_tests.sh`, `.coveragerc` ve `ci.yml` dosyalarını okuyup kalite kapısının kaldırılmadığını doğrular. Yani sadece ürün kodu değil, kalite kuralı da regresyon testine tabidir.
- **%100 kapsamaya yakın/fonksiyonel hedef ayrı regresyon dosyalarıyla korunur:** `tests/test_ultimate_coverage.py` ve `tests/test_missing_edge_case_coverage_final.py` gibi dosyalar uç yolları zorlayarak kapsama boşluğu bırakmama felsefesini sürdürür. Pratikte yazılı quality gate `99.9` olsa da, repo kültürü ve test isimlendirmesi “fiilî tam kapsama” hedefiyle hareket eder.

> Sonuç: Bu projede “teknik borç sıfır” ifadesi, manuel iyimserlikten değil; **tekrar edilebilir test matematiğinden, otomatik coverage reddinden ve kalite politikasının da test edilmesinden** doğar.

### 11.2 Gözlemlenebilirlik ile Gizli Borçların Proaktif Engellenmesi

Kod tabanında açık bug kalmaması tek başına yeterli değildir; kurumsal mimaride asıl risk, zamanla biriken **gizli performans borcu**dur. v4.3.0 bu borcu OpenTelemetry tabanlı gözlemlenebilirlikle erken yakalar:

- `web_server.py` içinde tracing etkinse uygulama FastAPI + HTTPX enstrümantasyonu ile OTLP exporter'a bağlanır; varsayılan Helm yardımcısı OTel hedefini APM collector'a, o yoksa `http://jaeger:4317` varsayılanına yönlendirir.
- `core/llm_client.py` LiteLLM yolunda `llm.litellm.chat` span'leri üretir; provider, stream modu, model ve toplam süre gibi attribute'lar kaydedilir. Aynı desen OpenAI/Ollama/Anthropic yollarına da yayılmıştır.
- `tests/test_otel_openai_litellm_spans.py` ve `tests/test_otel_rag_spans.py` bu span'lerin gerçekten açıldığını ve kritik attribute'ların yazıldığını doğrular; telemetri yalnızca “dokümante edilen” değil, testlenen bir davranıştır.
- RAG tarafında yavaş sorgular, backend seçimi ve vektör yolunun davranışı span seviyesinde izlenebilir olduğu için gecikme bir “mimari borç” haline gelmeden tespit edilir; semantic cache ve router kararları bu yüzden yalnızca maliyet optimizasyonu değil, aynı zamanda borç önleme mekanizmasıdır.

> Kurumsal yorum: Bu mimaride observability sonradan eklenen dashboard katmanı değil; latent darboğazların Jaeger/OTLP/Prometheus yüzeylerinde görünür kılınması sayesinde **borç oluşumunu proaktif olarak engelleyen kontrol sistemi**dir.

### 11.3 Teknik Borç Yok; Operasyonel Sınırlar Var

Bilinen açık bug veya kronik kod borcu bulunmamakla birlikte, aşağıdaki başlıklar yazılım kusuru değil **operasyonel sınır** olarak değerlendirilmelidir:

- **LLM API hız limitleri ve kota sınırları:** Swarm mimarisinde uzman ajanlar paralel çağrı açabildiği için OpenAI, Anthropic veya benzeri dış sağlayıcılarda RPM/TPM limitlerine daha hızlı ulaşılabilir. Bu durum mimari hata değil, çoklu ajan paralelliğinin dış servis kotasıyla etkileşimidir.
- **LiteLLM Gateway / dış ağ bağımlılığı:** `core/llm_client.py` gateway tabanlı bir OpenAI-uyumlu yol sunar; ancak gateway URL erişilemezse, proxy gecikirse veya dış ağda kesinti oluşursa toplam yanıt süresi uzar. Özellikle OpenRouter benzeri ara katmanlar kullanıldığında bu etki daha görünür hale gelir.
- **Yerel model çalıştırmada donanım limiti:** Ollama/yerel embedding akışında performansı doğrudan CPU/GPU ve özellikle VRAM kapasitesi belirler. `core/rag.py` FP16/mixed-precision ile VRAM tasarrufu yapabilse de, düşük bellekli GPU'larda ajan hızı ve eşzamanlılık seviyesi doğal olarak sınırlanır.
- **Vektör veri katmanının ölçek davranışı:** pgvector/ChromaDB hibrit arama güçlüdür; ancak tenant sayısı ve belge hacmi arttıkça vektör indeksleri ile embedding tablosunun RAM/IO davranışı yakından izlenmelidir. Büyük kurulumlarda pgvector index tuning (ör. IVFFlat/HNSW seçimi), vacuum ve kapasite planı operasyon ekibinin sorumluluğundadır.
- **Redis ve event-stream bağımlılıkları:** Semantic cache ve event stream katmanları Redis mevcutken daha hızlı ve daha düşük maliyetli çalışır; Redis kesintisinde sistem fail-safe/fallback yollarına düşse de, latency profili değişebilir.

### 11.4 Ödenmiş Teknik Borçlar (Arşiv / Resolved)

Aşağıdaki maddeler geçmişte kapanmış ve sıfır borç durumuna ulaşılmasını sağlayan başlıca düzeltmelerdir:

- **[Çözüldü] Legacy Test Kayması (Test Drift):** Eski senkron ajan yapısına ait testler, Supervisor-odaklı P2P ve delegasyon sözleşmelerine tam uyumlu olacak şekilde baştan yazıldı. Uç durum (edge case) testleri eklendi.
- **[Çözüldü] Bağımlılık Şişkinliği ve Çelişkisi:** Toplam 9 paket (`chromadb`, `torch`, `torchvision`, `sentence-transformers`, `asyncpg` ve `opentelemetry-*` ailesi) çekirdek kurulumdan ayrıştırılıp `pyproject.toml` üzerinde ilgili extras gruplarında (`[rag]`, `[postgres]`, `[telemetry]`) yönetilir hale getirildi.
- **[Çözüldü] Modern Paketleme (PEP 621) Geçişi:** Projenin tüm temel bağımlılıkları `requirements.txt` standardından `pyproject.toml` içindeki `dependencies` dizisine aktarılarak PEP 621 standardına tam uyum sağlandı. Ağır kütüphaneler (GPU, RAG, Telemetri) `optional-dependencies` altına alınarak kurulum profilleri hafifletildi.
- **[Çözüldü] RAG / `DocumentStore` Senkron Blokajı:** Vektör arama işlemleri asenkron yürütme desenine geçirildi.
- **[Çözüldü] API İmzası Kalıntıları:** Bellek başlatıcısı (`ConversationMemory`) modern veritabanı URL mimarisine uyarlandı.
- **[Çözüldü] Geriye Dönük Uyumluluk (isawaitable) Karmaşası:** Tüm ajan metotları asenkron standartlara (`async/await`) bağlandı.
- **[Çözüldü] Event Loop Blokajı ve Zombie Süreç Koruması:** I/O sızıntıları engellendi, alt süreç (child process) sonlandırmaları güvenlik altına alındı.
- **[Çözüldü] PBKDF2 Iterasyon Sayısı:** `core/db.py` satır 60'ta OWASP uyumlu 600.000 iterasyon kullanılmaktadır. Eski sürümde 120.000 olan değer güncellendi; `secrets.compare_digest` ile sabit-zamanlı karşılaştırma da aktif.
- **[Çözüldü] Test Kapsama ve Skip Temizliği:** Legacy/skip test yükü temizlendi, kritik dallar kapsamaya alındı ve kapsama kalite kapısı depo genelinde 99.9'a sabitlendi.
- **[Çözüldü] Legacy Web UI → React SPA Geçişi:** `web_ui_react/` Vite + React tabanlı canlı arayüz üretime alındı; `web_server.py` statik servisleme katmanı React build varsa yeni SPA'yı önceliklendirerek geriye dönük uyumlulukla çalışır hale getirildi.
- **[Çözüldü] Temel Yetki Kontrolünden Tenant-Policy RBAC'a Geçiş:** `access_policy_middleware`, `_resolve_policy_from_request` ve `/admin/policies` uç noktalarıyla tenant/policy bazlı ince taneli erişim denetimi aktif edilerek yetkilendirme modeli derinleştirildi.

### 11.5 Gelecek İyileştirmeler (Continuous Improvement)
Projede kritik borç kalmamakla birlikte, gelecekteki ölçeklenme için şu vizyon maddeleri takip edilecektir:
- **Gelişmiş Telemetri Görselleştirmesi:** Grafana dashboard'larına (`sidar-llm-overview.json`) ajanlar arası delegasyon sürelerinin daha detaylı kırılımlarının eklenmesi.
- **✅ [ÇÖZÜLDÜ — FAZ-3-3] Veritabanı Yük Testleri:** PostgreSQL bağlantı havuzu stres testleri `pg-stress` CI job'ı olarak otomatikleştirildi (`ci.yml`). PostgreSQL 16 service container, Alembic migration ve `pg_stress` marker'lı testler GitHub Actions üzerinde çalışır.
- **✅ [ÇÖZÜLDÜ — FAZ-3-3] `pytest-asyncio` Geçişi:** `conftest.py` deprecated `event_loop` fixture override kaldırıldı; `pytest.ini`'ye `asyncio_default_fixture_loop_scope = session` eklendi. Standart `pytest-asyncio` mimarisine tam geçiş tamamlandı.
- **✅ [ÇÖZÜLDÜ — FAZ-3-1] Pydantic Model Geçişi Kalıntıları:** `web_server.py` `/auth/register` ve `/auth/login` endpoint'lerindeki `hasattr(...)` + `payload.get(...)` dead-code desenleri kaldırıldı; `payload.username` / `payload.password` alanlarına doğrudan erişime geçildi.

### 11.6 2026-03-16 v3.0.6 Doğrulama Turu — Operasyonel Uyumsuzluklar (Kapatıldı)

> **Güncelleme (v3.0.8 — 2026-03-16):** Bu turda tespit edilen her iki bulgu da giderilmiştir.
> Kök neden analizi ve uygulanan düzeltmeler aşağıda belgelenmiştir.

v3.0.6 doğrulama turunda v3.0.4/v3.0.5 bulguları yeniden kod seviyesinde gözden geçirilmiştir.
K-1/K-2 ve YN serisi (YN-K-1, YN-Y-1..Y-3, YN-O-1) düzeltmeleri kodda korunmaktadır.
Bununla birlikte bu turda, çözümün kendisinden bağımsız olarak test/operasyon katmanında iki yeni
uyumsuzluk tespit edilmiştir.

#### ✅ YN2-Y-1 — Kapatıldı

| # | Dosya | Satır | Bulgu | Durum |
|---|-------|-------|-------|-------|
| YN2-Y-1 | `.github/workflows/ci.yml` | `22-24` | **Async test altyapısı bağımlılık uyumsuzluğu** | ✅ ÇÖZÜLDÜ |

**Kök neden:** `ci.yml` `Install dependencies` adımı `pip install -r requirements.txt` + `pip install -r requirements-dev.txt` ikilisini çalıştırıyordu. Ancak `requirements.txt` diskte **mevcut değildi**; bu nedenle CI kurulum adımı hata veriyor, `pytest-asyncio` hiç yüklenmiyordu. `pytest.ini:4` `asyncio_mode = auto` ayarı aktif olduğu hâlde plugin eksik kalıyordu.

**Uygulanan düzeltme:** `.github/workflows/ci.yml` satır 22'deki `pip install -r requirements.txt` satırı kaldırıldı. `requirements-dev.txt` zaten `-e .[rag,postgres,telemetry,dev]` komutuyla `pyproject.toml[dev]` extras'ındaki `pytest-asyncio>=0.23.0` dahil tüm bağımlılıkları yükler.

**Doğrulama:** `requirements-dev.txt:3` → `-e .[rag,postgres,telemetry,dev]` · `pyproject.toml:40` → `”pytest-asyncio>=0.23.0”` dev extras'ında.

#### ✅ YN2-O-1 — Kapatıldı

| # | Dosya | Satır | Bulgu | Durum |
|---|-------|-------|-------|-------|
| YN2-O-1 | `tests/test_code_manager_runtime.py` | `280-285` | **Test beklentisi / üretim davranışı drift'i (Docker socket fallback)** | ✅ ÇÖZÜLDÜ |

**Kök neden analizi:** Üretim kodu (`managers/code_manager.py:181`) WSL2 socket fallback akışında `stat.S_ISSOCK(file_stat.st_mode)` ile socket türü doğrulaması yapıyor. Raporda testin bu doğrulamayı mock'lamadığı belirtilmişti; ancak test dosyasının satır satır incelenmesi sorunun zaten giderildiğini ortaya koydu.

**Mevcut kod (çözüm):** `tests/test_code_manager_runtime.py:281-285`
```python
class _FakeStatResult:
    st_mode = 0

monkeypatch.setattr(os, “stat”, lambda _path: _FakeStatResult())
monkeypatch.setattr(stat, “S_ISSOCK”, lambda _mode: True)
```
`os.stat()` her çağrıda `st_mode=0` döndüren sahte nesne üretir; `stat.S_ISSOCK()` her zaman `True` döndürür. Fallback akışı deterministik biçimde `docker_available = True` ile sonuçlanır. Rapor, zaten uygulanmış olan bu mock'ları kaçırmıştı.

#### v3.0.6 Test ve Doğrulama Notu (Güncel)

* `bash scripts/collect_repo_metrics.sh` başarılı.
* **YN2-Y-1 giderildi:** `ci.yml` artık yalnızca `requirements-dev.txt` kurulumunu çalıştırır; `pytest-asyncio` CI ortamında güvenilir biçimde yüklenir.
* **YN2-O-1 giderildi:** `test_code_manager_runtime.py` socket mock'ları doğrulandı; test deterministik.

---

### 11.7 2026-03-16 v3.0.7/v3.0.9 Doğrulama Turu — Yeni Bulgular ve Kapatma Durumu

> **Güncelleme (v3.0.9 — 2026-03-16):** Bu turda tespit edilen 6 bulgunun tamamı giderilmiştir.
> YN3-O-4 yanlış pozitif olarak teyit edilmiştir.

#### ✅ v3.0.6 Bulgu Kapatma Durumu

| # | Önceki Durum | Güncel Durum | Açıklama |
|---|-------------|-------------|----------|
| YN2-Y-1 | 🟠 AÇIK | ✅ ÇÖZÜLDÜ | `ci.yml` `pip install -r requirements.txt` satırı kaldırıldı (dosya mevcut değildi). |
| YN2-O-1 | 🟡 AÇIK | ✅ ÇÖZÜLDÜ | `test_code_manager_runtime.py:281-285` mock'ları zaten mevcuttu; doğrulandı. |

#### ✅ YN3 Serisi — Kapatma Durumu (v3.0.9)

| # | Eski Durum | Güncel Durum | Uygulanan Düzeltme |
|---|-----------|-------------|-------------------|
| YN3-O-4 | 🟠 Orta | ✅ YANLIŞ POZİTİF | `_load_instruction_files` sync metot — `asyncio.to_thread()` ile çağrılıyor. Thread pool'da `threading.Lock()` kullanımı **doğru** pattern. `asyncio.Lock()` thread-safe değildir. Değişiklik gerekmez. |
| YN3-O-1 | 🟡 Orta | ✅ ÇÖZÜLDÜ | `_ANYIO_CLOSED` WebSocket handler'ın dış `except` blokuna eklendi (`web_server.py`). `anyio.ClosedResourceError` artık `WebSocketDisconnect` gibi normal çıkış olarak işleniyor. |
| YN3-O-2 | 🟡 Orta | ✅ ÇÖZÜLDÜ | `_rate_lock` dead code kaldırıldı (`web_server.py:467`). Test dosyalarında (`test_targeted_coverage_additions.py`, `test_sidar.py`) `_rate_lock` → `_local_rate_lock` güncellendi; artık asıl production kilidi sıfırlanıyor. |
| YN3-O-3 | 🟡 Orta | ✅ ÇÖZÜLDÜ (FAZ-3-1) | `isinstance(payload, dict)` dalları önceden kaldırılmıştı; kalan `hasattr(...)` + `payload.get(...)` dead-code desenleri de temizlendi. `/auth/register` ve `/auth/login` endpoint'lerinde artık doğrudan `payload.username` / `payload.password` erişimi kullanılıyor. |
| YN3-D-1 | 🟡 Düşük | ✅ ÇÖZÜLDÜ | `_get_jwt_secret()` yardımcı fonksiyonu eklendi. `JWT_SECRET_KEY` boşsa `logger.critical(...)` ile uyarı verilir; `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_TTL_DAYS` `config.py`'ye taşındı. `.env.example`'a dokümantasyon eklendi. |
| YN3-D-2 | 🟡 Düşük | ✅ ÇÖZÜLDÜ | `GRAFANA_URL` `config.py`'ye eklendi. `index()` route'u `window.__SIDAR_CONFIG__.grafanaUrl` değerini `<head>` içine inject ediyor. `index.html:286` butonu artık bu değeri kullanıyor; `.env.example`'a dokümantasyon eklendi. |

#### v3.0.9 Değişen Dosyalar

| Dosya | Değişiklik |
|-------|-----------|
| `config.py` | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_TTL_DAYS`, `GRAFANA_URL` eklendi |
| `web_server.py` | `_get_jwt_secret()` eklendi; `_rate_lock` kaldırıldı; `isinstance` dalları kaldırıldı; WS handler `_ANYIO_CLOSED` exception bloğu eklendi; `index()` Grafana URL inject ediyor |
| `web_ui/index.html` | Grafana butonu `window.__SIDAR_CONFIG__.grafanaUrl` kullanıyor |
| `tests/test_targeted_coverage_additions.py` | `_rate_lock` → `_local_rate_lock` (3 yerde) |
| `tests/test_sidar.py` | `_rate_lock` → `_local_rate_lock` (3 yerde) |
| `.env.example` | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_TTL_DAYS`, `GRAFANA_URL` belgelendi |

---

## 12. `.env` Tam Değişken Referansı (v4.3.0 Kurumsal Sürüm)

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

> **RAG notu:** Güncel yapılandırmada ayrı bir `CHROMADB_PATH` değişkeni yoktur; Chroma tarafı `RAG_DIR` ve belge deposu düzeni üzerinden yönetilir. `DATABASE_URL` ve şema versiyon anahtarları ise çalışma zamanında desteklenir; ancak bunların tamamı `.env.example` içinde hazır satır olarak bulunmayabilir.

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
| `DOCKER_RUNTIME` / `DOCKER_ALLOWED_RUNTIMES` / `DOCKER_MICROVM_MODE` | `""` / `,runc,runsc,kata-runtime` / `off` | Zero-trust sandbox runtime ve mikro-VM hazırlık seçenekleri (`DOCKER_MICROVM_MODE` şu anda `config.py` destekli olup `.env.example` şablonunda ayrıca listelenmemektedir) |
| `DOCKER_MEM_LIMIT` / `DOCKER_NETWORK_DISABLED` / `DOCKER_NANO_CPUS` | `256m` / `true` / `1000000000` | Sandbox konteyner kaynak kısıtları (`DOCKER_MEM_LIMIT` şu anda `config.py` destekli olup `.env.example` şablonunda ayrıca listelenmemektedir) |
| `SANDBOX_MEMORY` / `SANDBOX_CPUS` / `SANDBOX_NETWORK` / `SANDBOX_PIDS_LIMIT` / `SANDBOX_TIMEOUT` | `256m` / `0.5` / `none` / `64` / `10` | `config.py::SANDBOX_LIMITS` sözlüğüne beslenen detaylı çalışma kotaları |
| `WEB_HOST` / `WEB_PORT` / `WEB_GPU_PORT` | `0.0.0.0` / `7860` / `7861` | Web sunucusunun bind adresi ve portları |
| `HF_TOKEN` / `HF_HUB_OFFLINE` | `""` / `0/false` | HuggingFace model erişimi ve offline cache davranışı |
| `JUDGE_ENABLED` / `JUDGE_MODEL` / `JUDGE_PROVIDER` / `JUDGE_SAMPLE_RATE` | `false` / `""` / `ollama` / `0.2` | LLM-as-a-Judge kalite değerlendirme hattı |
| `ENABLE_COST_ROUTING` ve `COST_ROUTING_*` | `false` / eşik ve model varsayılanları | Basit/karmaşık sorgular için maliyet odaklı model yönlendirmesi |
| `ENABLE_ENTITY_MEMORY` / `ENTITY_MEMORY_TTL_DAYS` / `ENTITY_MEMORY_MAX_PER_USER` | `true` / `90` / `100` | Entity/persona memory kalıcılığı |
| `ENABLE_ACTIVE_LEARNING`, `AL_MIN_RATING_FOR_TRAIN`, `ENABLE_LORA_TRAINING`, `LORA_*` | çeşitli | Geri bildirim toplama ve LoRA/QLoRA fine-tuning hazırlıkları |
| `ENABLE_VISION` / `VISION_MAX_IMAGE_BYTES` | `true` / `10485760` | Çok modlu görsel girdi yetenekleri |

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
- **CI/CD ile korunan sıfır borç disiplini:** Kapsama hard gate'i `%99.9` olarak kodlanmış olsa da, repo kültürü fiilî tam kapsama hedefiyle yürür; test, audit ve metrik betikleri artık takip dışı dosyaları saymadan gerçek repo ölçümleri üzerinden kalite kapısı üretir.
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

> **Yön belirleyici ilke:** v5.x serisi, mevcut enterprise omurgayı koruyarak Sidar'ı daha güçlü akıl yürütme, dağıtık çalışma, sürekli öğrenme ve gerçek zamanlı çoklu modalite eksenlerinde ileri taşıyan Faz 6 yol haritasıdır.

### 14.1 GraphRAG ve Bilgi Grafikleri (Knowledge Graphs)

- Mevcut `pgvector` + BM25 + keyword hibrit aramasına, varlıklar ve ilişkiler arasındaki bağlantıları modelleyen **graph tabanlı bellek katmanı** eklenecektir.
- Bu katman; entity memory, prompt registry ve RAG akışlarını yalnızca benzerlik aramasıyla değil, **ilişki/topoloji tabanlı çıkarım** ile zenginleştirecektir.
- Olası teknoloji yönü; Neo4j benzeri bir grafik veri katmanı veya PostgreSQL üzerinde graph-benzeri ilişki indeksleriyle hibrit yaklaşım kurulmasıdır.
- Beklenen kazanım: çok adımlı reasoning, kurumsal bilgi keşfi ve belge/kişi/sistem bağıntılarının daha doğru modellenmesi.

### 14.2 Dağıtık Sürü Orkestrasyonu (Distributed Swarm via Message Brokers)

- Bugünkü Supervisor + Swarm akışı tek bir Python runtime içinde güçlü biçimde çalışsa da, Faz 6 hedefi ajanların bağımsız worker servislerine ayrılmasıdır.
- Uzman ajanların Kafka, RabbitMQ veya benzeri broker'lar üzerinden haberleşen **ayrı mikroservis/pod** yapısına taşınması planlanmaktadır.
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

> **Sonuç:** v4.x serisi Sidar'ın enterprise temelini tamamlamıştır; v5.x/Faz 6 ise bu temelin üstüne **daha derin akıl yürütme, daha dağıtık yürütme, daha güçlü öğrenme ve daha doğal insan-makine etkileşimi** katmanlarını eklemeyi hedeflemektedir.

---
## 15. Özellik-Gereksinim Matrisi (v4.3.0 Güncel Durum)

[⬆ İçindekilere Dön](#içindekiler)

Aşağıdaki matris, sistemin sahip olduğu kurumsal yeteneklerin hangi teknik gereksinimler ve modüller ile karşılandığını haritalandırmaktadır. Bu bölüm artık erken dönem RAG/LLM çekirdeğini değil, v4.3.0 itibarıyla **enterprise + swarm + observability** yüzeyini özetler.

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
| **Sıfır Borç Kalite Kapısı** | Agresif test envanteri, CI kalite kapıları ve `%99.9` coverage hard gate (`.github/workflows/ci.yml`, `run_tests.sh`, `.coveragerc`, `tests/`) | ✅ Tamamlandı |
| **Varlık Belleği (Entity Memory)** | Persona/ilişki odaklı kalıcı kullanıcı belleği (`core/entity_memory.py`, `web_server.py`) | ✅ Tamamlandı |
| **Prompt Registry ve Yönetim Denetimi** | DB tabanlı prompt versiyonlama ve admin paneli (`migrations/versions/0002_prompt_registry.py`, `web_server.py`, `web_ui_react/src/components/PromptAdminPanel.jsx`) | ✅ Tamamlandı |

> **Not:** Kullanıcı isteğinde geçen “%100 Test Kapsaması” ifadesi repo kültürünün hedefini yansıtsa da, kod tabanında **resmî kalite kapısı** `.coveragerc` ve CI üzerinde `%99.9` olarak uygulanmaktadır; raporda bu nedenle doğrudan ölçülebilir kural esas alınmıştır.

---
## 16. Hata Yönetimi ve Loglama Stratejisi

[⬆ İçindekilere Dön](#içindekiler)

### 16.1 Hata Yönetimi Kalıpları

Kod tabanı boyunca dört farklı hata yönetimi deseni kullanılmaktadır:

**1. Tuple Dönüş Deseni** (`Tuple[bool, str]`)
Araçların ve manager metodlarının büyük çoğunluğu `(başarı, mesaj)` tuple'ı döndürür. İstisna dışarıya sızmaz; hata durumu dönüş değerinden okunur. Bu, ReAct döngüsünün araç hatasını kolayca işlemesini sağlar.
```
(True, "sonuç metni")   → başarı
(False, "hata mesajı")  → hata
```
Kullanım yeri: `CodeManager`, `GitHubManager`, `WebSearchManager`, `DocumentStore`, `TodoManager`

**2. Loglama + Sessiz Fallback**
Opsiyonel bağımlılıklar (ChromaDB, BM25, psutil, pynvml, torch) yüklenemezse sistem çökmez; `logger.warning` ile kayıt alınır ve bir sonraki motora/moda geçilir.
```
ChromaDB başlatılamadı → _chroma_available = False → BM25'e düş
BM25 yok              → _bm25_available = False   → Keyword'e düş
```
Kullanım yeri: `DocumentStore.__init__`, `SystemHealthManager.__init__`

**3. Fail-Closed Güvenlik Deseni**
Güvenlik kararlarında belirsizlik varsa operasyon reddedilir. Erişim seviyesi tanımsızsa `sandbox`'a normalize edilir. Fernet anahtarı geçersizse `ValueError` ile sistem başlatılmaz.
```
bilinmeyen seviye → sandbox (daha kısıtlayıcı)
geçersiz şifreleme anahtarı → ValueError, sistem durur
```
Kullanım yeri: `SecurityManager`, `ConversationMemory`

**4. Unified LLM API Hata Sarmalama Deseni**
`core/llm_client.py`, sağlayıcıya özgü hataları (ör. `401 AuthenticationError`, `429 RateLimitError`, `ConnectionTimeout`) tek tip bir hata sözleşmesine (örn. `LLMAPIError`) dönüştürerek üst katmanlara iletir. Böylece kullanıcı mesajları ve log kayıtları OpenAI, Anthropic, Gemini ve Ollama için tutarlı kalır.

Kullanım yeri: `core/llm_client.py`, `agent/sidar_agent.py`, `web_server.py`

### 16.2 Loglama Stratejisi

| Seviye | Ne Zaman Kullanılır | Örnekler |
|--------|--------------------|---------|
| `DEBUG` | Geliştirici detayları, başarılı rutin işlemler | Dizin hazır, VRAM fraksiyon atlandı |
| `INFO` | Başarılı sistem olayları | GPU aktif, ChromaDB başlatıldı, belge eklendi |
| `WARNING` | Düşürülmüş modda çalışma, eksik opsiyonel bağımlılık | PyTorch yok, Ollama'ya ulaşılamadı |
| `ERROR` | Başarısız operasyon, kullanıcıya görünür hata | Dizin oluşturulamadı, ChromaDB hatası, geçersiz API key |

**Logger İsimlendirme Tutarlılığı:**
- `config.py` → `Sidar.Config`
- Diğer tüm modüller → `logging.getLogger(__name__)` (modül adı)

**RotatingFileHandler:** 10 MB / 5 yedek, UTF-8 — Türkçe log mesajları güvenle yazılır.

**Ajan Bazlı Bağlam (Contextual Logging):** Multi-Agent akışında log satırlarına ajan bağlamı (`[Supervisor]`, `[CoderAgent]`, `[ResearcherAgent]`) eklenerek hatanın hangi orkestrasyon adımında üretildiği izlenebilir hale getirilir.

### 16.3 Asenkron Hata Yönetimi

`AutoHandle` içindeki her araç çağrısı `asyncio.wait_for()` ile `AUTO_HANDLE_TIMEOUT` (12 sn) içine alınmıştır. `TimeoutError` yakalanarak kullanıcıya anlamlı mesaj döndürülür; event loop bloklanmaz.

ReAct döngüsünde araç exception'ı `_FMT_TOOL_ERR` formatına sarılarak belleğe yazılır ve LLM'e iletilir. LLM bir sonraki adımda farklı strateji deneyebilir.

**Döngü ve Limit Koruması (Graceful Degradation):** ReAct/Multi-Agent adımlarında `MAX_REACT_STEPS` sınırına ulaşıldığında döngü kontrollü şekilde sonlandırılır; sistem sonsuz döngüye girmek yerine o ana kadar toplanan kısmi sonucu ve açıklayıcı hata/uyarı bağlamını kullanıcıya döndürür.

### 16.4 Bozuk Veri Karantinası

`ConversationMemory` JSON okuma hatası veya şifre çözme başarısızlığı durumunda dosyayı `.json.broken` uzantısıyla yeniden adlandırır ve temiz bir oturum başlatır. 7 günden eski `.broken` dosyaları (en fazla 50 tutulur) otomatik temizlenir. Bu mekanizma disk üzerindeki kalıcı veri bozulmasının sistemi tamamen durdurmasını önler.

---

## 17. Yaygın Sorunlar ve Çözümleri

[⬆ İçindekilere Dön](#içindekiler)

Kodun incelenmesinden türetilen, gerçek kullanıcı senaryolarında karşılaşılması muhtemel sorunlar ve kodu okuyarak tespit edilen kökenleri.

### 17.1 Ollama Bağlantı Sorunları

**Belirti:** `⚠️ Ollama'ya ulaşılamadı` uyarısı; LLM yanıt vermiyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| `ollama serve` çalışmıyor | `config.py:437` httpx bağlantı hatası | `ollama serve` komutunu çalıştır |
| `OLLAMA_URL` yanlış | `.env` veya varsayılan `http://localhost:11434/api` | URL'yi kontrol et, `/api` son ekini dahil et |
| Timeout çok kısa | `OLLAMA_TIMEOUT=30` büyük modelde yetersiz | `.env`'de `OLLAMA_TIMEOUT=120` yap |
| Model adı hatalı | `CODING_MODEL` / `TEXT_MODEL` | `ollama list` ile mevcut modelleri kontrol et |

### 17.2 GPU / CUDA Sorunları

**Belirti:** `CUDA bulunamadı — CPU modunda çalışılacak` veya embedding çok yavaş.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| PyTorch CUDA wheel kurulmamış | `config.py:174` | `pip install torch --index-url https://download.pytorch.org/whl/cu124` |
| WSL2 + Windows sürücüsü eski | `config.py:130-131` WSL2 tespiti | NVIDIA Windows sürücüsünü güncelle |
| `USE_GPU=false` ayarı | `config.py:133` | `.env`'de `USE_GPU=true` yap |
| `GPU_MEMORY_FRACTION` aralık dışı | `config.py:151-157` | 0.1–0.99 arasında değer ver (1.0 dahil değil) |

### 17.3 ChromaDB / RAG Sorunları

**Belirti:** Vektör arama çalışmıyor; `BM25'e düşülüyor` logu.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| `chromadb` kurulmamış | `rag.py:129` import kontrolü | `pip install chromadb` |
| `sentence-transformers` yok | `rag.py:46` GPU embedding başlatma | `pip install sentence-transformers` |
| `all-MiniLM-L6-v2` indirilmemiş | İlk belgede uzun bekleme | `PRECACHE_RAG_MODEL=true` ile Docker build, veya `HF_HUB_OFFLINE=false` |
| ChromaDB versiyon uyumsuzluğu | `rag.py:201` başlatma hatası | `pip install chromadb --upgrade` |
| `chunk_size < chunk_overlap` | `rag.py:246` mantık hatası | `RAG_CHUNK_OVERLAP < RAG_CHUNK_SIZE` olduğundan emin ol |

### 17.4 Docker REPL Sorunları

**Belirti:** `execute_code` çalışmıyor; subprocess fallback devreye giriyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| Docker daemon çalışmıyor | `code_manager.py:_init_docker` | `docker ps` ile kontrol et, daemon'ı başlat |
| WSL2 socket yolu hatalı | `code_manager.py` WSL2 socket fallback | Docker Desktop'ı kur veya `DOCKER_HOST` ayarla |
| `python:3.11-alpine` imajı yok | İlk çalıştırmada uzun bekleme | `docker pull python:3.11-alpine` önceden çek |
| Zaman aşımı çok kısa | `DOCKER_EXEC_TIMEOUT=10` | Uzun hesaplamalar için artır |
| `ACCESS_LEVEL=restricted` | `security.py` erişim kontrolü | Seviyeyi `sandbox` veya `full` yap |

### 17.5 Bellek / Şifreleme Sorunları

**Belirti:** `ValueError: MEMORY_ENCRYPTION_KEY geçersiz` veya oturum yüklenemiyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| Geçersiz Fernet anahtarı | `config.py:411-420` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` ile yeni anahtar üret |
| `cryptography` kurulmamış | `config.py:421-427` | `pip install cryptography` |
| Eski şifresiz dosyalar | `memory.py` geçiş modu | Eski oturumlar `.broken` olarak işaretlenir; veri kaybı riski — yedekle |
| `data/sessions/` izin sorunu | `memory.py` write hatası | Dizin yazma izinlerini kontrol et |

### 17.6 GitHub Entegrasyon Sorunları

**Belirti:** `⚠ GitHub token ayarlanmamış` veya repo bulunamadı.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| `GITHUB_TOKEN` boş | `github_manager.py:61` | GitHub Settings → Developer settings → Personal access tokens |
| Token yetkileri yetersiz | PyGithub 403 hatası | Token'a `repo`, `read:org` scopelarını ekle |
| `GITHUB_REPO` formatı hatalı | `github_manager.py:80` | `owner/repo-name` formatında yaz |
| Binary dosya okuma girişimi | `github_manager.py:33` whitelist | Yalnızca metin uzantılı dosyalar okunabilir |
| Commit limiti aşıldı | `github_manager.py:296` | Maksimum 30 commit; daha fazlası sessizce kesilir |

### 17.7 Web Sunucu Sorunları

**Belirti:** Rate limit hatası, CORS hatası veya WebSocket bağlantısı kopuyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| Rate limit aşıldı | `web_server.py:83` | `RATE_LIMIT_CHAT` değerini artır veya sunucuyu yeniden başlat |
| CORS reddedildi | `web_server.py:66` | Yalnızca localhost kökeninden erişilebilir; proxy için CORS origins güncelle |
| Port kullanımda | `uvicorn` bind hatası | `WEB_PORT` farklı bir değere ayarla |
| WebSocket bağlantısı kopuyor | Ağ/proxy kesintisi veya backend restart | İstemci tarafı otomatik yeniden bağlanma mantığı kullan |

### 17.8 `.env` Dosyası Sorunları

**Belirti:** `⚠️ '.env' dosyası bulunamadı! Varsayılan ayarlar kullanılacak.`

| Olası Neden | Çözüm |
|-------------|-------|
| `.env` dosyası yok | `.env.example`'ı kopyala: `cp .env.example .env` |
| `.env` proje kökünde değil | `config.py:28` `BASE_DIR / ".env"` yolunu kullanır — dosyayı proje köküne taşı |
| Boolean değer yanlış formatda | `get_bool_env` yalnızca `true/1/yes/on` kabul eder (büyük-küçük harf bağımsız) |

### 17.9 Bulut LLM 429 (Rate Limit) Hatası

**Belirti:** OpenAI/Anthropic kullanımında istekler aniden `429 Too Many Requests` veya `RateLimitError` ile kesiliyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| Free tier / düşük RPM limiti aşıldı | `core/llm_client.py` çağrılarında 429/RateLimit uyarıları | API hesabı kredi/kota durumunu kontrol et; bekleme penceresi sonrası yeniden dene |
| Yoğun paralel istek yükü | Aynı oturumda kısa sürede çok sayıda sağlayıcı çağrısı | İstek yoğunluğunu azalt, yeniden deneme/backoff uygula, gerekirse daha yüksek kota planına geç |
| Sağlayıcı geçici kısıtlama | Belirli zaman aralığında düzenli 429 dalgaları | Geçici olarak farklı sağlayıcıya geç (`AI_PROVIDER=ollama`) veya retry stratejisi uygula |

### 17.10 Ajan Döngüsü / JSON Parse Hataları

**Belirti:** Özellikle yerel Ollama ile ajan aynı aracı tekrar çağırıyor veya `JSONDecodeError` / `ValidationError` üretiyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| Model structured output talimatını zayıf takip ediyor | ReAct adımlarında bozuk JSON, eksik `thought/tool/argument` alanları | JSON uyumu güçlü modeller kullan (`llama3.1`, `qwen2.5` vb.) |
| Model / sıcaklık kombinasyonu kararsız | Aynı girdide tutarsız/bozuk tool çağrıları | Daha stabil model seç; gerekirse bulut sağlayıcıya geç (`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`) |
| Araç argümanı format uyumsuzluğu | Pydantic doğrulama hataları (`ValidationError`) | `tooling.py` şema beklentilerine uygun argüman formatı kullan; promptu sadeleştir |

### 17.11 Supervisor Devreye Girmiyor (Tekli Ajan Davranışı)

**Belirti:** Coder/Researcher rol çağrıları beklenirken Supervisor izleri net görünmüyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| Günlük/izleme seviyesi yetersiz | Supervisor adımları loglarda görünmüyor | `LOG_LEVEL=DEBUG` ile yeniden çalıştır; `SupervisorAgent` izlerini doğrula |
| Süreç yeniden başlatılmadı | Konfigürasyon değişikliği sonrası davranış netleşmiyor | Uygulamayı tamamen yeniden başlat (CLI/Web server) |
| Yanlış ortam dosyası yükleniyor | `SIDAR_ENV` profili beklenenden farklı | Etkin `.env.<profile>` dosyasını ve `SIDAR_ENV` değerini kontrol et |

> **Not:** Güncel mimaride `ENABLE_MULTI_AGENT` bayrağı kod içinde sabitlenmiştir (`True`); legacy tekli ajan akışına `.env` üzerinden dönüş desteklenmez.

---

## 18. Geliştirme Geçmişi ve Final Doğrulama Raporu

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, v3.0 final sürümü öncesi yapılan tüm audit ve doğrulama seanslarının özetidir.

- **Final Doğrulama Tarihi:** 2026-03-19 (Güncel — v3.0.30)
- **Durum:** Kurumsal özellikler (Auth, Multi-User, Sandbox, Observability, Plugin Marketplace, Tenant RBAC) kod ve test düzeyinde yeniden doğrulanmıştır. v3.0.30 turunda üretim Python satır sayısı **19.554**, takipli toplam Python **53.675** ve test satırı **34.121** olarak yeniden ölçülmüş; kök giriş dosyaları ile D-8..D-14 kapanışını sağlayan çekirdek modüller (`core/entity_memory.py`, `core/cache_metrics.py`, `core/judge.py`, `core/vision.py`, `core/active_learning.py`, `core/hitl.py`, `core/llm_client.py`, `web_server.py`) satır satır incelenmiştir. Aktif açık bulgu kalmamıştır; güvenlik/operasyon puanı **10.0/10** olarak güncellenmiştir.

| Denetim Sürümü | Tarih | Özet |
|---|---|---|
| v3.0.1 | 2026-03-14 | İlk kapsamlı audit; PBKDF2 iterasyon eksikliği, event-loop blokaj riski, zombie process riski tespit edildi |
| v3.0.2 | 2026-03-15 | PBKDF2 600K doğrulandı; RAG async geçişi, multi-agent test kapsaması genişletildi |
| v3.0.3 | 2026-03-15 | Child-process sonlandırma güvenliği, OpenTelemetry async context sızıntı riski doğrulandı |
| v3.0.4 | 2026-03-16 | Test kapsama %100, 33 legacy skip testi temizlendi, kapsama kalite kapısı %99.9, kaynak dosya satır sayıları yeniden ölçüldü, 8 yeni güvenlik/işlevsellik bulgusu (K-1, K-2, Y-1..Y-5, O-1..O-7, D-1..D-6) kayıt altına alındı |
| **v3.0.5** | **2026-03-16** | **v3.0.4 bulgularının tamamı (K-1..K-2, Y-1..Y-5, O-1..O-7, D-1..D-6) doğrulandı/çözüldü; 3 yanlış pozitif (K-2, Y-4, O-2, D-4) teyit edildi; 5 yeni bulgu tespit edildi: YN-K-1 (rag.py _TEXT_EXTS bypass), YN-Y-1 (sidar_agent _lock lazy init), YN-Y-2 (SSRF in add_document_from_url), YN-Y-3 (github_manager .env izin), YN-O-1 (auth endpoint Pydantic eksik)** |
| **v3.0.6** | **2026-03-16** | **Doğrulama turunda önceki K/Y/O/D + YN bulguları tekrar teyit edildi; test/operasyon katmanında iki yeni uyumsuzluk kayıt altına alındı: YN2-Y-1 (async test plugin bağımlılık uyumsuzluğu), YN2-O-1 (Docker socket fallback test beklenti drift'i).** |
| **v3.0.7** | **2026-03-16** | **Tüm kaynak dosyalar yeniden satır satır incelendi. YN2-O-1 çözüldü (mock doğrulandı). YN2-Y-1 hâlâ açık. 6 yeni bulgu tespit edildi: YN3-O-4 (threading.Lock async bağlam), YN3-O-1 (_ANYIO_CLOSED dead code), YN3-O-2 (_rate_data/_rate_lock dead code), YN3-O-3 (isinstance dict redundant check), YN3-D-1 (JWT hardcoded fallback), YN3-D-2 (Grafana URL hardcoded).** |
| **v3.0.8** | **2026-03-16** | **YN2-Y-1 giderildi: `.github/workflows/ci.yml` `pip install -r requirements.txt` satırı kaldırıldı (dosya mevcut değildi); `requirements-dev.txt` tek kurulum kaynağı olarak bırakıldı. §11.3 her iki bulgu kapatıldı.** |
| **v3.0.9** | **2026-03-16** | **YN3 serisi (6 bulgu) kapatıldı: YN3-O-4 yanlış pozitif; YN3-O-1 (_ANYIO_CLOSED WS handler); YN3-O-2 (_rate_lock dead code + test düzeltmesi); YN3-O-3 (isinstance redundant); YN3-D-1 (JWT_SECRET_KEY config + uyarı); YN3-D-2 (Grafana URL dinamik injection). config.py, web_server.py, index.html, .env.example, 2 test dosyası güncellendi.** |
| **v3.0.10** | **2026-03-16** | **Kapsamlı yeniden denetim: tüm proje dosyaları satır satır incelendi. Doğrulanan ve güncellenen alanlar: Python kaynak 12.727 → 13.502 satır; test modülü 103 → 106; test satırı 21.290 → 21.552; web_server.py 1.406 → 1.568; core/llm_client.py 961 → 1.235; core/rag.py 810 → 1.057; core/db.py 1.012 → 1.353; config.py 607 → 722; event_stream.py 45 → 189. §2 dosya yapısına helm/, docs/module-notes/, AUDIT_REPORT_v4.0.md, 0002_prompt_registry.py eklendi; requirements.txt referansı (diskte yok) kaldırıldı. §12.4'e JWT_SECRET_KEY/JWT_ALGORITHM/JWT_TTL_DAYS/GRAFANA_URL eklendi. §13 Helm tamamlandı olarak işaretlendi. §15.7'ye Helm ve Prompt Registry satırları eklendi. §7 Auth notu PyJWT gerçeğini yansıtacak şekilde düzeltildi.** |
| **v3.0.11** | **2026-03-16** | **§13 v4.0 Kurumsal Yol Haritası iyileştirmeleri gerçekleştirildi: (1) OTel span enstrümantasyonu OpenAI ve LiteLLM sağlayıcılarına eklendi (tüm 5 LLM sağlayıcısı artık `sidar.llm.*` attribute'larıyla izleniyor); (2) RAG `search()` katmanına `rag.search` span ile `sidar.rag.*` attribute'ları eklendi; (3) Prompt Registry Admin UI (Yönetim Paneli: tablo, form, etkinleştirme) `index.html` + `app.js` üzerine eklendi; (4) `.env.example` dosyası LiteLLM, Semantic Cache, pgvector, Event Bus, JWT, OTel ve Redis bölümleri ile genişletildi. §13'te Anlamsal Önbellekleme, Dinamik Prompt Yönetimi ve Dağıtık İzlenebilirlik satırları ✅ Tamamlandı olarak güncellendi.** |
| **v3.0.12** | **2026-03-16** | **§13 kalan maddeler hayata geçirildi: (1) Bağımlılık Extras Grupları tamamlandı — `[gemini]`, `[anthropic]`, `[gpu]`, `[sandbox]`, `[gui]`, `[all]` extras eklendi; kullanılmayan `openai` SDK kaldırıldı; `otel-httpx` telemetry'e eklendi; (2) Agent Swarm + Marketplace temeli — `agent/registry.py` (AgentRegistry + @register dekoratörü) ve `agent/swarm.py` (SwarmOrchestrator: parallel/pipeline modları, TaskRouter) hayata geçirildi; (3) React/Vite frontend scaffold — `web_ui_react/` altında useWebSocket hook, useChatStore (Zustand), ChatWindow/ChatMessage/ChatInput/StatusBar bileşenleri; (4) Güvenlik: MEMORY_ENCRYPTION_KEY boşken logger.critical() uyarısı ve Redis rate limit fallback testleri (10 test).** |
| **v3.0.13** | **2026-03-16** | **Uçtan uca doğrulama ve dokümantasyon turu: (1) `plugins/crypto_price_agent.py` — `BaseAgent` türeyen `CryptoPriceAgent` örnek plugin: CoinGecko API üzerinden BTC/ETH/SOL USD fiyat sorgulama, sembol çıkarma regex'i, hata sarmalama (49 satır); (2) `runbooks/plugin_marketplace_demo.md` — plugin dosyası API ile yükleme, `AgentRegistry.create()` ile çağırma adımları curl + Python örnekleriyle belgelendi (32 satır); (3) `runbooks/tenant_rbac_scenarios.md` — tenant_A (rag:read izni) vs tenant_B (rag+swarm tam yetki) senaryoları; `/auth/register`, `/admin/policies`, policy matris curl örnekleri ve beklenen 403 davranışı (66 satır); (4) `runbooks/observability_simulation.md` — Docker Compose stack başlatma, RAG ekleme/arama, LLM+Supervisor tracing tetikleme, Jaeger UI span doğrulama ve temizlik adımları (87 satır); (5) `tests/test_observability_stack_compose.py` — Compose sağlık/endpoint testleri (34 satır); (6) `tests/test_plugin_marketplace_flow.py` — AgentRegistry kayıt, run_task, edge-case testleri (47 satır); (7) `tests/test_tenant_rbac_scenarios.py` — tenant izolasyonu, 403 beklenti ve policy matris doğrulama (132 satır); (8) `docker-compose.yml` 19 satır ek konfigürasyon. Rapor §2/§6/§8/§13 güncellendi; test sayısı 106→109, satır 21.552→21.765, Python kaynak +50 satır (13.502→13.552).** |
| **v3.0.19** | **2026-03-19** | **Roadmap Faz 3 — Agent Ekosistemi entegrasyon turu tamamlandı: (1) React SPA `react-router-dom` ile URL tabanlı navigasyona geçirildi; `App.jsx` sekme-state yapısı kaldırılarak chat/p2p/swarm/admin rotaları eklendi. (2) `PromptAdminPanel.jsx`, `AgentManagerPanel.jsx`, ayrıştırılmış `ChatPanel.jsx`, `P2PDialoguePanel.jsx`, `SwarmFlowPanel.jsx`, `TenantAdminPanel.jsx` bileşenleri oluşturuldu; bearer token araç çubuğu ile admin API entegrasyonu sağlandı. (3) `web_server.py` içine `/api/swarm/execute` endpoint'i, swarm ACL eşlemesi ve sonuç serileştirmesi eklendi. (4) `get_agent()` başlangıcı `SidarAgent.initialize()` üzerinden aktif sistem promptunu DB'den yükleyecek şekilde güçlendirildi. (5) `tests/test_swarm_execute_api.py` ile yeni backend davranışları kapsandı.** |
| **v3.0.18** | **2026-03-18** | **FAZ-6 son bulgu kapatıldı: D-6 core/db.py _run_sqlite_op içindeki erişilemez lazy-lock if/raise bloğu assert ile değiştirildi. TÜM BULGULAR KAPATILDI. Güvenlik puanı 9.6→10.0. Açık bulgu: 0.** |
| **v3.0.17** | **2026-03-18** | **FAZ-5 orta öncelikli güvenlik hardening tamamlandı: O-1..O-6 tüm bulgular kapatıldı. O-2: core/rag.py add_document_from_file Config.BASE_DIR sınır kontrolü. O-3: DOCKER_REQUIRED env bayrağı + kod_manager.py kontrolü + .env.example belgesi. O-6: run_shell shell=True yıkıcı komut blocklist. O-1/O-4/O-5 önceden çözülmüş olarak doğrulandı. tests/test_code_manager_runtime.py _DummyConfig DOCKER_REQUIRED eklendi. Güvenlik puanı 9.2→9.6.** |
| **v3.0.16** | **2026-03-18** | **FAZ-4 yüksek öncelikli güvenlik hardening tamamlandı: Y-1..Y-5 tüm AUDIT_REPORT_v4.0.md bulguları doğrulandı ve kapatıldı. Y-1: set_level_endpoint _require_admin_user (teyit); Y-2: RAG upload 50 MB + HTTP 413 (teyit); Y-3: docs.add_document await (teyit); Y-4: TRUSTED_PROXIES XFF (teyit); Y-5: config.py get_system_info() redis_url tamamen kaldırıldı + import re temizlendi. Güvenlik puanı 8.9→9.2. AUDIT_REPORT v4.0.1 §9.6, §10, §11 güncellendi.** |
| **v3.0.15** | **2026-03-18** | **FAZ-3 teknik borç temizliği tamamlandı: web_server.py dead-code (hasattr/payload.get) kaldırıldı; /metrics endpoint'leri METRICS_TOKEN/admin korumasına alındı; conftest.py deprecated event_loop fixture → asyncio_default_fixture_loop_scope=session; CI'ya PostgreSQL 16 bağlantı havuzu stres testi eklendi; config.py GPU fraction yorum düzeltildi; main.py port 1-65535 validasyonu eklendi; core/rag.py bleach DOM sanitizasyonu; agent/sidar_agent.py prompt injection koruması. D-1..D-5 tüm bulgular kapatıldı.** |
| **v3.0.14** | **2026-03-18** | **Kapsamlı yeniden ölçüm ve rapor düzeltme turu: Tüm Python kaynak dosyaları satır satır yeniden ölçüldü. Eksik dosyalar §2 dosya ağacına eklendi: `agent/registry.py` (186 satır — AgentRegistry marketplace), `agent/swarm.py` (370 satır — SwarmOrchestrator/TaskRouter), `plugins/upload_agent.py` (10 satır). Güncellenen satır sayıları: `web_server.py` 1.568→1.960, `core/db.py` 1.353→1.634, `core/llm_client.py` 1.235→1.319, `config.py` 722→749, `core/rag.py` 1.057→1.092, `agent/core/event_stream.py` 189→217, `agent/core/supervisor.py` 168→183, `agent/core/contracts.py` 56→63, `core/llm_metrics.py` 245→256, `managers/package_info.py` 326→343, `agent/sidar_agent.py` 557→574, `agent/tooling.py` 117→112, `web_ui/index.html` 572→639, `web_ui/app.js` 733→818. Test sayımları güncellendi: 109→130 modül, 111→132 dosya, 21.765→30.613 satır. Web UI toplamı 4.240→4.392. Python kaynak toplamı 13.552→15.027. §9.1 bağımlılık haritasına `agent/registry.py` ve `agent/swarm.py` eklendi.** |
| **v3.0.20** | **2026-03-18** | **Tüm kaynak dosyalar satır satır yeniden ölçüldü (mevcut yapıya göre). Güncellenen satır sayıları: `web_server.py` 1.960→2.089, `core/rag.py` 1.092→1.122, `agent/core/supervisor.py` 183→239, `agent/sidar_agent.py` 574→583, `managers/code_manager.py` 898→932, `config.py` 749→759, `main.py` 372→381, `core/db.py` 1.634→1.635. Test modülü 130→132, toplam test satırı 30.613→31.302. Python kaynak toplamı ~15.027→~15.305. §2 tests satırı 109/111→132/132 olarak güncellendi. AUDIT_REPORT_v4.0.md v4.0.2 olarak revize edildi; §2.1, §2.2 ve §9 modül tabloları mevcut koda uyarlandı.** |
| **v3.0.21** | **2026-03-18** | **Faz 5 başlangıç özellikleri hayata geçirildi: (1) DLP & PII Maskeleme (`core/dlp.py` 320 satır) — Regex tabanlı 10 PII deseni (Bearer token, sk- key, GitHub PAT, AWS key, JWT, TC kimlik no, e-posta, kredi kartı vb.); `core/llm_client.py`'ye API hook entegrasyonu; `DLP_ENABLED`/`DLP_LOG_DETECTIONS` config. (2) Human-in-the-Loop (`core/hitl.py` 274 satır) — HITLGate async polling; 3 yeni web API endpoint; WebSocket broadcast hook. (3) LLM-as-a-Judge (`core/judge.py` 257 satır) — RAG alaka + halüsinasyon ölçümü; Prometheus metrikleri. (4) .env.example ↔ config.py parite sertleştirmesi — `scripts/check_env_parity.sh` + CI otomatik kontrol. 60 yeni test (4 modül). Python kaynak ~15.305→~16.156.** |
| **v3.0.22** | **2026-03-18** | **Faz 5 devamı — 3 yüksek değerli özellik: (1) Cost-Aware Model Routing (`core/router.py` 211 satır) — QueryComplexityAnalyzer + CostAwareRouter; LLMClient.chat() içine şeffaf entegrasyon; 4 yeni config anahtarı. (2) Entity/Persona Memory (`core/entity_memory.py` 283 satır) — kullanıcı başına KV persona deposu (SQLite/PG); TTL + LRU eviction. (3) Semantic Cache Grafana Hit Rate (`core/cache_metrics.py` 50 satır) — thread-safe sayaçlar; `grafana/dashboards/sidar_overview.json` (Cache Hit Rate gauge + Hit/Miss Trend + LLM Cost & Latency panelleri); provisioning YAML. 62 yeni test (3 modül, 51 geçti/11 skip). Python kaynak ~16.156→~16.700.** |
| **v3.0.23** | **2026-03-18** | **Faz 4 özellikleri — Active Learning + Vision Pipeline: (1) Active Learning + LoRA/QLoRA (`core/active_learning.py` 419 satır) — FeedbackStore (SQLite/PG async), DatasetExporter (jsonl/alpaca/sharegpt), LoRATrainer (PEFT graceful degrade); 26 test. (2) Multimodal Vision Pipeline (`core/vision.py` 294 satır) — load_image_as_base64/from_bytes, build_vision_messages (openai/anthropic/gemini/ollama), VisionPipeline.mockup_to_code/analyze; 40 test. Python kaynak ~16.700→~17.413.** |
| **v3.0.24** | **2026-03-18** | **Faz 4 tamamlama — Jira/Slack/Teams entegrasyonu: (1) `managers/slack_manager.py` (205 satır) — Bot SDK + Webhook fallback, Block Kit yardımcıları. (2) `managers/jira_manager.py` (245 satır) — Jira Cloud REST API v3, Basic Auth / Bearer. (3) `managers/teams_manager.py` (234 satır) — MessageCard + Adaptive Card v1.4, HITL onay kartı. 44 yeni test (1 modül: test_slack_jira_teams.py). Python kaynak ~17.413→~18.200+. Test modülü 132→142, test satırı 31.302→33.868. PROJE_RAPORU.md + AUDIT_REPORT_v4.0.md tüm metriklere göre güncellendi.** |
| **v3.0.25** | **2026-03-18** | **Kapsamlı çapraz-modül tutarsızlık ve entegrasyon denetimi (AUDIT_REPORT_v4.0.4): Tüm yeni modüller (core/dlp, hitl, judge, router, entity_memory, cache_metrics, active_learning, vision) ve yöneticiler (slack, jira, teams) satır satır incelendi; llm_client.py, web_server.py, config.py entegrasyon noktaları doğrulandı. 11 yeni bulgu: Y-6 (record_routing_cost hiç çağrılmıyor), O-7 (6 modülde HTTP endpoint yok), O-8 (SlackManager sync init), D-7..D-14 (Prometheus tekrar kayıt, no-op kod, private singleton, Config() her çağrıda, senkron IO, f-string SQL, asyncio.Lock erken init, private _notify import). Önceki 18 bulgu (K-1..D-6) kapalı. Güvenlik puanı 9.2 olarak revize edildi.** |
| **v3.0.26** | **2026-03-18** | **Entegrasyon düzeltme ve rapor senkronizasyon turu: `core/llm_client.py` günlük maliyet takibini `record_routing_cost()` ile besleyecek şekilde güncellendi; `web_server.py` içine Vision (`/api/vision/*`), EntityMemory (`/api/memory/entity/*`), FeedbackStore (`/api/feedback/*`) ve Slack/Jira/Teams entegrasyon endpoint'leri eklendi; `managers/slack_manager.py` içinde senkron `auth_test()` kaldırılıp async `initialize()` akışına taşındı; `core/judge.py` Prometheus gauge tekrar kayıt riski singleton önbellek ile kapatıldı. Arkadaş yorumu ile yapılan karşılaştırmalı doğrulama sonucunda O-8 ve D-7 kapanışı yeniden teyit edildi; buna karşılık D-8 ve D-9 için önerilen düzeltmelerin koda tam yansımadığı görüldü. Açık bulgu sayısı 11→7'ye düştü; kalan bulgular D-8, D-9, D-10, D-11, D-12, D-13 ve D-14 olarak 7 düşük öncelikli kalite borcundan oluşmaktadır. Güvenlik/operasyon puanı 9.6 olarak güncellendi.** |
| **v3.0.27** | **2026-03-18** | **Reviewer QA akışı kurumsal fail-closed modele yükseltildi: `agent/roles/reviewer_agent.py` artık `CodeManager` + `SecurityManager` ile Docker sandbox komutları üzerinden test koşturuyor, LLM ile dinamik pytest içeriği üretiyor ve QA çıktısını yapılandırılmış JSON `qa_feedback` mesajı olarak coder ajana iletiyor. `agent/roles/coder_agent.py` JSON tabanlı QA geri bildirimini ayrıştırıp başarısız test çıktılarını revizyon bağlamı olarak özetliyor. `agent/core/supervisor.py` P2P köprüsünde ve coder↔reviewer döngüsünde `MAX_QA_RETRIES` sınırını fail-closed biçimde uyguluyor. `tests/test_reviewer_agent.py` LLM ve sandbox entegrasyonunu mock tabanlı olarak güncelledi.** |
| **v3.0.28** | **2026-03-18** | **Reviewer sandbox yürütmesi operasyonel olarak sertleştirildi: `managers/code_manager.py` içine `run_shell_in_sandbox()` eklendi ve Docker CLI komutları artık `ACCESS_LEVEL=sandbox` altında da `can_execute()` yetkisiyle çalışabiliyor. `agent/roles/reviewer_agent.py` host shell yetkisi gerektiren `run_shell()` yerine bu yeni yolu kullanacak şekilde güncellendi; böylece QA testleri sandbox modunda da Zero-Trust konteyner içinde devam ediyor. `tests/test_reviewer_agent.py` bu yeni yürütme yolunu ve fail-closed hata yüzeyini doğrulayacak şekilde revize edildi.** |
| **v3.0.29** | **2026-03-19** | **Ana giriş dosyaları ve rapor senkronizasyonu: `main.py`, `cli.py`, `web_server.py`, `config.py`, `github_upload.py` ve `gui_launcher.py` satır satır yeniden incelendi; başlatıcı sihirbazı, tek-loop CLI akışı, 60 endpointli web kontrol düzlemi, config bootstrap/telemetry yükleme yolu, güvenli GitHub paketleme mantığı ve Eel GUI köprüsü raporlara işlendi. Takipli ölçümler güncellendi: üretim Python 19.554 satır, test satırı 34.121, takipli toplam Python 53.675; Web UI toplamı 6.105 satır olarak teyit edildi. Açık kritik/yüksek/orta bulgu olmadığı ve yalnızca 7 düşük öncelikli kalite borcu kaldığı yeniden doğrulandı.** |
| **v3.0.30** | **2026-03-19** | **Zero Debt doğrulama turu: `core/entity_memory.py`, `core/cache_metrics.py`, `core/judge.py`, `core/vision.py`, `core/active_learning.py`, `core/hitl.py`, `core/llm_client.py` ve `web_server.py` satır satır yeniden incelendi. D-8 no-op atama temizliği, D-9 public cache wrapper API'si, D-10 config singleton kullanımı, D-11 async dosya okuma, D-12 named placeholder SQL, D-13 lazy-init lock ve D-14 public `notify()` arayüzü doğrudan koddan doğrulandı. Açık bulgu sayısı 7→0 düştü; sistem 60 endpoint, 19.554 üretim Python satırı ve **10.0/10** güvenlik/operasyon puanı ile Zero Debt durumuna taşındı.** |
| **v3.0.31** | **2026-03-19** | **Kurumsal rollout senkronizasyonu: `migrations/versions/0003_audit_trail.py`, `core/db.py`, `web_server.py`, `agent/core/contracts.py`, `agent/base_agent.py`, `agent/core/supervisor.py` ve `agent/swarm.py` satır satır yeniden incelendi. `audit_logs` migration'ı, `record_audit_log()` / `list_audit_logs()` yardımcıları ve `access_policy_middleware` audit trail yazımı ile tenant RBAC kararlarının kalıcı uyum izi doğrulandı. Aynı turda direct `p2p.v1` handoff protokolünün Supervisor + Swarm akışlarında sender/receiver/reason/handoff_depth bağlamını koruduğu ve ilgili testlerle güvence altına alındığı rapora işlendi.** |
| **v3.2.0** | **2026-03-19** | **Autonomous LLMOps anlatısının konsolidasyonu: Faz 4 kapsamı yeniden çerçevelenerek `core/active_learning.py`, `core/vision.py`, `core/router.py`, `managers/slack_manager.py`, `managers/jira_manager.py` ve `managers/teams_manager.py` üzerinden gelen aktif öğrenme, multimodal üretim, cost-aware routing ve dış sistem orkestrasyonu tek bir ürün hikâyesi altında birleştirildi. Böylece Faz 4 yalnızca “özellik eklendi” seviyesinde değil, kapalı döngü öğrenme + çok modlu çıktı + otonom entegrasyon yönetimi ekseninde Autonomous LLMOps katmanı olarak tanımlandı.** |
| **v4.2.0** | **2026-03-19** | **Faz 4 tamamlandı notu kurumsal operasyon seviyesine yükseltildi: `migrations/versions/0003_audit_trail.py`, `core/db.py`, `web_server.py`, `agent/core/contracts.py`, `agent/base_agent.py`, `agent/core/supervisor.py` ve `agent/swarm.py` ile doğrulanan audit trail + direct handoff omurgası, Faz 4 LLMOps yeteneklerinin denetlenebilir, rollout'a hazır ve kurumsal ölçek için kalıcı olduğunu teyit etti. Bu sürüm, Autonomous LLMOps vizyonunun teknik olarak tamamlanıp operasyonel olarak da kapanış aldığını belgeleyen rapor sürümüdür.** |
| **v4.3.0** | **2026-03-19** | **Sürüm + metrik senkronizasyon turu: `scripts/audit_metrics.sh` ve `scripts/collect_repo_metrics.sh` Git takipli dosyaları baz alacak şekilde düzeltildi; ardından `config.py`, `pyproject.toml`, `sidar_project.egg-info/PKG-INFO`, `helm/sidar/Chart.yaml`, `README.md`, `PROJE_RAPORU.md`, `AUDIT_REPORT_v4.0.md` ve `TEKNIK_REFERANS.md` güncel ölçümlerle hizalandı. Yeni baz çizgisi 58 üretim Python dosyası / 20.582 satır, 151 test dosyası / 39.147 satır, toplam 209 takipli Python dosyası / 59.729 satır ve 60 REST endpoint olarak teyit edildi.** |

- **Öne Çıkan Başarılar:** Multi-agent P2P delegasyon altyapısı ve %99.9 test kapsamı zorunluluğu projenin üretim kararlılığını garanti altına almıştır. Faz 4+5 özellik turlarıyla kurumsal DLP, HITL, Judge, Cost-Aware Routing, Entity Memory, Active Learning, Vision ve Slack/Jira/Teams entegrasyonu tamamlanarak platform ürün olgunluğuna ulaşmıştır.
- **Arşiv Notu:** Detaylı sürüm bazlı değişiklik geçmişi ve çözülen teknik borçlar için `CHANGELOG.md` dosyasını referans alınız.