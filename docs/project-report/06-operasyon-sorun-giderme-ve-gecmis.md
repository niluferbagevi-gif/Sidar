# Sidar Proje Raporu — Operasyon, Sorun Giderme ve Geçmiş

> Aktif ürün baseline: **v5.2.0**. Bu dosya, [`PROJE_RAPORU.md`](../PROJE_RAPORU.md) indeksinin bölümüdür.

<a id="içindekiler"></a>
## Bu dosyadaki bölümler

- Bölüm 16
- Bölüm 17
- Bölüm 18

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

Bu rapor itibarıyla proje yalnızca özellik eklemiş bir prototip değil; test, audit ve operasyon yüzeyleri birbirini doğrulayan olgun bir sistemdir. CI hattı `.github/workflows/ci.yml` üzerinden **%90 coverage hard gate** uygular; bu değer depo kültüründeki tam kapsama hedefinin repo içinde gerçekten kodlanmış karşılığıdır.

Son doğrulama turlarında migration akışları, swarm delegasyonları, audit trail kayıtları, observability hattı, HITL güvenlik kapıları, Redis/PostgreSQL veri düzlemi ve React SPA/REST/WebSocket yüzeyleri birlikte yeniden kontrol edilmiştir. `CHANGELOG.md`, `AUDIT_REPORT_v5.0.md` ve bu rapor aynı temel sonucu teyit eder: **açık kritik, yüksek, orta veya düşük öncelikli majör teknik borç kalmamıştır**; sistem kurumsal rollout ve production dağıtımı için hazır durumdadır.

### Güncel Kapanış Özeti (v5.0.0-alpha)

- **Güncel baz çizgisi:** 62 üretim Python dosyası / 26.261 satır, 167 test dosyası / 46.874 satır, toplam 229 takipli Python dosyası / 73.135 satır ve takipli ölçüm yüzeyi 343 dosya / 87.576 satır.
- **Operasyonel durum:** Güvenlik/operasyon puanı `10.0/10`; açık bulgu yok; audit trail, observability ve swarm orkestrasyonu birlikte doğrulanmış durumda.
- **Kurumsal sonuç:** Sidar artık yalnızca “kod yazan ajan” değil; React SPA, PostgreSQL/pgvector, Redis semantic cache, DLP/HITL güvenlik duvarı, Supervisor-first swarm ve telemetry-first observability katmanlarını tek üründe birleştiren üretim adayı bir platformdur.

> **Arşiv Notu:** Satır satır sürüm günlüğü, kapanan teknik borç kalemleri ve ara denetim turları için `CHANGELOG.md` ve `AUDIT_REPORT_v5.0.md` dosyalarına başvurulmalıdır.

## Session: Production Secret Rotation Runbook

- Installer'ın local/dev/test kolaylığı için ortak secret'ları `.env` zincirinden profil dosyalarına senkronize ettiği davranış production riski olarak belgelendi.
- `docs/runbooks/production-secret-rotation.md` eklendi; `API_KEY`, `JWT_SECRET_KEY`, `MEMORY_ENCRYPTION_KEY`, `AUTONOMY_WEBHOOK_SECRET`, `SWARM_FEDERATION_SHARED_SECRET`, `GITHUB_WEBHOOK_SECRET`, `GRAFANA_ADMIN_PASSWORD` ve `METRICS_TOKEN` için production öncesi rotasyon checklist'i tanımlandı.
- `scripts/install_modules/phases/08_env.sh` production env dosyası local kaynakla aynı ortak secret'ları taşıdığında runbook'a yönlendiren uyarı üretir.

## Session: Web Runtime Helper Refactor

- `web_server.py` içindeki process lifecycle, autonomy text/actor helper'ları ve collaboration stream chunking mantığı `web/process_lifecycle.py`, `web/autonomy_bridge.py` ve `web/collaboration_service.py` modüllerine taşındı.
- Geriye dönük test/route uyumluluğu için `web_server.py` üzerindeki mevcut private facade fonksiyonları korundu; uygulama davranışı değişmeden helper implementasyonları modüler hale getirildi.

## Session: Agent Exception Observability

- `agent/auto_handle.py` içindeki `.heal`, audit, health ve GPU otomatik komut hata yolları kullanıcı mesajı döndürmenin yanında `logger.exception` ile stack trace üretir hale getirildi.
- `agent/sidar_agent.py` içinde docs search, autonomy trigger ve self-heal hata yolları sunucu loglarında görünür olacak şekilde güçlendirildi; mevcut kullanıcıya dönük hata mesajları korundu.

## Session: Ruff Debt Baseline Ratchet

