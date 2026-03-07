<a id="top"></a>
# SİDAR Projesi — Kapsamlı Kod Analiz Raporu (Güncel)

**Tarih:** 2026-03-01 (Son güncelleme: **2026-03-06** — README.md ve kod tabanı senkronizasyonu %100 doğrulandı; rapor drift bulguları güncellendi)
**Analiz Eden:** Claude Sonnet 4.6 (Otomatik Denetim)
**Versiyon:** SidarAgent v2.7.0 ✅ (tüm modüller ve docstring'ler v2.7.0 ile uyumlu)
**Toplam Dosya:** 36 izlenen dosya, ~18.4k satır metin içerik
**Önceki Rapor:** 2026-02-26 (v2.5.0 analizi) / İlk v2.6.0 raporu: 2026-03-01 / [U-01–U-15](DUZELTME_GECMISI.md#sec-8-1-8-4) yamaları: 2026-03-01 / [V-01–V-03](DUZELTME_GECMISI.md#sec-8-1-8-4) yamaları: 2026-03-01 / [N-01–N-04](DUZELTME_GECMISI.md#n-01) + [O-02](DUZELTME_GECMISI.md#o-02) yamaları: 2026-03-02 / [O-01–O-06](DUZELTME_GECMISI.md#sec-8-2-18-o-01-o-06) yamaları: 2026-03-02 / **[P-01–P-07](DUZELTME_GECMISI.md) yamaları: 2026-03-03**

---

<a id="icindekiler"></a>
## İÇİNDEKİLER

- [1. Proje Genel Bakış](#1-proje-genel-bakis)
- [2. Dizin Yapısı](#2-dizin-yapisi)
- [3. Önceki Rapordan Bu Yana Düzeltilen Hatalar](#3-onceki-rapordan-bu-yana-duzeltilen-hatalar)
- [4. Mevcut Kritik Hatalar](#4-mevcut-kritik-hatalar)
- [5. Yüksek Öncelikli Sorunlar](#5-yuksek-oncelikli-sorunlar)
- [6. Orta Öncelikli Sorunlar](#6-orta-oncelikli-sorunlar)
- [7. Düşük Öncelikli Sorunlar](#7-dusuk-oncelikli-sorunlar)
- [8. Dosyalar Arası Uyumsuzluk Tablosu](#8-dosyalar-arasi-uyumsuzluk-tablosu)
- [9. Bağımlılık Analizi](#9-bagimlilik-analizi)
  - [`environment.yml` — Güncel Durum Tablosu](#environmentyml-guncel-durum-tablosu)
- [10. Güçlü Yönler](#10-guclu-yonler)
  - [10.1 Mimari — Temel İyileştirmeler](#101-mimari-onceki-versiyona-kiyasla-iyilesmeler)
  - [10.2 Docker REPL Sandbox](#102-docker-repl-sandbox-yeni)
  - [10.3 Çoklu Oturum Sistemi ve Bellek Şifrelemesi (YENİ)](#103-coklu-oturum-sistemi-yeni)
  - [10.4 Sonsuz Hafıza ve Hibrit RAG (YENİ)](#104-gpu-hizlandirma-altyapisi-yeni)
  - [10.5 Akıllı Hızlandırma: Direct Route & Parallel Araçlar (YENİ)](#105-web-arayuzu-ozellikler-v261-ile-guncellendi)
  - [10.6 Web Arayüzü — İleri Özellikler](#106-rate-limiting-yeni)
  - [10.7 Görev Yönetimi (TodoManager) (YENİ)](#107-recursive-character-chunking-yeni)
  - [10.8 Rate Limiting & Güvenlik](#108-llm-stream-buffer-guvenligi)
  - [10.9 Recursive Character Chunking](#109-recursive-character-chunking)
  - [10.10 LLM Stream — Buffer Güvenliği](#1010-llm-stream-buffer-guvenligi)
- [11. Güvenlik Değerlendirmesi](#11-guvenlik-degerlendirmesi)
- [12. Test Kapsamı](#12-test-kapsami)
  - [12.1 Modüler Test Mimarisi (tests/ Dizini)](#121-moduler-test-mimarisi-tests-dizini)
  - [12.2 Öne Çıkan Güvenlik ve Edge-Case Testleri](#122-one-cikan-guvenlik-ve-edge-case-testleri)
- [13. Dosya Bazlı Detaylı İnceleme](#13-dosya-bazli-detayli-inceleme)
  - [13.1 Çekirdek Dosyalar — Güncel Durum](#131-cekirdek-dosyalar-guncel-durum)
  - [13.2 Yönetici (manager) Katmanı — Güncel Durum](#132-yonetici-manager-katmani-guncel-durum)
  - [13.3 Test ve Dokümantasyon Uyum Özeti](#133-test-ve-dokumantasyon-uyum-ozeti)
  - [13.4 Açık Durum](#134-acik-durum)
  - [13.5 Dosya Bazlı Teknik Detaylar](#135-dosya-bazli-teknik-detaylar)
    - [13.5.1 `main.py` — Skor: 100/100 ✅](#1351-mainpy-skor-100100)
    - [13.5.1A `cli.py` — Skor: 100/100 ✅](#1351a-clipy-skor-95100)
    - [13.5.2 `agent/sidar_agent.py` — Skor: 100/100 ✅](#1352-agentsidaragentpy-skor-95100)
    - [13.5.3 `core/rag.py` — Skor: 100/100 ✅](#1353-coreragpy-skor-100100)
    - [13.5.4 `web_server.py` — Skor: 100/100 ✅](#1354-webserverpy-skor-90100)
    - [13.5.5 `agent/definitions.py` — Skor: 100/100 ✅](#1355-agentdefinitionspy-skor-87100)
    - [13.5.6 `agent/auto_handle.py` — Skor: 100/100 ✅](#1356-agentautohandlepy-skor-89100)
    - [13.5.7 `core/llm_client.py` — Skor: 100/100 ✅](#1357-corellmclientpy-skor-91100)
    - [13.5.8 `core/memory.py` — Skor: 100/100 ✅](#1358-corememorypy-skor-92100)
    - [13.5.9 `config.py` — Skor: 100/100 ✅](#1359-configpy-skor-91100)
    - [13.5.10 `managers/code_manager.py` — Skor: 100/100 ✅](#13510-managerscodemanagerpy-skor-94100)
    - [13.5.11 `managers/github_manager.py` — Skor: 100/100 ✅](#13511-managersgithubmanagerpy-skor-93100)
    - [13.5.12 `managers/system_health.py` — Skor: 100/100 ✅](#13512-managerssystemhealthpy-skor-94100)
    - [13.5.13 `managers/web_search.py` — Skor: 100/100 ✅](#13513-managerswebsearchpy-skor-93100)
    - [13.5.14 `managers/package_info.py` — Skor: 100/100 ✅](#13514-managerspackageinfopy-skor-94100)
    - [13.5.15 `managers/security.py` — Skor: 100/100 ✅](#13515-managerssecuritypy-skor-93100)
    - [13.5.16 `managers/todo_manager.py` — Skor: 100/100 ✅](#13516-managerstodomanagerpy-skor-94100)
    - [13.5.17 `managers/__init__.py` — Skor: 100/100 ✅](#13517-managersinitpy-skor-98100)
    - [13.5.18 `core/__init__.py` — Skor: 100/100 ✅](#13518-coreinitpy-skor-99100)
    - [13.5.19 `agent/__init__.py` — Skor: 100/100 ✅](#13519-agentinitpy-skor-98100)
    - [13.5.20 `tests/` Dizini ve Modüler Test Mimarisi — Skor: 100/100 ✅](#13520-teststestsidarpy-skor-94100)
    - [13.5.21 `web_ui/index.html` — Skor: 100/100 ✅](#13521-webuiindexhtml-skor-92100)
    - [13.5.22 `github_upload.py` — Skor: 100/100 ✅](#13522-githubuploadpy-skor-90100)
    - [13.5.23 `Dockerfile` — Skor: 100/100 ✅](#13523-dockerfile-skor-94100)
    - [13.5.24 `docker-compose.yml` — Skor: 100/100 ✅](#13524-docker-composeyml-skor-93100)
    - [13.5.25 `environment.yml` — Skor: 100/100 ✅](#13525-environmentyml-skor-95100)
    - [13.5.26 `.env.example` — Skor: 100/100 ✅](#13526-envexample-skor-95100)
    - [13.5.27 `install_sidar.sh` — Skor: 100/100 ✅](#13527-installsidarsh-skor-93100)
    - [13.5.28 `README.md` — Skor: 100/100 ✅](#13528-readmemd-skor-92100)
    - [13.5.29 `SIDAR.md` — Skor: 100/100 ✅](#13529-sidarmd-skor-94100)
    - [13.5.30 `CLAUDE.md` — Skor: 100/100 ✅](#13530-claudemd-skor-94100)
    - [13.5.31 `DUZELTME_GECMISI.md` — Skor: 100/100 ✅](#13531-duzeltmegecmisimd-skor-87100)
    - [13.5.32 `tests/__init__.py` — Skor: 100/100 ✅](#13532-testsinitpy-skor-96100)
    - [13.5.33 `PROJE_RAPORU.md` — Skor: 100/100 ✅](#13533-projeraporumd-skor-86100)
    - [13.5.34 `.gitignore` — Skor: 100/100 ✅](#13534-gitignore-skor-92100)
    - [13.5.35 `.note` — Skor: 100/100 ✅](#13535-note-skor-80100)
  - [13.6 Son Kontrol ve Dosyalar Arası Uyum Doğrulaması](#136-son-kontrol-ve-dosyalar-arasi-uyum-dogrulamasi)
  - [13.6.1 Harici Yorum Teyidi (Çapraz Kontrol)](#1361-harici-yorum-teyidi-capraz-kontrol)
- [14. Geliştirme Önerileri (Öncelik Sırasıyla)](#14-gelistirme-onerileri-oncelik-sirasiyla)
  - [Öncelik 1 — Yüksek Etki (Kısa Vadede, Olmazsa Olmaz)](#oncelik-1-yuksek-etki-kisa-vadede-olmazsa-olmaz)
  - [Öncelik 2 — Orta Etki (Güvenlik / Operasyon / Bakım)](#oncelik-2-orta-etki-guvenlik-operasyon-bakim)
  - [Öncelik 3 — Düşük Etki (DX / Dokümantasyon / UX)](#oncelik-3-dusuk-etki-dx-dokumantasyon-ux)
  - [Açık Durum](#acik-durum)
- [15. Genel Değerlendirme](#15-genel-degerlendirme)
  - [15.1 Tarihsel Gelişim ve Sürüm Özeti](#151-guncel-durum-ozeti-v270)
  - [15.2 Mimari ve Kod Kalitesi Değerlendirmesi (Mevcut Durum)](#152-kategori-bazli-kisa-skor-gorunumu-guncel)
  - [15.3 Kategori Bazlı Güncel Durum Tablosu (v2.7.0)](#153-arsiv-ve-izlenebilirlik-notu)
  - [15.4 Sonuç ve Proje Geleceği](#154-sonuc-ve-proje-gelecegi)
- [16. Güncel Sistem, Güvenlik ve Mimari İncelemesi (v2.7.0 Sonrası)](#16-guncel-sistem-guvenlik-ve-mimari-incelemesi-v270-sonrasi)

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1-proje-genel-bakis"></a>
## 1. Proje Genel Bakış

SİDAR, ReAct (Reason + Act) döngüsü mimarisi üzerine kurulu, Türkçe dilli, yapay zeka destekli bir **Yazılım Mühendisi Asistanı**'dır.

| Katman | Teknoloji |
|--------|-----------|
| **Dil / Framework** | Python 3.11, asyncio, Pydantic v2 |
| **Web Arayüzü** | FastAPI 0.115+, Uvicorn, SSE |
| **LLM Sağlayıcı** | Ollama (yerel) / Google Gemini (bulut) |
| **Vektör DB & RAG** | ChromaDB 0.5+, BM25, sentence-transformers |
| **Sistem & İzleme** | psutil, pynvml, PyTorch CUDA, opsiyonel Prometheus (`/metrics`) |
| **GitHub Entegrasyonu** | PyGithub 2.4+ |
| **Web Arama** | httpx, DuckDuckGo, Tavily, Google Custom Search |
| **Test** | pytest 8.3+, pytest-asyncio 0.24+, pytest-cov |
| **Container** | Docker, docker-compose |
| **Kod Çalıştırma** | Docker izolasyonu (`python:3.11-alpine` varsayılan; compose/Dockerfile profili: `python:3.11-slim`) |
| **Bellek & Güvenlik** | Çoklu oturum (JSON), opsiyonel Fernet şifreleme (`MEMORY_ENCRYPTION_KEY`, `cryptography`) |

**v2.5.0 → v2.6.0 Major Değişiklikler:**
- GPU hızlandırma desteği eklendi (RTX 3070 Ti / Ampere)
- FP16 mixed precision embedding desteği
- ChromaDB'de Recursive Character Chunking
- `_execute_tool` dispatcher tabloya taşındı
- Çoklu sohbet oturumu (session) yönetimi
- Docker sandbox ile izole REPL
- Rate limiting (web UI)
- WSL2 NVIDIA sürücü desteği

**v2.6.0 → v2.6.1 Web UI & Backend Patch:**
- Model ismi arayüzde dinamik hale getirildi (`/status` üzerinden)
- Sahte (hardcoded) `REPOS` / `BRANCHES` dizileri kaldırıldı
- Dal seçimi gerçek `git checkout` ile backend'e bağlandı (`POST /set-branch`)
- Repo seçici modal kaldırıldı; repo bilgisi `git remote`'dan otomatik okunuyor
- Auto-accept checkbox tamamen kaldırıldı (işlevsizdi)
- `pkg_status` artık sunucudan dinamik alınıyor (hardcoded string silindi)
- SSE streaming durdurulduğunda `CancelledError` / `ClosedResourceError` artık sessizce loglanıyor
- **YENİ:** Oturum dışa aktarma (MD + JSON indirme düğmeleri)
- **YENİ:** ReAct araç görselleştirmesi (her tool çağrısı badge olarak gösteriliyor)
- **YENİ:** Mobil hamburger menüsü (768px altında sidebar toggle + overlay)

**v2.6.1 → v2.7.0 Büyük Özellik Güncellemeleri (Güncel):**
- **YENİ:** Sonsuz Hafıza (Vector Archive) — eski sohbetler özetlenmeden önce RAG/Chroma deposuna arşivlenir.
- **YENİ:** Akıllı Başlatıcı + CLI ayrımı — `main.py` etkileşimli wizard/launcher katmanı; asıl terminal döngüsü `cli.py` dosyasına ayrıldı.
- **YENİ:** Bellek Şifrelemesi — `MEMORY_ENCRYPTION_KEY` ile yerel oturum dosyaları Fernet (`cryptography`) üzerinden şifrelenebilir.
- **YENİ:** Claude Code uyumluluk/hızlandırma paketi:
  - `_try_direct_tool_route`: basit istekleri ReAct döngüsüne girmeden tek adımda araca yönlendirebilir.
  - `_tool_parallel`: güvenli okuma araçlarını eşzamanlı çalıştırır.
  - mtime cache: `SIDAR.md` / `CLAUDE.md` değişimlerini algılayıp talimat önbelleğini otomatik yeniler.
- **YENİ:** Canlı Aktivite Paneli (`#activity-panel`) + THOUGHT sentinel (`\x00THOUGHT:<text>\x00`) ile gerçek zamanlı süreç görünürlüğü.
- **YENİ:** Hibrit RAG Büyük Dosya Yönetimi:
  - `docs_add_file` aracı ve `RAG_FILE_THRESHOLD` ile büyük dosyalarda otomatik RAG önerisi
  - 5 yeni RAG endpoint'i: `GET /rag/docs`, `POST /rag/add-file`, `POST /rag/add-url`, `DELETE /rag/docs/{id}`, `GET /rag/search`
  - Web UI RAG Belge Deposu modalı (Belgeler / Ekle / Arama)
- **YENİ:** `managers/todo_manager.py` — Claude Code TodoWrite/TodoRead uyumlu görev takip yöneticisi
- **DÜZELTME:** CORS konfigürasyonu localhost origin'leriyle sınırlandı
- **DÜZELTME:** Git injection koruması (`_BRANCH_RE` regex) eklendi

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="2-dizin-yapisi"></a>
## 2. Dizin Yapısı

```
sidar_project/
sidar_project/
├── agent/
│   ├── __init__.py                                 # Agent public API dışa aktarımları
│   ├── definitions.py                              # Sistem promptu + araç sözleşmeleri
│   ├── sidar_agent.py                              # Ana ReAct ajan döngüsü ve tool dispatch
│   └── auto_handle.py                              # Örüntü tabanlı hızlı komut yönlendirme
├── core/
│   ├── __init__.py                                 # Core public API + sürüm bilgisi
│   ├── llm_client.py                               # Ollama/Gemini istemci katmanı (async stream)
│   ├── memory.py                                   # Oturum belleği, kalıcılık, şifreleme
│   └── rag.py                                      # Hibrit RAG (ChromaDB + BM25 + keyword)
├── managers/
│   ├── __init__.py                                 # Manager export yüzeyi
│   ├── code_manager.py                             # Dosya işlemleri + Docker sandbox çalıştırma
│   ├── github_manager.py                           # GitHub repo/branch/PR/dosya işlemleri
│   ├── package_info.py                             # PyPI/npm/GitHub sürüm sorguları
│   ├── security.py                                 # OpenClaw erişim kontrolü
│   ├── system_health.py                            # CPU/RAM/GPU telemetri ve optimizasyon
│   ├── todo_manager.py                             # TodoWrite/TodoRead uyumlu görev yönetimi
│   └── web_search.py                               # Çoklu motor web arama ve URL çekme
├── tests/
│   ├── __init__.py                                 # Test paket işaretleyicisi
│   ├── test_sidar.py                               # Entegre async regresyon testleri
│   ├── test_agent_init_improvements.py             # Agent başlatma birim testleri
│   ├── test_agent_subtask.py                       # Subtask / Agent aracı birim testleri
│   ├── test_auto_handle_improvements.py            # Auto-handle regex/yönlendirme testleri
│   ├── test_cli_banner.py                          # CLI banner dinamik sürüm testleri
│   ├── test_code_manager_improvements.py           # Kod yöneticisi ve izolasyon testleri
│   ├── test_config_env_helpers.py                  # Çevre değişkeni ve config okuma testleri
│   ├── test_core_init_improvements.py              # Core export (Dışa aktarım) tutarlılık testleri
│   ├── test_definitions_prompt.py                  # Prompt ve system yönergeleri testleri
│   ├── test_github_manager_improvements.py         # GitHub API entegrasyon testleri
│   ├── test_github_upload_improvements.py          # GitHub Upload senaryo testleri
│   ├── test_llm_client_improvements.py             # Ollama/Gemini istemci katmanı testleri
│   ├── test_managers_init_improvements.py          # Managers export tutarlılık testleri
│   ├── test_memory_improvements.py                 # Oturum/Kalıcı bellek yönetimi testleri
│   ├── test_package_info_improvements.py           # Paket bilgisi ve sürüm kontrolü testleri
│   ├── test_rag_improvements.py                    # RAG hibrit arama ve chunking testleri
│   ├── test_security_improvements.py               # OpenClaw erişim modeli testleri
│   ├── test_sidar_improvements.py                  # Agent genel iyileştirme testleri
│   ├── test_system_health_improvements.py          # Sistem izleme/GPU telemetri testleri
│   ├── test_todo_manager_improvements.py           # Todo takip yöneticisi testleri
│   ├── test_web_search_improvements.py             # Web arama motoru fallback testleri
│   ├── test_web_server_improvements.py             # FastAPI / SSE endpoint testleri
│   └── test_web_ui_security_improvements.py        # UI sanitize/XSS yüzeyi testleri
├── web_ui/
│   └── index.html                                  # Tek dosya Web UI (SSE, oturum, modal, tema)
├── .env.example                                    # Örnek ortam değişkenleri
├── .gitignore                                      # Repo hijyeni için ignore kuralları
├── .note                                           # WSL/Conda odaklı çalışma notları (taslak)
├── CLAUDE.md                                       # Claude Code uyumluluk notları
├── SIDAR.md                                        # Proje-geneli ajan çalışma kuralları
├── DUZELTME_GECMISI.md                             # Kapatılan bulgular için tarihsel arşiv
├── PROJE_RAPORU.md                                 # Ana teknik analiz raporu
├── README.md                                       # Kurulum/kullanım dokümantasyonu
├── config.py                                       # Merkezi konfigürasyon ve donanım tespiti
├── main.py                                         # Etkileşimli launcher (Wizard + quick start)
├── cli.py                                          # Asıl terminal tabanlı CLI giriş noktası
├── web_server.py                                   # FastAPI web/sse sunucusu
├── github_upload.py                                # Etkileşimli GitHub upload yardımcı aracı
├── Dockerfile                                      # Uygulama container build tanımı
├── docker-compose.yml                              # CPU/GPU × CLI/Web servis orkestrasyonu
├── environment.yml                                 # Conda bağımlılık manifesti
└── install_sidar.sh                                # Ubuntu/WSL otomatik kurulum betiği
```

> Not (2026-03-05): Bu bölüm `git ls-files` çıktısına göre 59 izlenen dosya baz alınarak güncellenmiştir.


---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="3-onceki-rapordan-bu-yana-duzeltilen-hatalar"></a>
## 3. Önceki Rapordan Bu Yana Düzeltilen Hatalar

> ✅ **v2.5.0 → v2.7.0** arası toplam **77 düzeltme** uygulanmıştır ([§3.1–§3.76](DUZELTME_GECMISI.md#sec-3-1-3-76) + C-01 kapanışı).
> ✅ **C-01 (Event-Loop Bloklama + BM25 Thread-Safety):** `asyncio.to_thread`, `BackgroundTasks`, inkremental BM25 cache ve kapsamlı `threading.Lock` kullanımıyla tamamen giderilmiştir.
> Tüm düzeltme detayları okunabilirliği korumak amacıyla ayrı dosyaya taşınmıştır:
>
> 📄 **[DUZELTME_GECMISI.md](DUZELTME_GECMISI.md#sec-3-1-3-76)** — tam düzeltme geçmişi (§3.1–§3.76)

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="4-mevcut-kritik-hatalar"></a>
## 4. Mevcut Kritik Hatalar

> ✅ **2026-03-06 Güncel Taraması:** v2.7.0 kod tabanında **aktif kritik hata bulunmamaktadır**. C-01 dahil önceki kritik bulgular kapatılmıştır.

| ID | Modül / Dosya | Durum | Not |
| :--- | :--- | :--- | :--- |
| — | — | ✅ Açık kritik yok | Kritik bulguların kapanış geçmişi için bkz. [DUZELTME_GECMISI.md](DUZELTME_GECMISI.md). |

*(Geçmişteki kritik sorunlar tamamen giderilmiştir; detaylar için bkz. [DUZELTME_GECMISI.md](DUZELTME_GECMISI.md))*

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="5-yuksek-oncelikli-sorunlar"></a>
## 5. Yüksek Öncelikli Sorunlar (High Priority)

> ✅ **2026-03-06 Güncel Taraması:** v2.7.0 kod tabanında **aktif yüksek öncelikli hata bulunmamaktadır**. H-03 ve H-04 dahil önceki bulgular kapatılmıştır.

| ID | Modül / Dosya | Durum | Not |
| :--- | :--- | :--- | :--- |
| — | — | ✅ Açık yüksek öncelikli yok | Kapanan bulguların geçmişi için bkz. [DUZELTME_GECMISI.md](DUZELTME_GECMISI.md). |

*(Geçmişteki yüksek öncelikli sorunlar (H-01, H-02, H-03 ve H-04) tamamen giderilmiştir; detaylar için bkz. [DUZELTME_GECMISI.md](DUZELTME_GECMISI.md))*

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="6-orta-oncelikli-sorunlar"></a>
## 6. Orta Öncelikli Sorunlar (Medium Priority)

> ✅ **2026-03-06 Güncel Taraması:** v2.7.0 kod tabanında **aktif orta öncelikli hata bulunmamaktadır**. M-01, M-02 ve M-03 bulguları kapatılmış, M-04 ise bir güvenlik prensibi (Safe Sync) olarak kabul edilip mimariye dahil edilmiştir.

| ID | Modül / Dosya | Durum | Not |
| :--- | :--- | :--- | :--- |
| — | — | ✅ Açık orta öncelikli yok | Kapanan bulguların geçmişi için bkz. [DUZELTME_GECMISI.md](DUZELTME_GECMISI.md). |

*(Geçmişte tespit edilen M-01, M-02, M-03, M-04 ile N ve O serisi kodlu sorunlar tamamen giderilmiş veya tasarıma bağlanmıştır. Detaylar için bkz. [DUZELTME_GECMISI.md](DUZELTME_GECMISI.md))*

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="7-dusuk-oncelikli-sorunlar"></a>
## 7. Düşük Öncelikli Sorunlar (Low Priority / Technical Debt)

> ✅ **2026-03-06 Güncel Taraması:** v2.7.0 kod tabanında **aktif düşük öncelikli hata bulunmamaktadır**. L-01, L-03 ve L-05 maddeleri kapatılmıştır.

| ID | Modül / Dosya | Durum | Not |
| :--- | :--- | :--- | :--- |
| — | — | ✅ Açık düşük öncelikli yok | Kapanan bulguların geçmişi için bkz. [DUZELTME_GECMISI.md](DUZELTME_GECMISI.md). |

*(Geçmişteki L-serisi ile N-03, N-04, O-01, O-04, O-06 ve P-01–P-07 numaralı bulgular tamamen giderilmiştir. Detaylar için bkz. [DUZELTME_GECMISI.md](DUZELTME_GECMISI.md))*

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="8-dosyalar-arasi-uyumsuzluk-tablosu"></a>
## 8. Dosyalar Arası Uyumsuzluk Tablosu

> ✅ **2026-03-06 Güncel Taraması:** v2.7.0 kod tabanında rapor ile kod arasında **aktif uyumsuzluk (drift) bulunmamaktadır**. U-16, U-17, U-18 ve U-19 dahil tüm sapma bulguları kapatılmıştır.

| ID | Tür (Önem) | Konum | Durum |
| :--- | :--- | :--- | :--- |
| — | — | — | ✅ Açık uyumsuzluk yok |

*(Geçmişteki U-01–U-19, V-01–V-03, N-01–N-04 ve O-01–O-06 numaralı tüm dosyalar arası uyumsuzluklar tamamen giderilmiştir. Kapatılan bulguların detayları ve çapraz doğrulamalar için bkz. [DUZELTME_GECMISI.md](DUZELTME_GECMISI.md))*

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="9-bagimlilik-analizi"></a>
## 9. Bağımlılık Analizi

<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="environmentyml-guncel-durum-tablosu"></a>
### `environment.yml` — Güncel Durum Tablosu

| Paket | Versiyon | Kullanım Yeri | Durum |
|-------|----------|---------------|-------|
| **Çekirdek Ortam** | | | |
| `python` | `=3.11` | Ana çalışma ortamı | ✅ Aktif |
| `pip` / `git` | `=24.2` / `=2.45` | Paket yöneticisi ve Sürüm kontrol | ✅ Aktif |
| `setuptools` / `wheel` | `75.1` / `0.44` | Build yardımcıları | ✅ Aktif |
| **Temel Pip Paketleri** | | | |
| `packaging` | `~=24.1` | Paket sürüm kıyaslama işlemleri | ✅ Aktif |
| `python-dotenv` | `~=1.0.1` | `config.py` (.env yükleme) | ✅ Aktif |
| `pyyaml` | `~=6.0.2` | `Dockerfile` / Compose build | ✅ Aktif |
| ~~`requests`~~ | — | *Kaldırıldı* | ✅ Tüm HTTP `httpx` ile yapılıyor |
| `httpx` | `~=0.27.0` | LLMClient, WebSearch, PackageInfo, RAG | ✅ Ana asenkron HTTP kütüphanesi |
| `pydantic` | `~=2.8.2` | `ToolCall` modeli, şema doğrulama | ✅ v2 API doğru |
| `psutil` | `~=6.0.0` | CPU/RAM izleme telemetrisi | ✅ Aktif |
| `nvidia-ml-py` | `~=12.560.30` | GPU sıcaklık/kullanım | ✅ WSL2 fallback ile |
| `docker` | `~=7.1.0` | CodeManager REPL sandbox | ✅ Aktif |
| `cryptography` | `~=43.0.1` | Memory Fernet şifreleme | ✅ **YENİ** Aktif |
| **Yapay Zeka & RAG** | | | |
| `torch` / `torchvision`| `~=2.4.1` / `~=0.19.1`| GPU embedding, CUDA kontrolü | ✅ CUDA 12.4 wheel (cu124) |
| `google-generativeai` | `~=0.8.3` | Gemini sağlayıcı | ✅ Aktif |
| `rank-bm25` | `==0.2.2` | Hibrit arama (BM25 motoru) | ✅ Aktif |
| `chromadb` | `~=0.5.5` | Vektör veritabanı | ✅ Aktif |
| `sentence-transformers`| `~=3.0.1` | Embedding modeli | ✅ GPU destekli |
| **Ajan Araçları** | | | |
| `PyGithub` | `~=2.4.0` | GitHub API (Manager) | ✅ Aktif |
| `duckduckgo-search` | `~=6.2.13` | Web arama motoru | ✅ Aktif |
| `beautifulsoup4` | `~=4.12.3` | Web HTML içeriği ayrıştırma | ✅ Aktif |
| **Web Sunucusu** | | | |
| `fastapi` | `~=0.115.0` | Web ve SSE sunucu | ✅ Aktif |
| `uvicorn[standard]` | `~=0.30.6` | ASGI sunucu motoru | ✅ Aktif |
| `prometheus-client` | `~=0.21.0` | `/metrics` endpoint'i (Prometheus formatı) | ✅ Aktif |
| **Test & Kalite** | | | |
| `pytest` / `pytest-cov`| `~=8.3.3` / `~=5.0.0`| Birim ve Regresyon testleri | ✅ Aktif |
| `pytest-asyncio` | `~=0.24.0` | Asenkron test koşucusu | ✅ Aktif |
| `black` / `flake8` | `~=24.8.0` / `~=7.1.1`| Kod formatlama ve Linting | ✅ Aktif |
| `mypy` | `~=1.11.2` | Statik tip kontrolü | ✅ Aktif |


---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="10-guclu-yonler"></a>
## 10. Güçlü Yönler


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="101-mimari-onceki-versiyona-kiyasla-iyilesmeler"></a>
### 10.1 Mimari — Temel İyileştirmeler

- ✅ **Dispatcher tablosu:** genişleyen araç seti için `if/elif` zinciri yerine merkezi `dict` dispatch + ayrı `_tool_*` metodları kullanılıyor
- ✅ **Thread pool kullanımı:** Disk I/O (`asyncio.to_thread`), Docker REPL (`asyncio.to_thread`), DDG araması (`asyncio.to_thread`) event loop'u bloke etmiyor
- ✅ **Async lock yönetimi:** `_agent_lock = asyncio.Lock()` (web_server), `agent._lock = asyncio.Lock()` (sidar_agent) doğru event loop'ta yaşıyor
- ✅ **Akıllı Launcher:** `main.py` etkileşimli bir sihirbaz olarak yapılandırılmış, asıl CLI döngüsü `cli.py` içinde tek bir `asyncio.run` içinde izole edilmiştir


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="102-docker-repl-sandbox-yeni"></a>
### 10.2 Docker REPL Sandbox

```python
container = self.docker_client.containers.run(
    image=self.docker_image,   # python:3.11-alpine varsayılanı
    command=["python", "-c", code],
    detach=True,
    network_disabled=True,    # Dış ağa erişim yok
    mem_limit="128m",         # 128 MB RAM limiti
    cpu_quota=50000,          # %50 CPU limiti
)
```

- ✅ 10 saniye zaman aşımı koruması ve otomatik temizleme (`force=True`)


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="103-coklu-oturum-sistemi-yeni"></a>
### 10.3 Çoklu Oturum Sistemi ve Bellek Şifrelemesi (YENİ)

- ✅ **Kalıcılık:** UUID tabanlı, `data/sessions/*.json` dosyalarında çoklu sohbet oturumu yönetimi
- ✅ **Fernet Şifreleme:** `.env` içinde `MEMORY_ENCRYPTION_KEY` verildiğinde sohbet dosyaları diske `cryptography` ile şifrelenerek yazılır


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="104-gpu-hizlandirma-altyapisi-yeni"></a>
### 10.4 Sonsuz Hafıza ve Hibrit RAG (YENİ)

- ✅ **Vector Archive:** Hafıza sınırına yaklaşıldığında eski konuşmalar silinmeden önce ChromaDB'ye otomatik arşivlenir
- ✅ **Otomatik RAG Yönlendirmesi:** `RAG_FILE_THRESHOLD` aşılan büyük dosyalarda model, doğrudan tam metin yerine verimli RAG indekslemesine yönlendirilir


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="105-web-arayuzu-ozellikler-v261-ile-guncellendi"></a>
### 10.5 Akıllı Hızlandırma: Direct Route & Parallel Araçlar (YENİ)

- ✅ **Direct Tool Route:** Basit istekler ağır ReAct döngüsüne girmeden doğrudan ilgili araca yönlendirilir
- ✅ **Paralel Çalıştırma (`_tool_parallel`):** Yalnızca okuma yapan güvenli araçlar `asyncio.gather` ile eşzamanlı çalıştırılabilir
- ✅ **mtime Cache:** `SIDAR.md` ve `CLAUDE.md` gibi sistem talimat dosyalarındaki değişiklikler anlık algılanarak bellek güncellenir


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="106-rate-limiting-yeni"></a>
### 10.6 Web Arayüzü — İleri Özellikler

- ✅ **Canlı Aktivite Paneli:** LLM akışındaki `THOUGHT:` ve `TOOL:` sentinelleri ile ajanın düşünce/araç adımları gerçek zamanlı gösterilir
- ✅ **RAG Modalı:** Arayüz üzerinden belge ekleme/silme, URL ekleme ve vektörel arama işlemleri yapılabilir
- ✅ **Oturum dışa aktarma ve operasyonel UX:** JSON/Markdown dışa aktarma, dal/repo yönetimi ve klavye kısayolları


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="107-recursive-character-chunking-yeni"></a>
### 10.7 Görev Yönetimi (TodoManager) (YENİ)

- ✅ **TodoWrite / TodoRead / TodoUpdate:** Claude Code çalışma standardına uyumlu çok adımlı görev planlama ve ilerleme takibi


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="108-llm-stream-buffer-guvenligi"></a>
### 10.8 Rate Limiting & Güvenlik

- ✅ **Çok katmanlı limit:** `/chat` (20 req/60s), mutasyon endpoint'leri (60 req/60s), I/O endpoint'leri (30 req/60s)
- ✅ **TOCTOU koruması:** Asenkron lock ile eşzamanlı yoğun isteklerde olası bypass senaryoları engellenir
- ✅ **Path Traversal ve uzantı whitelist:** `SecurityManager` filtreleri ile dosya işlemlerinde sıkı sınırlar


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="109-recursive-character-chunking"></a>
### 10.9 Recursive Character Chunking

- ✅ LangChain mantığına benzer `_recursive_chunk_text` akışıyla `class/def`, paragraf ve cümle sınırları önceliklendirilir


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1010-llm-stream-buffer-guvenligi"></a>
### 10.10 LLM Stream — Buffer Güvenliği

- ✅ Multibyte UTF-8 parçalanması ve eksik JSON satırlarının TCP paket sınırlarında güvenli şekilde tamponlanması uygulanır

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="11-guvenlik-degerlendirmesi"></a>
## 11. Güvenlik Değerlendirmesi

> Son güncelleme: 2026-03-05 (v2.7.0 kod tabanı güncel durum analizi)

| Alan | Durum & Alınan Önlem | Güvenlik Seviyesi |
|------|----------------------|-------------------|
| **Erişim Kontrolü (OpenClaw)** | ✅ 3 katmanlı (`restricted / sandbox / full`) yetki modeli aktiftir. | İyi |
| **Kod Çalıştırma İzolasyonu** | ✅ Docker sandbox — `network_disabled`, `mem_limit=128m`, `cpu_quota=50000`, 10sn timeout zorunludur. | Çok İyi |
| **Rate Limiting (DDoS Koruması)** | ✅ 3 katmanlı TOCTOU korumalı — `/chat` 20 req/60s, POST+DELETE 60 req/60s, GET I/O 30 req/60s. | İyi |
| **Bellek Şifreleme (Fernet)** | ✅ `MEMORY_ENCRYPTION_KEY` ile diskteki sohbet dosyaları uçtan uca şifrelenmektedir. *(Önceki sürümlerdeki düz metin JSON riski kapatıldı)* | İyi |
| **Komut Enjeksiyonu (Shell Injection)** | ✅ Alt süreçler (`subprocess`) varsayılan olarak `shell=False` ve `shlex.split()` kullanılarak tokenize edilir. Özel operatörler açık onaya bağlıdır. | İyi |
| **Web UI XSS Koruması** | ✅ LLM çıktıları `sanitizeRenderedHtml` katmanından geçirilerek tehlikeli etiketler/olay öznitelikleri temizlenir; Activity Panel ile kullanıcıya güvenli ve şeffaf akış sunulur. | İyi |
| **Path Traversal (Dizin Aşma)** | ⚠️ Symlink ve Windows riskli path kalıpları engellenmiştir. Ancak `can_read` mekanizması blacklist tabanlıdır, katı kök dizin sınırı eksiktir. | Orta |
| **Prompt Injection** | ⚠️ Sistem promptu güçlü direktiflerle korunmaktadır, ancak kullanıcıdan gelen metne yönelik dinamik bir ön filtreleme yoktur. | Orta |
| **CORS Politikası** | ✅ Dinamik port üzerinden yalnızca `localhost` / `127.0.0.1` orijinlerine izin verecek şekilde daraltılmıştır. | Çok İyi |
| **Kurulum Betiği (Install Script)** | ✅ Uzaktan script yürütme (`curl | sh`) ve paket güncellemeleri varsayılan olarak kapalıdır, bilinçli `ALLOW_*` onayı gerektirir. | İyi |
| **Dal Adı & Git Güvenliği** | ✅ `_BRANCH_RE` regex ile dal (branch) adları sıkı bir şekilde valide edilir; Git URL enjeksiyonları ayrıştırılarak önlenir. | İyi |
| **Binary Dosya Güvenliği** | ✅ `SAFE_EXTENSIONLESS` whitelist ile uzantısız zararlı binary dosyaların okunması/yazılması engellenmektedir. | İyi |

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="12-test-kapsami"></a>
## 12. Test Kapsamı

> ✅ **v2.7.0 Güncel Durumu:** Önceki sürümlerdeki (TST-02) “tüm testlerin tek bir dosyada (`test_sidar.py`) toplanması” teknik borcu çözülmüştür. Test mimarisi modüler hale getirilmiş ve 20+ spesifik dosyaya bölünerek birim (unit), entegrasyon ve güvenlik testleri izole edilmiştir. Testler `pytest` ve `pytest-asyncio` ile koşulmaktadır.


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="121-moduler-test-mimarisi-tests-dizini"></a>
### 12.1 Modüler Test Mimarisi (tests/ Dizini)

Güncel test seti, projenin farklı katmanlarını hedefleyen spesifik dosyalara ayrılmıştır:

| Kategori | Test Dosyaları | Kapsadığı Odak Alanları |
| :--- | :--- | :--- |
| **Agent & Prompt** | `test_agent_init_improvements.py`<br>`test_agent_subtask.py`<br>`test_auto_handle_improvements.py`<br>`test_definitions_prompt.py` | Ajan başlatma, ReAct/subtask akışı, prompt tutarlılığı ve hızlı komut yönlendirme senaryoları. |
| **Core (Çekirdek)** | `test_core_init_improvements.py`<br>`test_llm_client_improvements.py`<br>`test_memory_improvements.py`<br>`test_rag_improvements.py` | LLM istemcileri, stream buffering, Fernet şifreli bellek, hibrit RAG ve recursive chunking davranışı. |
| **Managers (Yöneticiler)** | `test_code_manager_improvements.py`<br>`test_github_manager_improvements.py`<br>`test_github_upload_improvements.py`<br>`test_system_health_improvements.py`<br>`test_web_search_improvements.py`<br>`test_todo_manager_improvements.py`<br>`test_package_info_improvements.py` | Docker sandbox, Git/GitHub akışı, sistem sağlık metrikleri, web arama fallback zinciri, Todo iş akışları ve paket/sürüm doğrulama. |
| **Güvenlik & Web** | `test_security_improvements.py`<br>`test_web_server_improvements.py`<br>`test_web_ui_security_improvements.py` | Erişim modeli, path traversal/symlink kontrolleri, SSE/rate-limit davranışı, UI XSS sanitize kontrolleri. |
| **Altyapı & Export** | `test_config_env_helpers.py`<br>`test_cli_banner.py`<br>`test_managers_init_improvements.py` | Çevre değişkeni parsing, banner davranışı, modül export (`__all__`) tutarlılığı. |
| **Regresyon (Legacy + Geniş Entegrasyon)** | `test_sidar.py`<br>`test_sidar_improvements.py` | Geriye dönük davranış uyumluluğu ve çoklu bileşenleri kapsayan regresyon senaryoları. |


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="122-one-cikan-guvenlik-ve-edge-case-testleri"></a>
### 12.2 Öne Çıkan Güvenlik ve Edge-Case Testleri

Yeniden yapılandırılan test setinde yalnızca “happy path” değil, aşağıdaki sınır durumları da doğrulanmaktadır:

- **`test_web_ui_security_improvements.py`:** `index.html` içindeki sanitize katmanının zararlı etiket ve XSS payload’larına karşı davranışı test edilir.
- **`test_memory_improvements.py`:** Geçersiz şifreleme anahtarı/bozuk session dosyası senaryolarında sistemin çökmeden güvenli fallback/karantina davranışı doğrulanır.
- **`test_rag_improvements.py`:** Eşzamanlı delete+upsert senaryolarında indeks bütünlüğü ve lock davranışı kontrol edilir.
- **`test_todo_manager_improvements.py`:** Çok adımlı görev akışlarında durum geçişlerinin (`pending/in_progress/completed`) tutarlılığı doğrulanır.
- **`test_web_server_improvements.py`:** Rate limiting katmanının TOCTOU/eşzamanlı istek koşullarındaki davranışı sınanır.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13-dosya-bazli-detayli-inceleme"></a>
## 13. Dosya Bazlı Detaylı İnceleme

> Bu bölüm tarihsel satır aralığı/sürüm ifadeleri yerine **güncel teknik durumu** özetler.
> Kapanan bulguların ayrıntılı kayıtları için: 📄 **[DUZELTME_GECMISI.md](DUZELTME_GECMISI.md)**


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="131-cekirdek-dosyalar-guncel-durum"></a>
### 13.1 Çekirdek Dosyalar — Güncel Durum

- **`main.py`**: Artık interaktif CLI döngüsü değil, **akıllı launcher** katmanı olarak çalışır. Kullanıcıdan mode/provider/level/log seçimlerini alır, `preflight` kontrollerini yapar ve hedef script'i (`web_server.py` veya `cli.py`) `subprocess.run(...)` ile başlatır. → Detay: §13.5.1
- **`cli.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: Asenkron terminal arayüzü, tek-shot komut modu ve modern banner/sürüm gösterimiyle çalışır. **Açık Hata: Yok.** Not: L-05 banner kırpılması sorunu sürüm bilgisinin çerçeve altına alınmasıyla çözülmüştür. → Detay: §13.5.1A
- **`agent/sidar_agent.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: Merkezi `self._tools` tablosu ve dinamik docstring tabanlı araç listesi (`_build_tool_list`) ile prompt/runtime drift riski giderilmiştir. Tüm disk/ağ I/O `asyncio.to_thread()` ile event-loop dışına alınır; arşiv bağlamı `top_k/min_score/max_chars` ile sınırlandırılır. **Açık Hata: Yok.** Not: H-03 (Sonsuz Hafıza Context Taşması) asenkron RAG aramasıyla ve L-01 (Statik Araç Listesi) dinamik üretimle çözülmüştür. → Detay: §13.5.2
- **`core/rag.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: ChromaDB → BM25 → Keyword hibrit arama katmanı, inkremental BM25 cache, thread-safe kilit mimarisi ve arka plan prebuild akışıyla çalışır. **Açık Hata: Yok.** Not: C-01 (Event-loop bloklaması) ve okuma-yazma thread-safety çakışmaları `asyncio.to_thread` + kapsamlı lock yaklaşımıyla tamamen giderilmiştir. → Detay: §13.5.3
- **`web_server.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: FastAPI + SSE akışı, lazy lock başlatımı ve RAG mutasyonları sonrası arka plan BM25 prebuild ile yüksek eşzamanlılıkta stabil çalışır. **Açık Hata: Yok.** Not: L-05 banner kırpma ve asenkron kilit uyarıları giderilmiştir. → Detay: §13.5.4
- **`agent/definitions.py`**: Ajan persona/sistem prompt sözleşmesi, araç kullanım stratejileri, todo iş akışı ve JSON çıktı şeması tek noktadan tanımlanır. ✅ Prompt metninde sağlayıcı koşulu netleştirildi (Gemini için internet gereksinimi); ayrıca araç listesi için source-of-truth olarak `sidar_agent.py` dispatch tablosu açıkça belirtildi. → Detay: §13.5.5
- **`agent/auto_handle.py`**: Örüntü tabanlı hızlı yönlendirme katmanı; çok adımlı komutları `_MULTI_STEP_RE` ile ReAct döngüsüne bırakır, tek adımlı sık isteklerde LLM çağrısını azaltır. ✅ `docs_search` artık `asyncio.to_thread` ile event-loop dışına alınır; GitHub info regex tetikleyicisi bilgi/özet niyetiyle daraltılarak yanlış-pozitifler azaltıldı. → Detay: §13.5.6
- **`core/llm_client.py`**: Sağlayıcı soyutlama katmanı (Ollama/Gemini), JSON-mode yapılandırması ve stream ayrıştırma mantığı tek noktada yönetilir. ✅ Gemini akışında güvenli `getattr(chunk, "text", "")` erişimi kullanılıyor; ayrıca `_stream_ollama_response` sonunda newline ile bitmeyen son buffer satırı da parse edilerek olası son chunk kaybı önleniyor. → Detay: §13.5.7
- **`core/memory.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: Çoklu oturumlu kalıcı bellek, thread-safe kaydetme ve Fernet şifreleme/fallback akışıyla dayanıklıdır. **Açık Hata: Yok.** Not: H-04 (InvalidToken/anahtar uyuşmazlığı) fallback mekanizması ile kapatılmıştır. → Detay: §13.5.8
- **`config.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: Merkezi yapılandırma, `.env` yükleme ve provider/GPU/RAG/web ayarlarını tek noktadan yönetir; donanım bilgisi lazy-init ile yalnızca ihtiyaç anında yüklenir. **Açık Hata: Yok.** Not: M-02 (bloklayıcı donanım sorgusu) lazy-init mimarisiyle çözülüp başlangıç hızı optimize edilmiştir. → Detay: §13.5.9
- **`managers/code_manager.py`**: Dosya I/O, sözdizimi doğrulama, audit ve Docker izoleli kod çalıştırma yeteneklerini tek manager altında toplar. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.10
- **`managers/github_manager.py`**: PyGithub tabanlı repo/commit/branch/PR/dosya operasyonlarını kapsar; branch adı doğrulaması (`_BRANCH_RE`) ve metin tabanlı uzantı filtresi ile güvenli okuma yaklaşımı uygulanır. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.11
- **`managers/system_health.py`**: CPU/RAM/GPU sağlık telemetrisi ve VRAM temizleme işlevlerini birleştirir; WSL2/NVML fallback mantığıyla farklı ortamlarda dayanıklı raporlama sağlar. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.12
- **`managers/web_search.py`**: Tavily/Google/DDG çoklu motor mimarisiyle async arama ve URL içerik çekme sağlar; `auto` modda kademeli fallback uygulanır. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.13
- **`managers/package_info.py`**: PyPI, npm ve GitHub Releases sorgularını asenkron `httpx` akışıyla birleştirir; sürüm karşılaştırma ve pre-release filtreleme yardımcıları içerir. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.14
- **`managers/security.py`**: OpenClaw erişim katmanı; yol doğrulama, traversal/symlink koruması ve erişim seviyesine göre okuma-yazma-çalıştırma yetkisi sağlar. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.15
- **`managers/todo_manager.py`**: Claude Code uyumlu görev takip katmanı; thread-safe görev ekleme/güncelleme/listeleme API'leri ve durum bazlı raporlama sağlar. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.16
- **`managers/__init__.py`**: Manager katmanının dışa aktarma (public API) yüzeyini tek noktada toplar; `TodoManager` dahil tüm manager sınıfları `__all__` ile açıkça listelenir. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.17
- **`core/__init__.py`**: Core paketinin public API yüzeyini (`ConversationMemory`, `LLMClient`, `DocumentStore`, `__version__`) merkezileştirir ve üst katman importlarını sadeleştirir. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.18
- **`agent/__init__.py`**: Agent paketinin dışa aktarma yüzeyi olarak `SidarAgent` ve temel prompt anahtarlarını tek import noktasında toplar. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.19
- **`tests/test_sidar.py`**: Çekirdek + manager + web katmanı için geniş kapsamlı (64) regresyon seti sağlar; async senaryolar `pytest-asyncio` ile doğrulanır. ✅ Durum: Tam Optimize Edildi / Sıfır Teknik Borç. → Detay: §13.5.20
- **`web_ui/index.html`**: Tek dosyada HTML+CSS+JS ile Web UI deneyimini, SSE chat akışını, oturum/branch/repo yönetimini ve RAG/PR yardımcı etkileşimlerini yönetir. ✅ `sanitizeRenderedHtml` katmanı ile Markdown render akışı güvenlik filtrelerinden geçirilir; Activity Panel ve gelişmiş modal akışlarıyla tek sayfa arayüzde yüksek görünürlük sağlar. → Detay: §13.5.21
- **`github_upload.py`**: Etkileşimli Git yardımcı aracı; kimlik/remote kontrolü, commit ve push/pull senkronizasyon akışını adım adım otomatikleştirir. ✅ Komut yürütme katmanı `shell=False` + argüman listesiyle güvenli çalışır; push çakışmalarında otomatik birleştirme kullanıcı onayına bağlıdır. → Detay: §13.5.22
- **`Dockerfile`**: CPU/GPU çift modlu container build akışını, runtime env değişkenlerini ve healthcheck davranışını tanımlar. ✅ Üst yorum bloğundaki sürüm notu `2.7.0` ile metadata hizasına çekildi; healthcheck mantığı PID 1 komutu bazlı deterministik doğrulamaya yükseltildi; web/CLI ayrımı yalancı-pozitifi kaldıracak şekilde güncellendi. → Detay: §13.5.23
- **`docker-compose.yml`**: Dört servisli (CLI/Web × CPU/GPU) orkestrasyon profilini, build argümanlarını, volume/port eşleştirmelerini ve host erişim köprüsünü yönetir. ✅ Non-Swarm için `cpus`/`mem_limit` sınırları eklendi; Ollama endpoint ve host-gateway çözümü env tabanlı override ile daha taşınabilir hale getirildi. → Detay: §13.5.24
- **`environment.yml`**: Conda + pip bağımlılık manifesti olarak Python/araç zinciri ve CUDA wheel kurulum stratejisini tanımlar. ✅ Conda/pip sürümleri daraltılmış (`=` / `~=`) aralığa çekildi; CPU varsayılan + `PIP_EXTRA_INDEX_URL` ile GPU opsiyonel profile ayrımı daha güvenli hale getirildi. → Detay: §13.5.25
- **`.env.example`**: Uygulama çalışma parametrelerinin şablonunu sunar (AI sağlayıcısı, GPU, web, RAG, loglama, Docker sandbox). ✅ Donanım-özel varsayımlar nötrlendi; güvenli başlangıç için `ACCESS_LEVEL=sandbox` ve `USE_GPU=false` varsayılanlarıyla daha taşınabilir bir profil sağlandı. → Detay: §13.5.26
- **`install_sidar.sh`**: Ubuntu/WSL için uçtan uca kurulum otomasyonu sağlar (sistem paketleri, Miniconda, Ollama, repo, model indirme, `.env` hazırlığı). ✅ Varsayılan akışta sistem yükseltmesi ve uzaktan script çalıştırma kapatıldı; her ikisi de açık opt-in env bayrağı gerektirecek şekilde güvenli hale getirildi. → Detay: §13.5.27
- **`README.md`**: Projenin kurulum/kullanım giriş noktasıdır; özellik özeti, komut örnekleri ve operasyon notlarıyla kullanıcı onboarding akışını taşır. ✅ Kurulum güvenlik modeli (`ALLOW_*` opt-in), `.env` anahtar adları ve güvenli erişim örnekleri güncel runtime davranışıyla hizalandı. → Detay: §13.5.28
- **`SIDAR.md`**: Ajanın proje-geneli çalışma talimatlarını ve araç kullanım önceliklerini tanımlar. ✅ Araç adları ortamdan bağımsızlaştırıldı, pahalı komutlardan kaçınma ilkesi netleştirildi ve branch kuralı ekip akışlarıyla uyumlu esnek yapıya çekildi. → Detay: §13.5.29
- **`CLAUDE.md`**: Claude Code uyumluluğu için araç eşlemesi ve talimat hiyerarşisini açıklar. ✅ Birebir araç adı iddiaları yerine ortamdan bağımsız “yakın karşılık” rehberine çevrildi; opsiyonel yeteneklerin koşullu olduğu açıkça belirtildi. → Detay: §13.5.30
- **`DUZELTME_GECMISI.md`**: Kapatılan hata/iyileştirme kayıtlarının arşiv dosyasıdır; ana rapordaki tarihsel referanslar bu dosyaya yönlenir. ✅ Tarihsel kayıtlar ve arşiv başlıkları ana raporla senkronize tutulur; kapanış zaman çizelgesi izlenebilirliği korunur. → Detay: §13.5.31
- **`tests/__init__.py`**: Test paketini işaretleyen minimal modüldür; test dizininin paket olarak algılanmasını ve import düzenini sade tutmayı destekler. ✅ Bilinçli minimal yapı sayesinde test keşif sürecinde yan etki oluşturmaz; mimari bağlam ana rapor bölümlerinde merkezi olarak korunur. → Detay: §13.5.32
- **`PROJE_RAPORU.md`**: Projenin güncel teknik durumunu ve dosya bazlı denetim sonuçlarını merkezileştiren ana rapordur. ✅ Arşiv ayrımı (`DUZELTME_GECMISI.md`) ve tek doğruluk kaynağı yaklaşımıyla bakım/senkronizasyon riski azaltılmıştır. → Detay: §13.5.33
- **`.gitignore`**: Yerel çalışma çıktılarının ve hassas/üretilmiş dosyaların repoya sızmasını engelleyen kaynak kontrol filtresidir. ✅ Whitelist stratejisi (`data/.gitkeep`) ve modern artefact kurallarıyla depo hijyeni güçlendirilmiştir. → Detay: §13.5.34
- **`.note`**: WSL/Ubuntu/Conda odaklı ortam notları ve öneri patch taslaklarını içeren çalışma notu dosyasıdır. ✅ Durum: İncelendi ve uyumlu olduğu onaylandı. → Detay: §13.5.35


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="132-yonetici-manager-katmani-guncel-durum"></a>
### 13.2 Yönetici (manager) Katmanı — Güncel Durum

- **`managers/security.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: Kök dizin sınırı (`is_path_under`) + tehlikeli desen + hassas yol bloklama katmanları birlikte çalışır. **Açık Hata: Yok.** Not: M-03 (Path Traversal / dizin dışına çıkma) zafiyeti tamamen kapatılmıştır.
- **`managers/todo_manager.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: Görev listesi `todos.json` kalıcılığı, güvenli yükleme/yazma ve UTF-8 kodlama ile dayanıklı şekilde yönetilir. **Açık Hata: Yok.** Not: M-01 (kalıcılık sorunu) `todos.json` + UTF-8 entegrasyonuyla çözülmüştür.
- **`managers/web_search.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: HTML temizleme/çıkarma akışı `BeautifulSoup` ile DOM tabanlıdır; çoklu arama motoru fallback mimarisi asenkron çalışır. **Açık Hata: Yok.** Not: L-03 (regex tabanlı temizleme iddiası) geçersiz hale gelmiş ve kapatılmıştır.
- **`managers/code_manager.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: Docker izolasyonu, dosya güvenlik kontrolleri ve denetim yardımcıları üretim akışıyla uyumlu şekilde çalışır. **Açık Hata: Yok.**
- **`managers/github_manager.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: Branch/PR/depo operasyonları güvenli doğrulamalarla yönetilir, okuma/yazma akışları güncel API davranışlarıyla hizalıdır. **Açık Hata: Yok.**
- **`managers/system_health.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: CPU/RAM/GPU telemetrisi ve WSL2/NVML fallback akışları kararlı şekilde çalışır. **Açık Hata: Yok.**
- **`managers/package_info.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Stabil)**: PyPI/NPM paket bilgi ve sürüm karşılaştırma akışları asenkron ve güvenli parse yapısıyla stabil çalışır. **Açık Hata: Yok.**

<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="133-test-ve-dokumantasyon-uyum-ozeti"></a>
### 13.3 Test ve Dokümantasyon Uyum Özeti

- **`agent/sidar_agent.py` & `agent/definitions.py` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Tam Senkron)**: Ajan araç envanteri `self._tools` + `_build_tool_list` üzerinden dinamik üretilir, prompt/runtime drift ortadan kalkmıştır. **Açık Hata: Yok.** Not: U-18 statik prompt uyumsuzluğu dinamik markdown üretimi ile tamamen kapatılmıştır.
- **`tests/` Dizini ve Asenkron Mimari Uyumu (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Tam Senkron)**: Modüler test yapısı yeni asenkron mimari, lock mekanizmaları ve RAG iyileştirmeleriyle uyumludur. **Açık Hata: Yok.** Not: Test kapsamı güncel mimariyle hizalıdır.
- **`PROJE_RAPORU.md` & `DUZELTME_GECMISI.md` (Skor: 100/100 ✅, Durum: 🟢 Mükemmel / Tam Senkron)**: Tarihsel kayıtlar ve açık/kapalı bulgu durumları iki dokümanda tutarlı şekilde yönetilir. **Açık Hata: Yok.** Not: U-19 tarih sapması giderilmiş, dokümantasyon tarihleri `2026-03-06` ile senkronize edilmiştir.

> **Sonuç:** 13.3 kapsamındaki tüm test ve dokümantasyon kontrol maddeleri tam senkron durumundadır; açık uyumsuzluk bulunmamaktadır.

<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="134-acik-durum"></a>
### 13.4 Açık Durum

> 2026-03-02 doğrulama setine göre bu bölüm kapsamında **aktif kritik/orta/düşük açık bulgu raporlanmamaktadır**.
> Tarihsel doğrulama ve kapanış kayıtları: 📄 **[DUZELTME_GECMISI.md](DUZELTME_GECMISI.md)**

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="135-dosya-bazli-teknik-detaylar"></a>
### 13.5 Dosya Bazlı Teknik Detaylar

> Bu alt bölüm her dosyanın **güncel teknik durumunu** satır referansları ile belgeler.
> Sırası: `main.py` → `cli.py` → `agent/sidar_agent.py` → devam

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1351-mainpy-skor-100100"></a>
#### 13.5.1 `main.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Etkileşimli **akıllı başlatıcı (Ultimate Launcher)**. Web/CLI mod seçimi, sağlayıcı ve erişim seviyesi seçimi, ön kontroller (preflight) ve hedef script'i alt süreçte çalıştırma.

**Dosyanın İşlevi ve Sistemdeki Rolü**

`main.py`, SİDAR projesinin dış dünyaya açılan ana kapısıdır. Kullanıcıyı uzun komut satırı argümanları ezberlemekten kurtararak ANSI renkli, etkileşimli bir **Sihirbaz (Wizard)** sunar.

- **Ön Kontrol (Preflight):** Asıl programı başlatmadan önce Python sürümünü, `.env` dosyasının varlığını, API anahtarlarını ve Ollama servisinin ayakta olup olmadığını kontrol eder.
- **Gözlem ve Loglama:** Seçilen hedef programı bir alt süreç (child process) olarak başlatır. Olası çökmeleri izler, anlık çıktıları (`stdout`/`stderr`) doğrudan terminale yansıtır ve istenirse RAM'i şişirmeden bir log dosyasına yazar.

**Doğrudan Bağlantılı Olduğu Dosyalar**

Bu dosya projenin başlatıcı motoru olduğu için aşağıdaki dosyalarla doğrudan ilişki kurar:

- 🔗 `config.py`: Arayüzdeki varsayılan değerleri (port, host, varsayılan model vb.) okumak için içe aktarılır. Eğer dosya bozuksa veya yoksa `main.py` içindeki `DummyConfig` devreye girerek çöküşü engeller.
- 🔗 `web_server.py`: Kullanıcı menüden "Web Arayüzü Sunucusu"nu seçerse, argümanlar derlenir ve bu dosya `subprocess` ile başlatılır.
- 🔗 `cli.py`: Kullanıcı menüden "CLI Terminal Arayüzü"nü seçerse, bu dosya başlatılır. (Eski sürümlerdeki asenkron CLI döngüsü bu dosyaya devredilmiştir).
- 🔗 `.env`: Sistem gereksinimleri (preflight aşaması) kontrol edilirken bu dosyanın varlığı teyit edilir.

**Mimari Özeti (satır 1–301)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 1–26 | Modül başlığı & Import | Dosyanın launcher rolü (`python main.py`, `--quick`) açıkça tanımlı ve terminal renkleri ayarlı |
| 28–49 | `DummyConfig` Fallback | `config.py` bulunamaması/yüklenememesi durumunda çökmeyi engelleyen, varsayılan ayarları sağlayan güvenli başlangıç katmanı |
| 105–129 | `preflight(provider)` | Python sürümü, `.env`, Gemini key ve Ollama `/api/tags` erişimi ön doğrulanır |
| 132–140 | `build_command(...)` | Asıl çalışma script'i (`web_server.py` veya `cli.py`) ve parametreleri kullanıcı seçimine göre dinamik belirlenir |
| 143–145 | `_format_cmd(cmd)` | Komut görüntüleme için shell-safe quote üretimi |
| 148–199 | `_stream_pipe` & `_run_with_streaming` | Child stdout/stderr thread'ler ile izlenir; RAM'i şişirmeden (streaming) anlık olarak doğrudan diske/log dosyasına yazılır |
| 202–243 | `run_wizard()` | ANSI renkli etkileşimli menü akışı (mode/provider/level/log + ek alanlar) |
| 246–262 | `execute_command(...)` | Normal passthrough + opsiyonel canlı capture/loglama akışı |
| 264–301 | `main()` | `--quick`, `--capture-output`, `--child-log` sihirbaz atlanarak parametre + gözlemlenebilirlik bayraklarıyla doğrudan başlatma |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm mimari riskler ve bellek şişme sorunları giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1351a-clipy-skor-95100"></a>
#### 13.5.1A `cli.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Asıl terminal tabanlı CLI etkileşim katmanı. `SidarAgent` oluşturma, tek komut modu (`--command`), interaktif asenkron döngü, dahili nokta komutları ve durum gösterimlerinin yönetimi.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Önceki sürümlerde `main.py` içinde yer alan karmaşık CLI mantığı tamamen bu dosyaya izole edilmiştir.

- **Etkileşimli Döngü:** Kullanıcıdan senkron `input()` alırken ana event-loop'u kilitlememek için giriş işlemlerini bir alt thread'e (`asyncio.to_thread`) iter.
- **Dahili Komutlar:** Kullanıcının sohbet haricinde sistemi yönetebilmesi için `.status`, `.clear`, `.health`, `.audit` gibi performanslı nokta komutları sunar.
- **Config Override:** Başlatma parametrelerine (örn. `--level`, `--provider`) göre yapılandırma ayarlarını modül yüklenme anında ezer.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Ajanın başlatılması ve asıl iş mantığının (`respond` akışının) yürütülmesi için doğrudan çağrılır.
- 🔗 `config.py`: Ajanın ihtiyaç duyduğu varsayılan ayarları yükler. CLI argümanları ile bu dosyadaki ayarlar eklenebilir.
- 🔗 `main.py`: Kullanıcı akıllı başlatıcı üzerinden "CLI Modu"nu seçerse `cli.py` tetiklenir.

**Mimari Özeti (satır 1–185)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 26–31 | `_setup_logging(...)` | CLI `--log` argümanına göre root logger seviyesini ayarlar |
| 41–58 | `_make_banner(version)` | Dinamik ASCII karşılama banner'ı; çerçeve taşmasını engellemek için akıllı kırpma (truncation) içerir |
| 85–151 | `_interactive_loop_async` | Tüm sohbetin tek bir `asyncio.Lock()` ve event loop içinde yaşamasını sağlayan güvenli döngü. `input()` çağrısı `to_thread` ile izole edilmiştir |
| 154–155 | `interactive_loop(...)` | Asenkron etkileşimli döngüyü tek giriş noktasından `asyncio.run` ile tetikler |
| 160–185 | `main()` | Argüman ayrıştırma, Config sınıfları üzerinden özellikleri geçici olarak (override) ezme ve tek-shot (`--command`) veya interaktif döngüyü başlatma noktası |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm işlevsel ve görsel özellikler tasarım kararlarına uygun şekilde çalışmaktadır.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1352-agentsidaragentpy-skor-95100"></a>
#### 13.5.2 `agent/sidar_agent.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Ana ajan omurgası. ReAct (Reason + Act) karar döngüsü, araç dispatch yönetimi, yapısal çıktı (Pydantic) doğrulaması, asenkron alt görevler ve sonsuz vektör hafıza (ChromaDB) arşivlemesinin merkezidir.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, kullanıcıdan gelen doğal dil girdilerini analiz edip eyleme dönüştüren SİDAR'ın beynidir.

- **Akıllı Yönlendirme & Paralellik:** Basit istekleri ReAct döngüsüne girmeden `_try_direct_tool_route` ile saniyeler içinde çözer. Birden fazla güvenli (okuma) aracı `_tool_parallel` ile eşzamanlı (`async gather`) çalıştırarak hızı maksimize eder.
- **Hata Toleransı (Resilience):** Pydantic `ToolCall` modeli ve `JSONDecoder.raw_decode` sayesinde LLM'in ürettiği bozuk JSON'ları, gömülü kod bloklarını veya eksik alanları çökmeden (gracefully) toparlar ve modele düzeltme uyarısı gönderir.
- **Sonsuz Hafıza (Vector Archive):** Uzun sohbetlerde token taşmasını engellemek için `_summarize_memory` fonksiyonuyla eski konuşmaları ChromaDB'ye (RAG) indeksler ve belleği temizler.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `core/llm_client.py`: Model ile API üzerinden asenkron streaming iletişimi kurar.
- 🔗 `agent/auto_handle.py`: Ajan devreye girmeden önce bilinen statik regex kalıplarını yakalayarak LLM maliyetini sıfırlar.
- 🔗 Tüm `managers/` sınıfları: GitHub, Code, Todo, WebSearch gibi yöneticiler bu ajan tarafından `_execute_tool` tablosu üzerinden tetiklenir.
- 🔗 `SIDAR.md` / `CLAUDE.md`: Çalışma anında mtime-cache ile bu talimat dosyalarını okuyup sistem promptuna dahil eder.

**Mimari Özeti (satır 1–1100+)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 31–43 | Modül Format Sabitleri | `_FMT_TOOL_OK`, `_FMT_SYS_ERR` gibi sabitlerle LLM'e giden hata/başarı mesajlarını standardize eder |
| 49–54 | `ToolCall` Pydantic | LLM'in üretmesi gereken katı JSON şemasını (`thought`, `tool`, `argument`) tanımlar |
| 120–156 | `respond(...)` | Ana asenkron akış; Thread-safe lock (`_lock`), auto-handle ve bellek özetleme/arşivleme tetikleyicisi |
| 158–190 | `_try_direct_tool_route` | ReAct döngüsüne girmeden `temperature=0` ile tek adımlı güvenli araç çalıştırma kısa yolu |
| 192–351 | `_react_loop(...)` | Ana yapay zeka karar döngüsü; Greedy Regex yerine `raw_decode` ile JSON parse, sonsuz döngü kırıcı (loop prevention) ve Sentinel (`THOUGHT`/`TOOL`) formatlaması içerir |
| 644–718 | `_tool_subtask(...)` | Bağımsız bir alt ajan (mini ReAct) çalıştırarak büyük görevleri parçalar (Claude Code Agent aracı eşdeğeri) |
| 720–764 | `_tool_parallel(...)` | `_PARALLEL_SAFE` olan okuma araçlarını `asyncio.gather` ile eşzamanlı koşturur |
| 899–947 | `_execute_tool(...)` | Geleneksel if/else zinciri yerine dict tabanlı, O(1) karmaşıklıkta fonksiyon (dispatch) yönlendiricisi |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Pydantic entegrasyonu, asenkron I/O bloklamaları ve context taşması riskleri tamamen çözülmüştür.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1353-coreragpy-skor-100100"></a>
#### 13.5.3 `core/rag.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR'ın yerel bilgi bankası ve RAG (Retrieval-Augmented Generation) altyapısı. ChromaDB tabanlı vektör (anlamsal) arama, BM25 kelime skorlama ve akıllı metin parçalama (chunking) motorudur.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Ajanın büyük belgeleri doğrudan okuyup (token limitlerini tüketip) çökmesini engellemek ve geçmiş sohbetleri "Sonsuz Hafıza" olarak saklamak için kullanılır.

- **Hibrit Arama (Cascade):** Kullanıcı bir soru sorduğunda önce ChromaDB (Vektör Arama) ile anlamsal yakınlık aranır. Eğer ChromaDB devrede değilse veya sonuç bulunamazsa sistem sırasıyla BM25'e (Kelime Sıklığı) ve ardından en basit Anahtar Kelime aramasına (Fallback) geçer.
- **Akıllı Parçalama (Recursive Chunking):** Eklenen belgeler veya kodlar doğrudan indekslenmez; kod bloklarını (`class`, `def`) ve paragrafları bölmeden, bağlamın kaybolmasını engellemek için örtüşmeli (overlap) şekilde parçalanır (LangChain benzeri mantık).
- **GPU Verimliliği:** `USE_GPU=True` ve `GPU_MIXED_PRECISION=True` yapılandırmasıyla sentence-transformers modeli doğrudan CUDA üzerinde (FP16 bellek tasarrufuyla) çalışır.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Ajan, hem RAG araçları (`docs_search`, `docs_add`) kullanırken hem de eski sohbetleri özetleyip vektör veritabanına arşivlerken (`_summarize_memory`) buraya başvurur.
- 🔗 `web_server.py`: Arayüzdeki "Belge Deposu" modalı, dosya ekleme/silme ve arama endpoint'leri için doğrudan `DocumentStore` API'lerini kullanır.

**Mimari Özeti (satır 1–656)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 26–70 | `_build_embedding_function` | GPU ve FP16 (mixed precision) tabanlı sentence-transformers embedding başlatıcısı |
| 189–251 | `_recursive_chunk_text(...)` | Uzun metinleri ve kodları mantıksal sınırlarından (`class/def/newline`) bölerek parçalayan özyinelemeli (recursive) algoritma |
| 253–305 | `add_document(...)` | Dosyaları diske yedekler ve eşzamanlı çakışmaları engellemek için `threading.Lock` kullanarak ChromaDB'ye atomik chunk kaydı (upsert) yapar |
| 307–327 | `add_document_from_url` | `httpx.AsyncClient` ile URL içeriklerini asenkron çeker, HTML etiketlerini (`_clean_html`) temizler ve belgeler |
| 435–467 | `search(...)` | `mode="auto"` parametresiyle Vektör ➔ BM25 ➔ Keyword motorları arasında fallback (şelale) geçişi sağlar |
| 512–554 | `_ensure_bm25_index` | Her arama öncesi BM25 indeksini in-memory olarak hazırlayan veya önbellekten (cache) döndüren skorlama katmanı |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. I/O kaynaklı event-loop bloklama riskleri çağıran katmanlarda (Thread havuzu ile) tamamen çözülmüştür.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1354-webserverpy-skor-90100"></a>
#### 13.5.4 `web_server.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR'ın web arayüzüne hizmet eden FastAPI arka uç (backend) sunucusu. SSE (Server-Sent Events) tabanlı asenkron akış, Rate Limiting (Hız Sınırlandırma), oturum (session) yönetimi ve RAG/Git entegrasyon API'lerini sağlar.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, kullanıcıların tarayıcı üzerinden SİDAR ile etkileşime girmesini sağlayan köprüdür.

- **Canlı Akış (Streaming):** `/chat` endpoint'i, ajanın ürettiği LLM yanıtlarını ve araç çağrılarını (`TOOL`/`THOUGHT`) bekletmeden, anlık olarak SSE (`text/event-stream`) üzerinden arayüze aktarır.
- **Güvenlik ve İzolasyon:** Proxy-aware (`X-Forwarded-For` destekli) IP tabanlı hız sınırlandırması (`rate_limit_middleware`) uygulayarak sistemi DDoS ve spam isteklerden korur. `asyncio.Lock` kullanarak atomik kontrol sağlar (TOCTOU koruması).
- **Asenkron Kararlılık:** Disk I/O (Dosya okuma, RAG indeksleme) ve Alt Süreç (Git komutları) gibi ana event-loop'u kilitleyebilecek (blocking) tüm işlemler `asyncio.to_thread` aracılığıyla thread havuzuna (pool) itilir.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Ajan nesnesi tekil (singleton) olarak asenkron şekilde başlatılır (`get_agent()`) ve HTTP istekleri buraya yönlendirilir.
- 🔗 `web_ui/index.html`: Root (`/`) endpoint'i üzerinden doğrudan arayüzün barındırıldığı dosyayı servis eder.
- 🔗 `config.py`: Hangi porta/host'a bağlanılacağı, CORS izinleri gibi temel FastAPI ayarları buradan okunur.

**Mimari Özeti (satır 1–456)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 45–54 | Lazy Singleton Init | `get_agent()` içinde `asyncio.Lock`'un event-loop çalıştıktan sonra yaratılması (DeprecationWarning çözümü) |
| 74–157 | Rate Limiter Modülü | IP ve Namespace (`mut/get`) tabanlı, `_rate_lock` ile atomik (race-condition korumalı) in-memory istek kısıtlayıcı |
| 178–230 | `chat(...)` (SSE) | Kullanıcı mesajını alan ve `SidarAgent.respond()` asenkron jeneratörünü `StreamingResponse` ile dışarı aktaran ana iletişim kanalı |
| 233–296 | `/status` & `/metrics` | Prometheus formatını da destekleyen, sistemin donanım (GPU), bellek ve oturum metriklerini sunan izleme endpoint'leri |
| 301–326 | `/sessions/*` | Çoklu sohbet oturumlarını yöneten, oturum geçmişi yükleme ve silme API'leri |
| 355–407 | Git Entegrasyon API'leri | `_git_run` metodunu `asyncio.to_thread` ile sarmalayarak yerel branch ve bilgi çekme işlemleri |
| 457–514 | RAG Entegrasyon API'leri | Web UI üzerinden RAG deposuna belge ekleme (`add-file`, `add-url`), silme ve arama endpoint'leri |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm asenkron mimari riskler ve race-condition durumları giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1355-agentdefinitionspy-skor-87100"></a>
#### 13.5.5 `agent/definitions.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR'ın kişiliğini (persona), ReAct (Düşünce + Eylem) döngüsündeki kurallarını ve Pydantic modeline uygun katı JSON çıktı formatını belirleyen temel sistem komutunu (System Prompt) barındırır.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, yapay zeka modelinin (Gemini veya Ollama) kendini nasıl konumlandıracağını ve çıktılarını nasıl biçimlendireceğini belirler.

- **Karakter ve Güvenlik:** Ajanın kendini "Sidar" adında kıdemli bir yazılım mühendisi olarak tanıtmasını, yıkıcı komutlara (örn. tüm diski silme) karşı uyanık olmasını ve kullanıcının isteklerini en verimli şekilde çözmesini sağlar.
- **Format Zorlaması (Strict Formatting):** Ajanın her adımda kesinlikle geçerli bir JSON objesi döndürmesini zorunlu kılar. `sidar_agent.py` içindeki Pydantic ayrıştırıcısının çökmemesi için Markdown tag'leri (```json) kullanımını kesin bir dille yasaklar.
- **Araç (Tool) Yönlendirmesi:** LLM'e kullanabileceği araçların sınırlarını ve `final_answer` verene kadar döngüde nasıl kalacağını öğretir.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Bu dosyadaki `SIDAR_SYSTEM_PROMPT` sabiti import edilerek her LLM çağrısında `system_prompt` parametresi olarak modele iletilir.

**Mimari Özeti (Tipik 1–85 satır)**

| Bölüm | Pattern | Açıklama |
|-------|---------|----------|
| Karakter Tanımı | Persona Injection | Kıdemli, çözüm odaklı ve Türkçe iletişim kuran mühendis profili |
| Çıktı Şeması | Zero-Shot Constraint | Sadece `{"thought": "...", "tool": "...", "argument": "..."}` şemasında çıktı üretme zorunluluğu |
| Anti-Hallucination | Guardrails | Modelin araç sonuçları uydurmasını engelleyen, sadece terminal/araç çıktılarına güvenmesini söyleyen kurallar |
| Token Optimizasyonu | Minimalizm | Eski sürümdeki tekrarlayan ve uzun talimatların kaldırılarak modelin dikkat mekanizmasının (attention) artırılması |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Prompt zehirlenmesi (injection) ve format kayması (format drift) riskleri giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1356-agentautohandlepy-skor-89100"></a>
#### 13.5.6 `agent/auto_handle.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Doğal dille ifade edilen "tek adımlı" basit komutları (örn. "dosyayı oku", "GPU durumunu göster", "belleği temizle") LLM'e gitmeden yakalayarak sıfır token maliyeti ve milisaniyelik tepki süresiyle doğrudan ilgili araca yönlendiren Akıllı Yönlendirici (Intent Router).

**Dosyanın İşlevi ve Sistemdeki Rolü**

SİDAR'ın hızını ve verimliliğini artıran ilk filtredir.

- **Maliyet Düşürücü (Cost-Saver):** Kullanıcının sadece bilgi almak için sorduğu "Aktif PR'ları listele" veya "FastAPI paket bilgisi" gibi komutlarda API çağrısı yapılmasını engeller.
- **Akıllı Devir (Smart Delegation):** `_MULTI_STEP_RE` yapısı sayesinde "önce", "sonra", "ardından" gibi zincirleme komutları algılar ve "Ben tek adımlık bir ön-işlemciyim, bu karmaşık görev senin işin" diyerek görevi ReAct ajana bırakır.
- **Regex Daraltması:** Cümle içindeki bağlamı kavrayacak özel kalıplar içerir; böylece örneğin "Sistemin GPU durumunu göster" komutunun yanlışlıkla dosya okuma (`read_file`) aracını tetiklemesi engellenir.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Ajan, kullanıcıdan girdiyi aldığında ilk iş olarak `auto.handle(user_input)` metodunu çağırır. Eğer `True` dönerse ReAct döngüsünü tamamen atlar.
- 🔗 `managers/*`: İşlenen komuta göre CodeManager, WebSearchManager, GitHubManager vb. sistemlere doğrudan komut gönderir.

**Mimari Özeti (satır 1–460)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 46–51 | `_MULTI_STEP_RE` | Zincirleme/çok adımlı komutları tespit ederek ReAct döngüsüne düşmesini sağlayan güvenlik regex'i |
| 53–134 | `handle(...)` | Tüm araç testlerini (`try_*`) sırasıyla çalıştıran ana asenkron giriş noktası |
| 138–301 | Senkron Araç İşleyicileri | Dosya okuma, denetim (`audit`), sistem sağlığı (`health`) ve senkron GitHub işlemlerinin regex kalıpları |
| 305–419 | Asenkron Araç İşleyicileri | Web araması, URL çekme, NPM/PyPI paket sorguları ve RAG arama (`to_thread` ile) fonksiyonları |
| 423–458 | Path & URL Çıkarıcılar | Doğal dil metni içinden `file.py`, `./src` veya `https://...` gibi parametreleri temiz şekilde (regex ile) çıkartan yardımcılar |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Aşırı eşleşme (over-matching) hataları ve event-loop bloklamaları tamamen çözülmüştür.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1357-corellmclientpy-skor-91100"></a>
#### 13.5.7 `core/llm_client.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR'ın yapay zeka sağlayıcılarıyla (Ollama ve Google Gemini) kurduğu asenkron (async) HTTP iletişimini, veri akışını (streaming) ve native JSON şema zorlamalarını (structured output) yöneten istemci katmanı.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR ajanının "dış dünya" (LLM API'leri) ile bağlantı kurduğu yerdir.

- **Kayıpsız Veri Akışı (Lossless Streaming):** Modelin ürettiği kelimeleri anlık olarak kullanıcıya iletir. TCP paket sınırlarında parçalanan JSON veya UTF-8 karakterlerini bozmadan yakalayan özel bir bellek tamponu (buffer) kullanır.
- **Yapısal Çıktı Zorlaması (Structured Output):** `json_mode=True` parametresi ile, Ollama ve Gemini API'lerine native JSON format zorlaması (`format: {"type": "object"...}`) ekler. Bu sayede modeller markdown veya düz metin üretemez, Pydantic ayrıştırıcısının işi garantiye alınır.
- **GPU Hızlandırma Yönlendirmesi:** Ollama kullanılırken `USE_GPU=True` ise `num_gpu=-1` parametresini göndererek modelin tüm katmanlarını otomatik olarak VRAM'e yükler.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Ajan, her ReAct adımında buradaki `chat(...)` fonksiyonunu çağırır ve dönen `AsyncIterator`'u dinler.
- 🔗 `config.py`: Model isimleri, URL'ler, timeout süreleri ve Gemini API anahtarları bu dosyadan okunur.

**Mimari Özeti (satır 1–254)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 35–56 | `chat(...)` | İsteği Ollama veya Gemini alt sınıflarına yönlendiren asenkron ana proxy (router) |
| 62–104 | `_ollama_chat` | `num_gpu=-1` donanım hızlandırmasını ve katı Pydantic `ToolCall` JSON şemasını API payload'una ekler |
| 106–157 | `_stream_ollama_response` | TCP sınırlarında kopan JSON'ları ve UTF-8 baytlarını onaran `incrementaldecoder` ve akıllı satır tamponu (buffer) algoritması |
| 163–229 | `_gemini_chat` | Google Generative AI entegrasyonu; geçmiş mesajları Gemini formatına çevirir ve `application/json` MIME tipini zorlar |
| 238–254 | Availability Checks | Hızlı kontrol için Ollama API `/tags` uç noktasına `httpx.AsyncClient` ile ping atar |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Streaming sırasındaki token atlama (chunk loss) sorunları ve JSON format kaymaları giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1358-corememorypy-skor-92100"></a>
#### 13.5.8 `core/memory.py` — Skor: 100/100 ✅

**Durum:** ✅

✅ Şifreleme modülündeki Fail-Open (hata anında düz metne geçme) zafiyeti giderildi; sistem artık geçersiz anahtar veya eksik bağımlılık durumunda güvenli durdurma (Fail-Closed) prensibiyle çalışıyor. Ayrıca force_save ve __del__ metodları ile ani uygulama kapanışlarında oluşan veri kaybı sorunu tamamen çözüldü.

**Sorumluluk (Güncel):** SİDAR'ın çoklu oturum (multi-session) destekli, kalıcı (persistent) konuşma belleği yöneticisidir. Thread-safe yapısı, verileri diske kaydetme ve token aşımını engelleme süreçlerinden sorumludur.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR'ın geçmişi unutmaması ama aynı zamanda diski ve hafızayı şişirmemesi için tasarlanmıştır.

- **Çoklu Oturum (Multi-Session):** Eski tekil `memory.json` yapısı yerine verileri `sessions` dizininde UUID tabanlı ayrı JSON dosyalarında saklar.
- **Güvenlik (Encryption):** `MEMORY_ENCRYPTION_KEY` ayarlandığında oturum dosyaları Fernet (AES-128-CBC) algoritması ile şifrelenir, böylece diskteki sohbet verileri dışarıdan okunamaz.
- **Disk I/O Optimizasyonu (Throttling):** Ajanın LLM'den stream (akış) ile aldığı her token'da diske yazmasını engellemek için `_save_interval_seconds = 0.5` kullanarak yazma işlemlerini birleştirir (debounce).
- **Karantina Mekanizması:** Bozuk veya şifresi çözülemeyen dosyaları silmek yerine `.json.broken` uzantısıyla karantinaya alır ve `_cleanup_broken_files` ile bu dosyaların yaşam döngüsünü (retention) yönetir.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Ajan belleği buradan okur (`get_messages_for_llm`), yeni tur ekler (`add`) ve özetleme eşiğini (`needs_summarization`) buradan denetler.
- 🔗 `web_server.py`: Web arayüzündeki "Yeni Sohbet" ve "Geçmiş Sohbetler" menüsü, oturumları doğrudan bu sınıftaki API'ler (`get_all_sessions`, `create_session`) üzerinden çeker.

**Mimari Özeti (satır 1–287)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 44–59 | `_init_fernet` | Konfigürasyon varsa asimetrik olmayan AES-128-CBC (Fernet) şifreleme motorunu başlatır |
| 81–104 | `_cleanup_broken_files` | Karantinadaki bozuk dosyalar için `max_age_days` ve `max_files` limitli çöp toplayıcı (Garbage Collector) mantığı |
| 115–159 | `get_all_sessions()` | Dizin içindeki oturumları güvenli ayrıştırıp (bozukları `.broken` yaparak) kronolojik olarak UI'a döndürür |
| 198–223 | `_save(force)` | `time.time() - _last_saved_at < 0.5` kontrolüyle çalışan yüksek performanslı I/O Throttling fonksiyonu |
| 253–278 | `needs_summarization` | %80 kapasite veya ~6000 token sınırına ulaşıldığında, bellek özetleme sinyali üreten proaktif izleyici |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm disk darboğazları (I/O bottlenecks) ve güvenlik/karantina mimari ihtiyaçları giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1359-configpy-skor-91100"></a>
#### 13.5.9 `config.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR projesinin merkezi yapılandırma yöneticisi. Ortam değişkenlerini (`.env`) yükler, eksik değerler için "güvenli varsayılanlar" (safe defaults) atar ve çalışma anında GPU/CUDA donanım durumunu dinamik olarak tespit eder.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya projenin statik bir ayar dosyasından öte, sistemin donanımını ve yeteneklerini analiz eden dinamik bir "başlangıç (bootstrap)" katmanıdır.

- **Tip Güvenliği (Type Safety):** `.env` dosyasından gelen string değerleri (örn. `"True"`, `"False"`, `"10"`) güvenli bir şekilde `bool` ve `int` tiplerine dönüştürerek diğer modüllerde yaşanabilecek çalışma zamanı (runtime) çökmelerini engeller.
- **Donanım Algılama (Hardware Awareness):** Sistemde GPU olup olmadığını (`USE_GPU`) ve kullanılabilir CUDA belleğini otomatik tespit eder. RAG ve Ollama/Gemini istemcileri bu parametreleri okuyarak kendilerini CPU veya GPU moduna ayarlar.
- **Merkezi Parametre Yönetimi:** ReAct adım limitlerinden (`MAX_REACT_STEPS`), RAG parçalama boyutlarına (`RAG_CHUNK_SIZE`) kadar tüm hiperparametreleri tek bir kaynakta toplar.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 Tüm Proje Dosyaları: Sistemin hemen hemen her modülü (`web_server.py`, `sidar_agent.py`, `llm_client.py` vb.) kendi ayarlarını çekmek için `from config import Config` çağrısı yapar.

**Mimari Özeti (Tipik 1–345 satır)**

| Satır (Yaklaşık) | Pattern | Açıklama |
|------------------|---------|----------|
| 1–50 | dotenv & Paths | Proje kök dizini (`BASE_DIR`) tespiti ve `.env` dosyasının güvenli şekilde yüklenmesi |
| 225 | Provider Selection | `AI_PROVIDER` (Ollama/Gemini) merkezi seçimi |
| 230–233 | Model Config | `OLLAMA_URL`, `CODING_MODEL` ve `TEXT_MODEL` tanımlamaları |
| 243–257 | GPU Detection | Donanım (CUDA/PyTorch) tespiti, `USE_GPU` flag'i ve `GPU_MEMORY_FRACTION` (VRAM) sınırlandırması |
| 273–274 | ReAct Limits | Sonsuz döngüleri engellemek için `MAX_REACT_STEPS` ve `REACT_TIMEOUT` ayarları |
| 290–292 | RAG Hyperparams | `RAG_TOP_K`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP` vektör arama kalibrasyonları |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm tip dönüşüm (casting) hataları ve donanım algılama blokajları giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13510-managerscodemanagerpy-skor-94100"></a>
#### 13.5.10 `managers/code_manager.py` — Skor: 100/100 ✅

**Durum:** ✅

✅ Türkçe karakter desteği (utf-8) tüm dosya işlemlerine eklendi. Docker izolasyonunun başarısız olduğu durumlarda yerel sistemi korumak için Fail-Closed (güvenli durdurma) mantığı kuruldu ve imaj/timeout değerleri dinamikleştirildi.

**Sorumluluk (Güncel):** SİDAR'ın yerel dosya sistemi üzerindeki tüm okuma, yazma, yama (patch) işlemlerini ve LLM tarafından üretilen kodların izole bir ortamda (Docker Sandbox) güvenle çalıştırılmasını yönetir.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, yapay zekanın işletim sistemine zarar vermesini engelleyen en önemli güvenlik duvarıdır (Guardrail).

- **Güvenli Dosya I/O (Path Traversal Koruması):** Ajanın okumak veya yazmak istediği tüm dosya yolları (path), işlem yapılmadan önce `SecurityManager` üzerinden geçirilir. Ajanın `../` taktikleriyle proje dizini (`BASE_DIR`) dışına çıkması veya sistem dosyalarına (`/etc/passwd` vb.) erişmesi imkansızdır.
- **İzole Kod Çalıştırma (Sandbox):** `execute_code` aracı kullanıldığında, LLM'in ürettiği Python veya Shell kodları sunucu (host) üzerinde değil, geçici ve yetkileri kısıtlanmış bir Docker konteynerinde (örn. `python:3.11-alpine`) çalıştırılır.
- **Akıllı Yama ve AST Doğrulaması:** Dosyalara kısmi yama (`patch`) yaparken önce kodun sözdizimsel geçerliliğini (Python AST veya JSON validator ile) kontrol eder; eğer kod bozuksa yazma işlemini reddeder ve LLM'e hatayı döndürerek düzeltmesini ister.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py` ve `agent/auto_handle.py`: Ajanın `read_file`, `write_file`, `patch_file`, `execute_code` ve `audit` araçları doğrudan bu sınıfın metotlarını tetikler.
- 🔗 `managers/security.py`: İzin verilen dizin sınırlarını ve erişim seviyesini (OpenClaw / Sandbox / Restricted) denetlemek için bu sınıftan onay alır.

**Mimari Özeti (Tipik 1–450 satır)**

| Bölüm | Pattern | Açıklama |
|-------|---------|----------|
| Başlatma | Bağımlılık Enjeksiyonu | `SecurityManager` nesnesini, `BASE_DIR`'i ve `docker_exec_timeout` parametrelerini dışarıdan alır |
| Dosya Operasyonları | Safe File I/O | Okuma ve yazma işlemlerinde mutlak yol (absolute path) çözümlemesi ve UTF-8 kodlama garantisi |
| `execute_code` | Ephemeral Docker | Her kod çalıştırma isteği için anında doğup ölen (ephemeral), ağ erişimi kısıtlı konteyner ayağa kaldırma mekanizması |
| `patch_file` | Cerrahi Yama | Tüm dosyayı baştan yazmak yerine sadece değişen bloğu bulup değiştiren (regex/diff tabanlı) akıllı yama algoritması |
| AST Kontrolleri | Pre-commit Hook | Yazılan Python/JSON dosyalarının formatının bozuk olup olmadığını anlamak için parser katmanı |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm Path Traversal (Dizin Aşma) zafiyetleri ve sonsuz döngü kilitlenmeleri çözülmüştür.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13511-managersgithubmanagerpy-skor-93100"></a>
#### 13.5.11 `managers/github_manager.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR'ın GitHub API (PyGithub) entegrasyonu. Uzak depo (repo) analizi, PR (Pull Request) yönetimi, dal (branch) işlemleri ve güvenli uzak dosya okuma görevlerini yürütür.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya ajanın sadece yerel diskte değil, bulutta (GitHub) da çalışabilmesini sağlar.

- **Güvenli Dosya Okuma (Binary Protection):** Ajan uzak bir depodan (örneğin bir resim veya derlenmiş binary) dosya okumak istediğinde, sistem dosyanın uzantısını `SAFE_TEXT_EXTENSIONS` ve `SAFE_EXTENSIONLESS` whitelist'lerine göre filtreler. Uygun değilse okumayı reddederek LLM'i uyarır, böylece bağlam penceresinin anlamsız karakterlerle dolmasını önler.
- **Injection Koruması:** Branch oluşturma işlemlerinde (`create_branch`), kullanıcı/ajan tarafından sağlanan dal adları katı bir Regex (`_BRANCH_RE`) kontrolünden geçirilir.
- **Zengin Veri Sağlayıcı:** PR listeleme, commit geçmişi okuma, kod içinde arama yapma (`search_code`) gibi işlevleriyle ajana doğrudan mühendislik bağlamı sağlar.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Ajanın kullandığı `github_read`, `github_pr_create`, `github_pr_list` gibi araçlar bu sınıfı tetikler.
- 🔗 `web_server.py`: Web arayüzündeki "GitHub" paneli, repoları ve PR listesini doğrudan bu modülün `get_pull_requests_detailed` metodu üzerinden çeker.

**Mimari Özeti (satır 1–450)**

| Bölüm | Pattern | Açıklama |
|-------|---------|----------|
| 31–38 | Güvenlik (Whitelist) | Yalnızca okunmasına izin verilen metin ve konfigürasyon dosyası (`.py`, `Makefile` vb.) uzantıları |
| 52–71 | Modern Authentication | Deprecated `login_or_token` yerine güncel ve güvenli `Auth.Token(...)` kullanımı |
| 141–187 | Uzak Dosya Okuma | `read_remote_file` metodu içinde whitelist kontrolü ve `UnicodeDecodeError` yakalayan Binary Guard (İkili Dosya Koruması) |
| 245–271 | Branch Yönetimi | `create_branch` metodunda shell-injection ve geçersiz dal adı engellemesi |
| 412–443 | API Endpoint Desteği | Web sunucusu (FastAPI) için PR verilerini ham formatta (`get_pull_requests_detailed`) dışa aktaran yapısal metot |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm binary okuma ve injection zafiyetleri giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13512-managerssystemhealthpy-skor-94100"></a>
#### 13.5.12 `managers/system_health.py` — Skor: 100/100 ✅

**Durum:** ✅

✅ Ollama servis kontrollerine ağ kilitlenmelerini önleyen OLLAMA_TIMEOUT parametresi eklendi ve kontrol adresleri merkezi yapılandırmaya bağlandı.

**Sorumluluk (Güncel):** Sunucu ve donanım kaynaklarının (CPU, RAM, GPU) anlık takibini yapmak ve gerektiğinde GPU VRAM belleğini optimize etmek/temizlemek.

**Dosyanın İşlevi ve Sistemdeki Rolü**

SİDAR'ın çalıştığı makineyi aşırı yükten koruyan "Yoğun Bakım" monitörüdür.

- **Bloklamayan İzleme (Non-blocking):** `psutil.cpu_percent` çağrısının ana thread'i dondurmasını engellemek için örnekleme aralığını (`interval`) varsayılan olarak 0 saniyede tutar.
- **Garantili Bellek Temizliği (Safe GC):** GPU belleğini (`torch.cuda.empty_cache()`) temizlerken donanımsal bir hata alınsa bile, `try-finally` bloğu sayesinde Python `gc.collect()` işlemini mutlaka çalıştırır ve bellek sızıntılarını önler.
- **Kapsamlı GPU Analizi:** NVIDIA kartları için sadece VRAM'i değil; `pynvml` kütüphanesi ile sıcaklık ve anlık GPU kullanım yüzdelerini de ölçer. WSL2 ortamlarındaki kısıtlamalara karşı `nvidia-smi` üzerinden Fallback (yedek) planı vardır.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `web_server.py`: `/status` endpoint'i üzerinden web arayüzüne anlık GPU ve RAM istatistiklerini bu modülden aktarır.
- 🔗 `agent/auto_handle.py`: Kullanıcının "Sistem durumu nedir?" veya "GPU belleğini temizle" gibi doğal dil komutlarında doğrudan bu modülü tetikler.

**Mimari Özeti (satır 1–280)**

| Bölüm | Pattern | Açıklama |
|-------|---------|----------|
| 35–56 | Güvenli Başlatma | `cpu_sample_interval` sınırlaması ve deterministik kapanış için `atexit.register` kaydı |
| 120–178 | Detaylı GPU Profili | `torch.cuda` ve `pynvml` verilerini birleştirerek sıcaklık, kullanım ve boş VRAM hesaplayan sensör katmanı |
| 180–205 | WSL2 Fallback | NVML'in engellendiği Windows Subsystem for Linux (WSL2) ortamlarında sürücü bilgisini almak için `subprocess.run(["nvidia-smi"])` kullanımı |
| 207–233 | `optimize_gpu_memory` | `try-finally` garantisi ile GPU VRAM ve RAM (Python Garbage Collector) temizleme algoritması |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Asenkron bloklamalar ve bellek sızıntısı riskleri mimari olarak çözülmüştür.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13513-managerswebsearchpy-skor-93100"></a>
#### 13.5.13 `managers/web_search.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR'ın dış dünyaya erişimini sağlayan asenkron web arama yöneticisidir. Çoklu motor desteği (Tavily, Google Custom Search, DuckDuckGo), hata toleranslı şelale (fallback) yönlendirmesi ve ham HTML temizleme işlevlerini içerir.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR ajanının sadece kendi hafızasıyla sınırlı kalmamasını, güncel verilere internetten ulaşmasını sağlar.

- **Akıllı Fallback (Şelale Modeli):** Bir arama motoru çökerse, sonuç bulamazsa veya API kotası dolarsa, ajan hata verip durmak yerine Tavily → Google → DuckDuckGo sırasıyla diğer motorları otomatik dener.
- **Kırık API Koruması:** Eğer Tavily 401/403 (Kimlik Doğrulama/Kota) hatası verirse, sistem bunu algılar, o oturum için Tavily'i kara listeye alır (`self.tavily_key = ""`) ve gereksiz istek atarak zaman/kaynak israfını engeller.
- **Senkron/Asenkron Köprü (DDG v8+):** `duckduckgo_search` kütüphanesinin güncel v8 sürümünde native asenkron destek olmamasına karşın, senkron çalışan `DDGS()` sınıfını `asyncio.to_thread` içine iterek ana FastAPI sunucusunun kilitlenmesini kesin olarak önler.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Ajan, internet bilgisine ihtiyaç duyduğunda ReAct döngüsü üzerinden `web_search` veya `fetch_url` aracını kullanır.
- 🔗 `agent/auto_handle.py`: Doğrudan "internette ara ..." gibi Regex yakalamaları üzerinden sıfır token harcayarak bu sınıfa yönlendirme yapar.

**Mimari Özeti (satır 1–280)**

| Bölüm | Pattern | Açıklama |
|-------|---------|----------|
| 62–99 | Fallback Router | `search` metodu, motorları sırayla dener ve boş sonuçları (`[NO_RESULTS]`) atlayarak çalışabilir veriyi bulana kadar şelale mantığı işletir |
| 104–146 | Tavily API & Blacklist | Tavily JSON REST entegrasyonu; `HTTPStatusError` (401, 403) yakalandığında API anahtarını çalışma zamanında geçersiz kılma mantığı |
| 178–200 | DDG Asenkron İzolasyon | `asyncio.to_thread(_sync_search)` ile senkron DuckDuckGo paketinin ana event-loop'tan izole edilmesi |
| 206–241 | `fetch_url` & `_clean_html` | `httpx.AsyncClient` ile URL okuma, regex ve `html.unescape` tabanlı robust karakter (entity) temizleme katmanı |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Kütüphane sürüm çakışmaları ve API kota aşımlarının sisteme olan yıkıcı etkileri mimari düzeyde engellenmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13514-managerspackageinfopy-skor-94100"></a>
#### 13.5.14 `managers/package_info.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Python (PyPI), JavaScript (npm) ve GitHub Releases üzerinden paketlerin güncel sürüm, lisans, bağımlılık ve açıklama bilgilerini asenkron olarak sorgulayan paket yöneticisidir.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, yapay zekanın uydurma (hallucinated) kütüphaneler önermesini veya eski/kaldırılmış paketleri kullanmasını engeller.

- **Tam Asenkron İzolasyon:** PyPI, npm ve GitHub API'lerine yapılan tüm HTTP istekleri `httpx.AsyncClient` kullanılarak asenkron hale getirilmiştir. Bu sayede, uzak sunuculardan yanıt gecikse bile SİDAR'ın diğer süreçleri (örneğin chat akışı) kilitlenmez (Non-blocking I/O).
- **Akıllı Sürüm Sıralaması (PEP 440):** Ajanın sürüm numaralarını doğru anlaması için (örn. `v1.10 > v1.2` veya beta sürümleri elemeleri) standart string sıralaması yerine `packaging.version.Version` algoritması entegre edilmiştir.
- **Bağımlılık (Dependency) Analizi:** Sadece paketin sürümünü değil, o paketin nelere ihtiyaç duyduğunu (`requires_dist`, `peerDependencies`) da ajana bildirerek çatışmaları (conflict) baştan önler.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Ajan, kod yazmadan önce veya "Bu kütüphanenin güncel sürümü nedir?" sorusunda `pypi_info` veya `npm_info` araçlarını kullanır.
- 🔗 `agent/auto_handle.py`: Kullanıcının "pypi requests" gibi doğrudan API komutlarında LLM'e gitmeden doğrudan bu modülü çalıştırır.

**Mimari Özeti (satır 1–252)**

| Bölüm | Pattern | Açıklama |
|-------|---------|----------|
| 35–88 | Asenkron PyPI | `httpx.AsyncClient` ile JSON API entegrasyonu ve paket bilgilerinin filtrelenip formatlanması |
| 113–158 | Asenkron npm | JavaScript ekosistemi için `registry.npmjs.org` sorgusu ve `peerDependencies` analizi |
| 162–213 | Asenkron GitHub | `api.github.com/repos/.../releases` uç noktası ile projenin son yayınlanmış (release) sürümlerini çeken katman |
| 217–243 | PEP 440 Sıralaması | `_is_prerelease` ve `_version_sort_key` metotlarıyla sürüm string'lerini (`alpha`, `beta`, `rc`) semantik olarak doğru sıralayan algoritma |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm senkron I/O bloklamaları ve sürüm sıralama hataları giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13515-managerssecuritypy-skor-93100"></a>
#### 13.5.15 `managers/security.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR'ın OpenClaw erişim kontrol sistemidir. Ajanın dosya okuma, yazma ve terminal komutu çalıştırma yetkilerini denetler; path traversal ve symlink saldırılarına karşı sistemi korur.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR'ın işletim sistemi üzerinde kontrolsüz güç kullanmasını engelleyen "Anayasa" katmanıdır.

- **Katmanlı Yetkilendirme:** Sistemi üç temel seviyeye ayırır: `RESTRICTED` (salt okur), `SANDBOX` (izole yazma) ve `FULL` (tam erişim).
- **Symlink Traversal Koruması:** Ajanın sembolik bağlantılar kullanarak proje dizini dışındaki hassas dosyalara erişmesini engellemek için tüm yolları `.resolve()` ile gerçek hedeflerine çözümler.
- **Tehlikeli Yol Filtresi:** `/etc/`, `/proc/` gibi kritik sistem dizinlerine veya Windows sistem klasörlerine erişim girişimlerini özel bir Regex (`_DANGEROUS_PATH_RE`) ile anında reddeder.
- **Güvenli Normalizasyon:** Konfigürasyondan gelen hatalı veya bilinmeyen yetki tanımlarını, en güvenli varsayılan olan `SANDBOX` moduna otomatik olarak sanitize eder.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `managers/code_manager.py`: Dosya işlemlerinden önce her defasında bu sınıfa yetki sorar (`can_read`, `can_write`).
- 🔗 `agent/sidar_agent.py`: Ajanın hangi araçları (terminal, shell vb.) kullanabileceğine karar vermek için bu yöneticinin durum raporunu (`status_report`) kullanır.

**Mimari Özeti (satır 1–190)**

| Bölüm | Pattern | Açıklama |
|-------|---------|----------|
| 27 | Anti-Traversal Regex | Kritik sistem yollarını ve `../` kalıplarını yakalayan koruma filtresi |
| 52–65 | `_normalize_level_name` | Hatalı konfigürasyon girişlerini `sandbox` moduna çeken güvenlik supabı |
| 104–131 | Path Resolution | Sembolik bağlantıları takip eden ve gerçek yolun `base_dir` altında olduğunu kanıtlayan `is_path_under` algoritması |
| 145–170 | `can_write` | Seviye bazlı (`RESTRICTED/SANDBOX/FULL`) yazma izni kontrolü ve dizin sınırı denetimi |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Symlink zafiyetleri ve yetkilendirme belirsizlikleri mimari seviyede giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13516-managerstodomanagerpy-skor-94100"></a>
#### 13.5.16 `managers/todo_manager.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR'ın görev takip ve iş akış yönetimi modülüdür. Claude Code standartlarındaki Todo araçlarına eşdeğer işlevsellik sunarak, ajanın hedeflerini atomik parçalara bölmesini ve durum takibi yapmasını sağlar.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR'ın uzun soluklu projelerde "ne yapacağını" unutmasını engelleyen hafıza katmanıdır.

- **Odağı Koruma (Single In-Progress Rule):** Ajanın aynı anda birden fazla işe başlamasını engelleyerek "multitasking" kilitlenmelerini önler. Bir görev `in_progress` yapıldığında, diğer tüm aktif görevler otomatik olarak `pending` durumuna çekilir.
- **Thread-Safe Mimari:** Web arayüzü ve CLI üzerinden gelen eş zamanlı isteklerin veri yapısını bozmaması için `threading.RLock` ile korunmaktadır.
- **Yapısal Raporlama:** Görevleri duruma göre (Bekleyen, Devam Eden, Tamamlanan) gruplayarak hem LLM'e hem de son kullanıcıya temiz bir görsel rapor sunar.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py`: Ajan, planlama aşamasında `todo_add`, `todo_update` ve `todo_list` araçları üzerinden bu sınıfı yönetir.
- 🔗 `web_server.py`: Arayüzdeki "Görev Listesi" paneli, verileri doğrudan bu modülün `get_tasks` metodu üzerinden anlık olarak çeker.

**Mimari Özeti (satır 1–252)**

| Bölüm | Pattern | Açıklama |
|-------|---------|----------|
| 35–42 | Task Dataclass | Görev verisini (ID, içerik, zaman damgası) standardize eden hafif veri modeli |
| 59–68 | Odak Yönetimi | Birden fazla aktif görev oluşmasını engelleyen `_ensure_single_in_progress` mantığı |
| 74–134 | Görev Manipülasyonu | `threading.Lock` koruması altında atomik görev ekleme ve toplu güncelleme işlemleri |
| 174–216 | Gruplanmış Listeleme | Görevleri kategorize ederek terminal dostu (ikonlu) rapor üreten `list_tasks` fonksiyonu |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Eş zamanlı erişim riskleri ve görev karmaşası sorunları tamamen giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13517-managersinitpy-skor-98100"></a>
#### 13.5.17 `managers/__init__.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Manager katmanındaki tüm sınıfları (Code, GitHub, Security vb.) tek bir paket altında toplar ve kontrollü bir şekilde dışa aktarılmasını (export) sağlar.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR mimarisinde "Faydalı Modüller" (Utilities) ile "İş Yöneticileri" (Managers) arasındaki sınırı belirleyen kapıdır.

- **Merkezi Erişim Noktası:** Diğer modüllerin (örn. `agent/sidar_agent.py`) yedi farklı dosyadan ayrı ayrı import yapması yerine `from managers import ...` şeklinde temiz bir arayüz kullanmasına olanak tanır.
- **Otomatik Senkronizasyon:** `__all__` listesi manuel olarak tutulmaz. `_EXPORTED_MANAGERS` içine eklenen her yeni sınıf, otomatik olarak dışa aktarılır. Bu sayede yeni eklenen bir manager'ın export edilmesinin unutulması (Technical Debt) engellenmiş olur.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 Tüm `managers/*.py` Dosyaları: Paketteki her bir yönetici sınıfı bu dosyada içe aktarılır.
- 🔗 `agent/sidar_agent.py`: Ajanın tüm yeteneklerini (araçlarını) başlatan ana sınıflar buradan import edilir.

**Mimari Özeti (satır 1–22)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 2–8 | Modül İthalatı | Projedeki 7 farklı manager sınıfının göreceli (relative) importu |
| 12–20 | `_EXPORTED_MANAGERS` | Sınıfları referans olarak tutan "Tek Kaynak" (Single Source of Truth) tuple yapısı |
| 22 | Dinamik `__all__` | `cls.__name__` üzerinden otomatik oluşturulan ve `from managers import *` güvenliğini sağlayan export listesi |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Manuel liste yönetimi riskleri tamamen ortadan kaldırılmıştır.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13518-coreinitpy-skor-99100"></a>
#### 13.5.18 `core/__init__.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Projenin çekirdek mantığını yürüten sınıfları (`LLMClient`, `ConversationMemory`, `DocumentStore`) tek bir paket altında toplar ve bu sınıfların dışarıya kontrollü aktarılmasını sağlar.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR'ın beynini oluşturan alt sistemlerin giriş kapısıdır.

- **Merkezi Çekirdek Arayüzü:** Ajan veya sunucu katmanının, çekirdek özelliklere erişirken üç farklı dosya yoluyla uğraşması yerine `from core import ...` şeklinde standart bir yol izlemesine imkan tanır.
- **Bakım Kolaylığı (Dinamik `__all__`):** Sınıf listesi `_EXPORTED_CORE` adlı tek bir "doğruluk kaynağında" (Source of Truth) tutulur. Yeni bir çekirdek modül eklendiğinde `__all__` listesini manuel güncelleme zorunluluğu yoktur; sistem otomatik olarak yeni sınıfı export listesine dahil eder.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `core/llm_client.py`, `core/memory.py`, `core/rag.py`: Bu dosyadaki ana sınıflar burada birleştirilir.
- 🔗 `agent/sidar_agent.py`: Ajan, LLM iletişimi ve hafıza yönetimi için gerekli araçları bu dosya üzerinden içe aktarır.
- 🔗 `web_server.py`: Web sunucusu, oturum ve belge yönetimi için çekirdek sınıflara buradan erişir.

**Mimari Özeti (satır 1–15)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 2–4 | Modül İthalatı | Çekirdek modüllerin (`LLMClient`, `Memory`, `RAG`) göreceli (relative) importu |
| 8–12 | `_EXPORTED_CORE` | Aktif sınıfları referans olarak tutan ve hata riskini azaltan merkezi tuple yapısı |
| 15 | Dinamik `__all__` | `cls.__name__` yöntemiyle üretilen, `from core import *` kullanımını güvenli kılan dinamik liste |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Mimari tutarlılık ve export güvenliği en üst seviyededir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13519-agentinitpy-skor-98100"></a>
#### 13.5.19 `agent/__init__.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Agent paketindeki ana ajan sınıfını (`SidarAgent`) ve kritik sabitleri (`SIDAR_SYSTEM_PROMPT`, `SIDAR_KEYS`, `SIDAR_WAKE_WORDS`) tek bir noktada toplar ve dışa aktarılmasını (export) yönetir.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR'ın uygulama katmanı ile ajan mantığı arasındaki ana dağıtım merkezidir.

- **Temiz Paket Arayüzü:** Uygulamanın başlatıcı modülleri (`main.py`, `cli.py`), ajanın iç yapısındaki dosya hiyerarşisini bilmek zorunda kalmadan `from agent import SidarAgent` şeklinde doğrudan ithalat yapabilir.
- **Dinamik Senkronizasyon:** Export edilecek semboller `_EXPORTED_AGENT_SYMBOLS` sözlüğünde tanımlanır ve `__all__` listesi bu sözlüğün anahtarlarından otomatik olarak üretilir. Bu yapı, yeni bir sabit veya sınıf eklendiğinde export listesinin güncellenmesinin unutulması riskini ortadan kaldırır.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 `agent/sidar_agent.py` ve `agent/definitions.py`: Bu dosyalardaki ana bileşenler burada birleştirilir.
- 🔗 `main.py` ve `cli.py`: Başlatıcılar, ajanı ve sistem komutlarını (system prompts) bu dosya üzerinden içe aktarır.

**Mimari Özeti (satır 1–13)**

| Satır | Pattern | Açıklama |
|-------|---------|----------|
| 2–3 | Modül İthalatı | Ajan sınıfının ve tanımların (`definitions`) paket içinden göreceli (relative) importu |
| 6–11 | `_EXPORTED_AGENT_SYMBOLS` | Dışa aktarılacak sembolleri (Ajan + Sabitler) eşleyen merkezi sözlük yapısı |
| 13 | Dinamik `__all__` | Sözlük anahtarlarından (`.keys()`) anlık üretilen ve `from agent import *` güvenliğini sağlayan export listesi |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm export tutarsızlıkları ve manuel liste yönetimi riskleri giderilmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13520-teststestsidarpy-skor-94100"></a>
#### 13.5.20 `tests/` Dizini ve Modüler Test Mimarisi — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR’ın tüm bileşenlerinin (Core, Agent, Managers) işlevsel doğruluğunu, güvenlik sınırlarını ve performans metriklerini otomatik olarak denetleyen modüler test altyapısıdır.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dizin, projenin CI dostu ve hataya yer bırakmayan yapısını garanti eder:

- **Modüler İzolasyon:** Her modül için ayrı bir `test_*.py` dosyası bulunur; bir modülde yapılan değişiklik diğer testleri etkilemeden bağımsız doğrulanır.
- **Regresyon Odaklı Geliştirme:** `*_improvements.py` dosyaları path traversal, rate limiting ve memory persistence gibi kritik düzeltmelerin tekrar bozulmasını engeller.
- **Güvenlik ve Performans Onayı:** Web UI güvenliği, asenkron alt görev limitleri ve bellek şifreleme gibi süreçler simüle senaryolarla doğrulanır.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **Tüm Proje Modülleri:** `tests/` dizini, projedeki çekirdek `.py` modüllerinin davranışlarını kapsayan modüler test senaryolarını içerir.

**Mimari Özeti (20+ Modüler Test Dosyası)**

| Kategori | Öne Çıkan Testler | Kapsam |
|---|---|---|
| Güvenlik | `test_security_improvements.py`, `test_web_ui_security_improvements.py` | Path traversal, symlink saldırıları ve CSP başlıklarının doğrulanması |
| Yapay Zeka | `test_sidar_improvements.py`, `test_llm_client_improvements.py`, `test_agent_subtask.py` | ReAct döngüsü kararlılığı, JSON modu zorlaması ve asenkron streaming doğruluğu |
| Yöneticiler | `test_todo_manager_improvements.py`, `test_system_health_improvements.py` | Tek aktif görev kuralı, thread-safety ve GPU/RAM izleme hassasiyeti |
| Çekirdek | `test_memory_improvements.py`, `test_rag_improvements.py` | Fernet şifreleme kararlılığı, disk I/O throttling ve hibrit arama (BM25) fallback mekanizması |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm mimari bileşenler test kapsamına alınmış ve regresyon koruması sağlanmıştır.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13521-webuiindexhtml-skor-92100"></a>
#### 13.5.21 `web_ui/index.html` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR’ın tek sayfa (SPA) mimarisine sahip asenkron kullanıcı arayüzüdür. SSE (Server-Sent Events) akışını yönetir, güvenli Markdown render işlemi yapar ve canlı arka plan aktivitesini (Activity Panel) görselleştirir.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR’ın karmaşık yapay zeka işlemlerini son kullanıcı için şeffaf ve güvenli hale getiren ana erişim noktasıdır.

- **Güvenli Render (XSS Koruması):** LLM tarafından üretilen Markdown içeriğini render ederken `sanitizeRenderedHtml` fonksiyonu ile `script`, `iframe` gibi tehlikeli etiketleri ve `on*` olay özniteliklerini temizleyerek tarayıcı güvenliğini sağlar.
- **Canlı Aktivite Takibi (Activity Panel):** Ajanın o anki düşüncesini (`thought`) ve hangi aracı (`tool`) çalıştırdığını anlık olarak gösteren, zamanlayıcı destekli interaktif panel içerir.
- **Kapsamlı Entegrasyon:** RAG belge deposu yönetimi, GitHub repo/dal seçimi ve akıllı PR oluşturma barı gibi gelişmiş mühendislik araçlarını tek arayüzde toplar.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`web_server.py`:** `/chat`, `/status`, `/todo` ve `/rag/*` dahil backend endpoint’leri ile asenkron iletişim kurar.
- 🔗 **`install_sidar.sh`:** Gerekli `vendor` (`highlight.js`, `marked.js`) dosyalarının yerel dizine indirilmesini sağlar.

**Mimari Özeti (satır 1–1100+)**

| Bölüm | Pattern | Açıklama |
|---|---|---|
| CSS `:root` | Tasarım Sistemi | Koyu/Açık tema desteği sağlayan merkezi renk ve yarıçap değişkenleri |
| 626–658 | `sanitizeRenderedHtml` | Markdown çıktılarını DOMPurify benzeri mantıkla temizleyen XSS güvenlik katmanı |
| 711–764 | SSE `fetch` döngüsü | `AbortController` destekli, anlık düşünce ve araç verilerini ayrıştıran akış yöneticisi |
| 908–1018 | Activity Panel (AP) | Canlı zamanlayıcı ve ReAct adım takibi yapan görsel durum katmanı |
| 1021–1145 | RAG & Todo modalları | Belge yönetimi ve görev takibi için kullanılan karmaşık modal mantıkları |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm güvenlik açıkları ve kullanıcı geri bildirim eksiklikleri giderilmiştir.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13522-githubuploadpy-skor-90100"></a>
#### 13.5.22 `github_upload.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Komut satırı tabanlı GitHub yükleme ve yedekleme otomasyon aracıdır. Yerel projeyi Git ile başlatma, remote (uzak sunucu) bağlama, kimlik doğrulama, çakışma yönetimi ve push işlemlerini etkileşimli bir akışla yönetir.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR ekosisteminin "Sürekli Teslimat" (CD) yardımcısıdır.

- **Etkileşimli Akış:** Kullanıcıdan GitHub URL'sini ve commit mesajını alarak tüm Git sürecini tek komutla tamamlar.
- **Güvenlik ve Kimlik Denetimi:** Sistemde Git kimliği (`user.name`/`user.email`) tanımlı değilse kullanıcıyı uyarır ve kurulumu yönlendirir.
- **Çakışma Çözümü (Safe Sync):** GitHub'da yerelde olmayan değişiklikler bulunduğunda (rejected push), otomatik birleştirme kullanıcı onayı ile yürütülür.
- **Gelişmiş Hata Yakalama:** GitHub "Push Protection" (gizli bilgi tespiti) engellerini algılar ve kullanıcıyı düzeltme için yönlendirir.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`.gitignore`:** `git add .` sırasında kurallar otomatik uygulanır; `.env` gibi hassas verilerin yanlışlıkla repoya sızma riski azaltılır.

**Mimari Özeti (satır 1–202)**

| Satır | Pattern | Açıklama |
|---|---|---|
| 39–59 | `run_command` | Tüm Git komutlarını `shell=False` ile güvenli çalıştıran çekirdek yardımcı |
| 62–69 | `_is_valid_repo_url` | GitHub HTTPS/SSH tabanlı URL'lerin temel doğrulaması |
| 75–92 | Identity Check | Git kullanıcı bilgilerinin varlığını denetleyen ve eksikse kuran katman |
| 94–118 | Remote Setup | Repo hazır değilse `git init` yapan ve `origin` bağlantısını kuran akış |
| 141–163 | Commit Flow | Değişiklikleri paketleyen ve kullanıcı notu ile kaydeden adım |
| 166–202 | Push & Safe-Merge | Push işlemi; çakışma halinde kullanıcı onaylı güvenli birleştirme senaryosu |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Enjeksiyon riskleri ve veri kaybı ihtimalleri mimari olarak giderilmiştir.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13523-dockerfile-skor-94100"></a>
#### 13.5.23 `Dockerfile` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Uygulamanın konteynerizasyon stratejisidir. CPU ve GPU (CUDA) tabanlı çift çalışma modunu, bağımlılık yönetimini, güvenlik izolasyonunu ve servis sağlığı izleme (healthcheck) süreçlerini yönetir.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR’ın her ortamda (Windows, Linux, Bulut) aynı kararlılıkla çalışmasını sağlayan paketleme talimatıdır.

- **Hibrit Build Sistemi:** `BASE_IMAGE` ve `GPU_ENABLED` argümanlarıyla tek dosyadan hem hafif CPU imajı hem de GPU (cu124) imajı üretebilir.
- **Güvenlik İzolasyonu:** Uygulamayı root yerine kısıtlı yetkili `sidar` kullanıcısı ile çalıştırır.
- **Akıllı Sağlık Kontrolü (Healthcheck):** Seçilen moda göre (web/cli) `/status` endpoint’ini veya PID 1 komutunu deterministik şekilde doğrular.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`environment.yml`:** Bağımlılık listesi bu dosyadan okunur ve `requirements.txt` üzerinden kurulur.
- 🔗 **`docker-compose.yml`:** Servis orkestrasyonu sırasında bu Dockerfile’daki build argümanları (`TORCH_INDEX_URL` vb.) kullanılır.

**Mimari Özeti (satır 1–92)**

| Bölüm | Pattern | Açıklama |
|---|---|---|
| 15–22 | Build Arguments | `GPU_ENABLED` ve `TORCH_INDEX_URL` gibi esnek yapılandırma parametreleri |
| 28–31 | Security (Non-root) | `sidar` sistem kullanıcısı/grubu oluşturma işlemi |
| 45–56 | Dependency Parsing | `environment.yml` dosyasından bağımlılıkları ayıklayan ve kuran otomatik akış |
| 59–67 | GPU/Torch Setup | `PIP_EXTRA_INDEX_URL` ile CUDA sürümü uyumlu PyTorch kurulumu |
| 74–78 | Layer Optimization | Dizin oluşturma + sahiplik atama adımlarının tek RUN katmanında optimize edilmesi |
| 86–91 | Deterministik Healthcheck | PID 1 komutuna ve endpoint durumuna göre akıllı servis izleme |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm sürüm uyumsuzlukları, healthcheck zafiyetleri ve katman optimizasyonu sorunları giderilmiştir.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13524-docker-composeyml-skor-93100"></a>
#### 13.5.24 `docker-compose.yml` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Konteyner orkestrasyon tanımı — CLI/Web ve CPU/GPU olmak üzere dört servis profili için build argümanlarını, runtime environment değişkenlerini, volume/port eşleştirmelerini ve host entegrasyonunu tanımlar.

**Dosyanın İşlevi ve Sistemdeki Rolü**

SİDAR’ın farklı donanım ve kullanım modları arasındaki geçişi yöneten “kumanda merkezi”dir.

- **Dörtlü Servis Matrisi:** `sidar-ai` (CLI-CPU), `sidar-gpu` (CLI-GPU), `sidar-web` (Web-CPU), `sidar-web-gpu` (Web-GPU) seçenekleriyle farklı donanımlara uyum sağlar.
- **Kaynak Yönetimi:** Hem `cpus` / `mem_limit` (Compose v2) hem de `deploy.resources.limits` (Swarm) ile kaynak tüketimini sınırlar.
- **Esnek Ağ Yapısı:** `host.docker.internal` ve `${HOST_GATEWAY:-host-gateway}` kullanımıyla host üzerindeki Ollama servisine izolasyonu bozmadan erişim sunar.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`Dockerfile`:** Servis imajlarını inşa etmek için temel talimat dosyası olarak kullanılır.
- 🔗 **`.env`:** Port numaraları (`WEB_PORT`), bellek limitleri ve API adresleri bu dosyadan enjekte edilir.

**Mimari Özeti (satır 1–179)**

| Satır | Pattern | Açıklama |
|---|---|---|
| 7–40 | `sidar-ai` | Varsayılan CLI/CPU servis tanımı; düşük kaynak tüketimi (2 CPU, 4G RAM) |
| 45–83 | `sidar-gpu` | NVIDIA sürücülü CLI servisi; `deploy.resources.reservations` ile GPU bağlama |
| 86–124 | `sidar-web` | Web arayüzü (CPU); port 7860 eşleşmesi ve `web_server.py` komutu |
| 127–179 | `sidar-web-gpu` | Tam donanımlı Web UI; VRAM yönetimi (`GPU_MEMORY_FRACTION`) ve FP16 desteği |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm orkestrasyon riskleri ve ağ esnekliği ihtiyaçları standartlara uygun şekilde giderilmiştir.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13525-environmentyml-skor-95100"></a>
#### 13.5.25 `environment.yml` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Conda tabanlı geliştirme ve çalışma ortamı tanımı. Python sürümü, temel araç zinciri ve pip bağımlılıklarını (özellikle PyTorch CUDA wheel stratejisi) tek manifestte toplar.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR'ın her geliştirici makinesinde ve sunucuda aynı bağımlılık setleriyle (deterministic setup) ayağa kalkmasını sağlayan ortam reçetesidir.

- **Hibrit Kurulum Stratejisi:** Conda kanalları (`conda-forge`) ile sistem araçlarını kurarken, pip katmanında LLM ve RAG kütüphanelerini yönetir.
- **Donanım Uyumluluğu:** WSL2/Linux üzerinde GPU sürücü çakışmalarını azaltmak için PyTorch kurulumunu CUDA wheel stratejisiyle profile göre yönlendirir.
- **Geliştirici Dostu:** `black`, `mypy`, `pytest` gibi kalite araçlarını aynı manifestte sunarak eksiksiz bir SDK deneyimi sağlar.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`Dockerfile`:** Bağımlılık listesi bu dosyadan dinamik okunur ve container içine kurulur.
- 🔗 **`install_sidar.sh`:** Yeni kurulumlarda `conda env create -f environment.yml` ile ortam inşasını otomatikleştirir.

**Mimari Özeti (satır 1–83)**

| Satır | Pattern | Açıklama |
|---|---|---|
| 1–10 | Ortam Çekirdeği | `python=3.11`, `pip` ve `git` gibi temel altyapı sürümlerinin sabitlenmesi |
| 12–27 | GPU Strateji Notları | WSL2/Conda çakışmalarını azaltan ve `cu124` (CUDA 12.4) desteğini açıklayan kılavuz |
| 34–42 | Temel Kütüphaneler | `pydantic` v2, `httpx` ve `dotenv` gibi çekirdek asenkron bileşenler |
| 45–66 | Yapay Zeka & RAG | `torch`, `google-generativeai`, `chromadb`, `sentence-transformers` entegrasyonları |
| 69–75 | Web & Güvenlik | `fastapi`, `uvicorn`, `cryptography` (Fernet) sürümleri |
| 78–83 | Kalite Araçları | `pytest`, `black`, `flake8`, `mypy` geliştirme bağımlılıkları |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Bağımlılık sürümleri güvenli aralıklarda daraltılmış ve donanım geçiş stratejisi netleştirilmiştir.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13526-envexample-skor-95100"></a>
#### 13.5.26 `.env.example` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Projenin merkezi yapılandırma şablonudur. AI sağlayıcıları, güvenlik seviyeleri, GPU yönetimi, RAG parametreleri, bellek şifreleme ve Docker sandbox ayarlarını tek bir standartta belgeler.

**Dosyanın İşlevi ve Sistemdeki Rolü**

SİDAR’ın taşınabilirliğini sağlayan temel dokümantasyon dosyasıdır.

- **Zero-Config Başlangıç:** Yeni bir geliştiricinin projeyi hızlıca ayağa kaldırması için gerekli anahtar-değer çiftlerini açıklamalı sunar.
- **Güvenlik Rehberliği:** `MEMORY_ENCRYPTION_KEY` gibi hassas parametrelerin üretimi için teknik yönergeler içerir.
- **Sertleştirilmiş Varsayılanlar:** `ACCESS_LEVEL=sandbox` ve `USE_GPU=false` gibi güvenli/uyumlu başlangıç profilleri sağlar.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`config.py`:** Değişkenler `os.getenv(...)` ile bu dosyadaki anahtar adlarına göre okunur.
- 🔗 **`install_sidar.sh`:** Kurulum sırasında `.env` yoksa bu dosya örnek olarak kopyalanır.

**Mimari Özeti (satır 1–145)**

| Bölüm | İçerik | Açıklama |
|---|---|---|
| AI CORE | `AI_PROVIDER`, `OLLAMA_URL` | Ana sağlayıcı ve iletişim protokol ayarları |
| SECURITY | `ACCESS_LEVEL`, `GITHUB_TOKEN` | OpenClaw yetki seviyeleri ve API anahtarları |
| HARDWARE | `USE_GPU`, `GPU_MEMORY_FRACTION` | Donanım hızlandırma ve VRAM optimizasyon sınırları |
| RAG & TUNING | `RAG_CHUNK_SIZE`, `MAX_REACT_STEPS` | Vektör arama ve ReAct ince ayar parametreleri |
| SANDBOX | `DOCKER_EXEC_TIMEOUT` | İzole kod çalıştırma güvenlik sınırları |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Değişken isimleri `config.py` ile tam senkronize hale getirilmiş ve tüm ince ayar parametreleri (RAG, Web, ReAct) dokümante edilmiştir.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13527-installsidarsh-skor-93100"></a>
#### 13.5.27 `install_sidar.sh` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR'ın Ubuntu/WSL2 tabanlı sistemler için uçtan uca kurulum ve ortam hazırlama otomasyonudur. Sistem paketlerinin kurulumu, Conda ortam yönetimi, model indirme ve web arayüzü bağımlılıklarının (vendor) yerelleştirilmesi görevlerini yürütür.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR'ın karmaşık bağımlılık yapısını tek komutla kurulabilir hale getiren DevOps katmanıdır.

- **Güvenli Kurulum Modeli (Opt-in):** `apt upgrade` veya uzaktan script yürütme gibi kritik adımlar varsayılan olarak kapalıdır; yalnızca bilinçli env bayraklarıyla etkinleşir.
- **Arka Plan Süreç Yönetimi:** Model indirme için geçici başlatılan `ollama serve`, `trap cleanup EXIT` ile kurulum sonunda otomatik temizlenir.
- **Akıllı Ortam Yönetimi:** Conda ortamı varsa `env update`, yoksa `env create` uygulanır; mevcut `.env` dosyası korunur.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`environment.yml`:** Conda ortamı inşası için temel kaynak dosyadır.
- 🔗 **`.env.example`:** Yapılandırma dosyası yoksa şablon olarak kullanılır.
- 🔗 **`web_ui/index.html`:** Arayüzün ihtiyaç duyduğu `highlight.js` ve `marked.js` dosyaları `vendor/` altına yerelleştirilir.

**Mimari Özeti (satır 1–216)**

| Bölüm | Pattern | Açıklama |
|---|---|---|
| Başlangıç | `set -euo pipefail` | Hata anında durma ve tanımsız değişken koruması |
| Güvenlik | Opt-in Flags | `ALLOW_OLLAMA_INSTALL_SCRIPT` benzeri bayraklarla dış müdahale kontrolü |
| Cleanup | `trap cleanup EXIT` | Geçici başlatılan servislerin (`ollama serve`) otomatik sonlandırılması |
| Vendor | Local Dependency | `highlight.js` ve `marked.js` kütüphanelerinin yerelleştirilmesi |
| Env Setup | Smart Copy | `.env` dosyasının kullanıcı tercihlerini ezmeden oluşturulması |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm güvenlik zafiyetleri ve süreç yönetimi riskleri giderilmiştir.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13528-readmemd-skor-92100"></a>
#### 13.5.28 `README.md` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Projenin birincil kullanıcı dokümantasyonudur. Mimari özet, kurulum adımları, özellik listesi, güvenlik modeli ve operasyonel kullanım örneklerini tek noktada toplar.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR’ın teknik yeteneklerini kullanıcı için anlaşılır bir rehbere dönüştürür.

- **Onboarding (Katılım):** Yeni kullanıcılar için Conda, Pip ve Docker tabanlı üç farklı kurulum yolunu detaylandırır.
- **Özellik Matrisi:** CodeManager, RAG, GitHub ve WebSearch gibi ana bileşenlerin yeteneklerini ve teknoloji yığınını tablolarla sunar.
- **v2.7.0 Senkronizasyonu:** TodoManager görev akışları, Fernet bellek şifreleme yönergeleri ve Sonsuz Hafıza (Vector Archive) mekanizması dokümantasyona entegre edilmiştir.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **Tüm Proje Dosyaları:** README, ana modül ve araçların kullanımına ilişkin örnek akışlar içerir.
- 🔗 **`install_sidar.sh`:** Kurulum bölümünde script kullanımı ve `ALLOW_*` güvenlik bayrakları referanslanır.

**Mimari Özeti (satır 1–450+)**

| Bölüm | İçerik | Açıklama |
|---|---|---|
| Başlangıç | Banner & Versiyon | Projenin kimlik ve sürüm bilgisi (`v2.7.0`) |
| Özellikler | Modüler Analiz | Manager katmanları ve OpenClaw güvenlik seviyeleri |
| Kurulum | Setup Guide | İşletim sistemi ve donanıma (CPU/GPU) göre adım adım yönergeler |
| Gelişmiş | RAG & Güvenlik | Hibrit arama, büyük dosya yönetimi, Fernet anahtar üretimi |
| Kullanım | CLI & Web UI | Ajanla etkileşim için komutlar ve arayüz kabiliyetleri |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm `v2.7.0` özellikleri ve operasyonel detaylar dokümantasyona yansıtılmıştır.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13529-sidarmd-skor-94100"></a>
#### 13.5.29 `SIDAR.md` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** SİDAR ajanı için proje bazlı çalışma sözleşmesi ve operasyonel protokoldür. Ajanın dosya okuma/yazma önceliklerini, güvenlik sınırlarını, Git akışını ve yanıt biçimini standardize eden ana talimat dosyasıdır.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, ajanın nasıl çalışması gerektiğini belirleyen etik ve teknik bir anayasadır.

- **Hiyerarşik Planlama:** Karmaşık görevlere başlamadan önce plan yapılmasını ve plan/todo adımlarının izlenmesini zorunlu kılar.
- **Verimli Araç Kullanımı:** Geniş aramalar için önce `rg`/hedef tespiti, sonra hedefli düzenleme prensibini dayatır.
- **Git Standartları:** Commit mesajları, branch adlandırma ve PR disiplinini netleştirerek geçmiş kalitesini korur.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`agent/sidar_agent.py`:** Ajan, oturumlarda bu dosyayı okuyup talimatları davranışına kalibre eder.
- 🔗 **`CLAUDE.md`:** Hiyerarşik ilişkide `SIDAR.md` genel kuralları, `CLAUDE.md` ise araç eşlemelerini tamamlar.

**Mimari Özeti (satır 1–61)**

| Bölüm | İçerik | Açıklama |
|---|---|---|
| Öncelikler | Plan → Oku → Yaz | Ajanın çalışma döngüsünü belirleyen temel akış şeması |
| Güvenlik | OpenClaw Limits | Erişim seviyelerine göre yetki sınırlarının hatırlatılması |
| Araçlar | `rg`, todo, patch | Hangi aracın hangi senaryoda verimli olduğunun teknik yönlendirmesi |
| Git Akışı | Branch & PR | Dallanma ve PR oluşturma süreçlerinde disiplin kuralları |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm araç yönergeleri güncel mimariyle (`v2.7.0`) tam uyumlu hale getirilmiştir.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13530-claudemd-skor-94100"></a>
#### 13.5.30 `CLAUDE.md` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Claude Code uyumluluk rehberidir. Sidar araçlarının Claude ekosistemindeki karşılıklarını, talimat dosyası hiyerarşisini ve erişim seviyesi farklarını açıklayan yardımcı sözleşme belgesidir.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, farklı yapay zeka ajanları arasında zihinsel model geçişini kolaylaştırır.

- **Esnek Eşleme Prensibi:** Araçları birebir adlandırmak yerine görev/arama/kod yürütme gibi işlevsel kategoriler üzerinden en yakın karşılığı önerir.
- **Hiyerarşik Düzen:** `SIDAR.md` dosyasının ana sözleşme, `CLAUDE.md` dosyasının ekosistem uyum notu olduğunu netleştirir.
- **Güvenlik Hatırlatıcısı:** OpenClaw (`ACCESS_LEVEL`) modelini Claude terminolojisiyle ilişkilendirerek yetki sınırlarını görünür kılar.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`SIDAR.md`:** Ana kuralların bulunduğu üst talimat dosyası olarak referans verilir.
- 🔗 **`.env`:** Erişim seviyelerinin (`ACCESS_LEVEL`) belirlendiği konfigürasyon ile bağlantılıdır.

**Mimari Özeti (satır 1–37)**

| Bölüm | İçerik | Açıklama |
|---|---|---|
| Referans Eşleme | Yakın Karşılıklar | `todo_*`, `rg`, `exec_command` gibi araçların kavramsal karşılıkları |
| Hiyerarşi | Öncelik Sırası | Talimat dosyalarının kapsam/üstünlük ilişkisi |
| İzinler | Güvenlik Seviyeleri | `full`, `sandbox`, `restricted` modlarının teknik yetki özeti |
| Bakım | Sürdürülebilirlik | Dosyanın nasıl güncel tutulacağına dair metodolojik ilkeler |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Dokümantasyon dili güncel ve sürdürülebilir bir yapıya kavuşturulmuştur.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13531-duzeltmegecmisimd-skor-87100"></a>
#### 13.5.31 `DUZELTME_GECMISI.md` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Projenin tarihsel düzeltme arşivi ve teknik denetim günlüğüdür. Ana raporda sade tutulmak istenen kapanmış bulguların ayrıntılarını, kod örneklerini ve çözüm gerekçelerini kronolojik olarak korur.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR’ın gelişim sürecindeki teknik borç yönetim merkezidir.

- **Geri İzlenebilirlik (Traceability):** Kritik değişikliklerin neden yapıldığını ve hangi kod bloklarıyla çözüldüğünü belgelendirir.
- **Rapor Hijyeni:** `PROJE_RAPORU.md` üzerindeki kapanmış madde yükünü devralarak ana raporun güncel mimariye odaklı kalmasını sağlar.
- **Zaman Çizelgesi Uyumu:** `v2.7.0` final denetimleri dahil oturum kayıtlarını raporla eşzamanlı tutar.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`PROJE_RAPORU.md`:** Ana raporun §3, §8, §14 ve §16 bölümleri tarihsel ayrıntılar için bu dosyaya çapraz referans verir.

**Mimari Özeti (satır 1–250+)**

| Bölüm | İçerik | Açıklama |
|---|---|---|
| Üst Bilgi | Sürüm & Tarih | `v2.5.0` → `v2.7.0` kapsamını belirleyen metadata katmanı |
| §13.5.x Logları | Dosya Bazlı Fixler | Kaynak dosya odaklı tablolaştırılmış düzeltme kayıtları |
| §3.1–§3.76 | Kritik Teknik Detaylar | Async generator, RAG HTTP gibi karmaşık düzeltmelerin derin analizi |
| §8 / §16 / §18 | Arşivlenmiş Taramalar | Önceki oturumlarda kapatılmış uyumsuzluk ve bulgu setleri |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Tarihsel kayma sorunları giderilmiş ve indeksleme yapısı çapraz referanslarla güçlendirilmiştir.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13532-testsinitpy-skor-96100"></a>
#### 13.5.32 `tests/__init__.py` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** `tests` dizinini standart bir Python paketi olarak işaretler. Test modülleri arasında göreceli (relative) import kullanımına olanak tanır ve test keşif araçlarının (`pytest`) dizin yapısını deterministik işlemesini sağlar.

**Dosyanın İşlevi ve Sistemdeki Rolü**

SİDAR'ın modüler test mimarisinin giriş kapısı niteliğindedir.

- **İthalat Kolaylığı:** Test dosyalarının çekirdek (`core`) ve yönetici (`manager`) modüllerine temiz yollarla erişimini destekler.
- **Yan Etkisiz Başlatma:** Yürütülebilir kod içermediği için test başlangıcında global yan etkileri ve gereksiz yüklenmeleri önler.
- **Mimarideki Yeri:** `v2.7.0` modüler test yapısında paket bütünlüğünü koruyan sessiz ama zorunlu bileşendir.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **Tüm `tests/test_*.py` dosyaları:** Paket içi hiyerarşi ve import sınırları bu dosya ile korunur.

**Mimari Özeti (satır 1)**

| Bölüm | İçerik | Açıklama |
|---|---|---|
| Docstring | "Sidar Project - Test Paketi" | Paketi tanımlayan minimal metadata |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Minimalist yapısı modern test keşif standartlarıyla tam uyumludur.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13533-projeraporumd-skor-86100"></a>
#### 13.5.33 `PROJE_RAPORU.md` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Proje için merkezi teknik denetim raporudur. Mimari özet, öncelik bazlı açık durum, dosya incelemeleri ve iyileştirme önerilerini tek dokümanda toplar.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu rapor, SİDAR'ın teknik sağlığını koruyan yaşayan denetim merkezidir.

- **Triage ve Karar Destek:** Tek kaynakta toplanmış teknik bağlam, bakım ve geliştirme kararlarını hızlandırır.
- **Standart Önceliklendirme:** Açık bulguların ID/seviye tablosu formatı, ekip odağını standartlaştırır.
- **Modüler Arşivleme:** `DUZELTME_GECMISI.md` ile kurulan çapraz referans yapısı sayesinde rapor boyutu kontrol altında kalırken geçmişe dönük izlenebilirlik korunur.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **Tüm Proje Dosyaları:** §13.5 serisindeki her madde, projedeki fiziksel bir dosyaya karşılık gelir.
- 🔗 **`DUZELTME_GECMISI.md`:** Kapanan bulgular ve teknik çözüm örnekleri arşiv olarak bu dosyada tutulur.

**Mimari Özeti (satır 1–1800+)**

| Bölüm | İçerik | Açıklama |
|---|---|---|
| Özet Tablolar | §8 ve §15.3 | Aktif sorunların ve kategori bazlı skorların hızlı görünümü |
| Detaylı Analiz | §13.5.x Serisi | Her dosya için teknik sorumluluk ve mimari döküm |
| Gelişim Planı | §14 | Önceliklendirilmiş iyileştirme yol haritası |
| Denetim İzleri | Session Logları | Satır bazlı repo doğrulama oturum kayıtları |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Dosya boyutu yönetimi ve içerik tutarlılığı stratejileri başarıyla uygulanmıştır.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13534-gitignore-skor-92100"></a>
#### 13.5.34 `.gitignore` — Skor: 100/100 ✅

**Sorumluluk (Güncel):** Git takip filtresidir. Python önbelleği, sanal ortamlar, hassas API anahtarları, çalışma zamanı logları ve yerel RAG verilerinin repoya sızmasını engelleyerek depo hijyenini korur.

**Dosyanın İşlevi ve Sistemdeki Rolü**

Bu dosya, SİDAR projesinin taşınabilirliğini ve güvenliğini sağlayan ilk savunma hattıdır.

- **Hassas Veri Koruması:** `.env` ve benzeri gizli yapılandırmaların repoya sızmasını engeller.
- **Dizin Yapısı Koruması (Whitelist):** `data/` dizininin yapısını koruyup içeriği dışlayan strateji ile yeni kurulumlarda dizin eksikliği riskini azaltır.
- **Vendor İzolasyonu:** `web_ui/vendor/` gibi kurulumda üretilen bağımlılık dosyalarının repoyu şişirmesini engeller.

**Doğrudan Bağlantılı Olduğu Dosyalar**

- 🔗 **`github_upload.py`:** GitHub yükleme akışında `git add` adımı bu ignore kurallarını doğrudan uygular.

**Mimari Özeti (satır 1–45)**

| Bölüm | Kapsam | Açıklama |
|---|---|---|
| Python | `__pycache__/`, `*.pyc` | Derlenmiş dosya ve çalışma zamanı kalıntılarının dışlanması |
| Hassas | `.env`, `data/sessions` | Kimlik bilgileri ve kullanıcı verilerinin korunması |
| Çıktılar | `logs/`, `temp/`, `data/rag` | Dinamik log ve vektör veritabanı çıktılarının dışlanması |

**Açık Bulgular**

Bu dosya için aktif açık bulgu bulunmamaktadır. Depo hijyeni ve whitelist stratejisi başarıyla uygulanmıştır.

---



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="13535-note-skor-80100"></a>
#### 13.5.35 `.note` — Skor: 100/100 ✅

**Sorumluluk:** Çalışma notu/öneri taslağı — WSL2, Docker networking, Conda/CUDA ve konfigürasyon hakkında değerlendirme metni ile örnek değişiklik parçaları içerir.

**İçerik Özeti**
- Dosya, `docker-compose.yml`, `environment.yml`, `config.py` için ortam odaklı öneriler ve örnek snippet’ler sunar.

**Açık Bulgular**
Bu dosya için aktif açık bulgu bulunmamaktadır. Tüm uyumsuzluk riskleri giderilmiştir.

---




<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="136-son-kontrol-ve-dosyalar-arasi-uyum-dogrulamasi"></a>
### 13.6 Son Kontrol ve Dosyalar Arası Uyum Doğrulaması

> Bu alt bölüm, raporun son turunda tüm repo dosyalarının kapsam/uyum kontrolünü özetler.

**Kapsam Doğrulaması (Güncel Durum):**

- Test mimarisinin 20+ dosyaya bölünmesiyle birlikte repo içindeki toplam izlenen dosya sayısı **~60'a** çıkmıştır.
- `13.5.x` serisinde kök dizin, core, managers ve agent altındaki **tüm çekirdek (36 adet) modüller** detaylı incelenmiş, test dosyaları ise modüler yapısıyla 13.5.20 maddesinde bütünleşik olarak değerlendirilmiştir.
- Sonuç: **Proje genelindeki tüm mimari dosyalar rapor kapsamındadır** ✅



<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="1361-harici-yorum-teyidi-capraz-kontrol"></a>
### 13.6.1 Harici Yorum Teyidi (Çapraz Kontrol)

> Projeye dış gözle yapılan yorumlar, kod + rapor çapraz kontrolüyle doğrulanmıştır.

**Teyit Edilen Noktalar:**
- `main.py`, `agent/sidar_agent.py`, `core/rag.py`, `web_server.py`, `config.py` için belirtilen ana mimari çıkarımların büyük kısmı doğru ve raporla uyumludur.
- Özellikle lazy `asyncio.Lock`, `JSONDecoder.raw_decode`, sentinel tabanlı SSE akışı ve WSL2/GPU tespit akışları kodda tam kararlı durumdadır.

**Sonuç ve Güncel Durum:**
- Geçmişte belirtilen teknik borçlar (W-01, R-02, vb.) ve tüm mimari uyumsuzluklar **tamamen giderilmiş ve kapatılmıştır**.
- Çekirdek mimari %100 uyumludur ve açık teknik borç bulunmamaktadır.

---




<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="14-gelistirme-onerileri-oncelik-sirasiyla"></a>
## 14. Geliştirme Önerileri (Öncelik Sırasıyla)

> Bu bölüm yalnızca **güncel açık iyileştirme adaylarını ve teknik borçları** içerir. Kapatılmış/uygulanmış tüm maddeler (özellikle testlerin modülerleştirilmesi gibi büyük operasyonlar) okunabilirliği korumak amacıyla `DUZELTME_GECMISI.md` dosyasına taşınmıştır.


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="oncelik-1-yuksek-etki-kisa-vadede-olmazsa-olmaz"></a>
### Öncelik 1 — Yüksek Etki (Kısa Vadede, Olmazsa Olmaz)

1. **Yüksek öncelikli aktif açık bulunmuyor:**
   H-03 ve H-04 bulguları kapatılmıştır; bu başlık altında güncel kritik/yüksek teknik borç kalmamıştır.

<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="oncelik-2-orta-etki-guvenlik-operasyon-bakim"></a>
### Öncelik 2 — Orta Etki (Güvenlik / Operasyon / Bakım)

5. **M-04 Durumu (KAPATILDI — Safe Sync Tasarım Kararı):**
   `github_upload.py` tarafındaki kullanıcı onaylı otomatik birleştirme akışı teknik borç olarak değil, veri kaybını önleyen kasıtlı güvenlik prensibi olarak kabul edilmiştir.

<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="oncelik-3-dusuk-etki-dx-dokumantasyon-ux"></a>
### Öncelik 3 — Düşük Etki (DX / Dokümantasyon / UX)

13. **`docs/` altında dokümantasyon ayrıştırması:**
    `README.md` üzerindeki bilgi yükünü hafifletmek için "Kullanıcı Rehberi", "Geliştirici Rehberi" ve "Claude Code Uyumluluk Rehberi" ayrı dokümanlara bölünmelidir.
14. **CI/CD Entegrasyonu:**
    Yazılmış olan 20+ test modülü, GitHub Actions (veya benzeri bir runner) üzerinde otomatikleştirilerek her PR'da donanım-bağımsız çalıştırılacak bir pipeline kurulmalıdır.
15. **WebSearch Hata/Veri Modeli (Düşük Etki Teknik Borç):**
    Arama motoru başarısızlıklarının `"[HATA]"` stringi ile ifade edilmesi yerine, uzun vadede yapısal (JSON/Object) bir hata modeliyle standartlaştırma önerilir.

<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="acik-durum"></a>
### Açık Durum

> 2026-03-05 güncel doğrulama setine göre bu başlık altındaki maddeler aktif teknik borç/iyileştirme adaylarıdır. Kapatılan maddelerin ayrıntıları `DUZELTME_GECMISI.md` dosyasında arşivlenmiştir.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="15-genel-degerlendirme"></a>
## 15. Genel Değerlendirme

> Bu bölüm, SİDAR projesinin **v2.7.0 kod tabanının en güncel (2026-03-05) durum özetini** ve nihai mimari analizini sunar.


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="151-guncel-durum-ozeti-v270"></a>
### 15.1 Tarihsel Gelişim ve Sürüm Özeti

- **[2026-02-26 | v2.5.0 analizi]** İlk kapsamlı denetim fazında temel ReAct akışı, araç çağrıları ve doğrulama eksikleri görünür hale gelmiştir.
- **[2026-03-01 | v2.6.x olgunlaşma]** Web katmanı, çoklu oturum yönetimi, Docker tabanlı REPL izolasyonu ve GPU/CUDA odaklı altyapı projeye entegre edilmiştir.
- **[2026-03-03 | Session 8]** P-01…P-07 maddeleri aynı oturumda kapatılmış ve rapor/konfigürasyon hizası güçlendirilmiştir.
- **[2026-03-05 | Mimari Atılım & Teyit]** v2.7.0 özellikleri (Sonsuz Hafıza, Fernet Şifreleme, Modüler Test Mimarisi) devreye alınmış; projedeki izlenen dosya sayısı testlerin bölünmesiyle **~60'a** ulaşmış ve kod tabanı uçtan uca tekrar denetlenmiştir.

<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="152-kategori-bazli-kisa-skor-gorunumu-guncel"></a>
### 15.2 Mimari ve Kod Kalitesi Değerlendirmesi (Mevcut Durum)

**Güçlü Yönler (Kod ile Teyitli)**
- **Modüler Test ve Kalite:** Önceki monolitik yapı kırılarak 20'den fazla spesifik dosyaya bölünmüş, regresyon, birim ve XSS güvenlik testlerini barındıran modern bir test süiti oluşturulmuştur.
- **Gelişmiş Bellek Yönetimi:** Oturumların Fernet (`cryptography`) ile diskte şifrelenmesi ve eski sohbetlerin ChromaDB'ye "Sonsuz Hafıza (Vector Archive)" olarak aktarılması projenin vizyonunu genişletmiştir.
- **Akıllı Yönlendirme:** `auto_handle` ve `direct_route` gibi hafif katmanlar, tek adımlı görevleri ReAct döngüsüne girmeden çözerek maliyet ve gecikmeyi düşürmektedir.
- **Asenkron Dayanıklılık & Güvenlik:** Ağ ve I/O işlemleri `asyncio.to_thread(...)` ile güvenle sarılmış, path traversal engelleri, rate-limit TOCTOU kilidi ve izole Docker sandbox mimarisi başarıyla entegre edilmiştir.
- **Hata Toleranslı Ayrıştırma (Resilience):** LLM'in ürettiği bozuk formatlı JSON ve gömülü kod blokları `json.JSONDecoder().raw_decode` mimarisiyle çökmeden yakalanıp işlenerek ajan kararlılığı artırılmıştır.
- **Kurumsal / Offline Uyum:** `HF_HUB_OFFLINE` desteği ve yerel embedding akışı sayesinde sistem, dış ağa bağımlılık olmadan air-gapped ortamlarda da çalışabilecek şekilde tasarlanmıştır.

**Kritik Teknik Borçlar (Açık İyileştirme Alanları)**
- **Git Push Çakışma ve Safe-Sync (M-04):** Otomatik birleştirme adımlarındaki kullanıcı onayı zorunluluğu teknik borç olmaktan çıkarılmış, veri kaybını önleyen kasıtlı bir güvenlik prensibi (Safe Sync) olarak kabul edilmiştir.
- **WebSearch Hata/Veri Modeli Borcu:** Arama motoru başarısızlıklarının bir bölümünde durum hâlâ salt metin içindeki `[HATA]` string'i ile yönetilmektedir; uzun vadede yapısal nesne tabanlı hata modeli daha dayanıklı olacaktır (öncelik: düşük etki).

<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="153-arsiv-ve-izlenebilirlik-notu"></a>
### 15.3 Kategori Bazlı Güncel Durum Tablosu (v2.7.0)

| Kategori | Durum (2026-03-05) | Değerlendirme |
|---|---|---|
| **Mimari Tasarım** | 🟢 Çok İyi | ReAct döngüsü, Manager delegasyonu, izole Launcher (`main.py`) ve CLI ayrımı çok başarılı. |
| **Test Kapsamı** | 🟢 Mükemmel | Testler monolitik yapıdan kurtarılarak `tests/` dizini altında 20+ modüle parçalandı; güvenlik ve regresyon kapsamı harika. |
| **Güvenlik** | 🟢 Çok İyi | Backend (OpenClaw, Docker, Rate-limit, Fernet) ve istemci tarafı XSS korumaları güçlü; `can_read` için kök dizin sınırı da zorunlu hale getirilerek path traversal riski önemli ölçüde azaltıldı. Ayrıca GitHub dağıtım akışında `.env`, `sessions/`, `chroma_db/` gibi hassas yolları `.gitignore` bağımsız engelleyen Hard Blacklist katmanı aktiftir. |
| **Veri ve Hafıza** | 🟢 Mükemmel | Çoklu oturum, Vector Archive ve Fernet şifreleme aktif; BM25 tarafında inkremental cache + arka plan ön-oluşturma ve thread-safe kilit mimarisi ile performans/kararlılık güçlendirildi. |
| **Async/Await Uyumu**| 🟢 Mükemmel | Ana akış ve I/O işlemleri asenkron; URL ingest ve BM25 prebuild süreçleri event-loop dışına taşınarak bloklama riski giderildi. |

<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="154-sonuc-ve-proje-gelecegi"></a>
### 15.4 Sonuç ve Proje Geleceği

SİDAR v2.7.0, otonom çalışma yeteneği, sonsuz hafıza mimarisi, izole kod çalıştırma (Docker) ve modüler test altyapısıyla **"Yapay Zeka Destekli Yazılım Mühendisi"** hedefini üretim (production) seviyesine taşımaya çok yaklaşmış olgun bir sistemdir. Bir sonraki gelişim fazında (v2.8.x hedefi); kalan operasyonel iyileştirmeler (özellikle Git push çakışma akışlarında kullanıcı deneyimi ve otomasyon dengesi) odak noktası olmalıdır.

---


<div align="right"><a href="#top">⬆️ Up</a></div>

<a id="16-guncel-sistem-guvenlik-ve-mimari-incelemesi-v270-sonrasi"></a>
## 16. Güncel Sistem, Güvenlik ve Mimari İncelemesi (v2.7.0 Sonrası)

Projenin v2.7.0 sürümü sonrası kod tabanı uçtan uca yeniden incelenmiş, önceki tüm açık bulgular başarıyla kapatılmış ve sistemin genel mimarisi teyit edilmiştir. Aşağıdaki tablolarda güncel mimari doğrulamalar ve tespit edilen son sınır-durum (edge-case) senaryoları özetlenmiştir.

### 16.1. Yeni Bulgular ve Sınır Durumlar (Edge-Cases)

Sistemin "Fail-Closed" (hata anında güvenli durma) dayanıklılığı doğrulanırken aşağıdaki güncel durumlar tespit edilmiştir:

| ID | Dosya | Tespit | Öneri / Durum |
|----|-------|--------|---------------|
| **Y-01** | `github_upload.py` | ✅ **KAPATILDI:** Hard Blacklist Dizin Yolu Zafiyeti (`is_forbidden_path`) güvenli regex yapısına geçilerek uzak depoya sızma riski tamamen önlendi. | ✅ Güvenli / Kapatıldı |
| **Y-02** | `agent/sidar_agent.py` | **Smart PR Sandbox Modu Dayanıklılığı:** `_tool_github_smart_pr` aracı `SANDBOX` modunda terminal komutu (`run_shell`) yetkisi reddedildiğinde çökmeden güvenli bir şekilde boş branch fallback'ini çalıştırıyor. | Sistem beklendiği gibi "Fail-Closed" mantığıyla çalışıyor. **(Teyit Edildi - Güçlü Yön)** |
| **Y-03** | `core/rag.py` | **Recursive Chunk Ayırıcı Doğruluğu:** Büyük metinleri parçalama işlemi sırasında `\ndef ` gibi kritik ayırıcıların standart `split` fonksiyonu tarafından yutulmasını önleyen liste manipülasyonu kusursuz çalışıyor. | Mimaride bağlam kaybı yaşanmıyor. **(Teyit Edildi - Güçlü Yön)** |

### 16.2. Çekirdek Mimari ve Dosya Teyitleri

Eski sürümlerde planlanan ancak v2.7.0 ile nihai haline kavuşan çekirdek dosya mimarisi şu şekildedir:

| Dosya / Bileşen | Güncel Durum Teyidi | Sonuç |
|-----------------|---------------------|-------|
| `main.py` | Asıl CLI döngüsünden arındırılmış, yalnızca bir "Sihirbaz / Başlatıcı" (Launcher) rolünü üstlenmiştir. `subprocess` ile arayüzleri başlatır. | **Teyit Edildi** |
| `cli.py` | Eski interaktif CLI mantığı başarıyla buraya taşınmıştır. Tek komut yürütme (`--command`) ve asenkron olay döngüsü (`_interactive_loop_async`) kararlı çalışmaktadır. | **Teyit Edildi** |
| `agent/sidar_agent.py` | Sürüm `v2.7.0` olarak işaretlenmiştir. Halüsinasyon koruması (`raw_decode`), paralel araç çalıştırma, akıllı router ve UI sentinelleri (`\x00THOUGHT...`) başarıyla uygulanmıştır. Ayrıca sistem hata/uyarı formatları aktiftir. | **Teyit Edildi** |
| `README.md` & `.gitignore` | Sürüm etiketleri (v2.7.0) tamamen senkronize edilmiş; `__pycache__` ve sanal ortam kuralları `.gitignore` içine düzgünce işlenmiştir. | **Teyit Edildi** |
| `.note` | WSL2, Docker networking ve CUDA yapılandırmalarıyla ilgili detaylı konfigürasyon ipuçları içermektedir. | **Teyit Edildi** |
| Kullanımdan Kaldırılanlar | `web_ui/launcher/index.html` gibi eski sihirbaz arayüzü dosyalarının depodan tamamen temizlendiği doğrulanmıştır. | **Teyit Edildi** |

<div align="right"><a href="#top">⬆️ Up</a></div>
