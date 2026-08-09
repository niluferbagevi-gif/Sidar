# Sidar Proje Raporu — Bağımlılık ve Veri Akışları

> Aktif ürün baseline: **v5.2.0**. Bu dosya, [`PROJE_RAPORU.md`](../PROJE_RAPORU.md) indeksinin bölümüdür.

<a id="içindekiler"></a>
## Bu dosyadaki bölümler

- Bölüm 9
- Bölüm 10

---

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