- `scripts/ci/check_ruff_debt_baseline.py` artık yalnız borç artışını değil, ölçülen borç committed baseline'ın altına düştüğünde stale baseline durumunu da fail-closed raporlar.
- `--update` akışı committed Ruff debt baseline'ını `min(current, baseline)` değerine indirir; mevcut ölçümle E501 ve D202 baseline'ları sıkılaştırıldı.

## Session: Coverage Strict Local Ratchet Policy

- Coverage ratchet tavanı günlük local/CI profillerinde `%100` olarak sabitlendi; ölçülen tam kapsam artık `%99.x` regresyonlarını fail-closed yakalar.
- `docs/runbooks/coverage-strict-local-ratchet.md`, `%100` varsayılanını doğrulama ve yalnız kontrollü teşhis için override kullanma politikasını belgeler.


## Session: Security Directory Scope Clarification

- `security/` dizininin runtime güvenlik implementasyonu değil, `pip-audit` gibi kalite kapılarını destekleyen policy/veri alanı olduğu `security/README.md` ile açıklandı.
- Runtime güvenlik mantığı için `web/security.py`, dosya/komut/erişim seviyesi enforcement için `managers/security.py`, CI/test çıktıları için `artifacts/security/` yönlendirmeleri eklendi.


## Session: Config Facade Scope Clarification

- `config.py` geniş görünse de gerçek bir god object değil; `config_llm.py`, `config_security.py`, `config_rag_defaults.py` ve `core/config_*.py` domain modüllerini geriye dönük uyumlu tek import yüzeyinde birleştiren compatibility facade olarak belgelendi.
- İlk düşük riskli iyileştirme olarak `Config.llm_settings`, `Config.security_settings`, `Config.sandbox_settings`, `Config.observability_settings` ve benzeri typed domain settings alias'ları expose edildi; legacy class attribute yüzeyinin yeni kodda kademeli küçültülmesi hedeflendi.


## Session: Launcher Doctor Preflight Boundary

- `main.py` içindeki Doctor preflight kontrol sıralaması, database-dependent skip politikası, auto-fix tekrar limiti ve paralel RAG/GPU check orkestrasyonu `core/doctor/launcher_preflight.py` modülüne taşındı.
- `main.py` artık bu preflight için yalnız renkli çıktı, kullanıcı onayı, env reload ve auto-fix callback'lerini sağlayan compatibility facade olarak kaldı; böylece iki ayrı health-check/preflight sisteminin ıraksama riski azaltıldı.


## Session: RAG Config Naming Clarification

- Kök `config_rag.py` adı, `core/config_rag_store.py` ve `core/rag/` runtime modülleriyle karışmaması için statik varsayılanların canonical modülü olarak `config_rag_defaults.py` adına taşındı.
- Geriye dönük uyumluluk için `config_rag.py` shim olarak korundu; yeni kod ve `config.py`/`core/config_rag_store.py` importları `config_rag_defaults.py` üzerinden ilerler.


## Session: Frontend Bundle Near-Budget Warning

- Frontend bundle bütçesi kırmızı alarm seviyesinde olmasa da toplam JS/gzip kullanımının `%90+` bandına yaklaşması için `SIDAR_BUNDLE_BUDGET_WARN_RATIO` uyarı eşiği eklendi.
- Mevcut hard gate (`SIDAR_TOTAL_JS_BUDGET_KB`, `SIDAR_TOTAL_GZIP_BUDGET_KB`) korunurken, yeni uyarı mekanizması dependency eklemelerinde bütçeye yaklaşmayı fail etmeden görünür kılar.

## Session: Installer Offline Bootstrap Guard

- `--offline` / `--air-gapped` bayrakları artık `install_cli.sh` yüklenmeden önce, yalnız Bash built-in'leriyle erken algılanır; böylece fallback modül indirme bloğu CLI parse sırasını beklemez.
- Yerel `scripts/install_modules` ağacı eksikken offline modda raw GitHub modül indirme ve bootstrap clone/re-exec denenmez; kurulum release bundle veya yanında taşınan modül ağacı gerektiren açık hata ile durur.

## Session: Installer Fallback Module Cache Hygiene

- Raw fallback modül cache varsayılanı her çalıştırmada yeni `mktemp` dizini oluşturmak yerine kullanıcıya ait stabil cache yoluna taşındı; retry mesajındaki "mevcut modüller yeniden kullanılır" davranışı artık varsayılan akışla uyumlu.
- Eski otomatik `/tmp/sidar_install_modules_cache_<uid>.*` cache kökleri güvenli sahiplik ve yaş kontrolünden sonra temizlenir; böylece önceki koşumlardan kalan geçici cache dizinleri birikmez.
