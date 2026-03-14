# SİDAR Projesi — Kapsamlı Kod Analiz Raporu (Güncel)

> **Rapor Tarihi:** 2026-03-14
> **Son Güncelleme:** 2026-03-15 (v3.0.0 — **Final Sürüm (Production-Ready):** Kurumsal/SaaS v3.0 kapsamı (migration, auth, observability, sandbox hazırlıkları) operasyonel olarak doğrulandı; satır sayıları ve dosya envanteri güncel ölçümlerle eşleştirildi; Bölüm 11 teknik borç durumları kaynak kod incelemesiyle güncellendi — 3 borç kapatıldı, 1 kısmen çözüldü, 1 AÇIK)
> **Proje Sürümü:** 3.0.0
> **Derin Teknik Kılavuz:** API/DB/Operasyon detayları için `TEKNIK_REFERANS.md` dosyasına bakınız.
> **Analiz Kapsamı:** Tüm kaynak dosyaları satır satır incelenmiştir. Toplam Python kaynak: ~12.160 satır (tests hariç, güncel ölçüm); Test: **20.962** satır; Web UI: **4.239** satır.

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
  - [4.3 Kurumsal v3.0 Mimari Sütunlar (Enterprise Lens)](#43-kurumsal-v30-mimari-sütunlar-enterprise-lens)
- [5. Güvenlik Analizi](#5-güvenlik-analizi)
  - [5.1 Güvenlik Kontrolleri Özeti](#51-güvenlik-kontrolleri-özeti)
  - [5.2 Güvenlik Seviyeleri Davranışı](#52-güvenlik-seviyeleri-davranışı)
  - [5.3 Kurumsal Zero-Trust Savunma Sütunları (v3.0)](#53-kurumsal-zero-trust-savunma-sütunları-v30)
- [6. Test Kapsamı](#6-test-kapsamı)
  - [6.1 CI/CD Pipeline Durumu](#61-cicd-pipeline-durumu)
  - [6.2 Coverage Hard Gate (%95)](#62-coverage-hard-gate-95)
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
- [11. Mevcut Sorunlar ve Teknik Borç](#11-mevcut-sorunlar-ve-teknik-borç)
  - [11.1 Ödenmiş Teknik Borçlar (Resolved) ve Changelog Referansı](#111-ödenmiş-teknik-borçlar-resolved-ve-changelog-referansı)
  - [11.2 Yeni Nesil Kurumsal Teknik Borçlar (Açık)](#112-yeni-nesil-kurumsal-teknik-borçlar-açık)
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
- [13. Olası İyileştirmeler (v4.0 Kurumsal Yol Haritası)](#13-olası-i̇yileştirmeler-v40-kurumsal-yol-haritası)
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

**Sidar**, ReAct (Reason + Act) döngüsüyle çalışan, tamamen asenkron bir yazılım mühendisi AI asistanıdır. Yerel LLM (Ollama) veya bulut tabanlı LLM'ler (Google Gemini, OpenAI, Anthropic) ile çalışabilir; CLI ve FastAPI tabanlı Web arayüzü olmak üzere iki ayrı kullanıcı ara yüzü sunar.

### Temel Özellikler
- **Çift arayüz:** CLI (`cli.py`) ve Web (`web_server.py` + `web_ui/static/`)
- **Çoklu LLM sağlayıcı:** Ollama (yerel), Gemini, OpenAI ve Anthropic (bulut)
- **Multi-Agent + P2P Delegasyon:** Supervisor orkestrasyonu ile görevleri uzman rollere (Coder, Researcher, Reviewer) dağıtır; `agent/core/contracts.py` ile ajanlar arası P2P görev sözleşmesi desteklenir.
- **Çoklu Kullanıcı (Multi-User) ve Veritabanı Altyapısı:** PostgreSQL/SQLite destekli kalıcı veri katmanı ile kullanıcı bazlı oturum izolasyonu ve kota yönetimi (`core/db.py`).
- **Telemetri ve Bütçe İzleme:** Grafana ve Prometheus entegrasyonu ile LLM API maliyetleri (USD), token tüketimi ve gecikme (latency) takibi (`core/llm_metrics.py`).
- **Canlı Ajan Durum Akışı (Observability):** WebSocket tabanlı event stream ile düşünce adımları, araç çağrıları ve ajan durumları Web UI'da canlı izlenir (`agent/core/event_stream.py`).
- **Kurumsal Web UI Admin Paneli:** Yönetici rolüne sahip kullanıcılar için sistem kullanımını, aktif kullanıcıları ve global kotaları gösteren merkezi yönetim arayüzü.
- **QA ve Regresyon Sinyali:** Coder ajanı ile ortak çalışan, üretilen kodu test edip onaylayan/reddeden gelişmiş `ReviewerAgent` döngüsü.
- **GitHub Entegrasyonu (Smart PR/Issue):** Repo analizi, branch/PR akışı, issue ve release etkileşimleri `managers/github_manager.py` ile ajan araç setine entegredir.
- **ReAct döngüsü:** LLM → Araç çağrısı → Gözlem → LLM (maks. `MAX_REACT_STEPS` adım)
- **Görev Takibi ve Proje Denetimi:** `todo_manager.py` ile TODO yazma/okuma/güncelleme ve proje genelinde TODO/FIXME taraması (`scan_project_todos`) yapılır.
- **RAG (Vektör Bellek):** ChromaDB + BM25 + Keyword hibrit arama (RRF destekli)
- **Güvenlik:** OpenClaw 3 katmanlı erişim sistemi (restricted / sandbox / full)
- **Zero-Trust Sandbox:** Docker izolasyonuna ek olarak ağ kapatma, CPU/RAM sınırlandırma ve gVisor/Kata uyumluluğuna hazır çalışma modeliyle güvenli kod yürütme.
- **GPU desteği:** CUDA, FP16, çoklu GPU, WSL2 uyumu
- **Veritabanı destekli şifreli bellek:** Oturum geçmişi ve konuşma verileri DB katmanında kalıcı tutulur; Fernet ile şifreleme desteği korunur.

---

## 2. Proje Dosya Yapısı

[⬆ İçindekilere Dön](#içindekiler)

<pre>
sidar_project/
├── .github/workflows/         # CI/CD süreçleri (ci.yml, migration-cutover-checks.yml)
├── <a href="docs/module-notes/main.py.md">main.py</a>                    # Akıllı başlatıcı (wizard + --quick mod)
├── <a href="docs/module-notes/cli.py.md">cli.py</a>                     # CLI terminal arayüzü giriş noktası
├── <a href="docs/module-notes/web_server.py.md">web_server.py</a>              # FastAPI web sunucusu (WebSocket streaming)
├── <a href="docs/module-notes/config.py.md">config.py</a>                  # Merkezi yapılandırma (v3.0.0)
├── <a href="docs/module-notes/github_upload.py.md">github_upload.py</a>           # GitHub otomatik yükleme aracı
├── <a href="docs/module-notes/gui_launcher.py.md">gui_launcher.py</a>            # Eel tabanlı masaüstü başlatıcı giriş noktası
├── <a href="docs/module-notes/Dockerfile.md">Dockerfile</a>                 # CPU + GPU çift mod Dockerfile
├── <a href="docs/module-notes/docker-compose.yml.md">docker-compose.yml</a>         # 7 servis (redis, sidar-ai, sidar-gpu, sidar-web, sidar-web-gpu, prometheus, grafana)
├── <a href="docs/module-notes/environment.yml.md">environment.yml</a>            # Conda bağımlılıkları
├── <a href="docs/module-notes/requirements.txt.md">requirements.txt</a>           # Pip temel bağımlılıkları
├── <a href="docs/module-notes/requirements-dev.txt.md">requirements-dev.txt</a>       # Geliştirme ve test bağımlılıkları
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
│   └── <a href="docs/module-notes/core/rag.py.md">rag.py</a>                 # ChromaDB + BM25 hibrit RAG motoru
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
│   └── <a href="docs/module-notes/managers/todo_manager.py.md">todo_manager.py</a>        # Görev takip yöneticisi
│
├── migrations/                # Alembic veritabanı geçiş dosyaları
│   ├── <a href="docs/module-notes/migrations/env.py.md">env.py</a>
│   ├── <a href="docs/module-notes/migrations/script.py.mako.md">script.py.mako</a>
│   └── versions/              # 0001_baseline_schema.py vb. şema versiyonları
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
│   └── <a href="docs/module-notes/runbooks/production-cutover-playbook.md.md">production-cutover-playbook.md</a> # Kurumsal sürüme geçiş yönergeleri
│
├── launcher_gui/              # Eel tabanlı masaüstü başlatıcı frontend
│   ├── index.html             # Başlatıcı arayüzü
│   ├── script.js              # Başlatıcı mantığı
│   └── style.css              # Başlatıcı stilleri
│
├── web_ui/                    # Modüler Web UI
│   ├── <a href="docs/module-notes/web_ui/index.html.md">index.html</a>
│   ├── <a href="docs/module-notes/web_ui/style.css.md">style.css</a>
│   ├── <a href="docs/module-notes/web_ui/chat.js.md">chat.js</a>                # WebSocket streaming, canlı durum akışı
│   ├── <a href="docs/module-notes/web_ui/sidebar.js.md">sidebar.js</a>             # Oturum yönetimi
│   ├── <a href="docs/module-notes/web_ui/rag.js.md">rag.js</a>                 # RAG belge UI
│   └── <a href="docs/module-notes/web_ui/app.js.md">app.js</a>                 # Uygulama başlatma, auth, bütçe yönetimi
│
├── <a href="docs/module-notes/tests.md">tests/</a>                     # Kapsamlı test paketi (~70 test modülü)
├── <a href="docs/module-notes/data/gitkeep.md">data/</a>                      # RAG ve varsayılan yerel depolama dosyaları
├── <a href="docs/module-notes/coveragerc.md">.coveragerc</a>                # Coverage kalite kapısı kuralları (%95 eşik)
├── <a href="docs/module-notes/env.example.md">.env.example</a>               # Ortam değişkeni şablonu
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

Bu bölüm sadeleştirilmiştir. Her modülün detaylı incelemesi doğrudan `docs/module-notes/` altındaki ilgili not dosyasına taşınmıştır.

### 3.A Çekirdek Giriş Dosyaları

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.1 | `config.py` | [docs/module-notes/config.py.md](docs/module-notes/config.py.md) |
| 3.2 | `main.py` | [docs/module-notes/main.py.md](docs/module-notes/main.py.md) |
| 3.3 | `cli.py` | [docs/module-notes/cli.py.md](docs/module-notes/cli.py.md) |
| 3.4 | `web_server.py` | [docs/module-notes/web_server.py.md](docs/module-notes/web_server.py.md) |

### 3.B Agent Katmanı

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.5 | `agent/sidar_agent.py` | [docs/module-notes/agent/sidar_agent.py.md](docs/module-notes/agent/sidar_agent.py.md) |
| 3.6 | `agent/auto_handle.py` | [docs/module-notes/agent/auto_handle.py.md](docs/module-notes/agent/auto_handle.py.md) |
| 3.7 | `agent/definitions.py` | [docs/module-notes/agent/definitions.py.md](docs/module-notes/agent/definitions.py.md) |
| 3.7b | `agent/tooling.py` | [docs/module-notes/agent/tooling.py.md](docs/module-notes/agent/tooling.py.md) |
| 3.7c | `agent/base_agent.py` | [docs/module-notes/agent/base_agent.py.md](docs/module-notes/agent/base_agent.py.md) |
| 3.7d | `agent/core/supervisor.py` | [docs/module-notes/agent/core/supervisor.py.md](docs/module-notes/agent/core/supervisor.py.md) |
| 3.7e | `agent/core/contracts.py`, `event_stream.py`, `memory_hub.py`, `registry.py` | [docs/module-notes/agent/core/contracts.py.md](docs/module-notes/agent/core/contracts.py.md) |
| 3.7f | `agent/roles/` | [docs/module-notes/agent/roles/__init__.py.md](docs/module-notes/agent/roles/__init__.py.md) |

### 3.C Core ve Manager Katmanı

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.8 | `core/llm_client.py` | [docs/module-notes/core/llm_client.py.md](docs/module-notes/core/llm_client.py.md) |
| 3.9 | `core/memory.py` | [docs/module-notes/core/memory.py.md](docs/module-notes/core/memory.py.md) |
| 3.10 | `core/rag.py` | [docs/module-notes/core/rag.py.md](docs/module-notes/core/rag.py.md) |
| 3.11 | `managers/security.py` | [docs/module-notes/managers/security.py.md](docs/module-notes/managers/security.py.md) |
| 3.12 | `managers/code_manager.py` | [docs/module-notes/managers/code_manager.py.md](docs/module-notes/managers/code_manager.py.md) |
| 3.13 | `managers/github_manager.py` | [docs/module-notes/managers/github_manager.py.md](docs/module-notes/managers/github_manager.py.md) |
| 3.14 | `managers/system_health.py` | [docs/module-notes/managers/system_health.py.md](docs/module-notes/managers/system_health.py.md) |
| 3.15 | `managers/web_search.py` | [docs/module-notes/managers/web_search.py.md](docs/module-notes/managers/web_search.py.md) |
| 3.16 | `managers/package_info.py` | [docs/module-notes/managers/package_info.py.md](docs/module-notes/managers/package_info.py.md) |
| 3.17 | `managers/todo_manager.py` | [docs/module-notes/managers/todo_manager.py.md](docs/module-notes/managers/todo_manager.py.md) |

### 3.D UI, Altyapı ve Operasyon

| Bölüm | Modül | Modül Notu |
|---|---|---|
| 3.18 | `web_ui/` | [docs/module-notes/web_ui/index.html.md](docs/module-notes/web_ui/index.html.md) |
| 3.19 | `github_upload.py` | [docs/module-notes/github_upload.py.md](docs/module-notes/github_upload.py.md) |
| 3.20 | `core/db.py` | [docs/module-notes/core/db.py.md](docs/module-notes/core/db.py.md) |
| 3.21 | `core/llm_metrics.py` | [docs/module-notes/core/llm_metrics.py.md](docs/module-notes/core/llm_metrics.py.md) |
| 3.22 | `migrations/` ve `scripts/` | [docs/module-notes/migrations/env.py.md](docs/module-notes/migrations/env.py.md) |
| 3.23 | `docker/` ve `runbooks/` | [docs/module-notes/docker/prometheus/prometheus.yml.md](docs/module-notes/docker/prometheus/prometheus.yml.md) |

---

## 4. Mimari Değerlendirme

[⬆ İçindekilere Dön](#içindekiler)

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
| **Gözlemlenebilirlik** | OpenTelemetry + Prometheus/Grafana + `/api/budget` ile latency/token/maliyet metriklerinin canlı takibi |
| **Dağıtık Multi-Agent Orkestrasyonu** | Supervisor tabanlı görev yönlendirme (Coder/Researcher/Reviewer) ile modülerlik, hata izolasyonu ve kalite artışı |
| **Çoklu LLM Ekosistemi** | Ollama, Gemini, OpenAI, Anthropic istemcilerinin ortak sözleşmeyle birlikte çalışması |

### 4.2 Kısıtlamalar

| Alan | Durum |
|------|-------|
| **Rate Limiting Altyapısı** | Redis gerektirir; Redis kesintisinde local fallback devreye girer ve dağıtık tutarlılık geçici düşebilir |
| **Docker Bağımlılığı** | `execute_code` tam işlevsellik için Docker daemon erişimi gerektirir |
| **BM25 Bellek Maliyeti** | Büyük doküman korpuslarında BM25 token verisinin RAM tüketimi artar |
| **LLM Maliyet/Limit Baskısı** | Bulut sağlayıcılarda token maliyeti ve provider rate-limit yönetimi zorunludur |
| **QA Overhead** | Reviewer doğrulama adımları kaliteyi artırırken ek LLM çağrısı/latency maliyeti üretir |
| **Operasyonel Karmaşıklık** | PostgreSQL + Prometheus + Grafana + migration süreçleri kurulum/işletim maliyetini yükseltir |

### 4.3 Kurumsal v3.0 Mimari Sütunlar (Enterprise Lens)

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

#### 4.3.5 Observability + SaaS Veri Katmanı
- OpenTelemetry izleri, Prometheus metrik ihracı ve Grafana panoları ile latency/token/maliyet görünürlüğü uçtan uca sağlanır.
- SQLite kökenli tekil modelden, async pool destekli PostgreSQL ve multi-tenant kullanıcı izolasyonuna geçiş mimari olgunluk seviyesini yükseltir.

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
| LLM QA Devre Kesici | ✓ Aktif (`MAX_QA_RETRIES=3`) | `agent/sidar_agent.py` |
| GitHub binary engelleme | ✓ Aktif | `managers/github_manager.py` |
| Git upload blacklist | ✓ Aktif | `github_upload.py` |
| Bilinmeyen erişim seviyesi | ✓ Sandbox'a normalize | `managers/security.py` |
| Branch adı enjeksiyon koruması | ✓ Regex `_BRANCH_RE` | `managers/github_manager.py` |
| GitHub Webhook İmzası | ✓ Aktif (HMAC-SHA256) | `web_server.py` — `/api/webhook` |
| Büyük Dosya Okuma Limit | ✓ Aktif (boyut limiti) | `web_server.py` — `/file-content` |

### 5.2 Güvenlik Seviyeleri Davranışı

```
RESTRICTED → yalnızca okuma + analiz (yazma/çalıştırma/shell YOK)
SANDBOX    → okuma + /temp yazma + Docker Python REPL
FULL       → tam erişim (shell, git, npm, proje geneli yazma)
```

**QA ve Kod Onay Bariyeri (ReviewerAgent Süzgeci):** Hangi erişim seviyesinde (Sandbox veya Full) çalışılırsa çalışılsın, CoderAgent çıktıları ReviewerAgent doğrulamasından geçer. Ek olarak `MAX_QA_RETRIES=3` sınırı ile Coder ↔ Reviewer geri besleme zinciri fail-safe biçimde sonlandırılır; sonsuz döngü ve maliyet artışı engellenir.

### 5.3 Kurumsal Zero-Trust Savunma Sütunları (v3.0)

#### 5.3.1 Path Traversal + Blacklist + Symlink Koruması
- `SecurityManager`, ham yol girdilerinde `../` ve kritik sistem dizinlerini (`/etc`, `/proc`, `/sys`, `C:\Windows`, `Program Files`) `_DANGEROUS_PATH_RE` ile reddeder.
- `.env`, `.git`, `sessions`, `__pycache__` gibi hassas yollar `_BLOCKED_PATTERNS` ile ek katmanda engellenir; bu kural FULL seviyede dahi güvenlik zeminini korur.
- `Path.resolve()` + `relative_to(base_dir)` kontrolleri ile symlink üzerinden kök dizin dışına kaçış girişimleri fail-closed biçimde bloklanır.

#### 5.3.2 Docker Sandbox İzolasyonu (Kod Çalıştırma)
- `execute_code` akışı, kodu izole Docker konteynerinde çalıştırır; `network_mode="none"`, `mem_limit` ve `nano_cpus` ile ağ/kaynak sınırları uygulanır.
- Sandbox katmanı erişilemezse politika seviyesine göre kontrollü davranış devreye girer (SANDBOX modunda reddetme, FULL modda sınırlı fallback).

#### 5.3.3 Kriptografik Kimlik/Oturum Güvenliği
- Parola doğrulama akışı `PBKDF2-HMAC-SHA256` + salt + sabit-zamanlı karşılaştırma (`secrets.compare_digest`) ile uygulanır.
- Oturum belirteçleri `secrets.token_urlsafe(...)` ile üretilir; kullanıcı/oturum anahtarlarında UUID kullanımı tahmin edilebilirlik riskini azaltır.
- WebSocket kanalında `auth` handshake zorunludur; geçersiz/eksik token durumunda bağlantı policy violation ile kapatılır.

#### 5.3.4 OOM/Binary ve Rate-Limit Savunmaları
- GitHub dosya okuma katmanında güvenli uzantı/uzantısız whitelist uygulanır; binary/uygunsuz dosya tipleri decode edilmeden reddedilir.
- API yüzeyinde DDoS/rate-limit middleware'leri ve Redis destekli limit mekanizmasıyla ani yüklenmelerde servis kararlılığı korunur.
- Büyük dosya okuma limitleri ve güvenli metin odaklı işleme yaklaşımı, bellek şişmesi (OOM) riskini azaltan uygulama savunması sağlar.

#### 5.3.5 Web UI XSS Sertleştirmesi
- `marked` ile üretilen HTML, istemci tarafında `sanitizeRenderedHtml(...)` süzgecinden geçirilir.
- `script/iframe/object/embed/form/meta/link` etiketleri ve `javascript:` gibi tehlikeli URL şemaları temizlenerek içerik render edilir.

---

## 6. Test Kapsamı

[⬆ İçindekilere Dön](#içindekiler)

Güncel depoda test envanteri kurumsal kalite kapılarına göre genişletilmiştir:

- **`test_*.py` modül sayısı:** **92**
- **`tests/*.py` toplamı ( `conftest.py` + `__init__.py` dahil ):** **94**
- **Toplam test satırı (`tests/*.py`):** **20.962**

**v3.0 Öne Çıkan Test Kategorileri:**
- **Veritabanı & Migration:** `test_db_runtime.py`, `test_db_postgresql_branches.py`, `test_migration_assets.py`, `test_migration_ci_guards.py`
- **Zero-Trust Sandbox:** `test_sandbox_runtime_profiles.py`, `test_host_sandbox_installer_assets.py`, `test_dockerfile_runtime_improvements.py`
- **Telemetri & Bütçe:** `test_llm_metrics_runtime.py`, `test_grafana_dashboard_provisioning.py`
- **Multi-Agent & Reviewer:** `test_reviewer_agent.py`, `test_supervisor_agent.py`, `test_event_stream_runtime.py`, `test_agent_core_components.py`
- **Güvenlik ve WebSocket/Auth:** `test_security_level_transition.py`, `test_github_webhook.py`, `test_web_server_runtime.py`, `test_web_ui_security_improvements.py`

> Not: Önceki audit notlarında geçen 0 bayt test artifact uyarıları tarihsel kayıt niteliğindedir; güncel pipeline `find tests -type f -size 0` kontrolüyle bu durumu bloklayıcı kalite kapısı olarak yönetir.

### 6.1 CI/CD Pipeline Durumu

| Kalite Kapısı | Durum | Kaynak |
|---|---|---|
| Tüm testleri çalıştır (`run_tests.sh`) | ✅ Aktif | `.github/workflows/ci.yml` |
| Coverage Quality Gate (`fail_under=95`) | ✅ Zorunlu | `.coveragerc`, `run_tests.sh`, `ci.yml` |
| Boş test artifact engeli (`find tests -size 0`) | ✅ Zorunlu | `.github/workflows/ci.yml`, `scripts/check_empty_test_artifacts.sh` |
| Repo metrik/audit üretimi | ✅ Aktif | `scripts/collect_repo_metrics.sh`, `scripts/audit_metrics.sh` |
| Sandbox/Reviewer sertleştirme testi | ✅ Aktif | `tests/test_sandbox_runtime_profiles.py`, `tests/test_reviewer_agent.py` |

Bu yapı ile test disiplini yalnızca birim test sayısına değil, **coverage barajı + artifact hijyeni + güvenlik sertleştirme senaryoları** üzerine kurulu kurumsal bir kalite modeline taşınmıştır.

### 6.2 Coverage Hard Gate (%95)

- `.coveragerc` içinde `fail_under = 95` ve `show_missing = True` ayarları zorunlu kalite kapısı olarak tanımlıdır.
- CI hattı (`.github/workflows/ci.yml`) ayrı bir adımda `python -m pytest -q --cov=. --cov-report=term-missing --cov-fail-under=95` komutunu çalıştırır; eşik altı durumda pipeline fail olur.
- Bu model, "test çalıştı" seviyesinin ötesinde **ölçülebilir kapsam** zorunluluğu getirir ve eksik kapsanan satırların görünür kalmasını sağlar.

### 6.3 Test Havuzu ve Modüler Senaryolar

- Güncel depoda `test_*.py` desenine uyan **92 test modülü** bulunur; `tests/*.py` toplamı (yardımcı dosyalar dahil) **94** adettir.
- Testler yalnızca birim doğrulama ile sınırlı değildir; edge-case, provider retry/fallback, migration/DB branch ayrışmaları, sandbox profilleri ve web güvenliği gibi alanlara bölünmüş modüler paketler içerir.
- Örnek kurumsal odak alanları: `test_missing_edge_case_coverage.py`, `test_llm_client_retry_helpers.py`, `test_db_postgresql_branches.py`, `test_sandbox_runtime_profiles.py`.

### 6.4 Asenkron Test Altyapısı

- `pytest.ini` içinde `python_files = test_*.py` standardı ve `asyncio` marker tanımı ile tutarlı keşif/etiketleme sağlanır.
- `tests/conftest.py`, coroutine testlerini event loop içinde çalıştıran özel hook (`pytest_pyfunc_call`) içerir; böylece async servis akışları doğrudan test edilebilir.
- Bu altyapı, v3.0'ın async mimarisine uygun şekilde zamanlama/timeout/durum geçişi testlerini stabil biçimde yürütür.

---

## 7. Temel Bağımlılıklar

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, güncel `requirements.txt`, `requirements-dev.txt` ve `environment.yml` dosyalarına göre v3.0 bağımlılık setini kurumsal kategorilerle özetler.

### 7.1 Asenkron Altyapı ve Uygulama Çekirdeği

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `fastapi` + `uvicorn[standard]` | ✓ Zorunlu | Web API + WebSocket katmanı |
| `httpx` | ✓ Zorunlu | Asenkron HTTP istemcisi (LLM/web entegrasyonları) |
| `python-dotenv`, `pydantic`, `cachetools`, `anyio` | ✓ Zorunlu | Konfigürasyon, doğrulama, rate-limit yardımcıları |
| `redis` | Opsiyonel (önerilen) | Dağıtık/persist rate-limit altyapısı |

### 7.2 Veritabanı, Migrasyon ve Telemetri

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `SQLAlchemy` + `asyncpg` | ✓ Zorunlu (v3.0) | Async PostgreSQL veri katmanı |
| `alembic` | ✓ Zorunlu (v3.0) | Şema sürümleme ve migration zinciri |
| `prometheus-client` | ✓ Zorunlu (v3.0) | `/metrics` ve LLM telemetri export |
| `opentelemetry-*` | Opsiyonel | Tracing + OTLP export |
| `tiktoken` | ✓ Zorunlu (v3.0) | Token ölçümü ve özetleme eşikleri |

### 7.3 Güvenlik, Sandbox ve Donanım Gözlemlenebilirliği

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `docker` | Kritik/opsiyonel | Zero-Trust REPL sandbox çalıştırma |
| `nvidia-ml-py` + `psutil` | Opsiyonel | GPU/CPU/RAM donanım metrikleri |
| `cryptography` | Opsiyonel | Fernet tabanlı şifreleme yardımcıları |
| `python-multipart`, `packaging`, `pyyaml` | ✓ Zorunlu | Yardımcı runtime bileşenleri |

### 7.4 AI Sağlayıcıları ve RAG Katmanı

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `openai`, `anthropic`, `google-generativeai` | Opsiyonel (sağlayıcıya göre) | Çoklu LLM istemci katmanı |
| `chromadb` + `sentence-transformers` | Opsiyonel | Vektör tabanlı RAG ve embedding |
| `rank-bm25` | Opsiyonel (mevcut) | BM25 tabanlı hibrit arama uyumluluğu |
| `duckduckgo-search` + `beautifulsoup4` + `PyGithub` | Opsiyonel | Web/GitHub entegrasyonları |
| `torch` + `torchvision` | Opsiyonel | Embedding ve GPU hızlandırmalı iş yükleri |

### 7.5 Test ve Kalite Kapıları (Dev Bağımlılıkları)

| Paket | Durum | Kullanım Yeri |
|-------|-------|---------------|
| `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-benchmark` | ✓ Zorunlu (CI/QA) | Test yürütme, async test, coverage gate, benchmark |
| `ruff`, `mypy`, `black`, `flake8` | ✓ Zorunlu (CI/QA) | Lint, statik analiz, format kalite kapıları |

**Geçiş Notu (v3.0):**
- `requests` bağımlılığı doğrudan runtime listesinde yer almamaktadır; ana HTTP akışı `httpx` ile asenkron modele taşınmıştır.
- `rank-bm25` bağımlılığı ise mevcut bağımlılık dosyalarında hâlen tanımlıdır; hibrit RAG/BM25 uyumluluğu için opsiyonel katmanda korunmaktadır.
- `chardet` şu an doğrudan bağımlılık listesinde pinlenmemiştir; encoding fallback davranışı uygulama katmanında güvenli decode stratejileriyle yönetilmektedir.

**Auth Notu (v3.0):** Güncel kod tabanında kimlik doğrulama bearer token + DB tabanlı oturum modeli ile yürütülür. Şifre doğrulama `core/db.py` içinde PBKDF2-HMAC akışıyla yapılır; JWT/passlib/bcrypt şu an zorunlu bağımlılık setinde yer almamaktadır.

---

## 8. Kod Satır Sayısı Özeti

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, v3.0 final depo içeriği için güncel `wc -l` ölçümlerini içerir.

**Ölçüm notu (standart):** Kurumsal tekrar üretilebilirlik için satır sayısı raporları `scripts/audit_metrics.sh` ile otomatik üretilmelidir.

### 8.1 Çekirdek Modüller (Güncel)

| Dosya | Satır |
|---|---:|
| `config.py` | 607 |
| `main.py` | 341 |
| `cli.py` | 289 |
| `web_server.py` | 1.377 |
| `agent/sidar_agent.py` | 448 |
| `agent/auto_handle.py` | 602 |
| `agent/definitions.py` | 165 |
| `agent/tooling.py` | 117 |
| `agent/base_agent.py` | 55 |
| `core/llm_client.py` | 860 |
| `core/memory.py` | 280 |
| `core/rag.py` | 783 |
| `core/db.py` | 989 |
| `core/llm_metrics.py` | 235 |
| `managers/security.py` | 290 |
| `managers/code_manager.py` | 882 |
| `managers/github_manager.py` | 644 |
| `managers/system_health.py` | 475 |
| `managers/web_search.py` | 387 |
| `managers/package_info.py` | 322 |
| `managers/todo_manager.py` | 451 |
| `github_upload.py` | 294 |
| `gui_launcher.py` | 94 |

### 8.2 Multi-Agent Çekirdek ve Roller

| Dosya | Satır |
|---|---:|
| `agent/core/supervisor.py` | 164 |
| `agent/core/contracts.py` | 56 |
| `agent/core/event_stream.py` | 45 |
| `agent/core/memory_hub.py` | 54 |
| `agent/core/registry.py` | 25 |
| `agent/roles/coder_agent.py` | 134 |
| `agent/roles/researcher_agent.py` | 75 |
| `agent/roles/reviewer_agent.py` | 181 |

### 8.3 Migration / Operasyon / Altyapı

| Dosya | Satır |
|---|---:|
| `migrations/env.py` | 65 |
| `migrations/versions/0001_baseline_schema.py` | 98 |
| `scripts/migrate_sqlite_to_pg.py` | 91 |
| `scripts/load_test_db_pool.py` | 73 |
| `scripts/audit_metrics.sh` | 56 |
| `scripts/collect_repo_metrics.sh` | 13 |
| `scripts/install_host_sandbox.sh` | 200 |
| `docker/prometheus/prometheus.yml` | 7 |
| `docker/grafana/provisioning/datasources/prometheus.yml` | 8 |
| `docker/grafana/provisioning/dashboards/dashboards.yml` | 10 |
| `docker/grafana/dashboards/sidar-llm-overview.json` | 66 |
| `runbooks/production-cutover-playbook.md` | 109 |
| `Dockerfile` | 103 |
| `docker-compose.yml` | 236 |

### 8.4 Frontend ve Test Özeti

| Kapsam | Değer |
|---|---:|
| `web_ui/index.html` | 572 |
| `web_ui/style.css` | 1.684 |
| `web_ui/chat.js` | 721 |
| `web_ui/sidebar.js` | 421 |
| `web_ui/rag.js` | 131 |
| `web_ui/app.js` | 710 |
| **Web UI Toplamı** | **4.239** |
| **Test modülü (`tests/test_*.py`)** | **92** |
| **`tests/*.py` toplam dosya** | **94** |
| **`tests/*.py` toplam satır** | **20.962** |

### 8.5 Dizin Bazlı Hacim Özeti

| Dizin/Kapsam | Ölçüm | Değer |
|---|---|---:|
| `tests/` | `test_*.py` modül sayısı | 92 |
| `tests/` | `*.py` toplam dosya | 94 |
| `tests/` | `*.py` toplam satır | 20.962 |
| `scripts/` | dosya sayısı | 6 |
| `scripts/` | toplam satır | 443 |
| `migrations/` | dosya sayısı (tüm migration dosyaları) | 3 |
| `migrations/` | toplam satır | 163 |
| `docker/` | metin tabanlı stack dosyası sayısı (`*.yml`, `*.json`) | 4 |
| `docker/` | ilgili telemetri dosyaları toplam satır | 91 |

---

## 9. Modül Bağımlılık Haritası

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, v3.0 mimarisindeki bağımlılıkları yalnızca “dosya import ediyor mu?” seviyesinde değil; **event bus**, **güvenlik zinciri**, **DB merkezli state** ve **P2P delegasyon köprüleri** ile birlikte açıklar.

### 9.1 Statik Bağımlılık Matrisi (Import Grafı)

Aşağıdaki harita güncel iç bağımlılık yönünü gösterir (ok yönü: bağımlı modül → bağımlı olunan modül).

```
config.py              ←── (bağımlılık YOK — kök konfigürasyon)

core/db.py             ←── config.py
core/llm_client.py     ←── config.py
core/llm_metrics.py    ←── core/db.py, config.py
core/memory.py         ←── core/db.py, config.py
core/rag.py            ←── config.py

managers/security.py       ←── config.py
managers/code_manager.py   ←── managers/security.py, config.py
managers/github_manager.py ←── (yalnızca dış: PyGithub)
managers/system_health.py  ←── config.py
managers/web_search.py     ←── config.py
managers/package_info.py   ←── (yalnızca dış: httpx, packaging)
managers/todo_manager.py   ←── config.py

agent/definitions.py       ←── (salt metin sabiti)
agent/tooling.py           ←── pydantic (dış)
agent/base_agent.py        ←── config.py, core/llm_client.py, agent/tooling.py

agent/core/contracts.py    ←── (veri sözleşmeleri)
agent/core/event_stream.py ←── (event bus)
agent/core/memory_hub.py   ←── (hafif role/global bağlam merkezi)
agent/core/registry.py     ←── agent/base_agent.py
agent/core/supervisor.py   ←── agent/roles/*, agent/core/contracts.py,
                              agent/core/event_stream.py, agent/core/memory_hub.py

agent/roles/coder_agent.py      ←── agent/base_agent.py, managers/code_manager.py, agent/tooling.py
agent/roles/researcher_agent.py ←── agent/base_agent.py, managers/web_search.py, core/rag.py, agent/tooling.py
agent/roles/reviewer_agent.py   ←── agent/base_agent.py

agent/auto_handle.py       ←── managers/*, core/memory.py, core/rag.py
agent/sidar_agent.py       ←── config.py, core/*, managers/*, agent/auto_handle.py,
                              agent/definitions.py, agent/tooling.py,
                              agent/core/supervisor.py, agent/core/event_stream.py,
                              agent/roles/reviewer_agent.py

main.py                    ←── cli.py / web_server.py başlatımı (legacy tekli ajan akışı YOK)
cli.py                     ←── config.py, agent/sidar_agent.py
web_server.py              ←── config.py, agent/sidar_agent.py, core/*, managers/*,
                              agent/core/event_stream.py
github_upload.py           ←── (bağımsız araç)
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

- `agent/core/contracts.py` içinde `P2PMessage` ve `DelegationRequest`/`DelegationResult` sözleşmeleri, ajanlar arası nokta-atışı görev devri için veri modelini tanımlar.
- `agent/core/supervisor.py::_route_p2p(...)`, delegasyon isteklerini hedef ajanlara hop kontrollü (`max_hops`) biçimde taşır.
- Coder/Reviewer geri besleme döngüsü ve gerektiğinde araştırma/kod delegasyonu bu sözleşmeler üzerinden ilerleyerek QA odaklı P2P iş akışını kurar.

**Döngüsel bağımlılık:** Tespit edilmedi. `config.py` hâlâ bağımlılık ağacının kökü konumundadır.

**Ortak Kullanım Notu (Multi-Agent):** `Supervisor` ve rol ajanları; araç dispatch için `agent/tooling.py`, kalıcı konuşma verisi için `core/memory.py` + `core/db.py`, canlı durum akışı için `agent/core/event_stream.py`, maliyet/telemetri için `core/llm_metrics.py` katmanlarını birlikte kullanır.

---

## 10. Veri Akış Diyagramı

[⬆ İçindekilere Dön](#içindekiler)

### 10.1 Bir Chat Mesajının Ömrü

```
[Kullanıcı]
    │ mesaj gönderir (CLI / Web)
    ▼
[Auth Katmanı]
    │ HTTP: Bearer token middleware
    │ WS: zorunlu auth handshake (aksi: 1008 policy violation)
    ▼
[SidarAgent.respond(...)]
    │
    ├─► [SupervisorAgent.route(...)]   ← v3.0 Supervisor-first (legacy tekli akış YOK)
    │        │
    │        ├─► Araştırma/RAG görevi → ResearcherAgent
    │        └─► Kod görevi           → CoderAgent
    │                                   │
    │                                   ├─► (gerekirse) ReviewerAgent QA süzgeci
    │                                   │      ├─► Approve → devam
    │                                   │      └─► Reject  → Coder'a geri dönüş
    │                                   │                (MAX_QA_RETRIES=3 devre kesici)
    │                                   ▼
    │                          Tool dispatch (`agent/tooling.py`)
    │                                   │
    │                                   ├─► code_manager / security
    │                                   ├─► web_search / package_info
    │                                   ├─► github_manager
    │                                   ├─► rag / docs_* işlemleri
    │                                   └─► health / todo
    │
    ├─► [ConversationMemory.aadd(...)]
    │        └─► core/db.py → `messages`/`sessions` (user_id izolasyonlu)
    │
    ├─► [AgentEventBus.publish(...)]
    │        └─► WebSocket ile canlı thought/tool/status akışı
    │
    ├─► [LLM Metrics Collector]
    │        └─► token/latency/cost kaydı → `/api/budget`, `/metrics/llm`
    │
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

### 10.4 Kurumsal v3.0 Uçtan Uca Veri Hattı (5 Faz)

Aşağıdaki fazlar, v3.0'ın gerçek çalışma desenini (auth + async + event-driven + observability) özetler:

1. **Faz 1 — Ingestion & Auth Gate (CLI/HTTP/WS):**
   - İstek girişleri web tarafında zorunlu auth kontrollerinden (özellikle WebSocket `action=auth` handshake) geçer.
   - Doğrulama sonrası istek ajan yürütme hattına alınır; durum olayları `AgentEventBus` üzerinden yayınlanmaya başlar.

2. **Faz 2 — State & Context (DB + Token Budget):**
   - `ConversationMemory` kullanıcı bağlamını (`user_id`) doğrular, geçmiş oturum/mesajları DB katmanından yönetir.
   - Bağlam token boyutu izlenir; eşik aşımlarında özetleme/sıkıştırma adımlarıyla LLM'e taşınacak yük optimize edilir.

3. **Faz 3 — Supervisor Routing + P2P QA Loop:**
   - Supervisor niyet analizi sonrası işi `TaskEnvelope` ile uzman ajana yönlendirir.
   - Kod odaklı işlerde Coder çıktısı Reviewer süzgecinden geçer; gerekirse `DelegationRequest` + `_route_p2p` köprüsüyle Coder'a revizyon döner (`MAX_QA_RETRIES` devre kesici).

4. **Faz 4 — Zero-Trust Tool Execution Path:**
   - Araç çağrıları güvenlik denetiminden geçer (path/erişim seviyesi kontrolleri).
   - Web aramada motor fallback zinciri (Tavily → Google → DuckDuckGo), kod yürütmede Docker sandbox izolasyonu ve politika bazlı fallback uygulanır.

5. **Faz 5 — Observability Split + Persistence + Broadcast:**
   - LLM akışı yalnızca son kullanıcı yanıtı üretmez; paralelde telemetri (token/latency/cost) `core/llm_metrics.py` ile toplanır.
   - Bu metrikler `/api/budget` ve Prometheus format yüzeylerine aktarılır; event bus/WebSocket üzerinden canlı durum yayınları sürerken nihai içerik DB'ye kalıcı yazılır.

---

## 11. Mevcut Sorunlar ve Teknik Borç

[⬆ İçindekilere Dön](#içindekiler)

> **Not (v3.0.0):** Kurumsal/SaaS geçişiyle birlikte geçmiş sürümlerdeki temel mimari darboğazların büyük bölümü kapatılmıştır.
>
> JSON tabanlı bellek kalıcılığı, senkron çalışma kaynaklı blocking gecikmeleri, tekli ajan sınırlamaları ve izolasyon/güvenlik sertleşmesi gibi önceki nesil borçların çözüm kayıtları artık rapor içinde tekrar edilmek yerine **CHANGELOG.md** altında izlenebilir (traceable) biçimde tutulmaktadır.

### 11.1 Ödenmiş Teknik Borçlar (Resolved) ve Changelog Referansı

Aşağıdaki tarihsel borçlar **kapatılmış** olup ayrıntılı çözüm geçmişi için [CHANGELOG.md](./CHANGELOG.md) referans alınmalıdır:

- JSON tabanlı bellek/oturum kalıcılığından DB merkezli kalıcılığa geçiş,
- Senkron (blocking) ağ/işlem yollarından async çekirdeğe geçiş,
- Tekli ajan akışından Supervisor-first multi-agent + P2P QA mimarisine geçiş,
- Zero-Trust güvenlik katmanları (sandbox, path/symlink savunmaları, auth sertleşmesi),
- CI kalite kapıları (coverage hard gate, migration/sandbox doğrulama) olgunlaştırması,
- `core/memory.py` Sync/Async köprüsü (`_run_coro_sync`) kaldırılarak tam async dönüşüm,
- `agent/sidar_agent.py` ölü kod (`_react_loop`, `_tool_*`) temizliği (1.651 → 448 satır),
- Sandbox kaynak kotası standardizasyonu (`_resolve_sandbox_limits()` ile cgroups normalizasyonu).

### 11.2 Yeni Nesil Kurumsal Teknik Borçlar

| # | Sorun | Dosya/Alan | Etki | Öncelik | Durum |
|---|-------|------------|------|---------|-------|
| 1 | ~~Sync/Async köprü maliyeti (`_run_coro_sync`)~~ | `core/memory.py` | `_run_coro_sync` bridge tamamen kaldırıldı; `ConversationMemory` tüm metodlar (`add`, `initialize`, `get_history`, `set_active_user` vb.) tam `async/await` ile yeniden yazıldı. Event loop bloklaması riski ortadan kalktı. | Orta | ✅ **ÇÖZÜLDÜ** |
| 2 | ~~Vanilla JS UI ölçeklenme riski~~ | `web_ui/*.js` | **`seedUIStore()` IIFE** `app.js`'e eklenerek 12 paylaşımlı durum anahtarı (`isCurrentUserAdmin`, `isStreaming`, `msgCounter`, `currentRepo`, `currentBranch`, `defaultBranch`, `currentSessionId`, `attachedFileContent`, `attachedFileName`, `allSessions`, `cachedRepos`, `cachedBranches`) tek merkezde başlatıldı. Tüm `let` global değişkenleri (`isStreaming`, `currentSessionId`, `currentBranch`, `_cachedBranches` vb.) kaldırıldı. Çift yazma (double-write) anti-pattern'i ortadan kaldırıldı — `setUIState()` / `_setState()` tek kaynak oldu. `sidebar.js`'e `_getState` shimı eklenerek dosyalar arası tutarlılık sağlandı. `app.js` `isCurrentUserAdmin` global'i UIStore'a taşındı; `loadGitInfo()` doğrudan global atamaları bırakıp `setUIState()` kullanıyor. ESC kısayol ve DOMContentLoaded init kodları UIStore'u doğru okuyor. | Orta | ✅ **ÇÖZÜLDÜ** |
| 3 | Sağlayıcılar arası tool-calling şema farkları | `core/llm_client.py`, `agent/tooling.py` | `BaseLLMClient` soyut sınıfı ve sağlayıcıya özel alt sınıflar (`OllamaClient`, `GeminiClient`, `OpenAIClient`, `AnthropicClient`) oluşturularak if/else yüzeyi OOP'a taşındı. `build_provider_json_mode_config()` ile JSON mod konfigürasyonu standartlaştırıldı. Ancak provider-specific format farkları (streaming yapısı, response şeması) soyutlama içinde hâlâ mevcut; tam soyutlama sızıntısız değil. | Orta | 🟡 **KISMEN ÇÖZÜLDÜ** |
| 4 | ~~Sandbox kaynak kotası standardizasyonu (cgroups)~~ | `managers/code_manager.py` | `_resolve_sandbox_limits()` metodu eklenerek memory, cpus (→nano_cpus), pids_limit, timeout, network_mode tek merkezden normalize ediliyor. `SANDBOX_LIMITS` dict ile merkezi konfigürasyon desteği ve geçersiz değer koruması (pids_limit < 1 → 64, CPU ValueError handling) sağlandı. | Orta | ✅ **ÇÖZÜLDÜ** |
| 5 | ~~`sidar_agent.py` ölü kod temizliği~~ | `agent/sidar_agent.py` | `_react_loop` ve `_tool_*` metodları tamamen kaldırıldı. Dosya 1.651 satırdan 448 satıra indirildi; yalnızca `respond()`, `_try_multi_agent()`, `_build_context()`, `_summarize_memory()` gibi aktif Supervisor-first metodları kaldı. Bakım maliyeti önemli ölçüde azaldı. | Düşük | ✅ **ÇÖZÜLDÜ** |


## 12. `.env` Tam Değişken Referansı

[⬆ İçindekilere Dön](#içindekiler)

Aşağıdaki tablo projenin desteklediği tüm ortam değişkenlerini kapsar.

### 12.1 AI Sağlayıcı

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `AI_PROVIDER` | `ollama` | Aktif LLM sağlayıcı seçimi: `ollama`, `gemini`, `openai` veya `anthropic` |
| `GEMINI_API_KEY` | `""` | Gemini modu için zorunlu |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Kullanılacak Gemini model adı |
| `OLLAMA_URL` | `http://localhost:11434/api` | Ollama API adresi |
| `OLLAMA_TIMEOUT` | `30` | Ollama istek zaman aşımı (sn) |
| `CODING_MODEL` | `qwen2.5-coder:7b` | Ollama — kod görevleri modeli |
| `TEXT_MODEL` | `gemma2:9b` | Ollama — metin görevleri modeli |
| `OPENAI_API_KEY` | `""` | OpenAI (örn. GPT-4o ailesi) kullanımı için zorunlu API anahtarı |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model adı |
| `OPENAI_TIMEOUT` | `60` | OpenAI istek zaman aşımı (sn) |
| `LLM_MAX_RETRIES` | `2` | LLM çağrılarında maksimum yeniden deneme sayısı |
| `LLM_RETRY_BASE_DELAY` | `0.4` | Exponential backoff başlangıç gecikmesi (sn) |
| `LLM_RETRY_MAX_DELAY` | `4.0` | Yeniden deneme için üst gecikme sınırı (sn) |
| `ANTHROPIC_API_KEY` | `""` | Anthropic/Claude (örn. Claude 3.5 Sonnet) için zorunlu API anahtarı |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-latest` | Anthropic model adı |
| `ANTHROPIC_TIMEOUT` | `60` | Anthropic istek zaman aşımı (sn) |

> **Sağlayıcı Seçimi Notu:** Kod içinde ayrı bir `DEFAULT_LLM_PROVIDER` veya `ACTIVE_PROVIDER` değişkeni kullanılmamaktadır; aktif sağlayıcı doğrudan `AI_PROVIDER` ile belirlenir.

### 12.2 Güvenlik ve Erişim

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ACCESS_LEVEL` | `full` | `restricted` / `sandbox` / `full` |
| `API_KEY` | `""` | Web arayüzü/API için opsiyonel anahtar tabanlı yetkilendirme katmanı |
| `MEMORY_ENCRYPTION_KEY` | `""` | Fernet anahtarı — boşsa şifreleme kapalı |

### 12.3 GPU / Donanım

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `USE_GPU` | `true` | GPU kullanımını açar/kapar |
| `GPU_DEVICE` | `0` | Çoklu GPU'da hedef cihaz indeksi |
| `GPU_MEMORY_FRACTION` | `0.8` | VRAM fraksiyonu (0.1–1.0) |
| `GPU_MIXED_PRECISION` | `false` | FP16 mixed precision |
| `MULTI_GPU` | `false` | Dağıtık çoklu GPU modu |

### 12.4 Web Arayüzü

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `WEB_HOST` | `0.0.0.0` | Web sunucu bind adresi |
| `WEB_PORT` | `7860` | CPU mod web portu |
| `WEB_GPU_PORT` | `7861` | GPU mod web portu |

### 12.5 Web Arama

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `SEARCH_ENGINE` | `auto` | `auto` / `tavily` / `google` / `duckduckgo` |
| `TAVILY_API_KEY` | `""` | Tavily API anahtarı |
| `GOOGLE_SEARCH_API_KEY` | `""` | Google Custom Search API anahtarı |
| `GOOGLE_SEARCH_CX` | `""` | Google Custom Search Engine ID |
| `WEB_SEARCH_MAX_RESULTS` | `5` | Maksimum arama sonucu sayısı |
| `WEB_FETCH_TIMEOUT` | `15` | URL çekme zaman aşımı (sn) |
| `WEB_FETCH_MAX_CHARS` | `12000` | URL içerik karakter limiti (eski ad; `WEB_SCRAPE_MAX_CHARS` ile aynı değer) |
| `WEB_SCRAPE_MAX_CHARS` | `12000` | URL içerik karakter limiti (yeni/tercih edilen ad; `WEB_FETCH_MAX_CHARS` yoksa geçerli) |

### 12.6 RAG

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `RAG_DIR` | `data/rag` | Belge deposu dizini |
| `RAG_TOP_K` | `3` | Arama sonucu sayısı |
| `RAG_CHUNK_SIZE` | `1000` | Chunking karakter büyüklüğü |
| `RAG_CHUNK_OVERLAP` | `200` | Chunk örtüşme miktarı |
| `RAG_FILE_THRESHOLD` | `20000` | RAG deposuna ekleme önerisi eşiği (karakter) |

### 12.7 Hafıza ve ReAct

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `MAX_MEMORY_TURNS` | `20` | Bellekte tutulan max konuşma turu |
| `MEMORY_SUMMARY_KEEP_LAST` | `4` | Özetleme sırasında tam korunacak son mesaj sayısı (sliding window) |
| `MAX_REACT_STEPS` | `10` | ReAct döngüsü max adım sayısı |
| `REACT_TIMEOUT` | `60` | ReAct tek adım zaman aşımı (sn) |
| `SUBTASK_MAX_STEPS` | `5` | Alt ajan max adım sayısı |
| `AUTO_HANDLE_TIMEOUT` | `12` | AutoHandle araç zaman aşımı (sn) |

### 12.8 Loglama

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_FILE` | `logs/sidar_system.log` | Log dosya yolu |
| `LOG_MAX_BYTES` | `10485760` | Log dosya maksimum boyutu (10 MB) |
| `LOG_BACKUP_COUNT` | `5` | Tutulan log yedek sayısı |
| `DEBUG_MODE` | `false` | Açıksa Config özeti konsola yazdırılır |

### 12.9 Rate Limiting

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `RATE_LIMIT_WINDOW` | `60` | Pencere süresi (sn) |
| `RATE_LIMIT_CHAT` | `20` | Chat endpoint limit (istek/pencere) |
| `RATE_LIMIT_MUTATIONS` | `60` | Yazma endpoint limit |
| `RATE_LIMIT_GET_IO` | `30` | Okuma endpoint limit |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis bağlantı adresi (kalıcı/distro rate limiting) |

### 12.10 Veritabanı ve Auth (Kurumsal)

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/sidar.db` | Async DB bağlantı adresi (PostgreSQL için `postgresql+asyncpg://...`) |
| `DB_POOL_SIZE` | `5` | Async bağlantı havuzu taban boyutu |
| `DB_SCHEMA_VERSION_TABLE` | `schema_versions` | Uygulama şema sürüm tablosu adı |
| `DB_SCHEMA_TARGET_VERSION` | `1` | Hedef şema sürümü |

> **Auth Notu:** Güncel kod tabanında `.env` içinde ayrı `SECRET_KEY` / `AUTH_SECRET` değişkeni tanımlı değildir; kimlik doğrulama bearer token + DB tabanlı token yaşam döngüsü ile yönetilir.

### 12.11 Telemetri ve Zero-Trust Sandbox

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ENABLE_TRACING` | `false` | OpenTelemetry tracing aç/kapat |
| `OTEL_EXPORTER_ENDPOINT` | `http://localhost:4317` | OTLP exporter endpoint (collector/Jaeger) |
| `DOCKER_PYTHON_IMAGE` | `python:3.11-alpine` | REPL sandbox Docker imajı |
| `DOCKER_EXEC_TIMEOUT` | `10` | Docker REPL zaman aşımı (sn) |
| `DOCKER_RUNTIME` | `""` | Seçili container runtime (örn. `runsc`, `kata-runtime`) |
| `DOCKER_ALLOWED_RUNTIMES` | `"",runc,runsc,kata-runtime` | İzin verilen runtime listesi |
| `DOCKER_MICROVM_MODE` | `off` | Mikro-VM hazırlık modu (`off`,`gvisor`,`kata`) |
| `DOCKER_MEM_LIMIT` | `256m` | Sandbox konteyner bellek limiti |
| `DOCKER_NETWORK_DISABLED` | `true` | Sandbox için network kapatma anahtarı |
| `DOCKER_NANO_CPUS` | `1000000000` | Sandbox CPU kotası (~1 vCPU) |

> **Telemetri Notu:** Konfigürasyonda ayrı `ENABLE_TELEMETRY`/`METRICS_PORT` anahtarı yoktur; metrik ihracı uygulama endpoint'leri (`/metrics/llm`, `/metrics/llm/prometheus`, `/api/budget`) üzerinden sağlanır.

### 12.12 Çeşitli

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `RESPONSE_LANGUAGE` | `tr` | LLM yanıt dili |
| `SIDAR_ENV` | `""` | Ortam profili seçimi (`.env.<profil>` dosyasını temel `.env` üzerine yükler; örn. `production`) |
| `HF_TOKEN` | `""` | HuggingFace token (özel modeller) |
| `HF_HUB_OFFLINE` | `false` | HF Hub çevrimdışı mod |
| `GITHUB_TOKEN` | `""` | GitHub API token |
| `GITHUB_REPO` | `""` | Varsayılan GitHub repo (`owner/repo`) |
| `GITHUB_WEBHOOK_SECRET` | `""` | GitHub webhook HMAC doğrulama gizli anahtarı |
| `PACKAGE_INFO_TIMEOUT` | `12` | Paket bilgi HTTP zaman aşımı (sn) |
| `PACKAGE_INFO_CACHE_TTL` | `1800` | Paket bilgi cache süresi (sn) |
| `REVIEWER_TEST_COMMAND` | `bash run_tests.sh` | ReviewerAgent doğrulama aşamasında çalıştırılacak test komutu |
| `ENABLE_MULTI_AGENT` | `true` | **Sabitlenmiştir:** Legacy bayrak kaldırılmıştır; sistem daima Supervisor/Multi-Agent akışında çalışır (`.env` üzerinden değiştirilemez) |

### 12.13 Docker Compose Override Değişkenleri

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

<a id="13-olası-i̇yileştirmeler-v40-kurumsal-yol-haritası"></a>
## 13. Olası İyileştirmeler (v4.0 Kurumsal Yol Haritası)

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, v3.0 ile **zaten tamamlanan** kazanımları (DB geçişi, multi-agent, sandbox, observability) tekrar etmek yerine, bir sonraki kurumsal sıçrama için **yalnızca v4.0 hedeflerini** listeler.

| İyileştirme Alanı (v4.0) | Mevcut Durum (v3.0) | Önerilen Geliştirme |
|---|---|---|
| **Kubernetes/Helm ile Ölçekleme** | `docker-compose` tabanlı güçlü operasyon akışı mevcut | Çok tenantlı ve yüksek eşzamanlı yükte yatay ölçekleme için K8s deployment + HPA + Helm chart standardizasyonu |
| **LLM Gateway/Proxy Katmanı** | Sağlayıcılar `core/llm_client.py` içinde provider-bazlı yönetiliyor | LiteLLM/OpenRouter benzeri merkezi gateway ile model yönlendirme, kota/anahtar yönetimi, failover ve maliyet politikalarının tek noktadan yönetimi |
| **Kurumsal Vektör Veri Katmanı** | ChromaDB + FTS5/BM25 hibrit arama aktif | Büyük kurumsal korpuslarda pgvector/Milvus/Qdrant gibi dağıtık vektör altyapılarıyla ölçeklenebilir retrieval katmanı |
| **Dinamik Agent Swarm + Marketplace** | Coder/Researcher/Reviewer rolleri üretimde sabit tanımlı | Göreve göre dinamik uzman ajan türetimi (swarm), araç/ajan eklenti pazaryeri ve çalışma zamanı yetenek keşfi |
| **Reaktif Frontend ve Gelişmiş Admin UI** | Modüler Vanilla JS SPA + temel admin yüzeyleri mevcut | React/Next.js (veya Vue) ile stateful UI, canlı P2P ajan diyaloğu görselleştirme, tenant kota/anahtar yönetimi için gelişmiş yönetim paneli |

> **Kapsam Notu:** v3.0 ile tamamlanan “DB'ye geçiş, web arayüzü, güvenli kod çalıştırma, telemetri” gibi başlıklar artık teknik borç veya iyileştirme adayı değil; operasyonel olarak kapanmış yeteneklerdir.


---

## 14. Geliştirme Yol Haritası

[⬆ İçindekilere Dön](#içindekiler)

> **Not (v3.0.0 Sonrası Durum):** Projenin v3.0 vizyon hedeflerinin (Multi-agent geçişi, Çoklu Kullanıcı, DB kalıcılığı, Telemetri ve Zero-Trust Sandbox) tamamı gerçekleştirilmiş ve tarihsel kayıt olarak `CHANGELOG.md` dosyasına taşınmıştır. 
> 
> *Yeni nesil (v4.0 ve ötesi) geliştirme hedefleri ve yol haritası bu alanda planlanacaktır.*

---
## 15. Özellik-Gereksinim Matrisi

[⬆ İçindekilere Dön](#içindekiler)

Hangi özelliği kullanmak için hangi paket veya dış servisin kurulu/yapılandırılmış olması gerektiğini gösterir.

### 15.1 Çekirdek Özellikler (Her Zaman Zorunlu)

| Özellik | Zorunlu Paket / Servis | Zorunlu `.env` | Gerçekleşme Durumu |
|---------|----------------------|----------------|--------------------|
| CLI arayüzü | Python ≥ 3.10, `httpx`, `python-dotenv` | — | ✅ Tamamlandı |
| Web arayüzü | `fastapi`, `uvicorn`, `httpx` | `WEB_PORT` (opsiyonel) | ✅ Tamamlandı |
| **Multi-LLM Soyutlama Katmanı** (Ollama + Gemini + OpenAI + Anthropic) | `httpx`, `google-generativeai`, `openai`, `anthropic` | `AI_PROVIDER`, sağlayıcıya göre `*_API_KEY` | ✅ Tamamlandı |
| **Multi-Agent Orkestrasyonu (Supervisor)** | `agent/core/supervisor.py`, `agent/roles/*` | `ENABLE_MULTI_AGENT=True` (sabit; `.env` ile değiştirilemez) | ✅ Tamamlandı *(Legacy tekli ajan akışı devreden çıkarıldı)* |
| **Bağımsız Uzman Ajan Rolleri** (CoderAgent + ResearcherAgent) | `agent/base_agent.py`, `agent/roles/*` | Yapılandırma gerektirmez (daima aktif Supervisor orkestrasyonu) | ✅ Tamamlandı |
| Konuşma belleği | — (stdlib: `json`, `uuid`) | `MAX_MEMORY_TURNS` (opsiyonel) | ✅ Tamamlandı |
| Bellek şifreleme | `cryptography` | `MEMORY_ENCRYPTION_KEY` | ✅ Tamamlandı |
| GitHub entegrasyonu (PR + Issue yaşam döngüsü) | `PyGithub` | `GITHUB_TOKEN`, `GITHUB_REPO`, `GITHUB_WEBHOOK_SECRET` | ✅ Tamamlandı |
| GitHub Issue operasyon araçları (`list/create/comment/close`) | `PyGithub`, `agent/sidar_agent.py` tool zinciri | `GITHUB_TOKEN`, `GITHUB_REPO` | ✅ Tamamlandı |
| Proje denetimi (`audit`) | — (stdlib: `ast`, `pathlib`) | — | ✅ Tamamlandı |

### 15.2 Arama ve Web

| Özellik | Zorunlu Paket / Servis | Zorunlu `.env` | Gerçekleşme Durumu |
|---------|----------------------|----------------|--------------------|
| Tavily web arama | `httpx` | `TAVILY_API_KEY` | ✅ Tamamlandı |
| Google Custom Search | `httpx` | `GOOGLE_SEARCH_API_KEY`, `GOOGLE_SEARCH_CX` | ✅ Tamamlandı |
| DuckDuckGo (fallback) | `duckduckgo-search` | — | ✅ Tamamlandı |
| URL içerik çekme | `httpx`, `beautifulsoup4` | `WEB_FETCH_TIMEOUT` (opsiyonel) | ✅ Tamamlandı |
| PyPI sorgulama | `httpx`, `packaging` | — | ✅ Tamamlandı |
| npm sorgulama | `httpx` | — | ✅ Tamamlandı |
| **Gelişmiş Güvenlik ve Limitler** (Webhook HMAC + 1MB dosya limiti) | FastAPI middleware/endpoint güvenlik katmanları | `GITHUB_WEBHOOK_SECRET` | ✅ Tamamlandı |

### 15.3 RAG (Belge Deposu)

| Özellik | Zorunlu Paket / Servis | Zorunlu `.env` |
|---------|----------------------|----------------|
| Keyword arama (fallback) | — (stdlib) | — |
| BM25 arama | `rank_bm25` | — |
| Vektör arama (CPU) | `chromadb` | `RAG_DIR` (opsiyonel) |
| Vektör arama (GPU) | `chromadb`, `sentence-transformers`, `torch` (CUDA) | `USE_GPU=true`, `GPU_DEVICE` |
| GPU FP16 embedding | yukarıdaki + `torch.amp` | `GPU_MIXED_PRECISION=true` |
| HuggingFace model cache | `sentence-transformers` | `HF_TOKEN` (opsiyonel) |
| HF çevrimdışı mod | — | `HF_HUB_OFFLINE=true` |

<a id="154-sistem-i̇zleme-ve-gpu"></a>
### 15.4 Sistem İzleme ve GPU

| Özellik | Zorunlu Paket / Servis | Zorunlu `.env` |
|---------|----------------------|----------------|
| CPU/RAM izleme | `psutil` | — |
| CUDA tespiti | `torch` | — |
| GPU sıcaklık / kullanım | `pynvml` | — |
| VRAM fraksiyonu ayarı | `torch` | `GPU_MEMORY_FRACTION` |
| Mixed precision | `torch` ≥ 1.6 | `GPU_MIXED_PRECISION=true` |
| WSL2 GPU erişimi | Windows NVIDIA sürücüsü + CUDA 12.x wheel | — |

### 15.5 Kod Yürütme

| Özellik | Zorunlu Paket / Servis | Zorunlu `.env` |
|---------|----------------------|----------------|
| Docker REPL (izolasyon) | `docker` SDK + **çalışan Docker daemon** | `DOCKER_PYTHON_IMAGE` (opsiyonel) |
| Subprocess REPL (fallback) | — (stdlib) | `ACCESS_LEVEL=sandbox\|full` |
| Shell komutu (`run_shell`) | — (stdlib) | `ACCESS_LEVEL=full` |

### 15.6 Özellik Profilleri

Minimum kurulum senaryolarına göre gereken paket kümeleri:

| Profil | Gerekli Paketler | Gerçekleşme Durumu |
|--------|-----------------|--------------------|
| **Minimal CLI** (Ollama + keyword RAG) | `httpx`, `python-dotenv`, `pydantic`, `beautifulsoup4`, `packaging` | ✅ Aktif |
| **Tam CLI** (+ BM25 + GitHub + web arama) | yukarıdaki + `rank_bm25`, `PyGithub`, `duckduckgo-search` | ✅ Aktif |
| **Web Sunucu** | yukarıdaki + `fastapi`, `uvicorn` | ✅ Aktif |
| **GPU RAG** | yukarıdaki + `chromadb`, `sentence-transformers`, `torch` (CUDA) | ✅ Aktif |
| **Gemini Modu** | yukarıdaki + `google-generativeai` | ✅ Aktif |
| **Çoklu Sağlayıcı Deploy** | tüm opsiyonel dahil + Docker + Redis + `openai` + `anthropic` | ✅ Aktif |
| **Observability Stack** | `prometheus-client` + `opentelemetry-*` + (opsiyonel) Prometheus/Grafana servisleri | ✅ Aktif |


### 15.7 v3.0 Vizyon Gereksinimleri (Planlanan)

| Özellik | Hedef Gereksinim | Durum |
|---------|------------------|-------|
| **Reviewer (QA) Ajanı** | `agent/roles/reviewer_agent.py`, test/kalite geri bildirim döngüsü, Supervisor entegrasyonu | 🟡 Olgunlaştırma Aşaması |
| **Eski Mimarinin Kaldırılması** | Legacy `sidar_agent.py` akışının deprecate edilmesi, Supervisor-first tek omurga | ✅ Tamamlandı |
| **Gelişmiş Maliyet (Token) İzleme** | Sağlayıcı bazlı token/maliyet/rate-limit telemetrisi + dashboard | ✅ Tamamlandı (Grafana dashboard + provisioning aktif) |

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
| `GPU_MEMORY_FRACTION` aralık dışı | `config.py:151-157` | 0.1–1.0 arasında değer ver |

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

- **Final Doğrulama Tarihi:** 2026-03-15 (Güncel)
- **Durum:** Tüm kurumsal özellikler (Auth, Multi-User, Sandbox, Observability) kod düzeyinde doğrulanmıştır. Rapor, tüm kaynak dosyalar satır satır incelenerek güncel satır sayıları ve eksik dosya girişleriyle tam uyuma kavuşturulmuştur.
- **Öne Çıkan Başarılar:** Multi-agent P2P delegasyon altyapısı ve %95 test kapsamı zorunluluğu projenin üretim kararlılığını garanti altına almıştır.
- **Arşiv Notu:** Detaylı sürüm bazlı değişiklik geçmişi ve çözülen teknik borçlar için `CHANGELOG.md` dosyasını referans alınız.