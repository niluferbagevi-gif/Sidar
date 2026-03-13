# SİDAR Projesi — Kapsamlı Kod Analiz Raporu (Güncel)

> **Rapor Tarihi:** 2026-03-12
> **Son Güncelleme:** 2026-03-11 (v3.0.0 — **Final Sürüm (Production-Ready):** Kurumsal/SaaS v3.0 kapsamı (migration, auth, observability, sandbox hazırlıkları) operasyonel olarak kapatıldı)
> **Proje Sürümü:** 3.0.0
> **Analiz Kapsamı:** Tüm kaynak dosyaları satır satır incelenmiştir. Toplam Python kaynak: ~13.361 satır (tests hariç, güncel ölçüm); Test: **20.904** satır; Web UI: **4.160** satır.

---

<a id="içindekiler"></a>
## İçindekiler
- [1. Proje Genel Bakışı](#1-proje-genel-bakışı)
  - [Temel Özellikler](#temel-özellikler)
- [2. Proje Dosya Yapısı](#2-proje-dosya-yapısı)
- [3. Modül Bazında Detaylı Analiz](#3-modül-bazında-detaylı-analiz)
  - [3.1 `config.py` — Merkezi Yapılandırma (589 satır)](#31-configpy-merkezi-yapılandırma-589-satır)
  - [3.2 `main.py` — Akıllı Başlatıcı (225 satır)](#32-mainpy-akıllı-başlatıcı-225-satır)
  - [3.3 `cli.py` — CLI Arayüzü (232 satır)](#33-clipy-cli-arayüzü-232-satır)
  - [3.4 `web_server.py` — FastAPI Web Sunucusu (1.376 satır)](#34-web_serverpy-fastapi-web-sunucusu-1376-satır)
  - [3.5 `agent/sidar_agent.py` — Ana Ajan (1.651 satır)](#35-agentsidar_agentpy-ana-ajan-1651-satır)
  - [3.6 `agent/auto_handle.py` — Hızlı Yönlendirici (601 satır)](#36-agentauto_handlepy-hızlı-yönlendirici-601-satır)
  - [3.7 `agent/definitions.py` — Ajan Tanımları (165 satır)](#37-agentdefinitionspy-ajan-tanımları-165-satır)
  - [3.7b `agent/tooling.py` — Araç Kayıt ve Şema Yöneticisi (266 satır)](#37b-agenttoolingpy-araç-kayıt-ve-şema-yöneticisi-266-satır)
  - [3.7c `agent/base_agent.py` — Temel Ajan Sınıfı (55 satır)](#37c-agentbase_agentpy-temel-ajan-sınıfı-55-satır)
  - [3.7d `agent/core/supervisor.py` — Yönlendirici (Supervisor) Ajan (164 satır)](#37d-agentcoresupervisorpy-yönlendirici-supervisor-ajan-164-satır)
  - [3.7e `agent/core/contracts.py`, `event_stream.py`, `memory_hub.py`, `registry.py` — Çekirdek Ajan İletişim Altyapısı](#37e-agentcorecontractspy-event_streampy-memory_hubpy-registrypy-çekirdek-ajan-i̇letişim-altyapısı)
  - [3.7f `agent/roles/` — Uzman Ajan Rolleri (Coder, Researcher & Reviewer)](#37f-agentroles-uzman-ajan-rolleri-coder-researcher-reviewer)
  - [3.8 `core/llm_client.py` — LLM İstemcisi (Ollama + Gemini + OpenAI + Anthropic, 839 satır)](#38-corellm_clientpy-llm-i̇stemcisi-ollama-gemini-openai-anthropic-839-satır)
  - [3.9 `core/memory.py` — Konuşma Belleği (DB tabanlı, v3.0)](#39-corememorypy-konuşma-belleği-db-tabanlı-v30)
  - [3.10 `core/rag.py` — RAG Motoru (783 satır)](#310-coreragpy-rag-motoru-783-satır)
  - [3.11 `managers/security.py` — Güvenlik Yöneticisi (290 satır)](#311-managerssecuritypy-güvenlik-yöneticisi-290-satır)
  - [3.12 `managers/code_manager.py` — Kod Yöneticisi (805 satır)](#312-managerscode_managerpy-kod-yöneticisi-805-satır)
  - [3.13 `managers/github_manager.py` — GitHub Yöneticisi (644 satır)](#313-managersgithub_managerpy-github-yöneticisi-644-satır)
  - [3.14 `managers/system_health.py` — Sistem Sağlık Yöneticisi (475 satır)](#314-managerssystem_healthpy-sistem-sağlık-yöneticisi-475-satır)
  - [3.15 `managers/web_search.py` — Web Arama Yöneticisi (387 satır)](#315-managersweb_searchpy-web-arama-yöneticisi-387-satır)
  - [3.16 `managers/package_info.py` — Paket Bilgi Yöneticisi (322 satır)](#316-managerspackage_infopy-paket-bilgi-yöneticisi-322-satır)
  - [3.17 `managers/todo_manager.py` — Görev Takip Yöneticisi (451 satır)](#317-managerstodo_managerpy-görev-takip-yöneticisi-451-satır)
  - [3.18 `web_ui/` — Web Arayüzü (Toplam ~4.160 satır)](#318-web_ui-web-arayüzü-toplam-4160-satır)
  - [3.19 `github_upload.py` — GitHub Yükleme Aracı (294 satır)](#319-github_uploadpy-github-yükleme-aracı-294-satır)
  - [3.20 `core/db.py` — Veritabanı ve Çoklu Kullanıcı Altyapısı](#320-coredbpy-veritabanı-ve-çoklu-kullanıcı-altyapısı)
  - [3.21 `core/llm_metrics.py` — Telemetri ve Bütçe Yönetimi](#321-corellm_metricspy-telemetri-ve-bütçe-yönetimi)
  - [3.22 `migrations/` ve `scripts/` — Geçiş ve Operasyon Araçları](#322-migrations-ve-scripts-geçiş-ve-operasyon-araçları)
  - [3.23 `docker/` ve `runbooks/` — Telemetri ve Production Altyapı Dosyaları](#323-docker-ve-runbooks-telemetri-ve-production-altyapı-dosyaları)
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
- [13. Olası İyileştirmeler (v4.0 Kurumsal Yol Haritası)](#13-olası-i̇yileştirmeler-v40-kurumsal-yol-haritası)
- [14. Geliştirme Yol Haritası ve v3.0 Vizyonu (v2.11+)](#14-geliştirme-yol-haritası-ve-v30-vizyonu-v211)
  - [14.1 Eski Mimarinin Emekliye Ayrılması (Deprecation)](#141-eski-mimarinin-emekliye-ayrılması-deprecation)
  - [14.2 Reviewer (QA) Ajanının Olgunlaştırılması](#142-reviewer-qa-ajanının-olgunlaştırılması)
  - [14.3 Bütçe ve Token Yönetim Paneli (Dashboard)](#143-bütçe-ve-token-yönetim-paneli-dashboard)
  - [14.4 Kalıcı Çoklu Kullanıcı (Multi-User) Altyapısı](#144-kalıcı-çoklu-kullanıcı-multi-user-altyapısı)
  - [14.5 Test Kapsamının %95+ Seviyesine Zorlanması](#145-test-kapsamının-%95-seviyesine-zorlanması)
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
- [18. Doğrulanmış Çözüm Özeti (2026-03-10 Audit #8 — Güncel)](#18-doğrulanmış-çözüm-özeti-2026-03-10-audit-8-güncel)
  - [18.1 Önceki Raporda "Çözüldü" Olarak İşaretlenmiş ve Doğrulanan Maddeler](#181-önceki-raporda-çözüldü-olarak-i̇şaretlenmiş-ve-doğrulanan-maddeler)
  - [18.2 Rapor Düzeltme Özeti — Audit #2 (2026-03-08, Sürüm v2.10.0)](#182-rapor-düzeltme-özeti-audit-2-2026-03-08-sürüm-v2100)
  - [18.3 Rapor Düzeltme Özeti — Audit #3 (2026-03-08, Güncel)](#183-rapor-düzeltme-özeti-audit-3-2026-03-08-güncel)
  - [18.4 Rapor Düzeltme Özeti — Audit #4 (2026-03-10)](#184-rapor-düzeltme-özeti-audit-4-2026-03-10)
  - [18.5 Rapor Düzeltme Özeti — Audit #6 (2026-03-10)](#185-rapor-düzeltme-özeti-audit-6-2026-03-10)
  - [18.6 Rapor Düzeltme Özeti — Audit #7 (2026-03-10)](#186-rapor-düzeltme-özeti-audit-7-2026-03-10)
  - [18.7 Rapor Düzeltme Özeti — Audit #8 (2026-03-10)](#187-rapor-düzeltme-özeti-audit-8-2026-03-10)
  - [18.8 Rapor Düzeltme Özeti — Audit #9 (2026-03-11)](#188-rapor-düzeltme-özeti-audit-9-2026-03-11)
  - [18.9 Rapor Düzeltme Özeti — Audit #10 (2026-03-11)](#189-rapor-düzeltme-özeti-audit-10-2026-03-11)
  - [Session 2026-03-11 — Multi-Agent Geçiş Sertleştirme ve Reviewer QA Döngüsü](#session-2026-03-11-multi-agent-geçiş-sertleştirme-ve-reviewer-qa-döngüsü)
  - [Session 2026-03-11 — LLM Bütçe ve Maliyet Dashboard Geliştirmesi](#session-2026-03-11-llm-bütçe-ve-maliyet-dashboard-geliştirmesi)
  - [Session 2026-03-11 — Legacy ReAct Akışının Emekliye Ayrılması](#session-2026-03-11-legacy-react-akışının-emekliye-ayrılması)
  - [Session 2026-03-11 — Multi-User Faz 1: Veritabanı İskeleti](#session-2026-03-11-multi-user-faz-1-veritabanı-i̇skeleti)
  - [Session 2026-03-11 — Multi-User Faz 2: Memory Katmanının DB'ye Taşınması](#session-2026-03-11-multi-user-faz-2-memory-katmanının-dbye-taşınması)
  - [Session 2026-03-11 — Multi-User Faz 3: DB Tabanlı Authentication ve Session İzolasyonu](#session-2026-03-11-multi-user-faz-3-db-tabanlı-authentication-ve-session-i̇zolasyonu)
  - [Session 2026-03-11 — Multi-User Faz 3 Kapanış: Web UI Auth Entegrasyonu](#session-2026-03-11-multi-user-faz-3-kapanış-web-ui-auth-entegrasyonu)
  - [Session 2026-03-11 — P2P Multi-Agent Delegasyon ve Dinamik Reviewer QA](#session-2026-03-11-p2p-multi-agent-delegasyon-ve-dinamik-reviewer-qa)
  - [Session 2026-03-11 — Faz 5: Zero-Trust Sandbox ve Kaynak Kısıtları](#session-2026-03-11-faz-5-zero-trust-sandbox-ve-kaynak-kısıtları)
  - [Session 2026-03-11 — Observability / Canlı Ajan Durum Akışı](#session-2026-03-11-observability-canlı-ajan-durum-akışı)
  - [Session 2026-03-11 — Quality Gate: Coverage %95 Zorunluluğu](#session-2026-03-11-quality-gate-coverage-%95-zorunluluğu)
  - [Session 2026-03-11 — Telemetri, Maliyet Yönetimi ve Dashboard Altyapısı](#session-2026-03-11-telemetri-maliyet-yönetimi-ve-dashboard-altyapısı)
  - [Session 2026-03-11 — Frontend (Web UI) Admin Paneli ve Kurumsal Sürüme Geçiş (v3.0 Tamamlandı)](#session-2026-03-11-frontend-web-ui-admin-paneli-ve-kurumsal-sürüme-geçiş-v30-tamamlandı)
  - [18.10 Audit #11 (Session 2026-03-11) — Güvenlik ve Kararlılık Kapanışı](#1810-audit-11-session-2026-03-11-güvenlik-ve-kararlılık-kapanışı)
  - [Session 2026-03-11 — Üretim Geçiş Araçları ve Alembic Sertleştirmesi](#session-2026-03-11-üretim-geçiş-araçları-ve-alembic-sertleştirmesi)
  - [Session 2026-03-11 — Production Sertifikasyon Kalan Maddeler (QA + Sandbox + Migration Disiplini)](#session-2026-03-11-production-sertifikasyon-kalan-maddeler-qa-sandbox-migration-disiplini)

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

```text
sidar_project/
├── .github/workflows/         # CI/CD süreçleri (ci.yml, migration-cutover-checks.yml)
├── main.py                    # Akıllı başlatıcı (wizard + --quick mod)
├── cli.py                     # CLI terminal arayüzü giriş noktası
├── web_server.py              # FastAPI web sunucusu (WebSocket streaming)
├── config.py                  # Merkezi yapılandırma (v3.0.0)
├── github_upload.py           # GitHub otomatik yükleme aracı
├── Dockerfile                 # CPU + GPU çift mod Dockerfile
├── docker-compose.yml         # 5 servis + Prometheus & Grafana entegrasyonu
├── environment.yml            # Conda bağımlılıkları
├── requirements.txt           # Pip temel bağımlılıkları
├── requirements-dev.txt       # Geliştirme ve test bağımlılıkları
├── pyproject.toml             # Ruff + Mypy kalite standartları
├── pytest.ini                 # Pytest konfigürasyonu
├── alembic.ini                # Veritabanı geçiş (migration) ayarları
├── run_tests.sh               # Kapsam ve test çalıştırıcı betik
├── install_sidar.sh           # Otomatik kurulum betiği
│
├── agent/
│   ├── __init__.py
│   ├── sidar_agent.py         # Ana ajan bağlayıcısı
│   ├── base_agent.py          # BaseAgent soyut sınıfı (multi-agent iskeleti)
│   ├── auto_handle.py         # Anahtar kelime tabanlı hızlı yönlendirici
│   ├── definitions.py         # Sistem istemi ve ajan kimliği
│   ├── tooling.py             # Araç kayıt + Pydantic şema yöneticisi
│   ├── core/
│   │   ├── __init__.py
│   │   ├── supervisor.py      # Yönlendirici ve orkestrasyon ajanı
│   │   ├── contracts.py       # TaskEnvelope/TaskResult + P2P delegasyon sözleşmeleri
│   │   ├── event_stream.py    # Ajan olay veriyolu (canlı durum akışı)
│   │   ├── memory_hub.py      # Multi-agent bellek yönetim merkezi
│   │   └── registry.py        # Ajan ve yetenek kayıt defteri
│   └── roles/
│       ├── __init__.py
│       ├── coder_agent.py     # Dosya/kod odaklı uzman ajan
│       ├── researcher_agent.py # Web + RAG odaklı uzman ajan
│       └── reviewer_agent.py  # Test koşturan, kod kalitesini denetleyen QA ajanı
│
├── core/
│   ├── __init__.py
│   ├── db.py                  # Veritabanı bağlantısı, kullanıcı ve kota tabloları
│   ├── llm_client.py          # Ollama + Gemini + OpenAI + Anthropic asenkron istemci
│   ├── llm_metrics.py         # Token, maliyet ve Prometheus metrik toplayıcısı
│   ├── memory.py              # Kalıcı çok oturumlu bellek (DB destekli)
│   └── rag.py                 # ChromaDB + BM25 hibrit RAG motoru
│
├── docker/                    # Gözlemlenebilirlik (observability) ayarları
│   ├── grafana/               # Dashboard ve provisioning dosyaları
│   └── prometheus/            # Scrape yapılandırması
│
├── managers/
│   ├── __init__.py
│   ├── code_manager.py        # Dosya I/O + Docker REPL + denetim
│   ├── security.py            # OpenClaw erişim kontrol sistemi
│   ├── github_manager.py      # GitHub API entegrasyonu
│   ├── system_health.py       # CPU/RAM/GPU izleme
│   ├── web_search.py          # Tavily + Google + DuckDuckGo arama
│   ├── package_info.py        # PyPI + npm + GitHub Releases
│   └── todo_manager.py        # Görev takip yöneticisi
│
├── migrations/                # Alembic veritabanı geçiş dosyaları
│   ├── env.py
│   ├── script.py.mako
│   └── versions/              # 0001_baseline_schema.py vb. şema versiyonları
│
├── scripts/                   # Operasyon, test ve metrik betikleri
│   ├── audit_metrics.sh       # Kod satır sayısı ve audit metrikleri üretici
│   ├── check_empty_test_artifacts.sh # CI kalite kapısı kontrolleri
│   ├── collect_repo_metrics.sh
│   ├── install_host_sandbox.sh # Zero-trust sandbox (gVisor/Kata) hazırlığı
│   ├── load_test_db_pool.py   # DB bağlantı havuzu yük testi
│   └── migrate_sqlite_to_pg.py # SQLite'tan PostgreSQL'e geçiş aracı
│
├── runbooks/                  # Operasyonel kılavuzlar
│   └── production-cutover-playbook.md # Kurumsal sürüme geçiş yönergeleri
│
├── web_ui/                    # Modüler Web UI
│   ├── index.html
│   ├── style.css
│   ├── chat.js                # WebSocket streaming, canlı durum akışı
│   ├── sidebar.js             # Oturum yönetimi
│   ├── rag.js                 # RAG belge UI
│   └── app.js                 # Uygulama başlatma, auth, bütçe yönetimi
│
├── tests/                     # Kapsamlı test paketi (~70 test modülü)
│   ├── conftest.py            # Ortak test fixture'ları
│   └── test_*.py              # Modül bazlı ve entegrasyon testleri
│
├── data/                      # RAG ve varsayılan yerel depolama dosyaları
├── .coveragerc                # Coverage kalite kapısı kuralları (%95 eşik)
├── .env.example               # Ortam değişkeni şablonu
├── CHANGELOG.md               # Sürüm notları ve değişiklik geçmişi
├── CLAUDE.md                  # Geliştirici rehberi
├── PROJE_RAPORU.md            # Ana mimari ve denetim raporu
├── README.md                  # Proje tanıtım ve kurulum belgesi
├── RFC-MultiAgent.md          # Multi-agent mimari tasarım dokümanı
└── SIDAR.md                   # Sistem promptları ve proje kuralları
```

---

## 3. Modül Bazında Detaylı Analiz

[⬆ İçindekilere Dön](#içindekiler)

---

### 3.1 `config.py` — Merkezi Yapılandırma (589 satır)

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

### 3.2 `main.py` — Akıllı Başlatıcı (225 satır)

**Amaç:** Sidar'ı başlatmak için etkileşimli sihirbaz veya `--quick` hızlı mod sağlar.

**Temel Fonksiyonlar:**

| Fonksiyon | Açıklama |
|-----------|----------|
| `print_banner()` | ANSI renkli ASCII art banner |
| `ask_choice(prompt, options, default_key)` | Güvenli menü seçimi (geçersiz giriş döngüsü) |
| `ask_text(prompt, default)` | Metin girişi (Enter = varsayılan) |
| `confirm(prompt, default_yes)` | Y/n onay istemi |
| `preflight(provider)` | `.env` varlığı, Python sürümü, Ollama/Gemini/OpenAI/Anthropic erişim kontrolü |
| `build_command(mode, provider, level, log, extra_args)` | `cli.py` veya `web_server.py` komutu oluşturur |
| `_stream_pipe(pipe, file_obj, prefix, color, mirror)` | Thread'de pipe akışını bellek dostu okur |
| `_run_with_streaming(cmd, child_log_path)` | Çocuk süreç stdout/stderr canlı yayınlar; opsiyonel dosya logu |
| `execute_command(cmd, capture_output, child_log_path)` | `subprocess.run` veya streaming ile çalıştırır |
| `run_wizard()` | 4 adımlı etkileşimli menü |

**`--quick` Mod Argümanları:**
```
python main.py --quick web --host 0.0.0.0 --port 7860
python main.py --quick cli --provider gemini --level sandbox
python main.py --quick web --capture-output --child-log logs/child.log
```

**Mimari Not:** `DummyConfig` fallback sınıfı ile `config.py` olmadan da çalışır.

---

### 3.3 `cli.py` — CLI Arayüzü (232 satır)

**Amaç:** Terminal tabanlı etkileşimli REPL döngüsü.

**Mimari Düzeltme:**
Eski kodda `while` döngüsü içinde her turda `asyncio.run()` çağrılıyordu; bu `asyncio.Lock` ömrünü bozuyordu. Yeni yapıda tüm döngü tek bir `async` fonksiyona (`_interactive_loop_async`) alınmıştır — lock tüm oturum boyunca aynı event loop'ta yaşar.

**Desteklenen Nokta Komutları:**

| Komut | Eylem |
|-------|-------|
| `.status` | Sistem durumu |
| `.clear` / `/clear` / `/reset` | Konuşma belleğini temizle |
| `.audit` | Proje denetimi |
| `.health` | Sistem sağlık raporu |
| `.gpu` | GPU belleği optimize et |
| `.github` | GitHub bağlantı durumu |
| `.level` / `.level <seviye>` | Erişim seviyesini göster / değiştir |
| `.web` | Web arama durumu |
| `.docs` | Belge deposunu listele |
| `.help` | Yardım |
| `.exit` / `.q` | Çıkış |

**Doğrudan Komutlar (AutoHandle üzerinden):**
- `web'de ara: <sorgu>`, `pypi: <paket>`, `npm: <paket>`, `github releases: <owner/repo>`, `docs ara: <sorgu>`, `stackoverflow: <sorgu>`, `belge ekle <url>`

**CLI Argümanları:**
- `--level`, `--provider`, `--model`, `--log`, `-c/--command`, `--status`

---

### 3.4 `web_server.py` — FastAPI Web Sunucusu (1.376 satır)

**Amaç:** WebSocket destekli asenkron chat, DB tabanlı kimlik doğrulama ve kurumsal metrik/bütçe uçlarını tek API yüzeyinde sunar.

**Kurumsal v3.0 Öne Çıkanlar:**
- **Bearer Token middleware:** HTTP isteklerinde zorunlu kimlik doğrulama (`basic_auth_middleware`).
- **Auth uçları:** `/auth/register`, `/auth/login`, `/auth/me`.
- **Bütçe/telemetri uçları:** `/api/budget`, `/metrics/llm`, `/metrics/llm/prometheus`.
- **WebSocket Auth Handshake:** `/ws/chat` bağlantısında ilk mesajın `action="auth"` ve geçerli token içermesi zorunlu; aksi durumda policy violation ile bağlantı kapatılır.

**Temel API Endpoint'leri (özet):**

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/` | GET | `index.html` servis et |
| `/static/*` | GET | JS/CSS statik dosyaları |
| `/auth/register` | POST | Yeni kullanıcı kaydı |
| `/auth/login` | POST | Giriş + access token üretimi |
| `/auth/me` | GET | Aktif kullanıcı kimliği |
| `/ws/chat` | WS | Auth handshake + çift yönlü chat akışı |
| `/api/budget` | GET | LLM maliyet/token/latency bütçe özeti |
| `/metrics/llm` | GET | LLM metrik snapshot (JSON) |
| `/metrics/llm/prometheus` | GET | Prometheus formatında LLM metrikleri |
| `/sessions*` | GET/POST/DELETE | Kullanıcıya izole oturum CRUD işlemleri |

---

### 3.5 `agent/sidar_agent.py` — Ana Ajan (1.651 satır)

**Amaç:** ReAct döngüsü, araç yönetimi, akış yönetimi ve özetleme mantığı.

**Araç Kataloğu (45+ araç):**

| Kategori | Araçlar |
|----------|---------|
| Dosya İşlemleri | `list_dir`, `read_file`, `write_file`, `patch_file`, `glob_search`, `grep_files` |
| Kod Yürütme | `execute_code`, `run_shell` / `bash` / `shell` |
| GitHub — PR/Branch | `github_commits`, `github_info`, `github_read`, `github_list_files`, `github_write`, `github_create_branch`, `github_create_pr`, `github_smart_pr`, `github_list_prs`, `github_get_pr`, `github_comment_pr`, `github_close_pr`, `github_pr_files`, `github_search_code`, `github_pr_diff`, `github_list_repos` |
| GitHub — Issue | `github_list_issues`, `github_create_issue`, `github_comment_issue`, `github_close_issue` |
| Web | `web_search`, `fetch_url`, `search_docs`, `search_stackoverflow` |
| Paket Bilgi | `pypi`, `pypi_compare`, `npm`, `gh_releases`, `gh_latest` |
| RAG | `docs_search`, `docs_add`, `docs_add_file`, `docs_list`, `docs_delete` |
| Sistem | `health`, `gpu_optimize`, `audit`, `get_config`, `print_config_summary` |
| Görev | `todo_write`, `todo_read`, `todo_update`, `scan_project_todos` |
| Alt Ajan | `subtask` / `agent`, `parallel` |

**ReAct Döngüsü Akışı:**
```
kullanıcı mesajı
    → AutoHandle (hızlı yönlendirici)
        → [eşleşirse] doğrudan yanıt döner
        → [eşleşmezse] LLM çağrısı
            → JSON: {thought, tool, argument}
                → araç çalıştırılır
                    → sonuç belleğe eklenir
                        → [final_answer değilse] LLM tekrar çağrılır (maks. MAX_REACT_STEPS)
                            → final_answer → kullanıcıya akış
```

**Önemli Tasarım Kararları:**

1. **`_DIRECT_ROUTE_ALLOWED_TOOLS`:** `list_dir`, `read_file`, `health` vb. tek adımlı güvenli araçlar ReAct döngüsüne girmeden doğrudan çalıştırılır. Gereksiz LLM çağrısını önler.

2. **Yapısal Çıktı (Pydantic):** LLM çıktısı `ToolCall` modeli ile doğrulanır. Geçersiz JSON → `_FMT_SYS_ERR` formatında belleğe yazılır.

3. **Döngü Tespiti:** Aynı araç 3 kez arka arkaya çağrılırsa uyarı üretilir ve `final_answer`'a yönlendirilir.

4. **`_instructions_cache`:** `SIDAR.md` ve `CLAUDE.md` dosyaları mtime tabanlı cache ile okunur; her turda disk I/O yapılmaz.

5. **Bellek Özetleme:** `ConversationMemory.needs_summarization()` True döndürdüğünde ajan LLM'i özetleme için çağırır; eski turlar tek bir "KONUŞMA ÖZETİ" mesajıyla değiştirilir.

6. **`subtask` aracı:** Alt görev için bağımsız ajan döngüsü açar; `SUBTASK_MAX_STEPS` (varsayılan 5) adımla sınırlıdır.

7. **`parallel` aracı:** Birden fazla araç argümanını eşzamanlı `asyncio.gather` ile çalıştırır.

---

### 3.6 `agent/auto_handle.py` — Hızlı Yönlendirici (601 satır)

**Amaç:** Kullanıcı mesajındaki ortak kalıpları regex ile tanıyarak LLM döngüsüne girmeden cevap verir.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l agent/auto_handle.py` çıktısına göre **601** olarak ölçülmüştür.

**Mimari:**
- `AutoHandle.handle(text)` → `(işlendi_mi: bool, yanıt: str)` döner
- Senkron araçlar `asyncio.to_thread` ile event loop bloklanmadan çalıştırılır
- `AUTO_HANDLE_TIMEOUT` (varsayılan 12 sn) ile her araç çağrısı zaman aşımına karşı korunur

**`_MULTI_STEP_RE` Koruyucu:** "ardından", "önce...sonra", numaralı adım kalıpları algılanırsa AutoHandle çıkar ve ReAct'a bırakır.

**İşlenen Kalıplar:**

| Kategori | Regex Tetikleyici Örnekler |
|----------|---------------------------|
| Nokta komutları | `.status`, `.health`, `.clear`, `.audit`, `.gpu` |
| Dosya okuma | `dosyayı oku`, `incele`, `cat` |
| Dizin listeleme | `dizin listele`, `ls` |
| Denetim | `denetle`, `audit`, `teknik rapor` |
| Sağlık | `sistem sağlık`, `cpu durumu`, `gpu durum` |
| GitHub | `son commit`, `PR listele`, `github bilgi` |
| Web arama | `web'de ara:`, `google:`, `internette ara` |
| Paket bilgi | `pypi:`, `npm:`, `github releases:` |
| RAG | `depoda ara:`, `belge ekle`, `belge listele` |
| Güvenlik durumu | `openclaw`, `erişim seviyesi`, `access level` |

---

### 3.7 `agent/definitions.py` — Ajan Tanımları (165 satır)

**Amaç:** `SIDAR_SYSTEM_PROMPT` sistem istemini barındırır.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l agent/definitions.py` çıktısına göre **165** olarak ölçülmüştür.

**Sistem İstemi Bölümleri:**

| Bölüm | İçerik |
|-------|--------|
| Geriye dönük uyumluluk listeleri | `SIDAR_KEYS` ve `SIDAR_WAKE_WORDS` sabitleri |
| KİŞİLİK | Analitik, minimal, veriye dayalı, güvenliğe şüpheci |
| MİSYON | Dosya erişimi, GitHub senkronizasyonu, kod yönetimi, teknik denetim |
| GÜNCEL RUNTIME KİMLİĞİ | Varsayılan port/model bilgileri ve `get_config` ile doğrulama notu |
| BİLGİ SINIRI | Ağustos 2025 sonrası için tahmin yasağı; `web_search` / `pypi` zorunlu |
| HALLUCINATION YASAĞI | Sistem değerlerini (versiyon, model, yol) ASLA uydurma; `get_config` kullan |
| DOSYA ERİŞİM STRATEJİSİ | `glob_search` → `read_file` → `patch_file` sırası |
| GÖREV TAKİP | Çok adımlı görevlerde `todo_write` zorunlu |
| SIDAR.md | Proje özel talimatların otomatik yüklenmesi |
| İLKELER | PEP 8, UTF-8, test doğrulama ve fail-closed yaklaşımı |
| DÖNGÜ YASAĞI | Aynı araç 2 kez çağrılmaz; tek adımlı araçlar listelendi |
| HATA KURTARMA | Dosya/patch/izin/web/GitHub hataları için toparlanma adımları |
| ARAÇ KULLANIM STRATEJİLERİ | Her araç için ne zaman / hangi argüman kullanılacağı |
| ARAÇ KULLANIMI (JSON FORMATI) | Yanıtların zorunlu JSON şeması (`thought`, `tool`, `argument`) |
| ÖRNEK JSON YANITLARI | 5 örnek senaryo |

---

### 3.7b `agent/tooling.py` — Araç Kayıt ve Şema Yöneticisi (266 satır)

**Amaç:** Araçların Pydantic şemalarını ve `build_tool_dispatch()` fonksiyonu aracılığıyla araç dispatch tablosunu merkezi olarak yönetir.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l agent/tooling.py` çıktısına göre **266** olarak ölçülmüştür.

**Kritik Bileşenler:**

| Bileşen | Açıklama |
|---------|----------|
| `WriteFileSchema` | `path` + `content` alanlarına sahip yazma şeması |
| `PatchFileSchema` | `path` + `old_text` + `new_text` alanlarına sahip yama şeması |
| `GithubListFilesSchema` | `path` + opsiyonel `branch` alanları |
| `GithubWriteSchema` | `path`, `content`, `commit_message`, opsiyonel `branch` |
| `GithubCreateBranchSchema` | `branch_name` + opsiyonel `from_branch` |
| `GithubCreatePRSchema` | `title`, `body`, `head`, opsiyonel `base` |
| `GithubListPRsSchema` | `state` (varsayılan: `"open"`) + `limit` (varsayılan: 10) |
| `GithubListIssuesSchema` | `state` (varsayılan: `"open"`) + `limit` (varsayılan: 10) |
| `GithubCreateIssueSchema` | `title` + `body` |
| `GithubCommentIssueSchema` | `number` (int) + `body` |
| `GithubCloseIssueSchema` | `number` (int) |
| `GithubPRDiffSchema` | `number` (int) |
| `ScanProjectTodosSchema` | opsiyonel `directory` + opsiyonel `extensions` (uzantı listesi) |
| `TOOL_ARG_SCHEMAS` | Araç adını şema sınıfına eşleyen sözlük (13 giriş) |
| `parse_tool_argument()` | JSON öncelikli, `|||` sınırlı legacy format fallback ile argüman ayrıştırma |
| `build_tool_dispatch()` | `SidarAgent` instance'ından araç adı → metod sözlüğü üretir |

**`parse_tool_argument()` İki Aşamalı Ayrıştırma Mantığı:**
1. **JSON öncelik:** `json.loads(text)` başarılıysa `schema.model_validate(dict)` ile Pydantic doğrulaması yapılır.
2. **Legacy format fallback:** `|||` ayırıcısı ile bölünmüş eski string formatı desteklenir. Bu, eski LLM çıktılarıyla geriye dönük uyumluluğu korur.

**`build_tool_dispatch()` Araç Tablosu (56 araç/alias eşlemesi):**

| Araç Adı | Alias | Metod |
|----------|-------|-------|
| `list_dir` | `ls` | `_tool_list_dir` |
| `read_file` | — | `_tool_read_file` |
| `write_file` | — | `_tool_write_file` |
| `patch_file` | — | `_tool_patch_file` |
| `execute_code` | — | `_tool_execute_code` |
| `run_shell` | `bash`, `shell` | `_tool_run_shell` |
| `glob_search` | — | `_tool_glob_search` |
| `grep_files` | `grep` | `_tool_grep_files` |
| `github_*` PR/Branch (16 araç) | — | `_tool_github_*` |
| `github_list_issues`, `github_create_issue`, `github_comment_issue`, `github_close_issue` | — | `_tool_github_*` |
| `github_pr_diff`, `github_list_repos` | — | `_tool_github_*` |
| `web_search`, `fetch_url`, `search_docs`, `search_stackoverflow` | — | `_tool_*` |
| `pypi`, `pypi_compare`, `npm`, `gh_releases`, `gh_latest` | — | `_tool_*` |
| `docs_search`, `docs_add`, `docs_add_file`, `docs_list`, `docs_delete` | — | `_tool_*` |
| `health`, `gpu_optimize`, `audit` | — | `_tool_*` |
| `todo_write`, `todo_read`, `todo_update`, `scan_project_todos` | — | `_tool_*` |
| `get_config` | `print_config_summary` | `_tool_get_config` |
| `subtask` | `agent` | `_tool_subtask` |

> **Not:** `parallel` aracı bu dispatch tablosunda yer almaz; `sidar_agent.py` içinde ReAct döngüsünde doğrudan `asyncio.gather` ile işlenir.

**Mimari Değer:** `tooling.py` sayesinde araç ekleme/değiştirme işlemleri `sidar_agent.py` içine dağılmaz; tek bir yerden yönetilir. Şema eklemek için yalnızca `TOOL_ARG_SCHEMAS` sözlüğüne yeni giriş yapılması yeterlidir.

---


### 3.7c `agent/base_agent.py` — Temel Ajan Sınıfı (55 satır)

**Amaç:** Multi-agent yapısındaki uzman ajanlar için ortak bir soyut temel sınıf (`BaseAgent`) sağlar.

**Öne Çıkanlar:**
- Ortak `cfg` ve `llm_client` bağımlılıklarının tek bir tabanda toplanması
- Uzman roller arasında tutarlı arayüz (`register_tool`, `call_tool`)
- P2P delegasyon altyapısı: `delegate_to` ile `DelegationRequest` üretimi ve `is_delegation_message` ile sonuç tip doğrulama
- Gelecekte yeni role eklentileri için genişletilebilir iskelet (`ABC` + `@abstractmethod run_task`)

---

### 3.7d `agent/core/supervisor.py` — Yönlendirici (Supervisor) Ajan (164 satır)

**Amaç:** Kullanıcı niyetini analiz edip görevi uygun role yönlendiren orkestrasyon katmanı.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l agent/core/supervisor.py` çıktısına göre **164** olarak ölçülmüştür.

**Öne Çıkanlar:**
- Intent/role routing (`_intent`: research / review / code)
- `TaskEnvelope`/`TaskResult` sözleşmeleriyle uyumlu görev yönetimi (`_delegate`)
- Coder ↔ Reviewer QA döngüsü: `_review_requires_revision` + `MAX_QA_RETRIES=3` ile düzeltme turları ve devre kesici
- P2P delegasyon köprüsü: `_route_p2p` ile `DelegationRequest` zincirini `max_hops=4` sınırıyla yönlendirme
- Supervisor orkestrasyonu v3.0 omurgasında varsayılan ana akış olarak çalışır

---

### 3.7e `agent/core/contracts.py`, `event_stream.py`, `memory_hub.py`, `registry.py` — Çekirdek Ajan İletişim Altyapısı

**Amaç:** Multi-agent omurgasında roller arası görev sözleşmesi, canlı olay akışı ve paylaşımlı bellek/araç kayıt altyapısını sağlar.

**Kapsam:**
- `contracts.py` — `TaskEnvelope` / `TaskResult` + P2P delegasyon sözleşmeleri (`P2PMessage`, `DelegationRequest`, `DelegationResult`)
- `event_stream.py` — ajan durum ve araç olaylarını yayınlayan event bus
- `memory_hub.py` — roller arası ortak bellek erişim katmanı
- `registry.py` — çalışma zamanında rol/ajan kayıt ve çözümleme yardımcıları

**Mimari Değer:** Bu katman, `SupervisorAgent` ile rol ajanları arasında gevşek bağlı (loosely-coupled) iletişim kurarak genişletilebilirliği artırır.

---

### 3.7f `agent/roles/` — Uzman Ajan Rolleri (Coder, Researcher & Reviewer)

**Amaç:** Uzman ajanların görev paylaşımıyla kod üretimi, araştırma ve kalite kontrol döngüsünü yürütür.

> Not (Doğrulama): Güncel depoda `wc -l` çıktıları: `agent/roles/coder_agent.py=134`, `agent/roles/researcher_agent.py=75`, `agent/roles/reviewer_agent.py=181`, `agent/roles/__init__.py=6`.

**Alt Roller ve Yetenekler:**
- `__init__.py` — rol sınıflarını (`CoderAgent`, `ResearcherAgent`, `ReviewerAgent`) dışa aktarır.
- `coder_agent.py` — kod/dosya odaklı uzman ajan; `read_file`, `write_file`, `patch_file`, `execute_code`, `list_directory`, `glob_search`, `grep_search`, `audit_project`, `get_package_info`, `scan_project_todos` dahil 10 araç kaydıyla çalışır.
- `researcher_agent.py` — araştırma odaklı uzman ajan; `web_search`, `fetch_url`, `search_docs`, `docs_search` araçlarıyla web + RAG keşfi yapar.
- `reviewer_agent.py` — QA uzmanı; `_build_dynamic_test_content` ile dinamik test üretir, `_extract_changed_paths` ile değişen dosyaları hedefler, regresyon komutlarını çalıştırır ve sonucu `delegate_to("coder", ...)` ile P2P geri bildirim olarak kodlayıcıya iletir.

**Mimari Not:** Coder ↔ Reviewer etkileşimi yalnızca merkezî supervisor döngüsüyle sınırlı değildir; reviewer tarafından üretilen `qa_feedback|decision=...` çıktıları coder tarafında ayrıştırılıp yeniden çalışma (rework) akışı tetiklenebilir.

---

### 3.8 `core/llm_client.py` — LLM İstemcisi (Ollama + Gemini + OpenAI + Anthropic, 839 satır)

**Amaç:** Ollama, Gemini, OpenAI ve Anthropic için ortak asenkron chat arayüzü — `BaseLLMClient` ABC.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l core/llm_client.py` çıktısına göre **839** olarak ölçülmüştür.

**Sınıf Hiyerarşisi:**
```
BaseLLMClient (ABC)
├── OllamaClient
├── GeminiClient
├── OpenAIClient          ← v2.9.0 yeni eklenti
└── AnthropicClient       ← v2.10.8 yeni eklenti
```

**`LLMClient.chat()` Parametreleri:**
- `stream`: True → `AsyncIterator[str]`, False → `str`
- `json_mode`: True → LLM'i `{thought, tool, argument}` JSON çıktısına zorlar

**Ollama Entegrasyonu:**
- **Yapısal Çıktı (Structured Output):** Ollama ≥0.4 için JSON Schema formatı ile `{thought, tool, argument}` şeması zorunlu kılınır. Hallucination ve yanlış format sorunlarını önler.
- **Stream Güvenliği:** `aiter_bytes()` + `codecs.IncrementalDecoder` ile TCP paket sınırlarında bölünen JSON satırları güvenle birleştirilir. `aiter_lines()` kullanılmaz çünkü bu yaklaşım içerik kaybına yol açabilir.
- **GPU Desteği:** `USE_GPU=true` ise `options.num_gpu=-1` ile tüm katmanlar GPU'ya gönderilir.
- **Timeout:** `max(10, OLLAMA_TIMEOUT)` — minimum 10 sn garanti edilir.

**Gemini Entegrasyonu:**
- `google.generativeai` paketi runtime'da import edilir; kurulu değilse anlamlı hata mesajı döner.
- `response_mime_type: application/json` ile JSON modu; `text/plain` ile düz metin modu.
- Safety settings: Tüm zararlı içerik kategorileri `BLOCK_NONE` — teknik konularda LLM bloklamalarını önler.
- `send_message_async` ile gerçek asenkron Gemini çağrısı.

**OpenAI Entegrasyonu (v2.9.0):**
- `openai` paketi runtime'da import edilir; `AsyncOpenAI` istemcisi.
- `response_format: {"type": "json_object"}` ile JSON modu.
- WebSocket olay paketleri (`chunk/thought/tool_call/done`) ile gerçek zamanlı streaming desteği.
- `AI_PROVIDER=openai` + `OPENAI_API_KEY` ile aktif edilir.

**Anthropic Entegrasyonu:**
- `anthropic` paketi runtime'da import edilir; `AsyncAnthropic` istemcisiyle asenkron çağrı yapılır.
- `json_mode=True` iken sistem istemine ek JSON şema talimatı enjekte edilerek `{thought, tool, argument}` formatı zorlanır.
- Streaming ve non-streaming akışlar ortak yardımcılarla izlenir; sonuçlar `_ensure_json_text()` ile güvenli JSON'a normalize edilir.

**Akıllı Yeniden Deneme (Retry/Backoff):**
- `_is_retryable_exception` + `_retry_with_backoff` ile 429/5xx gibi geçici bulut hatalarında yeniden deneme uygulanır.
- Exponential backoff + jitter kullanılarak sağlayıcı geçici hatalarında dayanıklılık artırılır.

**Telemetri ve Gözlemlenebilirlik (Observability):**
- `core.llm_metrics` entegrasyonu ile çağrı başına latency/success/error ve token kullanımı kaydedilir (`_record_llm_metric`).
- OpenTelemetry span'leri üzerinden stream performansı izlenir; TTFT (time-to-first-token) ve toplam akış süresi `_trace_stream_metrics` ile ölçülür.

**`_ensure_json_text()`:** Modelin JSON dışı metin döndürmesi durumunda `final_answer` sarmalayıcı olarak güvenli JSON üretir.

---

### 3.9 `core/memory.py` — Konuşma Belleği (DB tabanlı, v3.0)

**Amaç:** Çok kullanıcılı, thread-safe ve DB kalıcılığı kullanan konuşma belleği katmanı sağlar.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l core/memory.py` çıktısına göre **316** olarak ölçülmüştür.

**v3.0 Mimari Değişim:**
- Eski JSON dosya temelli kalıcılık yerine `core/db.py` üzerinden **asenkron veritabanı** kalıcılığı kullanılır.
- Oturum ve mesaj işlemleri kullanıcı kimliği (`user_id`) ile izole edilir.
- Kimliği doğrulanmamış kullanım `MemoryAuthError` ile **fail-closed** engellenir (`_require_active_user`).

**Öne Çıkan API'ler:**
- Async çekirdek: `acreate_session`, `aload_session`, `adelete_session`, `aget_all_sessions`, `aadd`, `aget_history`, `aupdate_title`, `aset_active_user`
- Sync uyumluluk katmanı: `create_session`, `load_session`, `delete_session`, `add`, `get_history` (içeride async çağrıları `_run_coro_sync` köprüsü ile güvenli biçimde çalıştırır)

**Davranış Notları:**
- DB schema başlangıçta otomatik hazırlanır (`connect` + `init_schema`).
- Token bazlı akıllı özetleme aktiftir: `tiktoken` ile token tahmini yapılır; `max_turns` penceresi veya `6000` token eşiği aşılırsa `needs_summarization` tetiklenir.
- `apply_summary`, geçmiş konuşmayı `[KONUŞMA ÖZETİ]` mesajına sıkıştırır, son `keep_last` turları korur ve DB oturumunu özetlenmiş içerikle yeniden yazar.
- Legacy uyumluluk için `_save()` ve `_cleanup_broken_files()` DB modunda no-op olarak korunur.

---

### 3.10 `core/rag.py` — RAG Motoru (783 satır)

**Amaç:** ChromaDB (vektör) + BM25 + Keyword hibrit belge deposu. v3.0 ile birlikte **RRF birleştirme**, **oturum izolasyonu** ve disk tabanlı BM25 altyapısı birlikte çalışır.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l core/rag.py` çıktısına göre **783** olarak ölçülmüştür.

**Arama Modları (v3.0):**

| Mod | Motor | Açıklama |
|-----|-------|----------|
| `auto` | **RRF (ChromaDB + BM25)** → ChromaDB → BM25 → Keyword | Her iki motor hazırsa `_rrf_search` ile birleştirme (k=60) |
| `vector` | ChromaDB (cosine similarity + `session_id` where filtresi) | Anlamsal arama |
| `bm25` | SQLite FTS5 (`bm25_fts.db`) + `bm25()` skoru | Disk tabanlı tam metin arama; `tokenize='unicode61 remove_diacritics 1'` |
| `keyword` | Anahtar kelime eşleşmesi (`session_id` kontrolü) | Başlık ×5, etiket ×3, içerik ×1 ağırlıkla skor |

**RRF Algoritması (`_rrf_search`):**
```python
# Her iki motordan sonuç alınır; rank tabanlı birleştirme
rrf_score(doc) = Σ  1 / (k + rank_i)   (k=60, TREC'19 standardı)
```
ChromaDB ve BM25 sonuçları `_fetch_chroma()` / `_fetch_bm25()` ayrı metodlarıyla alınır; skorlar birleştirilerek `top_k` sonuç döndürülür.

**Oturum İzolasyonu (`session_id`):**
- `add_document()`: her belgeye `session_id` metadata alanı eklenir
- `_fetch_chroma()`: `where={"session_id": session_id}` ChromaDB filtresi
- `_fetch_bm25()`: SQL düzeyinde `session_id = ?` filtresiyle FTS5 araması yapılır
- `_keyword_search()`: `meta.get("session_id")` kontrolü
- `delete_document()`: farklı oturumun belgesini silmeye karşı yetki kontrolü
- `get_index_info()`: `session_id=None` → tüm belgeler; `session_id=<id>` → oturuma özgü

**Chunking Motoru:**
`_recursive_chunk_text()` LangChain'in `RecursiveCharacterTextSplitter` mantığını simüle eder. Öncelik sırası: `\nclass ` → `\ndef ` → `\n\n` → `\n` → ` ` → karakter. Overlap mekanizması bağlam sürekliliğini korur.

**Embedding Runtime Notları:**
- `_build_embedding_function()` — `USE_GPU=true` ise `sentence-transformers/all-MiniLM-L6-v2` modeli CUDA üzerinde çalışır; `GPU_MIXED_PRECISION=true` ise FP16 ile VRAM tasarrufu sağlanır.
- `_apply_hf_runtime_env()` — `HF_HUB_OFFLINE=true` iken `HF_HUB_OFFLINE=1` ve `TRANSFORMERS_OFFLINE=1` ortam değişkenleri zorlanarak çevrimdışı kurumsal ağlarda stabil çalışma sağlanır.

**BM25 Disk Motoru (FTS5):**
- `_init_fts()` ile `bm25_fts.db` üzerinde `bm25_index` sanal tablosu oluşturulur.
- Belge ekleme/silme akışında `_update_bm25_cache_on_add()` ve `_update_bm25_cache_on_delete()` ile FTS indeks güncel tutulur.
- Sonuç gösteriminde `_extract_snippet()` kullanılarak sorgu anahtar kelimesi etrafından kırpılmış bağlamsal metin döndürülür.

**Belge Yönetimi:**
- `add_document(session_id)`: dosya sistemi + index.json + ChromaDB chunked upsert (thread-safe `_write_lock`) + FTS5 güncelleme
- `add_document_from_url(session_id)`: httpx asenkron HTTP çekme + HTML temizleme + ekleme
- `add_document_from_file(session_id)`: uzantı whitelist kontrolü (.py, .md, .json, .yaml, vb.)
- `delete_document(session_id)`: izolasyon yetki kontrolü sonrası dosya + ChromaDB + FTS5 kayıt silme

---

### 3.11 `managers/security.py` — Güvenlik Yöneticisi (290 satır)

**Amaç:** OpenClaw erişim kontrol sistemi — 3 katmanlı güvenlik.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/security.py` çıktısına göre **290** olarak ölçülmüştür.

**Erişim Seviyeleri:**

| Seviye | Okuma | Yazma | REPL | Shell |
|--------|-------|-------|------|-------|
| `restricted` (0) | ✓ | ✗ | ✗ | ✗ |
| `sandbox` (1) | ✓ | Yalnızca `/temp` | ✓ | ✗ |
| `full` (2) | ✓ | Proje kökü altı | ✓ | ✓ |

**Hard-Gate Güvenlik Katmanları:**

1. **Path Traversal + Sistem Dizin Koruması:** `_DANGEROUS_PATH_RE` ile `../`, `/etc/`, `/proc/`, `/sys/`, `C:\Windows`, `C:\Program Files` kalıpları doğrudan engellenir.
2. **Hassas Dosya/Dizin Kara Listesi:** `_BLOCKED_PATTERNS` üzerinden `.env`, `sessions/`, `.git/`, `__pycache__/` erişimleri seviyeden bağımsız bloke edilir.
3. **Symlink Kaçış Koruması:** `_resolve_safe()` içinde `Path.resolve()` ile gerçek hedef hesaplanır; base_dir dışına çıkan sembolik bağlantılar reddedilir.
4. **Bilinmeyen Seviye Normalize (Fail-Safe):** Geçersiz erişim seviyesi adları güvenli varsayılan `sandbox` değerine düşürülür.

**İzin Karar API'leri:**
- `check_read(path)`: yol + blacklist + symlink doğrulaması sonrası okuma izni.
- `check_write(path)`: erişim seviyesine göre (`restricted`/`sandbox`/`full`) ve güvenlik bariyerlerine göre yazma izni.
- `check_terminal()`: REPL/terminal çağrılarına seviye tabanlı izin.
- `check_shell()`: yalnızca `full` seviyesinde kabuk komutlarına izin.

---

### 3.12 `managers/code_manager.py` — Kod Yöneticisi (805 satır)

**Amaç:** Güvenli dosya I/O, sözdizimi denetimi ve Docker tabanlı kod yürütmeyi yönetir.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/code_manager.py` çıktısına göre **805** olarak ölçülmüştür.

**Zero-Trust Sandbox (v3.0):**
- `execute_code()` akışı varsayılan olarak Docker izolesinde çalışır; çıktı `stdout/stderr` ayrıştırılarak geri döndürülür.
- `network_mode="none"` ile varsayılan ağ erişimi kapalıdır (`DOCKER_NETWORK_DISABLED=true`).
- `mem_limit` ve `nano_cpus` ile konteyner kaynakları sınırlandırılır.
- `DOCKER_MICROVM_MODE` + `DOCKER_ALLOWED_RUNTIMES` ile `runsc`/`kata-runtime` gibi mikro-VM runtime'larına uyumlu çalışır.
- Çalıştırma süresi `DOCKER_EXEC_TIMEOUT` ile zorlanır; timeout durumunda konteyner kill edilerek sonsuz döngü riski sınırlandırılır.
- Docker erişilemezse `execute_code_local()` ile kontrollü ve zaman-aşımlı yerel fallback devreye girer.

**Yazma Öncesi Kod Doğrulama:**
- Python dosyaları için `write_file()` / `patch_file()` akışlarında `ast.parse()` ile sözdizimi doğrulaması yapılır.
- `SyntaxError` durumunda değişiklik diske yazılmadan işlem güvenli şekilde reddedilir.

**Akıllı Encoding Fallback:**
- Okuma akışında UTF-8 başarısız olursa `chardet` ile encoding tespiti yapılarak `UnicodeDecodeError` kaynaklı kırılmalar azaltılır.

**Gelişmiş Arama Araçları:**
- `glob_search(pattern, base_path)` ile desen/uzantı bazlı dosya keşfi.
- `grep_files(regex, path, file_glob, context)` ile regex destekli içerik araması ve bağlam satırı döndürme.

**SecurityManager ile Sıkı Entegrasyon:**
- Tüm dosya okuma/yazma yolları `self.security_manager.check_read()` ve `check_write()` kararlarına bağlıdır.
- Güvenlik onayı alınmadan dosya erişimi veya yazma yapılmaz.

**Temel Yetenekler:**
- Güvenli dosya okuma/yazma ve path doğrulama
- Syntax kontrolü / proje denetimi (`audit_project`)
- Docker yoksa güvenlik seviyesine göre kontrollü fallback davranışı

---

### 3.13 `managers/github_manager.py` — GitHub Yöneticisi (644 satır)

**Amaç:** PyGithub üzerinden GitHub API entegrasyonu.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/github_manager.py` çıktısına göre **644** olarak ölçülmüştür.

**Kurumsal Koruma Katmanları:**
- **Binary dosya koruması (OOM savunması):** `read_remote_file()` içinde `SAFE_TEXT_EXTENSIONS` ve `SAFE_EXTENSIONLESS` kontrolleriyle metin dışı içerikler reddedilir; binary/bozuk içeriklerde güvenli hata mesajı döndürülür.
- **Branch adı doğrulama:** `_BRANCH_RE` ile yalnızca güvenli karakter setindeki dal adlarına izin verilir.
- **404 güvenli yakalama:** `_is_not_found_error()` ile not-found durumları kontrollü işlenir (sert çökme yerine anlamlı dönüş).

**Ölçeklenebilir Veri Çekme Sınırları (Pagination/Limit):**
- `list_commits(limit)`: istenen değer güvenli aralıkta sınırlandırılır (`1..100`); yüksek isteklerde kullanıcıya kısıtlama uyarısı verilir.
- `list_branches(limit)`, `list_pull_requests(limit)`, `list_issues(limit)`, `list_repos(limit)`: benzer şekilde limitli/paginated çağrılarla kaynak kullanımı kontrol altında tutulur.
- `search_code()`: sonuçlar ilk 10 kayıtla sınırlandırılır.

**PR ve Branch Yönetimi:**
- `list_commits(n)`, `get_repo_info()`, `list_files(path)`, `read_remote_file(path)`
- `write_file()`, `create_branch()`, `create_pr()`, `list_pull_requests()`
- `get_pull_request()`, `comment_pr()`, `close_pr()`, `get_pr_files()`
- `get_pull_request_diff(pr_number)` — PR diff metnini döndürür; patch olmayan dosyalar için binary olasılığına dair güvenli not üretir.
- `search_code(query)`, `github_smart_pr()` — LLM ile otomatik PR başlığı/açıklaması
- `get_pull_requests_detailed()`, `list_repos(owner_filter)` — yeni eklenti

**Issue Yönetimi (v2.9.0 — §14.5.2):**
- `list_issues(state, limit)`: Issue listesi (open/closed/all)
- `create_issue(title, body)`: Yeni issue açar
- `comment_issue(issue_number, body)`: Issue'ya yorum ekler
- `close_issue(issue_number)`: Issue'yu kapatır

**Not (Kapsam):** Mevcut sürümde açık bir exponential backoff yardımcı fonksiyonu bulunmaz; hata toleransı çoğunlukla limitli çağrı + kontrollü exception mesajları üzerinden sağlanır.

---

### 3.14 `managers/system_health.py` — Sistem Sağlık Yöneticisi (475 satır)

**Amaç:** CPU/RAM/GPU/disk donanım izleme ve VRAM optimizasyonu.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/system_health.py` çıktısına göre **475** olarak ölçülmüştür.

**Bağımlılıklar (opsiyonel):**
- `psutil`: CPU, RAM ve disk metrikleri
- `torch`: CUDA mevcutluğu, VRAM kullanım bilgisi, `empty_cache()`
- `pynvml`: GPU sıcaklık, anlık kullanım yüzdesi, sürücü sürümü

**Derin GPU/VRAM Gözlemi:**
- `get_gpu_info()` her GPU için cihaz adı, compute capability, ayrılan/rezerve VRAM, toplam VRAM, sıcaklık ve utilization yüzdesi döndürür.
- `_get_driver_version()` öncelikle pynvml ile sürücü sürümünü alır; gerekirse `nvidia-smi` fallback yolunu kullanır.

**Graceful Degradation (Donanım bağımsız çalışma):**
- `torch`/`pynvml`/`psutil` modülleri yoksa servis çökmez; ilgili alt metrikler güvenli fallback değerleriyle raporlanır.
- WSL2/NVIDIA sürücü kısıtlarında pynvml hataları kritik kabul edilmez, CPU/RAM odaklı gözlem akışı devam eder.

**Disk Darboğazı Takibi:**
- `get_disk_usage()` ile çalışma dizini için kullanılan/toplam/boş disk ve yüzde kullanım bilgisi üretilir.
- `full_report()` çıktısına disk kullanım satırları eklenerek kapasite doluluk riskleri görünür hale getirilir.

**Operasyonel API'ler:**
- `full_report()`: CPU, RAM, disk, GPU ve sürücü bilgilerini tek raporda sunar.
- `optimize_gpu_memory()`: `torch.cuda.empty_cache()` + `gc.collect()` ile VRAM boşaltır; `try-finally` ile GC her koşulda çalışır.
- `update_prometheus_metrics()`: metrikleri `Gauge` nesnelerine aktarır; `prometheus_client` yoksa sessizce atlar.
- `close()`: pynvml kapanışını güvenli şekilde yapar (atexit ile de çağrılır).

---

### 3.15 `managers/web_search.py` — Web Arama Yöneticisi (387 satır)

**Amaç:** Tavily → Google → DuckDuckGo kademeli motor desteğiyle asenkron web araması.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/web_search.py` çıktısına göre **387** olarak ölçülmüştür.

**Akıllı Motor Şelalesi (`auto`):** Tavily → Google Custom Search → DuckDuckGo sırasıyla denenir; anahtar eksikliği, kota/hata veya yanıt başarısızlığında sistem bir sonraki motora düşerek kesintisiz arama davranışı sağlar.

**Desteklenen Operasyonlar:**
- `search(query)`: Genel web araması
- `fetch_url(url)`: URL içerik çekme + BeautifulSoup HTML temizleme
- `search_docs(library, topic)`: Resmi dokümantasyon araması
- `search_stackoverflow(query)`: Stack Overflow araması

**Metin Sanitizasyonu (Token hijyeni):**
- Sonuç/snippet içerikleri `html.unescape` ile normalize edilerek HTML entity/artıklarının (`&amp;`, vb.) LLM bağlamını kirletmesi azaltılır.

**v2.8.0 DuckDuckGo Güvenlik İyileştirmeleri (Madde #10 Çözümü):**

`_search_duckduckgo()` içinde üç katmanlı güvenlik uygulandı:

```python
# 1. Dinamik AsyncDDGS kontrolü (versiyon değişikliği koruması)
if hasattr(duckduckgo_search, "AsyncDDGS"):
    results = await asyncio.wait_for(_async_search(), timeout=FETCH_TIMEOUT)
else:
    # AsyncDDGS yoksa (gelecek sürümler için) sync+thread fallback
    results = await asyncio.wait_for(
        asyncio.to_thread(_sync_search), timeout=FETCH_TIMEOUT)

# 2. Timeout koruması — her iki yol da wait_for ile sınırlı
# 3. Except sırası: asyncio.TimeoutError > Exception (Python best practice)
except asyncio.TimeoutError:  # Spesifik önce
    ...
except Exception as exc:       # Genel sonra
    ...
```

| Güvenlik Katmanı | Açıklama |
|---|---|
| Versiyon pinleme | `environment.yml`: `duckduckgo-search~=6.2.13` |
| `AsyncDDGS` dinamik kontrol | `hasattr()` ile mevcut sürümde async yol, gelecek sürümlerde sync yol |
| `asyncio.wait_for()` | Her iki arama yolu için `FETCH_TIMEOUT` sınırı (sessiz takılma engeli) |
| `asyncio.TimeoutError` handler | Spesifik timeout mesajı + `logger.warning` |

**Konfigürasyon:** `WEB_SEARCH_MAX_RESULTS` (5), `WEB_FETCH_TIMEOUT` (15sn), `WEB_SCRAPE_MAX_CHARS` (12000)

---

### 3.16 `managers/package_info.py` — Paket Bilgi Yöneticisi (322 satır)

**Amaç:** PyPI, npm ve GitHub Releases gerçek zamanlı sorgusu.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/package_info.py` çıktısına göre **322** olarak ölçülmüştür.

**Özellikler:**
- `pypi_info(package)`: Sürüm, lisans, GitHub URL, son güncelleme tarihi
- `pypi_compare(package, version)`: Mevcut kurulu sürüm ile son sürüm karşılaştırması
- `npm_info(package)`: npm Registry paket bilgisi
- `github_releases(owner/repo)`: GitHub Releases listesi
- `github_latest_release(owner/repo)`: Son release bilgisini hızlı döndürür

**Asenkron Ağ Katmanı (httpx):**
- Tüm dış istekler `httpx.AsyncClient` ile `async/await` akışında çalışır; ajan döngüsü bloklanmaz.
- Ortak `_get_json()` yardımcı metodu timeout/bağlantı hatalarını standartlaştırır.

**TTL Tabanlı Akıllı Önbellek:**
- `PACKAGE_INFO_CACHE_TTL` (varsayılan 1800 sn) ile in-memory cache (`_cache_get`/`_cache_set`) kullanılır.
- Aynı paket sorgularında gereksiz dış API çağrıları azaltılarak latency ve rate-limit baskısı düşürülür.

**Semantik Sürüm Doğrulama:**
- `packaging.version.Version` / `InvalidVersion` ile sürüm metinleri normalize edilir.
- `_is_prerelease()` ve `_version_sort_key()` üzerinden pre-release/bozuk sürüm durumları güvenli fallback ile ele alınır.

---

### 3.17 `managers/todo_manager.py` — Görev Takip Yöneticisi (451 satır)

**Amaç:** Claude Code'daki `TodoWrite/TodoRead` araçlarına eşdeğer görev listesi.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l managers/todo_manager.py` çıktısına göre **451** olarak ölçülmüştür.

**Görev Durumları:** `pending` ⬜ → `in_progress` 🔄 → `completed` ✅

**Özellikler:**
- Thread-safe `RLock` ile korunur (multi-agent eşzamanlı yazma/okuma yarışlarını azaltır)
- `@dataclass` tabanlı `TodoTask` modeli ile tip güvenliği (`id`, `content`, `status`, `created_at`, `updated_at`)
- `created_at` / `updated_at` timestamp alanlarıyla görev yaşam döngüsü takibi
- `todo_write("görev1:::pending|||görev2:::in_progress")` formatı
- `_ensure_single_in_progress()`: aynı anda yalnızca 1 aktif görev; diğerleri `pending`'e döner
- `set_tasks()`: toplu görev yenileme (TodoWrite style)
- `_normalize_limit()`: limit değeri 1–200 arasına sıkıştırılır
- Kalıcı: `data/todo.json` dosyasına kaydedilir

**`scan_project_todos()` (v2.9.0 — §14.7.5):**
Proje dizinini gezer; `.py`, `.md`, `.js`, `.ts` dosyalarındaki `TODO` ve `FIXME` yorumlarını tarar. Güvenlik kontrolü: `base_dir` dışı tarama engellenir.

---

### 3.18 `web_ui/` — Web Arayüzü (Toplam ~4.160 satır)

> Not (Doğrulama): Güncel depoda `wc -l` ölçümü: `index.html=572`, `style.css=1684`, `app.js=670`, `chat.js=695`, `rag.js=131`, `sidebar.js=408` (**toplam 4.160**).

**Mimari Yapı (Modüler Vanilla JS SPA):**
- Monolitik tek-dosya yaklaşımı yerine sorumluluklar `app.js`, `chat.js`, `sidebar.js`, `rag.js` modüllerine ayrılmıştır.
- `index.html` sadece iskelet + modal katmanları + script yükleme sırasını taşır; davranış mantığı modüllerde tutulur.

**Dosya Yapısı:**

| Dosya | Satır | Sorumluluk |
|-------|------:|-----------|
| `index.html` | 572 | HTML iskeleti, auth overlay, modal/board container'lar, script yükleme noktaları |
| `style.css` | 1.684 | Tema (dark/light), layout sistemi, bileşen stilleri |
| `chat.js` | 695 | WebSocket chat akışı, event render, markdown + kod çıktısı işleme |
| `sidebar.js` | 408 | Oturum listesi, filtreleme, başlık düzenleme/silme |
| `rag.js` | 131 | RAG belge ekleme/listeleme/arama/silme UI |
| `app.js` | 670 | Auth flow, global state, tema/yardımcı kontroller, uygulama orkestrasyonu |
| **Toplam** | **4.160** | Modüler ve ayrışmış web istemcisi |

**Kimlik Doğrulama ve Oturum Koruması:**
- `AUTH_TOKEN_KEY` / `AUTH_USER_KEY` ile token + kullanıcı bağlamı istemci tarafında yönetilir.
- Auth overlay (`login/register`) akışı olmadan chat oturumu başlatılmaz; token olmayan istemci WebSocket tarafında yetkisiz kapatmayı tetikler.

**Gerçek Zamanlı Event Stream ve UX:**
- `chat.js` WebSocket üzerinden ajan olaylarını/araç adımlarını JSON event olarak işler; kullanıcının işlem durumunu canlı görmesini sağlar.
- Bağlantı kopmaları için yeniden bağlanma ve auth-hata ayrımı yapılır (ör. auth kaynaklı kapanış vs geçici kesinti).

**Güvenli Render ve Metin İşleme:**
- `marked` tabanlı markdown render + güvenli HTML temizleme (`sanitizeRenderedHtml`) ile çıktı yüzeyi korunur.
- Kod blokları ve uzun yanıtlar UI tarafında kontrollü biçimde parse edilip gösterilir.

**Yükleme Sırası (index.html → script tags):**
```html
<script src="/static/chat.js"></script>
<script src="/static/sidebar.js"></script>
<script src="/static/rag.js"></script>
<script src="/static/app.js"></script>
```

---

### 3.19 `github_upload.py` — GitHub Yükleme Aracı (294 satır)

**Amaç:** Projeyi otomatik olarak GitHub'a yükler/yedekler.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l github_upload.py` çıktısına göre **294** olarak ölçülmüştür.

**Güvenlik Katmanı (`FORBIDDEN_PATHS`):**
- `.env`, `sessions/`, `chroma_db/`, `__pycache__/`, `.git/`, `logs/`, `models/`
- Binary/UTF-8 okunamayan dosyalar da engellenir

**Otomasyon ve Dayanıklılık Özellikleri:**
- **Repo/remote doğrulama:** Çalıştırma başında `.git` varlığı ve `origin` remote kontrol edilir; eksikse yönlendirici/otomatik kurulum adımları uygulanır.
- **Zaman damgalı commit mesajı:** Kullanıcı mesaj vermezse `datetime.now().strftime(...)` ile otomatik commit başlığı üretilir.
- **Push-rejected kurtarma akışı:** `git push` reddedildiğinde (`rejected`/`fetch first`/`non-fast-forward`) güvenli `pull` + merge stratejisi (`--rebase=false --allow-unrelated-histories --no-edit -X ours`) ile senkronizasyon denenir ve push tekrar edilir.
- **GitHub Push Protection farkındalığı:** secret scanning/push protection hataları algılanır ve kullanıcıya düzeltme yönlendirmesi verilir.

**Hata Yönetimi:**
- `subprocess.CalledProcessError` yakalanarak anlaşılır terminal çıktısı üretilir; ağ/auth/çatışma senaryolarında sessiz çökme engellenir.

---

### 3.20 `core/db.py` — Veritabanı ve Çoklu Kullanıcı Altyapısı

**Amaç:** Çoklu kullanıcı (multi-user) SaaS mimarisi için kullanıcı, oturum, mesaj ve yetkilendirme (token) verilerinin kalıcı ve izole olarak saklanmasını sağlar.

> Not (Doğrulama): Bu rapordaki satır sayısı, güncel depoda `wc -l core/db.py` çıktısına göre **989** olarak ölçülmüştür.

**Kriptografik Auth Altyapısı:**
- Parolalar PBKDF2-HMAC (`hashlib.pbkdf2_hmac`) + salt ile hashlenir; düz metin parola saklanmaz.
- Auth token üretimi `secrets` ile yapılır (`token_urlsafe` / güvenli karşılaştırma), token yaşam döngüsü DB'de izlenir.
- Kullanıcı/oturum/mesaj kimlikleri `uuid` tabanlı benzersiz anahtarlarla yönetilir.

**Asenkron ve Non-Blocking Veri Katmanı:**
- Tüm temel I/O yolu `async def` akışındadır (bağlantı, şema, CRUD, auth doğrulama).
- `DATABASE_URL`’e göre PostgreSQL (`asyncpg`) veya SQLite (`aiosqlite`) fallback desteği vardır.
- Çoklu ajan/kullanıcı eşzamanlılığında bloklamayı azaltmak için bağlantı ve sorgu yolları asenkron tasarlanmıştır.

**UTC / TTL Tabanlı Oturum Yönetimi:**
- Zaman alanları `datetime.now(timezone.utc)` ile UTC normalize edilir.
- Token süre sonları `timedelta` tabanlı hesaplanır (`_expires_in`), periyodik temizlik/süre kontrol akışlarıyla birlikte çalışır.
- `sessions`, `messages`, `auth_tokens` kayıtları zaman damgası ve kullanıcı kimliğiyle birlikte izlenir.

**Dataclass ile Katı Şema Temsili:**
- DB satırları `@dataclass` kayıt modellerine (`UserRecord`, `AuthTokenRecord`, `SessionRecord`, `MessageRecord`, vb.) dönüştürülür.
- Bu modelleme katmanı API tüketicilerinde tip güvenliği ve sözleşme tutarlılığı sağlar.

**Alembic / Şema Versiyonlama Uyum Notu:**
- `schema_versions` tablosu üzerinden uygulama tarafı şema sürümü izlenir.
- Migration kaynağı olarak Alembic zinciriyle uyumlu çalışacak biçimde tasarlanmıştır (`alembic.ini` + `migrations/`).

**Temel Tablolar ve İzolasyon:**
- Çekirdek tablolar: `users`, `auth_tokens`, `sessions`, `messages`, `daily_llm_usage`.
- Her oturum ve mesaj kaydı `user_id` bağlamına bağlıdır; tenant izolasyonu veri modelinde zorunludur.

---

### 3.21 `core/llm_metrics.py` — Telemetri ve Bütçe Yönetimi

**Amaç:** LLM çağrılarının operasyonel metriklerini toplamak, Prometheus'a aktarmak ve veritabanı üzerinden günlük kullanıcı kotalarını izlemek.

> Doğrulama notu: Bu bölüm, `wc -l core/llm_metrics.py` çıktısına göre dosya uzunluğunun 235 satır olduğu güncel sürümle hizalanmıştır.

**Özellikler:**
- `LLMMetricsManager` üzerinden token kullanımı (prompt, completion) ve işlem süresi (latency) ölçümü.
- API maliyetlerinin (USD bazında) model bazlı dinamik fiyat tablosu ile hesaplanması (`prompt`/`completion` token ayrımı).
- Prometheus uyumlu sayaç/ölçüm metriklerinin (`Counter`, `Histogram`, `Gauge`) dışa aktarımı; özellikle istek sayısı, token toplamı, maliyet ve gecikme dağılımı için panel uyumluluğu.
- Eşzamanlı isteklerde güvenli metrik güncellemesi için `threading.Lock` tabanlı kritik bölüm yaklaşımı ve process-içi tek toplayıcı erişim deseni.
- Grafana dashboard'ları için kurumsal metrik (observability) verisi sağlanması.

---

### 3.22 `migrations/` ve `scripts/` — Geçiş ve Operasyon Araçları

**Amaç:** Projenin tekil kullanıcıdan kurumsal veritabanına pürüzsüz geçişini sağlayan veri tabanı, migrasyon ve operasyonel otomasyon araçlarını standartlaştırmak.

**Özellikler (Kurumsal V3.0):**
- **Alembic ile otomatik şema sürümleme (`migrations/`):** `alembic.ini` + `migrations/env.py` altyapısı ile ortam-bağımsız veritabanı revizyon yönetimi yapılır; `DATABASE_URL` veya `-x database_url` üzerinden dinamik bağlantı çözümleme desteklenir.
- **Baseline kurulum garantisi (`migrations/versions/0001_baseline_schema.py`):** `users`, `auth_tokens`, `user_quotas`, `provider_usage_daily`, `sessions`, `messages`, `schema_versions` tablolarını ve kritik indeksleri tek revizyonda kurar; yeni ortamların sıfırdan güvenli bootstrap'ini sağlar.
- **SQLite → PostgreSQL veri taşıma (`scripts/migrate_sqlite_to_pg.py`):** Yerel SQLite verilerini tablo sırasına bağlı ve tutarlı biçimde PostgreSQL'e aktarır; `asyncio`/`asyncpg` tabanlı çalışır ve `--dry-run` ile kayıpsız geçiş öncesi doğrulama yapılabilir.
- **Docker sandbox güvenli host kurulumu (`scripts/install_host_sandbox.sh`):** gVisor/Kata runtime kurulumunu, Docker daemon runtime kaydını ve opsiyonel servis restart akışını otomatikleştirir (`--mode gvisor|kata|both`, `--dry-run`).
- **Veritabanı yük/stres testi (`scripts/load_test_db_pool.py`):** Asenkron connection pool davranışını eşzamanlı yükte ölçerek çoklu ajan senaryolarında havuz limitlerinin doğrulanmasını destekler.
- **Kalite ve CI/CD metrik denetimi (`scripts/audit_metrics.sh`, `scripts/collect_repo_metrics.sh`):** Satır sayısı/audit metriklerini ve repo özet metriklerini otomatik üretir; CI pipeline'larına doğrudan entegre edilebilir.

---

### 3.23 `docker/` ve `runbooks/` — Telemetri ve Production Altyapı Dosyaları

**Amaç:** Üretim ortamında gözlemlenebilirlik (observability), telemetri görselleştirme ve canlıya geçiş (cutover) operasyonlarını tekrarlanabilir SOP'larla yönetmek.

**Özellikler (Kurumsal V3.0 DevOps):**
- **Tek komutla observability orkestrasyonu (`docker-compose.yml`):** Uygulama servisleriyle birlikte `prometheus` ve `grafana` konteynerlerini tek bir `docker compose up -d` akışında ayağa kaldırır; servis bağımlılıkları (`depends_on`) ile başlangıç sırası yönetilir.
- **Prometheus scrape topolojisi (`docker/prometheus/prometheus.yml`):** `metrics_path: /metrics/llm/prometheus` üzerinden `sidar-web:7860` hedefini container ağında kazır; `global.scrape_interval: 15s` ile uygulama içi iş yükünü artırmadan dıştan metrik toplama modeli uygular.
- **Grafana auto-provisioning (`docker/grafana/provisioning/*`):** Datasource (`datasources/prometheus.yml`) ve dashboard provider (`dashboards/dashboards.yml`) tanımları kod olarak tutulur; konteyner her açıldığında manuel adım olmadan hazır dashboard'lar yüklenir.
- **JSON-as-Code dashboard (`docker/grafana/dashboards/sidar-llm-overview.json`):** LLM token, maliyet ve latency metriklerini standart panel setiyle sunar; dashboard değişiklikleri sürüm kontrolüne girerek denetlenebilir hale gelir.
- **Kurumsal cutover/rollback playbook (`runbooks/production-cutover-playbook.md`):** SQLite → PostgreSQL geçişinde pre-flight, Alembic migration zinciri, `--dry-run` veri taşıma provası ve kritik hata durumunda rollback adımlarını SOP düzeyinde tanımlar.
- **Host sandbox rollout notları (`runbooks/production-cutover-playbook.md` + `scripts/install_host_sandbox.sh`):** gVisor/Kata runtime kurulumu, doğrulama checklist'i ve kontrollü restart adımlarıyla production güvenlik sertleşmesini operasyonel sürece bağlar.

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
| Çoklu Kullanıcı (Tenant) İzolasyonu | ✓ Aktif (`user_id` tabanlı) | `core/db.py` — `users`, `auth_tokens`, `sessions`, `messages`, `daily_llm_usage` |
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

- **`test_*.py` modül sayısı:** **91**
- **`tests/*.py` toplamı ( `conftest.py` + `__init__.py` dahil ):** **93**
- **Toplam test satırı (`tests/*.py`):** **20.904**

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

- Güncel depoda `test_*.py` desenine uyan **91 test modülü** bulunur; `tests/*.py` toplamı (yardımcı dosyalar dahil) **93** adettir.
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
| `config.py` | 589 |
| `main.py` | 341 |
| `cli.py` | 288 |
| `web_server.py` | 1.376 |
| `agent/sidar_agent.py` | 1.651 |
| `agent/auto_handle.py` | 601 |
| `agent/definitions.py` | 165 |
| `agent/tooling.py` | 266 |
| `agent/base_agent.py` | 55 |
| `core/llm_client.py` | 839 |
| `core/memory.py` | 316 |
| `core/rag.py` | 783 |
| `core/db.py` | 989 |
| `core/llm_metrics.py` | 235 |
| `managers/security.py` | 290 |
| `managers/code_manager.py` | 805 |
| `managers/github_manager.py` | 644 |
| `managers/system_health.py` | 475 |
| `managers/web_search.py` | 387 |
| `managers/package_info.py` | 322 |
| `managers/todo_manager.py` | 451 |
| `github_upload.py` | 294 |

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
| `scripts/install_host_sandbox.sh` | 199 |
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
| `web_ui/chat.js` | 695 |
| `web_ui/sidebar.js` | 408 |
| `web_ui/rag.js` | 131 |
| `web_ui/app.js` | 670 |
| **Web UI Toplamı** | **4.160** |
| **Test modülü (`tests/test_*.py`)** | **91** |
| **`tests/*.py` toplam dosya** | **93** |
| **`tests/*.py` toplam satır** | **20.904** |

### 8.5 Dizin Bazlı Hacim Özeti

| Dizin/Kapsam | Ölçüm | Değer |
|---|---|---:|
| `tests/` | `test_*.py` modül sayısı | 91 |
| `tests/` | `*.py` toplam dosya | 93 |
| `tests/` | `*.py` toplam satır | 20.904 |
| `scripts/` | dosya sayısı | 6 |
| `scripts/` | toplam satır | 442 |
| `migrations/` | dosya sayısı (tüm migration dosyaları) | 3 |
| `migrations/` | toplam satır | 187 |
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

### 9.3 Güvenlik Zinciri: CodeManager → SecurityManager (Hard Coupling)

- `managers/code_manager.py`, kurulumda zorunlu `SecurityManager` instance’ı alır (`CodeManager(security=...)`).
- Dosya okuma/yazma ve yürütme öncesi güvenlik kararları `SecurityManager` denetimlerinden geçirilir.
- Bu nedenle yöneticiler genel olarak modüler olsa da, **kod yürütme hattında güvenlik açısından bilinçli bir hard-coupling** vardır.

### 9.4 DB Merkezli Bellek ve Kimlik Hiyerarşisi

- `core/memory.py` içindeki `ConversationMemory`, kalıcılık için doğrudan `core/db.py::Database` katmanına bağlıdır.
- Web katmanı (`web_server.py`) token tabanlı kimlik doğrulama/oturum çözümlemesinde DB kayıtlarını kullanır.
- `agent/core/memory_hub.py` ise DB yerine kısa ömürlü role/global notlar tutan hafif bir orchestrasyon belleğidir; DB merkezli uzun ömürlü oturum belleğinin yerini almaz, onu tamamlar.

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
- CI kalite kapıları (coverage hard gate, migration/sandbox doğrulama) olgunlaştırması.

### 11.2 Yeni Nesil Kurumsal Teknik Borçlar (Açık)

| # | Sorun | Dosya/Alan | Etki | Öncelik | Durum |
|---|-------|------------|------|---------|-------|
| 1 | Sync/Async köprü maliyeti (`_run_coro_sync`) | `core/memory.py` | Event loop içinden thread-bridge ile çağrı maliyeti ve debug karmaşıklığı artıyor; tam async dönüşüm ihtiyacı sürüyor | Orta | ⚠ **AÇIK** |
| 2 | Vanilla JS UI ölçeklenme riski | `web_ui/*.js` | Event stream + dashboard + auth durumları büyüdükçe DOM/state yönetimi karmaşıklaşıyor; component tabanlı çatı ihtiyacı doğuyor | Orta | ⚠ **AÇIK** |
| 3 | Sağlayıcılar arası tool-calling şema farkları | `core/llm_client.py`, `agent/tooling.py` | OpenAI/Anthropic/Gemini format farkları if/else yüzeyini büyütüyor; soyutlama sızıntısı riski | Orta | ⚠ **AÇIK** |
| 4 | Sandbox kaynak kotası standardizasyonu (cgroups) | `managers/code_manager.py`, Docker runtime profilleri | İzolasyon mevcut olsa da host profilleri arasında CPU/RAM limit standardı daha da sertleştirilmeli | Orta | ⚠ **AÇIK** |
| 5 | Operasyonel artefakt tutarlılığı (`.note`) | repo kökü / dokümantasyon | Rapor kapanış notlarıyla depodaki artefakt durumu zaman zaman ayrışabiliyor; audit izlenebilirliği etkileniyor | Düşük | ⚠ **AÇIK** |


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
| `ANTHROPIC_API_KEY` | `""` | Anthropic/Claude (örn. Claude 3.5 Sonnet) için zorunlu API anahtarı |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-latest` | Anthropic model adı |
| `ANTHROPIC_TIMEOUT` | `60` | Anthropic istek zaman aşımı (sn) |

> **Sağlayıcı Seçimi Notu:** Kod içinde ayrı bir `DEFAULT_LLM_PROVIDER` veya `ACTIVE_PROVIDER` değişkeni kullanılmamaktadır; aktif sağlayıcı doğrudan `AI_PROVIDER` ile belirlenir.

### 12.2 Güvenlik ve Erişim

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `ACCESS_LEVEL` | `full` | `restricted` / `sandbox` / `full` |
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
| `HF_TOKEN` | `""` | HuggingFace token (özel modeller) |
| `HF_HUB_OFFLINE` | `false` | HF Hub çevrimdışı mod |
| `GITHUB_TOKEN` | `""` | GitHub API token |
| `GITHUB_REPO` | `""` | Varsayılan GitHub repo (`owner/repo`) |
| `GITHUB_WEBHOOK_SECRET` | `""` | GitHub webhook HMAC doğrulama gizli anahtarı |
| `PACKAGE_INFO_TIMEOUT` | `12` | Paket bilgi HTTP zaman aşımı (sn) |
| `PACKAGE_INFO_CACHE_TTL` | `1800` | Paket bilgi cache süresi (sn) |
| `ENABLE_MULTI_AGENT` | `true` | Multi-agent Supervisor modunu etkinleştirir (Strangler Pattern, varsayılan açık; `false` deprecate) |

---

## 13. Olası İyileştirmeler (v4.0 Kurumsal Yol Haritası)

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, v3.0 ile **zaten tamamlanan** kazanımları (DB geçişi, multi-agent, sandbox, observability) tekrar etmek yerine, bir sonraki kurumsal sıçrama için v4.0 hedeflerini listeler.

| İyileştirme Alanı (v4.0) | Mevcut Durum (v3.0) | Önerilen Geliştirme |
|---|---|---|
| **Kubernetes/Helm ile Ölçekleme** | `docker-compose` tabanlı güçlü operasyon akışı mevcut | Çok tenantlı ve yüksek eşzamanlı yükte yatay ölçekleme için K8s deployment + HPA + Helm chart standardizasyonu |
| **LLM Gateway/Proxy Katmanı** | Sağlayıcılar `core/llm_client.py` içinde provider-bazlı yönetiliyor | LiteLLM/OpenRouter benzeri merkezi gateway ile model yönlendirme, kota/anahtar yönetimi, failover ve maliyet politikalarının tek noktadan yönetimi |
| **Kurumsal Vektör Veri Katmanı** | ChromaDB + FTS5/BM25 hibrit arama aktif | Büyük kurumsal korpuslarda pgvector/Milvus/Qdrant gibi dağıtık vektör altyapılarıyla ölçeklenebilir retrieval katmanı |
| **Dinamik Agent Swarm + Marketplace** | Coder/Researcher/Reviewer rolleri üretimde sabit tanımlı | Göreve göre dinamik uzman ajan türetimi (swarm), araç/ajan eklenti pazaryeri ve çalışma zamanı yetenek keşfi |
| **Reaktif Frontend ve Gelişmiş Admin UI** | Modüler Vanilla JS SPA + temel admin yüzeyleri mevcut | React/Next.js (veya Vue) ile stateful UI, canlı P2P ajan diyaloğu görselleştirme, tenant kota/anahtar yönetimi için gelişmiş yönetim paneli |

> **Kapsam Notu:** v3.0 ile tamamlanan “DB'ye geçiş, web arayüzü, güvenli kod çalıştırma, telemetri” gibi başlıklar artık teknik borç veya iyileştirme adayı değil; operasyonel olarak kapanmış yeteneklerdir.


---

## 14. Geliştirme Yol Haritası ve v3.0 Vizyonu (v2.11+)

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, v2.10.8 sonrası dönemde projeyi **v3.0 olgunluğuna** taşıyacak stratejik adımları içerir.

### 14.1 Eski Mimarinin Emekliye Ayrılması (Deprecation)
- ✅ `SidarAgent` akışı Supervisor-first tek omurgaya taşındı; legacy ReAct/feature-flag çatallanması kaldırıldı.
- ✅ Strangler Pattern kapanışı tamamlandı; multi-agent orkestrasyon tek giriş noktasıdır.
- ℹ Deprecation notları geriye uyumluluk kayıtlarında tutulur; çalışma zamanı artık legacy fallback kullanmaz.

### 14.2 Reviewer (QA) Ajanının Olgunlaştırılması
- `ReviewerAgent` temel rolü devrededir; bir sonraki adım kalite kapıları ve regresyon sinyallerini derinleştirmektir.
- Hedef: kod inceleme, test çalıştırma, regresyon tespiti ve kalite geri bildirim döngüsünü otomatikleştirmek.
- Önerilen akış: `Coder → Reviewer → (gerekirse tekrar Coder) → Supervisor final`.

### 14.3 Bütçe ve Token Yönetim Paneli (Dashboard)
- OpenAI ve Anthropic kullanımında token tüketimi, API maliyeti, hata oranı ve latency metriklerinin merkezileştirilmesi.
- Web UI tarafında sağlayıcı bazlı canlı izleme paneli (grafik/uyarı eşikleri) eklenmesi.
- OpenTelemetry + Prometheus/Grafana hattı üzerinden operasyonel görünürlük standardizasyonu.
- `core/llm_client.py` içinde OpenAI/Anthropic token (prompt/completion), latency ve hata/rate-limit metrikleri toplanıp `web_server.py` üzerinden `/metrics/llm` ve `/api/budget` uçlarıyla dışa açılmalıdır/aktiftir (v2.10.8+).

### 14.4 Kalıcı Çoklu Kullanıcı (Multi-User) Altyapısı
- ✅ Çoklu kullanıcı için DB tabanlı şema (`users`, `sessions`, `messages`, `user_quotas`, `provider_usage_daily`) devrede.
- ✅ Şema versiyonlama altyapısı (`schema_versions`) eklendi; SQLite/PostgreSQL için hedef versiyona ilerleme adımı mevcut.
- 🟡 Sonraki adım: resmi Alembic migration zinciri ve PostgreSQL production cutover playbook'u.

### 14.5 Test Kapsamının %95+ Seviyesine Zorlanması
- Boş test artifact riskine karşı CI hattında `find tests -type f -size 0` kontrolünün kalıcı olarak çalıştırılması (aktif).
- Kritik iş kuralları için branch + integration kapsamının artırılması.
- CI hattında coverage eşiğinin `%95+` altına düştüğünde PR engelleyecek kalite kapısı uygulanması.

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
| **Multi-Agent Orkestrasyonu (Supervisor)** | `agent/core/supervisor.py`, `agent/roles/*` | `ENABLE_MULTI_AGENT=true` (varsayılan) / `false` (legacy, deprecate) | ✅ Tamamlandı *(Geriye uyumluluk geçiş aşamasında)* |
| **Bağımsız Uzman Ajan Rolleri** (CoderAgent + ResearcherAgent) | `agent/base_agent.py`, `agent/roles/*` | `ENABLE_MULTI_AGENT=true` (aktif kullanım için) | ✅ Tamamlandı |
| Konuşma belleği | — (stdlib: `json`, `uuid`) | `MAX_MEMORY_TURNS` (opsiyonel) | ✅ Tamamlandı |
| Bellek şifreleme | `cryptography` | `MEMORY_ENCRYPTION_KEY` | ✅ Tamamlandı |
| GitHub entegrasyonu | `PyGithub` | `GITHUB_TOKEN`, `GITHUB_REPO`, `GITHUB_WEBHOOK_SECRET` | ✅ Tamamlandı |
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

**Belirti:** Coder/Researcher rol çağrıları görünmüyor; sistem legacy tekli ajan gibi davranıyor.

| Olası Neden | Nereden Anlaşılır | Çözüm |
|-------------|-------------------|-------|
| Multi-agent bayrağı kapalı | Akışta `SupervisorAgent` izi yok; legacy ReAct çalışıyor | `.env` içinde `ENABLE_MULTI_AGENT=true` ayarla |
| Süreç yeniden başlatılmadı | `.env` değişikliği sonrası davranış değişmiyor | Uygulamayı tamamen yeniden başlat (CLI/Web server) |
| Yanlış ortam dosyası yükleniyor | `SIDAR_ENV` profili beklenenden farklı | Etkin `.env.<profile>` dosyasını ve `SIDAR_ENV` değerini kontrol et |

---

## 18. Doğrulanmış Çözüm Özeti (2026-03-10 Audit #8 — Güncel)

[⬆ İçindekilere Dön](#içindekiler)

Bu bölüm, Audit #8 itibarıyla projenin ulaştığı güncel doğrulanmış çözüm durumunu özetler; önceki audit kayıtları tarihsel iz olarak korunur.


**Audit #8 Kapanışında Öne Çıkan Güncel Doğrulamalar:**
- ✅ **Tüm büyük modüllerin satır sayıları Audit #7 ile eşleşiyor** — değişiklik yok.
- ✅ **Python kaynak toplam güncellendi:** ~11.023 satır (tests hariç, tüm .py dahil); ~10.746 yalnızca büyük modüllerin toplamıydı.
- ✅ **RFC-MultiAgent.md satır sayısı düzeltildi:** 303 satır (önceki "~200" tahmini).
- ✅ **`ENABLE_MULTI_AGENT` `.env.example`'da mevcut** (satır 81) — §18.6.5'teki "Eksik" iddiası hatalıydı, düzeltildi.
- ⚠ **İki boş artifact hâlâ silinmedi:** `test_config_runtime_coverage` ve `test_config_runtime_coverage.py`.
- ⚠ **`ReviewerAgent` hâlâ eksik:** `agent/roles/reviewer_agent.py` mevcut değil.
- ⚠ `.note` dosyası depoda mevcut; “kaldırıldı” ifadeleri güncel duruma göre revize edilmelidir.

**Audit #7 Kapanışında Öne Çıkan Güncel Çözümler:**
- ✅ **Multi-Agent Altyapısı Entegre Edildi:** Legacy tekli ajan sınırları aşılarak `Supervisor` + `CoderAgent` + `ResearcherAgent` mimarisi devreye alındı; geçiş `ENABLE_MULTI_AGENT` feature toggle ve Strangler Pattern ile yönetiliyor.
- ✅ **Çoklu LLM (Cloud AI) Desteği Eklendi:** `BaseLLMClient` altında Ollama + Gemini + OpenAI + Anthropic sağlayıcıları tek çatıya alındı; yapısal JSON çıktı akışlarıyla uyumluluk güçlendirildi.
- ✅ **Hata ve Maliyet (Rate Limit) Yönetimi Güçlendirildi:** 429 / timeout / parse hatalarına karşı birleştirilmiş hata yaklaşımı, `MAX_REACT_STEPS` limit koruması ve güvenli düşüş stratejileri raporlandı.
- ✅ **Güvenlik Sınırları Maksimuma Çıkarıldı:** `/file-content` için 1 MB okuma limiti ve `/api/webhook` için HMAC-SHA256 imza doğrulaması aktif hale getirildi.
- ✅ **Test Kapsamı Genişletildi:** Multi-agent ve yeni sağlayıcı akışlarını doğrulayan test modülleri (örn. `test_supervisor_agent.py`, `test_anthropic_provider_runtime.py`) test envanterine eklendi.

### 18.1 Önceki Raporda "Çözüldü" Olarak İşaretlenmiş ve Doğrulanan Maddeler

| Madde | Doğrulama | Dosya / Referans |
|-------|-----------|-----------------|
| CLI `asyncio.Lock` lifetime hatası | ✅ `_interactive_loop_async()` tek async fonksiyon; `asyncio.run()` döngü dışında | `cli.py:1` |
| RAG oturum izolasyonu | ✅ `session_id` filtresi ChromaDB `where=` ve SQLite `WHERE` clause | `rag.py:_fetch_chroma`, `_fetch_bm25` |
| RRF hibrit sıralama | ✅ `_rrf_search()` k=60, her iki motordan bağımsız getirme | `rag.py:_rrf_search` |
| Sliding window özetleme | ✅ `apply_summary()` son `keep_last`=4 mesajı korur | `memory.py:apply_summary` |
| Web UI modülarizasyonu | ✅ 6 ayrı dosya; `StaticFiles` mount aktif | `web_server.py`, `web_ui/` |
| Bearer Token Auth | ✅ `basic_auth_middleware` + `auth_tokens` doğrulaması | `web_server.py`, `core/db.py` |
| DDoS rate limit | ✅ `ddos_rate_limit_middleware` 120 istek/60 sn; `/static/` muaf | `web_server.py` |
| LLM istemci yeniden yapılandırma | ✅ `BaseLLMClient` ABC + 3 concrete impl | `llm_client.py` |
| DuckDuckGo timeout koruması | ✅ `asyncio.wait_for` + doğru except sırası | `web_search.py` |
| GitHub Issue yönetimi | ✅ list/create/comment/close; 4 metod + 4 ajan aracı | `github_manager.py`, `tooling.py` |
| PR diff aracı | ✅ `get_pull_request_diff(pr_number)` + `github_pr_diff` ajan aracı | `github_manager.py` |
| `scan_project_todos` | ✅ `TodoManager.scan_project_todos()` + `ScanProjectTodosSchema` | `todo_manager.py`, `tooling.py` |
| Non-root Docker kullanıcısı | ✅ `sidaruser` uid=10001 | `Dockerfile` |
| Docker health check | ✅ web modunda `/status`, CLI'de PID 1 kontrol | `Dockerfile` |
| RAG pre-cache | ✅ `PRECACHE_RAG_MODEL=true` build-arg ile `all-MiniLM-L6-v2` önceden indirilir | `Dockerfile` |
| SQLite FTS5 disk tabanlı BM25 | ✅ `_init_fts()` PersistentClient; `unicode61 remove_diacritics 1` tokenizer | `rag.py:_init_fts` |
| Prometheus metrikleri | ✅ `update_prometheus_metrics()` + lazy Gauge init | `system_health.py` |
| OpenAI istemci | ✅ `OpenAIClient` + `response_format: json_object` | `llm_client.py` |
| Drag-drop dosya yükleme | ✅ `/api/rag/upload` endpoint; temp dizin temizleme | `web_server.py` |
| Coverage zorunluluğu (global %70 + kritik modüller %80) | ✅ `run_tests.sh` içinde iki aşamalı `pytest --cov` kapısı tanımlı | `run_tests.sh` |
| Performans benchmark baseline'ları | ✅ `tests/test_benchmark.py` ile ChromaDB/BM25/regex hedef eşikleri doğrulanıyor | `tests/test_benchmark.py` |

### 18.2 Rapor Düzeltme Özeti — Audit #2 (2026-03-08, Sürüm v2.10.0)

*Bu tablo, önceki raporun taşıdığı hatalı satır sayılarının o audit'te nasıl düzeltildiğini gösterir (tarihsel kayıt).*

| Dosya | Rapordaki (Eski) | Audit #2 Sonrası Düzeltme |
|-------|-----------------|--------------------------|
| `agent/sidar_agent.py` | 1.455/1.463 | 1.630 |
| `web_server.py` | 794/801 | 951 |
| `core/rag.py` | 777/851 | 787 |
| `managers/code_manager.py` | 746 | 766 |
| `managers/github_manager.py` | 560 | 644 |
| `managers/system_health.py` | 420 | 436 |
| `managers/todo_manager.py` | 380 | 451 |
| `agent/tooling.py` | 189 | 264 |
| `core/llm_client.py` | 445/513 | 570 |
| `config.py` | 480/517/520 | 528 |
| `web_ui/app.js` | 242 | 339 |
| `web_ui/index.html` | 436 | 461 |
| Web UI toplam | 3.394/3.399 | 3.516 |

---

### 18.3 Rapor Düzeltme Özeti — Audit #3 (2026-03-08, Güncel)

Bu bölüm, 2026-03-08 tarihli üçüncü kapsamlı audit'te tespit edilen ve düzeltilen hataları özetler. `wc -l` ile tüm dosyalar yeniden ölçüldü; "çözüldü" işaretli tüm maddeler doğrulandı.

#### 18.3.1 Satır Sayısı Düzeltmeleri

| Dosya | Audit #2'deki Değer | Gerçek (Audit #3) | Fark |
|-------|--------------------|--------------------|------|
| `web_server.py` | 951/957 | **1.108** | +151–157 |
| `agent/sidar_agent.py` | 1.630 | **1.659** | +29 |
| `cli.py` | 274/275 | **288** | +13–14 |
| `config.py` | 528 | **544** | +16 |
| `managers/security.py` | 280 | **290** | +10 |
| `web_ui/chat.js` | 654 | **656** | +2 |
| Web UI toplam | 3.516 | **3.528** | +12 |
| Toplam Python | ~11.170 | **~12.715** | +1.545 |
| Genel Toplam | ~14.686 | **~16.243** | +1.557 |

#### 18.3.2 Test Sayısı Düzeltmesi

| Metrik | Önceki Değer | Gerçek Değer |
|--------|-------------|--------------|
| Test modülü sayısı | 34 | **39** |
| Test toplam satır | ~2.157 | **~2.362** |

Eksik listelenen test dosyaları: `test_benchmark.py`, `test_coverage_policy.py`, `test_quality_tooling_config.py`, `test_config_env_profiles.py`, `test_github_webhook.py`, `test_security_level_transition.py`

#### 18.3.3 Doğrulanan "Çözüldü" İddiaları

| Madde | Doğrulama Yöntemi | Sonuç |
|-------|------------------|-------|
| CLI `asyncio.Lock` fix | `cli.py:114` — `_interactive_loop_async()` + `cli.py:213` — tek `asyncio.run()` | ✅ Onaylandı |
| WebSocket altyapısı | `web_server.py:322` — `@app.websocket("/ws/chat")` aktif | ✅ Onaylandı |
| Sandbox çıktı limiti | `code_manager.py:50` — `max_output_chars = 10000` | ✅ Onaylandı |
| Redis rate limiting | `web_server.py:33` — `from redis.asyncio import Redis` + fallback mekanizması | ✅ Onaylandı |
| SIDAR_ENV konfigürasyonu | `config.py:31` — `sidar_env = os.getenv("SIDAR_ENV")` + override yükleme | ✅ Onaylandı |
| Coverage eşikleri | `run_tests.sh:7` — `--cov-fail-under=70` + `run_tests.sh:15` — `--cov-fail-under=80` | ✅ Onaylandı |
| audit.jsonl denetim logu | `sidar_agent.py:1343-1346` — `logs/audit.jsonl` yazım metodu | ✅ Onaylandı |
| DuckDuckGo timeout | `web_search.py` — `asyncio.wait_for` + `AsyncDDGS` dinamik kontrol | ✅ Onaylandı |

#### 18.3.4 Yeni Açık Bulgu (Audit #3)

| Bulgu | Konum | Detay | Öncelik |
|-------|-------|-------|---------|
| `/file-content` boyut limiti yok | `web_server.py:622-624` | `target.read_text()` tüm dosyayı belleğe alır; GB'lık dosyalarda DoS riski | Orta |

---

### 18.4 Rapor Düzeltme Özeti — Audit #4 (2026-03-10)

Bu bölüm, 2026-03-10 tarihli dördüncü kapsamlı audit'te tespit edilen tüm uyumsuzlukları ve doğrulama sonuçlarını özetler. Tüm kaynak dosyalar `wc -l` ile yeniden ölçülmüş; rapordaki her "çözüldü" iddiası kaynak kodda teyit edilmiştir.

#### 18.4.1 Satır Sayısı Düzeltmeleri

| Dosya | Audit #3'teki Değer | Gerçek (Audit #4) | Fark |
|-------|---------------------|-------------------|------|
| `web_server.py` | 1.108 | **1.126** | +18 |
| `core/rag.py` | 787 | **783** | -4 |
| `managers/web_search.py` | 379 | **387** | +8 |
| `managers/package_info.py` | 314 | **322** | +8 |
| `core/memory.py` | 394 | **402** | +8 |
| `agent/tooling.py` | 264 | **266** | +2 |
| Diğer tüm dosyalar | — | ✅ Audit #3 ile aynı | 0 |

#### 18.4.2 Test Modülü Güncellemesi

| Metrik | Audit #3 Değeri | Gerçek (Audit #4) |
|--------|-----------------|--------------------|-------------------|
| Test modülü sayısı (.py) | 39 | **63** |
| Test toplam satır | ~2.362 | **~15.833** |
| Yeni eklenen modül | — | **24** (`*_runtime.py` ve diğerleri) |
| `test_web_server_runtime.py` öne çıkan | — | **1.470 satır** (en büyük yeni dosya) |

#### 18.4.3 Doğrulanan "Çözüldü" İddiaları (Audit #4)

Audit #3'te onaylanan tüm maddeler bu audit'te de doğrulanmıştır:

| Madde | Konum | Sonuç |
|-------|-------|-------|
| CLI `asyncio.Lock` fix | `cli.py:114` — `_interactive_loop_async()` | ✅ Onaylandı |
| WebSocket `/ws/chat` | `web_server.py:340` — `@app.websocket` | ✅ Onaylandı |
| Sandbox çıktı limiti | `code_manager.py:50` — `max_output_chars = 10000` | ✅ Onaylandı |
| Redis rate limiting + local fallback | `web_server.py:182-196` | ✅ Onaylandı |
| SIDAR_ENV konfigürasyonu | `config.py:31-47` | ✅ Onaylandı |
| Coverage eşikleri (%70 + %80) | `run_tests.sh:7,15` | ✅ Onaylandı |
| audit.jsonl denetim logu | `sidar_agent.py:1342-1346` | ✅ Onaylandı |
| DuckDuckGo timeout + AsyncDDGS dinamik kontrol | `web_search.py:232-279` | ✅ Onaylandı |
| GitHub webhook HMAC (`X-Hub-Signature-256`) | `web_server.py:1013-1029` | ✅ Onaylandı |
| Güvenlik seviyesi geçiş logu | `sidar_agent.py:1618,1628` | ✅ Onaylandı |
| OpenTelemetry tracing | `web_server.py:138-154` | ✅ Onaylandı |
| OpenAPI Swagger (`/docs` + `/redoc`) | `web_server.py:101-103` | ✅ Onaylandı |
| Non-root Docker kullanıcısı (sidaruser uid=10001) | `Dockerfile:90-91` | ✅ Onaylandı |
| Docker sağlık kontrolü (HEALTHCHECK) | `Dockerfile:99` | ✅ Onaylandı |
| Prometheus metrikleri (lazy init) | `system_health.py:283-309` | ✅ Onaylandı |
| RAG oturum izolasyonu (ChromaDB `where=` + SQLite `WHERE`) | `rag.py:567,630` | ✅ Onaylandı |
| RRF hibrit sıralama (k=60) | `rag.py:532-558` | ✅ Onaylandı |
| SQLite FTS5 disk tabanlı BM25 | `rag.py:202-238` | ✅ Onaylandı |
| Sliding window özetleme | `memory.py:332-339` | ✅ Onaylandı |

#### 18.4.4 Yeni Bulgular (Audit #4)

| # | Bulgu | Konum | Detay | Öncelik |
|---|-------|-------|-------|---------|
| 1 | `/file-content` boyut limiti yok *(Audit#3'ten süregelen)* | `web_server.py:641` | `target.read_text()` boyut kontrolsüz; GB dosyalarda DoS riski | Orta |
| 2 | `.env.example`'da eksik değişkenler | `.env.example` | `GITHUB_WEBHOOK_SECRET`, `SIDAR_ENV`, `MEMORY_SUMMARY_KEEP_LAST` eksik | Düşük |
| 3 | Boş artifact dosyası | `tests/test_config_runtime_coverage` | 0 bayt boş dosya; test sayısı karıştırır; kaldırılabilir | Düşük |
| 4 | DDG versiyon pin formatı uyumsuzluğu (belge ↔ kod) | `environment.yml`, `requirements.txt` | Raporda `~=6.2.13`; gerçekte `==6.2.13` | Düşük |

---

---

### 18.5 Rapor Düzeltme Özeti — Audit #6 (2026-03-10)

Bu bölüm, 2026-03-10 tarihli Audit #6 kapanış güncellemesinde Audit #5'te açık kalan maddelerin çözüm durumunu özetler. Tüm kritik dosyalar `wc -l` ile yeniden ölçülmüş; rapordaki durumlar kodla eşitlenmiştir.

#### 18.5.1 Audit #4/#5 Açık Sorunlarının Çözüm Durumu

| # | Sorun (Audit #4) | Durum (Audit #5) | Doğrulama |
|---|-----------------|-----------------|-----------|
| 1 | `/file-content` endpoint boyut limiti yok | ✅ **ÇÖZÜLDÜ** | `web_server.py:69` — `MAX_FILE_CONTENT_BYTES = 1_048_576` tanımlandı; `web_server.py:641-651` — `st_size` kontrolü + 413 yanıtı eklendi |
| 2 | `.env.example`'da `GITHUB_WEBHOOK_SECRET`, `SIDAR_ENV`, `MEMORY_SUMMARY_KEEP_LAST` eksik | ✅ **ÇÖZÜLDÜ** | `.env.example:38` — `GITHUB_WEBHOOK_SECRET=`; `.env.example:67` — `MEMORY_SUMMARY_KEEP_LAST=4`; `.env.example:71` — `SIDAR_ENV=development` |
| 3 | `test_config_runtime_coverage` boş dosya (0 bayt) | ✅ **ÇÖZÜLDÜ** | Dosya projeden silindi; test keşfi temizlendi |
| 4 | `duckduckgo-search` versiyon pin formatı (`==` vs `~=`) | ✅ **ÇÖZÜLDÜ** | `requirements.txt:16` ve `environment.yml:62` — her ikisi de `~=6.2.13` kullanıyor |

#### 18.5.2 Satır Sayısı Güncellemeleri (Audit #6)

| Dosya | Audit #5 Değeri | Gerçek (Audit #6) | Fark | Not |
|-------|------------------|-------------------|------|-----|
| `config.py` | 544 | **556** | +12 | OpenAI ayar/validasyon/özet güncellemesi |
| `web_server.py` | 1.139 | **1.139** | 0 | Provider seçeneği güncellendi, satır sayısı aynı |
| `cli.py` | 232 | **288** | 0 | Provider seçeneği güncellendi, satır sayısı aynı |
| `main.py` | 332 | **337** | +5 | OpenAI preflight + wizard provider seçeneği |
| Diğer dosyalar | — | ✅ Audit #5 ile uyumlu | — | |

#### 18.5.3 Doğrulanan "Çözüldü" İddiaları (Audit #6)

Audit #4'te onaylanan tüm maddeler bu audit'te de doğrulanmıştır. Ek olarak:

| Madde | Konum | Sonuç |
|-------|-------|-------|
| `/file-content` boyut limiti | `web_server.py:69,641-651` | ✅ `MAX_FILE_CONTENT_BYTES=1_048_576`; `413` yanıtı doğru dönüyor |
| `.env.example` eksik değişkenler | `.env.example:38,67,71` | ✅ Üç değişken de eklendi |
| DuckDuckGo pin formatı | `requirements.txt:16`, `environment.yml:62` | ✅ Her ikisi de `~=6.2.13` |

#### 18.5.4 Yeni Bulgular (Audit #5) — Audit #6 Durum Güncellemesi

| # | Bulgu | Konum | Audit #6 Durumu |
|---|-------|-------|------------------|
| 1 | **OpenAI provider eksik kayıt** | `config.py`, `.env.example`, `cli.py`, `web_server.py`, `main.py`, `requirements.txt`, `environment.yml` | ✅ **ÇÖZÜLDÜ** — OpenAI config alanları, provider seçenekleri ve bağımlılıklar eklendi; rapor §12.1 ile eşitlendi |
| 2 | **Rapor §12.1'de `AI_PROVIDER` açıklaması eksik** | `PROJE_RAPORU.md:§12.1` | ✅ **ÇÖZÜLDÜ** — `openai` üçüncü geçerli değer olarak belgelendi |
| 3 | **`WEB_FETCH_MAX_CHARS` raporda belgelenmemiş** | `PROJE_RAPORU.md:§12.5` | ✅ **ÇÖZÜLDÜ** — `WEB_FETCH_MAX_CHARS=12000` satırı tabloya eklendi |

---

*Bu rapor, projedeki tüm kaynak dosyaların satır satır incelenmesiyle 2026-03-07 tarihinde hazırlanmış; sonraki audit'lerde (2026-03-08 Audit #2, #3 ve 2026-03-10 Audit #4, #5, #6, #7, #8) güncellenerek doğrulanmıştır.*

---

### 18.6 Rapor Düzeltme Özeti — Audit #7 (2026-03-10)

Bu bölüm, 2026-03-10 tarihli yedinci kapsamlı audit'te tespit edilen tüm uyumsuzlukları, yeni modülleri ve açık bulguları özetler. Tüm kaynak dosyalar `wc -l` ile yeniden ölçülmüş; Audit #6'daki "çözüldü" iddiaları kaynak kodda teyit edilmiştir.

---

#### 18.6.1 Audit #6'dan Süregelen — Çözülmediği Tespit Edilen Madde

| # | Sorun | Audit #6 İddiası | Gerçek Durum |
|---|-------|-----------------|--------------|
| 1 | `test_config_runtime_coverage` (uzantısız, 0 bayt) | "Dosya projeden silindi" | ❌ **Hâlâ mevcut** (`tests/test_config_runtime_coverage`, 0 bayt) |

---

#### 18.6.2 Satır Sayısı Düzeltmeleri (Audit #7)

| Dosya | Audit #6 Değeri | Gerçek (Audit #7) | Fark | Sebep |
|-------|----------------|-------------------|------|-------|
| `config.py` | 556 | **570** | +14 | `ENABLE_MULTI_AGENT` + Anthropic validation + özet satırı |
| `main.py` | 337 | **341** | +4 | Anthropic wizard seçeneği |
| `web_server.py` | 1.139 | **1.173** | +34 | `_try_multi_agent`, yeni endpoint'ler |
| `agent/sidar_agent.py` | 1.659 | **1.698** | +39 | `_try_multi_agent()` Strangler Pattern |
| `core/llm_client.py` | 570 | **723** | +153 | `AnthropicClient` tam sınıf (streaming dahil) |
| `web_ui/index.html` | 461 | **467** | +6 | UI güncellemeleri |
| `web_ui/app.js` | 339 | **356** | +17 | Uygulama başlatma güncellemeleri |
| **Web UI Toplam** | 3.528 | **3.551** | **+23** | |
| Diğer tüm dosyalar | — | ✅ Audit #6 ile uyumlu | 0 | |

---

#### 18.6.3 Tamamen Belgelenmemiş Yeni Modüller — Multi-Agent Mimarisi

Aşağıdaki dosyalar Audit #6 dahil hiçbir önceki raporda yer almamaktadır. Strangler Pattern ile `sidar_agent.py` üzerine `ENABLE_MULTI_AGENT` feature flag'i aracılığıyla entegre edilmiştir.

| Dosya | Satır | Açıklama |
|-------|-------|----------|
| `agent/base_agent.py` | 55 | `BaseAgent` — tüm uzman ajanlar için ortak LLM + tool dispatch soyut sınıfı |
| `agent/core/__init__.py` | 5 | `SupervisorAgent`, `TaskEnvelope`, `TaskResult` export |
| `agent/core/supervisor.py` | 164 | `SupervisorAgent` — intent tespiti + delegasyon + QA orkestrasyonu |
| `agent/core/contracts.py` | 56 | `TaskEnvelope`/`TaskResult` + `P2PMessage`/`DelegationRequest`/`DelegationResult` veri sözleşmeleri |
| `agent/roles/__init__.py` | 5 | `CoderAgent`, `ResearcherAgent` export |
| `agent/roles/coder_agent.py` | 134 | `CoderAgent` — dosya/kod araçlarıyla çalışan uzman ajan |
| `agent/roles/researcher_agent.py` | 75 | `ResearcherAgent` — web + RAG araçlarıyla çalışan uzman ajan |
| `RFC-MultiAgent.md` | ~200 | Mimari tasarım RFC belgesi (Draft; `v2.11.x` hedefi) |

**Entegrasyon Noktası (`sidar_agent.py`):**
```python
# Strangler Pattern: feature flag ile kapalı, geriye dönük uyumlu
async def _try_multi_agent(self, user_input: str) -> Optional[str]:
    if not getattr(self.cfg, "ENABLE_MULTI_AGENT", True):
        return None
    # SupervisorAgent lazy-init + route + [LEGACY_FALLBACK] kontrolü
```

**`ENABLE_MULTI_AGENT` Davranışı:**
- `false` (varsayılan): Multi-agent devre dışı; ReAct döngüsü normale devam eder.
- `true`: `SupervisorAgent` kullanıcı isteğini analiz eder; `research` → `ResearcherAgent`, `code` → `CoderAgent`, `unknown/review` → `[LEGACY_FALLBACK]` → klasik ReAct.

**RFC'de Belirtilmiş Ancak Henüz İmplemente Edilmemiş:**
- `ReviewerAgent` — GitHub/PR/Issue inceleme rolü RFC-MultiAgent.md'de tanımlanmış, `agent/roles/` içinde mevcut değil.

---

#### 18.6.4 Yeni Test Modülleri (Audit #7 — 6 adet)

| Test Dosyası | Satır | Kapsam | Durum |
|-------------|-------|--------|-------|
| `test_supervisor_agent.py` | 42 | `SupervisorAgent` route mantığı + `TaskEnvelope`/`TaskResult` sözleşme testleri | ✅ İçerikli |
| `test_coder_agent.py` | 38 | `CoderAgent` araç seti ve doğal dil yazma yorumu | ✅ İçerikli |
| `test_researcher_agent.py` | 24 | `ResearcherAgent` araç seti ve web_search yönlendirmesi | ✅ İçerikli |
| `test_anthropic_provider_runtime.py` | 31 | `AnthropicClient` API key eksikliği + `LLMClient` factory | ✅ İçerikli |
| `test_config_runtime_coverage.py` | 0 | **BOŞ** — Audit #6 sonrası oluşturulmuş artifact | ⚠ Kaldırılmalı |
| `test_config_runtime_coverage` (uzantısız) | 0 | **BOŞ** — Audit #6'dan süregelen artifact | ⚠ Kaldırılmalı |

---

#### 18.6.5 `.env.example` Değişken Durumu (Audit #7 → Audit #8 düzeltmesi)

| Değişken | `config.py` Referansı | `.env.example` Durumu |
|----------|----------------------|----------------------|
| `ENABLE_MULTI_AGENT` | `config.py:230` — `get_bool_env("ENABLE_MULTI_AGENT", True)` | ✅ **Mevcut** — `.env.example:81` (`ENABLE_MULTI_AGENT=true`) |

> **Audit #8 Düzeltmesi (2026-03-10):** Bu bölümde daha önce "❌ Eksik" yazıyordu. Audit #8'de `.env.example` dosyası satır satır incelenmiş; `ENABLE_MULTI_AGENT=true` değerinin **satır 81**'de bulunduğu doğrulanmıştır. §11.2 zaten "ÇÖZÜLDÜ" olarak işaretlemişti — §18.6.5 ile çelişki bu düzeltmeyle giderilmiştir.
>
> **11 Mart 2026 Doğrulaması (Audit #7.1):** `ENABLE_MULTI_AGENT=true` değişkeni `.env.example` içinde varsayılan olarak mevcuttur; bu başlık altındaki durum **✅ ÇÖZÜLDÜ** olarak korunmalıdır.

---

#### 18.6.6 Doğrulanan "Çözüldü" İddiaları (Audit #7)

Audit #6'da onaylanan tüm maddeler bu audit'te de doğrulanmıştır:

| Madde | Konum | Sonuç |
|-------|-------|-------|
| `/file-content` boyut limiti | `web_server.py:70` — `MAX_FILE_CONTENT_BYTES = 1_048_576`; `:676` — `st_size` kontrolü + 413 | ✅ Onaylandı |
| `.env.example` — `GITHUB_WEBHOOK_SECRET` | `.env.example:48` | ✅ Onaylandı |
| `.env.example` — `MEMORY_SUMMARY_KEEP_LAST` | `.env.example:77` | ✅ Onaylandı |
| `.env.example` — `SIDAR_ENV` | `.env.example:81` | ✅ Onaylandı |
| DuckDuckGo pin formatı `~=6.2.13` | `requirements.txt:18`, `environment.yml:64` | ✅ Onaylandı |
| OpenAI uçtan uca entegrasyon | `config.py:245-247`, `cli.py:238`, `main.py:306`, `web_server.py:1133` | ✅ Onaylandı |
| Anthropic uçtan uca entegrasyon | `config.py:248-250`, `core/llm_client.py:504-668`, `requirements.txt:16`, `environment.yml:58` | ✅ Onaylandı |
| CLI `asyncio.Lock` fix | `cli.py:114` — `_interactive_loop_async()` + tek `asyncio.run()` | ✅ Onaylandı |
| WebSocket `/ws/chat` | `web_server.py:340` | ✅ Onaylandı |
| Sandbox çıktı limiti | `code_manager.py:50` — `max_output_chars = 10000` | ✅ Onaylandı |
| Redis rate limiting + local fallback | `web_server.py:182-196` | ✅ Onaylandı |
| SIDAR_ENV multi-env konfigürasyonu | `config.py:31-47` | ✅ Onaylandı |
| Coverage eşikleri (%70 + %80) | `run_tests.sh:7,15` | ✅ Onaylandı |
| audit.jsonl denetim logu | `sidar_agent.py:1382-1396` | ✅ Onaylandı |
| Güvenlik seviyesi geçiş logu | `sidar_agent.py:1657-1684` | ✅ Onaylandı |
| GitHub webhook HMAC | `web_server.py:1052-1071` | ✅ Onaylandı |
| OpenTelemetry tracing | `web_server.py:115-154` | ✅ Onaylandı |
| OpenAPI Swagger/ReDoc | `web_server.py:137-139` | ✅ Onaylandı |
| RAG cold-start prewarm | `web_server.py:75`, `web_server.py:117` | ✅ Onaylandı |
| Non-root Docker kullanıcısı | `Dockerfile:90-91` — `sidaruser` uid=10001 | ✅ Onaylandı |
| Sliding window özetleme | `memory.py:332-339` | ✅ Onaylandı |
| RRF hibrit sıralama | `rag.py:_rrf_search` k=60 | ✅ Onaylandı |
| SQLite FTS5 disk tabanlı BM25 | `rag.py:_init_fts` | ✅ Onaylandı |
| RAG oturum izolasyonu | `rag.py:_fetch_chroma`, `_fetch_bm25` | ✅ Onaylandı |
| Prometheus metrikleri | `system_health.py:283-309` | ✅ Onaylandı |

---

#### 18.6.7 Audit #7 Özet

| Kategori | Sayı | Detay |
|----------|------|-------|
| **Onaylanan çözüldü** | 24 | Audit #6 ve önceki tüm maddeler doğrulandı |
| **Süregelen açık sorun** | 1 | `test_config_runtime_coverage` uzantısız 0 baytlık dosya |
| **Yeni tespit — açık** | 2 | 0 baytlık `.py` artifact, `ReviewerAgent` eksik |
| **Yeni belgelenen modül** | 7 | `base_agent.py`, `core/supervisor.py`, `core/contracts.py`, `roles/coder_agent.py`, `roles/researcher_agent.py`, `RFC-MultiAgent.md`, multi-agent test'leri |
| **Satır sayısı güncellenen dosya** | 7 | `config.py`, `main.py`, `web_server.py`, `sidar_agent.py`, `llm_client.py`, `index.html`, `app.js` |

---

### 18.7 Rapor Düzeltme Özeti — Audit #8 (2026-03-10)

Bu bölüm, 2026-03-10 tarihli sekizinci kapsamlı audit'te yapılan tam doğrulama ve yeni tespitleri özetler. Tüm kaynak dosyalar `wc -l` ve `find … | xargs wc -l` ile ölçülmüştür. Audit #7 "çözüldü" iddiaları kaynak kodda teyit edilmiştir.

---

#### 18.7.1 Audit #7'den Süregelen — Açık Kalan Sorunlar

| # | Sorun | Audit #7 İddiası | Audit #8 Durumu |
|---|-------|-----------------|-----------------|
| 1 | `test_config_runtime_coverage` (uzantısız, 0 bayt) | Açık | ⚠ **Hâlâ mevcut** (`tests/test_config_runtime_coverage`, 0 bayt, 2026-03-10 08:04 tarihli) |
| 2 | `test_config_runtime_coverage.py` (0 bayt) | Açık | ⚠ **Hâlâ mevcut** (`tests/test_config_runtime_coverage.py`, 0 bayt, 2026-03-10 22:52 tarihli) |
| 3 | `ReviewerAgent` eksik | RFC Draft | ⚠ **Hâlâ eksik** — `agent/roles/reviewer_agent.py` mevcut değil |

---

#### 18.7.2 Satır Sayısı Düzeltmeleri (Audit #8)

| Dosya | Audit #7 Değeri | Gerçek (Audit #8) | Fark | Sebep |
|-------|----------------|-------------------|------|-------|
| Tüm büyük modüller | (Audit #7'deki değerler) | ✅ Aynı | 0 | Değişiklik yok |
| `RFC-MultiAgent.md` | ~200 | **303** | +103 | Tahmini değerdi; `wc -l` ile ölçüldü |
| `Dockerfile` | 101 | **103** | +2 | Küçük fark |
| `docker-compose.yml` | 209 | **208** | -1 | Küçük fark |
| **Toplam Python kaynak (tüm .py, tests hariç)** | ~10.746 | **~11.023** | **+277** | `find … \| xargs wc -l` tüm .py; önceki sayı büyük modüllerin toplamıydı (`__init__.py` ve küçük dosyalar hariçti) |

> **Not (Audit #8):** ~10.746 ile ~11.023 arasındaki +277 fark; `agent/__init__.py`, `agent/core/__init__.py`, `agent/roles/__init__.py`, `core/__init__.py`, `managers/__init__.py` ve diğer küçük `.py` yardımcı dosyalarının (`.coveragerc`, `pytest.ini`, `run_tests.sh` Python bölümleri vb.) daha önce tabloya dahil edilmemesinden kaynaklanmaktadır.

---

#### 18.7.3 İçindekiler Düzeltmesi — §18.6.5 Çelişkisi Giderildi

| Madde | §11.2 İddiası | §18.6.5 Eski Durum | Gerçek Durum | Audit #8 Sonucu |
|-------|--------------|---------------------|--------------|-----------------|
| `ENABLE_MULTI_AGENT` `.env.example`'da | ✅ ÇÖZÜLDÜ | ❌ "Eksik" | ✅ `.env.example:81`'de mevcut | §18.6.5 düzeltildi ✅ |

---

#### 18.7.4 `.note` Scratchpad Dosyası — Durum Düzeltmesi

| Dosya | Satır | Durum | Detay |
|-------|-------|-------|-------|
| `.note` | **mevcut** | ⚠ **Açık Çelişki** | Kök dizinde `.note` dosyası bulunduğu için “kaldırıldı” kapanışı güncel depo ile uyumsuzdur. |

---

#### 18.7.5 Doğrulanan "Çözüldü" İddiaları (Audit #8)

Audit #7'de onaylanan tüm maddeler bu audit'te de doğrulanmıştır:

| Madde | Konum | Sonuç |
|-------|-------|-------|
| Tüm büyük modül satır sayıları | `wc -l` ölçümü | ✅ Audit #7 ile tam eşleşme |
| Test satır toplamı | `wc -l tests/*.py` | ✅ 15.974 satır teyit |
| Web UI toplam | `wc -l web_ui/*` | ✅ 3.551 satır teyit |
| `ENABLE_MULTI_AGENT` `.env.example`'da | `.env.example:81` | ✅ Mevcut (`ENABLE_MULTI_AGENT=true`) |
| `duckduckgo-search` pin formatı | `requirements.txt:18`, `environment.yml:64` | ✅ `~=6.2.13` teyit |
| `openai` ve `anthropic` pin formatları | `requirements.txt:15,16` | ✅ `openai~=1.51.2`, `anthropic~=0.40.0` |
| `_tool_` metod sayısı (`sidar_agent.py`) | `grep -c "def _tool_" agent/sidar_agent.py` | ✅ 50 araç metodu teyit |
| Audit logging (`logs/audit.jsonl`) | `sidar_agent.py:1382-1396` | ✅ Onaylandı |
| Güvenlik seviyesi geçiş logu | `sidar_agent.py:1657-1684` | ✅ Onaylandı |
| GitHub webhook HMAC | `web_server.py:1052-1071` | ✅ Onaylandı |
| RAG oturum izolasyonu | `rag.py:_fetch_chroma`, `_fetch_bm25` | ✅ Onaylandı |
| RRF hibrit sıralama (k=60) | `rag.py:_rrf_search` | ✅ Onaylandı |
| SQLite FTS5 disk tabanlı BM25 | `rag.py:_init_fts` | ✅ Onaylandı |
| Sliding window özetleme | `memory.py:332-359` | ✅ Onaylandı |
| tiktoken entegrasyonu | `memory.py:316-320` | ✅ Onaylandı |
| AnthropicClient (5 sağlayıcı tam desteği) | `llm_client.py:504-652` | ✅ Onaylandı |
| `max_output_chars=10000` | `code_manager.py:50` | ✅ Onaylandı |
| Docker sandbox güvenliği (web servisinde `.sock` yok) | `docker-compose.yml` | ✅ Onaylandı |

---

#### 18.7.6 Audit #8 Özet

| Kategori | Sayı | Detay |
|----------|------|-------|
| **Onaylanan çözüldü** | 17 | Audit #7 ve önceki tüm önemli maddeler doğrulandı |
| **Süregelen açık sorun** | 3 | 2 boş artifact dosyası + `ReviewerAgent` eksikliği |
| **Açık bulgu** | 1 | `.note` scratchpad dosyası depoda mevcut; kapanış iddiası revize edilmeli |
| **Rapor iç çelişkisi giderildi** | 1 | §18.6.5 "Eksik" → "Mevcut" düzeltmesi |
| **Satır sayısı güncellenen alan** | 3 | RFC-MultiAgent.md (+103), Dockerfile (+2), Python toplam (+277) |

---

### 18.8 Rapor Düzeltme Özeti — Audit #9 (2026-03-11)

Bu bölüm, dış gözden gelen kontrol listesi (arkadaş yorumu) ile depo gerçekliğinin çapraz teyidini içerir. Odak: ana modüller, manager katmanı, dokümantasyon, test artifact'leri ve RFC ile rapor tutarlılığı.

#### 18.8.1 Arkadaş Yorumu ile Uyumlu Olarak Yeniden Teyit Edilen Bulgular

- `config.py`: `ENABLE_MULTI_AGENT`, `AUTO_HANDLE_TIMEOUT`, kritik ayar doğrulamaları (`validate_critical_settings`) ve özet üretimi (`print_config_summary`) rapordaki anlatımla uyumlu.
- `main.py`: `run_wizard`, banner, interaktif seçim yardımcıları ve `--quick` akışı rapordaki CLI/Hızlı Başlatma anlatımıyla uyumlu.
- `agent/definitions.py` + `agent/tooling.py`: sistem prompt kuralları ile araç şemaları (`write_file`, `patch_file`, GitHub araçları dahil) rapordaki mimari özetle uyumlu.
- `agent/auto_handle.py`: `cfg.AUTO_HANDLE_TIMEOUT` kullanımı ve regex tabanlı yönlendirme deseni rapordaki otomatik komut işleme bölümünü doğruluyor.
- `agent/sidar_agent.py` + multi-agent dosyaları (`base_agent.py`, `core/supervisor.py`, `core/contracts.py`, `roles/coder_agent.py`, `roles/researcher_agent.py`): feature-flag tabanlı delegasyon akışı (Supervisor → uzman ajanlar) ve `TaskResult` sözleşmesi raporla uyumlu.
- Yönetici modülleri (`code_manager.py`, `security.py`, `todo_manager.py`, `github_manager.py`, `package_info.py`, `system_health.py`, `web_search.py`): arkadaş yorumundaki fonksiyon kümeleri ile rapordaki karşılıkları büyük ölçüde tutarlı.

#### 18.8.2 11 Mart 2026 Tarihli Yeni / Yeniden-Açık Notlar

| # | Tespit | Durum | Not |
|---|--------|-------|-----|
| 1 | `tests/test_config_runtime_coverage` (uzantısız) ve `tests/test_config_runtime_coverage.py` dosyaları 0 bayt | ✅ Çözüldü | Dosyalar depoda yok; CI boş dosya kontrolü aktif. |
| 2 | `memory_hub.py` ve `registry.py` modülleri için eksiklik iddiası | ✅ Çözüldü | Her iki modül de depoda mevcut ve Supervisor akışında kullanılıyor. |
| 3 | `web_ui/index.html` satır sayısı 467 (raporda 461/467 geçişi olmuştu) | ℹ Bilgi | Güncel ölçüm 467 satır; raporun satır-sayısı tablolarında tek değer korunmalı. |
| 4 | `SIDAR.md` ve `CLAUDE.md` kısa yönlendirme dokümanları; teknik detaylar asıl olarak `README.md` + `PROJE_RAPORU.md` içinde | ℹ Bilgi | Arkadaş yorumundaki “belge çapraz kontrolü” adımı için teyit edildi. |

#### 18.8.3 Öneriler (11 Mart 2026)

1. ✅ Boş test artifact dosyaları kaldırıldı ve CI'da `find tests -size 0` kontrolü aktif.
2. ✅ RFC'de “planlanan/uygulanmış” ayrımını netleştiren durum matrisi eklendi (`memory_hub`, `registry`, `ReviewerAgent`).
3. ✅ Satır sayısı metriklerini tek komutla üreten `scripts/audit_metrics.sh` betiği eklendi ve CI'da çalıştırılıyor.



---

### 18.9 Rapor Düzeltme Özeti — Audit #10 (2026-03-11)

Bu bölüm, “dosya dosya/satır satır son durum” talebine karşılık nihai çapraz doğrulama çıktısıdır. Önceki audit kayıtları tarihsel olarak korunur; bu bölüm **güncel tek-doğru durum** özetini verir.

#### 18.9.1 Güncel Ölçüm ve Varlık Doğrulaması

| Kontrol | Komut/Referans | Sonuç |
|---|---|---|
| Test satır toplamı | `wc -l tests/*.py` | ✅ **15.974** |
| `tests/` dosya adedi | `find tests -maxdepth 1 -type f | wc -l` | ✅ **68** |
| Boş test artifact dosyaları | `find tests -maxdepth 1 -type f -size 0` | ✅ Bulunamadı (çıktı boş) |
| RFC satır sayısı | `wc -l RFC-MultiAgent.md` | ✅ **303** |
| `.note` varlık kontrolü | `test -f .note && echo present` | ⚠ **present** |
| Planlanan fakat eksik modüller | `test -f agent/roles/reviewer_agent.py`, `agent/core/memory_hub.py`, `agent/core/registry.py` | ✅ Üç modül de depoda mevcut |

#### 18.9.2 Önceki Yorumlarla Nihai Uyum Durumu

- `ENABLE_MULTI_AGENT` maddesi için güncel durum **çözüldü**: `.env.example` içinde değişken mevcut; bu başlık artık açık borç değildir.
- Multi-agent tarafında `ReviewerAgent`, `memory_hub` ve `registry` modülleri depoda mevcuttur; açık borç ağırlığı artık entegrasyon derinliği ve operasyonel metriklerdedir.
- “Tüm dosyalarda +1 satır artış” iddiası güncel ölçümde doğrulanmamıştır; mevcut rapor satır sayıları Audit #8/Audit #9 ile uyumludur.

#### 18.9.3 Kapanış Aksiyonları (Öncelikli)

1. ✅ `tests/test_config_runtime_coverage` ve `tests/test_config_runtime_coverage.py` dosyaları depoda bulunmuyor; `find tests -type f -size 0` doğrulaması temiz.
2. ✅ RFC dokümanında “planlandı / implement edildi” matrisi eklendi (`ReviewerAgent`, `memory_hub`, `registry`).
3. ✅ Satır sayısı metrikleri `scripts/audit_metrics.sh` ile standardize edildi (CI adımı aktif).
4. ⚠ `.note` dosyası depoda mevcut; dokümantasyon tutarlılığı için rapor kapanış notları revize edildi.
---

### Session 2026-03-11 — Multi-Agent Geçiş Sertleştirme ve Reviewer QA Döngüsü

Bu oturumda mimari sadeleştirme ve kalite döngüsü için aşağıdaki iyileştirmeler uygulandı:

1. **Config seviyesinde deprecation uyarısı eklendi**
   - `ENABLE_MULTI_AGENT=false` durumda `Config()` oluşturulurken `DeprecationWarning` üretiliyor.
   - Log kaydı ile birlikte v3.0’da legacy tekli ajan akışının kaldırılacağı netleştirildi.

2. **Supervisor workflow güçlendirildi (Coder -> Reviewer -> Coder -> Reviewer)**
   - Varsayılan kod niyetinde ilk tur `coder` çıktısı `review_code|...` formatıyla `reviewer` ajanına gönderiliyor.
   - Reviewer çıktısında regresyon/hata sinyali tespit edilirse Supervisor ikinci bir coder düzeltme turu tetikliyor.
   - İkinci tur sonrası final reviewer özeti kullanıcıya sunuluyor.

3. **ReviewerAgent üretim entegrasyonu derinleştirildi**
   - `review_code|<context>` görevi eklendi.
   - Reviewer, merkezi konfigürasyondan gelen `REVIEWER_TEST_COMMAND` ile test koşturup PASS/FAIL kalite özeti üretiyor.
   - Doğal dilde gelen “incele/review/regresyon/test” niyetleri de `review_code` akışına yönlendiriliyor.

4. **Test kapsamı güncellendi**
   - `Config` deprecation uyarısı testi eklendi.
   - Supervisor’ın reviewer başarısızlığında coder’ı yeniden çağırdığı akış testi eklendi.
   - Reviewer `review_code` kalite raporu üretimi için test eklendi.

---

### Session 2026-03-11 — LLM Bütçe ve Maliyet Dashboard Geliştirmesi

Bu oturumda çoklu sağlayıcı maliyet görünürlüğü için metrik katmanı ve UI iyileştirmeleri yapıldı:

1. **LLM metrik toplayıcı genişletildi (`core/llm_metrics.py`)**
   - Olay bazında `cost_usd` alanı eklendi.
   - OpenAI/Anthropic bilinen modelleri için yaklaşık token fiyatlandırma tablosu tanımlandı.
   - Toplam bütçe (`LLM_BUDGET_DAILY_USD`, `LLM_BUDGET_TOTAL_USD`) ve sağlayıcı bazlı limitler (`OPENAI_BUDGET_*`, `ANTHROPIC_BUDGET_*`) snapshot çıktısına eklendi.

2. **Backend bütçe endpoint sözleşmesi güçlendirildi**
   - `GET /api/budget` ve `GET /metrics/llm` üzerinden dönen payload artık `cost_usd`, global budget özeti ve sağlayıcı budget kırılımı içeriyor.

3. **Web UI canlı bütçe şeridi güncellendi (`web_ui/app.js`)**
   - LLM şeridi `apiUrl('/api/budget')` çağrısıyla provider bazlı kullanım/limit verisini çekiyor.
   - OpenAI veya Anthropic aktif kullanımında `$kullanım / $limit` ve toplam maliyet bilgisi canlı gösteriliyor.

4. **Test kapsamı artırıldı**
   - `tests/test_llm_metrics_runtime.py` içine maliyet ve budget sözleşmesi doğrulamaları eklendi.
   - `tests/test_web_ui_runtime_improvements.py` içine bütçe endpoint entegrasyonu testi eklendi.

---

### Session 2026-03-11 — Legacy ReAct Akışının Emekliye Ayrılması

Bu oturumda mimari sadeleştirme kapsamında tekli ajan fallback yolu devreden çıkarılarak Supervisor-first mimariye geçiş tamamlandı:

1. **`SidarAgent.respond` tek akışa indirildi**
   - Girdi işleme artık doğrudan `SupervisorAgent` çağrısı ile yürütülüyor.
   - Legacy `auto_handle/direct-route/ReAct` fallback zinciri yanıt akışından kaldırıldı.

2. **`_try_multi_agent` davranışı zorunlu hale getirildi**
   - Feature flag kontrolü kaldırıldı.
   - Metot her zaman supervisor örneğini başlatıp görevi ona delege ediyor.

3. **`Config` tarafında bayrak sadeleştirmesi**
   - `ENABLE_MULTI_AGENT` artık çevresel değişkenle kapatılamıyor; sabit `True` olarak çalışıyor.
   - Geçiş dönemi deprecation uyarısı kaldırıldı (legacy yol artık aktif değil).

4. **Test güncellemeleri**
   - `tests/test_sidar_agent_runtime.py` içinde `_try_multi_agent` için daima supervisor kullanan senaryolar güncellendi.
   - `tests/test_config_runtime.py` içinde yapılandırmanın supervisor modunu zorunlu tuttuğunu doğrulayan test eklendi/güncellendi.

---

### Session 2026-03-11 — Multi-User Faz 1: Veritabanı İskeleti

Bu oturumda çoklu kullanıcı geçişi için kalıcı veri katmanının temel altyapısı eklendi:

1. **Yeni veritabanı modülü eklendi (`core/db.py`)**
   - `Database` sınıfı asenkron API ile (connect/init_schema/close) eklendi.
   - `DATABASE_URL` boşsa otomatik fallback: `sqlite+aiosqlite:///data/sidar.db`.
   - PostgreSQL URL verildiğinde `asyncpg` tabanlı pool açma desteği eklendi.

2. **Temel tablolar ve ilişkiler tanımlandı**
   - `users(id, username, role, created_at)`
   - `sessions(id, user_id, title, created_at, updated_at)`
   - `messages(id, session_id, role, content, tokens_used, created_at)`
   - `sessions.user_id` ve `messages.session_id` için indeksler oluşturuldu.

3. **Konfigürasyon alanları genişletildi (`config.py`)**
   - `DATABASE_URL`
   - `DB_POOL_SIZE`

4. **Core paket dışa aktarımları güncellendi (`core/__init__.py`)**
   - `Database` ve `DatabaseManager` alias'ı eklendi.

5. **İlk faz testleri eklendi (`tests/test_db_runtime.py`)**
   - SQLite fallback bağlantısı + şema kurulum + user/session/message CRUD akışı doğrulandı.
   - `DATABASE_URL` boşken proje içi varsayılan `data/sidar.db` yolunun seçildiği doğrulandı.

---

### Session 2026-03-11 — Multi-User Faz 2: Memory Katmanının DB'ye Taşınması

Bu oturumda konuşma belleği JSON dosya tabanından veritabanı tabanına taşındı ve web katmanı uyumlandı:

1. **`core/memory.py` refactor (DB-backed)**
   - `ConversationMemory` artık kalıcılık için `core.db.Database` kullanıyor.
   - Yeni async API'ler eklendi: `acreate_session`, `aload_session`, `adelete_session`, `aget_all_sessions`, `aadd`, `aget_history`, `aupdate_title`.
   - Geriye dönük uyumluluk için sync metodlar korunarak async çekirdeğe yönlendirildi.

2. **Varsayılan kullanıcı entegrasyonu**
   - Başlangıçta `default_admin` kullanıcısı DB'de otomatik ensure ediliyor.
   - Yeni oturumlar varsayılan olarak bu `user_id` ile oluşturuluyor.

3. **`core/db.py` genişletmesi**
   - Memory refactor için ek metotlar eklendi: `ensure_user`, `list_sessions`, `load_session`, `update_session_title`, `delete_session`.

4. **Web sunucu uyumu (`web_server.py`)**
   - Session ve metrics rotaları async bellek API'lerini kullanacak şekilde güncellendi.
   - Geriye dönük test/stub uyumu için async metod yoksa sync fallback mantığı eklendi.

5. **Test kapsamı**
   - `tests/test_memory_db_runtime.py` eklendi (default user + async session/history akışları).
   - `tests/test_core_memory.py`, `tests/test_web_server_runtime.py`, `tests/test_db_runtime.py` ile yeni davranış doğrulandı.

---



### Session 2026-03-11 — Multi-User Faz 3: DB Tabanlı Authentication ve Session İzolasyonu

Bu oturumda çoklu kullanıcı geçişinin Faz 3 altyapısı için backend tarafta kimlik doğrulama katmanı etkinleştirildi:

1. **DB kimlik doğrulama modeli (`core/db.py`)**
   - `users` tablosuna `password_hash` alanı eklendi.
   - Yeni tablolar: `auth_tokens`, `user_quotas`, `provider_usage_daily`.
   - Yeni API metotları: `register_user`, `authenticate_user`, `create_auth_token`, `get_user_by_token`.

2. **Web auth middleware güncellemesi (`web_server.py`)**
   - API_KEY tabanlı Basic Auth yerine Bearer token doğrulaması aktif edildi.
   - Açık endpointler: `/auth/register`, `/auth/login`, `/health`, `/docs` vb.
   - Kimliği doğrulanan kullanıcı `request.state.user` içinde taşınıyor.

3. **Session sahiplik izolasyonu (`web_server.py`)**
   - `/sessions`, `/sessions/{id}`, `/sessions/new`, `/sessions/{id}` (DELETE) endpointleri artık `user.id` ile DB sorgusu yapıyor.
   - Böylece kullanıcılar yalnızca kendi session kayıtlarını okuyup/silebiliyor.

4. **Geçiş notu (teknik borç / açık iş)**
   - `ConversationMemory` başlangıçta hâlâ `default_admin` fallback davranışını barındırıyor.
   - Bu fallback yalnızca backward-compatibility için geçiş katmanı olarak tutulmalı; tam Faz 3 kapanışı için memory katmanı request-context kullanıcı kimliğine zorunlu bağlanmalı.

### Session 2026-03-11 — Multi-User Faz 3 Kapanış: Web UI Auth Entegrasyonu

Bu oturumda Faz 3 kapsamı backend + frontend uçtan uca tamamlandı:

1. **Web UI kimlik doğrulama katmanı (`web_ui/`)**
   - `index.html` içine login/register modalı (`auth-overlay`) ve kullanıcı profil/çıkış alanı eklendi.
   - `style.css` içinde auth modalı ve profil bileşenleri için dark/light tema uyumlu stiller tanımlandı.
   - `app.js` tarafında token saklama (`localStorage`), auth bootstrap ve logout akışı tamamlandı.

2. **Token taşıma standardizasyonu**
   - `fetchAPI(url, options)` wrapper'ı ile tüm UI isteklerine otomatik `Authorization: Bearer <token>` başlığı ekleniyor.
   - `chat.js`, `sidebar.js` ve `rag.js` içindeki endpoint çağrıları wrapper üzerinden çalışacak şekilde güncellendi.

3. **Faz 3 kapsam değerlendirmesi**
   - Kimlik doğrulama, oturum sahiplik izolasyonu ve Web UI entegrasyonu birlikte çalışır durumda.
   - Faz 3 hedefi rapor seviyesinde "tamamlandı" olarak kabul edildi.

---

### Session 2026-03-11 — P2P Multi-Agent Delegasyon ve Dinamik Reviewer QA

Bu oturumda ajanlar arası doğrudan delegasyon ve QA derinleştirmesi devreye alındı:

1. **P2P kontrat modeli (`agent/core/contracts.py`)**
   - `P2PMessage`, `DelegationRequest`, `DelegationResult` veri modelleri eklendi.
   - `TaskResult.summary` alanı delegasyon mesajlarını taşıyacak şekilde genişletildi.

2. **Ajan tabanı ve router köprüsü (`agent/base_agent.py`, `agent/core/supervisor.py`)**
   - BaseAgent'e `delegate_to(...)` yardımcı metodu eklendi.
   - Supervisor içinde `_route_p2p(...)` ile delegasyon zincirini hedef ajana yönlendiren köprü mekanizması kuruldu.

3. **Reviewer QA derinleştirmesi (`agent/roles/reviewer_agent.py`)**
   - Reviewer, coder bağlamına göre geçici dinamik test dosyası üretiyor ve çalıştırıyor.
   - Dinamik test + regresyon komutu sonuçlarından `APPROVE/REJECT` kararı çıkarıp coder'a P2P geri bildirim iletiyor.

4. **Coder geri bildirim tüketimi (`agent/roles/coder_agent.py`)**
   - `qa_feedback|...` mesajları parse edilip rework/approve durumları kodlayıcı tarafından işleniyor.

### Session 2026-03-11 — Faz 5: Zero-Trust Sandbox ve Kaynak Kısıtları

Bu oturumda kod çalıştırma katmanı kurumsal/multi-tenant güvenlik hedefleri için sertleştirildi:

1. **Yeni Docker güvenlik konfigürasyonları (`config.py`)**
   - `DOCKER_RUNTIME` (örn. `runsc` ile gVisor hazırlığı)
   - `DOCKER_MEM_LIMIT` (varsayılan: `256m`)
   - `DOCKER_NETWORK_DISABLED` (varsayılan: `True`)
   - `DOCKER_NANO_CPUS` (varsayılan: `1_000_000_000` ≈ 1 vCPU)

2. **Sandbox çalıştırma parametreleri (`managers/code_manager.py`)**
   - `containers.run(...)` çağrısında konfigürasyon tabanlı limitler aktif edildi:
     - `mem_limit=self.docker_mem_limit`
     - `nano_cpus=self.docker_nano_cpus`
     - `network_mode="none"` (ağ kapalıysa)
     - `runtime=self.docker_runtime` (runtime belirtilmişse)
   - Konteyner `StatusCode` bilgisi okunarak non-zero çıkışlar hata olarak işaretleniyor.

3. **Doğrulama testleri (`tests/test_code_manager_runtime.py`)**
   - Network disabled senaryosunda dış HTTP (`requests.get('https://google.com')`) çağrısının başarısız olduğu test ile doğrulandı.
   - Docker run kwargs içinde `network_mode`, `mem_limit` ve `nano_cpus` değerleri assertion ile kontrol edildi.

4. **Kapsam etkisi**
   - Bu adım, Firecracker/gVisor gibi daha ileri izolasyon katmanlarına geçiş için temel güvenlik sözleşmesini oluşturur.
   - SaaS/kurumsal dağıtımlarda varsayılan fail-closed davranışına yaklaşım güçlendirildi.

---

### Session 2026-03-11 — Observability / Canlı Ajan Durum Akışı

Bu oturumda ajanın arka plan adımlarını kullanıcıya gerçek zamanlı yansıtmak için event-stream entegrasyonu yapıldı:

1. **Agent event bus eklendi (`agent/core/event_stream.py`)**
   - Process-içi `AgentEventBus` ile subscribe/publish mekanizması kuruldu.
   - `SupervisorAgent`, `CoderAgent`, `ReviewerAgent` kritik adımlarda durum olayları yayınlamaya başladı.

2. **WebSocket canlı durum iletimi (`web_server.py`)**
   - `/ws/chat` içinde her mesaj için event bus aboneliği açılıyor.
   - Agent çalışırken gelen olaylar UI'ye `{ "status": "<source>: <message>" }` formatında stream ediliyor.
   - İstek tamamlandığında abonelik temizleniyor ve status-pump görevi güvenli kapatılıyor.

3. **Frontend durum göstergesi güncellemesi (`web_ui/chat.js`)**
   - WS mesajlarındaki `status` alanı `apSetThought(...)` ile "Düşünüyor/Ajan Durumu" alanında canlı gösteriliyor.
   - Nihai yanıt geldiğinde mevcut akış davranışı (`done`) korunuyor.

4. **Test kapsamı**
   - `tests/test_event_stream_runtime.py` eklendi (event bus publish/subscribe roundtrip).
   - `tests/test_web_ui_runtime_improvements.py` içine status stream handling kontrolü eklendi.
   - `tests/test_web_server_runtime.py` ile websocket akış uyumluluğu regresyonu doğrulandı.

---

### Session 2026-03-11 — Quality Gate: Coverage %95 Zorunluluğu

Bu oturumda test kapsamı kalite kapısı kurumsal eşiklere yükseltildi:

1. **Coverage policy güncellendi (`.coveragerc`)**
   - `[report]` bölümüne `fail_under = 95` eklendi.
   - `show_missing` ve `skip_covered` ile rapor okunabilirliği artırıldı.

2. **Test komutları kalite kapısına bağlandı (`run_tests.sh`)**
   - Global kapsam eşiği ve kritik modül kapsam eşiği `COVERAGE_FAIL_UNDER` (varsayılan: 95) ile zorunlu hale getirildi.
   - Böylece coverage %95 altına düşerse test süreci fail olur.

3. **CI/CD kalite kapısı güçlendirildi (`.github/workflows/ci.yml`)**
   - Test paketinden sonra bağımsız bir adım eklendi:
     `python -m pytest -q --cov=. --cov-report=term-missing --cov-fail-under=95`
   - Bu adım PR/push pipeline'ında coverage barajını bloklayıcı hale getirir.

4. **Politika testleri güncellendi (`tests/test_coverage_policy.py`)**
   - Script/CI/coveragerc üzerinde %95 kalite kapısı doğrulayan testler eklendi/güncellendi.
---

### Session 2026-03-11 — Telemetri, Maliyet Yönetimi ve Dashboard Altyapısı

**Durum: Tamamlandı ✅**

Bu oturumda kullanıcı bazlı maliyet/telemetri izleme ve dashboard altyapısı üretim kullanımına uygun şekilde tamamlandı:

1. **LLM telemetri ve kullanıcı kapsamı**
   - LLM çağrıları kullanıcı kimliği ile etiketlenerek provider + user kırılımında izlenebilir hale getirildi.
   - Runtime metrikleri Prometheus uyumlu metin formatında dışa açıldı.

2. **Maliyet/kullanımın kalıcılaştırılması**
   - Günlük provider kullanım değerleri (token/istek) DB tarafına yazılır hale getirildi.
   - Kullanıcı kota durumunun API üzerinden okunabilmesi için gerekli servis katmanı tamamlandı.

3. **Monitoring stack**
   - `docker-compose.yml` içine Prometheus (`:9090`) ve Grafana (`:3000`) servisleri eklendi.
   - Prometheus scrape konfigürasyonu `docker/prometheus/prometheus.yml` ile projeye dahil edildi.

4. **Doğrulama**
   - İlgili backend metrik/test paketleri çalıştırılarak regresyon kontrolü yapıldı.
   - Sonuç: telemetri + monitoring altyapısı v3.0 hedefleri için hazır ve çalışır durumda.

---

### Session 2026-03-11 — Frontend (Web UI) Admin Paneli ve Kurumsal Sürüme Geçiş (v3.0 Tamamlandı)

**Durum: Tamamlandı ✅**

Bu oturumla birlikte SİDAR projesinin v3.0 kurumsal/SaaS dönüşüm hedefi resmi olarak kapatıldı. Frontend (Web UI) üzerinde admin paneli tamamlanarak operasyonel görünürlük ve yönetilebilirlik hedefleri nihai hale getirildi.

1. **Web UI Admin Paneli tamamlandı**
   - Admin kullanıcılar için ayrı panel görünümü ve gezinim akışı devreye alındı.
   - Panelde toplam kullanıcı, toplam istek ve toplam token kullanımı gibi özet metrik kartları sağlandı.
   - Kullanıcı listesi rol/kota bilgileriyle birlikte tablo formatında görüntülenebilir hale getirildi.

2. **Backend admin endpoint ve yetkilendirme entegrasyonu**
   - Admin panelinin veri kaynağı olan güvenli admin istatistik endpoint’i ile UI arasında uçtan uca akış doğrulandı.
   - Role-based erişim kontrolü ile yalnızca yetkili kullanıcıların yönetim ekranına erişmesi garanti altına alındı.

3. **Kurumsal görünürlük ve maliyet takibi kapanışı**
   - Prometheus/Grafana altyapısı ve uygulama içi admin panel birlikte çalışacak şekilde nihai duruma getirildi.
   - Kullanıcı/kota/kullanım görünürlüğü hem teknik izleme katmanında hem ürün arayüzünde tamamlandı.

4. **Kilometre taşı kapanışı**
   - Multi-user mimari, P2P çoklu ajan akışı, zero-trust sandbox, telemetri, maliyet yönetimi ve admin dashboard başlıklarının tümü tamamlandı.
   - Proje bu aşamada üretim hazırlığı (production-readiness) açısından v3.0 hedeflerini karşılar durumdadır.

---

### 18.10 Audit #11 (Session 2026-03-11) — Güvenlik ve Kararlılık Kapanışı

**Durum: Tamamlandı ✅**

Bu oturumda v3.0 geçişinden kalan kritik güvenlik/kararlılık teknik borçları kapatıldı ve fail-closed prensibi çekirdek katmanlara uygulandı.

1. **ConversationMemory fail-closed sertleştirmesi**
   - `default_admin` fallback tamamen kaldırıldı.
   - Bellek katmanında doğrulanmış kullanıcı bağlamı yoksa işlem akışı `MemoryAuthError` ile reddedilecek şekilde fail-closed hale getirildi.
   - Böylece anonim/bağlamsız isteklerin oturum oluşturması veya bellek yazması engellendi.

2. **WebSocket zorunlu Auth Handshake**
   - `/ws/chat` akışında ilk paket zorunlu auth mesajı olacak şekilde sözleşme sıkılaştırıldı.
   - Geçersiz/anonim websocket bağlantıları policy-violation (1008) ile anında kapatılacak şekilde güvenlik katmanı sertleştirildi.
   - Frontend tarafında socket açılışında token tabanlı handshake gönderimi zorunlu hale getirildi.

3. **Supervisor QA döngüsüne circuit-breaker**
   - Coder ↔ Reviewer geri besleme zincirine `MAX_QA_RETRIES=3` sınırı eklendi.
   - Bu sınır ile sonsuz/uzayan QA döngülerinin LLM bütçesini tüketme riski kapatıldı.
   - Retry limiti aşıldığında süreç kontrollü biçimde durdurulup açık durum mesajı üretilir.

4. **Doğrulama özeti**
   - İlgili runtime testleri hedefli şekilde çalıştırıldı ve regresyon gözlenmedi.
   - Sonuç: güvenlik sertleştirmeleri ve kararlılık devre kesicisi üretim hazırlığı hedefleriyle uyumludur.
---

### Session 2026-03-11 — Üretim Geçiş Araçları ve Alembic Sertleştirmesi

**Durum: Tamamlandı ✅**

Bu oturumda veritabanı yönetim altyapısı üretim standartlarına (PostgreSQL) taşınacak seviyede sertleştirildi:

1. **Gelişmiş Veri Taşıma Aracı (`scripts/migrate_sqlite_to_pg.py`)**
   - SQLite verilerini PostgreSQL’e deterministik bir sırayla taşıyan asenkron script eklendi.
   - `--dry-run` desteği ile taşıma öncesi veri tutarlılığı kontrolü sağlandı.
2. **Alembic Yapılandırma İyileştirmesi**
   - `migrations/env.py` içinde dinamik DATABASE_URL çözümleme mantığı güçlendirildi.
   - Komut satırı argümanı (`-x database_url=...`) en yüksek önceliğe alındı.
3. **Migration Entegrasyon Testleri**
   - `tests/test_migration_assets.py` güncellendi.
   - Test sırasında geçici bir veritabanı üzerinde gerçek `alembic upgrade head` çalıştırılarak şemanın hatasız oluştuğu doğrulandı.
4. **Dökümantasyon Senkronizasyonu**
   - README versiyonu v3.0.0 ile eşitlendi.
   - `production-cutover-playbook.md` somut script komutlarıyla güncellendi.

---

### Session 2026-03-11 — Production Sertifikasyon Kalan Maddeler (QA + Sandbox + Migration Disiplini)

**Durum: Tamamlandı ✅**

Bu oturumda v3.0 kapanışı sonrası kalan üç stratejik açık için somut iyileştirmeler uygulandı:

1. **ReviewerAgent kalite kapıları derinleştirildi**
   - Reviewer, `review_code` akışında artık yalnızca tek komut yerine hedefe yönelik test + global regresyon komutlarını birlikte planlayıp çalıştırır.
   - Diff/metin içinden değişen dosya yolları çıkarılarak `tests/...` hedefleri için odaklı `pytest` komutu üretimi eklendi.
2. **Gelişmiş Sandbox runtime doğrulama testleri eklendi**
   - `DOCKER_MICROVM_MODE=gvisor` için `runsc`, `DOCKER_MICROVM_MODE=kata` için `kata-runtime` çözümlemesi otomatik testlerle doğrulandı.
   - İzinli runtime listesi dışındaki değerlerin fail-safe şekilde reddedildiği test altına alındı.
3. **Alembic migration sürekliliği operasyon disiplini netleştirildi**
   - Production cutover runbook'una “manuel SQL yerine zorunlu Alembic zinciri” ilkesi ve revizyon/rollback akışı eklendi.
   - `schema_versions` (uygulama telemetrisi) ile `alembic_version` (migration kaynağı) ayrımı dokümante edildi.
